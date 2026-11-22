"""HTTPS authentication and safe SQLite identity/reference enrollment for Windows."""
import json, hashlib, hmac, secrets, sqlite3
from pathlib import Path
from contextlib import contextmanager
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

BASE = Path(__file__).resolve().parent
import sys
from sherif_network import connection_dir
URL_FILE = connection_dir() / 'SERVER_URL.txt'
from sherif_paths import auth_db
AUTH_DB = auth_db()

def _api_url():
    from sherif_network import server_enabled
    if not server_enabled(): raise ConnectionError('لم يُهيأ سيرفر للاتصال.')
    url = URL_FILE.read_text(encoding='utf-8-sig').strip().rstrip('/') if URL_FILE.exists() else ''
    if not url.startswith('https://'):
        raise ConnectionError('SERVER_URL.txt must contain a valid HTTPS URL')
    return url

def _request(path, payload=None, token=None, *, _auth_retry=True):
    headers={'Accept':'application/json'}
    if payload is not None:headers['Content-Type']='application/json'
    if token:headers['Authorization']='Bearer '+token
    headers.update(device_auth_headers())
    data=json.dumps(payload).encode('utf-8') if payload is not None else None
    req=Request(_api_url()+path,data=data,headers=headers,method='POST' if data else 'GET')
    try:
        with urlopen(req,timeout=12) as response:return json.load(response)
    except HTTPError as error:
        if (error.code == 401 and _auth_retry and token and
                token == _SETUP_ADMIN_TOKEN and _SETUP_ADMIN_USER):
            error.close()
            renewed = _renew_setup_token(token)
            return _request(path, payload, renewed, _auth_retry=False)
        try:detail=json.loads(error.read(32768).decode('utf-8')).get('detail')
        except (ValueError,UnicodeError,AttributeError):detail=None
        if isinstance(detail,dict):message=str(detail.get('message') or detail.get('code') or '')[:1200]
        elif isinstance(detail,str):message=detail[:1200]
        elif isinstance(detail,list):
            labels={'username':'اسم المستخدم','password':'كلمة المرور','device_number':'رقم الجهاز','branch_id':'الفرع'}
            message='؛ '.join(labels.get(str((row.get('loc') or [''])[-1]),str((row.get('loc') or [''])[-1]))+': '+str(row.get('msg','بيانات غير صالحة')) for row in detail if isinstance(row,dict))[:1200]
        else:message=''
        if error.code>=500:
            failure=ConnectionError('تعذر إكمال إجراء الجهاز على السيرفر؛ لم يُعلن نجاحه. أعد المحاولة أو راجع المسؤول.')
            failure.http_status=error.code
            raise failure from error
        if error.code in (401,403) and not path.startswith(('/admin/devices','/devices/')):
            raise ValueError('اسم المستخدم أو كلمة المرور غير صحيحة، أو الحساب غير مصرح له') from error
        if message:
            failure=ValueError(message)
            failure.http_status=error.code
            failure.error_code=detail.get('code') if isinstance(detail,dict) else None
            raise failure from error
        if error.code==422:raise ValueError('رفض السيرفر البيانات (422) دون سبب مفصل.') from error
        raise ConnectionError('تعذر إكمال الطلب على السيرفر؛ البيانات محفوظة. راجع المسؤول.') from error
    except (URLError,TimeoutError,OSError) as error:
        raise ConnectionError('تعذر الاتصال بخدمة HTTPS: '+str(error)) from error

@contextmanager
def _auth_conn():
    c=sqlite3.connect(str(AUTH_DB),timeout=15)
    try:
        c.execute('CREATE TABLE IF NOT EXISTS logins(username TEXT PRIMARY KEY, salt BLOB NOT NULL, verifier BLOB NOT NULL, iterations INTEGER NOT NULL, user_json TEXT NOT NULL)')
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()

def online_login(username,password, *, expected_user_id=None):
    global _LAST_TOKEN, _ONLINE_CREDENTIALS
    if not isinstance(username, str) or not username.strip():
        raise ValueError('اسم المستخدم مطلوب لتسجيل الدخول أونلاين.')
    if not isinstance(password, str) or not password:
        raise ValueError('كلمة المرور مطلوبة لتسجيل الدخول أونلاين.')
    if len(username.strip()) > 100 or len(password) > 256:
        raise ValueError('اسم المستخدم أو كلمة المرور أطول من الحد المسموح على السيرفر.')
    response=_request('/auth/login',{'username':username.strip(),'password':password})
    user=response.get('user')
    if not isinstance(user,dict) or not all(k in user for k in ('id','username','role')):
        raise ConnectionError('استجابة الدخول من السيرفر غير مكتملة')
    if expected_user_id is not None and int(user['id']) != int(expected_user_id):
        raise ValueError('استخدم حساب المستخدم الحالي لاستعادة اتصال المزامنة.')
    # Token is available for device check only after server login.
    _LAST_TOKEN=response.get('access_token')
    if user.get('role') != 'Super_Admin':
        assert_device_branch(user, online=True)
    salt=secrets.token_bytes(16); rounds=310000
    verifier=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,rounds)
    with _auth_conn() as c:
        c.execute('REPLACE INTO logins VALUES (?,?,?,?,?)',(user['username'],salt,verifier,rounds,json.dumps(user)))
    user['_authenticated_online']=True
    # Token is held in-process only and never written to a file.
    _LAST_TOKEN=response.get('access_token')
    if not _LAST_TOKEN:
        raise ConnectionError('Server did not return an access token')
    # Reuse authenticated token for HTTPS invoice upload (in-memory only).
    from offline_store import set_api_token
    set_api_token(_LAST_TOKEN)
    _ONLINE_CREDENTIALS = (username.strip(), password)
    # Start safe automatic invoice uploads after authenticated online login.
    # Non-invoice SQL operations are intentionally left pending for reconciliation.
    from auto_sync import start_auto_sync
    if local_device_info().get('bound_device_id'):
        start_auto_sync()
    return user

