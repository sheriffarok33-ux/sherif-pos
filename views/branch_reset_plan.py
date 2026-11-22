"""Allowlisted branch-only reset plans. No backups, identities or arbitrary SQL."""
import hashlib,json,re,sqlite3
from views.device_registry import execute
OPTIONS={'invoices','sales','shifts','revenues','expenses','items','quantities','pending'}
PROTECTED={'users','branches','branch_devices','branch_device_changes','local_meta','app_settings','sync_queue','erp_outbox','offline_sync_receipts','offline_operation_receipts','erp_sync_receipts','device_shift_sync_receipts','audit_events_v1','activity_logs','sessions','role_permissions','user_branch_permissions','sidebar_menu_order','branch_reset_commands','branch_reset_devices','branch_reset_state'}
OWNERS=[('purchase_items','purchase_id','purchases','id'),('purchase_items','item_id','items','id'),('inventory_batches','item_id','items','id'),('shift_settlement_adjustments','closure_id','shift_closures','id'),('transfer_safety_log','transfer_log_id','transfer_logs','id')]
def sqlite(conn):return isinstance(getattr(conn,'_conn',conn),sqlite3.Connection)
def quote(name):
    if not re.fullmatch('[a-z_][a-z0-9_]*',name):raise ValueError('اسم جدول غير مدعوم في التصفير')
    return '"'+name+'"'
def scalar(row):return next(iter(row.values())) if isinstance(row,dict) else row[0]
def catalog(conn):
    sql="SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'" if sqlite(conn) else "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'"
    result={}
    for row in execute(conn,sql).fetchall():
        name=scalar(row);cur=execute(conn,'SELECT * FROM '+quote(name)+' WHERE 1=0');result[name]=[c[0] for c in cur.description]
    return result
def relations(conn,tables):
    links=[(*r,1) for r in OWNERS if r[0] in tables and r[2] in tables and r[1] in tables[r[0]] and r[3] in tables[r[2]]]
    if sqlite(conn):
        for table in tables:
            for row in execute(conn,'PRAGMA foreign_key_list('+quote(table)+')').fetchall():
                links.append((table,row[3],row[2],row[4] or 'id',1 if row[1]==0 else 2))
    else:
        rows=execute(conn,"""SELECT c.conrelid::regclass::text AS child,a.attname AS col,
            c.confrelid::regclass::text AS parent,b.attname AS pk,cardinality(c.conkey) AS size
            FROM pg_constraint c JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
            JOIN pg_attribute b ON b.attrelid=c.confrelid AND b.attnum=c.confkey[1]
            JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace
            WHERE c.contype='f' AND n.nspname=current_schema()""").fetchall()
        links.extend((r['child'],r['col'],r['parent'],r['pk'],r['size']) for r in rows)
    return sorted(set(r for r in links if r[0] in tables and r[2] in tables))
def normalized(choices):
    if not isinstance(choices,(list,tuple,set)) or not choices or not set(choices)<=OPTIONS:raise ValueError('خيارات تصفير غير صالحة')
    return sorted(set(choices))
def make_plan(conn,branch_id,choices):
    branch_id=int(branch_id);choices=set(normalized(choices))
    if branch_id<=0:raise ValueError('يلزم اختيار فرع واحد محدد')
    tables=catalog(conn);links=relations(conn,tables)
    selected=set()
    if choices&{'invoices','sales'}:selected|={'invoices','negative_sales_logs'}
    for flag,table in [('shifts','shift_closures'),('revenues','revenues'),('expenses','expenses'),('items','items')]:
        if flag in choices:selected.add(table)
    # A full financial reset explicitly includes the selected branch's journals.
    if choices&{'invoices','sales'} and {'shifts','revenues','expenses'}<=choices:selected|={'document_registry','treasury_movements','financial_vouchers'}
    selected&=set(tables)
    while True:
        expanded=selected|{c for c,_,p,_,_ in links if p in selected}
        if expanded==selected:break
        selected=expanded
    if selected&PROTECTED:raise ValueError('توجد علاقة ببيانات هوية أو تدقيق أو مزامنة محمية؛ لم يتم التصفير')
    for child,col,parent,pk,size in links:
        if parent in selected and size!=1:raise ValueError('علاقة مركبة تحتاج مراجعة آمنة: '+child)
    predicates={}
    def scope(table,seen=()):
        if table in predicates:return predicates[table]
        if table in seen:raise ValueError('علاقة دورية تمنع إثبات نطاق الفرع: '+table)
        columns=tables[table]
        if 'branch_id' in columns:answer=('branch_id=?',(branch_id,))
        elif {'from_branch_id','to_branch_id'}<=set(columns):answer=('from_branch_id=? AND to_branch_id=?',(branch_id,branch_id))
        else:
            clauses=[];args=[]
            for child,col,parent,pk,size in links:
                if child!=table or parent in PROTECTED:continue
                try:pred,values=scope(parent,seen+(table,))
                except ValueError:continue
                clauses.append(quote(col)+' IN (SELECT '+quote(pk)+' FROM '+quote(parent)+' WHERE '+pred+')');args.extend(values)
            if not clauses:raise ValueError('لا يمكن إثبات أن الجدول يخص الفرع وحده: '+table)
            answer=('('+' AND '.join(clauses)+')',tuple(args))
        predicates[table]=answer;return answer
    for child,col,parent,pk,size in links:
        if parent not in selected:continue
        cp,ca=scope(child);pp,pa=scope(parent)
        count=scalar(execute(conn,'SELECT COUNT(*) FROM '+quote(child)+' WHERE '+quote(col)+' IN (SELECT '+quote(pk)+' FROM '+quote(parent)+' WHERE '+pp+') AND NOT COALESCE(('+cp+'),FALSE)',pa+ca).fetchone())
        if count:raise ValueError('توجد سجلات مرتبطة بفرع آخر في '+child+'؛ أُلغي التصفير لحمايتها')
    order=[];visiting=set()
    def visit(table):
        if table in order:return
        if table in visiting:raise ValueError('علاقة دورية تحتاج مراجعة: '+table)
        visiting.add(table)
        for child,_,parent,_,_ in links:
            if parent==table and child in selected:visit(child)
        visiting.remove(table);order.append(table)
    for table in sorted(selected):visit(table)
    rows=[]
    for table in order:
        pred,args=scope(table);count=int(scalar(execute(conn,'SELECT COUNT(*) FROM '+quote(table)+' WHERE '+pred,args).fetchone()))
        rows.append({'table':table,'action':'delete','where':pred,'args':list(args),'count':count})
    if 'quantities' in choices and 'items' not in choices:
        for table,column in [('items','quantity'),('inventory_batches','remaining_quantity')]:
            if table not in tables or column not in tables[table]:continue
            pred,args=scope(table);count=int(scalar(execute(conn,'SELECT COUNT(*) FROM '+quote(table)+' WHERE '+pred,args).fetchone()))
            rows.append({'table':table,'action':'zero','column':column,'where':pred,'args':list(args),'count':count})
    return rows
def fingerprint(branch_id,choices,plan):return hashlib.sha256(json.dumps({'branch_id':int(branch_id),'choices':normalized(choices),'plan':plan},sort_keys=True,separators=(',',':')).encode()).hexdigest()
def apply_plan(conn,plan):
    for row in plan:
        sql=('DELETE FROM '+quote(row['table'])) if row['action']=='delete' else ('UPDATE '+quote(row['table'])+' SET '+quote(row['column'])+'=0')
        execute(conn,sql+' WHERE '+row['where'],tuple(row['args']))
