from sherif_network import server_enabled
from central_updater import start_update_service, mark_update_healthy, show_update_status
if server_enabled(): start_update_service()
from views.page_guard import guarded_page_call as _guarded_page_call
import streamlit as _page_client_errors
_page_client_errors.set_option('client.showErrorDetails','none' if isinstance(_page_client_errors.get_option('client.showErrorDetails'),str) else False)
# Compatibility for already installed launchers: same guarded close listener.
import os as _pos_host_os
if _pos_host_os.name == 'nt' and server_enabled():
    from pathlib import Path as _PosHostPath
    from central_updater import start_close_listener as _pos_start_close_listener, read_json as _pos_read_json
    import sys as _pos_host_sys
    _pos_host_root = _PosHostPath(_pos_host_sys.executable).resolve().parent if getattr(_pos_host_sys,'frozen',False) else _PosHostPath(__file__).resolve().parent
    _pos_host_address = _pos_read_json(_pos_host_root/'.updates/launcher-address.json')
    _pos_host_port = _pos_host_address.get('port',8501)
    if type(_pos_host_port) is int and 0 < _pos_host_port < 65536:_pos_start_close_listener(_pos_host_port)
from central_updater import maintenance_gate
maintenance_gate()
from branch_auth import start_device_registration_monitor
if server_enabled(): start_device_registration_monitor()
import os
import re
import json
import secrets
import hashlib
import sqlite3
import time
from pathlib import Path
import streamlit as st
from database import initialize_database, get_db_connection, get_remote_connection
from offline_store import ensure_local_schema, offline_login, sync_reference_data, sync_after_login, sync_pending_sales, sync_pending_operations, pending_count, get_local_connection
from backup_manager import daily_backup

# إعدادات الصفحة الأساسية
# يجب أن تكون أول أمر Streamlit في الملف.
st.set_page_config(
    page_title="SHERIF",
    layout="wide",
    initial_sidebar_state="expanded",
)

from views.ui_common import apply_rtl
apply_rtl()

from views.technical_visibility import install_message_policy
install_message_policy()


# ============================================================
# تهيئة PostgreSQL / Supabase مرة واحدة
# ============================================================

@st.cache_resource
def initialize_app_database():
    # Windows POS must never initialize central PostgreSQL on reruns.
    ensure_local_schema()
    return True


initialize_app_database()
if server_enabled(): mark_update_healthy()
# Local-first: do not contact the central server during application startup.
# Remote initialization/synchronization is performed only after a login attempt.


@st.cache_data(ttl=300)
def load_appearance_settings():
    """Load appearance locally; central settings are refreshed only during login sync."""
    defaults = {
        "app_bg_color": "#f8fafc", "sidebar_bg_color": "#0f172a",
        "sidebar_button_color": "#1e293b", "button_color": "#0284c7",
        "button_hover_color": "#0369a1", "text_color": "#000000",
        "font_size": "17", "font_weight": "900", "logo_data": "", "login_bg_data": "",
    }
    conn = None
    try:
        conn = get_local_connection()
        rows = conn.execute("SELECT setting_key, setting_value FROM app_settings").fetchall()
        for row in rows:
            defaults[row["setting_key"]] = row["setting_value"] or ""
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
    return defaults


appearance = load_appearance_settings()

# إضافة ستايل CSS ومؤشر الاتصال (Online/Offline) في رأس الصفحة
st.markdown("""
    <style>
    html, body, [class*="css"] { font-family: Arial, Tahoma, sans-serif !important; }
    .stApp p, .stApp label, .stApp td, .stApp th { color:#000000 !important; font-weight:700 !important; font-size:15px !important; line-height:1.55 !important; }
    [data-testid="stWidgetLabel"] p { white-space: normal !important; overflow-wrap:anywhere !important; }
    [data-testid="stSelectbox"] { margin-bottom: .35rem !important; }
    .main { background-color: #f8fafc; }
    h1 { font-size: 28px !important; color: #0f172a !important; }
    h2 { font-size: 24px !important; color: #1e293b !important; }
    h3 { font-size: 20px !important; color: #334155 !important; }
    
    div.stButton > button, div.stButton > button * { color: #ffffff !important; }
    div.stButton > button { 
        border-radius: 8px; font-weight: 900 !important; transition: all 0.3s ease; height: 50px; 
        background: linear-gradient(135deg, #0284c7, #0369a1); border: none;
        box-shadow: 0 3px 6px rgba(0,0,0,0.15); font-size: 18px !important;
    }
    div.stButton > button:hover { background: linear-gradient(135deg, #0369a1, #075985); transform: translateY(-2px); }
    
    [data-testid="stSidebar"] { background-color: #0f172a; }
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] span, [data-testid="stSidebar"] p { color: #ffffff !important; font-size: 17px !important; }
    [data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea {
        color: #111827 !important; background-color: #ffffff !important;
    }
    [data-testid="stSidebar"] [data-testid="stAlert"] p,
    [data-testid="stSidebar"] [data-testid="stAlert"] span {
        color: #111827 !important;
    }
    [data-testid="stSidebar"] .stButton>button {
        background-color: #1e293b; color: #ffffff !important; border: 1px solid #334155;
        border-radius: 10px; padding: 12px 15px; text-align: right; font-weight: 900 !important;
        transition: all 0.3s ease; margin-bottom: 8px; font-size: 17px !important; height: auto;
    }
    [data-testid="stSidebar"] .stButton>button:hover { background-color: #0284c7; color: white !important; border-color: #0284c7; transform: translateX(-5px); }
    
    div[data-testid="InputInstructions"] {
        display: none !important;
    }

    /* ========================================================
       اتجاه الواجهة العربية RTL - طبقة عرض فقط
       ======================================================== */
    html, body, .stApp {
        direction: rtl !important;
        text-align: right !important;
    }

    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"],
    [data-testid="stVerticalBlock"],
    [data-testid="stForm"],
    [data-testid="stExpander"],
    [data-testid="stAlert"] {
        direction: rtl !important;
        text-align: right !important;
    }

    [data-testid="stSidebar"] {
        direction: rtl !important;
        right: 0 !important;
        left: auto !important;
    }

    [data-testid="stSidebar"] > div,
    [data-testid="stSidebar"] button,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] p {
        direction: rtl !important;
        text-align: right !important;
    }

    .stTextInput, .stTextArea, .stNumberInput, .stSelectbox,
    .stMultiSelect, .stDateInput, .stTimeInput, .stRadio,
    .stCheckbox, .stFileUploader {
        direction: rtl !important;
        text-align: right !important;
    }

    .stTextInput input,
    .stTextArea textarea,
    .stNumberInput input,
    [data-baseweb="select"] > div {
        text-align: right !important;
    }

    [role="radiogroup"] {
        direction: rtl !important;
        justify-content: flex-start !important;
    }

    [data-testid="stDataFrame"],
    [data-testid="stTable"],
    table, thead, tbody, tr, th, td {
        direction: rtl !important;
        text-align: right !important;
    }

    input[type="number"],
    input[type="tel"],
    input[type="password"] {
        direction: ltr !important;
        text-align: right !important;
    }

    [data-testid="stSidebarCollapseButton"],
    [data-testid="collapsedControl"] {
        direction: ltr !important;
    }
    </style>


""", unsafe_allow_html=True)


# تطبيق إعدادات المظهر المحفوظة فوق التنسيق الافتراضي
_login_bg_css = ""
if appearance.get("login_bg_data") and not st.session_state.get("logged_in"):
    _login_bg_css = f"""
        background-image:
            linear-gradient(rgba(255,255,255,0.78), rgba(255,255,255,0.78)),
            url("{appearance['login_bg_data']}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    """