_LAST_TOKEN=None
# Online credentials are only held in RAM during this process, never written to disk.
_ONLINE_CREDENTIALS = None

def refresh_online_token():
    global _LAST_TOKEN
    if _SETUP_ADMIN_USER and _SETUP_ADMIN_TOKEN:
        return _renew_setup_token(_SETUP_ADMIN_TOKEN)
    if not _ONLINE_CREDENTIALS:
        return None
    username, password = _ONLINE_CREDENTIALS
    try:
        response = _request('/auth/login', {'username': username, 'password': password})
        token = response.get('access_token')
        if not token:
            return None
        _LAST_TOKEN = token
        from offline_store import set_api_token
        set_api_token(token)
        return token
    except Exception:
        return None

def clear_online_credentials():
    global _LAST_TOKEN, _ONLINE_CREDENTIALS, _SETUP_ADMIN_USER, _SETUP_ADMIN_UNTIL, _SETUP_ADMIN_TOKEN, _SETUP_CREDENTIALS
    _SETUP_ADMIN_USER = None
    _SETUP_ADMIN_UNTIL = 0.0
    _SETUP_ADMIN_TOKEN = None
    _SETUP_CREDENTIALS = None
    _LAST_TOKEN = None
    _ONLINE_CREDENTIALS = None
    from offline_store import set_api_token
    from auto_sync import stop_auto_sync
    stop_auto_sync()
    set_api_token(None)


def local_login(username,password):
    from offline_store import get_local_connection
    conn=get_local_connection(queue_writes=False)
    try:
        from sherif_local_identity import LOCAL_AUTH_KEY, authenticate, authorized_branch
        marker=conn.execute('SELECT value FROM local_meta WHERE key=?',(LOCAL_AUTH_KEY,)).fetchone()
        local_mode=conn.execute("SELECT 1 FROM local_meta WHERE key='sherif_local_mode' AND value='1'").fetchone()
        account=conn.execute('SELECT id FROM users WHERE username=?',(username.strip(),)).fetchone()
        pin_marker=conn.execute('SELECT 1 FROM local_meta WHERE key=?',('sherif_pin_user:'+str(account['id']),)).fetchone() if local_mode and account else None
        if (marker and marker[0]=='local_hash_v1') or pin_marker:
            user=authenticate(conn,username,password)
            if not user:return None
            from control_services import account_login_allowed
            if not account_login_allowed(conn,user['id']):return None
            authorized_branch(conn,user['id'])
            return user
    finally:conn.close()
    with _auth_conn() as c:
        row=c.execute('SELECT salt,verifier,iterations,user_json FROM logins WHERE username=?',(username.strip(),)).fetchone()
    if not row or not hmac.compare_digest(row[1],hashlib.pbkdf2_hmac('sha256',password.encode(),row[0],row[2])):
        return None
    user = json.loads(row[3])
    if not user.get('is_active', 1):
        return None
    from offline_store import get_local_connection
    conn = get_local_connection(queue_writes=False)
    try:
        current = conn.execute('SELECT id,role,branch_id,is_active FROM users WHERE id=? AND username=?', (user['id'],user['username'])).fetchone()
        if current is None or not current['is_active']:
            return None
        from control_services import account_login_allowed
        if not account_login_allowed(conn, user['id']):
            return None
        user.update(role=current['role'],branch_id=current['branch_id'])
    finally:
        conn.close()
    assert_device_branch(user, online=False)
    return user

def enroll_local_identity(user):
    from offline_store import get_local_connection
    conn=get_local_connection()
    try:
        # No plaintext password stored in the application users table.
        conn.execute('INSERT INTO users(id,username,password,role,branch_id,is_active) VALUES(?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET username=excluded.username,role=excluded.role,branch_id=excluded.branch_id,is_active=1',
            (int(user['id']),str(user['username']), '',str(user['role']),user.get('branch_id')))
        conn.commit()
    finally: conn.close()

def bootstrap_reference_data():
    from offline_store import sync_reference_data
    ok, error = sync_reference_data()
    if not ok:
        raise ConnectionError(error)


def admin_register_device(device_id, branch_id, device_number, active=True, resume_existing=False, reconfigure=False, device_name=None, command_id=None, replacement_command_id=None, recovery=None):
    if not _LAST_TOKEN:
        raise ValueError('يلزم تسجيل دخول الإدارة عبر الإنترنت أولًا')
    return _request('/admin/devices', {
        'device_id':device_id,'branch_id':int(branch_id),
        'device_number':str(device_number).strip(),'is_active':bool(active),
        'resume_existing':bool(resume_existing),'reconfigure':bool(reconfigure),
        'client_features':['invoice_history_cancellations_v1','device_admin_commands_v1'],
        'device_name':device_name,'command_id':command_id,'replacement_command_id':replacement_command_id, **(recovery or {})}, (_setup_token() or _LAST_TOKEN))



def admin_list_devices():
    if not _LAST_TOKEN:
        raise ValueError('يلزم تسجيل دخول الإدارة عبر الإنترنت أولًا')
    return _request('/admin/devices', token=(_setup_token() or _LAST_TOKEN)).get('devices', [])



