"""Branch-scoped device metadata and explicit, acknowledged change requests."""
import uuid

def execute(conn,sql,args=()):
    if hasattr(conn,'execute'):
        return conn.execute(sql,args) if args else conn.execute(sql)
    cur=conn.cursor()
    if args:cur.execute(sql.replace('?','%s'),args)
    else:cur.execute(sql)
    return cur

def super_admin(conn,actor):
    row=execute(conn,'SELECT role,is_active FROM users WHERE id=?',(actor,)).fetchone()
    if not row or not row['is_active'] or row['role']!='Super_Admin':raise PermissionError('يلزم Super Admin نشط')

def branch_administrator(conn,actor):
    row=execute(conn,'SELECT role,is_active FROM users WHERE id=?',(actor,)).fetchone()
    if not row or not row['is_active'] or row['role'] not in ('Super_Admin','Manager'):raise PermissionError('يلزم حساب إدارة فروع نشط')


def ensure_schema(conn):
    execute(conn,'ALTER TABLE branch_devices ADD COLUMN IF NOT EXISTS device_name TEXT')
    execute(conn,'''CREATE TABLE IF NOT EXISTS branch_device_changes(
        command_id TEXT PRIMARY KEY,device_id TEXT NOT NULL REFERENCES branch_devices(device_id),
        from_branch_id INTEGER NOT NULL,from_device_number TEXT NOT NULL,
        to_branch_id INTEGER NOT NULL,to_device_number TEXT NOT NULL,device_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',requested_by INTEGER NOT NULL,
        requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,applied_at TIMESTAMP,error TEXT)''')
    execute(conn,"CREATE UNIQUE INDEX IF NOT EXISTS branch_device_changes_pending ON branch_device_changes(device_id) WHERE status IN ('pending','awaiting_local_confirmation')")

def pending_changes(conn):
    row=execute(conn,"SELECT to_regclass('branch_device_changes') AS tbl").fetchone()
    if not row['tbl']:return []
    rows=execute(conn,"SELECT command_id,device_id,from_branch_id,from_device_number,to_branch_id,to_device_number,device_name,status,requested_at,applied_at,error FROM branch_device_changes WHERE status IN ('pending','awaiting_local_confirmation','failed') ORDER BY requested_at DESC").fetchall()
    return [dict(r) for r in rows]

def request_change(conn,actor,device_id,branch_id,number,name):
    branch_administrator(conn,actor);ensure_schema(conn)
    device_id=str(uuid.UUID(device_id));number=str(number).strip();name=str(name).strip();branch_id=int(branch_id)
    if not number.isascii() or not number.isdecimal() or not 1<=int(number)<=999999999:raise ValueError('رقم الجهاز يبدأ من1 داخل الفرع')
    number=str(int(number))
    if not name or len(name)>80:raise ValueError('اسم الجهاز مطلوب وبحد أقصى80حرفًا')
    execute(conn,'SELECT pg_advisory_xact_lock(hashtextextended(?,0))',(f'enroll:{branch_id}:{number}',))
    device=execute(conn,'SELECT device_id,branch_id,device_number,is_active FROM branch_devices WHERE device_id=? FOR UPDATE',(device_id,)).fetchone()
    if not device or not device['is_active']:raise ValueError('الجهاز غير موجود أو غير نشط؛ لم تتغير هويته')
    from views.device_lifecycle import list_actions
    if any(a['device_id']==device_id and a['status']=='pending' for a in list_actions(conn)):raise ValueError('أكمل إجراء الجهاز المعلق أولًا')
    from views.branch_reset_service import assert_no_pending_resets
    assert_no_pending_resets(conn,device_id)
    if not execute(conn,'SELECT id FROM branches WHERE id=? AND is_active=1',(branch_id,)).fetchone():raise ValueError('الفرع غير موجود أو غير نشط')
    conflict=execute(conn,"SELECT device_id FROM branch_devices WHERE branch_id=? AND is_active AND LTRIM(device_number,'0')=? AND device_id<>?",(branch_id,number,device_id)).fetchone()
    if conflict:raise ValueError('رقم الجهاز مستخدم بالفعل داخل الفرع المختار لهوية '+str(conflict['device_id']))
    current=execute(conn,"SELECT command_id FROM branch_device_changes WHERE device_id=? AND status IN ('pending','awaiting_local_confirmation') FOR UPDATE",(device_id,)).fetchone()
    if current:raise ValueError('يوجد تعديل محفوظ بانتظار اعتماد الجهاز أو إيصال التطبيق؛ أكمله أولًا')
    reserved=execute(conn,"SELECT device_id FROM branch_device_changes WHERE to_branch_id=? AND to_device_number=? AND status IN ('pending','awaiting_local_confirmation') AND device_id<>?",(branch_id,number,device_id)).fetchone()
    if reserved:raise ValueError('الرقم محجوز بطلب تعديل معلق لجهاز آخر داخل هذا الفرع')
    command=str(uuid.uuid4())
    execute(conn,'INSERT INTO branch_device_changes(command_id,device_id,from_branch_id,from_device_number,to_branch_id,to_device_number,device_name,requested_by) VALUES(?,?,?,?,?,?,?,?)',(command,device_id,device['branch_id'],device['device_number'],branch_id,number,name,actor))
    return {'command_id':command,'status':'pending','message':'تم حفظ طلب التعديل؛ يطبقه Super Admin من تجهيز الجهاز نفسه بعد تأمين معاملاته. لم تتغير الهوية أو الفواتير.'}

