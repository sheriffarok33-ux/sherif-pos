import json
import sqlite3
import threading
import uuid
import socket
import re
import requests
import time as _time
from datetime import timedelta
from functools import wraps
from pathlib import Path
from datetime import datetime, date, time
from decimal import Decimal

# تم التحديث بـ IP سيرفر كونتابو الفعلي
# Same HTTPS endpoint used by branch_auth; never connect to PostgreSQL from Windows.
import sys
from sherif_network import connection_dir
URL_FILE = connection_dir() / 'SERVER_URL.txt'
def _api_base_url():
    from sherif_network import server_enabled
    if not server_enabled(): raise ConnectionError('لم يُهيأ سيرفر للاتصال.')
    if not URL_FILE.is_file():
        raise ConnectionError('SERVER_URL.txt missing: HTTPS API URL required')
    url = URL_FILE.read_text(encoding='utf-8-sig').strip().rstrip('/')
    if not url.startswith('https://'):
        raise ConnectionError('SERVER_URL.txt must start with https://')
    return url

from contextlib import contextmanager
from contextvars import ContextVar
_SYNC_AUTHORIZATION = ContextVar('abuzaid_sync_authorization', default=None)
API_TOKEN = None 

def _current_api_token():
    return _SYNC_AUTHORIZATION.get() or API_TOKEN

@contextmanager
def sync_authorization(token=None):
    marker = _SYNC_AUTHORIZATION.set(token)
    try:
        yield
    finally:
        _SYNC_AUTHORIZATION.reset(marker)

def _authenticated_headers():
    token = _current_api_token()
    return {"Authorization": f"Bearer {token}"} if token else {}

def _request_with_auth_retry(method, path, **kwargs):
    """Retry once after a 401 only when online credentials are held in memory."""
    if path.startswith('/sync/') and device_registration_is_blocked():
        raise PermissionError('تسجيل الجهاز يحتاج اعتماد الإدارة؛ جميع الفواتير والمعلقات محفوظة محليًا.')
    headers = dict(kwargs.pop('headers', {}) or {})
    headers.update(_authenticated_headers())
    from branch_auth import device_auth_headers
    headers.update(device_auth_headers())
    response = requests.request(method, f"{_api_base_url()}{path}", headers=headers, **kwargs)
    if response.status_code != 401 or _SYNC_AUTHORIZATION.get() is not None:
        return response
    try:
        from branch_auth import refresh_online_token
        token = refresh_online_token()
    except Exception:
        token = None
    if not token:
        return response
    headers['Authorization'] = f'Bearer {token}'
    return requests.request(method, f"{_api_base_url()}{path}", headers=headers, **kwargs)

def set_api_token(token):
    global API_TOKEN
    API_TOKEN = token

from sherif_paths import local_db
LOCAL_DB = local_db()

def _schedule_invoice_journal():
    try:
        from sherif_sync_journal import schedule
        schedule(LOCAL_DB)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Invoice journal scheduling failed; committed invoices remain available for recovery')

_LOCK = threading.RLock()
_SYNC_LOCK = threading.RLock()
_LAST_CENTRAL_REFRESH = 0.0
_CENTRAL_REFRESH_SECONDS = 300

def sync_is_paused():
    """Pause only for an explicit maintenance hold; older databases may lack the flag."""
    c = get_local_connection(queue_writes=False)
    try:
        row = c.execute("SELECT value FROM local_meta WHERE key='maintenance_sync_enabled'").fetchone()
        # Missing setting is not evidence that maintenance was requested.
        # An explicit '0' still blocks uploads until maintenance is completed.
        return bool(row and str(row[0]) == '0')
    finally:
        c.close()

def maintenance_operation(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        with _SYNC_LOCK:
            ensure_local_schema()
            c = _raw_local()
            try:
                c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('maintenance_sync_enabled','0')")
                c.execute("DELETE FROM local_meta WHERE key='maintenance_reset_complete'")
                c.commit()
            finally:
                c.close()
            return fn(*args, **kwargs)
    return run

def serialized_sync(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        with _SYNC_LOCK:
            return fn(*args, **kwargs)
    return run

@serialized_sync
def resume_after_preparation():
    c = get_local_connection(queue_writes=False)
    try:
        row = c.execute("SELECT value FROM local_meta WHERE key='maintenance_reset_complete'").fetchone()
        if not row or row[0] != '1':
            raise ValueError('نفّذ التصفير المحلي أولًا. النسخة القديمة لا تُرفع إلى السيرفر تلقائيًا.')
    finally:
        c.close()
    if pending_count() or pending_business_operations_count():
        raise ValueError('توجد معاملات معلقة؛ راجعها أو استخدم التصفير الشامل قبل الاستئناف.')
    ok, error = sync_reference_data()
    if not ok:
        raise RuntimeError(error)
    c = get_local_connection(queue_writes=False)
    try:
        c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('maintenance_sync_enabled','1')")
        c.execute("DELETE FROM local_meta WHERE key='maintenance_reset_complete'")
        c.commit()
    finally:
        c.close()
    from auto_sync import start_auto_sync
    start_auto_sync()


def _sqlite_sql(sql):
    parts = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*.*?\*/)", sql, flags=re.S)
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"\bFOR\s+UPDATE\b", "", parts[i], flags=re.I)
    return ''.join(parts)

class LocalConnection:
    """SQLite connection that records each committed local transaction as one sync unit."""
    def __init__(self, conn, queue_writes=False, actor_id=None, audit_writes=False):
        self._conn = conn
        self._queue_writes = queue_writes
        self._audit_writes = bool(queue_writes or audit_writes)
        self._actor_id = int(actor_id) if actor_id is not None else None
        if self._audit_writes and self._actor_id is not None:
            from control_services import account_login_allowed
            if not account_login_allowed(self._conn, self._actor_id):
                self._conn.close()
                raise PermissionError('الحساب معطل أو انتهت الخدمة؛ يلزم تسجيل الدخول بحساب صالح.')
        self._tx_uuid = str(uuid.uuid4())
        self._tx_seq = 0
        self._invoice_dirty = False
        try:
            row = self._conn.execute("SELECT value FROM local_meta WHERE key='device_id'").fetchone()
            if row and row[0]:
                self._device_id = str(row[0])
            else:
                self._device_id = str(uuid.uuid4())
                self._conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_id',?)", (self._device_id,))
                self._conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('device_name',?)", (socket.gethostname(),))
                self._conn.commit()
        except Exception as exc:
            # A read/lock failure is not permission to invent a second device identity.
            raise RuntimeError('تعذر قراءة هوية الجهاز الحالية؛ لم يتم إنشاء هوية بديلة أو إرسال عمليات بهوية مختلفة.') from exc

        if self._queue_writes:
            _erp_install_capture(self)
        if self._audit_writes:
            from control_services import install_local_financial_audit
            install_local_financial_audit(self._conn, self._actor_id, self._device_id)

    def _record(self, sql, params):
        low = sql.lower(); head = sql.lstrip().upper()
        if not self._queue_writes or not head.startswith(("INSERT ", "UPDATE ", "DELETE ", "REPLACE ")):
            return
        # Appearance/settings changes are local preferences until a dedicated,
        # authenticated settings API is implemented. Never queue raw settings SQL.
        if re.match(r"(?is)^\s*(?:INSERT(?:\s+OR\s+REPLACE)?|REPLACE)\s+INTO\s+[\"`]?app_settings\b", sql) or re.match(
            r"(?is)^\s*(?:UPDATE|DELETE\s+FROM)\s+[\"`]?app_settings\b", sql
        ):
            return
        # POS invoices use the dedicated invoice synchronizer. Internal sync metadata never leaves the device.
        if any(x in low for x in ("sync_queue", "local_meta", "offline_sync_receipts", "into invoices", "update invoices", "delete from invoices")):
            return
        target=re.search(r'(?is)^\s*(?:INSERT(?: OR \w+)? INTO|REPLACE INTO|UPDATE|DELETE FROM)\s+["`]?([a-z_][a-z_0-9]*)',sql)
        if target and target[1].lower() in ERP_TABLES:
            return  # Captured as before/after JSON by connection-local triggers.
        self._tx_seq += 1
        self._conn.execute(
            "INSERT INTO sync_queue(operation_uuid,transaction_uuid,device_id,sequence_no,sql_text,params_json) VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), self._tx_uuid, self._device_id, self._tx_seq, sql, json.dumps(list(params or ()), ensure_ascii=False, default=str))
        )

    def execute(self, sql, params=()):
        if getattr(_SYNC_WORKER_CONTEXT, 'active', False) and _POS_PRIORITY_EVENT.is_set():
            raise sqlite3.OperationalError('Background sync deferred for POS')
        if not str(sql).lstrip().upper().startswith(('SELECT','PRAGMA','EXPLAIN')):
            if self._audit_writes and self._conn.execute("SELECT 1 FROM local_meta WHERE key IN ('device_reconfigure_intent','branch_reset_guard','device_lifecycle_intent','device_command_intent','device_registration_blocked') OR (key='setup_complete' AND value<>'1')").fetchone():
                raise PermissionError('يوجد إجراء إداري لم يكتمل على الجهاز؛ راجع Super Admin قبل تسجيل أي حركة مالية.')
            from central_updater import assert_writes_allowed
            assert_writes_allowed()
        clean = _sqlite_sql(sql)
        try:
            cur = self._conn.execute(clean, params or ())
            if re.match(r'(?is)^\s*(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|UPDATE|DELETE\s+FROM)\s+invoices\b', clean): self._invoice_dirty = True
            # A no-op UPDATE/DELETE must never create an unsendable sync operation.
            if cur.rowcount != 0:
                self._record(clean, params)
            return cur
        except sqlite3.Error:
            if self._audit_writes:
                self.rollback()
            raise

    def executemany(self, sql, seq):
        if getattr(_SYNC_WORKER_CONTEXT, 'active', False) and _POS_PRIORITY_EVENT.is_set():
            raise sqlite3.OperationalError('Background sync deferred for POS')
        if not str(sql).lstrip().upper().startswith(('SELECT','PRAGMA','EXPLAIN')):
            if self._audit_writes and self._conn.execute("SELECT 1 FROM local_meta WHERE key IN ('device_reconfigure_intent','branch_reset_guard','device_lifecycle_intent','device_command_intent','device_registration_blocked') OR (key='setup_complete' AND value<>'1')").fetchone():
                raise PermissionError('يوجد إجراء إداري لم يكتمل على الجهاز؛ راجع Super Admin قبل تسجيل أي حركة مالية.')
            from central_updater import assert_writes_allowed
            assert_writes_allowed()
        clean = _sqlite_sql(sql)
        rows = list(seq)
        try:
            cur = self._conn.executemany(clean, rows)
            # SQLite reports the number of affected rows. Avoid phantom queue entries.
            if cur.rowcount != 0:
                for params in rows:
                    self._record(clean, params)
            return cur
        except sqlite3.Error:
            if self._audit_writes:
                self.rollback()
            raise

    def commit(self):
        try:
            if self._queue_writes:
                _erp_flush(self)
            result = self._conn.commit()
        except Exception:
            self.rollback()
            raise
        self._tx_uuid = str(uuid.uuid4()); self._tx_seq = 0
        if self._invoice_dirty:
            self._invoice_dirty = False
            _schedule_invoice_journal()
        return result

    def rollback(self):
        result = self._conn.rollback()
        self._invoice_dirty = False
        self._tx_uuid = str(uuid.uuid4()); self._tx_seq = 0
        return result

    def close(self): return self._conn.close()
    def __getattr__(self, name): return getattr(self._conn, name)

_SYNC_WORKER_CONTEXT = threading.local()
_POS_PRIORITY_EVENT = threading.Event()
_POS_PRIORITY_LOCK = threading.Lock()
_POS_PRIORITY_COUNT = 0

def begin_pos_priority():
    global _POS_PRIORITY_COUNT
    with _POS_PRIORITY_LOCK:
        _POS_PRIORITY_COUNT += 1
        _POS_PRIORITY_EVENT.set()

def end_pos_priority():
    global _POS_PRIORITY_COUNT
    with _POS_PRIORITY_LOCK:
        _POS_PRIORITY_COUNT = max(0, _POS_PRIORITY_COUNT - 1)
        if not _POS_PRIORITY_COUNT: _POS_PRIORITY_EVENT.clear()

def mark_background_sync_worker():
    _SYNC_WORKER_CONTEXT.active = True

def _raw_local():
    # Background work yields quickly when POS already owns SQLite's writer lock.
    timeout = 0.25 if getattr(_SYNC_WORKER_CONTEXT, 'active', False) else 20
    conn = sqlite3.connect(str(LOCAL_DB), timeout=timeout, check_same_thread=False)
    if getattr(_SYNC_WORKER_CONTEXT, 'active', False):
        conn.set_progress_handler(lambda: int(_POS_PRIORITY_EVENT.is_set()), 500)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    return conn

