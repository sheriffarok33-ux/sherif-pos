"""Read-only central shift proofs and a conservative local shift resolver."""
import json,uuid

def central_state(conn,branch_id,device_id,generation,known_version=None):
    from views.device_registry import execute
    row=execute(conn,"SELECT COALESCE(MAX(shift_number),0) AS closed,MAX(closed_at) AS changed_at FROM shift_closures WHERE branch_id=? AND status='closed'",(branch_id,)).fetchone()
    number=int(row['closed'] or 0)+1
    version=str(generation or '')+':'+str(branch_id)+':'+str(number)+':'+str(row['changed_at'] or '')
    state={'branch_id':int(branch_id),'device_id':str(device_id),'current_shift':number,'version':version,'generation':generation}
    rows=execute(conn,"""SELECT r.offline_uuid,i.invoice_number,i.id AS remote_invoice_id
        FROM offline_sync_receipts r JOIN invoices i ON i.id=r.remote_invoice_id
        WHERE i.branch_id=? AND i.source_device_id=? AND i.shift_status='Z_Closed'
        ORDER BY i.id""",(branch_id,device_id)).fetchall()
    import hashlib
    proofs=[dict(r) for r in rows]
    state['version']=version+':'+hashlib.sha256(json.dumps(proofs,sort_keys=True).encode()).hexdigest()[:24]
    if state['version']!=known_version:state['closed_receipts']=proofs
    return state

def cached_state(conn,branch_id):
    row=conn.execute('SELECT value FROM local_meta WHERE key=?',('branch_operational_state:'+str(int(branch_id)),)).fetchone()
    return json.loads(row[0]) if row else None

def cache_state(conn,state,branch_id,device_id):
    if state is None:return False
    if not isinstance(state,dict) or state.get('branch_id')!=int(branch_id) or state.get('device_id')!=str(device_id):raise ValueError('حالة وردية خارج هوية الجهاز أو فرعه')
    number=state.get('current_shift')
    if type(number) is not int or number<1 or not isinstance(state.get('version'),str):raise ValueError('حالة وردية مركزية غير صالحة')
    old=cached_state(conn,branch_id)
    if old and old.get('generation')==state.get('generation') and number<int(old['current_shift']):raise ValueError('لقطة وردية أقدم؛ لم يتغير الرقم المحلي')
    if 'closed_receipts' not in state:
        if not old or old.get('version')!=state['version']:raise ValueError('إثباتات إغلاق الوردية غير مكتملة')
        return False
    proofs=state['closed_receipts']
    if not isinstance(proofs,list):raise ValueError('إثباتات الوردية غير صالحة')
    checked={}
    for row in proofs:
        identity=row['offline_uuid'];parsed=uuid.UUID(identity)
        if identity not in (str(parsed),parsed.hex) or type(row.get('remote_invoice_id')) is not int or row['remote_invoice_id']<=0 or not isinstance(row.get('invoice_number'),str):raise ValueError('إثبات فاتورة مغلقة غير صالح')
        if identity in checked:raise ValueError('إثبات فاتورة مكرر')
        checked[identity]={'invoice_number':row['invoice_number'],'remote_invoice_id':row['remote_invoice_id']}
    record={k:state.get(k) for k in ('branch_id','device_id','current_shift','version','generation')};record['closed_receipts']=checked
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('branch_operational_state:'+str(int(branch_id)),json.dumps(record,ensure_ascii=False)))
    return True

