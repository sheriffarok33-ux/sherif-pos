"""Seal a single local shift under SQLite's write lock, then await the real receipt."""
import json
from datetime import date
from decimal import Decimal

KEY='remote_shift_close_intent'

def _put(conn,key,value):
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(key,value))

def run_once(factory,lock,request,safe,generation):
    with lock:
        conn=factory()
        try:
            meta=dict(conn.execute('SELECT key,value FROM local_meta'))
            identity=meta.get('bound_device_id');token=meta.get('device_token')
            if not identity or meta.get('device_active')!='1':return {'state':'not_registered'}
            stored=meta.get(KEY)
            journal=json.loads(stored) if stored else None
            if journal is None:
                command=request('/device-shift-close/next',None,identity,token).get('request')
                if not command:return {'state':'no_request'}
                if (command['device_id'],str(command['branch_id']))!=(identity,meta.get('bound_branch_id')):
                    raise ValueError('طلب الإغلاق لا يطابق هوية الجهاز والفرع')
                conn.execute('BEGIN IMMEDIATE')
                # This checks all financial queues, prior shift ACKs, administrative
                # holds and durable carts; zero heartbeat counters are not used.
                try:safe(conn,'reinitialize')
                except ValueError:
                    conn.rollback();return {'state':'waiting_for_pending_work','request_id':command['request_id']}
                if conn.execute("SELECT 1 FROM local_meta WHERE key LIKE 'history_cancellation_ack:%' LIMIT 1").fetchone():
                    conn.rollback();return {'state':'waiting_for_reconciliation'}
                rows=conn.execute('SELECT * FROM invoices WHERE branch_id=? AND source_device_id=? AND shift_uuid=? ORDER BY id',
                                  (command['branch_id'],identity,command['shift_uuid'])).fetchall()
                if not rows or any(r['sync_status']!='synced' or str(r['shift_status'])!=str(command['shift_number']) or not r['offline_uuid'] for r in rows):
                    conn.rollback();return {'state':'waiting_for_matching_open_shift'}
                # Only this exact UUID is updated, even when another device/shift
                # shares its display number. Monetary totals are rechecked by API.
                number=command['shift_number'];branch=command['branch_id'];day=date.today().isoformat()
                prior=conn.execute('SELECT id FROM shift_closures WHERE branch_id=? AND shift_number=?',(branch,number)).fetchone()
                if prior:
                    conn.rollback();return {'state':'existing_closure_needs_reconciliation'}
                columns={r[1] for r in conn.execute('PRAGMA table_info(shift_closures)')}
                for column in ('shift_uuid','device_id'):
                    if column not in columns:conn.execute('ALTER TABLE shift_closures ADD COLUMN '+column+' TEXT')
                conn.execute('''CREATE TABLE IF NOT EXISTS local_shift_uploads(branch_id INTEGER NOT NULL,shift_date TEXT NOT NULL,
                    shift_number INTEGER NOT NULL,synced_at TEXT,last_error TEXT,PRIMARY KEY(branch_id,shift_date,shift_number))''')
                amounts={k:Decimal('0') for k in ('cash','card','transfer','credit','other')}
                methods={'كاش (نقدي)':'cash','كاش':'cash','شبكة / بطاقة':'card','بطاقة':'card','تحويل مصرفي':'transfer','دفع آخر':'other','آجل (على الحساب)':'credit'}
                net=gross=Decimal('0')
                for row in rows:
                    if row['payment_method'] not in methods:raise ValueError('طريقة دفع غير معروفة؛ لم تغلق الوردية')
                    value=Decimal(str(row['total_amount']));net+=value;amounts[methods[row['payment_method']]]+=value
                    notes=json.loads(row['notes'] or '{}')
                    gross+=Decimal(str(notes.get('gross_total',value)))
                local_actor=command['actor_id'] if conn.execute('SELECT 1 FROM users WHERE id=?',(command['actor_id'],)).fetchone() else None
                closure=conn.execute('''INSERT INTO shift_closures(branch_id,shift_date,shift_number,gross_sales,net_sales,cash_amount,card_amount,
                    transfer_amount,credit_amount,other_amount,closed_by,notes,shift_uuid,device_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(branch,day,number,str(gross),str(net),str(amounts['cash']),str(amounts['card']),
                    str(amounts['transfer']),str(amounts['credit']),str(amounts['other']),local_actor,'إغلاق بطلب الإدارة المركزية',command['shift_uuid'],identity))
                closure_id=closure.lastrowid
                treasury=conn.execute("SELECT id FROM treasuries WHERE treasury_type='company' ORDER BY id LIMIT 1").fetchone()
                if treasury:treasury_id=treasury['id']
                else:treasury_id=conn.execute("INSERT INTO treasuries(treasury_name,treasury_type,branch_id,is_active) VALUES('الخزينة الرئيسية','company',NULL,1)").lastrowid
                for key,method in (('cash','كاش'),('card','بطاقة'),('transfer','تحويل'),('other','أخرى')):
                    if amounts[key]:
                        conn.execute('''INSERT INTO treasury_movements(treasury_id,movement_type,amount,voucher_no,description,user_id,
                            branch_id,payment_method,movement_date,source_type,source_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                            (treasury_id,'ترحيل وردية',str(amounts[key]),'SHIFT-'+str(branch)+'-'+day+'-'+str(number),
                             'إغلاق بطلب الإدارة المركزية',local_actor,branch,method,day,'shift_close',str(closure_id)))
                conn.execute("UPDATE invoices SET shift_status='Z_Closed' WHERE branch_id=? AND source_device_id=? AND shift_uuid=?",(branch,identity,command['shift_uuid']))
                _put(conn,'last_shift_number:'+str(branch),str(number))
                payload=dict(branch_id=branch,device_id=identity,shift_uuid=command['shift_uuid'],shift_number=number,
                             shift_date=day,invoice_uuids=[r['offline_uuid'] for r in rows],sync_generation=generation(conn),
                             request_id=command['request_id'],proof=dict(sealed=True,pending_invoices=0,pending_operations=0,open_drafts=0))
                journal={'payload':payload,'net_total':str(net)}
                _put(conn,KEY,json.dumps(journal,sort_keys=True));conn.commit()
            payload=journal['payload']
            if (payload['device_id'],str(payload['branch_id']))!=(identity,meta.get('bound_branch_id')):
                raise ValueError('اعتماد الجهاز تغير أثناء إغلاق الوردية')
            reply=request('/device-shift-close/complete',payload,identity,token)
            if reply.get('state')!='completed' or reply.get('request_id')!=payload['request_id'] or reply.get('shift_uuid')!=payload['shift_uuid'] or reply.get('invoice_count')!=len(payload['invoice_uuids']) or Decimal(str(reply.get('net_total')))!=Decimal(journal['net_total']):
                raise ValueError('إيصال الإغلاق غير مطابق؛ يظل الطلب محفوظًا لإعادة التأكيد')
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('''INSERT INTO local_shift_uploads(branch_id,shift_date,shift_number,synced_at,last_error)
                VALUES(?,?,?,CURRENT_TIMESTAMP,NULL) ON CONFLICT(branch_id,shift_date,shift_number)
                DO UPDATE SET synced_at=CURRENT_TIMESTAMP,last_error=NULL''',(payload['branch_id'],payload['shift_date'],payload['shift_number']))
            _put(conn,'remote_shift_close_receipt:'+payload['request_id'],json.dumps(reply,sort_keys=True))
            conn.execute('DELETE FROM local_meta WHERE key=?',(KEY,));conn.commit()
            return {'state':'completed','request_id':payload['request_id']}
        except Exception:
            conn.rollback();raise
        finally:conn.close()

def process_pending_close():
    import offline_store,branch_auth
    from views.device_lifecycle import assert_local_safe
    from urllib.request import Request,urlopen
    def request(path,payload,identity,token):
        headers={'X-Device-ID':identity,'X-Device-Token':token,'Accept':'application/json'}
        data=json.dumps(payload).encode() if payload is not None else None
        if data:headers['Content-Type']='application/json'
        with urlopen(Request(branch_auth._api_url()+path,data=data,headers=headers),timeout=20) as response:
            return json.load(response)
    return run_once(lambda:offline_store.get_local_connection(queue_writes=False),offline_store._SYNC_LOCK,
                    request,assert_local_safe,offline_store._invoice_sync_generation)