def assert_device_branch(user, online=False):
    """Enforce the configured device branch for every login, including managers."""
    from offline_store import get_device_id, get_local_connection
    device_id = get_device_id()
    conn = get_local_connection(queue_writes=False)
    try:
        meta = dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('bound_branch_id','bound_device_id','device_active','server_enrolled','setup_complete')").fetchall())
    finally:
        conn.close()
    if meta.get('device_active', '1') != '1' or meta.get('bound_device_id') != device_id:
        raise ValueError('الجهاز غير معتمد؛ يلزم تجهيزه من الإدارة أولًا')
    branch = meta.get('bound_branch_id')
    if not branch or not str(branch).isdigit():
        raise ValueError('حدد فرع الجهاز أولًا من تجهيز الجهاز')
    if meta.get('server_enrolled')=='1' and meta.get('setup_complete')!='1':
        raise ValueError('لم يكتمل تنزيل بيانات الفرع وتجهيز الدخول المحلي')
    if online:
        approved=_request('/devices/'+device_id,token=_LAST_TOKEN)
        if not approved.get('is_active') or str(approved.get('branch_id'))!=str(branch):
            raise ValueError('اعتماد الجهاز متوقف أو لا يطابق الفرع')
    role = str(user.get('role') or '')
    if role != 'Cashier':
        return
    if str(user.get('branch_id')) != str(branch):
        raise ValueError('حساب الكاشير غير تابع للفرع المعتمد لهذا الجهاز')


def local_device_info():
    """Single source of device identity; legacy branch_id remains an alias."""
    from offline_store import get_local_connection
    conn = get_local_connection(queue_writes=False)
    try:
        return dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('branch_id','bound_branch_id','bound_device_id','device_name','device_number','device_active','server_enrolled','device_token','setup_complete')").fetchall())
    finally:
        conn.close()