def effective_current_shift(conn,branch_id):
    branch_id=int(branch_id)
    row=conn.execute('SELECT COALESCE(MAX(shift_number),0) FROM shift_closures WHERE branch_id=?',(branch_id,)).fetchone()
    durable=conn.execute('SELECT value FROM local_meta WHERE key=?',('last_shift_number:'+str(branch_id),)).fetchone()
    local=max(int(row[0] or 0),int(durable[0] or 0) if durable else 0)+1
    state=cached_state(conn,branch_id)
    if not state:return local
    bound=dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('bound_branch_id','device_id','sync_generation')"))
    if str(bound.get('bound_branch_id'))!=str(branch_id) or state['device_id']!=bound.get('device_id'):return local
    if str(state.get('generation') or '')!=str(bound.get('sync_generation') or ''):return local
    # Keep an already open cart on its original shift; never rewrite it on sync.
    for row in conn.execute("SELECT value FROM local_meta WHERE key LIKE 'pos_sale_draft:v1:%'"):
        draft=json.loads(row[0])
        if draft.get('state')=='open' and draft.get('cart') and int(draft.get('scope',{}).get('branch_id',-1))==branch_id:
            original=draft.get('original_shift')
            return int(original) if type(original) is int and original>0 else local
    if conn.execute("SELECT 1 FROM invoices WHERE branch_id=? AND COALESCE(sync_status,'pending')<>'synced' LIMIT 1",(branch_id,)).fetchone():return local
    from offline_store import _is_local_settings_sql
    for pending in conn.execute("SELECT sql_text FROM sync_queue WHERE COALESCE(sync_status,'pending') NOT IN ('synced','ignored','cancelled_reset')"):
        if not _is_local_settings_sql(pending[0]):return local
    for table in ('erp_outbox',):
        if conn.execute('SELECT 1 FROM '+table+" WHERE COALESCE(sync_status,'pending') NOT IN ('synced','ignored','cancelled_reset') LIMIT 1").fetchone():return local
    if conn.execute('SELECT 1 FROM transfer_logs WHERE receipt_pending=1 LIMIT 1').fetchone():return local
    if conn.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():return local
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_shift_uploads'").fetchone():
        cancelled=" AND COALESCE(u.cancelled_reset_id,'')=''" if 'cancelled_reset_id' in {r[1] for r in conn.execute('PRAGMA table_info(local_shift_uploads)')} else ''
        if conn.execute('SELECT 1 FROM shift_closures s LEFT JOIN local_shift_uploads u ON u.branch_id=s.branch_id AND u.shift_date=s.shift_date AND u.shift_number=s.shift_number WHERE s.branch_id=? AND u.synced_at IS NULL'+cancelled+' LIMIT 1',(branch_id,)).fetchone():return local
    elif conn.execute('SELECT 1 FROM shift_closures WHERE branch_id=? LIMIT 1',(branch_id,)).fetchone():return local
    proofs=state.get('closed_receipts',{})
    for invoice in conn.execute("SELECT offline_uuid,invoice_number,remote_invoice_id FROM invoices WHERE branch_id=? AND COALESCE(shift_status,'open')<>'Z_Closed'",(branch_id,)):
        proof=proofs.get(invoice['offline_uuid'])
        if not proof or proof['invoice_number']!=invoice['invoice_number'] or proof['remote_invoice_id']!=invoice['remote_invoice_id']:return local
    return max(local,int(state['current_shift']))


def registered_pos_branch(conn,user_id):
    """POS always uses the bound branch; cached branches are never sale choices."""
    meta=dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('device_id','bound_device_id','bound_branch_id','device_active','server_enrolled','setup_complete')"))
    if meta.get('bound_device_id')!=meta.get('device_id') or not meta.get('device_id') or meta.get('device_active','1')!='1' or meta.get('server_enrolled')!='1' or meta.get('setup_complete')!='1':
        raise PermissionError('لم يكتمل اعتماد الجهاز أو بيانات فرعه')
    branch_id=int(meta.get('bound_branch_id') or 0)
    actor=conn.execute('SELECT id,role,branch_id,is_active FROM users WHERE id=?',(user_id,)).fetchone()
    if not actor or not actor['is_active']:raise PermissionError('الحساب غير نشط')
    if actor['role']=='Cashier' and actor['branch_id']!=branch_id:raise PermissionError('حساب الكاشير غير تابع للفرع المسجل لهذا الجهاز؛ أعد تسجيل الدخول بحساب الفرع الصحيح')
    branch=conn.execute('SELECT id,branch_name FROM branches WHERE id=? AND is_active=1',(branch_id,)).fetchone()
    if not branch:raise PermissionError('الفرع المسجل للجهاز غير متاح')
    return int(branch['id']),str(branch['branch_name'])


