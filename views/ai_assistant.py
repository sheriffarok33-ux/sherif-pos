_PAGE_ERROR_UI_REVISION = 71
from views.technical_visibility import technical_details_allowed, require_technical_reader
"""Permission-aware, offline in-app help and read-only management summaries.
No external model is configured: answers come from reviewed application workflows.
"""
import re
import sqlite3
import streamlit as st
from database import get_db_connection
from views.number_format import decimal_display

REFUSAL = 'هنى روحك وارجع للمهندس شريف فاروق 😛'
MANAGEMENT = {'Super_Admin', 'Admin', 'Manager', 'General_Supervisor'}
SUPERVISORS = MANAGEMENT | {'Supervisor', 'Branch_Supervisor'}
ALL = SUPERVISORS | {'Cashier'}

# These permissions mirror main.check_user_permission. Do not disclose restricted
# workflow instructions or figures to roles that cannot access their screens.
HELP = [
    (('مرتجع تزويد','مرتجع التزويد','تصحيح تزويد','تصحيح التزويد','إلغاء تزويد','الغاء التزويد','مرتجع فاتورة تزويد','بعد التسوية','مرتجع فاتورة','مرتجع'), {'Super_Admin','Admin','Manager'}, 'من «التحويلات وتزويد الفروع» افتح «مرتجع وتصحيح وإلغاء تزويد». اختر الفرع ورقم مستند التزويد واعرض الأصل. اختر مرتجعًا كاملًا/جزئيًا، أو التصحيح لإدخال الكمية الصحيحة وإضافة صنف موجود بالمصدر والمستلم، أو إلغاء المتبقي. أدخل السبب وأكد فحص الكميات. تُسجل حركات مرتبطة بالأصل ولا يُحذف التاريخ. يفحص النظام الرصيد والدفعات المصروفة ويرفض العكس غير الآمن. تأكيد الاستلام لا يضيف مخزونًا ثانيًا. أوفلاين يُحفظ طلب معلق ويعتمد مرة واحدة بعد تحقق السيرفر؛ لا تتعامل معه كتسوية مكتملة قبل التأكيد.'),
    (('مرتجع فاتورة مبيعات','مرتجع المبيعات','مرتجع مبيعات','إرجاع فاتورة','استرجاع فاتورة','مرتجع فاتورة','مرتجع'), {'Super_Admin','Admin','Manager'}, 'من «إدارة المبيعات» اختر «مرتجع فاتورة مبيعات». حدد الفرع ورقم الفاتورة واعرض الأصل، ثم المرتجع الكامل أو كميات جزئية من المتبقي. حدد صلاحية البضاعة المرتجعة إذا كانت متتبعة، وخزينة الرد لغير الآجل، والسبب، وأكد الاستلام والفحص. يستخدم صافي الفاتورة وخصمها المسجل ويمنع تكرار الكميات؛ الآجل يخفض حساب العميل الصحيح، وغيره يسجل ردًا بالخزينة المحددة. يبقى الأصل وتقارير Z السابقة محفوظين ويصدر مستند مرتجع مرتبط. للكاشير لا تُمنح صلاحية إدارية تلقائيًا. أوفلاين يُحفظ الطلب في الطابور الموجود دون صرف أو تسوية نهائية حتى التأكيد المركزي؛ يمكن إلغاء طلب غير معتمد بعد تحقق السيرفر فقط.'),

    (('سعر الميزان','باركود الميزان','aclas','rongta','باركود الوزن','ميزان','الميزان'), ALL, 'من المخازن والأصناف صدّر Excel: عمود سعر الميزان بعد سعر البيع. أدخل سعر الكيلو الفعلي المستخدم على الميزان وقت طباعة الملصقات، ثم ارفع الملف من استيراد الأصناف؛ وجود العمود يحدّث سعر الميزان فقط ويترك باقي البيانات. الفراغ يحفظ السعر السابق. ينزل السعر للفروع بالمزامنة ويعمل أوفلاين. صيغة الوزن تستعمل الوزن مباشرة؛ صيغة السعر تستخرج الوزن بسعر الميزان ثم تسعّر بسعر بيع SHERIF. تقريب سعر الملصق قد يسبب فرقًا صغيرًا في الوزن المحسوب. الصيغ تؤخذ من الإعداد المعتمد ولا تتغير إعدادات الميزان تلقائيًا.'),
    (('مستخدم', 'مستخدمين', 'حساب', 'صلاحيات', 'موظف', 'كاشير جديد'), MANAGEMENT,
     'افتح «إدارة المستخدمين» ثم «🔐 حسابات الدخول». اكتب اسم المستخدم وكلمة المرور، وحدد الدور والفرع ثم اضغط «➕ إنشاء حساب». لإضافة صلاحية استثنائية افتح «صلاحيات إضافية حسب المستخدم والفرع» إن كانت متاحة لدورك. لا تشارك كلمات المرور مع أحد.'),
    (('وردية', 'ورديه', 'اقفال', 'إغلاق', 'اغلاق', 'تصفير'), ALL,
     'افتح «🛒 نقطة البيع (POS)» ثم «📊 التقارير والإغلاق»، وحدد الفرع واختر «🔒 إغلاق الوردية» بدل «عرض الوردية». تنفيذ الإغلاق يتطلب صلاحية الإغلاق؛ الكاشير لا يحصل عليها تلقائيًا.'),
    (('فاتورة', 'بيع', 'مبيعات', 'نقطة البيع', 'pos', 'طباعة'), ALL,
     'من «🛒 إدارة المبيعات» اختر «1- فاتورة بيع» لإنشاء فاتورة، أو «2- الأرشيف وإعادة الطباعة» لاستعراض الفواتير السابقة وإعادة طباعتها وفق صلاحيتك.'),
    (('صنف', 'اصناف', 'مخزون', 'جرد', 'سعر', 'كميه', 'كمية'), SUPERVISORS,
     'افتح «📦 إدارة المخزن والفروع» ثم اختر «الأصناف وتعديل الكميات والأسعار» أو «إضافة صنف جديد». تأكد من اختيار الفرع والصنف الصحيحين قبل الحفظ.'),
    (('تحويل', 'تزويد', 'نقل بضاعة', 'نقل مخزون'), MANAGEMENT,
     'افتح «🔄 التحويلات وتزويد الفروع» ثم «إنشاء فاتورة تزويد فرع». اختر فرع المصدر والوجهة والأصناف والكميات ثم راجع المخزون قبل الاعتماد.'),
    (('مشتريات', 'شراء', 'مورد'), MANAGEMENT,
     'افتح «📥 إدارة المشتريات» ثم «فاتورة مشتريات» لتسجيل فاتورة جديدة، أو «أرشيف وتقارير المشتريات» لمراجعتها.'),
    (('مصروف', 'ايراد', 'إيراد', 'خزينة', 'تسوية'), MANAGEMENT,
     'افتح «💰 المصروفات» لتسجيل الإيرادات أو المصروفات أو تسوية وإغلاق الورديات، أو «📈 ملخص الخزينة والتقارير» لمراجعة الأرقام.'),
    (('تقرير', 'ارباح', 'أرباح', 'ربح', 'خسارة'), SUPERVISORS,
     'افتح «📊 التقارير والأرباح» لعرض تقارير المبيعات المتاحة لدورك. تقارير الخزينة والمالية التفصيلية تتطلب صلاحية إدارية.'),
    (('فرع', 'فروع', 'انشاء فرع', 'إضافة فرع'), MANAGEMENT,
     'افتح «🏢 إدارة الفروع» لإدارة الفروع. المدير والمشرف المخوّل يستطيعان اختيار الفرع في شاشة نقطة البيع وفق الصلاحيات المفعّلة.'),
    (('مرتجع', 'تالف', 'هالك', 'فائض'), SUPERVISORS,
     'افتح «➕ الفائض والتوالف والمرتجعات وتعديل السعر» واختر العملية المطلوبة، ثم راجع الكمية والفرع قبل التسجيل.'),
]