def configure_local_device(branch_id, device_name, device_number, active=True, command_id=None, replacement_command_id=None, recovery=None):
    """Super Admin enrollment; retain identity and persist a crash-recovery intent."""
    from offline_store import get_device_id,get_local_connection,_SYNC_LOCK
    branch_id=int(branch_id);device_name=str(device_name).strip();device_number=str(device_number).strip()
    if not device_number.isascii() or not device_number.isdecimal() or not 1<=int(device_number)<=999999999:
        raise ValueError('رقم الجهاز يجب أن يكون رقمًا موجبًا')
    device_number=str(int(device_number))
    if not device_name or len(device_name)>80:raise ValueError('اكتب اسم الجهاز بصورة صحيحة')
    admin=setup_admin_user()
    if not admin:raise ValueError('يلزم اعتماد الإدارة عبر الإنترنت')
    with _SYNC_LOCK:
        old=local_device_info();device_id=get_device_id()
        branch_changed=str(old.get('bound_branch_id') or old.get('branch_id') or branch_id)!=str(branch_id)
        changed=branch_changed or str(old.get('device_number') or device_number).lstrip('0')!=device_number
        if recovery and admin['role']!='Super_Admin':raise ValueError('نقل التسجيل يتطلب Super_Admin نشطًا')
        if branch_changed and not recovery:
            raise ValueError('اختر نقل تسجيل الجهاز بواسطة Super_Admin لتأمين سجل الفرع السابق')
        conn=get_local_connection(queue_writes=False)
        previous_intent=None
        try:
            conn.execute('BEGIN IMMEDIATE')
            previous_intent=conn.execute("SELECT value FROM local_meta WHERE key='device_reconfigure_intent'").fetchone()
            changed=changed or bool(previous_intent) or bool(recovery)
            if recovery:
                admin=setup_admin_user()
                if not admin or admin['role']!='Super_Admin':raise ValueError('يلزم قرار Super Admin بمصادقة السيرفر')
                if previous_intent:
                    saved=json.loads(previous_intent[0])
                    if saved.get('recovery'):
                        if (saved['branch_id'],saved['device_number'])!=(branch_id,device_number):raise ValueError('استكمل هدف التسجيل المحفوظ أولًا')
                        recovery=saved['recovery']
            if changed:
                for table in ('invoices','sync_queue','erp_outbox'):
                    if conn.execute('SELECT 1 FROM '+table+" WHERE COALESCE(sync_status,'pending') NOT IN ('synced','ignored','cancelled_reset') LIMIT 1").fetchone():
                        raise ValueError('توجد معاملات معلقة؛ لا يمكن نقل الجهاز أو تغيير رقمه قبل تأكيد إرسالها')
                if conn.execute('SELECT 1 FROM transfer_logs WHERE receipt_pending=1 LIMIT 1').fetchone():
                    raise ValueError('يوجد استلام تزويد معلق؛ أكمل مزامنته قبل تغيير التسجيل')
                if conn.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():
                    raise ValueError('توجد تسوية محلية معلقة؛ أكمل مزامنتها قبل تغيير التسجيل')
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_shift_uploads'").fetchone():
                    cancelled=" AND COALESCE(u.cancelled_reset_id,'')=''" if 'cancelled_reset_id' in {r[1] for r in conn.execute('PRAGMA table_info(local_shift_uploads)')} else ''
                    historical=" AND NOT EXISTS (SELECT 1 FROM local_meta a WHERE a.key='historical_unconfirmed_shift:'||s.shift_uuid AND a.value='approved_unconfirmed_no_financial_effect')" if 'shift_uuid' in {r[1] for r in conn.execute('PRAGMA table_info(shift_closures)')} else ''
                    unsent_shift=conn.execute('SELECT 1 FROM shift_closures s LEFT JOIN local_shift_uploads u ON u.branch_id=s.branch_id AND u.shift_date=s.shift_date AND u.shift_number=s.shift_number WHERE u.synced_at IS NULL'+cancelled+historical+' LIMIT 1').fetchone()
                else:unsent_shift=conn.execute('SELECT 1 FROM shift_closures LIMIT 1').fetchone()
                if unsent_shift:raise ValueError('توجد وردية مغلقة بانتظار إيصال المزامنة؛ أكمل إرسالها قبل تغيير التسجيل')
                for row in conn.execute("SELECT value FROM local_meta WHERE key LIKE 'pos_sale_draft:v1:%'"):
                    draft=json.loads(row[0])
                    if draft.get('state')=='open' and draft.get('cart'):
                        raise ValueError('توجد سلة بيع مفتوحة؛ احفظها وأنهِ العمل قبل تغيير تسجيل الجهاز')
                if branch_changed and conn.execute("SELECT 1 FROM invoices WHERE COALESCE(shift_status,'open')<>'Z_Closed' LIMIT 1").fetchone():
                    from views.branch_shift_state import cached_state
                    old_branch=int(old.get('bound_branch_id') or old.get('branch_id'))
                    state=cached_state(conn,old_branch)
                    generation=conn.execute("SELECT value FROM local_meta WHERE key='sync_generation'").fetchone()
                    valid=state and state.get('device_id')==device_id and str(state.get('generation') or '')==str(generation[0] if generation else '')
                    proofs=state.get('closed_receipts',{}) if valid else {}
                    for invoice in conn.execute("SELECT branch_id,offline_uuid,invoice_number,remote_invoice_id FROM invoices WHERE COALESCE(shift_status,'open')<>'Z_Closed'"):
                        proof=proofs.get(invoice['offline_uuid'])
                        if invoice['branch_id']!=old_branch or not proof or proof['invoice_number']!=invoice['invoice_number'] or proof['remote_invoice_id']!=invoice['remote_invoice_id']:
                            raise ValueError('توجد وردية محلية لم يُثبت إغلاق فواتيرها؛ يلزم مطابقتها قبل نقل الجهاز إلى فرع آخر')
                intent=json.dumps({'device_id':device_id,'branch_id':branch_id,'device_number':device_number,'device_name':device_name,'recovery':recovery},ensure_ascii=False)
                conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_reconfigure_intent',?)",(intent,))
                conn.commit();conn.execute('BEGIN IMMEDIATE')
            archive=None
            if recovery and branch_changed:
                from views.device_recovery_client import prepare_branch_archive
                # The archive is created before the server change; it is never uploaded.
                archive=prepare_branch_archive(conn,recovery['recovery_id'])
            approved=admin_register_device(device_id,branch_id,device_number,active,
                resume_existing=old.get('setup_complete')!='1' or (not old.get('device_token') and old.get('bound_device_id')==device_id),
                reconfigure=changed and old.get('bound_device_id')==device_id,device_name=device_name,command_id=command_id,replacement_command_id=replacement_command_id,recovery=dict(recovery,recovery_local_safe=True) if recovery else None)
            if str(approved.get('device_id'))!=device_id or int(approved.get('branch_id',-1))!=branch_id or str(approved.get('device_number'))!=device_number or not approved.get('device_token'):
                raise ValueError('استجابة اعتماد الجهاز غير مكتملة؛ يلزم إعادة تأكيد التسجيل من Super Admin')
            if recovery and approved.get('recovery_id')!=recovery['recovery_id']:raise ValueError('السيرفر لم يؤكد إجراء الاستعادة؛ لم يُستبدل الفرع المحلي')
            if archive:
                from views.device_recovery_client import isolate_archived_branch
                isolate_archived_branch(conn,*archive)
            values={'branch_id':str(branch_id),'bound_branch_id':str(branch_id),'bound_device_id':device_id,'device_name':device_name,'device_number':device_number,'device_active':'1' if active else '0','server_enrolled':'1','device_token':approved['device_token'],'setup_complete':'1' if old.get('setup_complete')=='1' and not branch_changed and not recovery else '0'}
            conn.executemany('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',values.items())
            if recovery:
                conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_recovery_download_pending',?)",(json.dumps({'recovery':recovery,'branch_id':branch_id,'device_number':device_number},ensure_ascii=False),))
            if recovery:
                retired_intent=conn.execute("SELECT value FROM local_meta WHERE key='device_lifecycle_intent'").fetchone()
                if retired_intent:
                    action=json.loads(retired_intent[0])
                    if action.get('action')=='retire' and action.get('device_id')==device_id:
                        conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)",('device_lifecycle_superseded:'+str(action['command_id']),retired_intent[0]))
                        conn.execute("DELETE FROM local_meta WHERE key='device_lifecycle_intent'")
            conn.execute("DELETE FROM local_meta WHERE key='device_registration_blocked'")
            if command_id:conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_change_ack_pending',?)",(str(command_id),))
            conn.execute("DELETE FROM local_meta WHERE key='device_reconfigure_intent'")
            conn.commit()
        except Exception as error:
            conn.rollback()
            cause=getattr(error,'__cause__',None)
            if not previous_intent and isinstance(cause,HTTPError) and cause.code in (400,401,403,404,409,422):
                # The server's rejected transaction is rolled back; no half-move occurred.
                conn.execute("DELETE FROM local_meta WHERE key='device_reconfigure_intent'");conn.commit()
            # Network uncertainty retains the intent: block new financial writes
            # until the same Super Admin retries this identity and target safely.
            raise
        finally:conn.close()