def apply_closed_state(conn,branch_id,device_id):
    """Apply only server-proven closures to synced local rows; caller owns transaction."""
    state=cached_state(conn,branch_id)
    if not state:return {'applied':False,'reason':'no_state'}
    meta=dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('bound_branch_id','device_id','sync_generation')"))
    if state['device_id']!=str(device_id) or meta.get('device_id')!=str(device_id) or str(meta.get('bound_branch_id'))!=str(branch_id) or str(meta.get('sync_generation') or '')!=str(state.get('generation') or ''):raise ValueError('أمر الوردية لا يطابق اعتماد الجهاز والفرع والجيل')
    for row in conn.execute("SELECT value FROM local_meta WHERE key LIKE 'pos_sale_draft:v1:%'"):
        draft=json.loads(row[0])
        if draft.get('state')=='open' and draft.get('cart'):return {'applied':False,'reason':'open_cart'}
    next_shift=int(state['current_shift'])
    # The resolver already checks sales, business outboxes, receipts and closed-shift ACKs.
    if effective_current_shift(conn,branch_id)<next_shift:return {'applied':False,'reason':'pending_or_unproven_operations'}
    rows=conn.execute("SELECT id,offline_uuid,remote_invoice_id,invoice_number,sync_status,shift_status FROM invoices WHERE branch_id=? AND COALESCE(shift_status,'open')<>'Z_Closed'",(int(branch_id),)).fetchall()
    proofs=state.get('closed_receipts',{})
    for row in rows:
        proof=proofs.get(row['offline_uuid'])
        if not proof:continue
        if row['sync_status']!='synced' or proof['remote_invoice_id']!=row['remote_invoice_id'] or proof['invoice_number']!=row['invoice_number']:raise ValueError('إثبات إغلاق الفاتورة غير مطابق؛ لم تتغير البيانات')
        conn.execute("UPDATE invoices SET shift_status='Z_Closed' WHERE id=? AND branch_id=? AND sync_status='synced'",(row['id'],int(branch_id)))
    prior=conn.execute('SELECT value FROM local_meta WHERE key=?',('last_shift_number:'+str(branch_id),)).fetchone()
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('last_shift_number:'+str(branch_id),str(max(int(prior[0]) if prior else 0,next_shift-1))))
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('applied_shift_state:'+str(branch_id),state['version']))
    return {'applied':True,'version':state['version'],'current_shift':next_shift}



def sale_hold_reason(conn,branch_id,original_shift=None):
    """Block NEW sales, never mutate/reassign existing invoices or drafts."""
    branch_id=int(branch_id)
    if conn.execute("SELECT 1 FROM local_meta WHERE key='remote_shift_close_intent'").fetchone():
        return 'طلب إغلاق وردية من الإدارة قيد التأكيد؛ الفواتير والسلة محفوظة'
    meta=dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('device_id','bound_branch_id','sync_generation','device_active','setup_complete','device_lifecycle_intent','device_command_intent','device_reconfigure_intent','device_change_ack_pending','branch_reset_guard')"))
    if meta.get('device_active')=='0' or meta.get('setup_complete')=='0':return 'الجهاز في وضع التجهيز أو غير معتمد للبيع'
    if any(meta.get(k) for k in ('device_lifecycle_intent','device_command_intent','device_reconfigure_intent','device_change_ack_pending','branch_reset_guard')):return 'يوجد إجراء إداري غير مكتمل؛ لم تتغير الفواتير أو السلة'
    state=cached_state(conn,branch_id)
    if not state:return None  # Offline operation remains possible without a known closure.
    if state.get('device_id')!=meta.get('device_id') or str(meta.get('bound_branch_id'))!=str(branch_id) or str(state.get('generation') or '')!=str(meta.get('sync_generation') or ''):return 'حالة الوردية تحتاج مطابقة اعتماد الجهاز؛ لا تُفرض وردية جديدة'
    current=effective_current_shift(conn,branch_id)
    selected=int(original_shift) if original_shift is not None else current
    if int(state['current_shift'])>selected:
        return 'أُغلقت هذه الوردية مركزيًا؛ أوقف البيع الجديد وأكمل المزامنة وتسوية التعارض. الفواتير والسلة محفوظة بأرقامها الأصلية'
    return None