def _normalize(question):
    return re.sub(r'\s+', ' ', question.strip().lower().replace('أ','ا').replace('إ','ا').replace('آ','ا').replace('ة','ه'))


def _answer(question, role):
    q = _normalize(question)
    if not q:
        return 'اكتب سؤالك عن البرنامج وسأرشدك للخطوات المتاحة لصلاحيتك.'
    if any(x in q for x in ('مين عمل', 'مين صمم', 'مين نفذ', 'مين طور', 'من المطور', 'من المصمم', 'صاحب البرنامج', 'مبرمج البرنامج', 'مهندس البرنامج')):
        return 'تصميم وتنفيذ البرنامج: eng Sherif — المهندس شريف فاروق.'
    if any(x in q for x in ('اختراق', 'تهكير', 'تجاوز الصلاحي', 'سرقه', 'اسرق', 'كلمه سر غيري', 'باسورد غيري', 'احذف السجلات', 'اخفي العمليات')):
        return REFUSAL
    # Never guide deletion or disabling of privileged accounts, even if the
    # question also mentions users or permissions.
    forbidden_actions = ('امسح', 'مسح', 'احذف', 'حذف', 'اشيل', 'شيل', 'الغي', 'الغاء', 'عطل', 'تعطيل', 'امحي', 'محو', 'امسحلي', 'حذفلي')
    privileged_accounts = ('سوبر ادمن', 'سوبرادمِن', 'سوبرادمن', 'super admin', 'super_admin', 'superadmin', 'مدير النظام', 'المسؤول الاعلى')
    if any(action in q for action in forbidden_actions) and any(account in q for account in privileged_accounts):
        return REFUSAL
    matches = []
    for keywords, allowed, reply in HELP:
        score = sum(1 for word in keywords if _normalize(word) in q)
        if score:
            matches.append((score, allowed, reply))
    if matches:
        matches.sort(key=lambda item: item[0], reverse=True)
        _, allowed, reply = matches[0]
        return reply if role in allowed else REFUSAL
    return REFUSAL


