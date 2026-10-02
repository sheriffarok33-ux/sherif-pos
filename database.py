import streamlit as st
import psycopg2
from psycopg2 import pool
from psycopg2.extras import DictCursor
import threading
import re


# ============================================================
# القوائم الافتراضية
# ============================================================

DEFAULT_MENUS = [
    "🏠 الرئيسية واللوحة",
    "🛒 نقطة البيع (POS)",
    "📦 إدارة المخزن والفروع",
    "➕ الفائض والتوالف والمرتجعات وتعديل السعر",
    "🔄 تزويد الفروع والأرشيف",
    "🏢 إدارة الفروع",
    "📁 استيراد Excel",
    "💰 المصروفات",
    "📥 المشتريات والموردين",
    "⚙️ الجرد والتصفير السنوي",
    "🥜 التحميص والخلط",
    "📊 التقارير والأرباح",
    "👥 إدارة المستخدمين"
]


# ============================================================
# Connection Pool
# ============================================================

_POOL = None
_POOL_LOCK = threading.Lock()


def _get_pool():

    global _POOL

    if _POOL is not None:
        return _POOL

    with _POOL_LOCK:

        if _POOL is not None:
            return _POOL

        pg = st.secrets["postgres"]

        _POOL = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,

            host=pg["host"],
            port=int(
                pg.get(
                    "port",
                    5432
                )
            ),

            dbname=pg.get(
                "dbname",
                "postgres"
            ),

            user=pg["user"],
            password=pg["password"],

            sslmode=pg.get(
                "sslmode",
                "require"
            ),

            connect_timeout=10,

            application_name=(
                "abu_zaid_pos"
            )
        )

    return _POOL


# ============================================================
# تحويل SQLite SQL إلى PostgreSQL
# ============================================================

def _convert_query(query):

    if not isinstance(query, str):
        return query

    # --------------------------------------------------------
    # INSERT OR IGNORE
    # --------------------------------------------------------

    query = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        query,
        flags=re.IGNORECASE
    )

    # --------------------------------------------------------
    # تحويل ? إلى %s
    #
    # مهم:
    # لا نستخدم replace العادي لأننا نريد المحافظة
    # على النصوص داخل علامات الاقتباس.
    # --------------------------------------------------------

    result = []

    in_single_quote = False
    in_double_quote = False

    i = 0

    while i < len(query):

        char = query[i]

        # -----------------------------------------------
        # single quoted string
        # -----------------------------------------------

        if (
            char == "'"
            and not in_double_quote
        ):

            # PostgreSQL escape ''
            if (
                in_single_quote
                and i + 1 < len(query)
                and query[i + 1] == "'"
            ):

                result.append("''")
                i += 2
                continue

            in_single_quote = (
                not in_single_quote
            )

            result.append(char)

            i += 1
            continue

        # -----------------------------------------------
        # double quoted identifier
        # -----------------------------------------------

        if (
            char == '"'
            and not in_single_quote
        ):

            if (
                in_double_quote
                and i + 1 < len(query)
                and query[i + 1] == '"'
            ):

                result.append('""')
                i += 2
                continue

            in_double_quote = (
                not in_double_quote
            )

            result.append(char)

            i += 1
            continue

        # -----------------------------------------------
        # placeholder
        # -----------------------------------------------

        if (
            char == "?"
            and not in_single_quote
            and not in_double_quote
        ):

            result.append("%s")

        else:

            result.append(char)

        i += 1

    query = "".join(result)

    # --------------------------------------------------------
    # psycopg2 يعتبر % علامة formatting حتى داخل LIKE.
    #
    # لذلك:
    # LIKE '%تالف%'
    # تصبح:
    # LIKE '%%تالف%%'
    #
    # لكن لا نلمس %s الخاصة بالـ placeholders.
    # --------------------------------------------------------

    protected = "__ABU_ZAID_PARAM__"

    query = query.replace(
        "%s",
        protected
    )

    query = query.replace(
        "%",
        "%%"
    )

    query = query.replace(
        protected,
        "%s"
    )

    # --------------------------------------------------------
    # INSERT OR IGNORE -> ON CONFLICT DO NOTHING
    # --------------------------------------------------------

    original_upper = query.upper()

    # نعرف من النص الأصلي بعد re.sub:
    # لو المستخدم كان كاتب OR IGNORE فلن يبقى موجوداً.
    # لذلك نستخدم فحص بسيط قبل التحويل في المستقبل.
    # هذا الجزء للتوافق مع الاستعلامات الموجودة.
    # --------------------------------------------------------

    return query


