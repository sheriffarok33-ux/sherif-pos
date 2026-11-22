"""Durable branch reset generations and per-workstation execution receipts."""
import json,uuid,hmac
from views.device_registry import execute,super_admin
from views.branch_reset_plan import normalized,make_plan,fingerprint,apply_plan,scalar,quote

def ensure_schema(conn):
    execute(conn,'''CREATE TABLE IF NOT EXISTS branch_reset_state(branch_id INTEGER PRIMARY KEY REFERENCES branches(id),generation TEXT NOT NULL,reset_id TEXT NOT NULL,updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    execute(conn,'''CREATE TABLE IF NOT EXISTS branch_reset_commands(reset_id TEXT PRIMARY KEY,reset_seq BIGSERIAL UNIQUE,branch_id INTEGER NOT NULL REFERENCES branches(id),generation TEXT NOT NULL,choices_json TEXT NOT NULL,requested_by INTEGER NOT NULL,created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    execute(conn,'''CREATE TABLE IF NOT EXISTS branch_reset_devices(reset_id TEXT NOT NULL REFERENCES branch_reset_commands(reset_id),device_id TEXT NOT NULL REFERENCES branch_devices(device_id),status TEXT NOT NULL DEFAULT 'pending',error TEXT,applied_at TIMESTAMP,PRIMARY KEY(reset_id,device_id))''')

def head(conn,branch_id):
    if not scalar(execute(conn,"SELECT to_regclass('branch_reset_state')").fetchone()):return None
    row=execute(conn,'SELECT s.branch_id,s.generation,s.reset_id,c.reset_seq FROM branch_reset_state s JOIN branch_reset_commands c ON c.reset_id=s.reset_id WHERE s.branch_id=?',(int(branch_id),)).fetchone()
    return dict(row) if row else None

def check_upload_generation(conn,branch_id,generation):
    # Shared upload locks permit concurrent sales; reset takes the exclusive lock.
    execute(conn,'SELECT pg_advisory_xact_lock_shared(hashtextextended(?,0))',('branch-reset:'+str(int(branch_id)),))
    current=head(conn,branch_id)
    if not current:return False
    if not hmac.compare_digest(str(generation or ''),current['generation']):
        raise ValueError('branch_reset_required: يوجد أمر تصفير معتمد لهذا الفرع؛ يلزم تطبيقه محليًا قبل رفع أي حركات قديمة')
    return True

def preview(conn,actor,branch_id,choices):
    super_admin(conn,actor);choices=normalized(choices);branch_id=int(branch_id)
    branch=execute(conn,'SELECT id,branch_name FROM branches WHERE id=?',(branch_id,)).fetchone()
    if not branch:raise ValueError('الفرع غير موجود')
    plan=make_plan(conn,branch_id,choices)
    return {'branch_id':branch_id,'branch_name':branch['branch_name'],'choices':choices,'plan':plan,'fingerprint':fingerprint(branch_id,choices,plan),'request_id':str(uuid.uuid4()),
        'confirmation':'تصفير '+str(branch['branch_name']),
        'notice':'المعاينة تشمل التوابع المترابطة داخل الفرع فقط. الأرقام المحجوزة والهويات وسجلات التدقيق محفوظة. التصفير المالي الكامل يشمل دفاتر الفرع المرتبطة؛ الاختيارات الجزئية لا تصفر دفاتر غير محددة. الأجهزة تحتاج الإصدار18أو أحدث.'}

def perform(conn,actor,branch_id,choices,expected,confirmation,audit,request_id):
    super_admin(conn,actor);ensure_schema(conn);branch_id=int(branch_id);choices=normalized(choices)
    execute(conn,'SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('branch-reset:'+str(branch_id),))
    reset_id=str(uuid.UUID(request_id))
    previous=execute(conn,'SELECT branch_id,generation,choices_json,requested_by FROM branch_reset_commands WHERE reset_id=?',(reset_id,)).fetchone()
    if previous:
        if previous['branch_id']!=branch_id or previous['requested_by']!=actor or normalized(json.loads(previous['choices_json']))!=choices:raise ValueError('معرّف الطلب سبق استخدامه لعملية مختلفة')
        return {'reset_id':reset_id,'branch_id':branch_id,'generation':previous['generation'],'server_applied':True,'already_applied':True,'device_application_confirmed':False}
    devices=execute(conn,'SELECT device_id FROM branch_devices WHERE branch_id=? ORDER BY device_id FOR UPDATE',(branch_id,)).fetchall()
    reviewed=preview(conn,actor,branch_id,choices)
    if confirmation!=reviewed['confirmation'] or not hmac.compare_digest(expected,reviewed['fingerprint']):raise ValueError('تغيرت المعاينة أو لم يُكتب تأكيد الفرع الصحيح؛ لم يتم التصفير')
    # Lock only data tables in the reviewed plan, then verify counts again.
    for table in sorted({r['table'] for r in reviewed['plan']}):execute(conn,'LOCK TABLE '+quote(table)+' IN SHARE ROW EXCLUSIVE MODE')
    locked=preview(conn,actor,branch_id,choices)
    if locked['fingerprint']!=expected:raise ValueError('وصلت بيانات جديدة بعد المعاينة؛ راجع المعاينة ثم أكد من جديد')
    generation=str(uuid.uuid4())
    apply_plan(conn,locked['plan'])
    execute(conn,'INSERT INTO branch_reset_commands(reset_id,branch_id,generation,choices_json,requested_by) VALUES(?,?,?,?,?)',(reset_id,branch_id,generation,json.dumps(choices),actor))
    execute(conn,'INSERT INTO branch_reset_state(branch_id,generation,reset_id) VALUES(?,?,?) ON CONFLICT(branch_id) DO UPDATE SET generation=EXCLUDED.generation,reset_id=EXCLUDED.reset_id,updated_at=CURRENT_TIMESTAMP',(branch_id,generation,reset_id))
    for device in devices:execute(conn,'INSERT INTO branch_reset_devices(reset_id,device_id) VALUES(?,?)',(reset_id,device['device_id']))
    # A later explicitly authorized superset can safely replace failed/offline
    # older commands. Never skip an operation absent from the replacement.
    if 'pending' in choices:
        older=execute(conn,'SELECT reset_id,choices_json FROM branch_reset_commands WHERE branch_id=? AND reset_id<>?',(branch_id,reset_id)).fetchall()
        for old in older:
            if set(json.loads(old['choices_json']))-{'pending'}<=set(choices)-{'pending'}:
                execute(conn,"UPDATE branch_reset_devices SET status='superseded',error=? WHERE reset_id=? AND status IN ('pending','failed')",('يشمله الأمر الأحدث '+reset_id,old['reset_id']))
    audit(conn,'branch_data_reset',actor,branch_id,'branch_reset_commands',reset_id,
        details={'records':sum(r['count'] for r in locked['plan']),'fields':choices,'source_transaction_uuid':reset_id,'reason_code':'explicit_super_admin_branch_reset'},event_uuid=reset_id)
    return {'reset_id':reset_id,'branch_id':branch_id,'generation':generation,'devices_waiting':len(devices),'server_applied':True,'device_application_confirmed':False}

def commands_for_device(conn,device):
    current=head(conn,device['branch_id'])
    if not current:return {'head':None,'commands':[],'device_id':device['device_id'],'branch_id':device['branch_id']}
    rows=execute(conn,'''SELECT c.reset_id,c.reset_seq,c.branch_id,c.generation,c.choices_json,c.created_at,d.status
        FROM branch_reset_devices d JOIN branch_reset_commands c ON c.reset_id=d.reset_id
        WHERE d.device_id=? AND c.branch_id=? AND d.status IN ('pending','failed')
        ORDER BY c.reset_seq''',(device['device_id'],device['branch_id'])).fetchall()
    return {'head':current,'device_id':device['device_id'],'branch_id':device['branch_id'],'commands':[{'reset_id':r['reset_id'],'reset_seq':r['reset_seq'],'branch_id':r['branch_id'],'generation':r['generation'],'choices':json.loads(r['choices_json']),'device_id':device['device_id'],'required_release_seq':18} for r in rows]}

def acknowledge(conn,device,reset_id,generation,status,error=None):
    if status not in ('applied','failed'):raise ValueError('حالة إيصال غير صالحة')
    row=execute(conn,'''SELECT c.branch_id,c.generation,d.status FROM branch_reset_commands c
        JOIN branch_reset_devices d ON d.reset_id=c.reset_id WHERE c.reset_id=? AND d.device_id=? FOR UPDATE''',(reset_id,device['device_id'])).fetchone()
    if not row or row['branch_id']!=device['branch_id'] or row['generation']!=generation:raise ValueError('الإيصال لا يطابق الفرع أو الجهاز أو الجيل')
    if row['status']=='applied':return {'reset_id':reset_id,'status':'applied'}
    execute(conn,"UPDATE branch_reset_devices SET status=?,error=?,applied_at=CASE WHEN ?='applied' THEN CURRENT_TIMESTAMP ELSE NULL END WHERE reset_id=? AND device_id=?",(status,str(error or '')[:500] if status=='failed' else None,status,reset_id,device['device_id']))
    return {'reset_id':reset_id,'status':status}

def status(conn,actor,branch_id):
    super_admin(conn,actor)
    if not head(conn,branch_id):return []
    rows=execute(conn,'''SELECT c.reset_id,c.created_at,c.generation,d.device_id,b.device_number,
        CASE WHEN b.branch_id<>c.branch_id THEN 'failed' ELSE d.status END AS status,
        CASE WHEN b.branch_id<>c.branch_id THEN 'تغير ربط الجهاز؛ لم يطبق أمر فرع آخر' ELSE d.error END AS error,d.applied_at
        FROM branch_reset_commands c JOIN branch_reset_devices d ON d.reset_id=c.reset_id
        JOIN branch_devices b ON b.device_id=d.device_id WHERE c.branch_id=? ORDER BY c.created_at DESC,b.device_number''',(branch_id,)).fetchall()
    return [dict(r) for r in rows]

def assert_no_pending_resets(conn,device_id):
    if not scalar(execute(conn,"SELECT to_regclass('branch_reset_devices')").fetchone()):return
    if execute(conn,"SELECT 1 FROM branch_reset_devices WHERE device_id=? AND status IN ('pending','failed') LIMIT 1",(device_id,)).fetchone():raise ValueError('يوجد أمر تصفير ينتظر التطبيق؛ أكمله على الجهاز قبل تغيير فرعه أو رقمه')