def _scalar(conn, sql):
    row = conn.execute(sql).fetchone()
    return row[0] if row else 0


def _read_actor(conn, user_id, claimed_role):
    """Read current identity only; never initialize schema or grant a role."""
    if user_id is None:
        raise PermissionError('Missing current identity')
    row = conn.execute(
        'SELECT role, branch_id, is_active FROM users WHERE id=?', (user_id,)
    ).fetchone()
    if not row or int(row['is_active'] or 0) != 1 or row['role'] != claimed_role:
        raise PermissionError('Current identity is no longer valid')
    from control_services import account_login_allowed
    if not account_login_allowed(conn,user_id):
        raise PermissionError('Account lifecycle denies access')
    return row


def _management_scope(conn, user_id, claimed_role):
    """Same role set and branch policy as treasury_reports; read existing grants only."""
    actor = _read_actor(conn, user_id, claimed_role)
    if actor['role'] not in MANAGEMENT:
        raise PermissionError('Management summary is not available')
    if actor['role'] in ('Super_Admin', 'Admin'):
        return None
    branches = set()
    if actor['branch_id'] is not None:
        branches.add(int(actor['branch_id']))
    # Unlike scoped_branch_ids(), this reader must not create a permission table.
    raw = getattr(conn, '_conn', conn)
    if isinstance(raw, sqlite3.Connection):
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_branch_permissions'"
        ).fetchone()
    else:
        exists = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='user_branch_permissions'"
        ).fetchone()
    if exists:
        rows = conn.execute(
            'SELECT branch_id FROM user_branch_permissions WHERE user_id=? AND permission_key=?',
            (user_id, 'treasury_report_view')
        ).fetchall()
        branches.update(int(row[0]) for row in rows)
    if not branches:
        raise PermissionError('No authorized branch')
    return tuple(sorted(branches))


def _read_management_summary(conn, selected, user_id, claimed_role):
    """Shared read service used by the existing screen; no network, writes or free SQL."""
    queries = {
        'مبيعات اليوم': ('SELECT COALESCE(SUM(total_amount),0) FROM invoices WHERE date(created_at)=CURRENT_DATE', 'branch_id'),
        'عدد الفواتير اليوم': ('SELECT COUNT(*) FROM invoices WHERE date(created_at)=CURRENT_DATE', 'branch_id'),
        'الأصناف المسجلة': ('SELECT COUNT(*) FROM items WHERE 1=1', 'branch_id'),
        'الفروع النشطة': ('SELECT COUNT(*) FROM branches WHERE is_active=1', 'id'),
    }
    if selected not in queries:
        raise ValueError('Unknown management summary')
    scope = _management_scope(conn, user_id, claimed_role)
    sql, branch_column = queries[selected]
    params = ()
    if scope is not None:
        sql += ' AND ' + branch_column + ' IN (' + ','.join('?' for _ in scope) + ')'
        params = scope
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else 0


@st.dialog('رسالة من مساعد SHERIF', dismissible=False)
def _refusal_dialog():
    st.markdown(f'<div style="text-align:center; font-size:1.25rem; padding:1.5rem 0;">{REFUSAL}</div>', unsafe_allow_html=True)
    if st.button('OK', key='abuzaid_refusal_ok', type='primary', use_container_width=True):
        st.session_state['abuzaid_refusal_open'] = False
        st.rerun()