def _prepare_query(query):

    if not isinstance(query, str):
        return query

    had_insert_or_ignore = bool(
        re.search(
            r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
            query,
            flags=re.IGNORECASE
        )
    )

    converted = _convert_query(
        query
    )

    if (
        had_insert_or_ignore
        and "ON CONFLICT" not in converted.upper()
    ):

        converted = (
            converted.rstrip()
            .rstrip(";")
            + " ON CONFLICT DO NOTHING"
        )

    return converted


# ============================================================
# Cursor Wrapper
# ============================================================

class PostgreSQLCursor:

    def __init__(self, cursor):

        self._cursor = cursor

        self.lastrowid = None


    def execute(
        self,
        query,
        params=None
    ):

        query = _prepare_query(
            query
        )

        if params is None:
            params = ()

        # ====================================================
        # توافق lastrowid
        #
        # نضيف RETURNING فقط لو الكود القديم لم يكتبه.
        # ====================================================

        stripped = query.strip()

        is_insert = (
            stripped.upper().startswith(
                "INSERT INTO "
            )
        )

        supports_lastrowid = False

        if is_insert:

            match = re.match(
                r"INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)",
                stripped,
                flags=re.IGNORECASE
            )

            if match:

                table_name = (
                    match.group(1).lower()
                )

                supports_lastrowid = (
                    table_name
                    in {
                        "invoices",
                        "items"
                    }
                )

        has_returning = (
            "RETURNING" in stripped.upper()
        )

        # ----------------------------------------------------
        # الكود القديم يحتاج lastrowid
        # ----------------------------------------------------

        if (
            supports_lastrowid
            and not has_returning
        ):

            query = (
                query.rstrip()
                .rstrip(";")
                + " RETURNING id"
            )

            self._cursor.execute(
                query,
                params
            )

            row = self._cursor.fetchone()

            if row:
                self.lastrowid = row[0]

            return self

        # ----------------------------------------------------
        # RETURNING مكتوب بالفعل
        # لا نسحب النتيجة هنا حتى يقدر الكود يعمل fetchone()
        # ----------------------------------------------------

        self._cursor.execute(
            query,
            params
        )

        return self


    def executemany(
        self,
        query,
        params_list
    ):

        query = _prepare_query(
            query
        )

        self._cursor.executemany(
            query,
            params_list
        )

        return self


    def fetchone(self):

        return self._cursor.fetchone()


    def fetchall(self):

        return self._cursor.fetchall()


    def fetchmany(
        self,
        size=None
    ):

        if size is None:

            return self._cursor.fetchmany()

        return self._cursor.fetchmany(
            size
        )


    @property
    def description(self):

        return self._cursor.description


    @property
    def rowcount(self):

        return self._cursor.rowcount


    def close(self):

        try:
            self._cursor.close()
        except Exception:
            pass


    def __iter__(self):

        return iter(
            self._cursor
        )


# ============================================================
# Connection Wrapper
# ============================================================

