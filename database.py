import os
import streamlit as st
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

# 🌟 تحديد مسار ثابت ومطلق لقاعدة البيانات والنسخ الاحتياطي داخل مجلد المشروع
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "abu_zaid_new_system.db"
BACKUP_DIR = BASE_DIR / "backups"

# التأكد من إنشاء المجلدات تلقائياً (بما فيها مجلد data الذي أنشأته حديثاً)
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_MENUS = [
    "🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)", "⭐ لوحة المفضلة (1-20)", "📦 إدارة المخزن والفروع",
    "➕ الفائض والتوالف والمرتجعات وتعديل السعر", "🔄 تزويد الفروع والأرشيف", "🏢 إدارة الفروع",
    "📁 استيراد Excel", "💰 المصروفات", "📥 المشتريات والموردين", "⚙️ الجرد والتصفير السنوي",
    "🥜 التحميص والخلط", "📊 التقارير والأرباح", "👥 إدارة المستخدمين"
]

def get_db_connection():
    """إنشاء اتصال آمن وقوي مع قاعدة البيانات SQLite"""
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn

def create_desktop_backup():
    """أخذ نسخة احتياطية محلية للنسخة المكتبية وتجنب الأجهزة المحمولة"""
    try:
        user_agent = str(st.context.headers.get("User-Agent", "")).lower() if hasattr(st, "context") else ""
        is_mobile = any(m in user_agent for m in ["iphone", "android", "ipad", "mobile", "tablet"])
        
        if not is_mobile and DB_PATH.exists():
            today_str = datetime.now().strftime("%Y-%m-%d")
            backup_file = BACKUP_DIR / f"abu_zaid_backup_{today_str}.db"
            
            if not backup_file.exists():
                shutil.copy2(DB_PATH, backup_file)
                backups = sorted(BACKUP_DIR.glob("abu_zaid_backup_*.db"))
                if len(backups) > 7:
                    for old_b in backups[:-7]:
                        old_b.unlink()
    except Exception as e:
        print(f"Backup warning: {e}")

def initialize_database():
    """كود التهيئة الآمن: ينشئ الجداول إن لم تكن موجودة ويضمن وجود حساب الأدمن للدخول الفوري"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # جدول الفروع والمخازن
    cursor.execute("CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_name TEXT UNIQUE NOT NULL, branch_type TEXT DEFAULT 'فرع')")
    
    # جدول المستخدمين والصلاحيات
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
    
    # جدول الأصناف والمخزون
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
    
    # جدول الموردين والعملاء
    cursor.execute("CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_name TEXT UNIQUE NOT NULL, phone TEXT, balance REAL DEFAULT 0.0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL, phone TEXT UNIQUE NOT NULL, total_purchases REAL DEFAULT 0.0, balance REAL DEFAULT 0.0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    
    # جدول المشتريات
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
    
    # جدول حركات وتزويد الفروع
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
    
    # جدول المصروفات
    cursor.execute("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, amount REAL NOT NULL, description TEXT NOT NULL, is_general_store INTEGER DEFAULT 0, expense_date TEXT)")
    
    # جدول الفواتير والمبيعات
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
    
    # جدول تسويات المخزون
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER NOT NULL,
            item_id INTEGER,
            item_name TEXT NOT NULL,
            quantity REAL NOT NULL,
            adjustment_type TEXT NOT NULL,
            loss_or_gain_value REAL NOT NULL,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (branch_id) REFERENCES branches(id)
        )
    """)

    # جداول السجلات الإضافية والصلاحيات
    cursor.execute("CREATE TABLE IF NOT EXISTS negative_sales_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, user_id INTEGER, item_name TEXT, sale_qty REAL, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS role_permissions (role TEXT PRIMARY KEY, allowed_menus TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS custom_labels (original_name TEXT PRIMARY KEY, custom_name TEXT NOT NULL)")
    cursor.execute("CREATE TABLE IF NOT EXISTS activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

    # إدراج الصلاحيات الافتراضية
    try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Admin', ?)", (",".join(DEFAULT_MENUS),))
    except: pass
    try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('General_Supervisor', ?)", (",".join(DEFAULT_MENUS),))
    except: pass
    try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Cashier', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),🔄 تزويد الفروع والأرشيف')")
    except: pass

    # الفروع الافتراضية إذا كان النظام فارغاً
    branch_count = cursor.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
    if branch_count == 0:
        default_branches = [("المخزن الرئيسي", "مخزن"), ("فرع الجزيرة", "فرع"), ("فرع 2", "فرع")]
        for b_name, b_type in default_branches:
            cursor.execute("INSERT OR IGNORE INTO branches (branch_name, branch_type) VALUES (?, ?)", (b_name, b_type))

    # 🌟 التأكد الإجباري من وجود حساب الأدمن لضمان فتح البرنامج فوراً
    admin_chk = cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin' AND is_active = 1").fetchone()[0]
    if admin_chk == 0:
        cursor.execute("INSERT OR IGNORE INTO users (username, phone, password, role, allowed_branches, is_active) VALUES ('admin', '0910000000', '123456', 'Admin', 'ALL', 1)")

    conn.commit()
    conn.close()
    create_desktop_backup()

if __name__ == "__main__":
    initialize_database()
    print("✅ تم فحص وتهيئة قاعدة البيانات وتفعيل النسخ الاحتياطي بنجاح!")