def setup_branches():
    if not _LAST_TOKEN:
        raise ValueError('سجّل دخول Super Admin عبر الإنترنت أولًا')
    response = _request('/admin/devices/branches', token=(_setup_token() or _LAST_TOKEN))
    branches = response.get('branches')
    if not isinstance(branches, list):
        raise ValueError('تعذر قراءة قائمة الفروع المعتمدة')
    return branches


def complete_device_setup():
    from offline_store import sync_branch_reset_commands
    reset_result=sync_branch_reset_commands()
    if not reset_result.get('ok'):raise ValueError(reset_result.get('error','يلزم استكمال إجراء الفرع'))
    from offline_store import sync_reference_data, sync_offline_users, get_local_connection
    ok, error = sync_offline_users()
    if not ok:
        raise ConnectionError(error)
    ok, error = sync_reference_data()
    if not ok:
        # An already prepared device keeps its existing inventory and credentials.
        # A fresh device is never declared ready without its first complete snapshot.
        if local_device_info().get('setup_complete')!='1':
            raise ConnectionError(error)
        return
    conn = get_local_connection(queue_writes=False)
    try:
        conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('setup_complete','1')")
        conn.execute("DELETE FROM local_meta WHERE key='device_recovery_download_pending'")
        conn.commit()
    finally:
        conn.close()


def device_auth_headers():
    info = local_device_info()
    if info.get('device_token') and info.get('bound_device_id') and info.get('device_active') == '1':
        return {'X-Device-ID': info['bound_device_id'], 'X-Device-Token': info['device_token']}
    return {}

def provision_offline_users(data, branch_id):
    """Apply verifier-only enrollment and revocations in one attached SQLite transaction."""
    from offline_store import get_local_connection, _sqlite_value
    if data.get('protocol') != 2 or int(data.get('branch_id', -1)) != int(branch_id):
        raise ValueError('يلزم تحديث خدمة تجهيز الدخول المحلي على السيرفر؛ لم تُقبل كلمات مرور أصلية')
    records = data.get('users')
    if not isinstance(records, list):
        raise ValueError('قائمة المستخدمين غير مكتملة')
    prepared = []
    for row in records:
        if (not isinstance(row, dict) or row.get('role') != 'Cashier'
                or int(row.get('branch_id') or -1) != int(branch_id) or row.get('password')):
            raise ValueError('بيانات اعتماد خارج الفرع أو تحتوي كلمة مرور أصلية')
        user = {key: row.get(key) for key in ('id','username','role','branch_id','is_active')}
        if user['is_active']:
            auth = row.get('offline_auth') or {}
            if auth.get('scheme') != 'pbkdf2_sha256' or not 100000 <= int(auth.get('iterations', 0)) <= 2000000:
                raise ValueError('صيغة اعتماد محلي غير مدعومة')
            salt, verifier = bytes.fromhex(auth['salt']), bytes.fromhex(auth['verifier'])
            if len(salt) != 16 or len(verifier) != 32:
                raise ValueError('اعتماد محلي غير مكتمل')
            prepared.append((row,user,salt,verifier,int(auth['iterations'])))
        else:
            prepared.append((row,user,None,None,None))
    conn = get_local_connection(queue_writes=False)
    try:
        conn.execute('ATTACH DATABASE ? AS auth_cache', (str(AUTH_DB),))
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('CREATE TABLE IF NOT EXISTS auth_cache.logins(username TEXT PRIMARY KEY,salt BLOB NOT NULL,verifier BLOB NOT NULL,iterations INTEGER NOT NULL,user_json TEXT NOT NULL)')
        for row,user,salt,verifier,rounds in prepared:
            conn.execute("""INSERT INTO users(id,username,password,role,branch_id,is_active,phone,allowed_branches,custom_permissions)
                VALUES(?,?,'',?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                username=excluded.username,password='',role=excluded.role,branch_id=excluded.branch_id,
                is_active=excluded.is_active,phone=excluded.phone,allowed_branches=excluded.allowed_branches,custom_permissions=excluded.custom_permissions""",
                (user['id'],user['username'],user['role'],user['branch_id'],int(bool(user['is_active'])),
                 row.get('phone') or '',row.get('allowed_branches') or '',row.get('custom_permissions') or ''))
            if user['is_active']:
                conn.execute('INSERT OR REPLACE INTO auth_cache.logins VALUES(?,?,?,?,?)',
                             (user['username'],salt,verifier,rounds,json.dumps(user,ensure_ascii=False)))
            else:
                conn.execute('UPDATE auth_cache.logins SET user_json=? WHERE username=?',
                             (json.dumps(user,ensure_ascii=False),user['username']))
        conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('last_users_download',?)",
                     (__import__('datetime').datetime.now().isoformat(timespec='seconds'),))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True, None


# A remembered application session is never authority to provision a workstation.
_SETUP_ADMIN_USER = None
_SETUP_ADMIN_UNTIL = 0.0
_SETUP_ADMIN_TOKEN = None
_SETUP_CREDENTIALS = None
_SETUP_TOKEN_LOCK = __import__('threading').RLock()


