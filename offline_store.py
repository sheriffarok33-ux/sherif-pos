import json
import sqlite3
import threading
import uuid
from pathlib import Path
from datetime import datetime

LOCAL_DB = Path(__file__).with_name('abu_zaid_local.db')
_LOCK = threading.RLock()

class LocalConnection:
    def __init__(self, conn):
        self._conn = conn
    def execute(self, sql, params=()):
        sql = sql.replace('FOR UPDATE', '')
        return self._conn.execute(sql, params or ())
    def executemany(self, sql, seq):
        return self._conn.executemany(sql.replace('FOR UPDATE', ''), seq)
    def commit(self): return self._conn.commit()
    def rollback(self): return self._conn.rollback()
    def close(self): return self._conn.close()
    def __getattr__(self, name): return getattr(self._conn, name)

def _raw_local():
    conn = sqlite3.connect(str(LOCAL_DB), timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def ensure_local_schema():
    with _LOCK:
        c = _raw_local()
        c.executescript('''
        CREATE TABLE IF NOT EXISTS branches(
          id INTEGER PRIMARY KEY, branch_name TEXT, branch_type TEXT, location TEXT, is_active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT, branch_id INTEGER, is_active INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS items(
          id INTEGER PRIMARY KEY, item_code TEXT, item_name TEXT, unit TEXT, quantity REAL DEFAULT 0,
          buy_price REAL DEFAULT 0, sale_price REAL DEFAULT 0, avg_cost REAL DEFAULT 0,
          branch_id INTEGER, expiry_date TEXT, pieces_per_carton REAL DEFAULT 1, image_path TEXT);
        CREATE TABLE IF NOT EXISTS customers(
          id INTEGER PRIMARY KEY, customer_name TEXT, phone TEXT, total_purchases REAL DEFAULT 0,
          balance REAL DEFAULT 0, marketing_consent INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS inventory_batches(
          id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL, branch_id INTEGER NOT NULL,
          quantity REAL DEFAULT 0, remaining_quantity REAL DEFAULT 0, received_date TEXT,
          expiry_date TEXT, unit_cost REAL DEFAULT 0, source_type TEXT DEFAULT 'inventory', created_at TEXT);
        CREATE TABLE IF NOT EXISTS invoices(
          id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, user_id INTEGER, customer_name TEXT,
          customer_phone TEXT, total_amount REAL DEFAULT 0, payment_method TEXT, notes TEXT,
          shift_status TEXT DEFAULT 'open', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          offline_uuid TEXT NOT NULL DEFAULT (lower(hex(randomblob(16)))), sync_status TEXT NOT NULL DEFAULT 'pending',
          remote_invoice_id INTEGER, sync_error TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS ux_invoices_offline_uuid ON invoices(offline_uuid);
        CREATE TABLE IF NOT EXISTS supplier_payments(
          id INTEGER PRIMARY KEY, supplier_id INTEGER, branch_id INTEGER, user_id INTEGER,
          amount REAL DEFAULT 0, shift_number INTEGER, notes TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS transfer_logs(
          id INTEGER PRIMARY KEY, from_branch_id INTEGER, to_branch_id INTEGER, items_details TEXT,
          transfer_date TEXT, status TEXT, created_by TEXT, received_by TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS local_meta(key TEXT PRIMARY KEY, value TEXT);
        ''')
        c.commit(); c.close()

def get_local_connection():
    ensure_local_schema()
    return LocalConnection(_raw_local())

def server_available():
    try:
        from database import get_db_connection
        c = get_db_connection(); c.execute('SELECT 1').fetchone(); c.close(); return True
    except Exception:
        return False

def _cols(rows):
    if not rows: return []
    r = rows[0]
    try: return list(r.keys())
    except Exception: return []

def _replace_table(local, table, rows, allowed):
    local.execute(f'DELETE FROM {table}')
    if not rows: return
    cols = [x for x in _cols(rows) if x in allowed]
    if not cols: return
    q = ','.join('?' for _ in cols)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({q})"
    vals = [tuple(r[x] for x in cols) for r in rows]
    local.executemany(sql, vals)

def sync_reference_data(remote=None):
    own = False
    if remote is None:
        from database import get_db_connection
        remote = get_db_connection(); own = True
    local = get_local_connection()
    try:
        branches = remote.execute('SELECT * FROM branches').fetchall()
        users = remote.execute('SELECT id, username, password, role, branch_id, is_active FROM users').fetchall()
        items = remote.execute('SELECT * FROM items').fetchall()
        customers = remote.execute('SELECT * FROM customers').fetchall()
        batches = remote.execute('SELECT * FROM inventory_batches').fetchall()
        _replace_table(local,'branches',branches,{'id','branch_name','branch_type','location','is_active'})
        _replace_table(local,'users',users,{'id','username','password','role','branch_id','is_active'})
        _replace_table(local,'items',items,{'id','item_code','item_name','unit','quantity','buy_price','sale_price','avg_cost','branch_id','expiry_date','pieces_per_carton','image_path'})
        _replace_table(local,'customers',customers,{'id','customer_name','phone','total_purchases','balance','marketing_consent'})
        _replace_table(local,'inventory_batches',batches,{'id','item_id','branch_id','quantity','remaining_quantity','received_date','expiry_date','unit_cost','source_type','created_at'})
        local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('last_download',?)",(datetime.now().isoformat(timespec='seconds'),))
        local.commit()
        return True, None
    except Exception as e:
        local.rollback(); return False, str(e)
    finally:
        local.close()
        if own:
            try: remote.close()
            except Exception: pass

def offline_login(username, password):
    c = get_local_connection()
    try:
        return c.execute('SELECT * FROM users WHERE username=? AND password=? AND is_active=1 LIMIT 1',(username.strip(),password)).fetchone()
    finally: c.close()

def _ensure_remote_sync_schema(remote):
    remote.execute('''CREATE TABLE IF NOT EXISTS offline_sync_receipts(
        offline_uuid TEXT PRIMARY KEY, remote_invoice_id INTEGER, device_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    remote.commit()

def _remote_deduct_fefo(remote, item_id, branch_id, qty):
    remaining = float(qty)
    rows = remote.execute('''SELECT id, remaining_quantity FROM inventory_batches
        WHERE item_id=? AND branch_id=? AND COALESCE(remaining_quantity,0)>0
          AND (expiry_date IS NULL OR expiry_date >= CURRENT_DATE)
        ORDER BY expiry_date ASC NULLS LAST, id ASC FOR UPDATE''',(item_id,branch_id)).fetchall()
    for r in rows:
        if remaining <= 0: break
        take = min(remaining, float(r['remaining_quantity'] or 0))
        remote.execute('UPDATE inventory_batches SET remaining_quantity=remaining_quantity-? WHERE id=?',(take,r['id']))
        remaining -= take

def sync_pending_sales(remote=None):
    own=False
    if remote is None:
        from database import get_db_connection
        remote=get_db_connection(); own=True
    local=get_local_connection(); synced=0; failed=0
    try:
        _ensure_remote_sync_schema(remote)
        pending=local.execute("SELECT * FROM invoices WHERE sync_status='pending' ORDER BY id").fetchall()
        for inv in pending:
            try:
                seen=remote.execute('SELECT remote_invoice_id FROM offline_sync_receipts WHERE offline_uuid=?',(inv['offline_uuid'],)).fetchone()
                if seen:
                    local.execute("UPDATE invoices SET sync_status='synced', remote_invoice_id=?, sync_error=NULL WHERE id=?",(seen['remote_invoice_id'],inv['id']))
                    local.commit(); synced+=1; continue
                details=json.loads(inv['notes'] or '{}')
                items=details.get('items',[])
                for it in items:
                    if it.get('id') == 99999: continue
                    row=remote.execute('SELECT quantity FROM items WHERE id=? AND branch_id=? FOR UPDATE',(it['id'],inv['branch_id'])).fetchone()
                    if not row or float(row['quantity'] or 0) < float(it.get('qty') or 0):
                        raise ValueError(f"المخزون على السيرفر غير كافٍ للصنف {it.get('name','')}")
                phone=(inv['customer_phone'] or '').strip(); cname=(inv['customer_name'] or 'زبون نقدي').strip()
                if phone:
                    cust=remote.execute('SELECT id FROM customers WHERE phone=? LIMIT 1',(phone,)).fetchone()
                    if not cust:
                        cust=remote.execute('INSERT INTO customers(customer_name,phone,total_purchases,balance,marketing_consent) VALUES(?,?,0,0,FALSE) RETURNING id',(cname,phone)).fetchone()
                rr=remote.execute('''INSERT INTO invoices(branch_id,user_id,customer_name,customer_phone,total_amount,payment_method,notes,shift_status)
                    VALUES(?,?,?,?,?,?,?,?) RETURNING id''',(inv['branch_id'],inv['user_id'],cname,phone,inv['total_amount'],inv['payment_method'],inv['notes'],inv['shift_status'])).fetchone()
                rid=rr['id']
                for it in items:
                    if it.get('id') == 99999: continue
                    q=float(it.get('qty') or 0); _remote_deduct_fefo(remote,it['id'],inv['branch_id'],q)
                    remote.execute('UPDATE items SET quantity=quantity-? WHERE id=? AND branch_id=?',(q,it['id'],inv['branch_id']))
                if inv['payment_method']=='آجل (على الحساب)' and phone:
                    remote.execute('UPDATE customers SET balance=COALESCE(balance,0)+?, total_purchases=COALESCE(total_purchases,0)+? WHERE phone=?',(inv['total_amount'],inv['total_amount'],phone))
                remote.execute('INSERT INTO offline_sync_receipts(offline_uuid,remote_invoice_id) VALUES(?,?)',(inv['offline_uuid'],rid))
                remote.commit()
                local.execute("UPDATE invoices SET sync_status='synced', remote_invoice_id=?, sync_error=NULL WHERE id=?",(rid,inv['id'])); local.commit(); synced+=1
            except Exception as e:
                try: remote.rollback()
                except Exception: pass
                local.execute("UPDATE invoices SET sync_error=? WHERE id=?",(str(e),inv['id'])); local.commit(); failed+=1
        return synced, failed
    finally:
        local.close()
        if own:
            try: remote.close()
            except Exception: pass

def sync_now():
    from database import get_db_connection
    remote=get_db_connection()
    try:
        synced,failed=sync_pending_sales(remote)
        ok,err=sync_reference_data(remote)
        return {'synced':synced,'failed':failed,'download_ok':ok,'error':err}
    finally: remote.close()

def get_pos_connection():
    try:
        from database import get_db_connection
        remote=get_db_connection(); remote.execute('SELECT 1').fetchone()
        try: sync_pending_sales(remote); sync_reference_data(remote)
        except Exception: pass
        return remote, 'online'
    except Exception:
        return get_local_connection(), 'offline'

def pending_count():
    c=get_local_connection()
    try: return int(c.execute("SELECT COUNT(*) FROM invoices WHERE sync_status='pending'").fetchone()[0])
    finally: c.close()