def show_page():
    st.title('🤖 مساعد SHERIF — دليل البرنامج')
    role = st.session_state.get('role', '')
    if role not in ALL:
        _refusal_dialog()
        return
    st.caption('اسأل عن طريقة استخدام البرنامج. الإجابات إرشادية ومحلية وتراعي دور المستخدم، ولا تنفذ عمليات أو تغيّر البيانات.')
    question = st.text_input('كيف أقدر أساعدك؟', placeholder='مثلاً: إزاي أضيف مستخدم جديد؟', key='abuzaid_help_question')
    if st.button('اسأل المساعد', type='primary', use_container_width=True):
        st.session_state['abuzaid_ai_sync_answer'] = False
        if _is_sync_question(question) and not technical_details_allowed():
            reply=REFUSAL
        elif _is_sync_question(question):
            conn = None
            try:
                conn = get_db_connection()
                reply = _read_sync_evidence(conn, st.session_state.get('user_id'), role)
                st.session_state['abuzaid_ai_sync_scope'] = _management_scope(conn, st.session_state.get('user_id'), role)
                st.session_state['abuzaid_ai_sync_answer'] = True
            except PermissionError:
                reply = REFUSAL
            except Exception:
                reply = 'تعذر قراءة سجلات المزامنة الحالية؛ لا توجد أدلة كافية لتحديد السبب. لم يتم تغيير البيانات.'
            finally:
                if conn is not None:conn.close()
        else:
            reply = _answer(question, role)
        st.session_state['abuzaid_ai_answer_owner'] = (st.session_state.get('user_id'),role)

        if reply == REFUSAL:
            st.session_state['abuzaid_refusal_open'] = True
            st.session_state.pop('abuzaid_ai_last_answer', None)
        else:
            st.session_state['abuzaid_refusal_open'] = False
            st.session_state['abuzaid_ai_last_answer'] = reply
    if st.session_state.get('abuzaid_ai_answer_owner') != (st.session_state.get('user_id'),role):
        st.session_state.pop('abuzaid_ai_last_answer',None)
    if st.session_state.get('abuzaid_ai_sync_answer') and not technical_details_allowed():
        st.session_state.pop('abuzaid_ai_last_answer',None)
    if st.session_state.get('abuzaid_ai_last_answer') and st.session_state.get('abuzaid_ai_sync_answer'):
        conn = None
        try:
            conn = get_db_connection()
            current_scope = _management_scope(conn, st.session_state.get('user_id'), role)
            if current_scope != st.session_state.get('abuzaid_ai_sync_scope'):
                st.session_state.pop('abuzaid_ai_last_answer',None)
        except Exception:
            # Cached branch evidence is hidden when current access cannot be proved.
            st.session_state.pop('abuzaid_ai_last_answer',None)
        finally:
            if conn is not None:conn.close()
    if st.session_state.get('abuzaid_refusal_open', False):
        _refusal_dialog()
    elif st.session_state.get('abuzaid_ai_last_answer'):
        st.info(st.session_state['abuzaid_ai_last_answer'])

    # Management summaries are intentionally not offered to non-management roles.
    if role not in MANAGEMENT:
        return
    with st.expander('📊 التحليلات الإدارية السريعة (قراءة فقط)'):
        options = ['مبيعات اليوم', 'عدد الفواتير اليوم', 'الأصناف المسجلة', 'الفروع النشطة']
        selected = st.selectbox('اختر التقرير', options)
        if st.button('عرض التحليل', key='ai_show_report'):
            conn = None
            try:
                conn = get_db_connection()
                value = _read_management_summary(
                    conn, selected, st.session_state.get('user_id'), role
                )
                if selected == 'مبيعات اليوم':
                    st.metric(selected, f'{decimal_display(float(value or 0), 2)} د.ل')
                else:
                    st.metric(selected, int(value or 0))
            except Exception:
                st.error('تعذر قراءة التقرير. لم يتم تغيير أي بيانات.')
            finally:
                if conn is not None:
                    conn.close()


def _is_sync_question(question):
    return 'مزامن' in _normalize(question) or 'sync' in _normalize(question)


