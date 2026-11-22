"""Apply only authenticated, enumerated reset commands to this bound workstation."""
import hashlib,json,uuid
from views.branch_reset_plan import normalized,make_plan,apply_plan,catalog

def command_fingerprint(command):
    return hashlib.sha256(json.dumps({k:command[k] for k in ('reset_id','reset_seq','branch_id','device_id','generation','choices')},sort_keys=True,separators=(',',':')).encode()).hexdigest()

def apply_command(conn,command,device_id,branch_id,installed_sequence):
    if str(uuid.UUID(command['reset_id']))!=command['reset_id'] or str(uuid.UUID(command['generation']))!=command['generation']:raise ValueError('معرّف أمر التصفير غير صالح')
    if command.get('device_id')!=device_id or command.get('branch_id')!=int(branch_id):raise ValueError('أمر تصفير لجهاز أو فرع آخر؛ لم يُطبق')
    if type(command.get('reset_seq')) is not int or command['reset_seq']<=0:raise ValueError('تسلسل أمر التصفير غير صالح')
    if installed_sequence<int(command.get('required_release_seq',18)):raise ValueError('يلزم تثبيت تحديث البرنامج قبل تطبيق أمر التصفير')
    choices=normalized(command['choices']);key='branch_reset_applied:'+command['reset_id'];digest=command_fingerprint(command)
    seen=conn.execute('SELECT value FROM local_meta WHERE key=?',(key,)).fetchone()
    if seen:
        if json.loads(seen[0])['fingerprint']!=digest:raise ValueError('تغير محتوى أمر سبق تطبيقه؛ لم يُكرر التصفير')
        return False
    prior=conn.execute('SELECT value FROM local_meta WHERE key=?',('last_branch_reset:'+str(branch_id),)).fetchone()
    if prior and int(json.loads(prior[0])['reset_seq'])>=command['reset_seq']:raise ValueError('أمر أقدم من آخر تصفير مطبق؛ يحتاج مراجعة الإدارة')
    tables=catalog(conn);pending=False
    for table in ('invoices','sync_queue','erp_outbox'):
        if table not in tables:continue
        where="COALESCE(sync_status,'pending') NOT IN ('synced','ignored','cancelled_reset')";args=()
        if table=='invoices':where+=' AND branch_id=?';args=(branch_id,)
        if conn.execute('SELECT 1 FROM '+table+' WHERE '+where+' LIMIT 1',args).fetchone():pending=True
    drafts=[]
    for row in conn.execute("SELECT key,value FROM local_meta WHERE key LIKE 'pos_sale_draft:v1:%'"):
        draft=json.loads(row[1])
        if int(draft.get('scope',{}).get('branch_id',-1))!=int(branch_id):continue
        drafts.append(row[0])
        if draft.get('state')=='open' and draft.get('cart'):pending=True
    if 'transfer_logs' in tables and 'receipt_pending' in tables['transfer_logs'] and conn.execute('SELECT 1 FROM transfer_logs WHERE to_branch_id=? AND receipt_pending=1 LIMIT 1',(branch_id,)).fetchone():pending=True
    if 'exception_settlements' in tables and conn.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():pending=True
    if 'shift_closures' in tables:
        if 'local_shift_uploads' in tables:
            cancelled=" AND COALESCE(u.cancelled_reset_id,'')=''" if 'cancelled_reset_id' in tables['local_shift_uploads'] else ''
            if conn.execute('SELECT 1 FROM shift_closures s LEFT JOIN local_shift_uploads u ON u.branch_id=s.branch_id AND u.shift_date=s.shift_date AND u.shift_number=s.shift_number WHERE s.branch_id=? AND u.synced_at IS NULL'+cancelled+' LIMIT 1',(branch_id,)).fetchone():pending=True
        elif conn.execute('SELECT 1 FROM shift_closures WHERE branch_id=? LIMIT 1',(branch_id,)).fetchone():pending=True
    if pending and 'pending' not in choices:raise ValueError('توجد معاملات أو سلة معلقة؛ لم تُحذف. يلزم مراجعة Super Admin وإذن واضح لإلغاء المعلقات')
    if 'pending' in choices:
        if 'invoices' in tables and not set(choices)&{'invoices','sales'} and conn.execute("SELECT 1 FROM invoices WHERE branch_id=? AND COALESCE(sync_status,'pending') NOT IN ('synced','cancelled_reset') LIMIT 1",(branch_id,)).fetchone():raise ValueError('إلغاء فواتير غير مرسلة يتطلب اختيار الفواتير والمعلقات معًا؛ لم تُحذف أي فاتورة')
        for table in ('sync_queue','erp_outbox'):
            if table in tables:
                pending_status="COALESCE(sync_status,'pending') NOT IN ('synced','ignored','cancelled_reset')"
                if 'device_id' in tables[table] and conn.execute("SELECT 1 FROM "+table+" WHERE "+pending_status+" AND COALESCE(device_id,'')<>? LIMIT 1",(device_id,)).fetchone():raise ValueError('توجد معلّقات لهوية أخرى أو غير محددة؛ لم يُطبق التصفير')
                conn.execute('UPDATE '+table+" SET sync_status='cancelled_reset',sync_error=? WHERE "+pending_status,('Cancelled by authorized branch reset '+command['reset_id'],))
        if 'transfer_logs' in tables and 'receipt_pending' in tables['transfer_logs']:conn.execute('UPDATE transfer_logs SET receipt_pending=0,receipt_error=? WHERE to_branch_id=? AND receipt_pending=1',('Cancelled by branch reset '+command['reset_id'],branch_id))
        if 'exception_settlements' in tables:
            scope_column=next((name for name in ('branch_id','source_branch_id') if name in tables['exception_settlements']),None)
            if scope_column:conn.execute("UPDATE exception_settlements SET sync_status='cancelled_reset' WHERE sync_status='pending' AND "+scope_column+'=?',(branch_id,))
            elif conn.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():raise ValueError('لا يمكن إثبات فرع التسويات المعلقة؛ يلزم مراجعة الإدارة')
    plan=make_plan(conn,branch_id,choices);apply_plan(conn,plan)
    if 'shifts' in choices:
        conn.execute('DELETE FROM local_meta WHERE key=?',('last_shift_number:'+str(branch_id),))
        if 'local_shift_uploads' in tables:conn.execute('DELETE FROM local_shift_uploads WHERE branch_id=?',(branch_id,))
    elif 'pending' in choices and 'shift_closures' in tables:
        conn.execute('CREATE TABLE IF NOT EXISTS local_shift_uploads(branch_id INTEGER NOT NULL,shift_date TEXT NOT NULL,shift_number INTEGER NOT NULL,synced_at TEXT,last_error TEXT,cancelled_reset_id TEXT,PRIMARY KEY(branch_id,shift_date,shift_number))')
        cols={r[1] for r in conn.execute('PRAGMA table_info(local_shift_uploads)')}
        if 'cancelled_reset_id' not in cols:conn.execute('ALTER TABLE local_shift_uploads ADD COLUMN cancelled_reset_id TEXT')
        conn.execute('INSERT OR IGNORE INTO local_shift_uploads(branch_id,shift_date,shift_number) SELECT branch_id,shift_date,shift_number FROM shift_closures WHERE branch_id=?',(branch_id,))
        conn.execute('UPDATE local_shift_uploads SET cancelled_reset_id=? WHERE branch_id=? AND synced_at IS NULL',(command['reset_id'],branch_id))
    for draft_key in drafts:conn.execute('DELETE FROM local_meta WHERE key=?',(draft_key,))
    conn.execute('DELETE FROM local_meta WHERE key LIKE ?',('invoice_numbers:'+str(branch_id)+':%',))
    conn.execute('DELETE FROM local_meta WHERE key=?',('branch_operational_state:'+str(branch_id),))
    if 'central_z_summary_cache' in tables:conn.execute('DELETE FROM central_z_summary_cache WHERE branch_id=?',(branch_id,))
    receipt={'reset_id':command['reset_id'],'reset_seq':command['reset_seq'],'branch_id':branch_id,'generation':command['generation'],'fingerprint':digest}
    for k,value in [(key,json.dumps(receipt)),('last_branch_reset:'+str(branch_id),json.dumps(receipt)),('sync_generation',command['generation'])]:conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(k,value))
    return True
