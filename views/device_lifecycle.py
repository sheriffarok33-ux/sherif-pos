"""Explicit per-device lifecycle requests; no deletion of business history."""
import uuid,json
from views.device_registry import execute,super_admin,branch_administrator


def ensure_schema(conn):
    execute(conn,'''CREATE TABLE IF NOT EXISTS branch_device_actions(
        command_id TEXT PRIMARY KEY,device_id TEXT NOT NULL REFERENCES branch_devices(device_id),
        branch_id INTEGER NOT NULL,device_number TEXT NOT NULL,action TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',requested_by INTEGER NOT NULL,
        requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,applied_at TIMESTAMP,error TEXT)''')
    execute(conn,"CREATE UNIQUE INDEX IF NOT EXISTS branch_device_actions_pending ON branch_device_actions(device_id) WHERE status='pending'")


def list_actions(conn):
    row=execute(conn,"SELECT to_regclass('branch_device_actions') AS tbl").fetchone()
    if not row['tbl']:return []
    return [dict(r) for r in execute(conn,'SELECT * FROM branch_device_actions ORDER BY requested_at DESC').fetchall()]


def request_action(conn,actor,device_id,action,confirm):
    branch_administrator(conn,actor)
    if action=='unregister':return unregister_old_registration(conn,actor,device_id,confirm)
    return _request_authorized_action(conn,actor,device_id,action,confirm)


def _request_authorized_action(conn,actor,device_id,action,confirm):
    if action not in ('retire','reinitialize'):raise ValueError('إجراء جهاز غير صالح')
    device_id=str(uuid.UUID(device_id))
    if str(confirm)!=device_id:raise ValueError('يلزم تأكيد هوية الجهاز المحدد')
    ensure_schema(conn)
    device=execute(conn,'SELECT * FROM branch_devices WHERE device_id=? FOR UPDATE',(device_id,)).fetchone()
    if not device or not device['is_active']:raise ValueError('الجهاز غير مسجل أو غير نشط')
    assert_server_financial_safe(conn,device_id,action)
    from views.branch_reset_service import assert_no_pending_resets
    assert_no_pending_resets(conn,device_id)
    if execute(conn,"SELECT 1 FROM branch_device_changes WHERE device_id=? AND status IN ('pending','awaiting_local_confirmation')",(device_id,)).fetchone():raise ValueError('أكمل طلب تعديل تسجيل الجهاز أولًا')
    existing=execute(conn,"SELECT * FROM branch_device_actions WHERE device_id=? AND status='pending'",(device_id,)).fetchone()
    if existing:
        if existing['action']!=action:raise ValueError('يوجد إجراء آخر معلق لهذا الجهاز')
        return dict(existing)
    command=str(uuid.uuid4())
    execute(conn,'INSERT INTO branch_device_actions(command_id,device_id,branch_id,device_number,action,requested_by) VALUES(?,?,?,?,?,?)',(command,device_id,device['branch_id'],device['device_number'],action,actor))
    return {'command_id':command,'device_id':device_id,'action':action,'status':'pending'}


