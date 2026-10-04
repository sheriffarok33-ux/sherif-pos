import json
import sqlite3
import threading
import uuid
import socket
from pathlib import Path
from datetime import datetime, date, time
from decimal import Decimal

LOCAL_DB = Path(__file__).with_name('abu_zaid_local.db')
_LOCK = threading.RLock()

class LocalConnection:
    """SQLite connection that records each committed local transaction as one sync unit."""
    def __init__(self, conn, queue_writes=False):
        self._conn = conn
        self._queue_writes = queue_writes
        self._tx_uuid = str(uuid.uuid4())
        self._tx_seq = 0
        try:
            row = self._conn.execute("SELECT value FROM local_meta WHERE key='device_id'").fetchone()
            if row and row[0]:
                self._device_id = str(row[0])
            else:
                self._device_id = str(uuid.uuid4())
                self._conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_id',?)", (self._device_id,))
                self._conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_name',?)", (socket.gethostname(),))
                self._conn.commit()
        except Exception:
            self._device_id = str(uuid.uuid4())

    def _record(self, sql, params):
        low = sql.lower(); head = sql.lstrip().upper()
        if not self._queue_writes or not head.startswith(("INSERT ", "UPDATE ", "DELETE ", "REPLACE ")):
            return
        # POS invoices use the dedicated invoice synchronizer. Internal sync metadata never leaves the device.
        if any(x in low for x in ("sync_queue", "local_meta", "offline_sync_receipts", "into invoices", "update invoices", "delete from invoices")):
            return
        self._tx_seq += 1
        self._conn.execute(
            "INSERT INTO sync_queue(operation_uuid,transaction_uuid,device_id,sequence_no,sql_text,params_json) VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), self._tx_uuid, self._device_id, self._tx_seq, sql, json.dumps(list(params or ()), ensure_ascii=False, default=str))
        )

    def execute(self, sql, params=()):
        clean = sql.replace("FOR UPDATE", "")
        cur = self._conn.execute(clean, params or ())
        self._record(clean, params)
        return cur

    def executemany(self, sql, seq):
        clean = sql.replace("FOR UPDATE", "")
        rows = list(seq)
        cur = self._conn.executemany(clean, rows)
        for params in rows:
            self._record(clean, params)
        return cur

    def commit(self):
        result = self._conn.commit()
        self._tx_uuid = str(uuid.uuid4()); self._tx_seq = 0
        return result

    def rollback(self):
        result = self._conn.rollback()
        self._tx_uuid = str(uuid.uuid4()); self._tx_seq = 0
        return result

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
        CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY, supplier_name TEXT, phone TEXT, balance REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY, branch_id INTEGER, supplier_id INTEGER, supplier_name TEXT, invoice_number TEXT, total_cost REAL DEFAULT 0, payment_type TEXT, items_details TEXT, invoice_date TEXT);
        CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY, branch_id INTEGER, amount REAL DEFAULT 0, description TEXT, is_general_store INTEGER DEFAULT 0, expense_date TEXT);
        CREATE TABLE IF NOT EXISTS revenues(id INTEGER PRIMARY KEY, branch_id INTEGER, revenue_source TEXT, amount REAL DEFAULT 0, notes TEXT, description TEXT, revenue_date TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS stock_adjustments(id INTEGER PRIMARY KEY, branch_id INTEGER, item_id INTEGER, item_name TEXT, quantity REAL, adjustment_type TEXT, loss_or_gain_value REAL DEFAULT 0, notes TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS negative_sales_logs(id INTEGER PRIMARY KEY, branch_id INTEGER, user_id INTEGER, item_name TEXT, sale_qty REAL, log_time TEXT);
        CREATE TABLE IF NOT EXISTS production_logs(id INTEGER PRIMARY KEY, branch_id INTEGER, operation_type TEXT, source_details TEXT, target_item_id INTEGER, target_item_name TEXT, input_weight REAL DEFAULT 0, output_weight REAL DEFAULT 0, loss_weight REAL DEFAULT 0, total_cost REAL DEFAULT 0, unit_cost REAL DEFAULT 0, notes TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY, employee_name TEXT, phone TEXT, branch_id INTEGER, salary REAL DEFAULT 0, is_active INTEGER DEFAULT 1, created_at TEXT);
        CREATE TABLE IF NOT EXISTS employee_financial_transactions(id INTEGER PRIMARY KEY, employee_id INTEGER, branch_id INTEGER, transaction_type TEXT, amount REAL DEFAULT 0, notes TEXT, transaction_date TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS role_permissions(id INTEGER PRIMARY KEY, role_name TEXT, page_name TEXT, can_access INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS custom_labels(id INTEGER PRIMARY KEY, label_key TEXT, label_value TEXT);
        CREATE TABLE IF NOT EXISTS activity_logs(id INTEGER PRIMARY KEY, user_id INTEGER, branch_id INTEGER, action_type TEXT, details TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS app_settings(setting_key TEXT PRIMARY KEY, setting_value TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS local_meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS sync_queue(id INTEGER PRIMARY KEY AUTOINCREMENT, operation_uuid TEXT NOT NULL UNIQUE, transaction_uuid TEXT, device_id TEXT, sequence_no INTEGER DEFAULT 0, sql_text TEXT NOT NULL, params_json TEXT NOT NULL DEFAULT '[]', created_at TEXT DEFAULT CURRENT_TIMESTAMP, sync_status TEXT NOT NULL DEFAULT 'pending', sync_error TEXT);
        CREATE INDEX IF NOT EXISTS ix_sync_queue_status ON sync_queue(sync_status,id);
        ''')
        # Lightweight migrations for the full desktop/local application.
        migrations = [
          ('branches','location','TEXT'), ('users','phone','TEXT'), ('users','allowed_branches',"TEXT DEFAULT 'ALL'"), ('users','custom_permissions',"TEXT DEFAULT ''"),
          ('items','unit_type',"TEXT DEFAULT 'piece'"), ('items','no_expiry','INTEGER DEFAULT 0'), ('items','favorite_rank','INTEGER DEFAULT 0')
        ]
        for table, col, typ in migrations:
            try: c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {typ}')
            except Exception: pass
        for col, typ in [('transaction_uuid','TEXT'), ('device_id','TEXT'), ('sequence_no','INTEGER DEFAULT 0')]:
            try: c.execute(f'ALTER TABLE sync_queue ADD COLUMN {col} {typ}')
            except Exception: pass
        # Old queued rows become one-operation transactions.
        try:
            rows=c.execute("SELECT id,operation_uuid FROM sync_queue WHERE transaction_uuid IS NULL OR transaction_uuid='' ").fetchall()
            for r in rows: c.execute("UPDATE sync_queue SET transaction_uuid=?,sequence_no=COALESCE(sequence_no,0) WHERE id=?",(r['operation_uuid'],r['id']))
        except Exception: pass
        try:
            row=c.execute("SELECT value FROM local_meta WHERE key='device_id'").fetchone()
            did=str(row[0]) if row and row[0] else str(uuid.uuid4())
            c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_id',?)",(did,))
            c.execute("UPDATE sync_queue SET device_id=? WHERE device_id IS NULL OR device_id=''",(did,))
        except Exception: pass
        c.commit(); c.close()

def get_device_id():
    """Return a stable UUID for this Windows/device installation."""
    ensure_local_schema()
    c = _raw_local()
    try:
        row = c.execute("SELECT value FROM local_meta WHERE key='device_id'").fetchone()
        if row and row[0]:
            return str(row[0])
        device_id = str(uuid.uuid4())
        c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_id',?)", (device_id,))
        c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_name',?)", (socket.gethostname(),))
        c.commit()
        return device_id
    finally:
        c.close()

def get_local_connection(queue_writes=False):
    ensure_local_schema()
    return LocalConnection(_raw_local(), queue_writes=queue_writes)

def server_available():
    try:
        from database import get_remote_connection
        c = get_remote_connection(); c.execute('SELECT 1').fetchone(); c.close(); return True
    except Exception:
        return False

def _cols(rows):
    if not rows: return []
    r = rows[0]
    try: return list(r.keys())
    except Exception: return []

def _sqlite_value(value):
    """Convert PostgreSQL values to types SQLite can bind safely."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, memoryview):
        return bytes(value)
    return value

def _replace_table(local, table, rows, allowed):
    # Prepare/convert everything BEFORE deleting the existing local table.
    # This prevents a PostgreSQL Decimal (or another unsupported value)
    # from leaving the local reference table empty.
    if not rows:
        return
    cols = [x for x in _cols(rows) if x in allowed]
    if not cols:
        return
    q = ','.join('?' for _ in cols)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({q})"
    vals = [tuple(_sqlite_value(r[x]) for x in cols) for r in rows]

    savepoint = f"sync_replace_{table}"
    local.execute(f"SAVEPOINT {savepoint}")
    try:
        local.execute(f'DELETE FROM {table}')
        local.executemany(sql, vals)
        local.execute(f"RELEASE SAVEPOINT {savepoint}")
    except Exception:
        local.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        local.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise

def _merge_table(local, table, rows, allowed):
    """Merge server history into local SQLite without deleting local-only rows."""
    if not rows:
        return
    cols = [x for x in _cols(rows) if x in allowed]
    if not cols:
        return
    q = ','.join('?' for _ in cols)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({q})"
    vals = [tuple(_sqlite_value(r[x]) for x in cols) for r in rows]
    local.executemany(sql, vals)


def sync_reference_data(remote=None):
    own = False
    if remote is None:
        from database import get_remote_connection
        remote = get_remote_connection(); own = True
    local = get_local_connection()
    try:
        branches = remote.execute('SELECT * FROM branches').fetchall()
        users = remote.execute('SELECT id, username, password, role, branch_id, is_active FROM users').fetchall()
        items = remote.execute('SELECT * FROM items').fetchall()
        customers = remote.execute('SELECT * FROM customers').fetchall()
        batches = remote.execute('SELECT * FROM inventory_batches').fetchall()
        try:
            settings = remote.execute('SELECT setting_key, setting_value, updated_at FROM app_settings').fetchall()
        except Exception:
            settings = []
        _replace_table(local,'branches',branches,{'id','branch_name','branch_type','location','is_active'})
        _replace_table(local,'users',users,{'id','username','password','role','branch_id','is_active'})
        _replace_table(local,'items',items,{'id','item_code','item_name','unit','quantity','buy_price','sale_price','avg_cost','branch_id','expiry_date','pieces_per_carton','image_path'})
        _replace_table(local,'customers',customers,{'id','customer_name','phone','total_purchases','balance','marketing_consent'})
        _replace_table(local,'inventory_batches',batches,{'id','item_id','branch_id','quantity','remaining_quantity','received_date','expiry_date','unit_cost','source_type','created_at'})
        _replace_table(local,'app_settings',settings,{'setting_key','setting_value','updated_at'})
        # Download the rest of the ERP reference/history tables once at login.
        extra_tables = {
          'suppliers': {'id','supplier_name','phone','balance'},
          'purchases': {'id','branch_id','supplier_id','supplier_name','invoice_number','total_cost','payment_type','items_details','invoice_date'},
          'expenses': {'id','branch_id','amount','description','is_general_store','expense_date'},
          'revenues': {'id','branch_id','revenue_source','amount','notes','description','revenue_date','created_at'},
          'stock_adjustments': {'id','branch_id','item_id','item_name','quantity','adjustment_type','loss_or_gain_value','notes','created_at'},
          'negative_sales_logs': {'id','branch_id','user_id','item_name','sale_qty','log_time'},
          'production_logs': {'id','branch_id','operation_type','source_details','target_item_id','target_item_name','input_weight','output_weight','loss_weight','total_cost','unit_cost','notes','created_at'},
          'employees': {'id','employee_name','phone','branch_id','salary','is_active','created_at'},
          'employee_financial_transactions': {'id','employee_id','branch_id','transaction_type','amount','notes','transaction_date','created_at'},
          'role_permissions': {'id','role_name','page_name','can_access'},
          'custom_labels': {'id','label_key','label_value'},
          'activity_logs': {'id','user_id','branch_id','action_type','details','created_at'},
        }
        for table, allowed in extra_tables.items():
            try:
                rows = remote.execute(f'SELECT * FROM {table}').fetchall()
                _replace_table(local, table, rows, allowed)
            except Exception:
                pass

        # سجل التحويلات تاريخ تشغيلي وليس بيانات مرجعية:
        # لا نحذفه محلياً عند تسجيل الدخول. ننزل الموجود على السيرفر ونقوم بدمجه فقط.
        # بهذا تبقى فاتورة التزويد ظاهرة بعد الخروج/الدخول أو إعادة تشغيل التطبيق.
        try:
            transfer_rows = remote.execute('SELECT * FROM transfer_logs').fetchall()
            _merge_table(
                local,
                'transfer_logs',
                transfer_rows,
                {
                    'id', 'from_branch_id', 'to_branch_id', 'items_details',
                    'transfer_date', 'status', 'created_by', 'received_by',
                    'created_at'
                }
            )
        except Exception:
            # فشل تنزيل السجل لا يمسح السجل المحلي الموجود.
            pass
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
        from database import get_remote_connection
        remote=get_remote_connection(); own=True
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

def _ensure_remote_operation_receipts(remote):
    remote.execute("CREATE TABLE IF NOT EXISTS offline_operation_receipts(transaction_uuid TEXT PRIMARY KEY, device_id TEXT, device_synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    try:
        remote.execute("ALTER TABLE offline_operation_receipts ADD COLUMN IF NOT EXISTS device_id TEXT")
    except Exception:
        pass
    remote.commit()

def sync_pending_operations(remote=None):
    """Replay each local COMMIT as one atomic PostgreSQL transaction.
    A failed statement rolls back the whole group, preventing half-synced purchases/transfers/production operations.
    """
    own=False
    if remote is None:
        from database import get_remote_connection
        remote=get_remote_connection(); own=True
    local=get_local_connection(queue_writes=False); synced=failed=0
    try:
        _ensure_remote_operation_receipts(remote)
        txs=local.execute("SELECT transaction_uuid, MIN(id) first_id FROM sync_queue WHERE sync_status='pending' GROUP BY transaction_uuid ORDER BY first_id").fetchall()
        for tx in txs:
            txid=tx['transaction_uuid']
            rows=local.execute("SELECT * FROM sync_queue WHERE sync_status='pending' AND transaction_uuid=? ORDER BY sequence_no,id",(txid,)).fetchall()
            try:
                seen=remote.execute("SELECT transaction_uuid FROM offline_operation_receipts WHERE transaction_uuid=?",(txid,)).fetchone()
                if not seen:
                    for row in rows:
                        remote.execute(row['sql_text'],tuple(json.loads(row['params_json'] or '[]')))
                    device_id = rows[0]['device_id'] if rows and 'device_id' in rows[0].keys() else None
                    remote.execute("INSERT INTO offline_operation_receipts(transaction_uuid,device_id) VALUES(?,?)",(txid,device_id))
                    remote.commit()
                ids=[r['id'] for r in rows]
                for rid in ids:
                    local.execute("UPDATE sync_queue SET sync_status='synced',sync_error=NULL WHERE id=?",(rid,))
                local.commit(); synced += len(rows)
            except Exception as e:
                try: remote.rollback()
                except Exception: pass
                for row in rows:
                    local.execute("UPDATE sync_queue SET sync_error=? WHERE id=?",(str(e),row['id']))
                local.commit(); failed += len(rows)
        return synced,failed
    finally:
        local.close()
        if own:
            try: remote.close()
            except Exception: pass

def pending_operations_count():
    c=get_local_connection(queue_writes=False)
    try: return int(c.execute("SELECT COUNT(*) FROM sync_queue WHERE sync_status='pending'").fetchone()[0])
    finally: c.close()

def sync_now():
    from database import get_remote_connection
    remote=get_remote_connection()
    try:
        synced,failed=sync_pending_sales(remote)
        ops_synced,ops_failed=sync_pending_operations(remote)
        ok,err=sync_reference_data(remote)
        return {'synced':synced,'failed':failed,'ops_synced':ops_synced,'ops_failed':ops_failed,'download_ok':ok,'error':err}
    finally: remote.close()

def get_pos_connection():
    """
    Local-first POS connection.
    Synchronization is intentionally NOT performed here.
    It is performed once after each successful online login in main.py.
    """
    return get_local_connection(), 'offline'

def pending_count():
    c=get_local_connection()
    try: return int(c.execute("SELECT COUNT(*) FROM invoices WHERE sync_status='pending'").fetchone()[0])
    finally: c.close()
