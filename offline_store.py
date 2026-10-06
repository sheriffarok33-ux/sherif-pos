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
          branch_id INTEGER, expiry_date TEXT, pieces_per_carton REAL DEFAULT 1, image_path TEXT, scale_code TEXT);
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
        CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY, branch_id INTEGER, supplier_id INTEGER, supplier_name TEXT, invoice_number TEXT, document_number TEXT, total_cost REAL DEFAULT 0, payment_type TEXT, items_details TEXT, invoice_date TEXT);
        CREATE TABLE IF NOT EXISTS purchase_items(id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER NOT NULL, item_id INTEGER, item_code TEXT, item_name TEXT NOT NULL, quantity REAL DEFAULT 0, unit TEXT, unit_price REAL DEFAULT 0, line_total REAL DEFAULT 0, expiry_date TEXT);
        CREATE INDEX IF NOT EXISTS idx_purchase_items_purchase ON purchase_items(purchase_id);
        CREATE TABLE IF NOT EXISTS document_registry(id INTEGER PRIMARY KEY AUTOINCREMENT, document_number TEXT NOT NULL UNIQUE, document_type TEXT NOT NULL, source_table TEXT, source_id INTEGER, external_number TEXT, branch_id INTEGER, party_name TEXT, amount REAL DEFAULT 0, document_date TEXT, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS idx_document_registry_type_date ON document_registry(document_type,document_date);
        CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY, branch_id INTEGER, amount REAL DEFAULT 0, description TEXT, is_general_store INTEGER DEFAULT 0, expense_date TEXT);
        CREATE TABLE IF NOT EXISTS revenues(id INTEGER PRIMARY KEY, branch_id INTEGER, revenue_source TEXT, amount REAL DEFAULT 0, notes TEXT, description TEXT, revenue_date TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS stock_adjustments(id INTEGER PRIMARY KEY, branch_id INTEGER, item_id INTEGER, item_name TEXT, quantity REAL, adjustment_type TEXT, loss_or_gain_value REAL DEFAULT 0, notes TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS negative_sales_logs(id INTEGER PRIMARY KEY, branch_id INTEGER, user_id INTEGER, item_name TEXT, sale_qty REAL, log_time TEXT);
        CREATE TABLE IF NOT EXISTS production_logs(id INTEGER PRIMARY KEY, branch_id INTEGER, operation_type TEXT, production_type TEXT, source_details TEXT, source_item_id INTEGER, source_item_name TEXT, target_item_id INTEGER, target_item_name TEXT, input_weight REAL DEFAULT 0, output_weight REAL DEFAULT 0, loss_weight REAL DEFAULT 0, input_quantity REAL DEFAULT 0, output_quantity REAL DEFAULT 0, loss_quantity REAL DEFAULT 0, total_cost REAL DEFAULT 0, unit_cost REAL DEFAULT 0, sale_price REAL DEFAULT 0, notes TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY, user_id INTEGER, full_name TEXT, employee_name TEXT, phone TEXT, address TEXT, emergency_name TEXT, emergency_phone TEXT, emergency_relation TEXT, branch_id INTEGER, monthly_salary REAL DEFAULT 0, salary REAL DEFAULT 0, hire_date TEXT, termination_date TEXT, employment_status TEXT DEFAULT 'active', is_active INTEGER DEFAULT 1, notes TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS employee_financial_transactions(id INTEGER PRIMARY KEY, employee_id INTEGER, branch_id INTEGER, transaction_type TEXT, amount REAL DEFAULT 0, payroll_year INTEGER, payroll_month INTEGER, work_days INTEGER, month_days INTEGER, base_salary REAL DEFAULT 0, notes TEXT, expense_id INTEGER, created_by INTEGER, transaction_date TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS role_permissions(id INTEGER PRIMARY KEY, role_name TEXT, page_name TEXT, can_access INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS custom_labels(id INTEGER PRIMARY KEY, label_key TEXT, label_value TEXT);
        CREATE TABLE IF NOT EXISTS activity_logs(id INTEGER PRIMARY KEY, user_id INTEGER, branch_id INTEGER, action_type TEXT, details TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS app_settings(setting_key TEXT PRIMARY KEY, setting_value TEXT, updated_at TEXT);

        CREATE TABLE IF NOT EXISTS financial_vouchers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_no TEXT UNIQUE NOT NULL,
            voucher_type TEXT NOT NULL,
            party_type TEXT NOT NULL,
            party_id INTEGER,
            party_name TEXT NOT NULL,
            branch_id INTEGER,
            user_id INTEGER,
            amount REAL NOT NULL DEFAULT 0,
            notes TEXT,
            treasury_id INTEGER,
            treasury_name TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS treasuries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            treasury_name TEXT NOT NULL UNIQUE,
            treasury_type TEXT NOT NULL DEFAULT 'branch',
            branch_id INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS treasury_movements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            treasury_id INTEGER NOT NULL,
            movement_type TEXT NOT NULL,
            amount REAL NOT NULL,
            voucher_no TEXT,
            description TEXT,
            user_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_financial_vouchers_type_date
            ON financial_vouchers(voucher_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_treasury_movements_treasury_date
            ON treasury_movements(treasury_id, created_at);
        CREATE TABLE IF NOT EXISTS shift_closures(
            id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER NOT NULL, shift_date TEXT NOT NULL,
            shift_number INTEGER NOT NULL, gross_sales REAL DEFAULT 0, net_sales REAL DEFAULT 0,
            cash_amount REAL DEFAULT 0, card_amount REAL DEFAULT 0, transfer_amount REAL DEFAULT 0,
            credit_amount REAL DEFAULT 0, other_amount REAL DEFAULT 0, status TEXT DEFAULT 'closed',
            closed_by INTEGER, closed_at TEXT DEFAULT CURRENT_TIMESTAMP, notes TEXT,
            UNIQUE(branch_id, shift_date, shift_number));
        CREATE TABLE IF NOT EXISTS shift_settlement_adjustments(
            id INTEGER PRIMARY KEY AUTOINCREMENT, closure_id INTEGER, branch_id INTEGER NOT NULL,
            shift_date TEXT NOT NULL, shift_number INTEGER, cash_amount REAL DEFAULT 0, card_amount REAL DEFAULT 0,
            transfer_amount REAL DEFAULT 0, credit_amount REAL DEFAULT 0, other_amount REAL DEFAULT 0,
            reason TEXT, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);

        CREATE TABLE IF NOT EXISTS local_meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS sync_queue(id INTEGER PRIMARY KEY AUTOINCREMENT, operation_uuid TEXT NOT NULL UNIQUE, transaction_uuid TEXT, device_id TEXT, sequence_no INTEGER DEFAULT 0, sql_text TEXT NOT NULL, params_json TEXT NOT NULL DEFAULT '[]', created_at TEXT DEFAULT CURRENT_TIMESTAMP, sync_status TEXT NOT NULL DEFAULT 'pending', sync_error TEXT);
        CREATE INDEX IF NOT EXISTS ix_sync_queue_status ON sync_queue(sync_status,id);
        ''')
        # Lightweight migrations for the full desktop/local application.
        migrations = [
          ('branches','location','TEXT'), ('users','phone','TEXT'), ('users','allowed_branches',"TEXT DEFAULT 'ALL'"), ('users','custom_permissions',"TEXT DEFAULT ''"),
          ('purchases','document_number','TEXT'),
          ('items','unit_type',"TEXT DEFAULT 'piece'"), ('items','no_expiry','INTEGER DEFAULT 0'), ('items','favorite_rank','INTEGER DEFAULT 0'), ('items','scale_code','TEXT'),
          ('production_logs','production_type','TEXT'),
          ('production_logs','source_item_id','INTEGER'),
          ('production_logs','source_item_name','TEXT'),
          ('production_logs','input_quantity','REAL DEFAULT 0'),
          ('production_logs','output_quantity','REAL DEFAULT 0'),
          ('production_logs','loss_quantity','REAL DEFAULT 0'),
          ('production_logs','sale_price','REAL DEFAULT 0'),
          ('employees','user_id','INTEGER'),
          ('employees','full_name','TEXT'),
          ('employees','address','TEXT'),
          ('employees','emergency_name','TEXT'),
          ('employees','emergency_phone','TEXT'),
          ('employees','emergency_relation','TEXT'),
          ('employees','monthly_salary','REAL DEFAULT 0'),
          ('treasury_movements','branch_id','INTEGER'),
          ('treasury_movements','payment_method','TEXT'),
          ('treasury_movements','movement_date','TEXT'),
          ('treasury_movements','source_type','TEXT'),
          ('treasury_movements','source_ref','TEXT'),
          ('employees','hire_date','TEXT'),
          ('employees','termination_date','TEXT'),
          ('employees','employment_status',"TEXT DEFAULT 'active'"),
          ('employees','notes','TEXT'),
          ('employees','updated_at','TEXT'),
          ('employee_financial_transactions','payroll_year','INTEGER'),
          ('employee_financial_transactions','payroll_month','INTEGER'),
          ('employee_financial_transactions','work_days','INTEGER'),
          ('employee_financial_transactions','month_days','INTEGER'),
          ('employee_financial_transactions','base_salary','REAL DEFAULT 0'),
          ('employee_financial_transactions','expense_id','INTEGER'),
          ('employee_financial_transactions','created_by','INTEGER')
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
        try:
            c.execute("INSERT OR IGNORE INTO treasuries(treasury_name,treasury_type,branch_id) VALUES('خزينة الشركة','company',NULL)")
            for b in c.execute("SELECT id, branch_name FROM branches").fetchall():
                c.execute("INSERT OR IGNORE INTO treasuries(treasury_name,treasury_type,branch_id) VALUES(?, 'branch', ?)", (f"خزينة فرع {b['branch_name']}", b['id']))
        except Exception:
            pass
        for col, typ in [('treasury_id','INTEGER'), ('treasury_name','TEXT')]:
            try: c.execute(f'ALTER TABLE financial_vouchers ADD COLUMN {col} {typ}')
            except Exception: pass
        # Upgrade legacy HR rows without deleting old employee data.
        try:
            c.execute("UPDATE employees SET full_name=employee_name WHERE (full_name IS NULL OR TRIM(full_name)='') AND employee_name IS NOT NULL")
            c.execute("UPDATE employees SET monthly_salary=salary WHERE COALESCE(monthly_salary,0)=0 AND COALESCE(salary,0)<>0")
            c.execute("UPDATE employees SET employment_status=CASE WHEN COALESCE(is_active,1)=1 THEN 'active' ELSE 'terminated' END WHERE employment_status IS NULL OR employment_status=''")
            c.execute("UPDATE employees SET hire_date=COALESCE(hire_date, substr(created_at,1,10), date('now')) WHERE hire_date IS NULL OR hire_date=''")
        except Exception:
            pass
        # Keep historical production rows readable by the current production report.
        try:
            c.execute("UPDATE production_logs SET production_type=operation_type WHERE (production_type IS NULL OR production_type='') AND operation_type IS NOT NULL")
            c.execute("UPDATE production_logs SET input_quantity=input_weight WHERE COALESCE(input_quantity,0)=0 AND COALESCE(input_weight,0)<>0")
            c.execute("UPDATE production_logs SET output_quantity=output_weight WHERE COALESCE(output_quantity,0)=0 AND COALESCE(output_weight,0)<>0")
            c.execute("UPDATE production_logs SET loss_quantity=loss_weight WHERE COALESCE(loss_quantity,0)=0 AND COALESCE(loss_weight,0)<>0")
        except Exception:
            pass
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
        _replace_table(local,'items',items,{'id','item_code','item_name','unit','quantity','buy_price','sale_price','avg_cost','branch_id','expiry_date','pieces_per_carton','image_path','scale_code'})
        _replace_table(local,'customers',customers,{'id','customer_name','phone','total_purchases','balance','marketing_consent'})
        _replace_table(local,'inventory_batches',batches,{'id','item_id','branch_id','quantity','remaining_quantity','received_date','expiry_date','unit_cost','source_type','created_at'})
        _replace_table(local,'app_settings',settings,{'setting_key','setting_value','updated_at'})
        # Download the rest of the ERP reference/history tables once at login.
        extra_tables = {
          'suppliers': {'id','supplier_name','phone','balance'},
          'purchases': {'id','branch_id','supplier_id','supplier_name','invoice_number','document_number','total_cost','payment_type','items_details','invoice_date'},
          'purchase_items': {'id','purchase_id','item_id','item_code','item_name','quantity','unit','unit_price','line_total','expiry_date'},
          'document_registry': {'id','document_number','document_type','source_table','source_id','external_number','branch_id','party_name','amount','document_date','created_by','created_at'},
          'expenses': {'id','branch_id','amount','description','is_general_store','expense_date'},
          'revenues': {'id','branch_id','revenue_source','amount','notes','description','revenue_date','created_at'},
          'stock_adjustments': {'id','branch_id','item_id','item_name','quantity','adjustment_type','loss_or_gain_value','notes','created_at'},
          'negative_sales_logs': {'id','branch_id','user_id','item_name','sale_qty','log_time'},
          'production_logs': {'id','branch_id','operation_type','production_type','source_details','source_item_id','source_item_name','target_item_id','target_item_name','input_weight','output_weight','loss_weight','input_quantity','output_quantity','loss_quantity','total_cost','unit_cost','sale_price','notes','created_at'},
          'employees': {'id','user_id','full_name','employee_name','phone','address','emergency_name','emergency_phone','emergency_relation','branch_id','monthly_salary','salary','hire_date','termination_date','employment_status','is_active','notes','created_at','updated_at'},
          'employee_financial_transactions': {'id','employee_id','branch_id','transaction_type','amount','payroll_year','payroll_month','work_days','month_days','base_salary','notes','expense_id','created_by','transaction_date','created_at'},
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


def _ensure_remote_finance_schema(remote):
    """Create/upgrade central schema needed by locally queued operations."""
    # Item master upgrades used by inventory editor / scale barcode.
    # Must exist centrally BEFORE replaying queued UPDATE items statements, otherwise
    # a successful local edit would fail to upload and the next reference download
    # would restore the old server value.
    try:
        remote.execute("ALTER TABLE items ADD COLUMN IF NOT EXISTS scale_code TEXT")
    except Exception:
        pass
    try:
        remote.execute("ALTER TABLE purchases ADD COLUMN IF NOT EXISTS document_number TEXT")
    except Exception:
        pass
    remote.execute("""
        CREATE TABLE IF NOT EXISTS treasuries(
            id BIGSERIAL PRIMARY KEY,
            treasury_name TEXT NOT NULL UNIQUE,
            treasury_type TEXT NOT NULL DEFAULT 'branch',
            branch_id BIGINT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    remote.execute("""
        CREATE TABLE IF NOT EXISTS financial_vouchers(
            id BIGSERIAL PRIMARY KEY,
            voucher_no TEXT NOT NULL UNIQUE,
            voucher_type TEXT NOT NULL,
            party_type TEXT NOT NULL,
            party_id BIGINT,
            party_name TEXT NOT NULL,
            branch_id BIGINT,
            user_id BIGINT,
            amount DOUBLE PRECISION NOT NULL DEFAULT 0,
            notes TEXT,
            treasury_id BIGINT,
            treasury_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    remote.execute("""
        CREATE TABLE IF NOT EXISTS treasury_movements(
            id BIGSERIAL PRIMARY KEY, treasury_id BIGINT NOT NULL, movement_type TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL, voucher_no TEXT, description TEXT, user_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, branch_id BIGINT, payment_method TEXT,
            movement_date TEXT, source_type TEXT, source_ref TEXT
        )
    """)
    for col, typ in [("branch_id","BIGINT"),("payment_method","TEXT"),("movement_date","TEXT"),("source_type","TEXT"),("source_ref","TEXT")]:
        try: remote.execute(f"ALTER TABLE treasury_movements ADD COLUMN IF NOT EXISTS {col} {typ}")
        except Exception: pass
    remote.execute("""CREATE TABLE IF NOT EXISTS shift_closures(
        id BIGSERIAL PRIMARY KEY, branch_id BIGINT NOT NULL, shift_date TEXT NOT NULL, shift_number INTEGER NOT NULL,
        gross_sales DOUBLE PRECISION DEFAULT 0, net_sales DOUBLE PRECISION DEFAULT 0, cash_amount DOUBLE PRECISION DEFAULT 0,
        card_amount DOUBLE PRECISION DEFAULT 0, transfer_amount DOUBLE PRECISION DEFAULT 0, credit_amount DOUBLE PRECISION DEFAULT 0,
        other_amount DOUBLE PRECISION DEFAULT 0, status TEXT DEFAULT 'closed', closed_by BIGINT, closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        notes TEXT, UNIQUE(branch_id,shift_date,shift_number))""")
    remote.execute("""CREATE TABLE IF NOT EXISTS shift_settlement_adjustments(
        id BIGSERIAL PRIMARY KEY, closure_id BIGINT, branch_id BIGINT NOT NULL, shift_date TEXT NOT NULL, shift_number INTEGER,
        cash_amount DOUBLE PRECISION DEFAULT 0, card_amount DOUBLE PRECISION DEFAULT 0, transfer_amount DOUBLE PRECISION DEFAULT 0,
        credit_amount DOUBLE PRECISION DEFAULT 0, other_amount DOUBLE PRECISION DEFAULT 0, reason TEXT, created_by BIGINT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    remote.commit()

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
        _ensure_remote_finance_schema(remote)
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


def sync_after_login(remote=None):
    """
    Login synchronization.
    Upload local pending work first, then refresh reference data (especially branches)
    so every screen sees the main warehouse without requiring the POS sync button.
    """
    from database import get_remote_connection
    own = remote is None
    r = remote or get_remote_connection()
    upload_errors = []
    sales_result = (0, 0)
    ops_result = (0, 0)

    try:
        try:
            sales_result = sync_pending_sales(r)
        except Exception as e:
            upload_errors.append(f"sales: {e}")
            try: r.rollback()
            except Exception: pass

        try:
            ops_result = sync_pending_operations(r)
        except Exception as e:
            upload_errors.append(f"operations: {e}")
            try: r.rollback()
            except Exception: pass

        # A failed upload must not make branches/main warehouse disappear locally.
        # Use the current connection first; if it was left unusable, retry download
        # using a clean remote connection.
        ok, err = sync_reference_data(r)
        if not ok:
            fresh = None
            try:
                fresh = get_remote_connection()
                ok, err = sync_reference_data(fresh)
            finally:
                if fresh:
                    try: fresh.close()
                    except Exception: pass

        # Verify that branches really arrived locally before declaring download OK.
        if ok:
            lc = get_local_connection(queue_writes=False)
            try:
                count = lc.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
                if int(count or 0) == 0:
                    ok, err = False, "لم يتم تنزيل بيانات الفروع إلى القاعدة المحلية."
            finally:
                lc.close()

        return {
            "sales": sales_result,
            "operations": ops_result,
            "download_ok": bool(ok),
            "download_error": err,
            "upload_errors": upload_errors,
        }
    finally:
        if own:
            try: r.close()
            except Exception: pass


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
