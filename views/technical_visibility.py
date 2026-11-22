"""Presentation-only technical disclosure policy. No schema, sync or updater writes."""
import functools,os,re,sqlite3,threading
from pathlib import Path
PRIVILEGED=frozenset(('Admin','Super_Admin'))
FAILURE='تعذر إتمام الإجراء؛ يرجى مراجعة مسؤول النظام.'
NOTICE='يرجى مراجعة مسؤول النظام عند الحاجة.'
_lookup=threading.local()
PATTERN=re.compile(r'(?:\b(?:API|HTTPS?|SQL(?:ite)?|PostgreSQL|Traceback|\w*Exception|\w*Error|release_seq|device[ _]?id|sync_queue|erp_outbox|Runtime|Streamlit|psycopg\w*|SELECT|INSERT|CREATE TABLE|no such table)\b|[A-Za-z]:[\\/]|/opt/|__pycache__|\.py\b|التسلسل الداخلي|إيصال.{0,12}التثبيت|طابور|حزمة.{0,12}التحديث|تفاصيل المزامنة|سجلات.{0,10}الأخطاء|تشخيص|ملفات التشغيل|الخدمات الداخلية|هوية الجهاز|معرّف الجهاز|مصدر رصد الاتصال|التحديث المثبت|تحديث\s*\d+)',re.I)

def require_technical_reader(conn,user_id,claimed_role=None):
    if user_id is None:raise PermissionError('Authentication required')
    row=conn.execute('SELECT role,is_active FROM users WHERE id=?',(user_id,)).fetchone()
    if not row or str(row['is_active']).lower() not in ('1','true') or row['role'] not in PRIVILEGED or (claimed_role is not None and row['role']!=claimed_role):
        raise PermissionError('Technical details are restricted')
    return row['role']

def technical_details_allowed():
    import streamlit as st
    if not st.session_state.get('logged_in') or st.session_state.get('role') not in PRIVILEGED:return False
    if getattr(_lookup,'active',False):return False
    _lookup.active=True
    conn=None
    try:
        if os.name=='nt':
            from sherif_paths import local_db
            db=local_db()
            conn=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=2);conn.row_factory=sqlite3.Row
        else:
            from database import get_db_connection
            conn=get_db_connection()
        require_technical_reader(conn,st.session_state.get('user_id'),st.session_state.get('role'));return True
    except Exception:return False
    finally:
        if conn is not None:conn.close()
        _lookup.active=False

def technical_read(provider,*args,**kwargs):
    if not technical_details_allowed():raise PermissionError('Technical details are restricted')
    return provider(*args,**kwargs)

def is_technical(value):
    if isinstance(value,BaseException):return True
    if hasattr(value,'columns'):return any(PATTERN.search(str(c)) for c in value.columns)
    if isinstance(value,dict):return any(PATTERN.search(str(k)) for k in value)
    if isinstance(value,list) and value and isinstance(value[0],dict):return any(is_technical(row) for row in value)
    return isinstance(value,str) and bool(PATTERN.search(value))

def public_text(value,kind):
    text=str(value)
    if 'SHERIF POS' in text and re.search(r'تحديث\s*\d+',text):return 'SHERIF POS'
    if kind in ('error','warning','exception') or re.search(r'تعذر|فشل|خطأ|رفض|غير متاح|متوقف',text):return FAILURE
    if kind=='success':return 'اكتمل الإجراء بنجاح.'
    return NOTICE

def install_message_policy():
    """Redact before Streamlit serializes a response, never by CSS/browser hiding."""
    from streamlit.delta_generator import DeltaGenerator
    if getattr(DeltaGenerator,'_technical_visibility_installed',False):return
    originals={name:getattr(DeltaGenerator,name) for name in ('error','warning','info','success','caption','markdown','text','write','code','json','exception','dataframe','table')}
    def wrapper(name,original):
        @functools.wraps(original)
        def emit(self,*args,**kwargs):
            values=args or (kwargs.get('body',kwargs.get('data','')),)
            # Layout/scripts are executable UI, not diagnostic messages.
            structural=any(isinstance(v,str) and re.search(r'<(?:script|style|iframe)\b',v,re.I) for v in values)
            sensitive=name=='exception' or (not structural and any(is_technical(v) for v in values))
            if sensitive and not technical_details_allowed():
                if name in ('table','dataframe'):
                    data=values[0]
                    if hasattr(data,'columns'):
                        forbidden=[c for c in data.columns if PATTERN.search(str(c))]
                        data=data.drop(columns=forbidden)
                        keep=len(data.columns)>0
                    elif isinstance(data,list) and all(isinstance(row,dict) for row in data):
                        data=[{k:v for k,v in row.items() if not PATTERN.search(str(k))} for row in data];keep=any(data)
                    else:keep=False
                    if keep:
                        clean=dict(kwargs);clean.pop('data',None)
                        if isinstance(clean.get('column_config'),dict):clean['column_config']={k:v for k,v in clean['column_config'].items() if not PATTERN.search(str(k))}
                        return original(self,data,*args[1:],**clean)
                text=public_text(values[0],'exception' if any(isinstance(x,BaseException) for x in values) else name)
                method=originals['error'] if name=='exception' else originals['warning'] if name in ('code','json','table','dataframe') else original
                return method(self,text)
            return original(self,*args,**kwargs)
        return emit
    for name,original in originals.items():setattr(DeltaGenerator,name,wrapper(name,original))
    DeltaGenerator._technical_visibility_installed=True

def render_update_controls(role):
    """Call the existing updater unchanged; expose diagnostic reads only to admins."""
    import streamlit as st
    import central_updater as updater
    if technical_details_allowed():
        updater.show_update_status(role)
        if role=='Admin':
            with st.sidebar.expander('تفاصيل التحديث للإدارة'):
                data=technical_read(updater.status)
                for name in ('state','installed_release_seq','available_release_seq','phase','reason','idle_blocked_by'):
                    if name in data:st.caption(name+': '+str(data[name]))
        return
    if st.sidebar.button('حدّث الآن',key='central_update_action'):updater.request_update_check()
    # Only operational outcome projection; no fleet/ledger/log or manifest read.
    state=updater.status().get('state')
    if state in ('offline_or_rejected','install_failed','blocked_release','helper_required','device_required'):
        st.sidebar.warning('تعذر إكمال تحديث البرنامج؛ يرجى مراجعة المسؤول.')
    elif state=='current':st.sidebar.caption('البرنامج محدّث.')
    else:st.sidebar.caption('يمكنك متابعة العمل؛ سيكتمل التحديث عندما يكون البرنامج جاهزًا.')