def _renew_setup_token(previous=None):
    """Reauthenticate the same active setup actor; credentials never leave RAM."""
    global _LAST_TOKEN, _SETUP_ADMIN_TOKEN, _SETUP_ADMIN_UNTIL
    import time
    with _SETUP_TOKEN_LOCK:
        if previous and _SETUP_ADMIN_TOKEN and previous != _SETUP_ADMIN_TOKEN:
            return _SETUP_ADMIN_TOKEN
        if not _SETUP_ADMIN_USER or not _SETUP_CREDENTIALS:
            raise ValueError('يلزم تسجيل دخول الإدارة عبر الإنترنت من جديد')
        username, password = _SETUP_CREDENTIALS
        response = _request('/auth/login', {'username':username,'password':password}, _auth_retry=False)
        user = response.get('user') or {}
        if (user.get('id') != _SETUP_ADMIN_USER['id'] or
                user.get('role') != _SETUP_ADMIN_USER['role'] or not user.get('is_active', 1)):
            finish_setup_authentication()
            raise ValueError('تغير حساب الإدارة أو صلاحياته؛ يلزم تسجيل دخوله من جديد')
        token = response.get('access_token')
        if not isinstance(token,str) or not token:
            raise ConnectionError('لم يكتمل تجديد اعتماد الإدارة؛ لم يُنفذ إجراء الجهاز')
        lifetime = min(900,max(1,int(response.get('expires_in',900))))
        _SETUP_ADMIN_TOKEN = _LAST_TOKEN = token
        _SETUP_ADMIN_UNTIL = time.monotonic() + lifetime
        from offline_store import set_api_token
        set_api_token(token)
        return token


def _setup_token():
    import time
    if not _SETUP_ADMIN_USER or not _SETUP_ADMIN_TOKEN:return None
    if time.monotonic() >= _SETUP_ADMIN_UNTIL - 30:
        return _renew_setup_token(_SETUP_ADMIN_TOKEN)
    return _SETUP_ADMIN_TOKEN


def setup_admin_user():
    if _setup_token():return dict(_SETUP_ADMIN_USER)
    return None


def authenticate_setup_admin(username, password):
    """Online-only setup authentication; do not start sync or provision local users."""
    global _LAST_TOKEN, _ONLINE_CREDENTIALS, _SETUP_ADMIN_USER, _SETUP_ADMIN_UNTIL, _SETUP_ADMIN_TOKEN, _SETUP_CREDENTIALS
    import time
    clear_online_credentials()
    if not isinstance(username, str) or not username.strip() or len(username.strip()) > 100:
        raise ValueError('اكتب اسم مستخدم Super Admin الصحيح.')
    if not isinstance(password, str) or not password or len(password) > 256:
        raise ValueError('اكتب كلمة مرور Super Admin.')
    response = _request('/auth/login', {'username': username.strip(), 'password': password})
    user = response.get('user')
    if (not isinstance(user, dict) or user.get('role') not in ('Super_Admin','Admin','Manager')
            or not user.get('is_active', 1) or not user.get('id') or not user.get('username')):
        raise ValueError('الاستبدال يتطلب حساب Super Admin أو Admin أو المدير العام؛ التسجيل الجديد دون استبدال يظل للسوبر أدمن.')
    token = response.get('access_token')
    if not isinstance(token, str) or not token:
        raise ConnectionError('استجابة مصادقة الإدارة لا تحتوي رمز اعتماد صالحاً.')
    try:
        lifetime = min(900, max(1, int(response.get('expires_in', 900))))
    except (TypeError, ValueError):
        raise ConnectionError('استجابة مصادقة الإدارة غير مكتملة.')
    _SETUP_ADMIN_USER = {key: user.get(key) for key in ('id', 'username', 'role', 'branch_id', 'is_active')}
    _SETUP_ADMIN_UNTIL = time.monotonic() + lifetime
    _SETUP_ADMIN_TOKEN = token
    _SETUP_CREDENTIALS = (username.strip(), password)
    _LAST_TOKEN = token
    _ONLINE_CREDENTIALS = None
    from offline_store import set_api_token
    set_api_token(token)
    return dict(_SETUP_ADMIN_USER)


def finish_setup_authentication():
    """Revoke the setup grant without discarding the current online API token."""
    global _SETUP_ADMIN_USER, _SETUP_ADMIN_UNTIL, _SETUP_ADMIN_TOKEN, _SETUP_CREDENTIALS
    _SETUP_ADMIN_USER = None
    _SETUP_ADMIN_UNTIL = 0.0
    _SETUP_ADMIN_TOKEN = None
    _SETUP_CREDENTIALS = None


def verify_local_user_password(user_id, password):
    """Confirm the current active local identity using its existing offline verifier."""
    if not isinstance(password, str) or not password:
        return False
    try:
        expected_id = int(user_id)
    except (TypeError, ValueError):
        return False
    if expected_id <= 0:
        return False
    from offline_store import get_local_connection
    conn = get_local_connection(queue_writes=False)
    try:
        current = conn.execute('SELECT id,username,is_active FROM users WHERE id=?',
                               (expected_id,)).fetchone()
    finally:
        conn.close()
    if current is None or not current['is_active']:
        return False
    try:
        confirmed = local_login(current['username'], password)
    except (ValueError, TypeError, KeyError):
        return False
    return confirmed is not None and int(confirmed['id']) == expected_id


def admin_assign_settlement_device(branch_id,device_id):
    if not _LAST_TOKEN:raise ValueError('يلزم دخول Super_Admin أونلاين')
    return _request('/admin/settlement-authority',{'branch_id':int(branch_id),'device_id':device_id},(_setup_token() or _LAST_TOKEN))



