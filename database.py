import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

# مفتاح التبديل: اجعله "postgres" ليعمل مباشرة على سحابة Supabase التي أنشأناها
DB_TYPE = os.getenv("DB_TYPE", "postgres") 
SQLITE_DB_NAME = "abu_zaid_new_system.db"

# رابط الاتصال بقاعدة بيانات Supabase السحابية مع ترميز الرمز الخاص في كلمة المرور
POSTGRES_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://postgres:Saif_Sherif%401690@db.xuorffwqftrbxguqpucx.supabase.co:5432/postgres"
)

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

def get_db_connection():
    """دالة لإنشاء اتصال بقاعدة البيانات وإرجاعه (تدعم SQLite و PostgreSQL)"""
    if DB_TYPE == "postgres":
        conn = psycopg2.connect(POSTGRES_URL, cursor_factory=RealDictCursor)
        return conn
    else:
        conn = sqlite3.connect(SQLITE_DB_NAME, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

def reindex_table(conn, table_name):
    """إعادة ترقيم الـ ID تلقائياً (مخصص لـ SQLite المحلي، وفي بوستجريس يدار تلقائياً عبر SERIAL)"""
    if DB_TYPE == "postgres":
        return 
    
    cursor = conn.cursor()
    try:
        if table_name == "branches":
            rows = cursor.execute("SELECT branch_name, branch_type FROM branches ORDER BY id ASC").fetchall()
            cursor.execute("DELETE FROM branches")
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='branches'")
            for row in rows:
                cursor.execute("INSERT INTO branches (branch_name, branch_type) VALUES (?, ?)", (row[0], row[1]))
                
        elif table_name == "users":
            rows = cursor.execute("SELECT username, phone, password, role, branch_id, allowed_branches, custom_permissions, is_active FROM users ORDER BY id ASC").fetchall()
            cursor.execute("DELETE FROM users")
            cursor.execute("DELETE FROM sqlite_sequence WHERE name='users'")
            for row in rows:
                cursor.execute("INSERT INTO users (username, phone, password, role, branch_id, allowed_branches, custom_permissions, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)
                
        conn.commit()
    except Exception as e:
        print(f"Error re-indexing {table_name}: {e}")

def initialize_database():
    """دالة لإنشاء الجداول الأساسية للنظام وإدخال البيانات الافتراضية"""
    conn = get_db_connection()
    cursor = conn.cursor()

    if DB_TYPE == "postgres":
        # --- جداول PostgreSQL السحابية ---
        cursor.execute("CREATE TABLE IF NOT EXISTS branches (id SERIAL PRIMARY KEY, branch_name VARCHAR(255) UNIQUE NOT NULL, branch_type VARCHAR(100) DEFAULT 'فرع');")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) NOT NULL,
                phone VARCHAR(100),
                password VARCHAR(255) NOT NULL,
                role VARCHAR(100) NOT NULL,
                branch_id INT REFERENCES branches(id) ON DELETE SET NULL,
                allowed_branches TEXT DEFAULT 'ALL',
                custom_permissions TEXT DEFAULT '',
                is_active INT DEFAULT 1
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id SERIAL PRIMARY KEY,
                branch_id INT REFERENCES branches(id) ON DELETE CASCADE,
                item_code VARCHAR(255),
                item_name VARCHAR(255) NOT NULL,
                quantity FLOAT DEFAULT 0.0,
                buy_price FLOAT DEFAULT 0.0,
                sale_price FLOAT NOT NULL,
                avg_cost FLOAT DEFAULT 0.0,
                expiry_date VARCHAR(50) DEFAULT '',
                no_expiry INT DEFAULT 0,
                favorite_rank INT DEFAULT 0
            );
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS suppliers (id SERIAL PRIMARY KEY, supplier_name VARCHAR(255) UNIQUE NOT NULL, phone VARCHAR(100), balance FLOAT DEFAULT 0.0);")
        cursor.execute("CREATE TABLE IF NOT EXISTS customers (id SERIAL PRIMARY KEY, customer_name VARCHAR(255) NOT NULL, phone VARCHAR(100) UNIQUE NOT NULL, total_purchases FLOAT DEFAULT 0.0, balance FLOAT DEFAULT 0.0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY,
                branch_id INT REFERENCES branches(id) ON DELETE CASCADE,
                supplier_id INT,
                supplier_name VARCHAR(255),
                invoice_number VARCHAR(255),
                total_cost FLOAT,
                payment_type VARCHAR(100) DEFAULT 'كاش',
                items_details TEXT,
                invoice_date VARCHAR(50)
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transfer_logs (
                id SERIAL PRIMARY KEY,
                from_branch_id INT,
                to_branch_id INT,
                transfer_type VARCHAR(100),
                items_details TEXT,
                status VARCHAR(100) DEFAULT 'مكتملة',
                transfer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS expenses (id SERIAL PRIMARY KEY, branch_id INT, amount FLOAT NOT NULL, description TEXT NOT NULL, is_general_store INT DEFAULT 0, expense_date VARCHAR(50));")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id SERIAL PRIMARY KEY,
                branch_id INT,
                user_id INT,
                customer_name VARCHAR(255) DEFAULT 'زبون نقدي',
                customer_phone VARCHAR(100) DEFAULT '',
                total_amount FLOAT,
                payment_method VARCHAR(100) DEFAULT 'كاش',
                notes TEXT,
                shift_status VARCHAR(50) DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS negative_sales_logs (id SERIAL PRIMARY KEY, branch_id INT, user_id INT, item_name VARCHAR(255), sale_qty FLOAT, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
        cursor.execute("CREATE TABLE IF NOT EXISTS role_permissions (role VARCHAR(100) PRIMARY KEY, allowed_menus TEXT);")
        cursor.execute("CREATE TABLE IF NOT EXISTS custom_labels (original_name VARCHAR(255) PRIMARY KEY, custom_name VARCHAR(255) NOT NULL);")
        cursor.execute("CREATE TABLE IF NOT EXISTS activity_logs (id SERIAL PRIMARY KEY, user_id INT, action TEXT, details TEXT, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")

    else:
        # --- جداول SQLite المحلية (الوضع الاحتياطي) ---
        cursor.execute("CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_name TEXT UNIQUE NOT NULL, branch_type TEXT DEFAULT 'فرع')")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                phone TEXT,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                branch_id INTEGER,
                allowed_branches TEXT DEFAULT 'ALL',
                custom_permissions TEXT DEFAULT '',
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE SET NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_id INTEGER,
                item_code TEXT,
                item_name TEXT NOT NULL,
                quantity REAL DEFAULT 0.0,
                buy_price REAL DEFAULT 0.0,
                sale_price REAL NOT NULL,
                avg_cost REAL DEFAULT 0.0,
                expiry_date TEXT DEFAULT '',
                no_expiry INTEGER DEFAULT 0,
                favorite_rank INTEGER DEFAULT 0,
                FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_name TEXT UNIQUE NOT NULL, phone TEXT, balance REAL DEFAULT 0.0)")
        cursor.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL, phone TEXT UNIQUE NOT NULL, total_purchases REAL DEFAULT 0.0, balance REAL DEFAULT 0.0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_id INTEGER,
                supplier_id INTEGER,
                supplier_name TEXT,
                invoice_number TEXT,
                total_cost REAL,
                payment_type TEXT DEFAULT 'كاش',
                items_details TEXT,
                invoice_date TEXT,
                FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transfer_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_branch_id INTEGER,
                to_branch_id INTEGER,
                transfer_type TEXT,
                items_details TEXT,
                status TEXT DEFAULT 'مكتملة',
                transfer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, amount REAL NOT NULL, description TEXT NOT NULL, is_general_store INTEGER DEFAULT 0, expense_date TEXT)")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_id INTEGER,
                user_id INTEGER,
                customer_name TEXT DEFAULT 'زبون نقدي',
                customer_phone TEXT DEFAULT '',
                total_amount REAL,
                payment_method TEXT DEFAULT 'كاش',
                notes TEXT,
                shift_status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS negative_sales_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, user_id INTEGER, item_name TEXT, sale_qty REAL, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        cursor.execute("CREATE TABLE IF NOT EXISTS role_permissions (role TEXT PRIMARY KEY, allowed_menus TEXT)")
        cursor.execute("CREATE TABLE IF NOT EXISTS custom_labels (original_name TEXT PRIMARY KEY, custom_name TEXT NOT NULL)")
        cursor.execute("CREATE TABLE IF NOT EXISTS activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

    # إدخال البيانات الأساسية والصلاحيات
    try:
        if DB_TYPE == "postgres":
            cursor.execute("INSERT INTO role_permissions (role, allowed_menus) VALUES ('Admin', %s) ON CONFLICT (role) DO NOTHING", (",".join(DEFAULT_MENUS),))
            cursor.execute("INSERT INTO role_permissions (role, allowed_menus) VALUES ('General_Supervisor', %s) ON CONFLICT (role) DO NOTHING", (",".join(DEFAULT_MENUS),))
            cursor.execute("INSERT INTO role_permissions (role, allowed_menus) VALUES ('Cashier', %s) ON CONFLICT (role) DO NOTHING", ('🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),⭐ لوحة المفضلة (1-20),🔄 تزويد الفروع والأرشيف',))
        else:
            cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Admin', ?)", (",".join(DEFAULT_MENUS),))
            cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('General_Supervisor', ?)", (",".join(DEFAULT_MENUS),))
            cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Cashier', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),⭐ لوحة المفضلة (1-20),🔄 تزويد الفروع والأرشيف')")
    except Exception as e:
        print(f"Role permissions error: {e}")

    # الفروع الافتراضية
    cursor.execute("SELECT COUNT(*) FROM branches")
    branch_count = cursor.fetchone()
    count_val = branch_count["count"] if isinstance(branch_count, dict) else branch_count[0]
    
    if count_val == 0:
        default_branches = [("المخزن الرئيسي", "مخزن"), ("فرع الجزيرة", "فرع"), ("فرع 2", "فرع")]
        for b_name, b_type in default_branches:
            try:
                if DB_TYPE == "postgres":
                    cursor.execute("INSERT INTO branches (branch_name, branch_type) VALUES (%s, %s) ON CONFLICT (branch_name) DO NOTHING", (b_name, b_type))
                else:
                    cursor.execute("INSERT OR IGNORE INTO branches (branch_name, branch_type) VALUES (?, ?)", (b_name, b_type))
            except Exception as e:
                print(f"Branch insert error: {e}")

    # مستخدم الأدمن الافتراضي
    cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin' AND is_active = 1")
    admin_chk = cursor.fetchone()
    admin_count = admin_chk["count"] if isinstance(admin_chk, dict) else admin_chk[0]
    
    if admin_count == 0:
        try:
            if DB_TYPE == "postgres":
                cursor.execute("INSERT INTO users (username, phone, password, role, allowed_branches, is_active) VALUES (%s, %s, %s, %s, %s, %s)", ('admin', '0910000000', 'admin', 'Admin', 'ALL', 1))
            else:
                cursor.execute("INSERT OR IGNORE INTO users (username, phone, password, role, allowed_branches, is_active) VALUES ('admin', '0910000000', 'admin', 'Admin', 'ALL', 1)")
        except Exception as e:
            print(f"Admin insert error: {e}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    initialize_database()
    print("✅ تم ربط وتجهيز قاعدة البيانات السحابية على Supabase بنجاح تام!")
