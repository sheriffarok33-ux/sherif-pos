"""Import server-proven credit notes once; never enqueue them as new sales."""
import json,hashlib,uuid
from decimal import Decimal

def apply_page(conn,data,device_id,branch_id,generation):
    if data.get('device_id')!=device_id or data.get('branch_id')!=int(branch_id) or str(data.get('generation') or '')!=str(generation or ''):raise ValueError('إيصالات الإلغاء خارج الجهاز أو الفرع أو الجيل')
    records=data.get('records')
    if not isinstance(records,list) or len(records)>200:raise ValueError('صفحة إلغاء غير صالحة')
    deferred=0;applied=0
    for record in records:
        marker='device_invoice_exclusion:'+str(branch_id)+':'+record['offline_uuid']
        if conn.execute('SELECT 1 FROM local_meta WHERE key=?',(marker,)).fetchone():continue
        credit=record['credit'];details=json.loads(credit['notes'] or '{}') if isinstance(credit['notes'],str) else credit['notes']
        if (credit['branch_id']!=int(branch_id) or credit['source_device_id']!=device_id or not details.get('_administrative_reversal')
                or details.get('reversal_of_uuid')!=record['offline_uuid'] or Decimal(str(credit['total_amount']))!=-Decimal(str(record['original_total']))):raise ValueError('مستند عكسي لا يطابق الفاتورة الأصلية')
        original=conn.execute('SELECT * FROM invoices WHERE offline_uuid=?',(record['offline_uuid'],)).fetchone()
        if original:
            if (int(original['branch_id'])!=int(branch_id) or original['invoice_number']!=record['invoice_number']
                    or Decimal(str(original['total_amount']))!=Decimal(str(record['original_total']))):raise ValueError('النسخة المحلية لا تطابق إيصال الإلغاء؛ لم تُحذف')
            # Let the existing original shift receipt retry finish BEFORE adding
            # a new credit UUID to the local closed shift's invoice membership.
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_shift_uploads'").fetchone():
                unsent=conn.execute('SELECT 1 FROM shift_closures s LEFT JOIN local_shift_uploads u ON u.branch_id=s.branch_id AND u.shift_date=s.shift_date AND u.shift_number=s.shift_number WHERE s.branch_id=? AND u.synced_at IS NULL LIMIT 1',(branch_id,)).fetchone()
                if unsent:deferred+=1;continue
            customer=record.get('customer_current')
            if customer:
                if _pending_customer_work(conn):deferred+=1;continue
                _cache_customer(conn,customer)
            previous=conn.execute('SELECT * FROM invoices WHERE offline_uuid=?',(record['credit_uuid'],)).fetchone()
            if previous:
                if previous['invoice_number']!=credit['invoice_number'] or Decimal(str(previous['total_amount']))!=Decimal(str(credit['total_amount'])):raise ValueError('هوية المستند العكسي مستخدمة بمحتوى مختلف')
            else:
                # Translate only item references. No stock, customer balance or
                # treasury mutation occurs locally; normal reference sync owns it.
                for item in details.get('items',[]):
                    mapping=conn.execute("SELECT local_id FROM erp_id_map WHERE table_name='items' AND remote_id=?",(item['id'],)).fetchone()
                    if mapping:item['id']=mapping[0]
                conn.execute('''INSERT INTO invoices(branch_id,user_id,customer_name,customer_phone,total_amount,payment_method,notes,shift_status,created_at,sold_at,offline_uuid,sync_status,remote_invoice_id,source_device_id,invoice_number,shift_uuid)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,'synced',?,?,?,?)''',(branch_id,credit['user_id'],credit.get('customer_name') or '',credit.get('customer_phone') or '',float(credit['total_amount']),credit['payment_method'],json.dumps(details,ensure_ascii=False),credit['shift_status'],str(credit['created_at']),str(credit.get('sold_at') or credit['created_at']),record['credit_uuid'],record['credit_invoice_id'],device_id,credit['invoice_number'],credit.get('shift_uuid')))
            conn.execute("UPDATE invoices SET sync_status='synced',remote_invoice_id=?,shift_status='Z_Closed' WHERE offline_uuid=?",(record['invoice_id'],record['offline_uuid']))
        # If the old branch is archived/freshly enrolled, keep this history as
        # read-only evidence. Never insert an isolated negative invoice without
        # its local positive original or import another branch's transactions.
        conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(marker,json.dumps(record,ensure_ascii=False,sort_keys=True)))
        applied+=1
    return {'applied':applied,'deferred':deferred}