class PostgreSQLConnection:

    def __init__(
        self,
        raw_connection,
        connection_pool
    ):

        self._connection = (
            raw_connection
        )

        self._pool = (
            connection_pool
        )

        self._closed = False


    def cursor(self):

        return PostgreSQLCursor(
            self._connection.cursor(
                cursor_factory=DictCursor
            )
        )


    def execute(
        self,
        query,
        params=None
    ):

        cursor = self.cursor()

        try:

            cursor.execute(
                query,
                params
            )

            return cursor

        except Exception:

            cursor.close()
            raise


    def executemany(
        self,
        query,
        params_list
    ):

        cursor = self.cursor()

        try:

            cursor.executemany(
                query,
                params_list
            )

            return cursor

        except Exception:

            cursor.close()
            raise


    def commit(self):

        self._connection.commit()


    def rollback(self):

        self._connection.rollback()


    def close(self):

        if self._closed:
            return

        self._closed = True

        try:

            # لو الصفحة قرأت بيانات فقط ولم تعمل commit،
            # PostgreSQL قد يترك transaction مفتوحة.
            # rollback آمن قبل إعادة الاتصال للـ pool.
            if not self._connection.closed:

                self._connection.rollback()

        except Exception:
            pass

        try:

            self._pool.putconn(
                self._connection
            )

        except Exception:

            try:
                self._connection.close()
            except Exception:
                pass


    def __enter__(self):

        return self


    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback
    ):

        if exc_type is not None:

            try:
                self.rollback()
            except Exception:
                pass

        self.close()


    def __getattr__(
        self,
        name
    ):

        return getattr(
            self._connection,
            name
        )


# ============================================================
# الحصول على اتصال
# ============================================================

def get_db_connection():

    try:

        db_pool = _get_pool()

        raw_connection = (
            db_pool.getconn()
        )

        if (
            raw_connection is None
            or raw_connection.closed
        ):

            raise RuntimeError(
                "لم يتم الحصول على اتصال صالح."
            )

        # ----------------------------------------------------
        # تنظيف أي transaction قديمة
        # ----------------------------------------------------

        try:
            raw_connection.rollback()
        except Exception:
            pass

        return PostgreSQLConnection(
            raw_connection,
            db_pool
        )

    except Exception as e:

        raise RuntimeError(
            "تعذر الاتصال بقاعدة بيانات "
            f"PostgreSQL: {e}"
        )



# ============================================================
# ضمان جداول الموارد البشرية HR
# ============================================================

