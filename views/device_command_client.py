"""Crash-resumable administrative commands inside the existing sync worker."""
import json,hashlib,uuid
KEY='device_command_intent'

def _meta(conn):return dict(conn.execute('SELECT key,value FROM local_meta').fetchall())
def _put(conn,key,value):conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(key,value))
def _sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
def _save(conn,journal):_put(conn,KEY,json.dumps(journal,sort_keys=True,ensure_ascii=False))

def _proof(conn,safe):
    # Existing safety checks include all supported outboxes, transfer receipts,
    # shift ACKs and durable open carts. Historical synced invoices are retained.
    safe(conn,'reinitialize')
    if conn.execute("SELECT 1 FROM local_meta WHERE key LIKE 'history_cancellation_ack:%' LIMIT 1").fetchone():raise ValueError('تنتظر تسوية مالية إيصال استلام؛ يؤجل إجراء الجهاز')
    rows=conn.execute('SELECT id,offline_uuid,invoice_number,remote_invoice_id,sync_status FROM invoices ORDER BY id').fetchall()
    return dict(pending_invoices=0,pending_operations=0,open_drafts=0,unconfirmed_shifts=0,
        local_digest=_sha([tuple(r) for r in rows]))

def run_once(connection_factory,lock,request,apply_snapshot,provision_users,safe,archive_prepare,archive_isolate):
    """request(path,payload,device_id,credential) is authenticated HTTPS only."""
    with lock:
        conn=connection_factory()
        try:
            meta=_meta(conn);stored=meta.get(KEY)
            journal=json.loads(stored) if stored else None
            if not journal:
                identity=meta.get('bound_device_id');credential=meta.get('device_token')
                if not identity or meta.get('device_active')!='1':return {'state':'not_registered'}
                envelope=request('/device-commands/next',None,identity,credential)
                command=envelope.get('command')
                if not command:return {'state':'no_command'}
                if command.get('device_id')!=identity or (str(command.get('from_branch_id')),str(command.get('from_number')))!=(meta.get('bound_branch_id'),meta.get('device_number')):raise ValueError('الأمر لا يطابق هوية الجهاز وفرعه')
                command_id=str(uuid.UUID(command['command_id']))
                if command['operation'] not in ('move','reset','delete_registration'):raise ValueError('أمر غير مدعوم')
                conn.execute('BEGIN IMMEDIATE')
                try:proof=_proof(conn,safe)
                except ValueError:
                    conn.rollback();return {'state':'waiting_for_pending_work','command_id':command_id}
                journal=dict(command=command,source_credential=credential,phase='secured',proof=proof)
                _save(conn,journal);conn.commit()
                if command['operation']=='move':
                    conn.execute('BEGIN IMMEDIATE')
                    archive,tables=archive_prepare(conn,command_id)
                    journal['archive']=archive;journal['tables']=tables
                    from pathlib import Path
                    journal['proof']['archive_sha256']=hashlib.sha256(Path(archive).read_bytes()).hexdigest()
                    _save(conn,journal);conn.commit()
            command=journal['command'];identity=command['device_id'];command_id=command['command_id']
            if journal['phase']=='secured':
                # Recovery after guard creation but before archive creation.
                if command['operation']=='move' and not journal.get('archive'):
                    conn.execute('BEGIN IMMEDIATE');archive,tables=archive_prepare(conn,command_id)
                    from pathlib import Path
                    journal.update(archive=archive,tables=tables);journal['proof']['archive_sha256']=hashlib.sha256(Path(archive).read_bytes()).hexdigest()
                    _save(conn,journal);conn.commit()
                journal['remote_prepare_started']=True
                conn.execute('BEGIN IMMEDIATE');_save(conn,journal);conn.commit()
                reply=request('/device-commands/prepare',{'command_id':command_id,'proof':journal['proof']},identity,journal['source_credential'])
                for key in ('command_id','device_id','operation','from_branch_id','from_number','to_branch_id','to_number'):
                    if reply.get(key)!=command[key]:raise ValueError('استجابة اعتماد لا تطابق الأمر')
                conn.execute('BEGIN IMMEDIATE')
                if command['operation']=='move':
                    if not reply.get('device_token'):raise ValueError('لم يصل اعتماد الفرع الجديد')
                    archive_isolate(conn,journal['archive'],journal['tables'])
                    for key,value in dict(branch_id=str(command['to_branch_id']),bound_branch_id=str(command['to_branch_id']),bound_device_id=identity,
                        device_number=str(command['to_number']),device_name=command['device_name'],device_token=reply['device_token'],device_active='1',server_enrolled='1',setup_complete='0').items():_put(conn,key,value)
                    journal['target_credential']=reply['device_token']
                else:
                    _put(conn,'device_active','0');_put(conn,'setup_complete','0')
                journal['phase']='rebound';_save(conn,journal);conn.commit()
            if journal['phase']=='rebound':
                snapshot_sha=None
                if command['operation']=='move':
                    data=request('/device-commands/snapshot',{'command_id':command_id},identity,journal['target_credential'])
                    snapshot_sha=_sha(data['snapshot'])
                    ok,error=apply_snapshot(data['snapshot'])
                    if not ok:raise ValueError('لم يكتمل تنزيل بيانات الفرع الجديد؛ يظل الجهاز محميًا')
                    users_result=provision_users(data['offline_users'],command['to_branch_id'])
                    if isinstance(users_result,tuple) and not users_result[0]:raise ValueError('لم يكتمل تجهيز مستخدمي الفرع الجديد')
                completion=dict(command_id=command_id,device_id=identity,branch_id=command['to_branch_id'],device_number=str(command['to_number']),applied=True)
                if snapshot_sha:completion['snapshot_sha256']=snapshot_sha
                if journal.get('archive'):completion['archive_sha256']=journal['proof']['archive_sha256']
                journal.update(phase='applied',completion=completion);conn.execute('BEGIN IMMEDIATE');_save(conn,journal);conn.commit()
            reply=request('/device-commands/complete',{'command_id':command_id,'completion':journal['completion']},identity,journal.get('target_credential') or journal['source_credential'])
            if reply.get('state')!='completed' or any(reply.get(k)!=v for k,v in journal['completion'].items() if k not in ('snapshot_sha256','archive_sha256')):raise ValueError('لم يصل إيصال نجاح مطابق؛ ستُعاد المحاولة')
            conn.execute('BEGIN IMMEDIATE')
            _put(conn,'device_command_receipt:'+command_id,json.dumps(reply,sort_keys=True))
            _put(conn,'device_command_relogin_required',command_id)
            if command['operation']=='move':_put(conn,'setup_complete','1')
            conn.execute('DELETE FROM local_meta WHERE key=?',(KEY,));conn.commit()
            return {'state':'completed','command_id':command_id,'operation':command['operation']}
        except Exception:
            conn.rollback()
            value=locals().get('journal')
            if value and value.get('phase')=='secured' and not value.get('remote_prepare_started'):
                conn.execute('DELETE FROM local_meta WHERE key=?',(KEY,));conn.commit()
            raise
        finally:conn.close()

def process_pending_command():
    import offline_store,branch_auth
    from views.device_lifecycle import assert_local_safe
    from views.device_recovery_client import prepare_branch_archive,isolate_archived_branch
    from urllib.request import Request,urlopen
    def request(path,payload,identity,credential):
        headers={'X-Device-ID':identity,'X-Device-Token':credential,'Accept':'application/json'}
        data=json.dumps(payload).encode() if payload is not None else None
        if data:headers['Content-Type']='application/json'
        url=branch_auth._api_url()+path
        with urlopen(Request(url,data=data,headers=headers),timeout=20) as response:return json.load(response)
    return run_once(lambda:offline_store.get_local_connection(queue_writes=False),offline_store._SYNC_LOCK,request,
        lambda data:offline_store.sync_reference_data(approved_snapshot=data),branch_auth.provision_offline_users,
        assert_local_safe,prepare_branch_archive,isolate_archived_branch)