def admin_release_settlement_device():
    if not _LAST_TOKEN:raise ValueError('يلزم دخول Super_Admin أونلاين')
    from offline_store import get_local_connection,get_device_id
    conn=get_local_connection(queue_writes=False)
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():
            raise ValueError('لا يمكن نقل التفويض قبل تأكيد جميع طلبات هذا الجهاز')
        authority=conn.execute('SELECT authority_uuid,branch_id FROM branch_settlement_authorities WHERE device_id=?',(get_device_id(),)).fetchone()
        if not authority:raise ValueError('هذا الجهاز لا يمتلك تفويض تسويات')
        # Disable durably BEFORE the network call. A lost response must not re-enable it.
        conn.execute('UPDATE branch_settlement_authorities SET is_released=1 WHERE branch_id=?',(authority['branch_id'],))
        conn.commit()
    except Exception:conn.rollback();raise
    finally:conn.close()
    response=_request('/admin/settlement-authority/release',{'authority_uuid':authority['authority_uuid']},(_setup_token() or _LAST_TOKEN))
    if response.get('released') is not True or response.get('authority_uuid')!=authority['authority_uuid']:
        raise ValueError('لم يصل تأكيد موثوق لتحرير الجهاز؛ يظل متوقفاً عن التسويات')
    return response



def admin_device_registry():
    if not _LAST_TOKEN:raise ValueError('يلزم تسجيل دخول Super Admin أونلاين')
    return _request('/admin/devices',token=(_setup_token() or _LAST_TOKEN))


def admin_request_device_change(device_id,branch_id,number,name):
    if not _LAST_TOKEN:raise ValueError('يلزم تسجيل دخول Super Admin أونلاين')
    return _request('/admin/devices/change-request',{'device_id':device_id,'branch_id':int(branch_id),'device_number':str(number),'device_name':name},(_setup_token() or _LAST_TOKEN))


def admin_cancel_device_change(command_id):
    if not _LAST_TOKEN:raise ValueError('يلزم تسجيل دخول Super Admin أونلاين')
    return _request('/admin/devices/cancel-change',{'command_id':command_id},(_setup_token() or _LAST_TOKEN))


def acknowledge_pending_device_change():
    from offline_store import get_local_connection,_current_api_token
    conn=get_local_connection(queue_writes=False)
    try:
        meta=dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('device_change_ack_pending','setup_complete')"))
        command=meta.get('device_change_ack_pending')
        if not command or meta.get('setup_complete')!='1':return False
        token=_LAST_TOKEN or _current_api_token()
        if not token:return False
        reply=_request('/devices/change-ack',{'command_id':command},token)
        if reply.get('status')!='applied' or reply.get('command_id')!=command:raise ValueError('لم يؤكد السيرفر إيصال تعديل تسجيل الجهاز')
        conn.execute("DELETE FROM local_meta WHERE key='device_change_ack_pending' AND value=?",(command,));conn.commit();return True
    finally:conn.close()


def admin_request_device_action(device_id,action,confirm):
    if not _LAST_TOKEN:raise ValueError('يلزم دخول Super Admin أونلاين')
    return _request('/admin/devices/lifecycle',{'device_id':device_id,'action':action,'confirm':confirm},(_setup_token() or _LAST_TOKEN))



def apply_local_device_action(command):
    """Explicit local Super Admin confirmation; retain UUID, invoices and auth stores."""
    if not setup_admin_user() or not _LAST_TOKEN:raise ValueError('يلزم اعتماد Super Admin من تجهيز الجهاز')
    from offline_store import get_local_connection,get_device_id,_SYNC_LOCK
    from views.device_lifecycle import assert_local_safe
    identity=get_device_id();command_id=str(command['command_id']);action=command['action']
    if command.get('device_id')!=identity or action not in ('retire','reinitialize'):raise ValueError('الأمر لا يخص هذا الجهاز')
    with _SYNC_LOCK:
        info=local_device_info()
        if int(info.get('bound_branch_id') or 0)!=int(command['branch_id']) or str(info.get('device_number'))!=str(command['device_number']):raise ValueError('تسجيل الجهاز لا يطابق الأمر')
        c=get_local_connection(queue_writes=False)
        try:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute("SELECT value FROM local_meta WHERE key='device_lifecycle_intent'").fetchone()
            if old:
                if json.loads(old[0])!=command:raise ValueError('يوجد إجراء جهاز آخر غير مكتمل')
            else:
                assert_local_safe(c,action)
                c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_lifecycle_intent',?)",(json.dumps(command,sort_keys=True),))
            assert_local_safe(c,action)
            c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('setup_complete','0')");c.commit()
            if action=='reinitialize':complete_device_setup()
            reply=_request('/devices/lifecycle-ack',{'command_id':command_id},_LAST_TOKEN)
            if reply.get('command_id')!=command_id or reply.get('action')!=action or reply.get('status')!='applied':raise ValueError('لم يصل تأكيد موثوق؛ يبقى الجهاز في وضع التجهيز')
            c.execute('BEGIN IMMEDIATE')
            if action=='retire':
                c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_active','0')")
                c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('setup_complete','0')")
            c.execute("DELETE FROM local_meta WHERE key='device_lifecycle_intent'");c.commit()
            return reply
        except Exception:
            c.rollback()
            # Even a completed snapshot must not reopen sales before its receipt.
            if c.execute("SELECT 1 FROM local_meta WHERE key='device_lifecycle_intent'").fetchone():
                c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('setup_complete','0')");c.commit()
            raise
        finally:c.close()


def admin_update_distribution():
    if not _LAST_TOKEN:raise ValueError('يلزم تسجيل دخول Super Admin أونلاين')
    return _request('/admin/updates',token=(_setup_token() or _LAST_TOKEN))



def admin_set_update_distribution(sequence,mode,branch_id):
    if not _LAST_TOKEN:raise ValueError('يلزم تسجيل دخول Super Admin أونلاين')
    return _request('/admin/updates/scope',{'release_seq':int(sequence),'mode':mode,'branch_id':branch_id},(_setup_token() or _LAST_TOKEN))




