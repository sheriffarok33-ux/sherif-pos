import streamlit as st
import psycopg2
from psycopg2.extras import DictCursor


# ============================================================
# القوائم الافتراضية للنظام
# ============================================================

DEFAULT_MENUS = [
    "🏠 الرئيسية واللوحة",
    "🛒 نقطة البيع (POS)",
    "⭐ لوحة المفضلة (1-20)",
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
# طبقة توافق SQLite -> PostgreSQL
# ============================================================

def _convert_query(query):
    """
    تحويل بعض أوامر SQLite المستخدمة في المشروع
    إلى الصيغة المناسبة لـ PostgreSQL.
    """

    # SQLite يستخدم ? بينما PostgreSQL يستخدم %s
    query = query.replace("?", "%s")

    # تحويل INSERT OR IGNORE
    upper_query = query.upper()

    if "INSERT OR IGNORE INTO" in upper_query:
        query = query.replace(
            "INSERT OR IGNORE INTO",
            "INSERT INTO"
        )

        query = query.replace(
            "insert or ignore into",
            "INSERT INTO"
        )

        # إضافة ON CONFLICT DO NOTHING
        if "ON CONFLICT" not in query.upper():
            query = query.rstrip().rstrip(";")
            query += " ON CONFLICT DO NOTHING"

    return query


class PostgreSQLCursor:
    """
    Cursor متوافق قدر الإمكان مع طريقة SQLite
    المستخدمة في بقية ملفات المشروع.
    """

    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None

    def execute(self, query, params=None):

        query = _convert_query(query)

        if params is None:
            params = ()

        # ----------------------------------------------------
        # invoices تحتاج lastrowid في شاشة نقطة البيع
        # ----------------------------------------------------

        is_invoice_insert = (
            query.strip().upper().startswith("INSERT INTO INVOICES")
            and "RETURNING" not in query.upper()
        )

        if is_invoice_insert:
            query = query.rstrip().rstrip(";")
            query += " RETURNING id"

            self._cursor.execute(query, params)

            row = self._cursor.fetchone()

            if row:
                self.lastrowid = row[0]

            return self

        # ----------------------------------------------------
        # باقي الاستعلامات
        # ----------------------------------------------------

        self._cursor.execute(query, params)

        return self

    def executemany(self, query, params_list):

        query = _convert_query(query)

        self._cursor.executemany(query, params_list)

        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):

        if size is None:
            return self._cursor.fetchmany()

        return self._cursor.fetchmany(size)

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def close(self):
        self._cursor.close()

    def __iter__(self):
        return iter(self._cursor)


class PostgreSQLConnection:
    """
    Wrapper يسمح لبقية ملفات المشروع باستخدام:

        conn.execute(...)
        conn.cursor()
        conn.commit()
        conn.rollback()

    بنفس الأسلوب القديم تقريباً.
    """

    def __init__(self, connection):
        self._connection = connection

    def cursor(self):
        return PostgreSQLCursor(
            self._connection.cursor(
                cursor_factory=DictCursor
            )
        )

    def execute(self, query, params=None):

        cursor = self.cursor()

        cursor.execute(query, params)

        return cursor

    def executemany(self, query, params_list):

        cursor = self.cursor()

        cursor.executemany(query, params_list)

        return cursor

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    # مهم لبعض المكتبات مثل pandas
    def __getattr__(self, name):
        return getattr(self._connection, name)


# ============================================================
# الاتصال بقاعدة Supabase PostgreSQL
# ============================================================

def get_db_connection():

    try:

        pg = st.secrets["postgres"]

        raw_connection = psycopg2.connect(
            host=pg["host"],
            port=int(pg.get("port", 5432)),
            dbname=pg.get("dbname", "postgres"),
            user=pg["user"],
            password=pg["password"],
            sslmode=pg.get("sslmode", "require"),
            connect_timeout=15
        )

        return PostgreSQLConnection(raw_connection)

    except Exception as e:

        raise RuntimeError(
            f"تعذر الاتصال بقاعدة بيانات PostgreSQL: {e}"
        )


# ============================================================
# النسخ الاحتياطي
# ============================================================

def create_desktop_backup():
    """
    لم نعد ننسخ ملف SQLite محلياً.

    البيانات الآن محفوظة في PostgreSQL / Supabase
    خارج سيرفر Streamlit.
    """
    return


# ============================================================
# إنشاء الجداول
# ============================================================

