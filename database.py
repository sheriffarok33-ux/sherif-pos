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