def ensure_local_schema():
    with _LOCK:
        c = _raw_local()
        c.executescript("""
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
        """)
        # Lightweight migrations for the full desktop/local application.
        migrations = [
          ('transfer_logs','receipt_pending','INTEGER NOT NULL DEFAULT 0'),
          ('transfer_logs','receipt_error','TEXT'),
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
          ('items','scale_price','REAL'),
          ('invoices','invoice_number','TEXT'),
          ('invoices','shift_uuid','TEXT'),
          ('invoices','source_device_id','TEXT'), ('invoices','local_shift_number','INTEGER'), ('invoices','sold_at','TEXT'),
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
        # Device-qualified, monotonic numbering; historical invoice numbers are untouched.
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_local_invoice_number ON invoices(invoice_number) WHERE invoice_number IS NOT NULL")
        c.execute("INSERT OR IGNORE INTO local_meta(key,value) VALUES('invoice_sequence','0')")
        c.execute('DROP TRIGGER IF EXISTS trg_abuzaid_branch_invoice_number')
        c.executescript("""
        CREATE TRIGGER IF NOT EXISTS trg_abuzaid_device_invoice_number
        AFTER INSERT ON invoices
        WHEN NEW.invoice_number IS NULL OR NEW.invoice_number=''
        BEGIN
          UPDATE local_meta SET value=CAST(COALESCE(value,'0') AS INTEGER)+1 WHERE key='invoice_sequence';
          INSERT OR IGNORE INTO local_meta(key,value)
            VALUES('shift_uuid:'||NEW.branch_id||':'||NEW.shift_status,lower(hex(randomblob(16))));
          UPDATE invoices SET
            invoice_number='B'||printf('%02d',NEW.branch_id)||'-D'||
              COALESCE((SELECT value FROM local_meta WHERE key='device_number'),'0')||'-'||
              printf('%06d',(SELECT CAST(value AS INTEGER) FROM local_meta WHERE key='invoice_sequence'))||'-'||
              replace((SELECT value FROM local_meta WHERE key='device_id'),'-',''),
            source_device_id=(SELECT value FROM local_meta WHERE key='device_id'),
            local_shift_number=CASE WHEN NEW.shift_status NOT GLOB '*[^0-9]*' AND NEW.shift_status<>'' THEN CAST(NEW.shift_status AS INTEGER) ELSE NULL END,
            shift_uuid=COALESCE(NEW.shift_uuid,(SELECT value FROM local_meta WHERE key='shift_uuid:'||NEW.branch_id||':'||NEW.shift_status))
          WHERE id=NEW.id;
        END;
        """)
        for col, typ in [('transaction_uuid','TEXT'), ('device_id','TEXT'), ('sequence_no','INTEGER DEFAULT 0')]:
            try: c.execute(f'ALTER TABLE sync_queue ADD COLUMN {col} {typ}')
            except Exception: pass
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
            row=c.execute("SELECT id FROM treasuries WHERE treasury_type='company' ORDER BY id LIMIT 1").fetchone()
            if row:
                c.execute("UPDATE treasuries SET treasury_name='الخزينة الرئيسية',branch_id=NULL,is_active=1 WHERE id=?",(row['id'],))
            else:
                c.execute("INSERT OR IGNORE INTO treasuries(treasury_name,treasury_type,branch_id,is_active) VALUES('الخزينة الرئيسية','company',NULL,1)")
            c.execute("UPDATE treasuries SET is_active=0 WHERE treasury_type='branch'")
        except Exception:
            pass
        for col, typ in [('treasury_id','INTEGER'), ('treasury_name','TEXT')]:
            try: c.execute(f'ALTER TABLE financial_vouchers ADD COLUMN {col} {typ}')
            except Exception: pass
        # Account roles come from authenticated central identities; no automatic promotion.
        try:
            c.execute("UPDATE employees SET full_name=employee_name WHERE (full_name IS NULL OR TRIM(full_name)='') AND employee_name IS NOT NULL")
            c.execute("UPDATE employees SET monthly_salary=salary WHERE COALESCE(monthly_salary,0)=0 AND COALESCE(salary,0)<>0")
            c.execute("UPDATE employees SET employment_status=CASE WHEN COALESCE(is_active,1)=1 THEN 'active' ELSE 'terminated' END WHERE employment_status IS NULL OR employment_status=''")
            c.execute("UPDATE employees SET hire_date=COALESCE(hire_date, substr(created_at,1,10), date('now')) WHERE hire_date IS NULL OR hire_date=''")
        except Exception:
            pass
        try:
            c.execute("UPDATE production_logs SET production_type=operation_type WHERE (production_type IS NULL OR production_type='') AND operation_type IS NOT NULL")
            c.execute("UPDATE production_logs SET input_quantity=input_weight WHERE COALESCE(input_quantity,0)=0 AND COALESCE(input_weight,0)<>0")
            c.execute("UPDATE production_logs SET output_quantity=output_weight WHERE COALESCE(output_quantity,0)=0 AND COALESCE(output_weight,0)<>0")
            c.execute("UPDATE production_logs SET loss_quantity=loss_weight WHERE COALESCE(loss_quantity,0)=0 AND COALESCE(loss_weight,0)<>0")
        except Exception:
            pass
        # Durable invoice changes are captured in the sale transaction itself.
        c.execute("CREATE TABLE IF NOT EXISTS sherif_invoice_changes (seq INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id INTEGER NOT NULL)")
        c.execute("CREATE TRIGGER IF NOT EXISTS sherif_invoice_change_insert AFTER INSERT ON invoices BEGIN INSERT INTO sherif_invoice_changes(invoice_id) VALUES(NEW.id); END")
        c.execute("CREATE TRIGGER IF NOT EXISTS sherif_invoice_change_update AFTER UPDATE ON invoices BEGIN INSERT INTO sherif_invoice_changes(invoice_id) VALUES(NEW.id); END")
        initialized = c.execute("SELECT value FROM local_meta WHERE key='sherif_invoice_change_log_v1'").fetchone()
        if not initialized:
            c.execute("INSERT INTO sherif_invoice_changes(invoice_id) SELECT id FROM invoices WHERE offline_uuid IS NOT NULL AND offline_uuid<>''")
            c.execute("INSERT INTO local_meta(key,value) VALUES('sherif_invoice_change_log_v1','1')")
        _erp_schema(c)
        from control_services import ensure_governance_schema
        ensure_governance_schema(c)
        c.commit(); c.close()
        _schedule_invoice_journal()

def get_device_id():
    c = get_local_connection(queue_writes=False)
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

# Experimental Windows-only optimization: schema validation once per process
# for ordinary local connections. Explicit ensure_local_schema() calls remain unchanged.
_LOCAL_CONNECTION_SCHEMA_READY = False
_LOCAL_CONNECTION_SCHEMA_LOCK = threading.Lock()

def get_local_connection(queue_writes=False, actor_id=None, audit_writes=False):
    global _LOCAL_CONNECTION_SCHEMA_READY
    if not _LOCAL_CONNECTION_SCHEMA_READY:
        with _LOCAL_CONNECTION_SCHEMA_LOCK:
            if not _LOCAL_CONNECTION_SCHEMA_READY:
                ensure_local_schema()
                _LOCAL_CONNECTION_SCHEMA_READY = True
    return LocalConnection(_raw_local(), queue_writes=queue_writes, actor_id=actor_id, audit_writes=audit_writes)

def server_available():
    try:
        resp = requests.get(f"{_api_base_url()}/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False

def _cols(rows):
    if not rows: return []
    r = rows[0]
    try: return list(r.keys())
    except Exception: return []

def _sqlite_value(value):
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
    if not rows:
        return
    cols = [x for x in _cols(rows) if x in allowed]
    if not cols:
        return
    q = ','.join('?' for _ in cols)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({q})"
    vals = [tuple(_sqlite_value(r[x]) for x in cols) for r in rows]
    local.executemany(sql, vals)


def sync_offline_users():
    from branch_auth import local_device_info, provision_offline_users
    device = local_device_info()
    branch_id = int(device.get('bound_branch_id') or device.get('branch_id') or 0)
    if not _current_api_token() or branch_id <= 0:
        return False, 'يلزم اعتماد الجهاز والدخول أونلاين لتجهيز المستخدمين'
    try:
        response = _request_with_auth_retry('GET', '/sync/offline-users', params={'branch_id':branch_id}, timeout=20)
        response.raise_for_status()
        return provision_offline_users(response.json(), branch_id)
    except Exception as exc:
        return False, str(exc)

@serialized_sync
def sync_reference_data(remote=None, *, approved_snapshot=None):
    """Fetch outside the SQLite write lock, then recheck pending work before applying."""
    from branch_auth import local_device_info
    if approved_snapshot is None and not _current_api_token():
        return False, 'يلزم تسجيل دخول أونلاين لتنزيل البيانات.'
    fence_conn=get_local_connection(queue_writes=False)
    try:reference_fence=_reference_fence(fence_conn)
    finally:fence_conn.close()
    device = local_device_info()
    branch_id = int(device.get('bound_branch_id') or device.get('branch_id') or 0)
    try:
        from views.branch_shift_state import cached_state,cache_state
        state_conn=get_local_connection(queue_writes=False)
        try:known=cached_state(state_conn,branch_id)
        finally:state_conn.close()
        state_headers={'X-Operational-State':'true'}
        if known:state_headers['X-Known-Shift-Version']=known['version']
        if approved_snapshot is None:
            response = _request_with_auth_retry('GET', '/sync/branch-snapshot', headers=state_headers,timeout=20)
            response.raise_for_status()
            data = response.json()
        else:
            data=approved_snapshot
        if data.get('protocol') not in (1,2) or any(not isinstance(data.get(k),list) for k in ('branches','items','batches','transfers')):
            raise ValueError('استجابة التنزيل غير مكتملة؛ لم تتغير البيانات.')
        if branch_id and any(int(b['id']) != branch_id for b in data['branches']):
            raise ValueError('السيرفر لم يُرجع لقطة خاصة بالفرع المعتمد للجهاز')
        ids = {int(b['id']) for b in data['branches']}
        if not ids:
            raise ValueError('لم يصل الفرع المعتمد')
        for key,scope in [('items','branch_id'),('batches','branch_id'),('transfers','to_branch_id')]:
            if any(int(row[scope]) not in ids for row in data[key]):
                raise ValueError('بيانات خارج نطاق الفرع؛ لم يتغير الرصيد')
    except Exception as exc:
        return False, str(exc)
    head=data.get('branch_reset_head')
    if head:
        check=get_local_connection(queue_writes=False)
        try:
            current=dict(check.execute("SELECT key,value FROM local_meta WHERE key IN ('sync_generation','setup_complete')"))
            mismatch=current.get('sync_generation')!=head['generation']
            history=check.execute('SELECT 1 FROM invoices WHERE branch_id=? LIMIT 1',(branch_id,)).fetchone()
            if mismatch and (current.get('setup_complete')=='1' or history):
                check.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('branch_reset_guard',?)",(json.dumps(head),));check.commit()
                return False,'يوجد أمر تصفير للفرع؛ يلزم تطبيقه قبل تنزيل جيل جديد'
        finally:check.close()
    # Operational information is cached even when pending sales correctly prevent
    # stock replacement. The resolver pins active work; no invoice is modified.
    state_conn=get_local_connection(queue_writes=False)
    try:
        state_conn.execute('BEGIN IMMEDIATE')
        from views.scale_prices import apply_snapshot_prices
        apply_snapshot_prices(state_conn,data['items'],branch_id)
        stored_generation=state_conn.execute("SELECT value FROM local_meta WHERE key='sync_generation'").fetchone()
        # Existing generations may receive a closure while uploads are pending.
        # A new enrollment adopts its generation only with the complete snapshot.
        if stored_generation and str(stored_generation[0])==str(data.get('sync_generation')):
            from views.branch_shift_state import cache_state,apply_closed_state
            cache_state(state_conn,data.get('operational_state'),branch_id,get_device_id())
            apply_closed_state(state_conn,branch_id,get_device_id())
        state_conn.commit()
    except Exception as error:
        state_conn.rollback();return False,str(error)
    finally:state_conn.close()
    local = get_local_connection(queue_writes=False)
    try:
        local.execute('BEGIN IMMEDIATE')
        if _reference_fence(local)!=reference_fence:
            raise ValueError('وصلت معاملات أثناء تنزيل الأرصدة؛ ستعاد المزامنة تلقائيًا')
        pending = local.execute("SELECT COUNT(*) FROM invoices WHERE COALESCE(sync_status,'pending')!='synced'").fetchone()[0]
        ops = local.execute("SELECT sql_text FROM sync_queue WHERE sync_status='pending'").fetchall()
        structured=local.execute("SELECT COUNT(*) FROM erp_outbox WHERE sync_status='pending'").fetchone()[0]
        if pending or structured or any(not _is_local_settings_sql(r[0]) for r in ops):
            raise ValueError('توجد معاملات معلقة؛ لم تتغير الأرصدة المحلية')
        if local.execute('SELECT COUNT(*) FROM transfer_logs WHERE receipt_pending=1').fetchone()[0]:
            raise ValueError('تأكيد استلام بانتظار الإرسال؛ لم يتغير الرصيد')
        if local.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():
            raise ValueError('تسويات محلية بانتظار تأكيد السيرفر؛ لم يتغير الرصيد')
        def upsert(table,rows,columns):
            for row in rows:
                existing = local.execute(f'SELECT * FROM {table} WHERE id=?',(row['id'],)).fetchone()
                scope = 'to_branch_id' if table=='transfer_logs' else 'branch_id'
                if existing and scope in row and existing[scope] != row[scope]:
                    raise ValueError('تعارض معرفات الصنف بين الجهاز والسيرفر')
                values=[]
                for col in columns:
                    value=row.get(col)
                    if col not in row and existing is not None and col in existing.keys():value=existing[col]
                    if col=='unit_type' and not value:
                        value='kg' if str(row.get('unit') or '').lower() in ('kg','كجم','كيلو') else 'piece'
                    if col=='pieces_per_carton' and value is None:value=1
                    values.append(_sqlite_value(value))
                sql=f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(id) DO UPDATE SET "
                sql+=','.join(f'{col}=excluded.{col}' for col in columns if col!='id')
                local.execute(sql,tuple(values))
        # Translate authoritative ids back to stable local ids; never renumber a working database.
        id_rows=local.execute('SELECT table_name,local_id,remote_id FROM erp_id_map').fetchall()
        reverse={(r['table_name'],int(r['remote_id'])):int(r['local_id']) for r in id_rows}
        for key,table in [('items','items'),('batches','inventory_batches'),('transfers','transfer_logs')]:
            for row in data[key]:
                remote_id=int(row['id']);mapping=(table,remote_id)
                local_id=reverse.get(mapping,remote_id)
                if mapping not in reverse:
                    existing=local.execute('SELECT * FROM '+table+' WHERE id=?',(local_id,)).fetchone()
                    prior=local.execute('SELECT remote_id FROM erp_id_map WHERE table_name=? AND local_id=?',(table,local_id)).fetchone()
                    scope='to_branch_id' if table=='transfer_logs' else 'branch_id'
                    occupied=bool(prior and int(prior[0])!=remote_id)
                    occupied=occupied or bool(existing and int(existing[scope])!=int(row[scope]))
                    if table=='items' and existing:
                        occupied=occupied or str(existing['item_code'])!=str(row['item_code'])
                    if occupied:
                        # A branch move must not overwrite or renumber the old
                        # branch's rows when a remote ID collides with a local ID.
                        used=local.execute('SELECT COALESCE(MAX(id),0) FROM '+table).fetchone()[0]
                        mapped=local.execute('SELECT COALESCE(MAX(local_id),0) FROM erp_id_map WHERE table_name=?',(table,)).fetchone()[0]
                        local_id=max(int(used),int(mapped))+1
                row['id']=local_id;reverse[mapping]=local_id
                local.execute('INSERT INTO erp_id_map VALUES(?,?,?) ON CONFLICT(table_name,local_id) DO UPDATE SET remote_id=excluded.remote_id',(table,local_id,remote_id))
                if table=='inventory_batches':row['item_id']=reverse.get(('items',int(row['item_id'])),row['item_id'])
        from views.party_reference import apply_parties
        party_result=apply_parties(local,data.get('parties'),branch_id)
        local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('party_reference_status',?)",(json.dumps(party_result,ensure_ascii=False),))
        upsert('branches',data['branches'],['id','branch_name','branch_type','location','is_active'])
        upsert('items',data['items'],['id','item_code','item_name','unit','quantity','buy_price','sale_price','scale_price','avg_cost','branch_id','expiry_date','pieces_per_carton','image_path','scale_code','unit_type','no_expiry'])
        if 'item_barcodes' in data:
            from views.item_barcodes import apply_snapshot
            if data['item_barcodes'] or local.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='item_barcodes'").fetchone():
                apply_snapshot(local,data['item_barcodes'],{str(row['item_code']) for row in data['items']},data.get('scale_settings',{}))
        central_items={int(row['id']) for row in data['items']}
        central_batches={int(row['id']) for row in data['batches']}
        for bid in ids:
            for row in local.execute('SELECT id FROM items WHERE branch_id=?',(bid,)).fetchall():
                if row['id'] not in central_items:local.execute('UPDATE items SET quantity=0 WHERE id=?',(row['id'],))
            for row in local.execute('SELECT id FROM inventory_batches WHERE branch_id=?',(bid,)).fetchall():
                if row['id'] not in central_batches:local.execute('UPDATE inventory_batches SET remaining_quantity=0 WHERE id=?',(row['id'],))
        upsert('inventory_batches',data['batches'],['id','item_id','branch_id','quantity','remaining_quantity','received_date','expiry_date','unit_cost','source_type','created_at'])
        upsert('transfer_logs',data['transfers'],['id','from_branch_id','to_branch_id','items_details','transfer_date','status','created_by','received_by','created_at'])
        if isinstance(data.get('permissions'),list):
            local.execute('CREATE TABLE IF NOT EXISTS user_branch_permissions(user_id INTEGER NOT NULL,branch_id INTEGER NOT NULL,permission_key TEXT NOT NULL,granted_by INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(user_id,branch_id,permission_key))')
            for bid in ids:
                local.execute("DELETE FROM user_branch_permissions WHERE branch_id=? AND permission_key='pos_sell'",(bid,))
            for grant in data['permissions']:
                if int(grant['branch_id']) not in ids or grant['permission_key']!='pos_sell':raise ValueError('صلاحية خارج الفرع')
                local.execute('INSERT OR IGNORE INTO user_branch_permissions(user_id,branch_id,permission_key) VALUES(?,?,?)',(grant['user_id'],grant['branch_id'],grant['permission_key']))
        generation=data.get('sync_generation')
        if generation is not None:
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('sync_generation',?)",(str(generation),))
        from views.branch_shift_state import cache_state,apply_closed_state
        cache_state(local,data.get('operational_state'),branch_id,get_device_id())
        apply_closed_state(local,branch_id,get_device_id())
        cache_replacement_history(local,data.get('recovery_history'))
        local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('last_download',?)",(datetime.now().isoformat(timespec='seconds'),))
        local.commit()
        return True,None
    except Exception as exc:
        local.rollback();return False,str(exc)
    finally:
        local.close()


@serialized_sync
def acknowledge_transfers(transfer_ids, branch_id, username):
    local = get_local_connection(queue_writes=False)
    try:
        local.execute('BEGIN IMMEDIATE')
        for tid in transfer_ids:
            row = local.execute('SELECT status,to_branch_id FROM transfer_logs WHERE id=?', (int(tid),)).fetchone()
            if not row or row['to_branch_id'] != int(branch_id) or row['status'] != 'بانتظار تأكيد الكاشير':
                raise ValueError('حالة التزويد تغيرت؛ حدّث الشاشة قبل تأكيد الاستلام.')
            local.execute('UPDATE transfer_logs SET status=?,received_by=?,receipt_pending=1,receipt_error=NULL WHERE id=?',
                          ('مكتملة ومستلمة بواسطة الكاشير: '+username, username, int(tid)))
        local.commit()
    except Exception:
        local.rollback()
        raise
    finally:
        local.close()


@serialized_sync
def sync_transfer_receipts():
    if sync_is_paused():
        return 0, 0
    local = get_local_connection(queue_writes=False)
    sent = failed = 0
    try:
        # Migrate only the exact legacy receipt UPDATE, retaining its audit row.
        for op in local.execute("SELECT id,sql_text,params_json FROM sync_queue WHERE sync_status='pending'").fetchall():
            if ' '.join(op['sql_text'].split()).upper() != 'UPDATE TRANSFER_LOGS SET STATUS = ? WHERE ID = ?':
                continue
            try:
                status, tid = json.loads(op['params_json'])
                if not isinstance(status, str) or not status.startswith('مكتملة ومستلمة بواسطة الكاشير: '):
                    continue
                row = local.execute('SELECT id FROM transfer_logs WHERE id=?', (int(tid),)).fetchone()
                if not row: continue
                local.execute('UPDATE transfer_logs SET receipt_pending=1 WHERE id=?', (int(tid),))
                local.execute("UPDATE sync_queue SET sync_status='ignored',sync_error='Moved to structured transfer receipt retry' WHERE id=?", (op['id'],))
            except (ValueError, TypeError):
                continue
        local.commit()
        for row in local.execute('SELECT id,to_branch_id FROM transfer_logs WHERE receipt_pending=1 ORDER BY id').fetchall():
            try:
                response = _request_with_auth_retry('POST','/sync/transfer-receipt',
                    json={'transfer_id':row['id'],'branch_id':row['to_branch_id'],'sync_generation':_invoice_sync_generation(local)},timeout=15)
                if response.status_code in (404, 409):
                    local.execute('UPDATE transfer_logs SET receipt_pending=0,status=?,receipt_error=? WHERE id=?',
                                  ('تعذر الاستلام: راجع حالة التزويد', str(response.text), row['id']))
                    local.commit(); failed += 1
                    continue
                response.raise_for_status()
                data = response.json()
                if data.get('transfer_id') != row['id'] or data.get('branch_id') != row['to_branch_id'] or not str(data.get('status','')).startswith('مكتملة ومستلمة'):
                    raise ValueError('لم يؤكد السيرفر الاستلام.')
                local.execute('UPDATE transfer_logs SET status=?,receipt_pending=0,receipt_error=NULL WHERE id=?', (data['status'],row['id']))
                local.commit(); sent += 1
            except Exception as exc:
                local.execute('UPDATE transfer_logs SET receipt_error=? WHERE id=?', (str(exc),row['id']))
                local.commit(); failed += 1
        return sent, failed
    finally:
        local.close()


def offline_login(username, password):
    c = get_local_connection()
    try:
        return c.execute('SELECT * FROM users WHERE username=? AND password=? AND is_active=1 LIMIT 1',(username.strip(),password)).fetchone()
    finally: c.close()

def _invoice_sync_generation(local):
    """Generation from a previously validated central snapshot, never guessed."""
    row = local.execute("SELECT value FROM local_meta WHERE key='sync_generation'").fetchone()
    return str(row[0]) if row and row[0] else None


def _safe_sync_error(error):
    """Reuse existing diagnostics columns without retaining recognizable credentials."""
    try:
        text = str(error)
    except Exception:
        return 'Synchronization error: details unavailable'
    sensitive = re.search(
        r"""(?ix)\bbearer\s+\S+|\b(?:password|passwd|pwd|token|access_token|refresh_token|device_token|api_key|authorization)\b["']?\s*[:=]|(?:https?|postgres(?:ql)?)://[^/\s@]+@""",
        text)
    if sensitive:
        status = re.search(r'(?i)\bHTTP\s+(\d{3})\b', text)
        return (('HTTP ' + status.group(1) + ': ') if status else '') + 'Sensitive diagnostic details omitted'
    return text[:500]


def _valid_reconciled_invoice(found, original):
    """Validate existing receipt fields; no new endpoint or payload field."""
    if type(found.get('remote_invoice_id')) is not int or found['remote_invoice_id'] <= 0:
        return False
    if str(found.get('invoice_number') or '') != str(original['invoice_number'] or ''):
        return False
    if 'total_amount' not in found or isinstance(found['total_amount'], bool):
        return False
    try:
        remote_total = Decimal(str(found['total_amount']))
        local_total = Decimal(str(original['total_amount']))
        return (remote_total.is_finite() and local_total.is_finite()
                and abs(remote_total - local_total) <= Decimal('0.001'))
    except (ValueError, TypeError, ArithmeticError):
        return False


def _validated_erp_mappings(mappings):
    """Reject corrupt mappings before changing the ID map or acknowledging a batch."""
    if not isinstance(mappings, list):
        raise ValueError('Invalid ERP mappings')
    seen = {}
    for mapping in mappings:
        if not isinstance(mapping, dict) or not isinstance(mapping.get('table'), str) or mapping['table'] not in ERP_TABLES:
            raise ValueError('Invalid ERP mapping table')
        if any(type(mapping.get(k)) is not int or mapping[k] <= 0 for k in ('local_id', 'remote_id')):
            raise ValueError('Invalid ERP mapping identity')
        key = (mapping['table'], mapping['local_id'])
        if key in seen and seen[key] != mapping['remote_id']:
            raise ValueError('Conflicting ERP mappings')
        seen[key] = mapping['remote_id']
    return mappings


def _reconcile_pending_invoices(local):
    """Confirm previously accepted uploads by immutable UUID; never post stock."""
    rows = local.execute("SELECT id, offline_uuid, invoice_number, branch_id, total_amount FROM invoices WHERE sync_status='pending' ORDER BY id").fetchall()
    groups = {}
    for row in rows:
        if row['offline_uuid']:
            groups.setdefault(int(row['branch_id']), []).append(row)
    for branch_id, entries in groups.items():
        for offset in range(0, len(entries), 100):
            batch = entries[offset:offset+100]
            try:
                resp = _request_with_auth_retry('POST', '/sync/invoice-reconcile', json={
                    'branch_id': branch_id,
                    'invoices': [{'offline_uuid': r['offline_uuid'], 'invoice_number': r['invoice_number'] or ''} for r in batch]
                }, timeout=15)
                if resp.status_code != 200:
                    continue  # Old server / insufficient permission: ordinary upload reports the error.
                response_data = resp.json()
                if type(response_data.get('branch_id')) is not int or response_data['branch_id'] != branch_id:
                    continue
                results = response_data.get('invoices', [])
                by_uuid = {str(r['offline_uuid']): r for r in batch}
                for found in results:
                    original = by_uuid.get(str(found.get('offline_uuid')))
                    if not original or found.get('state') != 'found' or found.get('match_source') != 'offline_uuid':
                        continue  # Invoice-number matches alone are NOT proof of identity.
                    remote_id = found.get('remote_invoice_id')
                    if not _valid_reconciled_invoice(found, original):
                        continue
                    local.execute("UPDATE invoices SET sync_status='synced', remote_invoice_id=?, sync_error=NULL WHERE id=? AND sync_status='pending'", (remote_id, original['id']))
                local.commit()
            except Exception:
                local.rollback()  # Fail closed; do not assume successful upload.


@serialized_sync
def sync_pending_sales(remote=None):
    if sync_is_paused():
        return 0, 0
    local = get_local_connection()
    synced = 0; failed = 0
    try:
        _reconcile_pending_invoices(local)
        from sherif_sync_journal import pending_invoice_ids
        ids = pending_invoice_ids(LOCAL_DB)
        pending = []
        for invoice_id, operation_id in ids:
            row = local.execute("SELECT * FROM invoices WHERE id=? AND offline_uuid=? AND sync_status='pending'", (invoice_id, operation_id)).fetchone()
            if row: pending.append(row)
        for inv in pending:
            try:
                mapped_notes=json.loads(inv['notes'] or '{}')
                for item in mapped_notes.get('items',[]):
                    mapping=local.execute("SELECT remote_id FROM erp_id_map WHERE table_name='items' AND local_id=?",(item.get('id'),)).fetchone()
                    if mapping:item['id']=mapping[0]
                if mapped_notes.get('customer_id'):
                    customer=local.execute("SELECT remote_id FROM erp_id_map WHERE table_name='customers' AND local_id=?",(mapped_notes['customer_id'],)).fetchone()
                    if customer:mapped_notes['customer_id']=int(customer[0])
                    else:mapped_notes.pop('customer_id',None)  # Legacy phone lookup; never send a local ID as a central ID.
                payload = {
                    "sync_generation": _invoice_sync_generation(local),
                    "offline_uuid": inv["offline_uuid"],
                    "branch_id": inv["branch_id"],
                    "user_id": inv["user_id"],
                    "customer_name": inv["customer_name"] or "زبون نقدي",
                    "customer_phone": inv["customer_phone"] or "",
                    "total_amount": float(inv["total_amount"] or 0),
                    "payment_method": inv["payment_method"] or "كاش",
                    "notes": json.dumps(mapped_notes,ensure_ascii=False,separators=(',',':')),
                    "shift_status": str(inv["local_shift_number"]) if inv["local_shift_number"] else (inv["shift_status"] or "open"),
                    "invoice_number": inv["invoice_number"],
                    "shift_uuid": inv["shift_uuid"],
                    "source_device_id": inv["source_device_id"] or get_device_id(),
                    "created_at": inv["created_at"],
                    "sold_at": inv["sold_at"]
                }
                headers = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}
                resp = _request_with_auth_retry("POST", "/sync/invoice", json=payload, timeout=10)
                
                if resp.status_code == 200:
                    data = resp.json()
                    remote_id = _validate_invoice_ack(data, inv)
                    local.execute("UPDATE invoices SET sync_status='synced', remote_invoice_id=?, sync_error=NULL WHERE id=?", (remote_id, inv["id"]))
                    local.commit()
                    synced += 1
                else:
                    raise ValueError(f"HTTP {resp.status_code}: {resp.text}")
            except Exception as e:
                local.execute("UPDATE invoices SET sync_error=? WHERE id=?", (_safe_sync_error(e), inv['id']))
                local.commit()
                failed += 1
                break  # Keep later sales pending until this earlier sale is acknowledged.
        return synced, failed
    finally:
        local.close()

_LEGACY_LOCAL_HR_SQL = {
    "UPDATE employees SET full_name=employee_name WHERE (full_name IS NULL OR TRIM(full_name)='') AND employee_name IS NOT NULL",
    "UPDATE employees SET monthly_salary=salary WHERE COALESCE(monthly_salary,0)=0 AND COALESCE(salary,0)<>0",
    "UPDATE employees SET employment_status=CASE WHEN COALESCE(is_active,1)=1 THEN 'active' ELSE 'terminated' END WHERE employment_status IS NULL OR employment_status=''",
    "UPDATE employees SET hire_date=COALESCE(NULLIF(hire_date,''), substr(created_at,1,10), date('now')) WHERE hire_date IS NULL OR hire_date=''",
}

def _quarantine_legacy_hr_migrations(local):
    rows = local.execute("SELECT id,sql_text FROM sync_queue WHERE sync_status='pending'").fetchall()
    ids = [(r['id'],) for r in rows if r['sql_text'].strip() in _LEGACY_LOCAL_HR_SQL]
    if ids:
        local.executemany(
            "UPDATE sync_queue SET sync_status='ignored', sync_error='Legacy local HR schema migration; not a remote business operation' WHERE id=?", ids
        )
        local.commit()
    return len(ids)

@serialized_sync
def sync_pending_operations(remote=None):
    return sync_structured_erp()


def preview_pending_item_conflicts():
    """Read-only comparison of queued item edits against central item values.

    Does not upload SQL, replay edits, change statuses, or overwrite local stock.
    Returns a list of server/local snapshots for manual reconciliation.
    """
    local = get_local_connection(queue_writes=False)
    try:
        rows = local.execute(
            "SELECT id, sql_text, params_json FROM sync_queue "
            "WHERE sync_status='pending' ORDER BY id"
        ).fetchall()
        ids = set()
        unsupported = []
        for row in rows:
            sql = ' '.join((row['sql_text'] or '').split())
            if re.match(r'^UPDATE\s+items\s+SET\s+', sql, re.I) and re.search(
                r'\bWHERE\s+id\s*=\s*\?\s+AND\s+branch_id\s*=\s*\?\s*$', sql, re.I
            ):
                try:
                    params = json.loads(row['params_json'] or '[]')
                    ids.add(int(params[-2]))
                except (ValueError, TypeError, IndexError):
                    unsupported.append(row['id'])
            elif re.match(r'^UPDATE\s+items\s+SET\s+', sql, re.I):
                # Global unit migrations: do not replay as remote writes.
                unsupported.append(row['id'])
            else:
                unsupported.append(row['id'])
        local_rows = {}
        for item_id in ids:
            item = local.execute(
                'SELECT id, branch_id, item_name, quantity, buy_price, sale_price, avg_cost '
                'FROM items WHERE id=?', (item_id,)
            ).fetchone()
            local_rows[item_id] = dict(item) if item else None
    finally:
        local.close()
    server_rows = {}
    if ids:
        response = _request_with_auth_retry(
            'POST', '/sync/items/compare', json={'item_ids': sorted(ids)}, timeout=20
        )
        response.raise_for_status()
        server_rows = {int(r['id']): r for r in response.json()['items']}
    return {
        'pending_operations': len(rows),
        'compared_items': len(ids),
        'manual_review_operation_ids': unsupported,
        'differences': [
            {'item_id': item_id, 'local': local_rows[item_id], 'server': server_rows.get(item_id)}
            for item_id in sorted(ids)
            if local_rows[item_id] != server_rows.get(item_id)
        ],
        'read_only': True,
    }


def sync_diagnostics(limit=20):
    local = get_local_connection(queue_writes=False)
    try:
        ops = local.execute(
            "SELECT id, transaction_uuid, sync_status, sync_error "
            "FROM sync_queue WHERE sync_status='pending' ORDER BY id LIMIT ?",
            (max(1, min(int(limit), 100)),)
        ).fetchall()
        sales = local.execute(
            "SELECT id, sync_status, sync_error FROM invoices "
            "WHERE sync_status='pending' ORDER BY id LIMIT ?",
            (max(1, min(int(limit), 100)),)
        ).fetchall()
        return {
            'pending_operations': pending_operations_count(),
            'pending_invoices': pending_count(),
            'operation_errors': [dict(row) for row in ops],
            'invoice_errors': [dict(row) for row in sales],
            'transport': 'https_api',
            'note': 'Using HTTP API via requests',
        }
    finally:
        local.close()

def _is_local_settings_sql(sql):
    """Recognize only direct writes to app_settings, regardless of whitespace/quoting.

    This is a classification for download safety, not permission to discard queue rows.
    """
    normalized = re.sub(r"\s+", " ", (sql or "").strip())
    return bool(re.match(
        r'(?is)^(?:INSERT(?: OR (?:REPLACE|IGNORE|ABORT|FAIL|ROLLBACK))? INTO|REPLACE INTO|UPDATE|DELETE FROM)\s+(?:["`\[]?app_settings["`\]]?)\b',
        normalized,
    )) or bool(re.match(
        r'(?is)^(?:INSERT(?: OR (?:REPLACE|IGNORE|ABORT|FAIL|ROLLBACK))? INTO|REPLACE INTO|UPDATE|DELETE FROM)\s+["`\[]app_settings["`\]](?:\s|\(|$)',
        normalized,
    ))


def pending_business_operations_count():
    """Count pending operations except verified app_settings-only writes.

    Existing settings queue records are retained without modification.
    """
    c = get_local_connection(queue_writes=False)
    try:
        rows = c.execute("SELECT sql_text FROM sync_queue WHERE sync_status='pending'").fetchall()
        return (sum(not _is_local_settings_sql(row['sql_text']) for row in rows)
                +int(c.execute("SELECT COUNT(*) FROM erp_outbox WHERE sync_status='pending' AND source!='legacy'").fetchone()[0]))
    finally:
        c.close()

def pending_operations_count():
    c=get_local_connection(queue_writes=False)
    try: return pending_business_operations_count()
    finally: c.close()

def sync_after_login(remote=None):
    upload_errors = []
    sales_result = (0, 0)
    ops_result = (0, 0)

    try:
        reset_result=sync_branch_reset_commands()
        if not reset_result.get('ok'):return {'sales':(0,0),'operations':(0,0),'download_ok':False,'download_error':reset_result.get('error'),'upload_errors':[]}
        try:
            from branch_auth import acknowledge_pending_device_change
            acknowledge_pending_device_change()
        except Exception:
            pass
        try:
            sales_result = sync_pending_sales()
        except Exception as e:
            upload_errors.append(f"sales: {e}")

        try:
            ops_result = sync_pending_operations()
        except Exception as e:
            upload_errors.append(f"operations: {e}")

        sync_transfer_receipts()
        ok, err = sync_reference_data()
        # Offline password provisioning is a separate Super_Admin-only action.
        users_ok, users_error = None, None
        
        if ok:
            lc = get_local_connection(queue_writes=False)
            try:
                count = lc.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
                if int(count or 0) == 0:
                    ok, err = False, "لم يتم تنزيل بيانات الفروع إلى القاعدة المحلية."
            finally:
                lc.close()

        try:
            refresh_central_z_cache(force=True)
        except Exception:
            pass
        return {
            "sales": sales_result,
            "operations": ops_result,
            "download_ok": bool(ok),
            "download_error": err,
            "upload_errors": upload_errors,
        }
    except Exception as e:
        return {
            "sales": sales_result,
            "operations": ops_result,
            "download_ok": False,
            "download_error": str(e),
            "upload_errors": upload_errors,
        }


@serialized_sync
def sync_pending_shift_closures():
    if sync_is_paused():return 0,0
    local=get_local_connection();ok=failed=0
    try:
        local.execute("""CREATE TABLE IF NOT EXISTS local_shift_uploads(branch_id INTEGER NOT NULL,shift_date TEXT NOT NULL,
            shift_number INTEGER NOT NULL,synced_at TEXT,last_error TEXT,PRIMARY KEY(branch_id,shift_date,shift_number))""")
        if 'cancelled_reset_id' not in {r[1] for r in local.execute('PRAGMA table_info(local_shift_uploads)')}:local.execute('ALTER TABLE local_shift_uploads ADD COLUMN cancelled_reset_id TEXT')
        local.commit()
        has_shift_uuid=any(r[1]=='shift_uuid' for r in local.execute('PRAGMA table_info(shift_closures)'))
        historical_guard=" AND NOT EXISTS (SELECT 1 FROM local_meta a WHERE a.key='historical_unconfirmed_shift:'||s.shift_uuid AND a.value='approved_unconfirmed_no_financial_effect')" if has_shift_uuid else ''
        closures=local.execute("""SELECT s.* FROM shift_closures s LEFT JOIN local_shift_uploads u
            ON u.branch_id=s.branch_id AND u.shift_date=s.shift_date AND u.shift_number=s.shift_number
            WHERE u.synced_at IS NULL AND COALESCE(u.cancelled_reset_id,'')=''"""+historical_guard+' ORDER BY s.shift_date,s.shift_number').fetchall()
        for c in closures:
            b,day,shift=int(c['branch_id']),str(c['shift_date']),int(c['shift_number'])
            try:
                shift_uuid=c['shift_uuid'] if 'shift_uuid' in c.keys() else None
                remote_intent=local.execute("SELECT value FROM local_meta WHERE key='remote_shift_close_intent'").fetchone()
                if remote_intent and json.loads(remote_intent[0])['payload']['shift_uuid']==shift_uuid:
                    continue  # The delegated endpoint owns this seal and its administrator audit actor.

                if shift_uuid:
                    invoices=local.execute('SELECT offline_uuid,sync_status FROM invoices WHERE branch_id=? AND shift_uuid=? ORDER BY id',(b,shift_uuid)).fetchall()
                else:
                    # Never guess which historical invoices belong to two already closed legacy shifts.
                    count=local.execute('SELECT COUNT(*) FROM shift_closures WHERE branch_id=? AND shift_date=?',(b,day)).fetchone()[0]
                    if count!=1:raise ValueError('إغلاق قديم متعدد الورديات يحتاج مصالحة معتمدة؛ لم تُغيّر الفواتير')
                    invoices=local.execute("SELECT offline_uuid,sync_status FROM invoices WHERE branch_id=? AND date(created_at)=? AND shift_status='Z_Closed' ORDER BY id",(b,day)).fetchall()
                if not invoices or any(row['sync_status']!='synced' for row in invoices):raise ValueError('انتظر تأكيد رفع جميع فواتير الوردية')
                payload={'branch_id':b,'shift_date':day,'shift_number':shift,'sync_generation':_invoice_sync_generation(local),
                         'invoice_uuids':[row['offline_uuid'] for row in invoices]}
                if shift_uuid:payload.update(shift_uuid=shift_uuid,device_id=c['device_id'])
                response=_request_with_auth_retry('POST','/sync/shift-close',json=payload,timeout=20)
                response.raise_for_status()
                result=response.json()
                if result.get('invoice_count')!=len(invoices):raise ValueError('عدد فواتير الإغلاق لم يؤكده السيرفر')
                local.execute("""INSERT INTO local_shift_uploads(branch_id,shift_date,shift_number,synced_at,last_error)
                    VALUES(?,?,?,CURRENT_TIMESTAMP,NULL) ON CONFLICT(branch_id,shift_date,shift_number)
                    DO UPDATE SET synced_at=CURRENT_TIMESTAMP,last_error=NULL""",(b,day,shift))
                local.commit();ok+=1
            except Exception as exc:
                local.execute("""INSERT INTO local_shift_uploads(branch_id,shift_date,shift_number,last_error) VALUES(?,?,?,?)
                    ON CONFLICT(branch_id,shift_date,shift_number) DO UPDATE SET last_error=excluded.last_error""",(b,day,shift,str(exc)))
                local.commit();failed+=1
        return ok,failed
    finally:local.close()

def _resume_unintended_pause_if_safe():
    """Resume an old pause only if the server reset generation is proven unchanged.

    Never accept a missing generation as a match. Never alter invoices or stock.
    """
    if not sync_is_paused():
        return True
    local = get_local_connection(queue_writes=False)
    try:
        stored = local.execute("SELECT value FROM local_meta WHERE key='sync_generation'").fetchone()
        reset = local.execute("SELECT value FROM local_meta WHERE key='maintenance_reset_complete'").fetchone()
        if not stored or not stored[0] or reset:
            return False
        response = _request_with_auth_retry('GET', '/sync/branch-snapshot', timeout=15)
        if response.status_code != 200:
            return False
        current = response.json().get('sync_generation')
        if current is None or str(current) != str(stored[0]):
            return False
        # Compare-and-swap: only release the precise legacy hold we checked.
        local.execute("UPDATE local_meta SET value='1' WHERE key='maintenance_sync_enabled' AND value='0'")
        local.commit()
        return True
    except Exception:
        local.rollback()
        return False
    finally:
        local.close()


@serialized_sync
def sync_now():
    try:
        from branch_auth import acknowledge_pending_device_change
        acknowledge_pending_device_change()
    except Exception:
        pass
    if not _current_api_token():
        return {'synced':0,'failed':0,'ops_synced':0,'ops_failed':0,
                'download_ok':False,'users_ok':None,'users_error':None,'auth_required':True,
                'error':'الدخول المحلي متاح؛ استعد اتصال المزامنة أونلاين من القائمة الجانبية.'}
    reset_result=sync_branch_reset_commands()
    if not reset_result.get('ok'):
        return {'synced':0,'failed':0,'ops_synced':0,'ops_failed':0,'download_ok':False,'error':reset_result.get('error','يوجد أمر إداري يحتاج الاستكمال')}
    if not _resume_unintended_pause_if_safe():
        return {'synced':0,'failed':0,'ops_synced':0,'ops_failed':0,'download_ok':False,
                'error':'المزامنة متوقفة؛ استأنفها من تجهيز البيانات.'}
    stage_errors={}
    def run_stage(name, operation, fallback):
        try:return operation()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception('Independent sync stage failed: %s',name)
            stage_errors[name]=type(exc).__name__
            return fallback
    ops_synced, ops_failed = run_stage('operations',sync_pending_operations,(0,1))
    synced, failed = run_stage('sales',sync_pending_sales,(0,1))
    shifts_synced, shifts_failed = run_stage('shifts',sync_pending_shift_closures,(0,1))
    receipts, receipt_failed = run_stage('transfer_receipts',sync_transfer_receipts,(0,1))
    settlement_sent, settlement_failed = run_stage('settlements',sync_exception_settlements,(0,1))
    from views.invoice_cancellation_client import sync_cancellations
    cancellation_result=run_stage('history_cancellations',sync_cancellations,{'state':'retry_pending'})
    ok, err = run_stage('reference_data',sync_reference_data,(False,'تعذر تنزيل البيانات المرجعية؛ محفوظة محليًا'))
    if ok:run_stage('exception_targets',sync_exception_targets,None)
    # Cashier background sync must not repeatedly request all user passwords.
    users_ok, users_error = None, None
    try:
        refresh_central_z_cache()
    except Exception:
        pass
    return {'synced':synced,'failed':failed,'receipts':receipts,'receipt_failed':receipt_failed,
            'shifts_synced':shifts_synced,'shifts_failed':shifts_failed,
            'settlements_synced':settlement_sent,'settlements_failed':settlement_failed,
            'ops_synced':ops_synced,'ops_failed':ops_failed,'download_ok':ok,'error':err,'users_ok':users_ok,'users_error':users_error,'stage_errors':stage_errors}

def get_pos_connection(actor_id=None):
    # POS has a dedicated invoice uploader: audit locally, never enqueue stock twice.
    return get_local_connection(actor_id=actor_id, audit_writes=True), 'offline'

def pending_count():
    c=get_local_connection()
    try: return int(c.execute("SELECT COUNT(*) FROM invoices WHERE sync_status='pending'").fetchone()[0])
    finally: c.close()


def _ensure_central_z_cache(conn):
    """Read-only central summary cache. Never inserts sales or stock movements."""
    conn.execute("""CREATE TABLE IF NOT EXISTS central_z_summary_cache (
        branch_id INTEGER NOT NULL,
        shift_date TEXT NOT NULL,
        summary_json TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        PRIMARY KEY(branch_id, shift_date))""")


def get_cached_central_shift_summary(branch_id, shift_date):
    """Latest successfully downloaded central total, available without Internet."""
    c = _raw_local()
    try:
        _ensure_central_z_cache(c)
        row = c.execute("""SELECT summary_json,fetched_at FROM central_z_summary_cache
            WHERE branch_id=? AND shift_date=?""", (int(branch_id), str(shift_date))).fetchone()
        if not row:
            return None
        result = json.loads(row['summary_json'])
        result['cached_at'] = row['fetched_at']
        return result
    finally:
        c.close()


def get_central_shift_summary(branch_id, shift_date):
    """Fetch and cache an authorized central Z; never change invoices, stock or treasury."""
    response = _request_with_auth_retry('GET', '/sync/shift-summary',
        params={'branch_id':int(branch_id), 'shift_date':str(shift_date)}, timeout=8)
    response.raise_for_status()
    data = response.json()
    if (int(data['branch_id']) != int(branch_id)
            or str(data['shift_date']) != str(shift_date)):
        raise ValueError('Central summary branch/date mismatch; cache not updated')
    c = _raw_local()
    try:
        _ensure_central_z_cache(c)
        c.execute("""INSERT INTO central_z_summary_cache
            (branch_id,shift_date,summary_json,fetched_at) VALUES(?,?,?,?)
            ON CONFLICT(branch_id,shift_date) DO UPDATE SET
            summary_json=excluded.summary_json,fetched_at=excluded.fetched_at""",
            (int(branch_id), str(shift_date), json.dumps(data, ensure_ascii=False),
             datetime.now().isoformat(timespec='seconds')))
        c.commit()
    finally:
        c.close()
    return data


def refresh_central_z_cache(force=False):
    """Bounded, throttled best-effort refresh; never blocks offline sales."""
    global _LAST_CENTRAL_REFRESH
    if not _current_api_token():
        return 0
    now = _time.monotonic()
    if not force and now - _LAST_CENTRAL_REFRESH < _CENTRAL_REFRESH_SECONDS:
        return 0
    _LAST_CENTRAL_REFRESH = now
    c = _raw_local()
    try:
        dates = [date.today().isoformat(), (date.today() - timedelta(days=1)).isoformat()]
        try:
            for r in c.execute('SELECT DISTINCT shift_date FROM shift_closures ORDER BY shift_date DESC LIMIT 2'):
                if r[0] not in dates:
                    dates.append(r[0])
        except sqlite3.OperationalError:
            pass
        branches = []
        # One Windows branch installation is bound to one branch; do not fetch other branches.
        try:
            row = c.execute("SELECT value FROM local_meta WHERE key='branch_id'").fetchone()
            if row and str(row[0]).isdigit():
                branches = [int(row[0])]
        except sqlite3.OperationalError:
            pass
        if not branches:
            row = c.execute('SELECT branch_id FROM invoices WHERE branch_id IS NOT NULL ORDER BY id DESC LIMIT 1').fetchone()
            branches = [int(row[0])] if row else []
        if not branches:
            row = c.execute('SELECT branch_id FROM shift_closures ORDER BY shift_date DESC LIMIT 1').fetchone()
            branches = [int(row[0])] if row else []
    finally:
        c.close()
    successes = 0
    for branch_id in branches:
        for day in dates[:4]:
            try:
                get_central_shift_summary(branch_id, day)
                successes += 1
            except Exception:
                # Keep last good snapshot and continue local operation.
                continue
    return successes


def next_invoice_number(conn, branch_id):
    data = _read_number_range(conn,branch_id)
    if not data or data['next'] > data['end']:
        data = _read_number_range(conn,branch_id,'spare')
    if not data or data['next'] > data['end']:
        return 'يُجهّز رقم الفاتورة تلقائياً'
    return _format_reserved_invoice_number(data, branch_id)


# Structured ERP outbox. SQL text is retained locally for legacy audit only.
ERP_TABLES = frozenset({
    'item_barcodes','items','inventory_batches','suppliers','customers','purchases','purchase_items',
    'expenses','revenues','stock_adjustments','production_logs','transfer_logs',
    'transfer_safety_log','financial_vouchers','treasury_movements','supplier_payments',
    'employees','employee_financial_transactions','document_registry','damaged_stock'})
ERP_FOREIGN_KEYS = {
    'branch_id':'branches','from_branch_id':'branches','to_branch_id':'branches',
    'main_branch_id':'branches','source_branch_id':'branches','item_id':'items',
    'source_item_id':'items','target_item_id':'items','supplier_id':'suppliers',
    'customer_id':'customers','purchase_id':'purchases','transfer_log_id':'transfer_logs',
    'employee_id':'employees','expense_id':'expenses','treasury_id':'treasuries','user_id':'users',
    'created_by':'users','granted_by':'users'}
ERP_NATURAL_KEYS = {
    'item_barcodes':('namespace','barcode'),'items':('branch_id','item_code','item_name'),'suppliers':('supplier_name','phone'),
    'customers':('phone','customer_name'),'users':('username',),'branches':('branch_name',),
    'treasuries':('treasury_type','branch_id'),'purchases':('document_number',),
    'document_registry':('document_number',),'employees':('phone','full_name')}

def _erp_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS erp_changes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,transaction_uuid TEXT NOT NULL,
        table_name TEXT NOT NULL,record_key INTEGER NOT NULL,before_json TEXT,after_json TEXT,actor_id INTEGER,device_id TEXT)""")
    existing={row['name'] for row in conn.execute('PRAGMA table_info(erp_changes)')}
    for column,kind in (('actor_id','INTEGER'),('device_id','TEXT')):
        if column not in existing:conn.execute('ALTER TABLE erp_changes ADD COLUMN '+column+' '+kind)
    conn.execute("""CREATE TABLE IF NOT EXISTS erp_outbox(
        transaction_uuid TEXT PRIMARY KEY,device_id TEXT NOT NULL,actor_id INTEGER,
        payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,source TEXT NOT NULL,
        sync_status TEXT NOT NULL DEFAULT 'pending',sync_error TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        synced_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS erp_id_map(
        table_name TEXT NOT NULL,local_id INTEGER NOT NULL,remote_id INTEGER NOT NULL,
        PRIMARY KEY(table_name,local_id),UNIQUE(table_name,remote_id))""")

def _erp_install_capture(connection):
    raw=connection._conn
    raw.create_function('erp_transaction_uuid',0,lambda:connection._tx_uuid)
    raw.create_function('erp_actor_id',0,lambda:connection._actor_id)
    raw.create_function('erp_device_id',0,lambda:connection._device_id)
    for table in ERP_TABLES:
        columns=[r['name'] for r in raw.execute('PRAGMA table_info("'+table+'")').fetchall()]
        if 'id' not in columns:continue
        def image(alias):
            return 'json_object('+','.join("'"+c+"',"+alias+'."'+c+'"' for c in columns)+')'
        before,after=image('OLD'),image('NEW')
        different=' OR '.join('OLD."'+c+'" IS NOT NEW."'+c+'"' for c in columns)
        for action,old,new,key,condition in (
            ('INSERT','NULL',after,'NEW.id',''),
            ('UPDATE',before,after,'NEW.id',' WHEN '+different),
            ('DELETE',before,'NULL','OLD.id','')):
            raw.execute('CREATE TEMP TRIGGER IF NOT EXISTS "erp_capture_'+table+'_'+action.lower()+'" AFTER '+action+
                ' ON main."'+table+'"'+condition+' BEGIN INSERT INTO erp_changes(transaction_uuid,table_name,record_key,before_json,after_json,actor_id,device_id) '+
                'VALUES(erp_transaction_uuid(),\''+table+'\','+key+','+old+','+new+',erp_actor_id(),erp_device_id()); END;')

def _erp_reference(conn,table,local_id):
    mapped=conn.execute('SELECT remote_id FROM erp_id_map WHERE table_name=? AND local_id=?',(table,local_id)).fetchone()
    reference={'table':table,'local_id':int(local_id)}
    if mapped:reference['remote_id']=int(mapped[0])
    keys=ERP_NATURAL_KEYS.get(table,())
    if keys:
        existing={r['name'] for r in conn.execute('PRAGMA table_info("'+table+'")')}
        selected=[key for key in keys if key in existing]
        if selected:
            row=conn.execute('SELECT '+','.join('"'+key+'"' for key in selected)+' FROM "'+table+'" WHERE id=?',(local_id,)).fetchone()
            if row:reference['identity']={key:_sqlite_value(row[key]) for key in selected}
    return reference

def _erp_flush(connection):
    raw=connection._conn
    records=raw.execute('SELECT * FROM erp_changes WHERE transaction_uuid=? ORDER BY id',(connection._tx_uuid,)).fetchall()
    if not records:return
    events=[]
    for record in records:
        before=json.loads(record['before_json']) if record['before_json'] else None
        after=json.loads(record['after_json']) if record['after_json'] else None
        row=after or before
        references={};before_references={}
        for key,table in ERP_FOREIGN_KEYS.items():
            value=row.get(key)
            if isinstance(value,int) and value>0:references[key]=_erp_reference(raw,table,value)
            old_value=before.get(key) if before else None
            if isinstance(old_value,int) and old_value>0:before_references[key]=_erp_reference(raw,table,old_value)
        identity=_erp_reference(raw,record['table_name'],record['record_key'])
        if before and 'identity' in identity:
            identity['identity']={key:before[key] for key in identity['identity'] if key in before}
        events.append({'table':record['table_name'],'local_id':record['record_key'],
                       'before':before,'after':after,'references':references,'before_references':before_references,
                       'record':identity})
    meta=raw.execute("SELECT value FROM local_meta WHERE key='sync_generation'").fetchone()
    payload={'protocol':1,'transaction_uuid':connection._tx_uuid,'device_id':connection._device_id,
             'actor_id':connection._actor_id,'sync_generation':meta[0] if meta else None,'events':events}
    encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
    digest=__import__('hashlib').sha256(encoded.encode()).hexdigest()
    raw.execute('INSERT INTO erp_outbox(transaction_uuid,device_id,actor_id,payload_json,payload_hash,source) VALUES(?,?,?,?,?,?)',
                (connection._tx_uuid,connection._device_id,connection._actor_id,encoded,digest,'capture'))

def _legacy_erp_event(conn,row):
    """Translate only a bounded parameter grammar; never execute the queued SQL."""
    sql=' '.join(row['sql_text'].strip().rstrip(';').split())
    params=list(json.loads(row['params_json'] or '[]'))
    match=re.fullmatch(r'INSERT INTO ([a-z_]+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)(?: RETURNING id)?',sql,re.I)
    if match:
        table=match[1].lower();columns=[c.strip().strip('"') for c in match[2].split(',')]
        tokens=[v.strip() for v in match[3].split(',')]
        if table not in ERP_TABLES or len(columns)!=len(tokens):raise ValueError('Unsupported legacy insert')
        values={};index=0
        for column,token in zip(columns,tokens):
            if not re.fullmatch('[a-z_][a-z_0-9]*',column,re.I):raise ValueError('Invalid legacy field')
            if token=='?':values[column]=params[index];index+=1
            elif token.upper()=='NULL':values[column]=None
            elif token.upper() in ('CURRENT_TIMESTAMP','CURRENT_DATE'):values[column]=row['created_at'][:10] if token.upper()=='CURRENT_DATE' else row['created_at']
            elif re.fullmatch(r'-?\d+(?:\.\d+)?',token):values[column]=float(token) if '.' in token else int(token)
            elif re.fullmatch(r"'(?:[^']|'')*'",token):values[column]=token[1:-1].replace("''", "'")
            else:raise ValueError('Legacy expression requires review')
        if index!=len(params):raise ValueError('Legacy parameter mismatch')
        if 'id' not in values:
            guards=[];args=[]
            for key,value in values.items():
                guards.append('"'+key+'" IS ?');args.append(value)
            found=conn.execute('SELECT id FROM "'+table+'" WHERE '+' AND '.join(guards)+' LIMIT 2',args).fetchall()
            if len(found)!=1:raise ValueError('Legacy insert identity is ambiguous')
            values['id']=found[0][0]
        local_id=int(values['id'])
        refs={key:_erp_reference(conn,target,value) for key,target in ERP_FOREIGN_KEYS.items() for value in [values.get(key)] if isinstance(value,int) and value>0}
        return {'table':table,'local_id':local_id,'before':None,'after':values,'references':refs,'record':_erp_reference(conn,table,local_id)}
    match=re.fullmatch(r'UPDATE ([a-z_]+) SET ([a-z_]+)\s*=\s*\2\s*([+-])\s*\? WHERE id\s*=\s*\?(?: AND branch_id\s*=\s*\?)?',sql,re.I)
    if match and match[1].lower() in ERP_TABLES and match[2].lower() in ('quantity','remaining_quantity','balance','total_purchases'):
        table,column,sign=match[1].lower(),match[2].lower(),match[3]
        if len(params) not in (2,3):raise ValueError('Legacy parameter mismatch')
        local_id=int(params[1]);before={'id':local_id};after={'id':local_id}
        if len(params)==3:before['branch_id']=after['branch_id']=int(params[2])
        before[column]=0;after[column]=float(params[0])*(1 if sign=='+' else -1)
        return {'table':table,'local_id':local_id,'before':before,'after':after,'references':{},'record':_erp_reference(conn,table,local_id),'legacy_delta':True}
    raise ValueError('Legacy operation needs review; original SQL and parameters retained')

def migrate_legacy_erp_queue():
    conn=get_local_connection(queue_writes=False)
    try:
        groups=conn.execute("SELECT transaction_uuid,MIN(id) first_id FROM sync_queue WHERE sync_status='pending' GROUP BY transaction_uuid ORDER BY first_id").fetchall()
        for group in groups:
            rows=conn.execute("SELECT * FROM sync_queue WHERE transaction_uuid=? AND sync_status='pending' ORDER BY sequence_no,id",(group['transaction_uuid'],)).fetchall()
            if not rows or all(_is_local_settings_sql(row['sql_text']) for row in rows):continue
            try:
                if not group['transaction_uuid']:raise ValueError('Legacy transaction has no immutable identity')
                if conn.execute('SELECT 1 FROM erp_outbox WHERE transaction_uuid=?',(group['transaction_uuid'],)).fetchone():continue
                events=[_legacy_erp_event(conn,row) for row in rows]
                actors={int(e['after'].get('user_id') or e['after'].get('created_by')) for e in events if e['after'] and isinstance(e['after'].get('user_id') or e['after'].get('created_by'),int)}
                # Legacy transactions lacking an actor can only be forwarded by an approved Super_Admin;
                # server-side authorization still applies and never treats SQL as executable.
                actor=next(iter(actors)) if len(actors)==1 else None
                generation=_invoice_sync_generation(conn)
                payload={'protocol':1,'transaction_uuid':group['transaction_uuid'],'device_id':get_device_id(),
                         'actor_id':actor,'sync_generation':generation,'events':events,'legacy':True}
                encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
                digest=__import__('hashlib').sha256(encoded.encode()).hexdigest()
                conn.execute('INSERT INTO erp_outbox(transaction_uuid,device_id,actor_id,payload_json,payload_hash,source) VALUES(?,?,?,?,?,?)',
                             (group['transaction_uuid'],payload['device_id'],actor,encoded,digest,'legacy'))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                conn.execute("UPDATE sync_queue SET sync_error=? WHERE transaction_uuid=? AND sync_status='pending'",(_safe_sync_error(exc)[:500],group['transaction_uuid']))
                conn.commit()
    finally:conn.close()

@serialized_sync
def sync_structured_erp():
    if sync_is_paused():return 0,0
    recover_erp_changes()
    migrate_legacy_erp_queue()
    conn=get_local_connection(queue_writes=False);sent=failed=0
    try:
        pending=conn.execute("SELECT * FROM erp_outbox WHERE sync_status='pending' ORDER BY created_at,rowid").fetchall()
        for row in pending:
            try:
                endpoint='/documents/corrections/apply' if row['source']=='document_correction' else '/sync/erp'
                response=_request_with_auth_retry('POST',endpoint,json=json.loads(row['payload_json']),timeout=30)
                try:response.raise_for_status()
                except Exception:
                    if row['source']=='document_correction':
                        try:detail=response.json().get('detail','تعذر اعتماد الطلب')
                        except ValueError:detail='تعذر اعتماد الطلب'
                        raise ValueError(str(detail.get('message',detail) if isinstance(detail,dict) else detail)) from None
                    raise
                ack=response.json()
                if ack.get('transaction_uuid')!=row['transaction_uuid'] or ack.get('payload_hash')!=row['payload_hash']:
                    raise ValueError('ERP receipt identity/hash mismatch')
                conn.execute('BEGIN IMMEDIATE')
                if row['source']=='document_correction':
                    from views.document_correction_client import store_ack
                    store_ack(conn,ack)
                for mapping in _validated_erp_mappings(ack.get('mappings', [])):
                    if mapping['table'] not in ERP_TABLES:raise ValueError('Invalid ERP mapping')
                    conn.execute('INSERT INTO erp_id_map(table_name,local_id,remote_id) VALUES(?,?,?) ON CONFLICT(table_name,local_id) DO UPDATE SET remote_id=excluded.remote_id',
                                 (mapping['table'],int(mapping['local_id']),int(mapping['remote_id'])))
                conn.execute("UPDATE erp_outbox SET sync_status='synced',sync_error=NULL,synced_at=CURRENT_TIMESTAMP WHERE transaction_uuid=?",(row['transaction_uuid'],))
                conn.execute("UPDATE sync_queue SET sync_status='synced',sync_error=NULL WHERE transaction_uuid=? AND sync_status='pending'",(row['transaction_uuid'],))
                conn.commit();sent+=1
            except Exception as exc:
                conn.rollback();conn.execute('UPDATE erp_outbox SET sync_error=? WHERE transaction_uuid=?',(_safe_sync_error(exc)[:500],row['transaction_uuid']));conn.commit();failed+=1
                # Preserve order: dependent financial/stock operations cannot overtake a failure.
                break
        unresolved=conn.execute("SELECT COUNT(DISTINCT transaction_uuid) FROM sync_queue q WHERE sync_status='pending' AND sync_error IS NOT NULL AND NOT EXISTS(SELECT 1 FROM erp_outbox e WHERE e.transaction_uuid=q.transaction_uuid)").fetchone()[0]
        return sent,failed+int(unresolved)
    finally:conn.close()


def recover_erp_changes():
    """Recover an audited raw-connection commit without replaying any local operation."""
    from types import SimpleNamespace
    conn=get_local_connection(queue_writes=False)
    try:
        groups=conn.execute("""SELECT transaction_uuid,MIN(id) first_id FROM erp_changes c
            WHERE NOT EXISTS(SELECT 1 FROM erp_outbox o WHERE o.transaction_uuid=c.transaction_uuid)
            GROUP BY transaction_uuid ORDER BY first_id""").fetchall()
        for group in groups:
            rows=conn.execute('SELECT actor_id,device_id FROM erp_changes WHERE transaction_uuid=? ORDER BY id',(group['transaction_uuid'],)).fetchall()
            actors={row['actor_id'] for row in rows};devices={row['device_id'] for row in rows}
            if len(actors)!=1 or None in actors or len(devices)!=1 or None in devices:
                continue  # No invented author: preserve the audit rows for explicit reconciliation.
            proxy=SimpleNamespace(_conn=conn._conn,_tx_uuid=group['transaction_uuid'],_actor_id=next(iter(actors)),_device_id=next(iter(devices)))
            _erp_flush(proxy);conn.commit()
    except Exception:
        conn.rollback();raise
    finally:conn.close()


# Local cashier drafts use existing local_meta; never enter invoice/ERP queues.
def sale_draft_scope(conn, branch_id, user_id):
    branch_id, user_id = int(branch_id), int(user_id)
    row = conn.execute("SELECT value FROM local_meta WHERE key='device_id'").fetchone()
    if branch_id <= 0 or user_id <= 0 or not row or not row[0]:
        raise ValueError('تعذر تحديد مالك مسودة البيع والجهاز')
    return {'branch_id': branch_id, 'user_id': user_id, 'device_id': str(row[0])}


def _sale_draft_key(scope):
    return 'pos_sale_draft:v1:' + json.dumps(scope, sort_keys=True, separators=(',', ':'))


def read_sale_draft(conn, scope):
    row = conn.execute('SELECT value FROM local_meta WHERE key=?', (_sale_draft_key(scope),)).fetchone()
    if not row:
        return None
    draft = json.loads(row[0])
    if draft.get('scope') != scope or draft.get('schema') != 1 or draft.get('state') not in ('open', 'completed'):
        raise ValueError('بيانات مسودة البيع غير صالحة؛ يلزم مراجعة الإدارة')
    return draft


def save_sale_draft(conn, scope, cart, expected, original_shift=None):
    """Caller owns BEGIN IMMEDIATE/commit; no financial effects or schema changes."""
    current = read_sale_draft(conn, scope)
    if expected is None:
        if current and current['state'] == 'open':
            raise ValueError('توجد مسودة أحدث؛ أعد تحميلها قبل التعديل')
        draft = {'schema': 1, 'id': str(uuid.uuid4()), 'scope': scope, 'revision': 0,
                 'state': 'open', 'created_at': datetime.now().astimezone().isoformat(),
                 'original_shift': original_shift}
    else:
        if not current or (current['id'], current['revision'], current['state']) != (expected['id'], expected['revision'], 'open'):
            raise ValueError('تغيرت المسودة في نافذة أخرى؛ لم يُستبدل التعديل الأحدث')
        draft = dict(current)
        if (not current.get('cart') or current.get('original_shift') is None) and type(original_shift) is int and original_shift>0:
            draft['original_shift']=original_shift
    # Reject non-JSON/NaN instead of silently changing saved cart values.
    encoded_cart = json.dumps(cart, ensure_ascii=False, allow_nan=False)
    if not isinstance(cart, list):
        raise ValueError('سلة البيع غير صالحة')
    draft.update(cart=json.loads(encoded_cart), revision=draft['revision'] + 1,
                 updated_at=datetime.now().astimezone().isoformat())
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',
                 (_sale_draft_key(scope), json.dumps(draft, ensure_ascii=False, allow_nan=False)))
    return draft


def claim_sale_draft(conn, scope, expected, cart):
    current = read_sale_draft(conn, scope)
    if not expected or not current or current['id'] != expected['id']:
        raise ValueError('لم تُحفظ مسودة هذه السلة؛ أعد المحاولة بعد حفظها')
    if current['state'] == 'completed':
        return current
    if current['revision'] != expected['revision'] or current.get('cart') != cart:
        raise ValueError('تغيرت المسودة؛ حدّث السلة قبل اعتماد البيع')
    if not cart:
        raise ValueError('لا يمكن اعتماد سلة فارغة')
    return current


def complete_sale_draft(conn, scope, draft, invoice_id, print_data):
    current = claim_sale_draft(conn, scope, draft, draft['cart'])
    if current['state'] != 'open':
        raise ValueError('تم اعتماد هذه المسودة من قبل')
    if not conn.execute('SELECT id FROM invoices WHERE id=?', (int(invoice_id),)).fetchone():
        raise ValueError('الفاتورة المرتبطة بالمسودة غير موجودة')
    closed = dict(current, state='completed', invoice_id=int(invoice_id), print_data=print_data,
                  completed_at=datetime.now().astimezone().isoformat())
    encoded = json.dumps(closed, ensure_ascii=False, allow_nan=False)
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',
                 ('pos_sale_draft_closed:v1:' + closed['id'], encoded))
    conn.execute('UPDATE local_meta SET value=? WHERE key=?', (encoded, _sale_draft_key(scope)))
    return closed


@serialized_sync
def reconcile_historical_invoice_receipts(limit=100, force=False):
    """Bounded read-only server checks, including locally synced invoices.

    Existing API proves identity/number/total only, not complete item content.
    No invoice is requeued, marked synced or changed by this diagnostic.
    """
    if type(limit) is not int or not 1<=limit<=100:
        raise ValueError('Historical reconciliation limit must be 1..100')
    if not _current_api_token():return {'state':'authorization_required','checked':0}
    local=get_local_connection(queue_writes=False)
    try:
        meta=dict(local.execute("SELECT key,value FROM local_meta WHERE key IN ('branch_id','history_invoice_cursor','history_invoice_last_attempt')").fetchall())
        branch=str(meta.get('branch_id') or '')
        if not branch.isdigit() or int(branch)<=0:return {'state':'device_branch_unknown','checked':0}
        branch=int(branch);now=_time.time()
        try:last=float(meta.get('history_invoice_last_attempt') or 0)
        except (ValueError,TypeError):last=0
        if not force and 0<=now-last<300:return {'state':'scheduled','checked':0,'needs_review':_historical_review_count(local,'history_invoice:',branch)}
        try:cursor=max(0,int(meta.get('history_invoice_cursor') or 0))
        except (ValueError,TypeError):cursor=0
        rows=local.execute('''SELECT id,offline_uuid,invoice_number,total_amount,sync_status FROM invoices
            WHERE branch_id=? AND id>? AND offline_uuid IS NOT NULL AND offline_uuid<>'' ORDER BY id LIMIT ?''',(branch,cursor,limit)).fetchall()
        local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_invoice_last_attempt',?)",(str(now),));local.commit()
        if not rows:
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_invoice_cursor','0')")
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_invoice_scan_completed',?)",(str(now),));local.commit()
            return {'state':'scan_completed','checked':0,'needs_review':_historical_review_count(local,'history_invoice:',branch),'assurance':'receipt_fields_only'}
        all_ids=list(dict.fromkeys(str(row['offline_uuid']) for row in rows))
        ids=[identity for identity in all_ids if 16<=len(identity)<=80]
        try:
            if ids:
                response=_request_with_auth_retry('POST','/sync/receipts/check',json={'branch_id':branch,'offline_uuids':ids},timeout=8)
                response.raise_for_status();data=response.json()
            else:
                data={'branch_id':branch,'receipts':{},'missing':[],'read_only':True}
            receipts=data.get('receipts');missing=data.get('missing')
            if (type(data.get('branch_id')) is not int or data['branch_id']!=branch or data.get('read_only') is not True
                or not isinstance(receipts,dict) or not isinstance(missing,list)
                or any(not isinstance(x,str) for x in missing)
                or set(receipts)&set(missing) or set(receipts)|set(missing)!=set(ids)
                or any(not isinstance(value,dict) for value in receipts.values())):
                raise ValueError('Invalid historical receipt response')
            states={}
            for row in rows:
                identity=str(row['offline_uuid']);found=receipts.get(identity)
                copies=local.execute('SELECT COUNT(*) FROM invoices WHERE offline_uuid=?',(identity,)).fetchone()[0]
                if identity not in ids:state='local_identity_invalid'
                elif copies!=1:state='local_identity_conflict'
                elif found is None:state='missing_after_local_confirmation' if row['sync_status']=='synced' else 'pending_not_received'
                elif found.get('confirmed') is not True:state='receipt_without_live_invoice'
                elif not _valid_reconciled_invoice(found,row):state='receipt_fields_conflict'
                else:state='receipt_fields_match'
                states[identity]={'invoice_id':int(row['id']),'branch_id':branch,'state':state,'checked_at':now,'assurance':'identity_number_total_only','automatic_repair':False}
            for identity,result in states.items():
                local.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('history_invoice:'+identity,json.dumps(result,ensure_ascii=False,separators=(',',':'))))
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_invoice_cursor',?)",(str(rows[-1]['id']),))
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_invoice_last_success',?)",(str(now),));local.commit()
            return {'state':'checked','checked':len(rows),'needs_review':_historical_review_count(local,'history_invoice:',branch),'assurance':'receipt_fields_only'}
        except Exception as exc:
            local.rollback()
            # No exception body or tokens are persisted. Cursor remains unchanged.
            status=getattr(getattr(exc,'response',None),'status_code',None)
            result={'state':'check_failed','checked':0,'http_status':status if type(status) is int else None,'error_type':type(exc).__name__,'attempted_at':now}
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_invoice_last_error',?)",(json.dumps(result,separators=(',',':')),));local.commit()
            return result
    finally:local.close()


@serialized_sync
def reconcile_historical_erp_receipts(limit=100,force=False):
    """Scan pending AND synced immutable outbox payloads; never resend or edit them."""
    import hashlib
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('ERP receipt limit must be 1..100')
    if not _current_api_token():return {'state':'authorization_required','checked':0}
    local=get_local_connection(queue_writes=False)
    try:
        meta=dict(local.execute("SELECT key,value FROM local_meta WHERE key IN ('branch_id','device_id','history_erp_cursor','history_erp_last_attempt')").fetchall())
        branch=str(meta.get('branch_id') or '');device=str(meta.get('device_id') or '')
        if not branch.isdigit() or int(branch)<=0 or not device:return {'state':'device_scope_unknown','checked':0}
        branch=int(branch);now=_time.time()
        try:last=float(meta.get('history_erp_last_attempt') or 0)
        except (TypeError,ValueError):last=0
        if not force and 0<=now-last<300:return {'state':'scheduled','checked':0,'needs_review':_historical_review_count(local,'history_erp:',branch)}
        try:cursor=max(0,int(meta.get('history_erp_cursor') or 0))
        except (TypeError,ValueError):cursor=0
        rows=local.execute('''SELECT rowid AS scan_id,transaction_uuid,device_id,payload_json,payload_hash,sync_status
            FROM erp_outbox WHERE rowid>? ORDER BY rowid LIMIT ?''',(cursor,limit)).fetchall()
        local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_erp_last_attempt',?)",(str(now),));local.commit()
        if not rows:
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_erp_cursor','0')")
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_erp_scan_completed',?)",(str(now),));local.commit()
            return {'state':'scan_completed','checked':0,'needs_review':_historical_review_count(local,'history_erp:',branch),'assurance':'receipt_hash_only'}
        probes=[];states={}
        for row in rows:
            identity=row['transaction_uuid'];digest=str(row['payload_hash'] or '')
            if row['device_id']!=device:states[identity]='local_device_conflict';continue
            try:
                payload=json.loads(row['payload_json']);encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
                if not isinstance(payload,dict) or payload.get('transaction_uuid')!=identity or payload.get('device_id')!=device:raise ValueError()
                if not 16<=len(identity)<=80 or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError()
                if hashlib.sha256(encoded.encode()).hexdigest()!=digest:raise ValueError()
            except (TypeError,ValueError):states[identity]='local_payload_conflict';continue
            probes.append({'transaction_uuid':identity,'payload_hash':digest})
        try:
            if probes:
                response=_request_with_auth_retry('POST','/sync/erp-receipts/check',json={'branch_id':branch,'probes':probes},timeout=8)
                response.raise_for_status();data=response.json();receipts=data.get('receipts')
                if (type(data.get('branch_id')) is not int or data['branch_id']!=branch or data.get('device_id')!=device
                    or data.get('read_only') is not True or data.get('assurance')!='receipt_hash_only'
                    or not isinstance(receipts,dict) or set(receipts)!={p['transaction_uuid'] for p in probes}
                    or any(value not in ('receipt_hash_match','receipt_hash_conflict','receipt_missing') for value in receipts.values())):
                    raise ValueError('Invalid ERP receipt response')
                states.update(receipts)
            for row in rows:
                identity=row['transaction_uuid'];state=states[identity]
                if state=='receipt_missing':state='missing_after_local_confirmation' if row['sync_status']=='synced' else 'pending_not_received'
                states[identity]=state
                report={'branch_id':branch,'device_id':device,'state':state,'checked_at':now,'assurance':'receipt_hash_only','automatic_repair':False}
                local.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('history_erp:'+identity,json.dumps(report,separators=(',',':'))))
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_erp_cursor',?)",(str(rows[-1]['scan_id']),))
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_erp_last_success',?)",(str(now),));local.commit()
            return {'state':'checked','checked':len(rows),'needs_review':_historical_review_count(local,'history_erp:',branch),'assurance':'receipt_hash_only'}
        except Exception as exc:
            local.rollback();status=getattr(getattr(exc,'response',None),'status_code',None)
            result={'state':'check_failed','checked':0,'http_status':status if type(status) is int else None,'error_type':type(exc).__name__,'attempted_at':now}
            local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('history_erp_last_error',?)",(json.dumps(result,separators=(',',':')),));local.commit();return result
    finally:local.close()



def _historical_review_count(local,prefix,branch_id):
    """Aggregate saved per-operation evidence, not a substitute for comparing it."""
    row=local.execute("""SELECT COUNT(*) FROM local_meta WHERE substr(key,1,?)=? AND
        CASE WHEN NOT json_valid(value) THEN 1
             WHEN json_extract(value,'$.branch_id') IS NOT NULL AND json_extract(value,'$.branch_id')<>? THEN 0
             WHEN json_extract(value,'$.state') IN ('receipt_fields_match','receipt_hash_match','pending_not_received') THEN 0
             ELSE 1 END=1""",(len(prefix),prefix,branch_id)).fetchone()
    return int(row[0])


@serialized_sync
def sync_exception_settlements():
    import hashlib
    """Retain pending effects until a matching durable server receipt arrives."""
    local=get_local_connection(queue_writes=False)
    sent=failed=0
    try:
        from branch_auth import local_device_info
        info=local_device_info();branch=int(info.get('bound_branch_id') or 0);device=get_device_id()
        # Refresh the authority independently from financial snapshots.
        response=_request_with_auth_retry('GET','/sync/settlement-authority',timeout=8)
        response.raise_for_status();data=response.json()
        if data.get('branch_id')!=branch or data.get('device_id')!=device:raise ValueError('Authority response scope mismatch')
        authority=data.get('authority')
        if authority:
            if authority.get('branch_id')!=branch:raise ValueError('Authority branch mismatch')
            local.execute('''INSERT INTO branch_settlement_authorities(branch_id,device_id,authority_uuid,approved_by,approved_at,is_released)
                VALUES(?,?,?,?,?,?) ON CONFLICT(branch_id) DO UPDATE SET device_id=excluded.device_id,authority_uuid=excluded.authority_uuid,
                approved_by=excluded.approved_by,approved_at=excluded.approved_at,is_released=CASE WHEN branch_settlement_authorities.authority_uuid=excluded.authority_uuid THEN max(branch_settlement_authorities.is_released,?) ELSE ? END''',
                tuple(authority[k] for k in ('branch_id','device_id','authority_uuid','approved_by','approved_at'))+(int(authority.get('is_released',0)),int(authority.get('is_released',0)),int(authority.get('is_released',0))))
        else:
            # Never erase existing offline authority blindly; mark a mismatch for review.
            if local.execute('SELECT 1 FROM branch_settlement_authorities WHERE branch_id=?',(branch,)).fetchone():
                raise ValueError('Previously granted settlement authority is absent centrally; administrative review required')
        local.commit()
        rows=local.execute("SELECT * FROM exception_settlements WHERE sync_status='pending' AND device_id=? ORDER BY created_at,settlement_uuid",(device,)).fetchall()
        for row in rows:
            try:
                payload=json.loads(row['payload_json'])
                encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
                if hashlib.sha256(encoded.encode('utf-8')).hexdigest()!=row['payload_hash']:raise ValueError('Local settlement content conflict')
                response=_request_with_auth_retry('POST','/sync/exception-settlement',json=dict(payload,sync_generation=_invoice_sync_generation(local)),timeout=8)
                response.raise_for_status();receipt=response.json()
                if receipt.get('accepted') is not True or receipt.get('settlement_uuid')!=row['settlement_uuid'] or receipt.get('payload_hash')!=row['payload_hash']:
                    raise ValueError('Invalid settlement acknowledgement')
                local.execute("UPDATE exception_settlements SET sync_status='confirmed' WHERE settlement_uuid=? AND payload_hash=?",(row['settlement_uuid'],row['payload_hash']))
                local.commit();sent+=1
            except Exception:
                local.rollback();failed+=1
        return sent,failed
    finally:local.close()


@serialized_sync
def reconcile_historical_content(limit=100):
    """Resumable bidirectional row comparison, including previously synced records.

    Reports differences; never replays history or replaces a newer business row.
    """
    from control_services import RECONCILE_TABLES,reconciliation_columns,reconciliation_digest
    from branch_auth import local_device_info
    import uuid
    local=get_local_connection(queue_writes=False)
    try:
        info=local_device_info();branch=int(info.get('bound_branch_id') or 0);device=get_device_id()
        if not branch:return {'state':'device_branch_unknown','needs_review':1}
        if local.execute("SELECT 1 FROM invoices WHERE sync_status='pending' LIMIT 1").fetchone() or local.execute("SELECT 1 FROM erp_outbox WHERE sync_status='pending' LIMIT 1").fetchone() or local.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():
            return {'state':'pending_local_operations','needs_review':1,'automatic_repair':False}
        key='history_content_cursor:'+str(branch)
        saved=local.execute('SELECT value FROM local_meta WHERE key=?',(key,)).fetchone()
        cursor=json.loads(saved[0]) if saved else {'table_index':0,'after_id':0,'cycle':str(uuid.uuid4())}
        table=RECONCILE_TABLES[cursor['table_index']];columns={r['name'] for r in local.execute('PRAGMA table_info("'+table+'")')}
        fields=reconciliation_columns(columns)
        def report(identity,state,**details):
            evidence={'branch_id':branch,'device_id':device,'table':table,'state':state,'cycle':cursor['cycle'],
                'checked_at':_time.time(),'automatic_repair':False,**details}
            local.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',
                          ('history_content:'+str(branch)+':'+table+':'+str(identity),json.dumps(evidence,ensure_ascii=False)))
        cycle_completed=False
        def advance():
            nonlocal cycle_completed
            cursor['table_index']+=1;cursor['after_id']=0
            if cursor['table_index']>=len(RECONCILE_TABLES):
                cycle_completed=True
                local.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('history_content_cycle_completed:'+str(branch),json.dumps({'cycle':cursor['cycle'],'checked_at':_time.time(),'assurance':'current_business_projection','automatic_repair':False})))
                cursor.update(table_index=0,cycle=str(uuid.uuid4()))
        if not fields:
            report('schema','local_table_unavailable');advance()
        else:
            response=_request_with_auth_retry('POST','/sync/content-reconciliation/page',json={'branch_id':branch,'table':table,'after_id':cursor['after_id'],'limit':max(1,min(int(limit),100)),'columns':fields},timeout=8)
            if response.status_code==403:return {'state':'administrative_authorization_required','needs_review':1}
            response.raise_for_status();data=response.json()
            if data.get('read_only') is not True or data.get('table')!=table:raise ValueError('Invalid content evidence')
            if data.get('state')!='checked':
                report('schema',data.get('state','check_failed'));advance()
            else:
                if data.get('branch_id')!=branch or data.get('device_id')!=device or not set(data.get('fields',[]))<=set(fields):raise ValueError('Content evidence scope mismatch')
                report('schema','schema_gap' if data.get('missing_columns') else 'content_match',missing_columns=data.get('missing_columns',[]))
                for proof in data['rows']:
                    remote=int(proof['remote_id']);identity=proof.get('identity') or {};row=None
                    if table=='invoices':
                        if identity.get('offline_uuid'):row=local.execute('SELECT rowid AS _reconcile_local_id,* FROM invoices WHERE offline_uuid=? AND branch_id=?',(identity['offline_uuid'],branch)).fetchone()
                        elif identity.get('invoice_number'):row=local.execute('SELECT rowid AS _reconcile_local_id,* FROM invoices WHERE invoice_number=? AND branch_id=?',(identity['invoice_number'],branch)).fetchone()
                    elif table=='user_branch_permissions':
                        row=local.execute('SELECT rowid AS _reconcile_local_id,* FROM user_branch_permissions WHERE user_id=? AND branch_id=? AND permission_key=?',tuple(identity.get(k) for k in ('user_id','branch_id','permission_key'))).fetchone()
                    elif table=='shift_closures':
                        row=local.execute('SELECT rowid AS _reconcile_local_id,* FROM shift_closures WHERE branch_id=? AND shift_date=? AND shift_number=?',tuple(identity.get(k) for k in ('branch_id','shift_date','shift_number'))).fetchone()
                    else:
                        mapping=local.execute('SELECT local_id FROM erp_id_map WHERE table_name=? AND remote_id=?',(table,remote)).fetchone()
                        if mapping:row=local.execute('SELECT rowid AS _reconcile_local_id,* FROM "'+table+'" WHERE id=?',(mapping[0],)).fetchone()
                        elif table=='users':row=local.execute('SELECT rowid AS _reconcile_local_id,* FROM users WHERE id=? AND branch_id=?',(remote,branch)).fetchone()

                        if row is None and identity and proof.get('identity_proven') is True:
                            # A proven natural key recovers only a reference, never inventory or money.
                            allowed=set(ERP_NATURAL_KEYS.get(table,()))
                            if allowed and set(identity)==allowed and set(identity)<=columns and all(v is not None and str(v).strip() for v in identity.values()):
                                predicates=' AND '.join('"'+k+'"=?' for k in identity)
                                matches=local.execute('SELECT rowid AS _reconcile_local_id,* FROM "'+table+'" WHERE '+predicates,tuple(identity.values())).fetchall()
                                if len(matches)==1 and ('branch_id' not in columns or int(matches[0]['branch_id'])==branch):
                                    row=matches[0]
                                    existing=local.execute('SELECT remote_id FROM erp_id_map WHERE table_name=? AND local_id=?',(table,row['id'])).fetchone()
                                    reverse=local.execute('SELECT local_id FROM erp_id_map WHERE table_name=? AND remote_id=?',(table,remote)).fetchone()
                                    if (existing and int(existing[0])!=remote) or (reverse and int(reverse[0])!=int(row['id'])):row=None
                                    else:local.execute('INSERT OR IGNORE INTO erp_id_map(table_name,local_id,remote_id) VALUES(?,?,?)',(table,row['id'],remote))

                    if row is None:
                        report(remote,'central_record_missing_locally',remote_id=remote);continue
                    image=dict(row);unresolved=[]

                    if table=='invoices' and image.get('notes'):
                        details=json.loads(image['notes'])
                        for entry in details.get('items',[]):
                            mapping=local.execute("SELECT remote_id FROM erp_id_map WHERE table_name='items' AND local_id=?",(entry.get('id'),)).fetchone()
                            if mapping:entry['id']=mapping[0]
                        image['notes']=details

                    for field,reference_table in ERP_FOREIGN_KEYS.items():
                        if field not in data['fields'] or image.get(field) is None or reference_table in ('users','branches'):continue
                        mapping=local.execute('SELECT remote_id FROM erp_id_map WHERE table_name=? AND local_id=?',(reference_table,image[field])).fetchone()
                        if mapping:image[field]=mapping[0]
                        else:unresolved.append(field)
                    state=('reference_identity_unverified' if unresolved else 'schema_gap' if data.get('missing_columns') else
                           'content_match' if reconciliation_digest(image,data['fields'])==proof['digest'] else 'content_differs_review')
                    report(remote,state,remote_id=remote,source_local_id=row['_reconcile_local_id'],unresolved_fields=unresolved,missing_columns=data.get('missing_columns',[]))
                    report('local-'+str(row['_reconcile_local_id']),state,source_local_id=row['_reconcile_local_id'])
                    local.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('history_content_seen:'+cursor['cycle']+':'+table+':'+str(row['_reconcile_local_id']),'1'))
                if data['complete']:
                    if 'branch_id' in columns:scope='branch_id=?';args=(branch,)
                    elif table=='purchase_items':scope='purchase_id IN (SELECT id FROM purchases WHERE branch_id=?)';args=(branch,)
                    elif 'from_branch_id' in columns and 'to_branch_id' in columns:scope='from_branch_id=? OR to_branch_id=?';args=(branch,branch)
                    else:scope='1=0';args=() # No guessed scope for global/legacy records.
                    for row in local.execute('SELECT rowid AS local_row FROM "'+table+'" WHERE '+scope,args).fetchall():
                        seen=local.execute('SELECT 1 FROM local_meta WHERE key=?',('history_content_seen:'+cursor['cycle']+':'+table+':'+str(row['local_row']),)).fetchone()
                        if not seen:report('local-'+str(row['local_row']),'local_record_missing_or_unmapped_centrally',source_local_id=row['local_row'])
                    advance()
                else:cursor['after_id']=data['next_id']
        local.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(key,json.dumps(cursor)));local.commit()
        needs=local.execute("SELECT COUNT(*) FROM local_meta WHERE key LIKE ? AND json_extract(value,'$.state')<>'content_match'",('history_content:'+str(branch)+':%',)).fetchone()[0]
        if cycle_completed and not needs:
            local.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('history_content_last_complete_match:'+str(branch),str(_time.time())));local.commit()
        last=local.execute('SELECT value FROM local_meta WHERE key=?',('history_content_last_complete_match:'+str(branch),)).fetchone()
        return {'state':'checked','table':table,'needs_review':int(needs),'cycle_completed':cycle_completed,'last_complete_match':last[0] if last else None,'assurance':'current_business_projection','automatic_repair':False}
    except Exception as exc:
        local.rollback();return {'state':'check_failed','needs_review':1,'error_type':type(exc).__name__,'automatic_repair':False}
    finally:local.close()


@serialized_sync
def sync_exception_targets():
    """Cache exception evidence only; never create invoices or replay their stock."""
    import copy
    from decimal import Decimal
    local=get_local_connection(queue_writes=False)
    try:
        if local.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():
            return {'state':'pending_settlements','downloaded':0}
        device=get_device_id()
        authority=local.execute('SELECT * FROM branch_settlement_authorities WHERE device_id=? AND is_released=0',(device,)).fetchone()
        if not authority:return {'state':'not_authorized_device','downloaded':0}
        saved=local.execute("SELECT value FROM local_meta WHERE key='exception_target_cursor'").fetchone();cursor=int(saved[0]) if saved else 0
        response=_request_with_auth_retry('GET','/sync/exception-targets',params={'after_id':cursor},timeout=8)
        response.raise_for_status();data=response.json()
        if data.get('branch_id')!=authority['branch_id'] or data.get('device_id')!=device or data.get('authority_uuid')!=authority['authority_uuid']:
            raise ValueError('Exception evidence authority mismatch')
        local.execute('BEGIN IMMEDIATE')
        # Recheck after the network wait; a manager may have created an offline request.
        if local.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():
            local.rollback();return {'state':'pending_settlements','downloaded':0}
        downloaded=0
        for target in data['targets']:
            if target['branch_id']!=authority['branch_id']:raise ValueError('Exception target branch mismatch')
            if local.execute('SELECT 1 FROM invoices WHERE offline_uuid=?',(target['offline_uuid'],)).fetchone():continue
            exceptions=[]
            for source in target['exceptions']:
                mapping=local.execute("SELECT local_id FROM erp_id_map WHERE table_name='items' AND remote_id=?",(source['item_id'],)).fetchone()
                if not mapping:raise ValueError('Central item has no proven local identity')
                exception=copy.deepcopy(source);exception['item_id']=int(mapping[0])
                rows=local.execute("SELECT quantity FROM exception_settlements WHERE invoice_identity=? AND item_id=? AND sync_status='confirmed'",(target['offline_uuid'],mapping[0])).fetchall()
                known=sum((Decimal(str(r['quantity'])) for r in rows),Decimal(0));settled=Decimal(str(source['central_settled_qty']))
                if settled<known:raise ValueError('Central settlement ledger lost locally confirmed data')
                exception['surplus_baseline_qty']=str(settled-known)
                exception['surplus_adjustment_qty']=float(settled)
                exception['surplus_remaining_qty']=float(Decimal(str(source['shortfall_qty']))-settled)
                exception['surplus_adjustment_done']=exception['surplus_remaining_qty']==0
                exceptions.append(exception)
            old=local.execute('SELECT notes FROM branch_exception_cache WHERE id=?',(target['id'],)).fetchone()
            if old:
                previous=json.loads(old['notes'])
                for exception in exceptions:
                    for prior in previous.get('stock_exceptions',[]):
                        if prior.get('item_id')==exception['item_id']:
                            for key in ('review_status','reviewed_by','reviewed_at'):
                                if key in prior:exception[key]=prior[key]
            notes=json.dumps({'stock_exceptions':exceptions,'_invoice_number':target.get('invoice_number') or target['offline_uuid']},ensure_ascii=False)
            local.execute('''INSERT INTO branch_exception_cache(id,branch_id,user_id,offline_uuid,notes,branch_name,username,authority_uuid)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET notes=excluded.notes,authority_uuid=excluded.authority_uuid''',
                (target['id'],target['branch_id'],target['user_id'],target['offline_uuid'],notes,target['branch_name'],target['username'],authority['authority_uuid']))
            downloaded+=1
        local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('exception_target_cursor',?)",(str(0 if data['complete'] else data['next_id']),))
        local.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('exception_target_unresolved',?)",(json.dumps(data['unresolved']),))
        local.commit();return {'state':'checked','downloaded':downloaded,'unresolved':len(data['unresolved'])}
    except Exception:
        local.rollback();raise
    finally:local.close()


def local_display_scope(role,requested_branch=None):
    """A branch terminal displays its enrolled scope, never leftover other-branch rows."""
    if role in ('Super_Admin','Admin','Manager'):
        return None  # Management retains existing cross-branch permissions.
    c=get_local_connection(queue_writes=False)
    try:
        meta=dict(c.execute("SELECT key,value FROM local_meta WHERE key IN ('bound_branch_id','bound_device_id','device_id')").fetchall())
        branch=int(meta.get('bound_branch_id') or 0)
        if branch<=0 or not meta.get('device_id') or meta.get('bound_device_id')!=meta.get('device_id'):
            raise PermissionError('تعذر تحديد نطاق الجهاز المعتمد')
        if requested_branch is not None and int(requested_branch)!=branch:
            raise PermissionError('فرع الجلسة لا يطابق فرع الجهاز')
        row=c.execute('SELECT branch_type FROM branches WHERE id=?',(branch,)).fetchone()
        if row and row[0]=='مخزن رئيسي' and role in ('Super_Admin','Admin','Manager','General_Supervisor'):
            return None
        return (branch,)
    finally:c.close()


@serialized_sync
def send_device_heartbeat():
    """Reachability is not enrollment or upload success. Send only the bound device."""
    c=get_local_connection(queue_writes=False)
    try:
        meta=dict(c.execute("SELECT key,value FROM local_meta WHERE key IN ('bound_branch_id','bound_device_id','device_id','device_active','server_enrolled')").fetchall())
        device=get_device_id();branch=int(meta.get('bound_branch_id') or 0)
        if branch<=0 or meta.get('bound_device_id')!=device or meta.get('device_active')!='1' or meta.get('server_enrolled')!='1':
            return {'accepted':False,'state':'device_not_enrolled'}
        pending=int(c.execute("SELECT COUNT(*) FROM invoices WHERE sync_status<>'synced'").fetchone()[0])
        operations=int(c.execute("SELECT COUNT(*) FROM erp_outbox WHERE sync_status='pending'").fetchone()[0])
        operations+=int(c.execute("SELECT COUNT(*) FROM sync_queue WHERE sync_status='pending'").fetchone()[0])
        operations+=int(c.execute("SELECT COUNT(*) FROM exception_settlements WHERE sync_status='pending'").fetchone()[0])
        response=_request_with_auth_retry('POST','/sync/device-heartbeat',json={'device_id':device,'branch_id':branch,'pending_invoices':pending,'pending_operations':operations},timeout=5)
        response.raise_for_status();data=response.json()
        if data.get('accepted') is not True:raise ValueError('Heartbeat not acknowledged')
        c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('last_device_heartbeat',?)",(str(_time.time()),));c.commit()
        return {'accepted':True,'state':'accepted'}
    except Exception as exc:
        c.rollback();status=getattr(getattr(exc,'response',None),'status_code',None)
        return {'accepted':False,'state':'failed','http_status':status if isinstance(status,int) else None,'error_type':type(exc).__name__}
    finally:c.close()


def _number_range_key(branch_id, slot):
    return 'invoice_numbers:'+str(int(branch_id))+':'+slot


def _read_number_range(conn, branch_id, slot='current'):
    row = conn.execute('SELECT value FROM local_meta WHERE key=?', (_number_range_key(branch_id,slot),)).fetchone()
    if not row:
        return None
    data = json.loads(row[0])
    meta = dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('device_id','sync_generation')").fetchall())
    if (data.get('device_id') != meta.get('device_id') or data.get('sync_generation') != meta.get('sync_generation')
            or data.get('branch_id') != int(branch_id)
            or data.get('prefix') not in ('B', '')
            or (data.get('prefix') == '' and data.get('number_format') != 'fixed_v1')):
        raise ValueError('اعتماد نطاق أرقام الفواتير لا يطابق الجهاز الحالي')
    return data


def _format_reserved_invoice_number(data, branch_id):
    # Empty prefix is enabled only by an explicit server reservation contract.
    prefix = data.get('prefix')
    if prefix not in ('B', '') or (prefix == '' and data.get('number_format') != 'fixed_v1'):
        raise ValueError('Unsupported invoice numbering contract')
    if (type(data.get('next')) is not int or type(data.get('end')) is not int
            or not 0 < data['next'] <= data['end']):
        raise ValueError('Invoice number reservation exhausted')
    return prefix + str(int(branch_id)).zfill(2) + '-' + str(data['next']).zfill(6)


def _validate_invoice_ack(data, invoice):
    remote_id = data.get('remote_invoice_id')
    if type(remote_id) is not int or remote_id <= 0:
        raise ValueError('Server did not confirm a valid invoice ID')
    expected = str(invoice['invoice_number'] or '')
    # New fixed numbers require an explicit matching acknowledgement.
    if ('invoice_number' in data or re.fullmatch(r'\d{2,}-\d{6,}', expected)):
        if data.get('invoice_number') != expected:
            raise ValueError('Server invoice number differs; local number was preserved')
    if 'offline_uuid' in data and data['offline_uuid'] != invoice['offline_uuid']:
        raise ValueError('Server invoice identity differs')
    return remote_id


def claim_windows_invoice_number(conn, branch_id):
    if not conn.in_transaction:
        raise ValueError('Invoice number must be claimed inside the sale transaction')
    data = _read_number_range(conn, branch_id)
    if not data or data['next'] > data['end']:
        data = _read_number_range(conn, branch_id, 'spare')
        if not data or data['next'] > data['end']:
            raise ValueError('يلزم اتصال لتجهيز أرقام فواتير جديدة؛ السلة محفوظة ولم تُحفظ مبيعات ناقصة')
        conn.execute('DELETE FROM local_meta WHERE key=?', (_number_range_key(branch_id,'spare'),))
    number = _format_reserved_invoice_number(data, branch_id)
    if conn.execute('SELECT 1 FROM invoices WHERE invoice_number=?', (number,)).fetchone():
        raise ValueError('رقم الفاتورة مستخدم؛ لم تُحفظ الفاتورة مرتين')
    data['next'] += 1
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)', (_number_range_key(branch_id,'current'),json.dumps(data,separators=(',',':'))))
    return number


@serialized_sync
def ensure_invoice_number_range():
    c = get_local_connection(queue_writes=False)
    try:
        meta = dict(c.execute("SELECT key,value FROM local_meta WHERE key IN ('bound_branch_id','device_id','sync_generation','setup_complete')").fetchall())
        branch = int(meta.get('bound_branch_id') or 0)
        if branch <= 0 or meta.get('setup_complete') != '1' or not meta.get('sync_generation'):
            return {'ready':False}
        current = _read_number_range(c,branch)
        spare = _read_number_range(c,branch,'spare')
        usable_spare = bool(spare and spare['next'] <= spare['end'])
        legacy_retry = c.execute("SELECT value FROM local_meta WHERE key='invoice_format_retry_after'").fetchone()
        if (current and current['next'] <= current['end'] and current.get('prefix') == 'B'
                and legacy_retry and _time.time() < float(legacy_retry[0])):
            return {'ready':True,'legacy_server':True}
        if current and current.get('number_format') == 'fixed_v1' and (current['end']-current['next'] >= 1000 or usable_spare):
            return {'ready':True}
        c.execute('BEGIN IMMEDIATE')
        key = _number_range_key(branch,'request')
        old = c.execute('SELECT value FROM local_meta WHERE key=?',(key,)).fetchone()
        request_id = old[0] if old else str(uuid.uuid4())
        c.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(key,request_id));c.commit()
        response = _request_with_auth_retry('POST','/sync/invoice-number-range',json={'branch_id':branch,'request_uuid':request_id,'sync_generation':meta['sync_generation'],'number_format':'fixed_v1'},timeout=8)
        response.raise_for_status();data=response.json()
        if (data.get('branch_id') != branch or data.get('device_id') != meta['device_id']
            or data.get('request_uuid') != request_id or data.get('sync_generation') != meta['sync_generation']
            or data.get('prefix') not in ('B', '')
            or (data.get('prefix') == '' and data.get('number_format') != 'fixed_v1')
            or type(data.get('start')) is not int or type(data.get('end')) is not int
            or not 0 < data['start'] <= data['end']):
            raise ValueError('Invalid invoice number reservation acknowledgement')
        data['next']=data['start']
        c.execute('BEGIN IMMEDIATE')
        # Recheck after the network call: a sale may have consumed current numbers.
        current=_read_number_range(c,branch)
        if data.get('prefix') == 'B':
            c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('invoice_format_retry_after',?)",(str(_time.time()+300),))
            old_spare=_read_number_range(c,branch,'spare')
            if current and old_spare and old_spare['next'] <= old_spare['end']:
                history='legacy_ack:'+request_id
                c.execute('INSERT OR IGNORE INTO local_meta(key,value) VALUES(?,?)',(_number_range_key(branch,history),json.dumps(data,separators=(',',':'))))
                c.execute('DELETE FROM local_meta WHERE key=?',(key,))
                c.commit()
                return {'ready':True,'legacy_server':True}
        if data.get('number_format') == 'fixed_v1' and current and current.get('number_format') != 'fixed_v1':
            # Park unused legacy reservations only after a verified fixed ACK.
            # Already-issued/pending invoices keep their original numbers.
            for legacy_slot in ('current', 'spare'):
                legacy = _read_number_range(c, branch, legacy_slot)
                if legacy:
                    history = 'legacy:' + legacy_slot + ':' + str(legacy.get('request_uuid') or legacy.get('start'))
                    c.execute('INSERT OR IGNORE INTO local_meta(key,value) VALUES(?,?)',
                              (_number_range_key(branch,history),json.dumps(legacy,separators=(',',':'))))
                    c.execute('DELETE FROM local_meta WHERE key=?',(_number_range_key(branch,legacy_slot),))
            current = None
        slot='current' if not current else 'spare'
        existing=_read_number_range(c,branch,slot)
        if existing and existing.get('request_uuid')==request_id:
            pass  # A restored/repeated acknowledgement never rewinds the counter.
        elif slot=='spare' and existing and existing['next'] <= existing['end']:
            raise ValueError('An unused spare reservation is already present')
        else:
            c.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(_number_range_key(branch,slot),json.dumps(data,separators=(',',':'))))
        c.execute('DELETE FROM local_meta WHERE key=?',(key,));c.commit()
        return {'ready':True}
    except Exception:
        c.rollback();raise
    finally:c.close()


@serialized_sync
def sync_branch_reset_commands():
    """Receive all resets in sequence; unlock financial writes only after ACKs."""
    from views.branch_reset_client import apply_command
    from views.branch_reset_plan import normalized
    c=get_local_connection(queue_writes=False)
    try:meta=dict(c.execute("SELECT key,value FROM local_meta WHERE key IN ('device_id','bound_branch_id','sync_generation','setup_complete','branch_reset_guard')"))
    finally:c.close()
    device_id=meta.get('device_id');branch_id=int(meta.get('bound_branch_id') or 0)
    if not device_id or branch_id<=0:return {'ok':True,'applied':0}
    def fetch():
        response=_request_with_auth_retry('GET','/sync/branch-resets',timeout=12)
        response.raise_for_status();return response.json()
    try:data=fetch()
    except Exception as error:
        return {'ok':not bool(meta.get('branch_reset_guard')),'applied':0,'error':_safe_sync_error(error)}
    if data.get('device_id')!=device_id or data.get('branch_id')!=branch_id or not isinstance(data.get('commands'),list):return {'ok':False,'error':'أمر تصفير خارج هوية الجهاز أو الفرع'}
    head=data.get('head');commands=data['commands']
    if not head:
        return {'ok':not bool(meta.get('branch_reset_guard')),'applied':0}
    if head.get('branch_id')!=branch_id:return {'ok':False,'error':'حالة تصفير خارج الفرع'}
    if not commands and not meta.get('branch_reset_guard') and meta.get('sync_generation')==head['generation']:return {'ok':True,'applied':0}
    if not commands and meta.get('setup_complete')!='1' and not meta.get('sync_generation'):
        c=get_local_connection(queue_writes=False)
        try:
            has_history=c.execute('SELECT 1 FROM invoices WHERE branch_id=? LIMIT 1',(branch_id,)).fetchone()
            if not has_history:return {'ok':True,'applied':0,'fresh_device':True}
        finally:c.close()
    previous_seq=0
    for command in commands:
        if (command.get('device_id')!=device_id or command.get('branch_id')!=branch_id or type(command.get('reset_seq')) is not int or not previous_seq<command['reset_seq']<=head['reset_seq']):return {'ok':False,'error':'تسلسل أمر تصفير غير صالح'}
        normalized(command['choices']);previous_seq=command['reset_seq']
    c=get_local_connection(queue_writes=False)
    try:
        c.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('branch_reset_guard',?)",(json.dumps(head),));c.commit()
    finally:c.close()
    installed=int(json.loads(Path(__file__).with_name('APP_VERSION.json').read_text(encoding='utf-8-sig')).get('release_seq',0))
    applied=0
    for command in commands:
        c=get_local_connection(queue_writes=False)
        try:
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='erp_changes'").fetchone():
                # Seal pre-reset audit captures into their ORIGINAL generation
                # before changing local_meta; never reconstruct them as new work.
                recover_erp_changes()
                if c.execute('SELECT 1 FROM erp_changes e WHERE NOT EXISTS(SELECT 1 FROM erp_outbox o WHERE o.transaction_uuid=e.transaction_uuid) LIMIT 1').fetchone():
                    raise ValueError('توجد حركات قديمة غير محددة الهوية؛ لم تُحذف ويلزم مراجعة Super Admin')
            if 'sql_text' in {r[1] for r in c.execute('PRAGMA table_info(sync_queue)')}:
                migrate_legacy_erp_queue()
            c.execute('BEGIN IMMEDIATE')
            applied+=int(apply_command(c,command,device_id,branch_id,installed));c.commit()
        except Exception as error:
            c.rollback();message=_safe_sync_error(error)
            try:_request_with_auth_retry('POST','/sync/branch-reset-ack',json={'reset_id':command['reset_id'],'generation':command['generation'],'status':'failed','error':message[:500]},timeout=12).raise_for_status()
            except Exception:pass
            return {'ok':False,'applied':applied,'error':message}
        finally:c.close()
    c=get_local_connection(queue_writes=False)
    try:
        generation=c.execute("SELECT value FROM local_meta WHERE key='sync_generation'").fetchone()
        if not generation or generation[0]!=head['generation']:return {'ok':False,'error':'لا يوجد أمر موثق يطابق جيل الفرع؛ يلزم مراجعة Super Admin'}
    finally:c.close()
    ok,error=sync_reference_data()
    if not ok:return {'ok':False,'applied':applied,'error':error}
    if meta.get('setup_complete')=='1':
        try:
            if not ensure_invoice_number_range().get('ready'):return {'ok':False,'applied':applied,'error':'لم يكتمل تجهيز أرقام الفواتير للجيل الجديد'}
        except Exception as error:return {'ok':False,'applied':applied,'error':_safe_sync_error(error)}
    try:
        current=fetch()
        if not current.get('head') or current['head']['generation']!=head['generation']:return {'ok':False,'error':'وصل أمر أحدث؛ يُستكمل في المزامنة التالية'}
        for command in commands:
            response=_request_with_auth_retry('POST','/sync/branch-reset-ack',json={'reset_id':command['reset_id'],'generation':command['generation'],'status':'applied'},timeout=12);response.raise_for_status();receipt=response.json()
            if receipt.get('reset_id')!=command['reset_id'] or receipt.get('status')!='applied':raise ValueError('لم يؤكد السيرفر إيصال تطبيق التصفير')
    except Exception as error:return {'ok':False,'applied':applied,'error':_safe_sync_error(error)}
    c=get_local_connection(queue_writes=False)
    try:c.execute("DELETE FROM local_meta WHERE key='branch_reset_guard'");c.commit()
    finally:c.close()
    return {'ok':True,'applied':applied}


def cache_replacement_history(conn,history):
    if history is None:return
    meta=dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('device_id','bound_branch_id')"))
    if history.get('source')!='central_committed_only' or history.get('device_id')!=meta.get('device_id') or str(history.get('branch_id'))!=str(meta.get('bound_branch_id')):raise ValueError('تاريخ الاستبدال لا يطابق الجهاز والفرع؛ لم يتغير شيء')
    seen=set();sources=set(history['source_device_ids'])
    if meta['device_id'] in sources:raise ValueError('لا يُنسب تاريخ الجهاز السابق إلى البديل')
    for row in history['invoices']:
        if row['branch_id']!=history['branch_id'] or row['source_device_id'] not in sources or row['remote_id'] in seen:raise ValueError('تاريخ فواتير غير صالح أو مكرر')
        seen.add(row['remote_id'])
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',('replacement_history:'+str(history['branch_id']),json.dumps(history,ensure_ascii=False)))


def device_registration_is_blocked():
    """Read the explicit registration fence only; no network or data mutation."""
    if not LOCAL_DB.exists():return False
    from contextlib import closing
    with closing(sqlite3.connect(LOCAL_DB.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_meta'").fetchone():return False
        return c.execute("SELECT 1 FROM local_meta WHERE key='device_registration_blocked'").fetchone() is not None


def _reference_fence(conn):
    row=conn.execute("SELECT COUNT(*),COALESCE(MAX(id),0),COALESCE(SUM(total_amount),0),COALESCE(SUM(CASE WHEN sync_status='synced' THEN 1 ELSE 0 END),0) FROM invoices").fetchone()
    return tuple(row)+(conn.execute('SELECT COUNT(*) FROM erp_outbox').fetchone()[0],)
