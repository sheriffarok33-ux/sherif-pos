"""Use the existing ERP outbox and sync lock; no parallel uploader/service."""
import json,hashlib,uuid

def encoded(payload):return json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str)
def queue_request(conn,body):
    from offline_store import get_device_id,_invoice_sync_generation
    body=dict(body,device_id=get_device_id(),sync_generation=_invoice_sync_generation(conn));raw=encoded(body);h=hashlib.sha256(raw.encode()).hexdigest()
    old=conn.execute('SELECT payload_hash FROM erp_outbox WHERE transaction_uuid=?',(body['transaction_uuid'],)).fetchone()
    if old:
        if old[0]!=h:raise ValueError('معرف طلب محفوظ بمحتوى مختلف')
        return body['transaction_uuid']
    # Duplicate form submits cannot create two concurrent intents for one source.
    other=conn.execute("SELECT transaction_uuid FROM erp_outbox WHERE source='document_correction' AND sync_status='pending' AND json_extract(payload_json,'$.kind')=? AND json_extract(payload_json,'$.branch_id')=? AND json_extract(payload_json,'$.source_number')=?",(body['kind'],body['branch_id'],body['source_number'])).fetchone()
    if other:raise ValueError('يوجد طلب معلق لنفس المستند؛ راجع نتيجته قبل إنشاء طلب آخر')
    conn.execute("INSERT INTO erp_outbox(transaction_uuid,device_id,actor_id,payload_json,payload_hash,source) VALUES(?,?,?,?,?,'document_correction')",(body['transaction_uuid'],body['device_id'],body['actor_id'],raw,h))
    return body['transaction_uuid']

def has_transfer_request(conn,local_id):
    raw=getattr(conn,'_conn',conn)
    mapped=raw.execute("SELECT remote_id FROM erp_id_map WHERE table_name='transfer_logs' AND local_id=?",(local_id,)).fetchone();number=str(mapped[0] if mapped else local_id)
    return bool(raw.execute("SELECT 1 FROM erp_outbox WHERE source='document_correction' AND json_extract(payload_json,'$.kind')='transfer' AND json_extract(payload_json,'$.source_number')=? LIMIT 1",(number,)).fetchone())

def store_ack(conn,ack):
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('document_correction_receipt:'+ack['transaction_uuid'],encoded(ack)))

def cancel_local_pending(conn,transaction_uuid):
    from offline_store import _request_with_auth_retry
    row=conn.execute("SELECT * FROM erp_outbox WHERE transaction_uuid=? AND source='document_correction' AND sync_status='pending'",(transaction_uuid,)).fetchone()
    if not row:raise ValueError('الطلب ليس معلقًا')
    response=_request_with_auth_retry('POST','/documents/corrections/cancel-pending',json=json.loads(row['payload_json']),timeout=30);response.raise_for_status();ack=response.json()
    if ack.get('cancelled') is not True or ack.get('payload_hash')!=row['payload_hash'] or ack.get('transaction_uuid')!=transaction_uuid:raise ValueError('لم يصل إثبات إلغاء الطلب قبل الاعتماد')
    conn.execute('BEGIN IMMEDIATE');store_ack(conn,ack);conn.execute("UPDATE erp_outbox SET sync_status='synced',sync_error=NULL,synced_at=CURRENT_TIMESTAMP WHERE transaction_uuid=?",(transaction_uuid,));conn.commit()
    return ack


def transfer_correction_counts(conn,ids):
    raw=getattr(conn,'_conn',conn);counts={}
    for row in raw.execute("SELECT value FROM local_meta WHERE key LIKE 'document_correction_receipt:%'").fetchall():
        ack=json.loads(row[0])
        if ack.get('kind')=='transfer' and not ack.get('cancelled'):
            remote=int(ack['original_transfer_id']);mapped=raw.execute("SELECT local_id FROM erp_id_map WHERE table_name='transfer_logs' AND remote_id=?",(remote,)).fetchone();local=int(mapped[0]) if mapped else remote
            if local in ids:counts[local]=counts.get(local,0)+1
    return counts