st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {appearance['app_bg_color']} !important;
        {_login_bg_css}
    }}
    .stApp p, .stApp label, .stApp td, .stApp th {{
        color: {appearance['text_color']} !important;
        font-weight: {appearance['font_weight']} !important;
        font-size: {appearance['font_size']}px !important;
        line-height: 1.55 !important;
    }}
    div.stButton > button {{
        background: {appearance['button_color']} !important;
        font-weight: {appearance['font_weight']} !important;
    }}
    div.stButton > button:hover {{
        background: {appearance['button_hover_color']} !important;
    }}
    [data-testid="stSidebar"] {{
        background-color: {appearance['sidebar_bg_color']} !important;
    }}
    [data-testid="stSidebar"] .stButton > button {{
        background: {appearance['sidebar_button_color']} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover {{
        background: {appearance['button_color']} !important;
    }}
    /* SHERIF cashier palette: burgundy main buttons; sidebar unchanged. */
    [data-testid="stMain"] div.stButton > button,
    [data-testid="stAppViewContainer"] section.main div.stButton > button {{
        background: #990b12 !important;
        background-color: #990b12 !important;
        color: #ffffff !important;
        border-color: #990b12 !important;
    }}
    [data-testid="stMain"] div.stButton > button:hover,
    [data-testid="stAppViewContainer"] section.main div.stButton > button:hover {{
        background: #76070d !important;
        background-color: #76070d !important;
        border-color: #76070d !important;
    }}
    </style>
    """,
    unsafe_allow_html=True
)


# Adaptive contrast for messages, captions, labels and buttons; layout is unchanged.
st.html(r"""<script>
// Message text only: retain original semantic backgrounds and all geometry.
(() => {
  const w = window, d = w.document;
  if (w.__abuzaidMessageContrast) w.__abuzaidMessageContrast.disconnect();
  const selector = '[data-testid="stAlertContainer"], [data-testid="stToast"], [data-baseweb="notification"], [data-testid="stCaptionContainer"], [data-testid="stWidgetLabel"], [data-testid="stMarkdownContainer"], [data-testid="stHeading"], button, input, textarea, [role="option"], [data-baseweb="select"]';
  const parse = value => {
    if (!value || value === 'transparent') return [0,0,0,0];
    const match = value.match(/^rgba?\(([^)]+)\)$/);
    if (!match) return [0,0,0,0];
    const parts = match[1].split(/[,\s/]+/).filter(Boolean).map(Number);
    return [parts[0],parts[1],parts[2],parts.length > 3 ? parts[3] : 1];
  };
  const background = el => {
    const layers = [];
    for (let node=el; node; node=node.parentElement) {
      const layer=parse(w.getComputedStyle(node).backgroundColor);
      layers.push(layer);
      if (layer[3] >= 1) break;
    }
    let rgb=w.matchMedia('(prefers-color-scheme: dark)').matches ? [14,17,23] : [255,255,255];
    for (let i=layers.length-1;i>=0;i--) {
      const layer=layers[i];
      rgb=rgb.map((channel,j)=>layer[j]*layer[3]+channel*(1-layer[3]));
    }
    return rgb;
  };
  const luminance = rgb => rgb.map(v=>{
    v/=255; return v<=.04045 ? v/12.92 : ((v+.055)/1.055)**2.4;
  }).reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
  const apply = () => {
    d.querySelectorAll(selector).forEach(box=>{
      const nodes=[box,...box.querySelectorAll('div,p,span,li,strong,em,b,i,a,code,pre,h1,h2,h3,h4,svg')];
      nodes.forEach(node=>{
        const lum=luminance(background(node));
        const color=(1.05/(lum+.05)) >= ((lum+.05)/.05) ? '#ffffff' : '#000000';
        // Compare computed output before writing to avoid observer feedback loops.
        const expected=color==='#ffffff' ? 'rgb(255, 255, 255)' : 'rgb(0, 0, 0)';
        if (w.getComputedStyle(node).color !== expected || node.style.getPropertyPriority('color') !== 'important') {
          node.style.setProperty('color',color,'important');
        }
        if (node.style.getPropertyValue('-webkit-text-fill-color') !== 'currentcolor') {
          node.style.setProperty('-webkit-text-fill-color','currentColor','important');
        }
      });
    });
  };
  let frame=0;
  const schedule=()=>{
    if (!frame) frame=w.requestAnimationFrame(()=>{frame=0;apply();});
  };
  const observer=new MutationObserver(schedule);
  observer.observe(d.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['class','style','data-theme']});
  w.__abuzaidMessageContrast={disconnect:()=>{observer.disconnect();if(frame)w.cancelAnimationFrame(frame);}};
  schedule();
})();
</script>""", unsafe_allow_javascript=True)

# إنشاء مجلد الصور إذا لم يكن موجوداً
if not os.path.exists("item_images"): 
    os.makedirs("item_images")

# Windows workstation assignment. Stored locally; never queued for central sync.
def _workstation_info():
    from branch_auth import local_device_info
    from offline_store import get_local_connection, get_device_id
    vals = local_device_info()
    if not server_enabled():
        from sherif_local_identity import local_identity
        c = get_local_connection(queue_writes=False)
        try:
            identity = local_identity(c)
            if identity:
                return {'branch_id': identity['branch_id'], 'branch_name': identity['branch_name'], 'device_number': vals.get('device_number','1')}
            return None
        finally: c.close()
    if vals.get('server_enrolled')!='1' or vals.get('setup_complete')!='1':
        return None
    bid = vals.get('bound_branch_id') or vals.get('branch_id')
    if (not bid or not str(bid).isdigit() or not vals.get('device_number')
            or vals.get('device_active', '1') != '1'
            or vals.get('bound_device_id') != get_device_id()):
        return None
    c = get_local_connection(queue_writes=False)
    try:
        branch = c.execute('SELECT branch_name FROM branches WHERE id=? AND is_active=1', (int(bid),)).fetchone()
        if not branch:
            return None
        return {'branch_id': int(bid), 'branch_name': branch['branch_name'], 'device_number': vals['device_number']}
    finally:
        c.close()


def _branch_access_error(user):
    device = _workstation_info()
    if not device:
        return 'هذا الجهاز لم يتم تعريفه بفرعه ورقم الجهاز بعد. راجع الإدارة العامة.'
    # Global administration can configure workstations, but cannot bypass branch
    # restrictions when acting as a branch employee.
    if user.get('role') != 'Cashier':
        return None
    try:
        user_branch = int(user.get('branch_id'))
    except (ValueError, TypeError):
        user_branch = None
    if user_branch != device['branch_id']:
        return f"هنّي روحك 😂 إحنا في فرع {device['branch_name']}"
    return None


def _setup_error_message(exc):
    message = str(exc)
    status=getattr(exc,'http_status',None)
    if isinstance(status,int) and status>=500:
        return 'خدمة السيرفر لم تُكمل الطلب ('+str(status)+'). أعد المحاولة بعد عودة الخدمة؛ البيانات محفوظة ولم يُتجاوز اعتماد Super Admin.'

    if message == 'HTTPS API returned 404' or message == 'رفض السيرفر الطلب (404): Not Found':
        return ('خدمة السيرفر الحالية لا تحتوي مسارات تجهيز الأجهزة (404). '
                'يلزم تحديث API على السيرفر قبل اعتماد الجهاز. يمكنك إعادة المحاولة أو الإلغاء؛ '
                'لن يتم تفعيل الجهاز محلياً دون اعتماد السيرفر.')
    if 'HTTPS API returned 409' in message:
        return 'رفض السيرفر طلب التسجيل (409) دون سبب مفصل؛ لم تتغير بيانات الجهاز. راجع الإدارة.'
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return ('تعذر الاتصال بخدمة HTTPS لإكمال التجهيز. تحقق من الإنترنت ثم أعد المحاولة. '
                'البيانات الموجودة محفوظة ولم يتم تجاوز اعتماد الإدارة.')
    return message


def _cancel_workstation_setup():
    from central_updater import request_program_exit
    try:request_program_exit()
    except ValueError as exc:
        st.error(str(exc));return
    from branch_auth import clear_online_credentials
    clear_online_credentials()
    token = st.context.cookies.get(_auth_cookie_name(), '')
    if token:
        with _auth_connection() as conn:
            conn.execute('DELETE FROM sessions WHERE token_hash=?', (_auth_hash(token),))
    st.session_state.clear()
    st.session_state['_setup_cancelled'] = True
    st.info('جارٍ إغلاق البرنامج بأمان؛ لن يتم إيقاف عملية نشطة.')
    st.stop()


@st.dialog('موافقة Super_Admin لإعادة تجهيز الجهاز')
def _device_recovery_login(identity):
    from branch_auth import authenticate_setup_admin, clear_online_credentials
    with st.form('device_recovery_admin',clear_on_submit=True):
        username=st.text_input('اسم مستخدم Super_Admin',key='recovery_admin_name')
        password=st.text_input('كلمة مرور Super_Admin',type='password',key='recovery_admin_password')
        accepted=st.form_submit_button('تحقق من السيرفر واستمرار')
    if accepted:
        try:
            admin=authenticate_setup_admin(username,password)
            if admin['role']!='Super_Admin':
                clear_online_credentials()
                raise ValueError('هذا الإجراء يتطلب Super_Admin فقط')
            st.session_state['device_recovery_authorized']=identity
        except Exception as exc:
            st.error(_setup_error_message(exc));return
        st.rerun()


def _workstation_setup():
    from branch_auth import (setup_branches, configure_local_device, complete_device_setup,
                             local_device_info, authenticate_setup_admin, setup_admin_user,
                             clear_online_credentials, enroll_local_identity)
    st.subheader('🖥️ تجهيز الجهاز')
    st.caption('سجّل دخول الإدارة عبر الإنترنت. التسجيل الجديد للسوبر أدمن؛ الاستبدال متاح أيضًا لـ Admin والمدير العام.')
    # Recovery controls render before any network request and remain available on every failure.
    if st.button('إلغاء التجهيز والخروج من البرنامج', key='setup_cancel'):
        _cancel_workstation_setup()
        return
    if st.button('إعادة المحاولة', key='setup_retry'):
        st.rerun()
        return
    if st.button('تغيير حساب الإدارة / العودة لتسجيل الدخول', key='setup_change_admin'):
        clear_online_credentials()
        st.rerun()
        return
    admin = setup_admin_user()
    if not admin:
        st.info('يلزم تسجيل دخول الإدارة أونلاين؛ الجلسة المحفوظة لا تكفي لاعتماد الجهاز.')
        with st.form('setup_admin_login', clear_on_submit=True):
            username = st.text_input('اسم مستخدم الإدارة', key='setup_admin_username')
            password = st.text_input('كلمة مرور Super Admin', type='password', key='setup_admin_password')
            login = st.form_submit_button('تسجيل دخول الإدارة عبر الإنترنت')
        if login:
            try:
                authenticate_setup_admin(username, password)
            except Exception as exc:
                st.error(_setup_error_message(exc))
                return
            st.rerun()
        return
    st.info('تمت مصادقة الإدارة عبر الإنترنت: ' + str(admin['username']))
    try:
        branches = setup_branches()
    except Exception as exc:
        st.error(_setup_error_message(exc))
        return
    choices = {str(b['branch_name']) + ' (#' + str(b['id']) + ')': b for b in branches}
    from offline_store import get_device_id
    from branch_auth import admin_device_registry,acknowledge_pending_device_change
    identity=get_device_id()
    st.caption('الهوية الداخلية لهذا الجهاز — لا تتغير عند إعادة المحاولة')
    st.code(identity,language=None)
    try:
        registry=admin_device_registry()
    except Exception as exc:
        st.error(_setup_error_message(exc));return
    from offline_store import get_local_connection
    recovery_conn=get_local_connection(queue_writes=False)
    try:
        resume_row=recovery_conn.execute("SELECT value FROM local_meta WHERE key='device_reconfigure_intent'").fetchone()
        resume_data=json.loads(resume_row[0]) if resume_row else {}
        if not resume_data.get('recovery'):
            resume_row=recovery_conn.execute("SELECT value FROM local_meta WHERE key='device_recovery_download_pending'").fetchone()
            resume_data=json.loads(resume_row[0]) if resume_row else {}
    finally:recovery_conn.close()
    existing_device=next((d for d in (registry.get('devices',[])+registry.get('historical_devices',[])) if d['device_id']==identity),None)
    recovering=bool(existing_device)
    recovery=None
    recovery_mode=None
    if recovering:
        if st.session_state.get('device_recovery_authorized')!=identity:
            state='غير نشطة' if not existing_device['is_active'] else 'نشطة'
            st.warning('هذا الجهاز مسجل سابقًا على النظام، وحالته الحالية '+state+'. هل تريد الاستمرار في إعادة تفعيله أو تسجيله على فرع آخر؟ تتطلب العملية موافقة السوبر أدمن')
            yes,no=st.columns(2)
            if yes.button('استمرار',key='device_recovery_continue'):
                _device_recovery_login(identity)
            if no.button('إلغاء',key='device_recovery_cancel'):
                st.session_state.pop('device_recovery_authorized',None)
                st.info('أُلغي الإجراء؛ لم يتغير تسجيل الجهاز أو بياناته')
            return
        if admin['role']!='Super_Admin':
            st.session_state.pop('device_recovery_authorized',None)
            st.error('يلزم تحقق جديد من Super_Admin');return
        if resume_data.get('recovery'):
            recovery=dict(resume_data['recovery'])
            branches=[b for b in branches if int(b['id'])==int(resume_data['branch_id'])]
            choices={str(b['branch_name'])+' (#'+str(b['id'])+')':b for b in branches}
            st.info('استكمال إجراء التسجيل المحفوظ وتنزيل بيانات الفرع؛ لن يُنشأ إجراء نقل آخر')
        else:
            recovery_mode=st.radio('إجراء تسجيل الجهاز',('reactivate','move','register'),
                format_func=lambda x:{'reactivate':'إعادة تفعيل الجهاز في فرعه السابق','move':'نقل تسجيل الجهاز إلى فرع آخر','register':'تسجيل الجهاز لفرع جديد'}[x],key='device_recovery_mode')
            if recovery_mode=='register':
                with st.expander('إنشاء فرع جديد وفق الصلاحيات الحالية'):
                    with st.form('recovery_create_branch',clear_on_submit=True):
                        new_name=st.text_input('اسم الفرع الجديد',max_chars=160)
                        new_kind=st.selectbox('نوع الفرع',('فرع','مخزن'))
                        create_branch=st.form_submit_button('إنشاء الفرع على السيرفر')
                    if create_branch:
                        try:
                            from branch_auth import _request,_LAST_TOKEN
                            _request('/admin/branches',{'name':new_name,'kind':new_kind},_LAST_TOKEN)
                            st.success('تم إنشاء الفرع؛ اختره من القائمة');st.rerun()
                        except Exception as exc:st.error(_setup_error_message(exc))
            if recovery_mode=='reactivate':
                branches=[b for b in branches if int(b['id'])==int(existing_device['branch_id'])]
            elif recovery_mode=='move':
                branches=[b for b in branches if int(b['id'])!=int(existing_device['branch_id'])]
            choices={str(b['branch_name'])+' (#'+str(b['id'])+')':b for b in branches}
            import uuid
            rid=st.session_state.setdefault('device_recovery_request:'+identity+':'+recovery_mode,str(uuid.uuid4()))
            recovery={'recovery_mode':recovery_mode,'recovery_id':rid,
                'recovery_from_branch':int(existing_device['branch_id']),
                'recovery_from_number':str(existing_device['device_number']),
                'recovery_from_active':bool(existing_device['is_active'])}
    from branch_auth import apply_local_device_action
    from offline_store import get_local_connection
    lifecycle=next((a for a in registry.get('actions',[]) if a['device_id']==identity and a['status']=='pending'),None)
    c=get_local_connection(queue_writes=False)
    try:
        intent=c.execute("SELECT value FROM local_meta WHERE key='device_lifecycle_intent'").fetchone()
        if intent:lifecycle=json.loads(intent[0])
    finally:c.close()
    if lifecycle and recovery and lifecycle['action']=='retire':
        st.info('اعتماد إعادة التسجيل سيحل محل طلب إلغاء التسجيل القديم بعد التحقق من سلامة المعاملات.')
        lifecycle=None
    if lifecycle:
        label='إعادة التهيئة' if lifecycle['action']=='reinitialize' else 'إلغاء التسجيل'
        st.warning('يوجد طلب '+label+' لهذا الجهاز. لن تُحذف الفواتير؛ يلزم انتهاء المزامنة وحفظ السلة أولًا.')
        confirmed_action=st.checkbox('أوافق على تطبيق '+label+' على هذا الجهاز فقط',key='device_lifecycle_confirm')
        if st.button('تنفيذ '+label+' بأمان',key='device_lifecycle_apply'):
            if not confirmed_action:st.error('يلزم تأكيد الإجراء')
            else:
                try:
                    apply_local_device_action(lifecycle)
                    st.success('تم تطبيق '+label+' وحفظ السجل السابق. أعد فتح البرنامج بعد الإغلاق الآمن.')
                    _cancel_workstation_setup()
                except Exception as exc:st.error(_setup_error_message(exc))
        return
    pending=next((row for row in registry.get('changes',[]) if row['device_id']==identity and row['status'] in ('pending','awaiting_local_confirmation')),None)
    if recovering and pending:
        branches=[b for b in branches if int(b['id'])==int(pending['to_branch_id'])]
        choices={str(b['branch_name'])+' (#'+str(b['id'])+')':b for b in branches}
        st.info('سيُستكمل طلب نقل هذا الجهاز إلى نفس الهدف بعد التحقق من معاملاته.')
    if pending:st.info('يوجد طلب تعديل محفوظ لهذا الجهاز. راجع الفرع والرقم والاسم ثم اعتمده أدناه.')
    if not choices:
        st.warning('لا توجد فروع نشطة؛ أضف الفرع من الإدارة المركزية ثم اضغط إعادة المحاولة.')
        return
    current = local_device_info()
    try:
        current_number = max(1, min(999999999, int(current.get('device_number') or 1)))
    except (ValueError, TypeError):
        current_number = 1
    with st.form('workstation_assignment'):
        preferred=int(pending['to_branch_id']) if pending else int(current.get('bound_branch_id') or current.get('branch_id') or next(iter(choices.values()))['id'])
        labels=list(choices)
        index=next((i for i,label in enumerate(labels) if int(choices[label]['id'])==preferred),0)
        label = st.selectbox('اسم الفرع الموجود فيه هذا الجهاز', labels,index=index)
        name=st.text_input('اسم الجهاز',value=pending['device_name'] if pending else current.get('device_name') or 'جهاز '+str(current_number),max_chars=80)
        if pending:current_number=int(pending['to_device_number'])
        number = st.number_input('رقم الجهاز داخل الفرع', min_value=1, max_value=999999999,
                                 value=int(resume_data['device_number']) if resume_data.get('recovery') else current_number, step=1,disabled=bool(resume_data.get('recovery')))
        confirmed = st.checkbox('أؤكد أن هذا الجهاز موجود في الفرع المختار')
        apply_pending=st.checkbox('أوافق على تطبيق طلب تعديل التسجيل المحفوظ لهذا الجهاز') if pending else False
        save = st.form_submit_button('💾 اعتماد الجهاز وتنزيل بيانات الفرع')
    registered=[row for row in registry.get('devices',[]) if int(row['branch_id'])==int(choices[label]['id'])]
    if registered:
        st.dataframe([{'الرقم':row['device_number'],'الهوية':row['device_id'],'هذا الجهاز':row['device_id']==identity,'نشط':row['is_active']} for row in registered],hide_index=True,use_container_width=True)
    replacement=next((row for row in registry.get('replacements',[]) if row['new_device_id']==identity and int(row['branch_id'])==int(choices[label]['id']) and str(row['device_number'])==str(int(number))),None)
    conflicts=[row for row in registered if row['is_active'] and str(row['device_number']).lstrip('0')==str(int(number)) and row['device_id']!=identity]
    if conflicts:
        occupied=conflicts[0]
        st.warning('هذا الفرع ورقم الجهاز مسجلان لكمبيوتر سابق. يمكن للسوبر أدمن اعتماد الكمبيوتر الحالي بديلًا للجهاز التالف دون تغيير الرقم.')
        if len(conflicts)!=1:
            st.error('يوجد أكثر من تسجيل نشط للرقم نفسه؛ يلزم مراجعة الإدارة.')
        elif recovering:
            st.error('رقم الجهاز مستخدم لهوية أخرى؛ اختر رقمًا غير مستخدم. الاستعادة لا تُلغي أي جهاز آخر.')
        elif admin['role']=='Super_Admin' and not replacement:
            with st.form('setup_device_replacement'):
                st.error('تحذير: لن تُسترد أي فواتير أو عمليات لم تصل إلى السيرفر من الكمبيوتر التالف. ستُسجل كغير مستردة وتحتاج تسوية منفصلة إذا استُعيد القرص. سيُمنع الجهاز السابق من إرسال عمليات جديدة بعد نجاح الاستبدال.')
                replace_submit=st.form_submit_button('تأكيد استبدال الجهاز التالف وتنزيل بيانات الفرع')
            if replace_submit:
                if admin['role']=='Super_Admin':
                    try:
                        from branch_auth import admin_replace_damaged_device
                        replacement=admin_replace_damaged_device(choices[label]['id'],number,identity,True,True)
                        configure_local_device(choices[label]['id'],name,number,replacement_command_id=replacement['command_id'])
                        complete_device_setup()
                        enroll_local_identity(admin)
                        st.success('تم اعتماد البديل وتنزيل البيانات المؤكدة. المعاملات غير المستردة محفوظة بسجل الاستبدال للمراجعة.')
                        st.session_state.update(logged_in=False,page='🏠 الرئيسية واللوحة')
                        st.rerun()
                    except Exception as error:st.error(_setup_error_message(error))
    if replacement:
        st.info('تفويض الاستبدال محفوظ؛ اضغط اعتماد الجهاز وتنزيل بيانات الفرع لاستكمال أي تنزيل انقطع. لا تُكرر الفواتير المؤكدة.')
    if save:
        if conflicts and (recovering or not replacement):
            st.info('التسجيل السابق معروف تلقائيًا؛ اضغط تأكيد استبدال الجهاز التالف أعلاه لإكمال الاعتماد بنفس الرقم.')
            return
        if not confirmed and not replacement:
            st.error('يرجى تأكيد الفرع أولًا.')
            return
        try:
            # Recheck the online setup grant immediately before the registration request.
            if not setup_admin_user():
                raise ValueError('انتهت مصادقة الإدارة؛ أعد تسجيل الدخول عبر الإنترنت.')
            branch = choices[label]
            if admin['role']!='Super_Admin' and not replacement:raise ValueError('صلاحيتك تسمح باستبدال جهاز معتمد؛ التسجيل الجديد دون استبدال يتطلب Super Admin')
            if pending and not apply_pending:raise ValueError('يلزم تأكيد تطبيق طلب تعديل الجهاز المحفوظ')
            with st.status('جارٍ تأمين السجل السابق واعتماد الجهاز من السيرفر',expanded=True) as progress:
                configure_local_device(branch['id'],name,number,command_id=pending['command_id'] if pending and not recovery else None,replacement_command_id=replacement['command_id'] if replacement and not recovery else None,recovery=recovery)
                st.write('اعتمد السيرفر التسجيل؛ جارٍ تنزيل بيانات الفرع المعتمد')
                complete_device_setup()
                from central_updater import version_info
                APP_VERSION=version_info().get('version','1.0.0')
                st.write('الفرع: '+str(branch['branch_name'])+' — الجهاز: '+str(number)+' — الإصدار: '+str(APP_VERSION))
                progress.update(label='اكتمل تجهيز الجهاز وتنزيل بيانات الفرع',state='complete')
            st.session_state.pop('device_recovery_authorized',None)
            st.session_state.pop('device_recovery_request',None)
            enroll_local_identity(admin)
            try:acknowledge_pending_device_change()
            except Exception:st.warning('حُفظ التسجيل محليًا؛ إيصال تطبيق التعديل ينتظر الاتصال القادم.')
        except Exception as exc:
            st.error('لم يكتمل تجهيز الجهاز: ' + _setup_error_message(exc))
            return
        if recovery:st.session_state.clear()
        st.session_state.update(_auth_release_seq=_current_auth_release(),logged_in=True, username=admin['username'], role=admin['role'],
                                user_id=admin['id'], branch_id=admin.get('branch_id'),
                                connection_mode='online', page='🏠 الرئيسية واللوحة',
                                _reference_sync_done_this_login=True)
        # Drop setup authority, while retaining the authenticated online session.
        from branch_auth import finish_setup_authentication
        finish_setup_authentication()
        from auto_sync import request_sync
        request_sync('admin_login')
        st.success('تم اعتماد الجهاز وتجهيز الفرع. يمكنك تسجيل الخروج والدخول بحساب الكاشير.')
        st.rerun()




# F5 persistence: opaque browser cookie, server-side revocable session.
# Requires Streamlit 1.65+ for st.html(unsafe_allow_javascript=True).
from sherif_paths import session_db
_AUTH_DB = session_db()
_AUTH_COOKIE = "abuzaid_session"
_AUTH_LIFETIME = 8 * 60 * 60


def _auth_connection():
    conn = sqlite3.connect(str(_AUTH_DB), timeout=10)
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, role TEXT NOT NULL, user_id TEXT NOT NULL, branch_id TEXT, connection_mode TEXT NOT NULL, expires_at INTEGER NOT NULL)")
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (int(time.time()),))
    conn.commit()
    return conn





@st.cache_resource(show_spinner=False)
def _auth_window_component():
    from streamlit.components.v2 import component
    return component('abuzaid_login_window_v1',js=r"""
    export default function(component) {
      const { setStateValue } = component;
      try {
        const slot = '__abuzaidLoginWindowV1';
        if (!window[slot]) {
          const key = 'abuzaid_login_window_v1';
          const kind = performance.getEntriesByType('navigation')[0]?.type;
          let identity = sessionStorage.getItem(key);
          // Refresh keeps this tab. A fresh/reopened navigation gets a new identity,
          // including a restored tab whose sessionStorage was restored by the browser.
          if (kind !== 'reload' || !/^[0-9a-f]{64}$/.test(identity || '')) {
            const bytes = crypto.getRandomValues(new Uint8Array(32));
            identity = Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
            sessionStorage.setItem(key,identity);
          }
          window[slot] = identity;
        }
        setStateValue('identity',window[slot]);
      } catch (_) {
        setStateValue('identity','unavailable');
      }
    }
    """)


def _ensure_auth_window_context():
    """Obtain a browser-window identity before restoring any authenticated view.

    No password or bearer token is put into sessionStorage or URL parameters.
    The component disappears after the initial handshake; existing layout is kept.
    """
    if os.name=='nt':
        from central_updater import observe_browser_window
        observe_browser_window()
    identity=st.session_state.get('_auth_window_id','')
    if re.fullmatch(r'[0-9a-f]{64}',str(identity)):
        return True
    if st.session_state.get('_auth_window_unavailable'):
        return False
    try:
        result=_auth_window_component()(key='abuzaid_window_identity',height=0,
            default={'identity':None},on_identity_change=lambda:None)
        identity=result.identity
    except (ImportError,AttributeError,TypeError):
        # Unsupported browser/runtime: allow manual login, never restore a cookie.
        st.session_state['_auth_window_unavailable']=True
        return False
    if identity=='unavailable':
        st.session_state['_auth_window_unavailable']=True
        return False
    if isinstance(identity,str) and re.fullmatch(r'[0-9a-f]{64}',identity):
        st.session_state['_auth_window_id']=identity
        st.rerun()
    st.stop()


def _auth_cookie_name():
    identity=str(st.session_state.get('_auth_window_id',''))
    return _AUTH_COOKIE+'_'+identity if re.fullmatch(r'[0-9a-f]{64}',identity) else _AUTH_COOKIE


@st.cache_resource(show_spinner=False)
def _auth_runtime_key():
    # A real application-process restart requires employee login again.
    return secrets.token_hex(32)


def _current_auth_release():
    from release_info import installed_release, installed_source_release
    root=Path(__file__).resolve().parent
    release=installed_release(root,'windows') if os.name=='nt' else installed_source_release(root)
    return release['release_seq']


def _auth_hash(token):
    # Same existing sessions table; old unbound cookies are not trusted on upgrade.
    window_id=str(st.session_state.get('_auth_window_id',''))
    release=_current_auth_release()
    return hashlib.sha256(('abuzaid-window-v2:'+str(release)+':'+_auth_runtime_key()+':'+window_id+':'+token).encode('ascii')).hexdigest()


def _browser_cookie_script(token=None, delete=False, cookie_name=None):
    # The cookie is an opaque bearer token, never a username/password.
    cookie_name=cookie_name or _auth_cookie_name()
    if delete:
        js = f"document.cookie={json.dumps(cookie_name + '=; Path=/; Max-Age=0; SameSite=Lax')};"
    else:
        js = f"document.cookie={json.dumps(cookie_name + '=' + token + '; Path=/; Max-Age=' + str(_AUTH_LIFETIME) + '; SameSite=Lax')};"
    reload_target = 'window.parent' if os.name == 'nt' else 'window'
    st.html("<script>" + js + reload_target + ".location.reload();</script>", unsafe_allow_javascript=True)
    st.info("جارٍ تحديث جلسة الدخول...")
    st.stop()


def _remember_login():
    # Cloud test sessions stay in Streamlit state; do not reload the embedded page.
    if os.name != 'nt':
        st.rerun()
    if not re.fullmatch(r'[0-9a-f]{64}',str(st.session_state.get('_auth_window_id',''))):
        st.rerun()  # Session-only fallback; no unsafe persistent restore.
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + _AUTH_LIFETIME
    with _auth_connection() as conn:
        conn.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?)", (
            _auth_hash(token), str(st.session_state['username']),
            str(st.session_state['role']), str(st.session_state['user_id']),
            None if st.session_state.get('branch_id') is None else str(st.session_state['branch_id']),
            st.session_state.get('connection_mode', 'online'), expires))
    _browser_cookie_script(token)


def _restore_login():
    if not re.fullmatch(r'[0-9a-f]{64}',str(st.session_state.get('_auth_window_id',''))):
        return
    token = st.context.cookies.get(_auth_cookie_name(), '')
    if not token or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', token):
        return
    with _auth_connection() as conn:
        row = conn.execute("SELECT username, role, user_id, branch_id, connection_mode FROM sessions WHERE token_hash=? AND expires_at>?", (_auth_hash(token), int(time.time()))).fetchone()
    if not row:
        return
    username, role, user_id, branch_id, mode = row
    # An opaque browser session cannot restore an API token lost on process exit.
    from offline_store import API_TOKEN
    if not API_TOKEN:
        mode = 'offline'
    # Validate current account status and permissions, not only cached session claims.
    try:
        from offline_store import get_local_connection
        db = get_local_connection()
        try:
            user = db.execute("SELECT * FROM users WHERE id=? AND username=? AND is_active=1", (int(user_id), username)).fetchone()
        finally:
            db.close()
    except Exception:
        return
    if not user:
        return
    st.session_state.update(_auth_release_seq=_current_auth_release(),logged_in=True, username=user['username'], role=user['role'],
        user_id=user['id'], branch_id=user['branch_id'], connection_mode=mode,
        page=("🛒 نقطة البيع (POS)" if user["role"] == "Cashier" else "🔎 استعلام الأصناف" if user["role"] == "استعلام فقط" else st.session_state.get("page", "🏠 الرئيسية واللوحة")),
        _reference_sync_done_this_login=False)


def _forget_login():
    from views.pos_policy import clear_memory
    clear_memory(st.session_state)
    from central_updater import request_logout_update_check
    request_logout_update_check()
    cookie_name=_auth_cookie_name()
    token = st.context.cookies.get(_auth_cookie_name(), '')
    if token:
        with _auth_connection() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (_auth_hash(token),))
    from branch_auth import clear_online_credentials
    from offline_store import API_TOKEN as _logout_sync_token
    clear_online_credentials()
    # One bounded attempt with the already-issued token; no password survives logout.
    if _logout_sync_token:
        try:
            from auto_sync import request_sync
            request_sync('logout', token=_logout_sync_token)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Could not schedule logout sync; local queue retained')
    st.session_state.clear()
    _browser_cookie_script(delete=True,cookie_name=cookie_name)


# Explicit administrative close uses the same revocable logout as the sidebar.
st.session_state['_logout_handler']=_forget_login
def _logout_after_update_when_safe():
    if not st.session_state.get('logged_in') or st.session_state.get('_auth_release_seq')==_current_auth_release():return
    pending=bool(st.session_state.get('cart')) or any(bool(value) for key,value in st.session_state.items()
        if isinstance(key,str) and (key.endswith('_pending_action') or key in ('_operation_success','_financial_operation_active','_sale_save_in_progress')))
    if pending:
        st.info('اكتمل تحديث البرنامج؛ أكمل العملية الحالية أو ألغها قبل العودة إلى تسجيل الدخول.')
        return
    _forget_login()

_logout_after_update_when_safe()

# تهيئة متغيرات الجلسة (Session State)
if os.name == 'nt':
    from auto_sync import start_command_polling
    start_command_polling()
    from offline_store import get_local_connection
    _command_conn=get_local_connection(queue_writes=False)
    try:
        _command_relogin=_command_conn.execute("SELECT value FROM local_meta WHERE key='device_command_relogin_required'").fetchone()
        if (_command_relogin and st.session_state.get('logged_in') and not st.session_state.get('cart')):
            _forget_login()
            _command_conn.execute("DELETE FROM local_meta WHERE key='device_command_relogin_required'");_command_conn.commit()
    finally:_command_conn.close()

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "username" not in st.session_state: st.session_state["username"] = ""
if "role" not in st.session_state: st.session_state["role"] = ""
if "user_id" not in st.session_state: st.session_state["user_id"] = None
if "branch_id" not in st.session_state: st.session_state["branch_id"] = None
if "cart" not in st.session_state: st.session_state["cart"] = []
if "page" not in st.session_state: st.session_state["page"] = "🏠 الرئيسية واللوحة"
if "success_alert_msg" not in st.session_state: st.session_state["success_alert_msg"] = ""
if st.session_state.get('_setup_cancelled'):
    st.info('تم إغلاق البرنامج؛ يمكنك إغلاق النافذة.')
    st.stop()

_ensure_auth_window_context()
if not st.session_state["logged_in"]:
    _restore_login()

def set_page(page_name, remember=True):
    if st.session_state.get("role") == "Cashier" and page_name not in ("🛒 نقطة البيع (POS)","🤖 المساعد الذكي AI"):
        page_name = "🛒 نقطة البيع (POS)"
    current = st.session_state.get("page", "🏠 الرئيسية واللوحة")
    if remember and current != page_name:
        history = st.session_state.setdefault("_nav_history", [])
        # Keep a short, useful back-stack and avoid duplicate consecutive entries.
        context=st.session_state.get('_nav_rendered_context',{})
        entry={'page':current,'state':dict(context.get('state',{})) if context.get('page')==current else {}}
        previous=history[-1].get('page') if history and isinstance(history[-1],dict) else history[-1] if history else None
        if previous != current:
            history.append(entry)
        st.session_state["_nav_history"] = history[-30:]
    st.session_state["page"] = page_name
    st.rerun()

def check_user_permission(menu_name):
    if menu_name=='🛒 نقطة البيع (POS)':return True
    role = st.session_state.get("role", "")
    # الفئات الرسمية: Super_Admin > Admin > Manager > Supervisor > Cashier.
    # الأسماء القديمة مدعومة مؤقتاً حتى لا تتعطل الحسابات الموجودة قبل الترقية.
    if role == "استعلام فقط":
        return menu_name == "🔎 استعلام الأصناف"
    if role == "Super_Admin":
        return True
    if menu_name == "__WORKSTATION_SETUP__":
        return role in ("Super_Admin","Admin","Manager")
    if menu_name == "🧹 تهيئة النظام لأول تشغيل":
        return role == "Super_Admin"
    if menu_name == "🎨 تخصيص المظهر":
        return role in ["Super_Admin", "Admin", "Manager", "General_Supervisor"]
    if role == "Admin": return True
    if role in ["Manager", "General_Supervisor"]: return True
    if role in ["Supervisor", "Branch_Supervisor"]: return menu_name in ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)", "📦 إدارة المخزن والفروع", "📊 التقارير والأرباح"]
    if role == "Cashier": return menu_name in ("🛒 نقطة البيع (POS)","🤖 المساعد الذكي AI")
    return False

# --- بوابة الدخول: تصميم SHERIF لنسخة Windows (بدون تغيير المصادقة) ---
# A fresh or partially prepared device always owns an online-only setup login.
if not _workstation_info():
    if not server_enabled():
        c=get_local_connection(queue_writes=False)
        try: fresh=not c.execute('SELECT 1 FROM users LIMIT 1').fetchone() and not c.execute('SELECT 1 FROM branches LIMIT 1').fetchone()
        finally: c.close()
        if fresh:
            from views.local_first_setup import show_local_first_setup
            show_local_first_setup()
        else: st.error('هوية الجهاز المحلي غير صالحة؛ لم تتغير بيانات الجهاز.')
    else: _workstation_setup()
    st.stop()

if not st.session_state["logged_in"]:
    st.markdown('<div dir="ltr" style="text-align:center;font-family:Arial,sans-serif;font-size:16px;font-weight:600;line-height:1.6;padding:6px 14px;margin:4px auto 10px;width:fit-content;max-width:95%;color:#f8fafc;background:rgba(15,23,42,.82);border-radius:8px">Developed by Eng. Sherif Farouk | 0931050639</div>', unsafe_allow_html=True)
    import base64
    import sys
    _login_resources = [Path(__file__).resolve().parent]
    if getattr(sys, '_MEIPASS', None):
        _login_resources.append(Path(sys._MEIPASS))
    _login_image = next((root / 'login_background.jpg' for root in _login_resources
                         if (root / 'login_background.jpg').is_file()), None)
    if _login_image is not None:
        _login_image_b64 = base64.b64encode(_login_image.read_bytes()).decode("ascii")
        st.markdown(f"""
        <style>
        [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
        [data-testid="stHeader"], [data-testid="stToolbar"] {{display:none !important;}}
        .stApp {{background: #150b05 url('data:image/jpeg;base64,{_login_image_b64}') center center / cover no-repeat fixed !important;}}
        [data-testid="stMainBlockContainer"] {{padding:0 !important; max-width:100% !important;}}
        [data-testid="stForm"] {{
            position:fixed !important; z-index:20 !important;
            top:43.5vh !important; right:6.7vw !important;
            width:33vw !important; max-width:480px !important; min-width:310px !important;
            padding:12px 32px 18px !important;
            background:linear-gradient(135deg,#1a100a 0%,#160b06 100%) !important;
            border:1px solid #a77735 !important; border-radius:18px !important;
            box-shadow:0 8px 22px rgba(0,0,0,.5) !important;
        }}
        [data-testid="stForm"] [data-testid="stTextInput"] {{margin:0 0 3px !important;}}
        [data-testid="stForm"] [data-testid="stTextInput"] input {{
            background:#20150d !important; border:1px solid #76522d !important;
            border-radius:20px !important; color:#f9dfb1 !important;
            height:43px !important; text-align:right !important;
        }}
        [data-testid="stForm"] input::placeholder {{color:#bba17e !important; opacity:1 !important;}}
        [data-testid="stForm"] [data-testid="stFormSubmitButton"] button {{
            background:linear-gradient(110deg,#bd7827,#f1be66,#c48730) !important;
            color:#211307 !important; border:0 !important; border-radius:22px !important;
            height:44px !important; font-weight:900 !important; width:100% !important;
        }}
        [data-testid="stForm"] [data-testid="stFormSubmitButton"] button * {{color:#211307 !important;}}
        @media(max-width:900px) {{
            .stApp {{background-position:38% center !important;}}
            [data-testid="stForm"] {{right:4vw !important; width:44vw !important;
                min-width:280px !important; padding:10px 16px !important;}}
        }}
        @media(max-width:650px) {{
            .stApp {{background-position:38% center !important;}}
            [data-testid="stForm"] {{right:5vw !important; width:90vw !important;
                min-width:0 !important; top:43vh !important; padding:12px 18px !important;}}
        }}
/* Align the existing real fields with the single card painted in the original image. */
.stApp {{
 --login-pixel:max(calc(100vw / 1280),calc(100vh / 719));
 --login-bg-left:calc((100vw - 1280 * var(--login-pixel)) / 2);
 --login-bg-top:calc((100vh - 719 * var(--login-pixel)) / 2);
}}
[data-testid="stForm"] {{
 position:fixed !important; z-index:20 !important;
 left:calc(var(--login-bg-left) + 821 * var(--login-pixel)) !important;
 top:calc(var(--login-bg-top) + 324 * var(--login-pixel)) !important;
 right:auto !important; bottom:auto !important;
 width:calc(327 * var(--login-pixel)) !important; min-width:0 !important; max-width:none !important;
 height:auto !important; min-height:0 !important; padding:0 !important;
 background:transparent !important; border:0 !important; border-radius:0 !important; box-shadow:none !important;
}}
[data-testid="stForm"] > [data-testid="stVerticalBlock"] {{
 display:grid !important; height:auto !important; min-height:0 !important; flex:none !important;
 grid-template-rows:calc(48 * var(--login-pixel)) calc(11 * var(--login-pixel)) calc(48 * var(--login-pixel)) calc(20 * var(--login-pixel)) calc(44 * var(--login-pixel)) auto !important;
 gap:0 !important; grid-template-columns:minmax(0,1fr) !important; align-items:stretch !important; justify-items:stretch !important;
}}
[data-testid="stForm"] > [data-testid="stVerticalBlock"] > :nth-child(1) {{grid-row:1 !important;}}
[data-testid="stForm"] > [data-testid="stVerticalBlock"] > :nth-child(2) {{grid-row:3 !important;}}
[data-testid="stForm"] > [data-testid="stVerticalBlock"] > :nth-child(3) {{grid-row:5 !important;}}
[data-testid="stForm"] > [data-testid="stVerticalBlock"] > :nth-child(n+4) {{margin-top:12px !important;}}
[data-testid="stForm"] [data-testid="stTextInput"] {{margin:0 !important; height:100% !important;}}
[data-testid="stForm"] [data-baseweb="input"], [data-testid="stForm"] input {{
 height:calc(48 * var(--login-pixel)) !important; min-height:0 !important;
 font-size:clamp(12px,calc(15 * var(--login-pixel)),24px) !important;
}}
[data-testid="stForm"] [data-testid="stFormSubmitButton"], [data-testid="stForm"] [data-testid="stFormSubmitButton"] button {{
 height:calc(44 * var(--login-pixel)) !important; min-height:0 !important;
 font-size:clamp(13px,calc(18 * var(--login-pixel)),26px) !important;
}}
[data-testid="stForm"] [data-testid="stFormSubmitButton"] button * {{font-size:inherit !important;}}
@media(max-width:900px) {{
 .stApp {{background-position:right center !important; --login-bg-left:calc(100vw - 1280 * var(--login-pixel));}}
}}

[data-testid="stForm"] > [data-testid="stVerticalBlock"] > * {{width:100% !important; min-width:0 !important; max-width:100% !important;}}
[data-testid="stForm"] [data-testid="stTextInputRootElement"], [data-testid="stForm"] [data-testid="stTextInput"] > div {{height:100% !important; min-height:0 !important;}}
[data-testid="stForm"] [data-testid="stTextInput"] input {{height:100% !important; min-height:0 !important;}}

        </style>
        """, unsafe_allow_html=True)

    _device_before_login = _workstation_info()
    if _device_before_login:
        st.caption(f"🏢 {_device_before_login['branch_name']} — جهاز رقم {_device_before_login['device_number']}")
    else:
        st.warning('الجهاز غير معرّف: سجل دخول السوبر أدمن لتحديد الفرع ورقم الجهاز قبل استخدام البرنامج.')

    # Keyboard-only login: focus username, Enter -> password, Enter -> submit.
    # Use the real Streamlit form so the existing authentication logic stays intact.
    st.html(r"""
    <script>
    (() => {
      try {
        const win = window.parent;
        const doc = win.document;
        if (win.__abuZaidLoginKeyboardCleanup) win.__abuZaidLoginKeyboardCleanup();
        let observer;
        let focusTimer;
        let focusedOnce = false;
        const getInputs = () => {
          const form = Array.from(doc.querySelectorAll('[data-testid="stForm"]'))
            .find(f => f.querySelector('input[type="password"]'));
          if (!form) return null;
          const username = form.querySelector('input:not([type="password"]):not([type="hidden"])');
          const password = form.querySelector('input[type="password"]');
          const submit = form.querySelector('[data-testid="stFormSubmitButton"] button');
          return username && password && submit ? { username, password, submit } : null;
        };
        const focusUsername = () => {
          if (focusedOnce) return;
          const fields = getInputs();
          if (!fields) return;
          // Don't steal focus after the user has already started typing.
          const active = doc.activeElement;
          if (active && active.tagName === 'INPUT' && active !== fields.username) return;
          fields.username.focus();
          focusedOnce = true;
          if (observer) observer.disconnect();
          clearTimeout(focusTimer);
        };
        const onKeyDown = (event) => {
          if (event.key !== 'Enter' || event.isComposing || event.repeat) return;
          const fields = getInputs();
          if (!fields) return;
          if (event.target === fields.username) {
            event.preventDefault();
            event.stopImmediatePropagation();
            fields.password.focus();
          } else if (event.target === fields.password) {
            event.preventDefault();
            event.stopImmediatePropagation();
            fields.submit.click();
          }
        };
        doc.addEventListener('keydown', onKeyDown, true);
        observer = new MutationObserver(focusUsername);
        observer.observe(doc.body, { childList: true, subtree: true });
        focusTimer = setTimeout(focusUsername, 150);
        focusUsername();
        win.__abuZaidLoginKeyboardCleanup = () => {
          doc.removeEventListener('keydown', onKeyDown, true);
          if (observer) observer.disconnect();
          clearTimeout(focusTimer);
        };
      } catch (error) { /* Login remains usable by mouse if iframe access is blocked. */ }
    })();
    </script>
    """, unsafe_allow_javascript=True)

    from release_info import login_footer
    login_footer(Path(__file__).resolve().parent, 'windows')

    with st.form("login_form", enter_to_submit=True):
        u_name = st.text_input("اسم المستخدم", placeholder="اسم المستخدم", label_visibility="collapsed")
        u_pass = st.text_input("الرقم السري أو كلمة المرور" if not server_enabled() else "كلمة المرور", type="password", placeholder="الرقم السري أو كلمة المرور" if not server_enabled() else "كلمة المرور", label_visibility="collapsed")
        submit = st.form_submit_button("دخول", use_container_width=True)

        if submit:
            from branch_auth import online_login, local_login
            user = None
            if not server_enabled():
                # Standalone SHERIF installations have no server login endpoint.
                user = local_login(u_name, u_pass)
                if user is None:
                    st.error("تعذر تسجيل الدخول. تحقق من اسم المستخدم والرقم السري المحلي.")
            else:
                try:
                    user = online_login(u_name, u_pass)
                except ValueError as exc:
                    st.error(str(exc))
                except (ConnectionError, KeyError, TypeError, OSError):
                    user = local_login(u_name, u_pass)
                    if user is None:
                        st.error("تعذر تسجيل الدخول. تحقق من اسم المستخدم وكلمة المرور، وتأكد من تجهيز الحساب للعمل دون إنترنت.")
                    else:
                        st.info("تم تسجيل الدخول؛ يُرجى متابعة حالة المزامنة قبل إغلاق اليوم.")
            if user:
                # Reject other-branch users before enrolling them or uploading local sales.
                # Super_Admin may sign in to provision or move this workstation.
                try:
                    _login_branch_error = _branch_access_error(user)
                except Exception as exc:
                    st.error(f"تعذر التحقق من تعريف جهاز الفرع: {exc}")
                    st.stop()
                if _login_branch_error and user.get("role") != "Super_Admin":
                    st.error(_login_branch_error)
                    st.stop()
                st.session_state.pop("_branch_confirmed", None)
                st.session_state.pop("_login_assigned_branch_id", None)
                # Keep the authenticated identity in local SQLite for session restoration.
                from branch_auth import enroll_local_identity, bootstrap_reference_data
                from offline_store import sync_offline_users
                try:
                    enroll_local_identity(user)
                except Exception as exc:
                    st.error("تعذر حفظ حساب المستخدم محليًا: " + str(exc))
                    st.stop()
                if _workstation_info():
                    from auto_sync import request_sync
                    request_sync('admin_login' if user.get('_authenticated_online') and user.get('role') == 'Super_Admin' else 'login')
                st.session_state.update(_auth_release_seq=_current_auth_release(),logged_in=True, username=user["username"], role=user["role"],
                    user_id=user["id"], branch_id=user.get("branch_id"),
                    connection_mode=("online" if user.get("_authenticated_online") else "offline"), _reference_sync_done_this_login=True,
                    page=("🛒 نقطة البيع (POS)" if user["role"] == "Cashier" else
                          "🔎 استعلام الأصناف" if user["role"] == "استعلام فقط" else "🏠 الرئيسية واللوحة")
                )
                # Persist a revocable, time-limited login across browser refresh (F5).
                # The cookie stores only a random token; credentials stay out of the browser.
                _remember_login()

    st.stop()


# --- مزامنة مرجعية مؤكدة مرة واحدة بعد اكتمال تسجيل الدخول ---
# بعض اتصالات السيرفر تنجح في التحقق من المستخدم ثم تصبح غير صالحة قبل تنزيل
# البيانات المرجعية. لذلك نؤكد تنزيل الفروع/المخزن الرئيسي في أول rerun بعد الدخول.
# All Windows sessions use SQLite. Legacy direct PostgreSQL reference sync removed.
# Windows local-first: legacy direct PostgreSQL reference sync removed.
# HTTPS bootstrap is handled by branch_auth after online authentication.


# Price / reference synchronization while the page stays open.
# Streamlit fragments run periodically without requiring the user to log out.
# Keep any unsynced local work safe: sync_reference_data refuses destructive download
# while pending operations or invoices remain.
# Legacy direct-PostgreSQL sync is disabled on Windows until HTTPS data sync is ready.

# Cashier landing page: never route to the management dashboard.
# Preserve POS subviews (invoice archive, supply receipt, shift close) unchanged.
if st.session_state.get("role") == "Cashier":
    if st.session_state.get("page") not in ("🛒 نقطة البيع (POS)","🤖 المساعد الذكي AI"):
        st.session_state["page"] = "🛒 نقطة البيع (POS)"
        st.session_state["pos_active_view"] = "الكاشير السريع"
    if not st.session_state.get("_cashier_pos_landing_ready"):
        st.session_state["_cashier_pos_landing_ready"] = True
        st.session_state["pos_focus_barcode"] = True

# شاشة استراحة الكاشير تمنع الوصول لأي صفحات بيع أثناء القفل.
if st.session_state.get("cashier_break_locked"):
    from views.cashier_break import show as show_cashier_break
    show_cashier_break()

# A new workstation must complete central approval before cashier operation.
_device = _workstation_info()
if _device:
    if st.session_state.get('role') == 'Cashier' and str(st.session_state.get('branch_id')) != str(_device['branch_id']):
        st.error('هذا المستخدم غير تابع للفرع المعرّف على الجهاز.')
        st.stop()
    if st.session_state.get('role')=='Manager':st.session_state['branch_id']=None
    else:st.session_state['branch_id'] = _device['branch_id']
    st.sidebar.caption(f"🏢 {_device['branch_name']} — جهاز رقم {_device['device_number']}")
else:
    if st.session_state.get('role') != 'Super_Admin':
        st.error('هذا الجهاز غير معرّف. اطلب من السوبر أدمن تجهيز الجهاز من الإدارة العامة.')
        st.stop()
    _workstation_setup()
    st.stop()

def _ensure_current_session_account():
    """Recheck a valid local/central account on rerun; drafts stay in durable storage."""
    from database import account_login_allowed
    conn = None
    try:
        conn = get_db_connection()
        uid = st.session_state.get('user_id')
        if not account_login_allowed(conn, uid):
            _forget_login(); st.rerun()
        current = conn.execute('SELECT username,role FROM users WHERE id=?',(uid,)).fetchone()
        st.session_state.update(username=current['username'],role=current['role'])
    except PermissionError:
        _forget_login(); st.rerun()
    finally:
        if conn is not None:
            conn.close()


_ensure_current_session_account()
from views.technical_visibility import render_update_controls
if server_enabled(): render_update_controls(st.session_state.get("role", ""))


# --- القائمة الجانبية الجديدة (أقسام رئيسية فقط) ---
st.sidebar.markdown("<h2 style='text-align: center; color: white;'>SHERIF</h2>", unsafe_allow_html=True)
st.sidebar.markdown(
    f"<p style='text-align: center; color: white;'><b>{st.session_state['username']} | {st.session_state['role']}</b></p>",
    unsafe_allow_html=True
)
st.sidebar.markdown("---")

# Reauthenticate the same identity without interrupting local/offline operation.
from offline_store import API_TOKEN as _current_api_token
if server_enabled() and not _current_api_token and st.session_state.get("role") == "Super_Admin":
    st.session_state['connection_mode'] = 'offline'
    with st.sidebar.expander('🔐 استعادة اتصال المزامنة', expanded=True):
        st.caption('الدخول المحلي متاح. يلزم دخول أونلاين لاستعادة تنزيل البيانات والمزامنة.')
        with st.form('sync_reauthentication', clear_on_submit=True):
            st.caption('المستخدم الحالي: ' + str(st.session_state['username']))
            _sync_password = st.text_input('كلمة المرور لاستعادة المزامنة', type='password')
            _sync_login = st.form_submit_button('استعادة الاتصال أونلاين')
        if _sync_login:
            try:
                from branch_auth import online_login
                _sync_identity = online_login(st.session_state['username'], _sync_password,
                                              expected_user_id=st.session_state['user_id'])
                st.session_state['connection_mode'] = 'online'
                st.rerun()
            except (ValueError, ConnectionError, OSError) as exc:
                st.error('تعذر استعادة المزامنة: ' + str(exc))

MENU_GROUPS = {
    "🔎 استعلام الأصناف": [
        ("🔎 استعلام الأصناف", "استعلام حركة وأرصدة صنف", {}),
    ],
    "🏠 لوحة التحكم": [
        ("🏠 الرئيسية واللوحة", "🏠 لوحة التحكم", {}),
    ],
    "🛒 إدارة المبيعات": [
        ("🛒 نقطة البيع (POS)", "1- فاتورة بيع", {"pos_active_view": "الكاشير"}),
        ("🛒 نقطة البيع (POS)", "2- الأرشيف وإعادة الطباعة", {"pos_active_view": "الأرشيف"}),
        ("🛒 نقطة البيع (POS)", "مرتجع فاتورة مبيعات", {"document_correction_mode": "sale"}),
    ],
    "📥 إدارة المشتريات": [
        ("📥 المشتريات", "1- فاتورة مشتريات", {"purchase_quick_mode": "invoice"}),
        ("📥 المشتريات", "2- أرشيف وتقارير المشتريات", {"purchase_quick_mode": "reports"}),
    ],
    "📦 المخازن والأصناف": [
        ("📦 إدارة المخزن والفروع", "1- الأصناف وتعديل الكميات والأسعار", {"inventory_mode": "list"}),
        ("📦 إدارة المخزن والفروع", "2- إضافة صنف جديد", {"inventory_mode": "new"}),
        ("📦 إدارة المخزن والفروع", "فائض صنف", {"inventory_mode": "add"}),
        ("📦 إدارة المخزن والفروع", "3- الصلاحيات", {"inventory_mode": "expiry"}),
        ("➕ الفائض والتوالف والمرتجعات وتعديل السعر", "4- مرتجعات مخزنية", {"damage_returns_mode": "return"}),
        ("➕ الفائض والتوالف والمرتجعات وتعديل السعر", "5- سجل حركات المخزون", {"damage_returns_mode": "log"}),
        ("📁 استيراد Excel", "6- استيراد الأصناف من Excel", {}),
    ],
    "🏭 التحميص والتصنيع": [
        ("🥜 التحميص والخلط", "1- خلط", {"production_screen_mode": "mix"}),
        ("🥜 التحميص والخلط", "2- تحميص", {"production_screen_mode": "roast"}),
        ("🥜 التحميص والخلط", "3- سجل الإنتاج", {"production_screen_mode": "log"}),
    ],
    "👥 جهات التعامل والحسابات": [
        ("👥 جهات التعامل", "1- كشف حساب الدائن والمدين", {"parties_mode": "accounts"}),
        ("👥 جهات التعامل", "2- إضافة مورد / جهة تعامل", {"parties_mode": "add"}),
    ],
    "💰 المالية والإيصالات": [
        ("💰 المصروفات", "1- تسجيل الإيرادات", {"finance_screen_mode": "revenue"}),
        ("💰 المصروفات", "2- المصروفات العامة والخاصة", {"finance_screen_mode": "expense"}),
        ("👥 جهات التعامل", "3- سند صرف / دفع لجهة", {"parties_mode": "supplier_payment"}),
        ("👥 جهات التعامل", "4- سند قبض من جهة", {"parties_mode": "customer_collection"}),
        ("💰 المصروفات", "5- تسوية وإغلاق الورديات", {"finance_screen_mode": "settlement"}),
        ("💰 المصروفات", "6- أرشيف المصروفات والإيرادات", {"finance_screen_mode": "archive"}),
        ("👥 جهات التعامل", "7- أرشيف الإيصالات", {"parties_mode": "vouchers"}),
    ],
    "🏦 الخزينة وجميع التقارير": [
        ("🔎 البحث عن مستند", "0- البحث عن مستند برقم النظام", {}),
        ("🏦 الخزينة الرئيسية", "1- الخزينة الرئيسية", {"parties_mode": "treasuries"}),
        ("📈 ملخص الخزينة والتقارير", "2- تكلفة وقيمة المخزون والربح والخسارة", {}),
        ("🛒 نقطة البيع (POS)", "3- أرشيف وتقارير المبيعات", {"pos_active_view": "الأرشيف"}),
        ("📥 المشتريات", "4- تقارير المشتريات", {"purchase_quick_mode": "reports"}),
        ("➕ الفائض والتوالف والمرتجعات وتعديل السعر", "5- تقرير حركات المخزون", {"damage_returns_mode": "log"}),
        ("🥜 التحميص والخلط", "6- تقرير الإنتاج", {"production_screen_mode": "log"}),
        ("💰 المصروفات", "7- تقرير المصروفات والإيرادات", {"finance_screen_mode": "archive"}),
    ],
    "🤖 المساعد الذكي AI": [
        ("🤖 المساعد الذكي AI", "🤖 فتح المساعد الذكي", {}),
    ],
    "🔄 التحويلات وتزويد الفروع": [
        ("🔄 تزويد الفروع والأرشيف", "1- إنشاء فاتورة تزويد فرع", {"transfers_mode": "new"}),
        ("🔄 تزويد الفروع والأرشيف", "2- أرشيف التحويلات والتزويد", {"transfers_mode": "archive"}),
        ("🔄 تزويد الفروع والأرشيف", "مرتجع وتصحيح وإلغاء تزويد", {"document_correction_mode": "transfer"}),
    ],
    "👤 الإدارة العامة": [
        ("__BRANCH_DEVICE_ADMIN__", "🖥️ إدارة أجهزة الفروع", {}),
        ("__BRANCH_RESET_ADMIN__", "🧹 تصفير بيانات الفرع", {}),
        ("🏢 إدارة الفروع", "1- الفروع", {}),
        ("👥 إدارة المستخدمين", "2- المستخدمون والصلاحيات", {}),
        ("🎨 تخصيص المظهر", "3- إعدادات البرنامج وبيانات المنشأة", {}),
        ("⚙️ الجرد والتصفير السنوي", "4- إقفال وأرشفة السنة", {}),
        ("🧹 تهيئة النظام لأول تشغيل", "5- تجهيز البيانات", {}),
        ("__WORKSTATION_SETUP__", "6- 🖥️ تجهيز الجهاز", {}),
    ],
}

# إعداد ترتيب القوائم (محلي ومشترك بين جلسات البرنامج)
def _menu_order_connection():
    conn = get_local_connection()
    conn.execute("""CREATE TABLE IF NOT EXISTS sidebar_menu_order (
        config_key TEXT PRIMARY KEY, config_value TEXT NOT NULL
    )""")
    conn.commit()
    return conn

def _read_menu_order():
    conn = None
    try:
        conn = _menu_order_connection()
        row = conn.execute("SELECT config_value FROM sidebar_menu_order WHERE config_key='order'").fetchone()
        return json.loads(row[0]) if row else {}
    except Exception:
        return {}
    finally:
        if conn is not None:
            conn.close()

def _write_menu_order(order):
    conn = _menu_order_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sidebar_menu_order(config_key, config_value) VALUES ('order', ?)",
            (json.dumps(order, ensure_ascii=False),)
        )
        conn.commit()
    finally:
        conn.close()

_ORIGINAL_MENU_GROUPS = MENU_GROUPS
_MENU_PREFERENCES = _read_menu_order()

def _ordered_menu_groups():
    prefs = _read_menu_order()
    groups = prefs.get("groups", [])
    groups = [g for g in groups if g in _ORIGINAL_MENU_GROUPS]
    groups += [g for g in _ORIGINAL_MENU_GROUPS if g not in groups]
    result = {}
    for group in groups:
        originals = _ORIGINAL_MENU_GROUPS[group]
        indices = prefs.get("items", {}).get(group, [])
        indices = [i for i in indices if type(i) is int and 0 <= i < len(originals)]
        indices = list(dict.fromkeys(indices))
        indices += [i for i in range(len(originals)) if i not in indices]
        result[group] = [originals[i] for i in indices]
    return result

MENU_GROUPS = _ordered_menu_groups()

def allowed_group_entries(group_name):
    return [
        (target, label, state_updates)
        for target, label, state_updates in MENU_GROUPS.get(group_name, [])
        if check_user_permission(target)
    ]

for group_name in MENU_GROUPS:
    entries = allowed_group_entries(group_name)
    if entries:
        if st.sidebar.button(
            group_name,
            use_container_width=True,
            key=f"sidebar_group_{group_name}"
        ):
            if st.session_state.get("role")=="Cashier" and group_name=="🤖 المساعد الذكي AI":
                set_page("🤖 المساعد الذكي AI")
            elif group_name == "🏠 لوحة التحكم":
                set_page("🏠 الرئيسية واللوحة")
            else:
                set_page(f"__GROUP__::{group_name}")

if st.session_state.get("role") == "Super_Admin":
    if st.sidebar.button("⚙️ ترتيب القوائم الجانبية", use_container_width=True):
        set_page("__MENU_ORDER_SETTINGS__")

st.sidebar.markdown("---")
from central_updater import request_login_update_check
if st.session_state.get('logged_in'):request_login_update_check()
if os.name == 'nt' and st.sidebar.button("إغلاق البرنامج", key="pos_exit_program", width="stretch"):
    from central_updater import request_program_exit
    try:request_program_exit()
    except ValueError as exc:st.error(str(exc))
    else:
        st.info("جارٍ إنهاء جلسة البرنامج بأمان.")
        st.stop()

if st.sidebar.button("🚪 تسجيل الخروج", use_container_width=True):
    _forget_login()

st.sidebar.markdown("---")

# Real server reachability is separate from authenticated login and sync status.
@st.cache_data(ttl=20, show_spinner=False)
def _abuzaid_server_reachable():
    from auto_sync import auto_sync_status
    return bool(auto_sync_status().get('server_reachable'))


def _show_branch_connection_status():
    if not server_enabled():
        st.sidebar.info('المزامنة غير مهيأة.')
        return
    if st.session_state.get('role') not in ('Super_Admin','Admin'):
        from auto_sync import auto_sync_status
        if auto_sync_status().get('server_reachable'):
            st.sidebar.success('🟢 متصل')
        else:
            st.sidebar.info('البيانات محفوظة محلياً؛ يمكنك متابعة العمل.')
        if st.session_state.get('role') == 'Cashier':
            from auto_sync import request_sync
            if st.sidebar.button('مزامنة الآن مع السيرفر', key='cashier_manual_sync', width='stretch'):
                requested_at = time.time()
                request_sync('cashier_manual')
                st.session_state['_cashier_sync_requested_at'] = requested_at
                st.session_state['pos_focus_barcode'] = True
                st.rerun()
            requested_at = st.session_state.get('_cashier_sync_requested_at')
            if requested_at:
                status = auto_sync_status()
                if ((status.get('last_success') or 0) >= requested_at
                        and status.get('pending_invoices') == 0
                        and status.get('pending_operations') == 0):
                    st.sidebar.success('اكتملت المزامنة مع السيرفر.')
                elif status.get('state') == 'needs_admin_review':
                    st.sidebar.warning('البيانات محفوظة؛ توجد عمليات تحتاج مراجعة المسؤول.')
                else:
                    st.sidebar.info('تم طلب المزامنة؛ ستُستكمل تلقائيًا عند توفر الاتصال. يمكنك متابعة البيع.')
        return
    reachable = _abuzaid_server_reachable()
    if reachable:
        st.sidebar.success("🟢 السيرفر: متصل (Online)")
    else:
        st.sidebar.error("🔴 السيرفر: غير متصل (Offline) — البيع المحلي مستمر")
    try:
        from offline_store import sync_is_paused as _is_paused
        if _is_paused():
            st.sidebar.warning("🟠 المزامنة: متوقفة من تجهيز البيانات")
        elif not reachable:
            st.sidebar.info("المزامنة: تنتظر عودة الاتصال")
        elif not __import__("offline_store").API_TOKEN:
            st.sidebar.warning("المزامنة: تنتظر تأكيد الدخول")
        else:
            st.sidebar.info("المزامنة: مفعّلة — لا يعني ذلك اكتمال آخر مزامنة")
    except Exception:
        st.sidebar.warning("تعذر قراءة حالة المزامنة المحلية")


if hasattr(st, "fragment"):
    @st.fragment(run_every="30s")
    def _branch_connection_indicator():
        _show_branch_connection_status()
    with st.sidebar:
        _branch_connection_indicator()
else:
    _show_branch_connection_status()

# زر الاستراحة للكاشير فقط، أسفل حالة الاتصال والمزامنة.
if st.session_state.get("role") == "Cashier":
    if st.sidebar.button("☕ استراحة شريف", key="cashier_break_start", use_container_width=True):
        st.session_state["cashier_break_locked"] = True
        st.rerun()

st.sidebar.markdown("---")


# تقليل الفراغ العلوي في شاشة الكاشير فقط.
if st.session_state.get("role") == "Cashier":
    st.markdown("""<style>
    /* Cashier-only: remove the unused Streamlit toolbar and its white band. */
    [data-testid="stHeader"], [data-testid="stToolbar"],
    [data-testid="stDecoration"], [data-testid="stStatusWidget"],
    [data-testid="stMainMenu"] {display:none !important;}
    [data-testid="stAppViewContainer"] {top:0 !important;}
    [data-testid="stMainBlockContainer"],
    [data-testid="stMain"] .block-container {
        padding-top: 0.15rem !important;
        padding-bottom: 0.7rem !important;
    }
    [data-testid="stSidebar"] [data-testid="stButton"] button {
        margin-bottom: 0 !important;
    }
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap:0.35rem !important;}
    </style>""", unsafe_allow_html=True)

# --- منطقة توجيه الشاشات واللوحة الرئيسية ---
from views.ui_feedback import begin_ui_run, show_pending_success
begin_ui_run()
show_pending_success()

choice = st.session_state.get("page", "🏠 الرئيسية واللوحة")
_nav_targets={target for entries in MENU_GROUPS.values() for target,_,_ in entries if check_user_permission(target)}
_nav_targets.update('__GROUP__::'+g for g in MENU_GROUPS if allowed_group_entries(g))
st.session_state['_nav_allowed_targets']=list(_nav_targets)
from views.ui_common import back_button as _shared_back_button
_shared_back_button(key='shared_page_back')
_context_keys={key for entries in MENU_GROUPS.values() for _,_,modes in entries for key in modes}
st.session_state['_nav_context_keys']=list(_context_keys)
st.session_state['_nav_rendered_context']={'page':choice,'state':{key:st.session_state[key] for key in _context_keys if isinstance(st.session_state.get(key),str)}}


if choice!='🛒 نقطة البيع (POS)' and st.session_state.get('_pos_memory_context') is not None:
    from views.pos_policy import clear_memory
    clear_memory(st.session_state)
if choice not in ("🧹 تهيئة النظام لأول تشغيل", "⚙️ الجرد والتصفير السنوي"):
    for _key in list(st.session_state):
        if _key.startswith("prep_"):
            st.session_state.pop(_key, None)
from offline_store import sync_is_paused
if sync_is_paused() and st.session_state.get('role') == 'Super_Admin':
    st.warning('مزامنة الرفع متوقفة: يلزم تجهيز البيانات بواسطة السوبر أدمن قبل استئنافها.')


# تغيير فرع الجهاز ورقمه متاح للسوبر أدمن في أي وقت.
if choice == "__WORKSTATION_SETUP__":
    if st.session_state.get("role") not in ("Super_Admin","Admin","Manager"):
        st.error("غير مصرح بالدخول.")
        st.stop()
    _workstation_setup()
    st.stop()

if choice == "__BRANCH_RESET_ADMIN__":
    from views.branch_reset_admin import show_page
    show_page()
    st.stop()

if choice == "__BRANCH_DEVICE_ADMIN__":
    from views.branch_devices import show_page
    show_page()
    st.stop()

# شاشة خاصة بالسوبر أدمن لترتيب القوائم
if choice == "__MENU_ORDER_SETTINGS__":
    if st.session_state.get("role") != "Super_Admin":
        st.error("غير مصرح بالدخول.")
        st.stop()
    st.title("⚙️ ترتيب القوائم الجانبية")
    st.caption("استخدم الأسهم لترتيب المجموعات والشاشات، ثم اضغط حفظ.")
    if "_menu_order_draft" not in st.session_state:
        prefs = _read_menu_order()
        st.session_state["_menu_order_draft"] = {
            "groups": list(MENU_GROUPS),
            "items": dict(prefs.get("items", {})),
        }
    draft = st.session_state["_menu_order_draft"]
    draft["groups"] = [g for g in draft["groups"] if g in _ORIGINAL_MENU_GROUPS]
    draft["groups"] += [g for g in _ORIGINAL_MENU_GROUPS if g not in draft["groups"]]
    for gi, group in enumerate(list(draft["groups"])):
        with st.container(border=True):
            title_col, up_col, down_col = st.columns([8, 1, 1])
            title_col.markdown(f"**{group}**")
            if up_col.button("⬆️", key=f"grp_up_{gi}", disabled=gi == 0):
                draft["groups"][gi-1], draft["groups"][gi] = draft["groups"][gi], draft["groups"][gi-1]
                st.rerun()
            if down_col.button("⬇️", key=f"grp_down_{gi}", disabled=gi == len(draft["groups"])-1):
                draft["groups"][gi+1], draft["groups"][gi] = draft["groups"][gi], draft["groups"][gi+1]
                st.rerun()
            with st.expander("ترتيب الشاشات داخل المجموعة"):
                originals = _ORIGINAL_MENU_GROUPS[group]
                indices = draft["items"].get(group, [])
                indices = [i for i in indices if type(i) is int and 0 <= i < len(originals)]
                indices = list(dict.fromkeys(indices))
                indices += [i for i in range(len(originals)) if i not in indices]
                draft["items"][group] = indices
                for pos, original_idx in enumerate(list(indices)):
                    item_col, item_up, item_down = st.columns([8, 1, 1])
                    item_col.write(originals[original_idx][1])
                    if item_up.button("⬆️", key=f"item_up_{gi}_{original_idx}", disabled=pos == 0):
                        indices[pos-1], indices[pos] = indices[pos], indices[pos-1]
                        st.rerun()
                    if item_down.button("⬇️", key=f"item_down_{gi}_{original_idx}", disabled=pos == len(indices)-1):
                        indices[pos+1], indices[pos] = indices[pos], indices[pos+1]
                        st.rerun()
    save_col, reset_col = st.columns(2)
    if save_col.button("💾 حفظ الترتيب", use_container_width=True):
        try:
            _write_menu_order(draft)
            st.session_state.pop("_menu_order_draft", None)
            st.success("تم حفظ ترتيب القوائم.")
            st.rerun()
        except Exception as exc:
            st.error(f"تعذر حفظ الترتيب: {exc}")
    if reset_col.button("↩️ استعادة الترتيب الأصلي", use_container_width=True):
        st.session_state["_menu_order_draft"] = {
            "groups": list(_ORIGINAL_MENU_GROUPS),
            "items": {g: list(range(len(v))) for g, v in _ORIGINAL_MENU_GROUPS.items()},
        }
        st.rerun()
    st.stop()

# لو المستخدم داخل قسم رئيسي، نعرض لوحة أزرار داخلية.
if choice.startswith("__GROUP__::"):
    group_name = choice.split("::", 1)[1]
    entries = allowed_group_entries(group_name)

    st.markdown(
        f"<h2 style='direction:rtl;text-align:right;'>"
        f"{group_name}</h2>",
        unsafe_allow_html=True
    )
    st.caption("اختر العملية المطلوبة من الأزرار التالية.")

    if not entries:
        st.warning("⚠️ لا توجد عمليات متاحة لك داخل هذا القسم حسب صلاحياتك.")
        st.stop()

    cols = st.columns(3)
    for idx, (target, label, state_updates) in enumerate(entries):
        if cols[idx % 3].button(
            label,
            use_container_width=True,
            key=f"group_action_{group_name}_{target}_{idx}"
        ):
            # القائمة الرئيسية هي مكان التنقل الوحيد.
            for lock_key in [
                "document_correction_mode", "inventory_entry_lock", "production_entry_lock",
                "parties_entry_lock", "purchases_entry_lock",
                "finance_entry_lock", "damage_returns_entry_lock",
                "transfers_entry_lock"
            ]:
                st.session_state.pop(lock_key, None)

            for state_key, state_value in state_updates.items():
                st.session_state[state_key] = state_value

            lock_map = {
                "inventory_mode": "inventory_entry_lock",
                "production_screen_mode": "production_entry_lock",
                "parties_mode": "parties_entry_lock",
                "purchase_quick_mode": "purchases_entry_lock",
                "finance_screen_mode": "finance_entry_lock",
                "damage_returns_mode": "damage_returns_entry_lock",
                "transfers_mode": "transfers_entry_lock",
            }
            for state_key, lock_key in lock_map.items():
                if state_key in state_updates:
                    st.session_state[lock_key] = True

            set_page(target)

    st.stop()

if not check_user_permission(choice):
    st.error("❌ غير مصرح لك بالوصول إلى هذه الشاشة.")
    st.stop()

def _dashboard_amount(value, currency=True):
    """Format displayed numbers with a decimal comma and no thousands grouping."""
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    try:
        number = Decimal(str(value if value is not None else 0))
        formatted = format(number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f").replace(".", ",")
    except (InvalidOperation, ValueError, TypeError):
        formatted = "0,00"
    return formatted + (" د.ل" if currency else "")


def _dashboard_metric(label, value, currency=True):
    import html
    st.markdown(
        '<div style="direction:rtl;text-align:right;padding:5px 0 12px">'
        f'<div style="font-weight:700;font-size:14px">{html.escape(str(label))}</div>'
        f'<div dir="ltr" style="text-align:right;font-weight:800;font-size:19px;line-height:1.7">{html.escape(_dashboard_amount(value, currency))}</div>'
        '</div>', unsafe_allow_html=True
    )


from central_inventory import headquarters_frontend
if headquarters_frontend(choice, MENU_GROUPS):
    st.stop()

if choice == "🔎 استعلام الأصناف":
    from views import item_inquiry
    _guarded_page_call(item_inquiry.show_page)
elif choice == "🏠 الرئيسية واللوحة":
    # Same visual dashboard as Contabo; strictly local SQLite on Windows.
    from views.dashboard import show_dashboard
    show_dashboard(
        st.session_state.get("username", ""),
        st.session_state.get("role", ""),
        st.session_state.get("branch_id"),
    )

elif choice == "🛒 نقطة البيع (POS)":
    try:
        from views import pos
        _guarded_page_call(pos.show_page)
    except ImportError as e:
        st.error("❌ تعذر تحميل شاشة نقطة البيع بسبب ملف أو مكتبة مفقودة.")
        st.code(str(e))
elif choice == "🔎 البحث عن مستند":
    try:
        from views import documents
        _guarded_page_call(documents.show_page)
    except ImportError as e:
        st.warning("⚠️ شاشة البحث عن المستندات غير متاحة.")
        st.code(str(e))
elif choice == "🤖 المساعد الذكي AI":
    try:
        from views import ai_assistant
        _guarded_page_call(ai_assistant.show_page)
    except ImportError as e:
        st.warning("⚠️ شاشة المساعد الذكي غير متاحة حالياً.")
        st.code(str(e))
elif choice == "🏢 إدارة الفروع":
    try:
        from views import branches
        _guarded_page_call(branches.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة إدارة الفروع غير موجود.")
elif choice == "👥 إدارة المستخدمين":
    try:
        from views import users
        _guarded_page_call(users.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة إدارة المستخدمين غير موجود.")
elif choice == "➕ الفائض والتوالف والمرتجعات وتعديل السعر":
    try:
        from views import damages_returns
        _guarded_page_call(damages_returns.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة الفائض والتوالف والمرتجعات غير موجود.")
elif choice == "📁 استيراد Excel":
    try:
        from views import items_import
        _guarded_page_call(items_import.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة الاستيراد غير موجود.")
elif choice == "💰 المصروفات":
    try:
        from views import expenses
        _guarded_page_call(expenses.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة المصروفات غير موجود.")
elif choice in ["👥 جهات التعامل", "🏦 الخزينة الرئيسية"]:
    try:
        from views import parties
        if choice == "🏦 الخزينة الرئيسية":
            st.session_state["parties_mode"] = "treasuries"
            st.session_state["parties_entry_lock"] = True
        _guarded_page_call(parties.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة جهات التعامل والخزائن غير موجود.")
elif choice == "📥 المشتريات":
    try:
        from views import purchases
        _guarded_page_call(purchases.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة المشتريات غير موجود.")
elif choice == "🔄 تزويد الفروع والأرشيف":
    try:
        from views import transfers
        _guarded_page_call(transfers.show_page)
    except ImportError:
        st.info("🔄 شاشة تزويد الفروع والأرشيف قيد التجهيز.")
elif choice == "📦 إدارة المخزن والفروع":
    try:
        from views import inventory
        _guarded_page_call(inventory.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة إدارة المخزن والفروع غير موجود.")
elif choice == "⚙️ الجرد والتصفير السنوي":
    try:
        from views import annual_reset
        _guarded_page_call(annual_reset.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة الجرد والتصفير السنوي غير موجود.")
elif choice == "🧹 تهيئة النظام لأول تشغيل":
    try:
        from views import initial_setup_reset
        _guarded_page_call(initial_setup_reset.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة تهيئة النظام لأول تشغيل غير موجود.")
elif choice == "🥜 التحميص والخلط":
    try:
        from views import roasting_blending
        _guarded_page_call(roasting_blending.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة التحميص والخلط غير موجود.")
elif choice == "🎨 تخصيص المظهر":
    try:
        from views import appearance as appearance_view
        _guarded_page_call(appearance_view.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة تخصيص المظهر غير موجود.")
elif choice == "📊 التقارير والأرباح":
    try:
        from views import reports
        _guarded_page_call(reports.show_page)
    except ImportError:
        st.warning("⚠️ ملف شاشة التقارير والأرباح غير موجود.")
elif choice == "📈 ملخص الخزينة والتقارير":
    try:
        from views import treasury_reports
        _guarded_page_call(treasury_reports.show_page)
    except ImportError as e:
        st.warning("⚠️ ملف شاشة ملخص الخزينة والتقارير غير موجود.")
        st.code(str(e))