def acknowledge_action(conn,actor,device_id,command_id):
    authorize_action_ack(conn,actor,command_id)
    execute(conn,'SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('device-authority:'+str(device_id),))
    device=execute(conn,'SELECT * FROM branch_devices WHERE device_id=? FOR UPDATE',(device_id,)).fetchone()
    command=execute(conn,'SELECT * FROM branch_device_actions WHERE command_id=? AND device_id=? FOR UPDATE',(command_id,device_id)).fetchone()
    if not device or not command:raise ValueError('طلب الجهاز غير موجود')
    if command['status']=='applied':return dict(command)
    if command['status']!='pending' or not device['is_active']:raise ValueError('حالة الطلب أو الجهاز لا تسمح بالتطبيق')
    if (int(device['branch_id']),str(device['device_number']))!=(int(command['branch_id']),str(command['device_number'])):raise ValueError('تغير تسجيل الجهاز؛ لم يُطبق الإجراء')
    assert_server_financial_safe(conn,device_id,command['action'])
    if command['action']=='retire':execute(conn,'UPDATE branch_devices SET is_active=FALSE,updated_at=CURRENT_TIMESTAMP WHERE device_id=?',(device_id,))
    execute(conn,"UPDATE branch_device_actions SET status='applied',applied_at=CURRENT_TIMESTAMP,error=NULL WHERE command_id=?",(command_id,))
    if command['action']=='retire':
        from views.device_registry import _release_inactive_registration
        _release_inactive_registration(conn,device_id,actor)
    return {'command_id':command_id,'device_id':device_id,'action':command['action'],'status':'applied'}


def assert_local_safe(conn,action=None):
    """Caller holds sync lock and BEGIN IMMEDIATE; fail closed on unknown schema."""
    for table in ('invoices','sync_queue','erp_outbox'):
        if conn.execute('SELECT 1 FROM '+table+" WHERE COALESCE(sync_status,'pending') NOT IN ('synced','ignored','cancelled_reset') LIMIT 1").fetchone():raise ValueError('توجد معاملات غير مؤكدة؛ أكمل المزامنة أولًا')
    if conn.execute('SELECT 1 FROM transfer_logs WHERE receipt_pending=1 LIMIT 1').fetchone():raise ValueError('يوجد استلام تزويد معلق')
    if conn.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():raise ValueError('توجد تسويات معلقة')
    if conn.execute("SELECT 1 FROM local_meta WHERE key IN ('branch_reset_guard','device_reconfigure_intent','device_change_ack_pending','remote_shift_close_intent')").fetchone():raise ValueError('يوجد إجراء إداري سابق يحتاج الاستكمال')
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_shift_uploads'").fetchone():
        columns={r[1] for r in conn.execute('PRAGMA table_info(local_shift_uploads)')}
        condition=" AND COALESCE(u.cancelled_reset_id,'')=''" if 'cancelled_reset_id' in columns else ''
        pending=conn.execute('SELECT 1 FROM shift_closures s LEFT JOIN local_shift_uploads u ON u.branch_id=s.branch_id AND u.shift_date=s.shift_date AND u.shift_number=s.shift_number WHERE u.synced_at IS NULL'+condition+' LIMIT 1').fetchone()
    else:pending=conn.execute('SELECT 1 FROM shift_closures LIMIT 1').fetchone()
    if pending:raise ValueError('وردية مغلقة تنتظر تأكيد المزامنة')
    if action=='retire' and conn.execute("SELECT 1 FROM invoices WHERE COALESCE(shift_status,'open')<>'Z_Closed' LIMIT 1").fetchone():raise ValueError('الوردية بها فواتير لم تُسوّ؛ تبقى محفوظة ولا يُلغى تسجيل الجهاز')
    for row in conn.execute("SELECT value FROM local_meta WHERE key LIKE 'pos_sale_draft:v1:%'"):
        draft=json.loads(row[0])
        if draft.get('state')=='open' and draft.get('cart'):raise ValueError('توجد سلة بيع مفتوحة')



def assert_server_financial_safe(conn,device_id,action):
    heartbeat=execute(conn,"SELECT to_regclass('branch_device_heartbeats') AS tbl").fetchone()
    if heartbeat['tbl']:
        row=execute(conn,'SELECT pending_invoices,pending_operations FROM branch_device_heartbeats WHERE device_id=?',(device_id,)).fetchone()
        if row and (int(row['pending_invoices'] or 0)>0 or int(row['pending_operations'] or 0)>0):raise ValueError('آخر اتصال للجهاز يثبت معاملات معلقة؛ أكمل المزامنة قبل الإجراء')
    if action=='retire' and execute(conn,"SELECT 1 FROM invoices WHERE source_device_id=? AND COALESCE(shift_status,'open')<>'Z_Closed' LIMIT 1",(device_id,)).fetchone():raise ValueError('توجد فواتير مؤكدة على وردية لم تُسوّ؛ لا يُلغى التسجيل قبل تسوية التعارض')


def replacement_administrator(conn,actor):
    row=execute(conn,'SELECT role,is_active FROM users WHERE id=?',(actor,)).fetchone()
    if not row or not row['is_active'] or row['role'] not in ('Super_Admin','Admin','Manager'):
        raise PermissionError('الاستبدال يتطلب Super Admin أو Admin أو المدير العام بحساب نشط')


def replacement_info(conn,command_id):
    command_id=str(uuid.UUID(str(command_id)))
    row=execute(conn,'SELECT setting_value FROM app_settings WHERE setting_key=?',('device_replacement:'+command_id,)).fetchone()
    if not row:raise ValueError('طلب الاستبدال غير موجود')
    return json.loads(row['setting_value'])


def request_replacement(conn,actor,old_device_id,new_device_id,confirm,immediate=False):
    if immediate:return authorize_immediate_replacement(conn,actor,old_device_id,new_device_id,confirm)
    replacement_administrator(conn,actor)
    old_device_id=str(uuid.UUID(str(old_device_id)));new_device_id=str(uuid.UUID(str(new_device_id)))
    if old_device_id==new_device_id:raise ValueError('استكمال نفس الهوية ليس استبدال جهاز؛ استخدم استكمال التسجيل')
    from views.device_registry import assert_not_retired
    assert_not_retired(conn,new_device_id)
    # The existing retirement command performs both financial checks and the
    # authenticated workstation ACK. A stale heartbeat is never a safe ACK.
    if str(confirm)!=old_device_id:raise ValueError('اكتب هوية الجهاز السابق كاملة لتأكيد التفويض')
    device=execute(conn,'SELECT is_active FROM branch_devices WHERE device_id=? FOR UPDATE',(old_device_id,)).fetchone()
    if not device:raise ValueError('التسجيل السابق غير موجود؛ استخدم إضافة جهاز جديد')
    if device['is_active']:
        command=_request_authorized_action(conn,actor,old_device_id,'retire',confirm)
    else:
        # After planned maintenance the old disk need not exist: an applied
        # retirement ACK proves that local operations were secured first.
        # Merely setting is_active=False or an old zero heartbeat is no proof.
        assert_server_financial_safe(conn,old_device_id,'retire')
        from views.branch_reset_service import assert_no_pending_resets
        assert_no_pending_resets(conn,old_device_id)
        present=execute(conn,"SELECT to_regclass('branch_device_actions') AS tbl").fetchone()
        command=execute(conn,"SELECT * FROM branch_device_actions WHERE device_id=? AND action='retire' AND status='applied' ORDER BY applied_at DESC LIMIT 1 FOR UPDATE",(old_device_id,)).fetchone() if present and present['tbl'] else None
        if not command:raise ValueError('لم يثبت تأمين بيانات الجهاز السابق؛ يلزم استعادة ملفات العمل أو إكمال الإلغاء الآمن قبل إعادة التسجيل بعد الصيانة')

    key='device_replacement:'+command['command_id']
    row=execute(conn,'SELECT setting_value FROM app_settings WHERE setting_key=? FOR UPDATE',(key,)).fetchone()
    if row:
        record=json.loads(row['setting_value'])
        if record['new_device_id']!=new_device_id:raise ValueError('الرقم محجوز لاستبدال آخر؛ أكمل الطلب الموجود')
        return record
    device=execute(conn,'SELECT branch_id,device_number FROM branch_devices WHERE device_id=?',(old_device_id,)).fetchone()
    record={'command_id':command['command_id'],'old_device_id':old_device_id,'new_device_id':new_device_id,
            'branch_id':int(device['branch_id']),'device_number':str(device['device_number']),
            'requested_by':actor,'status':'waiting_for_safe_retirement'}
    execute(conn,'INSERT INTO app_settings(setting_key,setting_value) VALUES(?,?)',(key,json.dumps(record)))
    from control_services import write_audit_event
    write_audit_event(conn,'device_replacement_requested',actor,record['branch_id'],'branch_device_actions',command['command_id'],
        details={'reason_code':'explicit_authorized_device_replacement','source_transaction_uuid':command['command_id']})
    return record


def assert_replacement_reservation(conn,new_device_id,branch_id,number,command_id=None):
    rows=execute(conn,"SELECT setting_value FROM app_settings WHERE setting_key LIKE ?",('device_replacement:%',)).fetchall()
    for row in rows:
        record=json.loads(row['setting_value'])
        if record.get('status') in ('completed','superseded_by_super_admin'):continue
        if (int(record['branch_id']),str(record['device_number']))!=(int(branch_id),str(number)):continue
        if record['new_device_id']!=new_device_id or record['command_id']!=command_id:
            raise ValueError('رقم الجهاز محجوز لطلب استبدال معتمد؛ لم يتم تجاوزه')


def validate_replacement(conn,actor,command_id,new_device_id,branch_id,number):
    replacement_administrator(conn,actor)
    record=replacement_info(conn,command_id)
    if record.get('status')=='superseded_by_super_admin':raise ValueError('تم تفويض بديل آخر بواسطة Super Admin')
    if (record['new_device_id'],int(record['branch_id']),str(record['device_number']))!=(new_device_id,int(branch_id),str(number)):
        raise ValueError('بيانات الجهاز البديل لا تطابق طلب الاستبدال المعتمد')
    if record.get('kind')=='damaged':
        super_admin(conn,actor)
        execute(conn,'SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('device-authority:'+record['old_device_id'],))
        old=execute(conn,'SELECT * FROM branch_devices WHERE device_id=? FOR UPDATE',(record['old_device_id'],)).fetchone()
        if not old or (int(old['branch_id']),str(old['device_number']).lstrip('0'))!=(int(branch_id),str(number)):
            raise ValueError('تغير تسجيل الجهاز السابق؛ أعد مراجعة التفويض')
        if record.get('status')=='completed':return record
        if record.get('unrecovered_local_operations',{}).get('status')!='unknown_unrecovered':
            raise ValueError('لم يكتمل إقرار المعاملات غير المستردة')
        execute(conn,'UPDATE branch_devices SET is_active=FALSE,updated_at=CURRENT_TIMESTAMP WHERE device_id=?',(record['old_device_id'],))
        # Administrative revocation, explicitly NOT a workstation ACK.
        execute(conn,"UPDATE branch_device_actions SET status='admin_confirmed_unrecoverable',error=? WHERE command_id=?",('الجهاز تالف؛ المعلقات المحلية غير مستردة ولم تؤكد مزامنتها',record['command_id']))
        return record
    command=execute(conn,'SELECT status,device_id,action FROM branch_device_actions WHERE command_id=? FOR UPDATE',(record['command_id'],)).fetchone()
    old=execute(conn,'SELECT is_active FROM branch_devices WHERE device_id=? FOR UPDATE',(record['old_device_id'],)).fetchone()
    if not command or command['device_id']!=record['old_device_id'] or command['action']!='retire' or command['status']!='applied' or not old or old['is_active']:
        raise ValueError('الاستبدال ينتظر تأمين عمليات الجهاز السابق ووصول إيصال إلغاء تسجيله؛ لم تُحذف بياناته')
    return record


def complete_replacement(conn,actor,record):
    from views.device_registry import _release_inactive_registration
    if record.get('status')=='completed':
        _release_inactive_registration(conn,record['old_device_id'],actor)
        return
    record=dict(record,status='completed',completed_by=actor)
    execute(conn,'UPDATE app_settings SET setting_value=? WHERE setting_key=?',(json.dumps(record),'device_replacement:'+record['command_id']))
    from control_services import write_audit_event
    write_audit_event(conn,'device_replacement_completed',actor,record['branch_id'],'branch_device_actions',record['command_id'],
        details={'reason_code':'safe_retirement_acknowledged','source_transaction_uuid':record['command_id']})
    _release_inactive_registration(conn,record['old_device_id'],actor)


def replacement_records(conn):
    return [json.loads(row['setting_value']) for row in execute(conn,"SELECT setting_value FROM app_settings WHERE setting_key LIKE ?",('device_replacement:%',)).fetchall()]


def replacement_download_allowed(conn,actor_id,actor_role,device):
    if actor_role not in ('Super_Admin','Admin','Manager') or not device:return False
    return any(row.get('status')=='completed' and row.get('completed_by')==actor_id
        and row['new_device_id']==device['device_id'] and int(row['branch_id'])==int(device['branch_id'])
        for row in replacement_records(conn))


def authorize_action_ack(conn,actor,command_id):
    # Admin and Manager can acknowledge only the retirement associated with an
    # explicitly approved replacement. Other lifecycle permissions stay intact.
    try:record=replacement_info(conn,command_id)
    except ValueError:
        super_admin(conn,actor);return
    replacement_administrator(conn,actor)


def authorize_immediate_replacement(conn,actor,old_device_id,new_device_id,confirm):
    """Immediate enrollment only after proven safety; unknown pending work blocks it."""
    replacement_administrator(conn,actor)
    record=request_replacement(conn,actor,old_device_id,new_device_id,confirm,immediate=False)
    old=execute(conn,'SELECT is_active FROM branch_devices WHERE device_id=?',(record['old_device_id'],)).fetchone()
    if old['is_active']:
        # Preserve the existing authorized command, but do not revoke a live
        # device merely because its last heartbeat happened to report zero.
        return dict(record,message='الاستبدال متوقف حتى تأمين عمليات الجهاز السابق ووصول إيصال الإلغاء؛ لم يتغير اعتماده')
    validate_replacement(conn,actor,record['command_id'],record['new_device_id'],record['branch_id'],record['device_number'])
    # The applied retirement ACK is the checkpoint. No source history, pending
    # operation, invoice reservation, inventory or shift is moved or reset.
    updated=dict(record,status='authorized_for_enrollment',resume_from='last_confirmed_server_state',safety_confirmed=True)
    execute(conn,'UPDATE app_settings SET setting_value=? WHERE setting_key=?',(json.dumps(updated),'device_replacement:'+record['command_id']))
    return updated


def request_damaged_replacement(conn,actor,branch_id,number,new_device_id,confirmed=False,accept_unrecovered=False):
    """Administrative disaster recovery; no false device ACK or invoice rewrite."""
    super_admin(conn,actor)
    ensure_schema(conn)
    if confirmed is not True:
        raise ValueError('يلزم تأكيد Super Admin للاستبدال')
    branch_id=int(branch_id);number=str(number).strip()
    if not number.isascii() or not number.isdecimal() or int(number)<1:raise ValueError('رقم الجهاز غير صالح')
    number=str(int(number));new_device_id=str(uuid.UUID(new_device_id))
    execute(conn,'SELECT pg_advisory_xact_lock(hashtextextended(?,0))',(f'enroll:{branch_id}:{number}',))
    # Idempotent retry even after enrollment, with no new command or credential.
    prior=[x for x in replacement_records(conn) if x.get('kind')=='damaged' and x['new_device_id']==new_device_id and int(x['branch_id'])==branch_id and str(x['device_number'])==number]
    if prior:
        record=prior[-1]
        return record
    existing=execute(conn,'SELECT device_id FROM branch_devices WHERE device_id=?',(new_device_id,)).fetchone()
    if existing:raise ValueError('هذا الكمبيوتر مسجل بالفعل؛ استخدم استكمال تسجيله ولا تنقل تاريخه')
    rows=execute(conn,"SELECT * FROM branch_devices WHERE branch_id=? AND is_active AND LTRIM(device_number,'0')=? FOR UPDATE",(branch_id,number)).fetchall()
    if len(rows)!=1:raise ValueError('يلزم تسجيل سابق نشط واحد فقط لنفس الفرع والرقم')
    old=rows[0]
    for previous in replacement_records(conn):
        if int(previous['branch_id'])==branch_id and str(previous['device_number'])==number and previous.get('status') not in ('completed','superseded_by_super_admin'):
            previous=dict(previous,status='superseded_by_super_admin',superseded_by=actor)
            execute(conn,'UPDATE app_settings SET setting_value=? WHERE setting_key=?',(json.dumps(previous),'device_replacement:'+previous['command_id']))
    heartbeat=execute(conn,"SELECT to_regclass('branch_device_heartbeats') AS tbl").fetchone()
    reported=execute(conn,'SELECT pending_invoices,pending_operations FROM branch_device_heartbeats WHERE device_id=?',(old['device_id'],)).fetchone() if heartbeat['tbl'] else None
    command=str(uuid.uuid4())
    execute(conn,"INSERT INTO branch_device_actions(command_id,device_id,branch_id,device_number,action,status,requested_by,error) VALUES(?,?,?,?,?,'authorized_damaged',?,?)",(command,old['device_id'],branch_id,number,'retire',actor,'بانتظار اعتماد البديل؛ لا يوجد إيصال من الجهاز التالف'))
    record={'kind':'damaged','command_id':command,'old_device_id':old['device_id'],'new_device_id':new_device_id,'branch_id':branch_id,'device_number':number,'requested_by':actor,'status':'authorized_damaged','unrecovered_local_operations':{'status':'unknown_unrecovered','workstation_acknowledged':False,'last_reported_pending':dict(reported) if reported else None,'unknown_additional_transactions_possible':True,'message':'أي معاملات لم تصل للسيرفر غير مستردة؛ ليست متزامنة وتحتاج تسوية مستقلة عند استعادة القرص'}}
    execute(conn,'INSERT INTO app_settings(setting_key,setting_value) VALUES(?,?)',('device_replacement:'+command,json.dumps(record)))
    from control_services import write_audit_event
    write_audit_event(conn,'damaged_device_replacement_authorized',actor,branch_id,'branch_device_actions',command,details={'reason_code':'explicit_unrecovered_local_operations_accepted','source_transaction_uuid':command})
    return record


def registration_record(conn,device_id):
    row=execute(conn,'SELECT setting_value FROM app_settings WHERE setting_key=?',('device_registration:'+str(device_id),)).fetchone()
    return json.loads(row['setting_value']) if row else None


def unregister_old_registration(conn,actor,device_id,confirm):
    """Remove an inactive registration, not its identity-linked accounting history.

    Caller commits or rolls back the whole action. No device ACK is fabricated.
    """
    branch_administrator(conn,actor)
    device_id=str(uuid.UUID(str(device_id)))
    if str(confirm).strip()!=device_id:raise ValueError('اكتب معرّف الجهاز المحدد كاملًا لتأكيد حذف تسجيله')
    execute(conn,'SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('device-authority:'+device_id,))
    device=execute(conn,'SELECT * FROM branch_devices WHERE device_id=? FOR UPDATE',(device_id,)).fetchone()
    if not device:raise ValueError('تسجيل الجهاز غير موجود')
    if device['is_active']:raise ValueError('هذا الجهاز نشط؛ زر حذف التسجيل مخصص للأجهزة القديمة غير النشطة فقط')
    prior=registration_record(conn,device_id)
    if prior and prior.get('state') in ('unregistered','released'):return {'device_id':device_id,'status':'unregistered','message':'تسجيل هذا الجهاز محذوف بالفعل؛ سجله وفواتيره محفوظة'}
    from views.branch_reset_service import assert_no_pending_resets
    assert_no_pending_resets(conn,device_id)
    history=list((prior or {}).get('history',[]))
    history.append({'branch_id':int(device['branch_id']),'device_number':str(device['device_number']),'device_name':dict(device).get('device_name'),'removed_by':int(actor)})
    record={'state':'unregistered','device_id':device_id,'history':history}
    # Keep the FK anchor. All old invoice/source IDs and branch IDs stay intact.
    execute(conn,'UPDATE branch_devices SET is_active=FALSE,token_hash=NULL,updated_at=CURRENT_TIMESTAMP WHERE device_id=?',(device_id,))
    execute(conn,"UPDATE branch_device_changes SET status='cancelled_unregistered',error=NULL WHERE device_id=? AND status IN ('pending','awaiting_local_confirmation')",(device_id,))
    execute(conn,"UPDATE branch_device_actions SET status='cancelled_unregistered',error=NULL WHERE device_id=? AND status='pending'",(device_id,))
    execute(conn,'INSERT INTO app_settings(setting_key,setting_value) VALUES(?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',('device_registration:'+device_id,json.dumps(record,ensure_ascii=False)))
    from control_services import write_audit_event
    write_audit_event(conn,'device_registration_removed',actor,device['branch_id'],'branch_device',device_id,details={'reason_code':'inactive_registration_removed_history_preserved'})
    from views.device_registry import _release_inactive_registration
    _release_inactive_registration(conn,device_id,actor)
    return {'device_id':device_id,'status':'unregistered','message':'حُذف التسجيل القديم وأُبطل اعتماده. يمكنك إضافة نفس المعرّف لفرع آخر واعتماده رسميًا؛ جميع الفواتير والسجلات السابقة محفوظة.'}
