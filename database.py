import sqlite3

def get_db_connection():
    # فتح الاتصال بقاعدة البيانات محلياً مع منع أخطاء الخيوط المتعددة
    conn = sqlite3.connect("abu_zaid_data.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    """هذه الدالة هي كود التهيئة وتُستدعى عند بدء تشغيل البرنامج لإنشاء الجداول إن لم تكن موجودة"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # تفعيل القيود المرجعية
    cur.execute("PRAGMA foreign_keys = ON;")
    
    # جدول المستخدمين والصلاحيات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            phone TEXT,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            branch_id INTEGER,
            is_active INTEGER DEFAULT 1
        )
    """)
    
    # جدول الفروع والمخازن
    cur.execute("""
        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_name TEXT UNIQUE NOT NULL,
            branch_type TEXT NOT NULL,
            phone TEXT
        )
    """)
    
    # جدول الأصناف والمخزون
    cur.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL,
            item_code TEXT NOT NULL,
            item_name TEXT NOT NULL,
            quantity REAL DEFAULT 0.0,
            buy_price REAL DEFAULT 0.0,
            sale_price REAL DEFAULT 0.0,
            avg_cost REAL DEFAULT 0.0,
            expiry_date TEXT,
            favorite_rank INTEGER DEFAULT 0
        )
    """)
    
    # جدول الفواتير (المبيعات)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            customer_name TEXT,
            customer_phone TEXT,
            total_amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            notes TEXT,
            shift_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # جدول الموردين
    cur.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_name TEXT UNIQUE NOT NULL,
            phone TEXT,
            balance REAL DEFAULT 0.0
        )
    """)
    
    # جدول الزبائن الآجلين والولاء
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT UNIQUE NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            total_purchases REAL DEFAULT 0.0,
            balance REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # جدول المشتريات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            supplier_name TEXT,
            invoice_number TEXT,
            total_cost REAL NOT NULL,
            payment_type TEXT,
            items_details TEXT,
            invoice_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # جدول حركات تزويد الفروع
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transfer_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_branch_id INTEGER NOT NULL,
            to_branch_id INTEGER NOT NULL,
            transfer_type TEXT,
            items_details TEXT,
            status TEXT,
            transfer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # جدول المصروفات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL,
            expense_type TEXT NOT NULL,
            amount REAL NOT NULL,
            notes TEXT,
            expense_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # إنشاء حساب أدمن افتراضي تلقائياً إن لم يكن موجوداً لضمان عدم غلق النظام
    admin_exists = cur.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
    if not admin_exists:
        cur.execute("""
            INSERT INTO users (username, password, role, is_active)
            VALUES ('admin', '123456', 'Admin', 1)
        """)

    conn.commit()
    conn.close()