def admin_prepare_device(device_id,branch_id,number,name):
    if not _LAST_TOKEN:raise ValueError('يلزم دخول Super Admin أونلاين')
    return _request('/admin/devices',{'device_id':device_id,'branch_id':int(branch_id),'device_number':str(number),'device_name':name,'prepare_only':True},(_setup_token() or _LAST_TOKEN))



def admin_device_invoices(device_id,branch_id,page=1):
    import uuid
    if not _LAST_TOKEN:raise ValueError('يلزم تسجيل دخول الإدارة أونلاين')
    identity=str(uuid.UUID(str(device_id)))
    return _request('/admin/devices/'+identity+'/invoices?branch_id='+str(int(branch_id))+'&page='+str(int(page)),token=(_setup_token() or _LAST_TOKEN))



def admin_request_device_replacement(old_device_id,new_device_id,confirm,immediate=False):
    if not _LAST_TOKEN:raise ValueError('يلزم تسجيل دخول الإدارة عبر الإنترنت')
    return _request('/admin/devices/replacement',{'old_device_id':old_device_id,'new_device_id':new_device_id,'confirm':confirm,'immediate':bool(immediate)},(_setup_token() or _LAST_TOKEN))



def admin_replace_damaged_device(branch_id,device_number,new_device_id,confirmed=False,accept_unrecovered=False):
    if not _LAST_TOKEN:raise ValueError('يلزم تسجيل دخول Super Admin عبر الإنترنت')
    return _request('/admin/devices/replacement',{'branch_id':int(branch_id),'device_number':str(device_number),'new_device_id':new_device_id,'damaged':True,'confirmed':bool(confirmed),'accept_unrecovered':bool(accept_unrecovered)},(_setup_token() or _LAST_TOKEN))


_REGISTRATION_POLL_LOCK = __import__('threading').Lock()
_REGISTRATION_LAST_ATTEMPT = 0.0

def refresh_device_registration(force=False):
    """Device-only HTTPS state; no identity regeneration or user-session renewal."""
    import time,requests
    global _REGISTRATION_LAST_ATTEMPT
    from offline_store import get_local_connection,_api_base_url
    if not _REGISTRATION_POLL_LOCK.acquire(blocking=False):return {'state':'checking'}
    try:
        now=time.monotonic()
        if not force and now-_REGISTRATION_LAST_ATTEMPT<30:return {'state':'throttled'}
        _REGISTRATION_LAST_ATTEMPT=now
        c=get_local_connection(queue_writes=False)
        try:before=dict(c.execute('SELECT key,value FROM local_meta').fetchall())
        finally:c.close()
        identity=before.get('bound_device_id');credential=before.get('device_token')
        if not identity or not credential or before.get('device_id')!=identity:return {'state':'not_prepared'}
        response=requests.get(_api_base_url()+'/devices/registration-state',headers={'X-Device-ID':identity,'X-Device-Token':credential},timeout=4,allow_redirects=False)
        blocked=False;reason=None
        if response.status_code==403:
            detail=response.json().get('detail',{})
            if not isinstance(detail,dict) or detail.get('code')!='device_registration_invalid' or detail.get('device_id')!=identity:
                return {'state':'unconfirmed'}
            blocked=True;reason='registration_removed_or_credential_revoked'
        elif response.status_code==200:
            value=response.json()
            if value.get('device_id')!=identity or type(value.get('is_active')) is not bool:return {'state':'unconfirmed'}
            if not value['is_active']:blocked=True;reason='registration_inactive'
            elif (str(value.get('branch_id'))!=str(before.get('bound_branch_id')) or str(value.get('device_number'))!=str(before.get('device_number'))):
                blocked=True;reason='registration_changed_requires_local_approval'
        else:return {'state':'unavailable' if response.status_code!=404 else 'server_upgrade_required'}
        c=get_local_connection(queue_writes=False)
        try:
            c.execute('BEGIN IMMEDIATE')
            current=dict(c.execute('SELECT key,value FROM local_meta').fetchall())
            # Never let a delayed reply invalidate a newly approved credential.
            if any(current.get(k)!=before.get(k) for k in ('bound_device_id','device_token','bound_branch_id','device_number')):
                c.rollback();return {'state':'superseded'}
            c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('last_device_registration_check',?)",(str(time.time()),))
            if blocked:
                c.executemany('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',[
                    ('device_active','0'),('setup_complete','0'),('device_registration_blocked',reason)])
            # Active state confirms the current registration; it never reactivates
            # a previously blocked client without official local enrollment.
            elif current.get('device_active')=='1' and not current.get('device_registration_blocked'):
                c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_registration_state','active')")
            c.commit()
            return {'state':'approval_required' if blocked or current.get('device_registration_blocked') or current.get('device_active')!='1' else 'active'}
        except Exception:c.rollback();raise
        finally:c.close()
    except (requests.RequestException,OSError,ValueError):
        return {'state':'offline_or_unconfirmed'}
    finally:_REGISTRATION_POLL_LOCK.release()

def start_device_registration_monitor():
    import builtins,threading
    prior=getattr(builtins,'_abuzaid_registration_monitor',None)
    if prior and prior.is_alive():return
    def run():
        while True:
            try:refresh_device_registration()
            except Exception:pass  # No user credentials or raw transport errors logged.
            __import__('time').sleep(30)
    worker=threading.Thread(target=run,name='abuzaid-device-registration',daemon=True)
    builtins._abuzaid_registration_monitor=worker;worker.start()