def _read_sync_evidence(conn,user_id,claimed_role):
    require_technical_reader(conn,user_id,claimed_role)
    """Existing assistant answer area, existing scope; no repair or network action."""
    import json
    scope=_management_scope(conn,user_id,claimed_role)
    raw=getattr(conn,'_conn',conn)
    if isinstance(raw,sqlite3.Connection):
        exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_meta'").fetchone()
        if not exists:return 'لا توجد سجلات مطابقة محلية متاحة؛ لا يمكن تحديد سبب تعثر المزامنة من البيانات الحالية.'
        binding=conn.execute("SELECT value FROM local_meta WHERE key='branch_id'").fetchone()
        if not binding or not str(binding[0]).isdigit():return 'هوية الفرع المحلية غير موثقة في سجلات المطابقة المتاحة؛ لا يمكن عرض نتيجة موثوقة.'
        branch=int(binding[0])
        if scope is not None and branch not in scope:raise PermissionError('Branch evidence denied')
        rows=conn.execute("""SELECT key,value FROM local_meta WHERE key LIKE 'history_invoice:%'
            OR key LIKE 'history_erp:%' OR key LIKE 'history_content:%' ORDER BY key LIMIT 201""").fetchall()
        labels={'content_differs_review':'محتوى مختلف؛ السبب يحتاج مراجعة', 'central_record_missing_locally':'سجل مركزي غير موجود محلياً', 'local_record_missing_or_unmapped_centrally':'سجل محلي مفقود مركزياً أو هويته غير موثقة', 'reference_identity_unverified':'مرجع غير قابل للمطابقة الآمنة', 'schema_gap':'حقول غير متوافقة', 'local_table_unavailable':'جدول محلي غير متاح', 'missing_after_local_confirmation':'مفقودة مركزياً رغم التأكيد المحلي السابق',
                'receipt_fields_conflict':'اختلاف في رقم الفاتورة أو الإجمالي',
                'receipt_without_live_invoice':'إيصال دون فاتورة مركزية موجودة',
                'local_identity_conflict':'هوية محلية مكررة','local_identity_invalid':'هوية محلية غير صالحة',
                'receipt_hash_conflict':'اختلاف بصمة عملية ERP','local_payload_conflict':'محتوى محلي لا يطابق بصمته',
                'local_device_conflict':'العملية منسوبة لجهاز مختلف','pending_not_received':'معلّقة ولم يثبت استلامها'}
        lines=[];matched=0;unknown=0;reviewed=0
        for row in rows[:200]:
            try:
                report=json.loads(row['value'])
                if type(report.get('branch_id')) is not int or report['branch_id']!=branch:continue
                state=report['state'];identity=row['key'].split(':',1)[1]
                if not re.fullmatch('[a-zA-Z0-9_:-]{1,160}',identity):unknown+=1;continue
            except (ValueError,TypeError,KeyError,AttributeError):unknown+=1;continue
            reviewed+=1
            if state in ('receipt_fields_match','receipt_hash_match','content_match'):matched+=1
            elif state in labels:
                if len(lines)<10:lines.append(identity+' — '+labels[state])
            else:unknown+=1
        text=f'الفرع {branch}: روجعت {reviewed} نتيجة محفوظة؛ {matched} نتيجة متوافقة ضمن الأدلة المتاحة.'
        if lines:text+='\n'+'\n'.join(lines)
        elif reviewed:text+='\nلم تظهر فجوات في النتائج المعروضة، وهذا لا يثبت اكتمال جميع بيانات الفرع.'
        else:text+='\nلا توجد نتيجة مطابقة محفوظة يمكن الاعتماد عليها بعد.'
        if len(rows)>200:text+='\nالعرض مقتصر على أول 200 نتيجة محفوظة.'
        if unknown:text+=f'\nتوجد {unknown} نتيجة غير مكتملة أو غير صالحة للتفسير.'
        text+='\nهذه نتائج الصفحات التي فُحصت فعلاً؛ لا تثبت اكتمال جميع الجداول، ولم تُنفّذ إعادة رفع أو تسوية.'
        return text
    exists=conn.execute("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='audit_events_v1'").fetchone()
    if not exists:return 'سجل الاستلام المركزي غير متاح؛ لا توجد أدلة كافية لتحديد حالة الفروع.'
    sql="SELECT entity_id,branch_id,device_id,occurred_at FROM audit_events_v1 WHERE action_type IN ('invoice_received','erp_transaction_committed')"
    params=()
    if scope is not None:
        sql+=' AND branch_id IN ('+','.join('?' for _ in scope)+')';params=scope
    rows=conn.execute(sql+' ORDER BY occurred_at DESC,event_uuid DESC LIMIT 10',params).fetchall()
    text='المتاح مركزياً: آخر عمليات استلام موثقة في نطاق صلاحيتك.'
    for row in rows:text+='\n'+str(row['entity_id'])+' — فرع '+str(row['branch_id'])+' — '+str(row['occurred_at'])
    if not rows:text+='\nلا توجد سجلات استلام متاحة في هذا النطاق.'
    return text+'\nلا يمكن من هذه السجلات وحدها معرفة العمليات التي لم تصل أو الجزم بسبب فشل مزامنة جهاز.'