def validate_change(conn,command_id,device_id,branch_id,number,name):
    row=execute(conn,"SELECT * FROM branch_device_changes WHERE command_id=? AND device_id=? AND status IN ('pending','awaiting_local_confirmation') FOR UPDATE",(command_id,device_id)).fetchone()
    if not row:raise ValueError('طلب تعديل الجهاز غير موجود أو سبق إلغاؤه؛ أعد تحميل القائمة')
    if (int(row['to_branch_id'])!=int(branch_id) or str(row['to_device_number'])!=str(number) or str(row['device_name'])!=str(name)):
        raise ValueError('بيانات التعديل لا تطابق الطلب المعتمد؛ أعد تحميل تجهيز الجهاز')
    return dict(row)

def await_local_confirmation(conn,command_id):
    execute(conn,"UPDATE branch_device_changes SET status='awaiting_local_confirmation',error=NULL WHERE command_id=?",(command_id,))

def acknowledge_change(conn,device,command_id):
    row=execute(conn,'SELECT * FROM branch_device_changes WHERE command_id=? AND device_id=? FOR UPDATE',(command_id,device['device_id'])).fetchone()
    if not row or row['status'] not in ('awaiting_local_confirmation','applied'):raise ValueError('لا يوجد تعديل ينتظر إيصال التطبيق لهذا الجهاز')
    if int(row['to_branch_id'])!=int(device['branch_id']) or str(row['to_device_number'])!=str(device['device_number']):raise ValueError('تسجيل الجهاز لا يطابق طلب التعديل')
    execute(conn,"UPDATE branch_device_changes SET status='applied',applied_at=COALESCE(applied_at,CURRENT_TIMESTAMP),error=NULL WHERE command_id=?",(command_id,))
    return {'command_id':command_id,'status':'applied'}

def cancel_change(conn,actor,command_id):
    branch_administrator(conn,actor)
    row=execute(conn,'SELECT status FROM branch_device_changes WHERE command_id=? FOR UPDATE',(command_id,)).fetchone()
    if not row or row['status']!='pending':raise ValueError('يمكن إلغاء الطلب قبل تطبيقه مركزيًا فقط؛ بعد ذلك يلزم استكمال إيصال الجهاز')
    execute(conn,"UPDATE branch_device_changes SET status='cancelled' WHERE command_id=?",(command_id,))
    return {'command_id':command_id,'status':'cancelled'}

