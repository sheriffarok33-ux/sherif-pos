import sqlite3
import os

DB_NAME = 'database.db'

def get_db_connection():
    """تأسيس اتصال بقاعدة البيانات وإرجاع الكائن للتعامل معه كقاموس."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def create_tables():
    """إنشاء جميع الجداول الأساسية لبرنامج محامص أبو زيد إذا لم تكن موجودة."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. جدول الفروع والمخازن
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_name TEXT NOT NULL,
            branch_type TEXT
        )
    """)

    # 2. جدول المستخدمين والصلاحيات
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            phone TEXT,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            branch_id INTEGER,
            FOREIGN KEY (branch_id) REFERENCES branches (id)
        )
    """)

    # 3. جدول سجل مراقبة النظام
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            action TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 4. جدول الأصناف والمخزون
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code TEXT,
            item_name TEXT NOT NULL,
            branch_id INTEGER,
            quantity REAL DEFAULT 0.0,
            buy_price REAL DEFAULT 0.0,
            sale_price REAL DEFAULT 0.0,
            avg_cost REAL DEFAULT 0.0,
            favorite_rank INTEGER DEFAULT 0,
            expiry_date TEXT,
            FOREIGN KEY (branch_id) REFERENCES branches (id)
        )
    """)

    # 5. جدول الزبائن
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT UNIQUE NOT NULL,
            phone TEXT,
            total_purchases REAL DEFAULT 0.0,
            balance REAL DEFAULT 0.0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 6. جدول الموردين
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_name TEXT UNIQUE NOT NULL,
            phone TEXT,
            balance REAL DEFAULT 0.0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 7. جدول فواتير المبيعات
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER,
            user_id INTEGER,
            customer_name TEXT,
            customer_phone TEXT,
            total_amount REAL,
            payment_method TEXT,
            notes TEXT,
            shift_status TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (branch_id) REFERENCES branches (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # 8. جدول المشتريات
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER,
            supplier_id INTEGER,
            supplier_name TEXT,
            invoice_number TEXT,
            total_cost REAL,
            payment_type TEXT,
            items_details TEXT,
            invoice_date TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (branch_id) REFERENCES branches (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
        )
    """)

    # 9. جدول المصروفات
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER,
            amount REAL,
            description TEXT,
            expense_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (branch_id) REFERENCES branches (id)
        )
    """)

    # 10. جدول سجلات التزويد والتحويل
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transfer_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_branch_id INTEGER,
            to_branch_id INTEGER,
            transfer_type TEXT,
            items_details TEXT,
            status TEXT,
            transfer_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (from_branch_id) REFERENCES branches (id),
            FOREIGN KEY (to_branch_id) REFERENCES branches (id)
        )
    """)

    conn.commit()

    # إنشاء حساب Admin افتراضي إذا كان الجدول فارغاً
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
            INSERT INTO users (username, password, role)
            VALUES ('admin', 'admin123', 'Admin')
        """)
        conn.commit()

    conn.close()

# 🌟 الحل الذكي: جعل initialize_database مرادفاً تماماً لـ create_tables لمنع أي خطأ استيراد
initialize_database = create_tables

# تنفيذ التهيئة عند الاستيراد
create_tables()