def ensure_hr_schema():
    """
    ينشئ/يضمن جداول HR بشكل مستقل عن initialize_database().
    آمن للاستدعاء عند كل فتح لشاشة الموظفين.
    """
    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS employees
            (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE,
                full_name TEXT NOT NULL,
                phone TEXT,
                address TEXT,
                emergency_name TEXT,
                emergency_phone TEXT,
                emergency_relation TEXT,
                branch_id INTEGER NOT NULL,
                monthly_salary DOUBLE PRECISION DEFAULT 0,
                hire_date DATE NOT NULL DEFAULT CURRENT_DATE,
                termination_date DATE,
                employment_status TEXT DEFAULT 'active',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE RESTRICT
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS employee_financial_transactions
            (
                id BIGSERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                transaction_type TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL DEFAULT 0,
                payroll_year INTEGER,
                payroll_month INTEGER,
                work_days INTEGER,
                month_days INTEGER,
                base_salary DOUBLE PRECISION DEFAULT 0,
                notes TEXT,
                expense_id INTEGER,
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE RESTRICT,
                FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE RESTRICT,
                FOREIGN KEY (expense_id) REFERENCES expenses(id) ON DELETE SET NULL,
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_employees_branch
            ON employees(branch_id)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_employee_financial_employee_date
            ON employee_financial_transactions(employee_id, created_at)
            """
        )

        conn.commit()

    except Exception:
        if conn:
            conn.rollback()
        raise

    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            conn.close()


# ============================================================
# النسخ الاحتياطي
# ============================================================

def create_desktop_backup():

    # البيانات لم تعد في ملف SQLite محلي.
    return


# ============================================================
# إنشاء الجداول
# ============================================================

def initialize_database():

    conn = None
    cursor = None

    try:

        conn = get_db_connection()

        cursor = conn.cursor()

        # ====================================================
        # الفروع
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS branches
            (
                id SERIAL PRIMARY KEY,

                branch_name TEXT
                    UNIQUE NOT NULL,

                branch_type TEXT
                    DEFAULT 'فرع'
            )
            """
        )

        # ====================================================
        # المستخدمون
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users
            (
                id SERIAL PRIMARY KEY,

                username TEXT NOT NULL,

                phone TEXT,

                password TEXT NOT NULL,

                role TEXT NOT NULL,

                branch_id INTEGER,

                allowed_branches TEXT
                    DEFAULT 'ALL',

                custom_permissions TEXT
                    DEFAULT '',

                is_active INTEGER
                    DEFAULT 1,

                FOREIGN KEY (branch_id)
                    REFERENCES branches(id)
                    ON DELETE SET NULL
            )
            """
        )

        # ====================================================
        # الأصناف
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS items
            (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                item_code TEXT,

                item_name TEXT NOT NULL,

                quantity DOUBLE PRECISION
                    DEFAULT 0.0,

                buy_price DOUBLE PRECISION
                    DEFAULT 0.0,

                sale_price DOUBLE PRECISION
                    NOT NULL,

                avg_cost DOUBLE PRECISION
                    DEFAULT 0.0,

                expiry_date TEXT
                    DEFAULT '',

                no_expiry INTEGER
                    DEFAULT 0,

                favorite_rank INTEGER
                    DEFAULT 0,

                FOREIGN KEY (branch_id)
                    REFERENCES branches(id)
                    ON DELETE CASCADE
            )
            """
        )

        # ====================================================
        # وحدات الأصناف ودفعات الصلاحية
        # ====================================================

        cursor.execute(
            """
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS unit_type TEXT DEFAULT 'piece'
            """
        )

        cursor.execute(
            """
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS pieces_per_carton INTEGER DEFAULT 1
            """
        )

        cursor.execute(
            """
            UPDATE items
            SET unit_type = 'piece'
            WHERE unit_type IS NULL OR TRIM(unit_type) = ''
            """
        )

        cursor.execute(
            """
            UPDATE items
            SET pieces_per_carton = 1
            WHERE pieces_per_carton IS NULL
               OR pieces_per_carton < 1
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_batches
            (
                id BIGSERIAL PRIMARY KEY,
                item_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                quantity NUMERIC DEFAULT 0,
                remaining_quantity NUMERIC DEFAULT 0,
                received_date DATE DEFAULT CURRENT_DATE,
                expiry_date DATE,
                unit_cost NUMERIC DEFAULT 0,
                source_type TEXT DEFAULT 'inventory',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (item_id)
                    REFERENCES items(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (branch_id)
                    REFERENCES branches(id)
                    ON DELETE CASCADE
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_inventory_batches_expiry
            ON inventory_batches(branch_id, expiry_date)
            """
        )

        # ====================================================
        # الموردون
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS suppliers
            (
                id SERIAL PRIMARY KEY,

                supplier_name TEXT
                    UNIQUE NOT NULL,

                phone TEXT,

                balance DOUBLE PRECISION
                    DEFAULT 0.0
            )
            """
        )

        # ====================================================
        # العملاء
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS customers
            (
                id SERIAL PRIMARY KEY,

                customer_name TEXT
                    NOT NULL,

                phone TEXT
                    UNIQUE NOT NULL,

                total_purchases
                    DOUBLE PRECISION
                    DEFAULT 0.0,

                balance DOUBLE PRECISION
                    DEFAULT 0.0,

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ====================================================
        # المشتريات
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS purchases
            (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                supplier_id INTEGER,

                supplier_name TEXT,

                invoice_number TEXT,

                total_cost DOUBLE PRECISION,

                payment_type TEXT
                    DEFAULT 'كاش',

                items_details TEXT,

                invoice_date TEXT,

                FOREIGN KEY (branch_id)
                    REFERENCES branches(id)
                    ON DELETE CASCADE
            )
            """
        )

        # ====================================================
        # تحويلات الفروع
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS transfer_logs
            (
                id SERIAL PRIMARY KEY,

                from_branch_id INTEGER,

                to_branch_id INTEGER,

                transfer_type TEXT,

                items_details TEXT,

                status TEXT
                    DEFAULT 'مكتملة',

                transfer_date TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ====================================================
        # المصروفات
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses
            (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                amount DOUBLE PRECISION
                    NOT NULL,

                description TEXT
                    NOT NULL,

                is_general_store INTEGER
                    DEFAULT 0,

                expense_date TEXT
            )
            """
        )

        # ====================================================
        # الإيرادات اليدوية
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS revenues
            (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                revenue_source TEXT
                    NOT NULL,

                amount DOUBLE PRECISION
                    NOT NULL,

                notes TEXT,

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (branch_id)
                    REFERENCES branches(id)
                    ON DELETE SET NULL
            )
            """
        )

        # ====================================================
        # ترقيات جدول الإيرادات للتوافق مع الشاشات الحالية
        # ====================================================

        cursor.execute(
            """
            ALTER TABLE revenues
            ADD COLUMN IF NOT EXISTS
                description TEXT
            """
        )

        cursor.execute(
            """
            ALTER TABLE revenues
            ADD COLUMN IF NOT EXISTS
                revenue_date TEXT
            """
        )

        cursor.execute(
            """
            UPDATE revenues
            SET description = COALESCE(
                NULLIF(description, ''),
                NULLIF(notes, ''),
                NULLIF(revenue_source, ''),
                'إيراد'
            )
            WHERE description IS NULL
               OR description = ''
            """
        )

        cursor.execute(
            """
            UPDATE revenues
            SET revenue_date =
                COALESCE(
                    NULLIF(revenue_date, ''),
                    created_at::date::text
                )
            WHERE revenue_date IS NULL
               OR revenue_date = ''
            """
        )

        # ====================================================
        # الفواتير
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS invoices
            (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                user_id INTEGER,

                customer_name TEXT
                    DEFAULT 'زبون نقدي',

                customer_phone TEXT
                    DEFAULT '',

                total_amount DOUBLE PRECISION,

                payment_method TEXT
                    DEFAULT 'كاش',

                notes TEXT,

                shift_status TEXT
                    DEFAULT 'open',

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ====================================================
        # تسويات المخزون
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_adjustments
            (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER
                    NOT NULL,

                item_id INTEGER,

                item_name TEXT
                    NOT NULL,

                quantity DOUBLE PRECISION
                    NOT NULL,

                adjustment_type TEXT
                    NOT NULL,

                loss_or_gain_value
                    DOUBLE PRECISION
                    NOT NULL
                    DEFAULT 0.0,

                notes TEXT,

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (branch_id)
                    REFERENCES branches(id)
            )
            """
        )

        # ====================================================
        # سجل البيع بالسالب
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS negative_sales_logs
            (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                user_id INTEGER,

                item_name TEXT,

                sale_qty DOUBLE PRECISION,

                log_time TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ====================================================
        # سجل عمليات التحميص والخلط
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS production_logs
            (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                operation_type TEXT
                    NOT NULL,

                source_details TEXT,

                target_item_id INTEGER,

                target_item_name TEXT,

                input_weight DOUBLE PRECISION
                    DEFAULT 0.0,

                output_weight DOUBLE PRECISION
                    DEFAULT 0.0,

                loss_weight DOUBLE PRECISION
                    DEFAULT 0.0,

                total_cost DOUBLE PRECISION
                    DEFAULT 0.0,

                unit_cost DOUBLE PRECISION
                    DEFAULT 0.0,

                notes TEXT,

                created_at TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (branch_id)
                    REFERENCES branches(id)
                    ON DELETE SET NULL
            )
            """
        )

        # ====================================================
        # ترقيات سجل الإنتاج للتوافق مع الخلط والتحميص والتقارير
        # ====================================================
        # توافق قواعد البيانات القديمة مع كود الإنتاج الحديث
        cursor.execute(
            """
            ALTER TABLE production_logs
            ALTER COLUMN operation_type DROP NOT NULL
            """
        )


        production_columns = [
            ("production_type", "TEXT"),
            ("source_item_id", "INTEGER"),
            ("source_item_name", "TEXT"),
            ("input_quantity", "DOUBLE PRECISION DEFAULT 0.0"),
            ("output_quantity", "DOUBLE PRECISION DEFAULT 0.0"),
            ("loss_quantity", "DOUBLE PRECISION DEFAULT 0.0"),
            ("sale_price", "DOUBLE PRECISION DEFAULT 0.0")
        ]

        for column_name, column_type in production_columns:
            cursor.execute(
                f"""
                ALTER TABLE production_logs
                ADD COLUMN IF NOT EXISTS
                    {column_name} {column_type}
                """
            )

        cursor.execute(
            """
            UPDATE production_logs
            SET production_type =
                COALESCE(
                    NULLIF(production_type, ''),
                    operation_type
                )
            WHERE production_type IS NULL
               OR production_type = ''
            """
        )

        cursor.execute(
            """
            UPDATE production_logs
            SET input_quantity = COALESCE(input_weight, 0)
            WHERE COALESCE(input_quantity, 0) = 0
              AND COALESCE(input_weight, 0) <> 0
            """
        )

        cursor.execute(
            """
            UPDATE production_logs
            SET output_quantity = COALESCE(output_weight, 0)
            WHERE COALESCE(output_quantity, 0) = 0
              AND COALESCE(output_weight, 0) <> 0
            """
        )

        cursor.execute(
            """
            UPDATE production_logs
            SET loss_quantity = COALESCE(loss_weight, 0)
            WHERE COALESCE(loss_quantity, 0) = 0
              AND COALESCE(loss_weight, 0) <> 0
            """
        )

        # ====================================================
        # أرشيف السنوات المالية
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS financial_year_archives
            (
                id SERIAL PRIMARY KEY,
                financial_year INTEGER UNIQUE NOT NULL,
                closed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                closed_by INTEGER,
                closed_by_username TEXT,
                summary_json TEXT,
                FOREIGN KEY (closed_by)
                    REFERENCES users(id)
                    ON DELETE SET NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS financial_year_archive_rows
            (
                id BIGSERIAL PRIMARY KEY,
                archive_id INTEGER NOT NULL,
                source_table TEXT NOT NULL,
                source_row_id TEXT,
                row_data TEXT NOT NULL,
                archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (archive_id)
                    REFERENCES financial_year_archives(id)
                    ON DELETE CASCADE
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_financial_archive_rows_archive
            ON financial_year_archive_rows(archive_id)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_financial_archive_rows_table
            ON financial_year_archive_rows(
                archive_id,
                source_table
            )
            """
        )

        # ====================================================
        # HR المصغرة: الموظفون والرواتب والسلف
        # ====================================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE SET NULL,
                full_name TEXT NOT NULL, phone TEXT, address TEXT,
                emergency_name TEXT, emergency_phone TEXT, emergency_relation TEXT,
                branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
                monthly_salary DOUBLE PRECISION DEFAULT 0,
                hire_date DATE NOT NULL DEFAULT CURRENT_DATE,
                termination_date DATE, employment_status TEXT DEFAULT 'active',
                notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS employee_financial_transactions (
                id BIGSERIAL PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
                branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
                transaction_type TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL DEFAULT 0,
                payroll_year INTEGER, payroll_month INTEGER,
                work_days INTEGER, month_days INTEGER,
                base_salary DOUBLE PRECISION DEFAULT 0,
                notes TEXT, expense_id INTEGER REFERENCES expenses(id) ON DELETE SET NULL,
                created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_employees_branch ON employees(branch_id)")
        cursor.execute("""CREATE INDEX IF NOT EXISTS idx_employee_financial_employee_date
                          ON employee_financial_transactions(employee_id, created_at)""")

        # ====================================================
        # صلاحيات الرتب
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS role_permissions
            (
                role TEXT PRIMARY KEY,

                allowed_menus TEXT
            )
            """
        )

        # ====================================================
        # أسماء القوائم
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS custom_labels
            (
                original_name TEXT
                    PRIMARY KEY,

                custom_name TEXT
                    NOT NULL
            )
            """
        )

        # ====================================================
        # إعدادات مظهر النظام
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings
            (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ====================================================
        # سجل النشاط
        # ====================================================

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_logs
            (
                id SERIAL PRIMARY KEY,

                user_id INTEGER,

                action TEXT,

                details TEXT,

                log_time TIMESTAMP
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # ====================================================
        # Indexes للأداء
        # ====================================================

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_items_branch
            ON items(branch_id)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_items_branch_code
            ON items(branch_id, item_code)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_invoices_branch_created
            ON invoices(branch_id, created_at)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_expenses_branch_date
            ON expenses(branch_id, expense_date)
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_adjustments_branch_created
            ON stock_adjustments(
                branch_id,
                created_at
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_transfer_to_date
            ON transfer_logs(
                to_branch_id,
                transfer_date
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_purchases_branch_date
            ON purchases(
                branch_id,
                invoice_date
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_revenues_branch_date
            ON revenues(
                branch_id,
                revenue_date
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_production_branch_created
            ON production_logs(
                branch_id,
                created_at
            )
            """
        )

        # ====================================================
        # الصلاحيات الافتراضية
        # ====================================================

        default_roles = {
            "Admin":
                ",".join(
                    DEFAULT_MENUS
                ),

            "General_Supervisor":
                ",".join(
                    DEFAULT_MENUS
                ),

            "Cashier":
                (
                    "🏠 الرئيسية واللوحة,"
                    "🛒 نقطة البيع (POS),"
                    "🔄 تزويد الفروع والأرشيف"
                )
        }

        for role, menus in (
            default_roles.items()
        ):

            cursor.execute(
                """
                INSERT INTO role_permissions
                (
                    role,
                    allowed_menus
                )
                VALUES (?, ?)
                ON CONFLICT (role)
                DO NOTHING
                """,
                (
                    role,
                    menus
                )
            )

        # ====================================================
        # الفروع الافتراضية
        # ====================================================

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM branches
            """
        )

        branch_count = (
            cursor.fetchone()[0]
        )

        if branch_count == 0:

            default_branches = [
                (
                    "المخزن الرئيسي",
                    "مخزن"
                ),
                (
                    "فرع الجزيرة",
                    "فرع"
                ),
                (
                    "فرع 2",
                    "فرع"
                )
            ]

            for (
                branch_name,
                branch_type
            ) in default_branches:

                cursor.execute(
                    """
                    INSERT INTO branches
                    (
                        branch_name,
                        branch_type
                    )
                    VALUES (?, ?)
                    ON CONFLICT (branch_name)
                    DO NOTHING
                    """,
                    (
                        branch_name,
                        branch_type
                    )
                )

        # ====================================================
        # Admin الافتراضي
        # ====================================================

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE role = 'Admin'
              AND is_active = 1
            """
        )

        admin_count = (
            cursor.fetchone()[0]
        )

        if admin_count == 0:

            cursor.execute(
                """
                INSERT INTO users
                (
                    username,
                    phone,
                    password,
                    role,
                    allowed_branches,
                    is_active
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "admin",
                    "0910000000",
                    "123456",
                    "Admin",
                    "ALL",
                    1
                )
            )

        conn.commit()

    except Exception:

        if conn:
            conn.rollback()

        raise

    finally:

        if cursor:

            try:
                cursor.close()
            except Exception:
                pass

        if conn:
            conn.close()


# ============================================================
# تشغيل مباشر
# ============================================================

if __name__ == "__main__":

    initialize_database()

    print(
        "✅ PostgreSQL / Supabase جاهز."
    )