def list_registered(conn,actor):
    from views.device_lifecycle import replacement_administrator
    replacement_administrator(conn,actor)
    # to_jsonb supports registries created before device_name was introduced.
    heartbeat=execute(conn,"SELECT to_regclass('branch_device_heartbeats') AS tbl").fetchone()['tbl']
    last_seen=',h.last_seen_at,h.pending_invoices,h.pending_operations' if heartbeat else ',NULL AS last_seen_at,NULL AS pending_invoices,NULL AS pending_operations'
    join=' LEFT JOIN branch_device_heartbeats h ON h.device_id=d.device_id AND h.branch_id=d.branch_id' if heartbeat else ''
    rows=execute(conn,"SELECT d.device_id,d.branch_id,d.device_number,d.is_active,d.updated_at,COALESCE(to_jsonb(d)->>'device_name','') AS device_name,(COALESCE(to_jsonb(d)->>'token_hash','')<>'') AS credential_ready"+last_seen+' FROM branch_devices d'+join+' ORDER BY d.branch_id,length(d.device_number),d.device_number').fetchall()
    values=[dict(r) for r in rows]
    stats=execute(conn,"SELECT source_device_id,COUNT(*) AS confirmed_invoice_count,COUNT(*) FILTER(WHERE COALESCE(shift_status,'open')<>'Z_Closed') AS unsettled_confirmed_invoices FROM invoices GROUP BY source_device_id").fetchall()
    counts={r['source_device_id']:dict(r) for r in stats}
    registration_rows=execute(conn,"SELECT setting_key,setting_value FROM app_settings WHERE setting_key LIKE 'device_registration:%'").fetchall()
    import json
    registrations={r['setting_key'].split(':',1)[1]:json.loads(r['setting_value']) for r in registration_rows}
    for value in values:
        value['registration_state']=registrations.get(value['device_id'],{}).get('state','registered')
        value.update({k:v for k,v in counts.get(value['device_id'],{}).items() if k!='source_device_id'})
    from views.device_lifecycle import list_actions
    from pathlib import Path
    from server_update_service import installation_view
    current=[v for v in values if v['is_active']]
    historical=[dict(v,registration_state='released',registration_label='محرر لإعادة الاستخدام') for v in values if not v['is_active']]
    software=installation_view(Path(__file__).resolve().parents[1]/'update_releases',current)
    active_ids={v['device_id'] for v in current}
    actions=list_actions(conn)
    return {'devices':software['devices'],'historical_devices':historical,
        'software':{k:v for k,v in software.items() if k!='devices'},
        'changes':[c for c in pending_changes(conn) if c['device_id'] in active_ids],
        'actions':[a for a in actions if a['device_id'] in active_ids],
        'historical_actions':[a for a in actions if a['device_id'] not in active_ids],
        'replacements':__import__('views.device_lifecycle',fromlist=['replacement_records']).replacement_records(conn)}