def sync_cancellations():
    import offline_store,branch_auth
    from urllib.request import Request,urlopen
    info=branch_auth.local_device_info()
    if info.get('device_active')!='1':return {'state':'not_registered','applied':0}
    branch=int(info['bound_branch_id']);identity=info['bound_device_id']
    with offline_store._SYNC_LOCK:
        conn=offline_store.get_local_connection(queue_writes=False)
        try:
            _flush_acks(conn,branch_auth,info)
            generation=dict(conn.execute("SELECT key,value FROM local_meta WHERE key='sync_generation'")).get('sync_generation','')
            key='device_history_cursor:'+str(branch)+':'+generation
            saved=conn.execute('SELECT value FROM local_meta WHERE key=?',(key,)).fetchone();after=int(saved[0]) if saved else 0
            url=branch_auth._api_url()+'/device-history/cancellations?after='+str(after)
            try:
                with urlopen(Request(url,headers=branch_auth.device_auth_headers()),timeout=12) as response:data=json.load(response)
            except __import__('urllib.error',fromlist=['HTTPError']).HTTPError as error:
                if error.code==404:return {'state':'server_upgrade_required','applied':0}
                raise
            conn.execute('BEGIN IMMEDIATE')
            current=dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('bound_device_id','bound_branch_id','sync_generation')"))
            if current.get('bound_device_id')!=identity or str(current.get('bound_branch_id'))!=str(branch) or str(current.get('sync_generation') or '')!=generation:raise ValueError('تغير نطاق الجهاز أثناء وصول الإيصال')
            result=apply_page(conn,data,identity,branch,generation)
            if not result['deferred']:
                conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(key,str(data['next_after'])))
                if data['records']:
                    ids=sorted(int(r['credit_invoice_id']) for r in data['records'])
                    request_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'device-cancellation-ack:'+identity+':'+str(branch)+':'+generation+':'+','.join(map(str,ids))))
                    ack=dict(request_id=request_id,branch_id=branch,generation=generation,credit_ids=ids)
                    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('history_cancellation_ack:'+request_id,json.dumps(ack)))
            conn.commit();_flush_acks(conn,branch_auth,info)
            return dict(result,state='waiting_for_shift_ack' if result['deferred'] else 'applied')
        except Exception:conn.rollback();raise
        finally:conn.close()


def _flush_acks(conn,branch_auth,info):
    from urllib.request import Request,urlopen
    rows=conn.execute("SELECT key,value FROM local_meta WHERE key LIKE 'history_cancellation_ack:%' ORDER BY key LIMIT 5").fetchall()
    for key,value in rows:
        body=json.loads(value)
        if body['branch_id']!=int(info['bound_branch_id']):continue
        headers=branch_auth.device_auth_headers();headers['Content-Type']='application/json'
        with urlopen(Request(branch_auth._api_url()+'/device-history/received',data=json.dumps(body).encode(),headers=headers),timeout=10) as response:reply=json.load(response)
        if reply.get('request_id')!=body['request_id'] or reply.get('received') is not True or reply.get('credit_ids')!=body['credit_ids']:raise ValueError('إيصال استلام تسوية غير مطابق')
        conn.execute('DELETE FROM local_meta WHERE key=? AND value=?',(key,value));conn.commit()


def _pending_customer_work(conn):
    import re
    for row in conn.execute("SELECT sql_text FROM sync_queue WHERE COALESCE(sync_status,'pending') NOT IN ('synced','ignored','cancelled_reset')"):
        if re.search(r'\bcustomers\b',row[0] or '',re.I):return True
    for row in conn.execute("SELECT payload_json FROM erp_outbox WHERE COALESCE(sync_status,'pending') NOT IN ('synced','ignored','cancelled_reset')"):
        try:
            value=json.loads(row[0]);events=value.get('events',[]) if isinstance(value,dict) else value
            if any(event.get('table')=='customers' for event in events):return True
        except (TypeError,ValueError,AttributeError):return True
    return False

def _cache_customer(conn,customer):
    for field in ('balance','total_purchases'):
        if not Decimal(str(customer[field])).is_finite():raise ValueError('رصيد عميل غير صالح')
    rows=conn.execute('SELECT id FROM customers WHERE phone=?',(customer['phone'],)).fetchall()
    if len(rows)>1:raise ValueError('حساب العميل المحلي غير وحيد؛ لم يُستبدل أي رصيد')
    if rows:local_id=rows[0][0]
    else:
        local_id=int(customer['id'])
        if conn.execute('SELECT 1 FROM customers WHERE id=?',(local_id,)).fetchone():local_id=int(conn.execute('SELECT COALESCE(MAX(id),0)+1 FROM customers').fetchone()[0])
    mapping=conn.execute("SELECT remote_id FROM erp_id_map WHERE table_name='customers' AND local_id=?",(local_id,)).fetchone()
    if mapping and int(mapping[0])!=int(customer['id']):raise ValueError('خريطة هوية العميل متعارضة؛ لم يتغير رصيده')
    conn.execute('INSERT INTO customers(id,customer_name,phone,balance,total_purchases) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET customer_name=excluded.customer_name,phone=excluded.phone,balance=excluded.balance,total_purchases=excluded.total_purchases',(local_id,customer['customer_name'],customer['phone'],float(customer['balance']),float(customer['total_purchases'])))
    conn.execute("INSERT INTO erp_id_map(table_name,local_id,remote_id) VALUES('customers',?,?) ON CONFLICT(table_name,local_id) DO UPDATE SET remote_id=excluded.remote_id",(local_id,int(customer['id'])))