def initialize_database():

    conn = get_db_connection()

    cursor = conn.cursor()

    try:

        # ====================================================
        # الفروع
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS branches (
                id SERIAL PRIMARY KEY,
                branch_name TEXT UNIQUE NOT NULL,
                branch_type TEXT DEFAULT 'فرع'
            )
        """)

        # ====================================================
        # المستخدمون
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL,
                phone TEXT,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                branch_id INTEGER,
                allowed_branches TEXT DEFAULT 'ALL',
                custom_permissions TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,

                FOREIGN KEY (branch_id)
                REFERENCES branches(id)
                ON DELETE SET NULL
            )
        """)

        # ====================================================
        # الأصناف والمخزون
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                item_code TEXT,

                item_name TEXT NOT NULL,

                quantity DOUBLE PRECISION DEFAULT 0.0,

                buy_price DOUBLE PRECISION DEFAULT 0.0,

                sale_price DOUBLE PRECISION NOT NULL,

                avg_cost DOUBLE PRECISION DEFAULT 0.0,

                expiry_date TEXT DEFAULT '',

                no_expiry INTEGER DEFAULT 0,

                favorite_rank INTEGER DEFAULT 0,

                FOREIGN KEY (branch_id)
                REFERENCES branches(id)
                ON DELETE CASCADE
            )
        """)

        # ====================================================
        # الموردون
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id SERIAL PRIMARY KEY,

                supplier_name TEXT UNIQUE NOT NULL,

                phone TEXT,

                balance DOUBLE PRECISION DEFAULT 0.0
            )
        """)

        # ====================================================
        # العملاء الآجلون
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,

                customer_name TEXT NOT NULL,

                phone TEXT UNIQUE NOT NULL,

                total_purchases DOUBLE PRECISION DEFAULT 0.0,

                balance DOUBLE PRECISION DEFAULT 0.0,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ====================================================
        # المشتريات
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                supplier_id INTEGER,

                supplier_name TEXT,

                invoice_number TEXT,

                total_cost DOUBLE PRECISION,

                payment_type TEXT DEFAULT 'كاش',

                items_details TEXT,

                invoice_date TEXT,

                FOREIGN KEY (branch_id)
                REFERENCES branches(id)
                ON DELETE CASCADE
            )
        """)

        # ====================================================
        # تحويلات وتزويد الفروع
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transfer_logs (
                id SERIAL PRIMARY KEY,

                from_branch_id INTEGER,

                to_branch_id INTEGER,

                transfer_type TEXT,

                items_details TEXT,

                status TEXT DEFAULT 'مكتملة',

                transfer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ====================================================
        # المصروفات
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                amount DOUBLE PRECISION NOT NULL,

                description TEXT NOT NULL,

                is_general_store INTEGER DEFAULT 0,

                expense_date TEXT
            )
        """)

        # ====================================================
        # الفواتير والمبيعات
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                user_id INTEGER,

                customer_name TEXT DEFAULT 'زبون نقدي',

                customer_phone TEXT DEFAULT '',

                total_amount DOUBLE PRECISION,

                payment_method TEXT DEFAULT 'كاش',

                notes TEXT,

                shift_status TEXT DEFAULT 'open',

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ====================================================
        # تسويات المخزون
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock_adjustments (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER NOT NULL,

                item_id INTEGER,

                item_name TEXT NOT NULL,

                quantity DOUBLE PRECISION NOT NULL,

                adjustment_type TEXT NOT NULL,

                loss_or_gain_value DOUBLE PRECISION NOT NULL,

                notes TEXT,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (branch_id)
                REFERENCES branches(id)
            )
        """)

        # ====================================================
        # سجل البيع بالسالب
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS negative_sales_logs (
                id SERIAL PRIMARY KEY,

                branch_id INTEGER,

                user_id INTEGER,

                item_name TEXT,

                sale_qty DOUBLE PRECISION,

                log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ====================================================
        # صلاحيات الرتب
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS role_permissions (
                role TEXT PRIMARY KEY,

                allowed_menus TEXT
            )
        """)

        # ====================================================
        # أسماء القوائم المخصصة
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS custom_labels (
                original_name TEXT PRIMARY KEY,

                custom_name TEXT NOT NULL
            )
        """)

        # ====================================================
        # سجل النشاط
        # ====================================================

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_logs (
                id SERIAL PRIMARY KEY,

                user_id INTEGER,

                action TEXT,

                details TEXT,

                log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ====================================================
        # الصلاحيات الافتراضية
        # ====================================================

        cursor.execute("""
            INSERT INTO role_permissions
            (role, allowed_menus)

            VALUES (%s, %s)

            ON CONFLICT (role)
            DO NOTHING
        """, (
            "Admin",
            ",".join(DEFAULT_MENUS)
        ))

        cursor.execute("""
            INSERT INTO role_permissions
            (role, allowed_menus)

            VALUES (%s, %s)

            ON CONFLICT (role)
            DO NOTHING
        """, (
            "General_Supervisor",
            ",".join(DEFAULT_MENUS)
        ))

        cursor.execute("""
            INSERT INTO role_permissions
            (role, allowed_menus)

            VALUES (%s, %s)

            ON CONFLICT (role)
            DO NOTHING
        """, (
            "Cashier",
            "🏠 الرئيسية واللوحة,"
            "🛒 نقطة البيع (POS),"
            "🔄 تزويد الفروع والأرشيف"
        ))

        # ====================================================
        # الفروع الافتراضية
        # ====================================================

        cursor.execute(
            "SELECT COUNT(*) FROM branches"
        )

        branch_count = cursor.fetchone()[0]

        if branch_count == 0:

            default_branches = [

                ("المخزن الرئيسي", "مخزن"),

                ("فرع الجزيرة", "فرع"),

                ("فرع 2", "فرع")
            ]

            for branch_name, branch_type in default_branches:

                cursor.execute("""
                    INSERT INTO branches
                    (branch_name, branch_type)

                    VALUES (%s, %s)

                    ON CONFLICT (branch_name)
                    DO NOTHING
                """, (
                    branch_name,
                    branch_type
                ))

        # ====================================================
        # حساب Admin الافتراضي
        # ====================================================

        cursor.execute("""
            SELECT COUNT(*)

            FROM users

            WHERE role = 'Admin'
            AND is_active = 1
        """)

        admin_count = cursor.fetchone()[0]

        if admin_count == 0:

            cursor.execute("""
                INSERT INTO users
                (
                    username,
                    phone,
                    password,
                    role,
                    allowed_branches,
                    is_active
                )

                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
            """, (
                "admin",
                "0910000000",
                "123456",
                "Admin",
                "ALL",
                1
            ))

        # ====================================================
        # حفظ جميع التغييرات
        # ====================================================

        conn.commit()

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()


# ============================================================
# تشغيل الملف منفرداً
# ============================================================

if __name__ == "__main__":

    initialize_database()

    print(
        "✅ تم الاتصال بـ Supabase PostgreSQL "
        "وتهيئة قاعدة البيانات بنجاح."
    )
