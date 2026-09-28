import os
import streamlit as st
import sqlite3

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

DB_NAME = "abu_zaid_new_system.db"

DEFAULT_MENUS = [
    "🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)", "⭐ لوحة المفضلة (1-20)", "📦 إدارة المخزن والفروع",
    "➕ الفائض والتوالف والمرتجعات وتعديل السعر", "🔄 تزويد الفروع والأرشيف", "🏢 إدارة الفروع",
    "📁 استيراد Excel", "💰 المصروفات", "📥 المشتريات والموردين", "⚙️ الجرد والتصفير السنوي",
    "🥜 التحميص والخلط", "📊 التقارير والأرباح", "👥 إدارة المستخدمين"
]

def get_db_connection():
    db_type = os.getenv("DB_TYPE", "")
    postgres_url = os.getenv("DATABASE_URL", "")

    if "DB_TYPE" in st.secrets:
        db_type = st.secrets["DB_TYPE"]
    if "DATABASE_URL" in st.secrets:
        postgres_url = st.secrets["DATABASE_URL"]

    if db_type == "postgres" and POSTGRES_AVAILABLE and postgres_url:
        try:
            conn = psycopg2.connect(postgres_url, cursor_factory=RealDictCursor)
            return conn
        except Exception as e:
            conn = sqlite3.connect(DB_NAME, timeout=10)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            return conn
    else:
        conn = sqlite3.connect(DB_NAME, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

def reindex_table(conn, table_name):
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
    conn = get_db_connection()
    cursor = conn.cursor()

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

    try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Admin', ?)", (",".join(DEFAULT_MENUS),))
    except: pass
    try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('General_Supervisor', ?)", (",".join(DEFAULT_MENUS),))
    except: pass
    try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Cashier', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),⭐ لوحة المفضلة (1-20),🔄 تزويد الفروع والأرشيف')")
    except: pass

    branch_count = cursor.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
    if branch_count == 0:
        default_branches = [("المخزن الرئيسي", "مخزن"), ("فرع الجزيرة", "فرع"), ("فرع 2", "فرع")]
        for b_name, b_type in default_branches:
            cursor.execute("INSERT OR IGNORE INTO branches (branch_name, branch_type) VALUES (?, ?)", (b_name, b_type))

    admin_chk = cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin' AND is_active = 1").fetchone()[0]
    if admin_chk == 0:
        cursor.execute("INSERT OR IGNORE INTO users (username, phone, password, role, allowed_branches, is_active) VALUES ('admin', '0910000000', 'admin', 'Admin', 'ALL', 1)")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    initialize_database()
    print("✅ تم إنشاء قاعدة البيانات والجداول بنجاح!")