def register_device(conn,actor,device_id,branch_id,number,name):
    """Reserve an actual workstation UUID through the existing registry.

    No credential is issued remotely. The normal local Super Admin setup resumes
    this same UUID/number and issues its device credential using the existing API.
    """
    branch_administrator(conn,actor);ensure_schema(conn)
    device_id=str(uuid.UUID(str(device_id)));branch_id=int(branch_id);number=str(number).strip();name=str(name).strip()
    if not number.isascii() or not number.isdecimal() or not 1<=int(number)<=999999999:raise ValueError('رقم الجهاز يبدأ من 1 داخل الفرع')
    number=str(int(number))
    if not name or len(name)>80:raise ValueError('اسم الجهاز مطلوب وبحد أقصى80 حرفًا')
    if not execute(conn,'SELECT id FROM branches WHERE id=? AND is_active=1',(branch_id,)).fetchone():raise ValueError('الفرع غير موجود أو غير نشط')
    execute(conn,'SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('identity:'+device_id,))
    execute(conn,'SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('device-authority:'+device_id,))
    execute(conn,'SELECT pg_advisory_xact_lock(hashtextextended(?,0))',(f'enroll:{branch_id}:{number}',))
    from views.device_lifecycle import assert_replacement_reservation
    assert_replacement_reservation(conn,device_id,branch_id,number)
    existing=execute(conn,'SELECT * FROM branch_devices WHERE device_id=? FOR UPDATE',(device_id,)).fetchone()
    from views.device_lifecycle import registration_record
    prior=registration_record(conn,device_id) if existing else None
    if existing and existing['is_active']:
        raise ValueError('الجهاز مسجل ونشط؛ استكمل تسجيله من الجهاز نفسه بواسطة Super_Admin')
    if existing:
        super_admin(conn,actor)
        _release_inactive_registration(conn,device_id,actor)
        prior=registration_record(conn,device_id)
    else:assert_not_retired(conn,device_id)
    if execute(conn,"SELECT 1 FROM branch_devices WHERE branch_id=? AND is_active AND LTRIM(device_number,'0')=?",(branch_id,number)).fetchone():raise ValueError('رقم الجهاز مستخدم داخل الفرع')
    if execute(conn,"SELECT 1 FROM branch_device_changes WHERE to_branch_id=? AND to_device_number=? AND status IN ('pending','awaiting_local_confirmation')",(branch_id,number)).fetchone():raise ValueError('الرقم محجوز بطلب تعديل لجهاز آخر')
    if existing:
        execute(conn,'UPDATE branch_devices SET branch_id=?,device_number=?,device_name=?,is_active=TRUE,token_hash=NULL,updated_at=CURRENT_TIMESTAMP WHERE device_id=?',(branch_id,number,name,device_id))
        import json
        prior=dict(prior,state='awaiting_local_setup')
        execute(conn,'UPDATE app_settings SET setting_value=? WHERE setting_key=?',(json.dumps(prior,ensure_ascii=False),'device_registration:'+device_id))
    else:
        execute(conn,'INSERT INTO branch_devices(device_id,branch_id,device_number,device_name,is_active,token_hash) VALUES(?,?,?,?,TRUE,NULL)',(device_id,branch_id,number,name))
    return {'device_id':device_id,'branch_id':branch_id,'device_number':number,'status':'awaiting_local_setup','message':'تمت إضافة هوية الجهاز وحجز رقمه. أكمل تجهيز نفس الجهاز بواسطة Super Admin لتنزيل بيانات الفرع وإصدار اعتماده؛ لم تُغيّر هوية أي جهاز آخر.'}


def device_invoice_page(conn,actor,device_id,branch_id,page=1):
    import json
    branch_administrator(conn,actor)
    device_id=str(uuid.UUID(str(device_id)));branch_id=int(branch_id)
    if not execute(conn,'SELECT device_id FROM branch_devices WHERE device_id=? AND branch_id=?',(device_id,branch_id)).fetchone():
        raise ValueError('الجهاز غير مسجل في الفرع المختار')
    page=int(page)
    if page<1 or page>100000:raise ValueError('رقم الصفحة غير صالح')
    rows=execute(conn,"""SELECT to_jsonb(i) AS invoice,
        (SELECT MAX(r.device_synced_at)::TEXT FROM offline_sync_receipts r WHERE r.remote_invoice_id=i.id) AS received_at
        FROM invoices i WHERE i.source_device_id=? AND i.branch_id=?
        ORDER BY i.created_at DESC,i.id DESC LIMIT 50 OFFSET ?""",(device_id,branch_id,(page-1)*50)).fetchall()
    invoices=[]
    for row in rows:
        record=row['invoice']
        if isinstance(record,str):record=json.loads(record)
        notes=record.get('notes')
        try:notes=json.loads(notes or '{}') if not isinstance(notes,dict) else notes
        except (ValueError,TypeError):notes={}
        if not isinstance(notes,dict):notes={}
        if notes.get('_non_financial') or notes.get('is_simulated'):continue
        items=[]
        for item in notes.get('items',[]) if isinstance(notes.get('items'),list) else []:
            if not isinstance(item,dict):continue
            items.append({k:item[k] for k in ('id','name','item_name','qty','quantity','price','total','unit') if k in item})
        invoices.append({'id':record['id'],'branch_id':branch_id,'source_device_id':device_id,
            'invoice_number':record.get('invoice_number'),'sold_at':record.get('sold_at') or record.get('created_at'),
            'created_at':record.get('created_at'),'total_amount':record.get('total_amount'),
            'shift_status':record.get('shift_status'),'shift_uuid':record.get('shift_uuid'),
            'user_id':record.get('user_id'),'payment_method':record.get('payment_method'),
            'received_at':row['received_at'],'sync_status':'وصلت للسيرفر بإيصال' if row['received_at'] else 'محفوظة على السيرفر؛ لا يتوفر إيصال رفع منفصل',
            'items':items})
    return {'invoices':invoices,'page':page,'may_have_more':len(rows)==50,'source':'central_committed_only'}


def assert_not_retired(conn,device_id):
    import hashlib,json
    device_id=str(uuid.UUID(str(device_id)))
    row=execute(conn,"SELECT setting_value FROM app_settings WHERE setting_key='retired_device_hashes_v1'").fetchone()
    if row and hashlib.sha256(device_id.encode()).hexdigest() in set(json.loads(row['setting_value'])):
        raise ValueError('هذه هوية ملغاة من تشغيل سابق. استخدم التثبيت النظيف لتوليد هوية جديدة ثم اعتماد Super Admin؛ لا يُعاد تفعيل الهوية القديمة.')


def device_error_message(error):
    """Public Arabic errors; never expose SQL, a connection string or a trace."""
    import re
    if isinstance(error,PermissionError):return 'ليس لديك صلاحية تنفيذ هذا الإجراء؛ استخدم حساب الإدارة المخول.'
    if isinstance(error,(ConnectionError,TimeoutError,OSError)):
        return 'تعذر إكمال الاتصال بالسيرفر. لم يُعلن نجاح الإجراء؛ أعد المحاولة بعد عودة الاتصال.'
    if isinstance(error,(ValueError,TypeError)):
        text=str(error)
        if re.search('[\u0600-\u06ff]',text) and not any(word in text.lower() for word in ('select ','insert ','password','traceback','psycopg')):return text
        return 'بيانات الجهاز غير صالحة؛ انسخ Device ID كاملًا وراجع الفرع ورقم الجهاز.'
    return 'تعذر حفظ إجراء الجهاز على السيرفر. لم يُعلن نجاحه؛ راجع المسؤول ثم أعد المحاولة.'


def confirmed_replacement_history(conn,device):
    """Read-only committed history, never uploaded as the replacement's sales."""
    import json
    from views.device_lifecycle import replacement_records
    records=replacement_records(conn);sources=set();front={device['device_id']}
    while front:
        next_ids={row['old_device_id'] for row in records if row.get('status')=='completed' and row['new_device_id'] in front and int(row['branch_id'])==int(device['branch_id'])}-sources
        sources.update(next_ids);front=next_ids
    if not sources:return None
    marks=','.join('?' for _ in sources)
    rows=execute(conn,'SELECT id,branch_id,source_device_id,invoice_number,created_at,total_amount,shift_status,notes FROM invoices WHERE branch_id=? AND source_device_id IN ('+marks+') ORDER BY id DESC LIMIT 101',(int(device['branch_id']),*sorted(sources))).fetchall()
    invoices=[]
    for row in rows[:100]:
        value=dict(row)
        try:notes=value['notes'] if isinstance(value.get('notes'),dict) else json.loads(value.get('notes') or '{}')
        except (ValueError,TypeError):notes={}
        if not isinstance(notes,dict):notes={}
        if notes.get('_non_financial') or notes.get('is_simulated'):continue
        invoices.append({'remote_id':int(value['id']),'branch_id':int(value['branch_id']),
            'source_device_id':value['source_device_id'],'invoice_number':value['invoice_number'],
            'created_at':str(value['created_at']),'total_amount':float(value['total_amount'] or 0),
            'shift_status':value['shift_status'],
            'items':[{k:item[k] for k in ('name','item_name','qty','quantity','price','total','unit') if k in item} for item in notes.get('items',[]) if isinstance(item,dict)] if isinstance(notes.get('items'),list) else []})
    return {'device_id':device['device_id'],'branch_id':int(device['branch_id']),'source_device_ids':sorted(sources),
            'invoices':invoices,'has_older_on_server':len(rows)>100,'source':'central_committed_only'}


def _release_inactive_registration(conn,device_id,actor=None):
    """Internal post-authorization cleanup. Keep the FK anchor and all money rows.

    Called by already-authorized lifecycle paths or explicit server maintenance;
    never exposed as an unauthenticated endpoint. Active rows are never changed.
    """
    import json,hashlib
    device_id=str(uuid.UUID(str(device_id)))
    execute(conn,'SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('device-authority:'+device_id,))
    device=execute(conn,'SELECT * FROM branch_devices WHERE device_id=? FOR UPDATE',(device_id,)).fetchone()
    if not device or device['is_active']:return False
    from views.device_lifecycle import registration_record
    prior=registration_record(conn,device_id) or {}
    if prior.get('state')=='released':return False
    history=list(prior.get('history',[]))
    history.append({'branch_id':int(device['branch_id']),'device_number':str(device['device_number']),
        'device_name':dict(device).get('device_name'),'released_by':actor})
    record=dict(prior,state='released',device_id=device_id,history=history)
    execute(conn,'UPDATE branch_devices SET token_hash=NULL,updated_at=CURRENT_TIMESTAMP WHERE device_id=? AND NOT is_active',(device_id,))
    execute(conn,"UPDATE branch_device_changes SET status='cancelled_released',error=NULL WHERE device_id=? AND status IN ('pending','awaiting_local_confirmation')",(device_id,))
    execute(conn,"UPDATE branch_device_actions SET status='cancelled_released',error=NULL WHERE device_id=? AND status='pending'",(device_id,))
    for table,sql in (
        ('branch_reset_devices',"UPDATE branch_reset_devices SET status='cancelled_released',error=NULL WHERE device_id=? AND status IN ('pending','failed')"),
        ('branch_settlement_authorities','UPDATE branch_settlement_authorities SET is_released=1 WHERE device_id=? AND is_released=0')):
        if execute(conn,'SELECT to_regclass(?) AS tbl',(table,)).fetchone()['tbl']:execute(conn,sql,(device_id,))
    # A cancelled replacement no longer reserves a number. Completed history stays intact.
    for row in execute(conn,"SELECT setting_key,setting_value FROM app_settings WHERE setting_key LIKE 'device_replacement:%'").fetchall():
        replacement=json.loads(row['setting_value'])
        if replacement.get('old_device_id')==device_id and replacement.get('status') not in ('completed','superseded_by_super_admin'):
            replacement.update(status='superseded_by_super_admin',release_reason='inactive_registration_released')
            execute(conn,'UPDATE app_settings SET setting_value=? WHERE setting_key=?',(json.dumps(replacement,ensure_ascii=False),row['setting_key']))
    retired=execute(conn,"SELECT setting_value FROM app_settings WHERE setting_key='retired_device_hashes_v1' FOR UPDATE").fetchone()
    if retired:
        digest=hashlib.sha256(device_id.encode()).hexdigest();hashes=json.loads(retired['setting_value'])
        if digest in hashes:execute(conn,"UPDATE app_settings SET setting_value=? WHERE setting_key='retired_device_hashes_v1'",(json.dumps([h for h in hashes if h!=digest]),))
    execute(conn,'INSERT INTO app_settings(setting_key,setting_value) VALUES(?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',('device_registration:'+device_id,json.dumps(record,ensure_ascii=False)))
    from control_services import write_audit_event
    write_audit_event(conn,'inactive_registration_released',actor,device['branch_id'],'branch_device',device_id,
        details={'reason_code':'inactive_registration_reusable_history_preserved'})
    return True
