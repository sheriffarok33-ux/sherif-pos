"""Scoped party reference snapshots; never post a financial transaction."""
import json,time
FIELDS={'customers':('id','customer_name','phone','total_purchases','balance','marketing_consent'),
        'suppliers':('id','supplier_name','phone','balance')}

def namespace(branch_id):return 'test:7' if int(branch_id)==7 else 'production'

def export_parties(cursor,branch_id):
    # The API has authorized this bound branch. Keep the established server
    # TEST account router; never query raw public masters around its boundary.
    cursor.set_party_branch(int(branch_id))
    result={'protocol':1,'namespace':namespace(branch_id),'branch_id':int(branch_id),'server_time':int(time.time())}
    for table,fields in FIELDS.items():
        cursor.execute('SELECT '+','.join(fields)+' FROM '+table+' ORDER BY id')
        result[table]=[{k:row[k] for k in fields} for row in cursor.fetchall()]
    return result

def apply_parties(conn,payload,branch_id):
    if not payload:return {'state':'not_provided'}
    expected=namespace(branch_id)
    if payload.get('protocol')!=1 or payload.get('namespace')!=expected or payload.get('branch_id')!=int(branch_id):raise ValueError('بيانات العملاء لا تطابق نطاق الجهاز')
    if type(payload.get('server_time')) is not int or payload['server_time']<=0:raise ValueError('وقت لقطة الأرصدة غير صالح')
    last=conn.execute("SELECT value FROM local_meta WHERE key='party_reference_last_success'").fetchone()
    if last and int(last[0])>payload['server_time']:raise ValueError('وصلت لقطة أرصدة أقدم؛ لم تستبدل البيانات الأحدث')
    previous=conn.execute("SELECT value FROM local_meta WHERE key='party_reference_namespace'").fetchone()
    if previous and previous[0]!=expected:raise ValueError('أرصدة محلية من نطاق سابق؛ يلزم مطابقة آمنة دون استبدالها')
    legacy_unscoped=not previous and any(conn.execute('SELECT 1 FROM '+table+' LIMIT 1').fetchone() for table in FIELDS)
    # Same transaction as the existing reference import, after its pending-work
    # guards. Validate all rows before applying either direction of balance.
    for table,fields in FIELDS.items():
        rows=payload.get(table)
        if not isinstance(rows,list):raise ValueError('لقطة العملاء والموردين غير مكتملة')
        ids=set()
        for row in rows:
            if type(row.get('id')) is not int or row['id']<=0 or row['id'] in ids or any(k not in row for k in fields):raise ValueError('معرف عميل أو مورد غير صالح')
            ids.add(row['id'])
    count=0
    for table,fields in FIELDS.items():
        for source in payload[table]:
            remote=source['id']
            mapped=conn.execute('SELECT local_id FROM erp_id_map WHERE table_name=? AND remote_id=?',(table,remote)).fetchone()
            local=int(mapped[0]) if mapped else remote
            if legacy_unscoped and not mapped:
                local=int(conn.execute('SELECT COALESCE(MAX(id),0)+1 FROM '+table).fetchone()[0])
            current=conn.execute('SELECT * FROM '+table+' WHERE id=?',(local,)).fetchone()
            if current and not mapped:
                name='customer_name' if table=='customers' else 'supplier_name'
                conflict=conn.execute('SELECT 1 FROM erp_id_map WHERE table_name=? AND local_id=?',(table,local)).fetchone()
                if conflict or current['phone']!=source['phone'] or current[name]!=source[name]:
                    local=int(conn.execute('SELECT COALESCE(MAX(id),0)+1 FROM '+table).fetchone()[0])
            values=[local if field=='id' else source[field] for field in fields]
            conn.execute('INSERT INTO '+table+' ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+') ON CONFLICT(id) DO UPDATE SET '+','.join(field+'=excluded.'+field for field in fields if field!='id'),values)
            conn.execute('INSERT INTO erp_id_map(table_name,local_id,remote_id) VALUES(?,?,?) ON CONFLICT(table_name,local_id) DO UPDATE SET remote_id=excluded.remote_id',(table,local,remote));count+=1
    for key,value in (('party_reference_namespace',expected),('party_reference_last_success',str(payload['server_time']))):
        conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(key,value))
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('party_reference_customer_ids',json.dumps([int(conn.execute("SELECT local_id FROM erp_id_map WHERE table_name='customers' AND remote_id=?",(r['id'],)).fetchone()[0]) for r in payload['customers']])))
    return {'state':'applied','records':count,'legacy_rows_preserved':bool(legacy_unscoped)}


def credit_accounts(conn):
    import sqlite3
    raw=getattr(conn,'_conn',conn)
    if isinstance(raw,sqlite3.Connection):
        row=conn.execute("SELECT value FROM local_meta WHERE key='party_reference_customer_ids'").fetchone()
        if row:
            ids=json.loads(row[0])
            if not ids:return []
            return conn.execute('SELECT id,customer_name,phone,balance FROM customers WHERE id IN ('+','.join('?' for _ in ids)+') ORDER BY customer_name,id',ids).fetchall()
    return conn.execute('SELECT id,customer_name,phone,balance FROM customers ORDER BY customer_name,id').fetchall()
