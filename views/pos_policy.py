"""POS-only, session-memory sale isolation. No global finance permission changes."""
import sqlite3,re,json,uuid
from decimal import Decimal

DATA_TABLES={'item_barcodes','branches','items','inventory_batches','customers','app_settings','user_branch_permissions','users'}
TABLES=DATA_TABLES|{'invoices','negative_sales_logs','shift_closures','treasuries','treasury_movements','supplier_payments','transfer_logs','financial_vouchers','expenses','revenues','local_meta','local_shift_uploads','sync_queue','erp_outbox','exception_settlements'}
GLOBAL_ROLES={'Super_Admin','Admin','Manager','General_Supervisor'}


def actor(conn,user_id):
    row=conn.execute('SELECT id,role,branch_id,is_active FROM users WHERE id=?',(user_id,)).fetchone()
    if not row or not row['is_active']:raise PermissionError('الحساب غير نشط؛ أعد تسجيل الدخول')
    return dict(row)


def is_real_actor(value):return value['role']=='Cashier'


class MemoryConnection:
    virtual_pos=True
    def __init__(self,source,owner):
        self.owner=(owner['id'],owner['role']);self.serial=0;self._closed=False
        self._conn=sqlite3.connect(':memory:',check_same_thread=False);self._conn.row_factory=sqlite3.Row
        raw=getattr(source,'_conn',source)
        if isinstance(raw,sqlite3.Connection):
            raw.backup(self._conn)
            for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():self._conn.execute('DROP TRIGGER "'+row[0].replace('"','""')+'"')
            for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
                if row[0] not in DATA_TABLES:self._conn.execute('DELETE FROM "'+row[0].replace('"','""')+'"')
            self._conn.execute('DELETE FROM users WHERE id<>?',(owner['id'],))
            columns={r[1] for r in self._conn.execute('PRAGMA table_info(users)')}
            if 'password' in columns:self._conn.execute("UPDATE users SET password=''")
        else:
            existing={r['table_name'] for r in source.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()").fetchall()}
            for table in sorted(TABLES&existing):
                cursor=source.execute('SELECT * FROM '+table+' WHERE 1=0');columns=[r[0] for r in cursor.description]
                definitions=[('"'+name+'" INTEGER PRIMARY KEY' if name=='id' else '"'+name+'"') for name in columns]
                self._conn.execute('CREATE TABLE "'+table+'" ('+','.join(definitions)+')')
                if table not in DATA_TABLES:continue
                where=' WHERE id=?' if table=='users' else ''
                rows=source.execute('SELECT * FROM '+table+where,(owner['id'],) if where else ()).fetchall()
                for row in rows:
                    values=[self._value(row[name]) if name!='password' else '' for name in columns]
                    self._conn.execute('INSERT INTO "'+table+'" VALUES('+','.join('?' for _ in columns)+')',values)
            for table,definition in {'local_meta':'key TEXT PRIMARY KEY,value TEXT','sync_queue':'sync_status TEXT','erp_outbox':'sync_status TEXT','local_shift_uploads':'branch_id INTEGER,shift_date TEXT,shift_number INTEGER,synced_at TEXT'}.items():self._conn.execute('CREATE TABLE IF NOT EXISTS '+table+' ('+definition+')')
        if owner['role'] not in GLOBAL_ROLES:
            bid=owner.get('branch_id')
            self._conn.execute('DELETE FROM branches WHERE id<>? OR ? IS NULL',(bid,bid))
            for table in ('items','inventory_batches'):self._conn.execute('DELETE FROM '+table+' WHERE branch_id<>? OR ? IS NULL',(bid,bid))
        if self._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='item_barcodes'").fetchone():
            self._conn.execute('DELETE FROM item_barcodes WHERE item_code NOT IN (SELECT item_code FROM items)')
        self._conn.commit()
    @staticmethod
    def _value(value):
        if isinstance(value,Decimal):return float(value)
        if isinstance(value,(dict,list)):return json.dumps(value)
        if value is not None and not isinstance(value,(str,int,float,bytes)):return str(value)
        return value
    def execute(self,sql,args=()):
        sql=re.sub(r'\s+FOR\s+UPDATE(?:\s+OF\s+\w+)?','',sql,flags=re.I)
        sql=re.sub(r'\b(?:BIGSERIAL|SERIAL)\s+PRIMARY\s+KEY','INTEGER PRIMARY KEY AUTOINCREMENT',sql,flags=re.I)
        return self._conn.execute(sql,tuple(self._value(x) for x in args))
    def executemany(self,sql,args):return self._conn.executemany(sql,args)
    def commit(self):self._conn.commit()
    def rollback(self):self._conn.rollback()
    @property
    def in_transaction(self):return self._conn.in_transaction
    def close(self):pass  # Short-lived view leases do not own the session context.
    def dispose(self):
        if not self._closed:self._conn.close();self._closed=True
    def next_number(self):return 'P-'+uuid.uuid4().hex[:16].upper()


def clear_memory(state):
    value=state.pop('_pos_memory_context',None)
    if value is not None:value.dispose()
    for key in ('cart','last_invoice','pos_success_pending','_sale_draft_scope','_sale_draft_record','_pos_actor_key','_pos_branch_id'):
        state.pop(key,None)


def clear_disposed_state(state):
    value=state.get('_pos_memory_context')
    if value is not None and value._closed:clear_memory(state)


def _pin_to_session(value):
    import streamlit as st
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    if get_script_run_ctx(suppress_warning=True) is None:return value
    global _session_resource
    if '_session_resource' not in globals():
        @st.cache_resource(scope='session',on_release=lambda resource:resource.dispose())
        def scoped_resource(token,_resource):return _resource
        _session_resource=scoped_resource
    return _session_resource(uuid.uuid4().hex,_resource=value)


def connection(state,source_factory,real_factory):
    source=source_factory()
    try:
        owner=actor(source,state.get('user_id'))
        local_super=False
        if owner['role']=='Super_Admin':
            from sherif_local_identity import local_identity, authorized_branch
            if local_identity(source):
                authorized_branch(source,owner['id'])
                local_super=True
    finally:source.close()
    clear_disposed_state(state)
    key=(owner['id'],owner['role'])
    if state.get('_pos_actor_key')!=key:
        prior=state.get('_pos_actor_key')
        if prior and prior[1]=='Cashier' and (state.get('cart') or state.get('_sale_draft_save_failed')):raise PermissionError('تغير الحساب؛ يلزم تأمين سلة الكاشير السابقة قبل فتح سياق آخر')
        clear_memory(state);state['cart']=[];state['_pos_actor_key']=key
    if is_real_actor(owner) or local_super or state.get('pos_active_view') in ('التقارير','الأرشيف'):
        return real_factory()
    value=state.get('_pos_memory_context')
    if value is None:
        source=source_factory()
        try:value=MemoryConnection(source,owner)
        finally:source.close()
        value=_pin_to_session(value)
        state['_pos_memory_context']=value
    return value,'memory'





def document_html(html,invoice):
    if not invoice.get('_non_financial'):return html
    warning='<div style="border:3px solid #000;padding:10px;font-size:20px;font-weight:bold;text-align:center;color:#000;background:#fff">غير صالحة للاعتماد المالي — لا تُثبت عملية بيع</div>'
    return html.replace('<body>', '<body>'+warning,1).replace('</body>',warning+'</body>',1)
