import sqlite3
import os
import logging

# إعداد ملف قاعدة البيانات المحلية للفرع
LOCAL_DB_PATH = "mahamis.db"

def get_db_connection():
    """
    إنشاء وإرجاع اتصال بقاعدة البيانات المحلية SQLite.
    تم تفعيل check_same_thread=False لضمان التوافق مع Streamlit.
    """
    conn = sqlite3.connect(LOCAL_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """
    تهيئة وإنشاء كافة جداول النظام الأساسية إذا لم تكن موجودة.
    يتم تنفيذ هذه الدالة مرة واحدة عند تشغيل النظام.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. جدول الفروع والمخازن
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_name TEXT NOT NULL,
            branch_type TEXT NOT NULL
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
            FOREIGN KEY (branch_id) REFERENCES branches(id)
        )
    """)

    # 3. جدول الأصناف والمخزون
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER,
            item_code TEXT,
            item_name TEXT NOT NULL,
            quantity REAL DEFAULT 0.0,
            buy_price REAL DEFAULT 0.0,
            sale_price REAL DEFAULT 0.0,
            avg_cost REAL DEFAULT 0.0,
            favorite_rank INTEGER DEFAULT 0,
            expiry_date TEXT,
            FOREIGN KEY (branch_id) REFERENCES branches(id)
        )
    """)

    # 4. جدول الموردين (تجار الجملة)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_name TEXT UNIQUE NOT NULL,
            phone TEXT,
            balance REAL DEFAULT 0.0
        )
    """)

    # 5. جدول الزبائن الآجلين والولاء
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT UNIQUE NOT NULL,
            phone TEXT,
            total_purchases REAL DEFAULT 0.0,
            balance REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 6. جدول مبيعات نقطة البيع (الكاشير)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER,
            user_id INTEGER,
            customer_name TEXT,
            customer_phone TEXT,
            total_amount REAL DEFAULT 0.0,
            payment_method TEXT,
            notes TEXT,
            shift_status TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_status INTEGER DEFAULT 0
        )
    """)

    # 7. جدول المشتريات والتوريد
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER,
            supplier_id INTEGER,
            supplier_name TEXT,
            invoice_number TEXT,
            total_cost REAL DEFAULT 0.0,
            payment_type TEXT,
            items_details TEXT,
            invoice_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_status INTEGER DEFAULT 0
        )
    """)

    # 8. جدول المصروفات (للتقارير المالية)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER,
            amount REAL DEFAULT 0.0,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_status INTEGER DEFAULT 0
        )
    """)

    # 9. جدول حركات النقل وتزويد الفروع
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transfer_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_branch_id INTEGER,
            to_branch_id INTEGER,
            transfer_type TEXT,
            items_details TEXT,
            status TEXT,
            transfer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sync_status INTEGER DEFAULT 0
        )
    """)

    conn.commit()

    # ==========================================
    # سكريبت ترقية قواعد البيانات الحالية (Migration)
    # لإضافة عمود sync_status برمجياً دون حذف البيانات
    # ==========================================
    tables_to_upgrade = ["invoices", "purchases", "expenses", "transfer_logs"]
    
    for table in tables_to_upgrade:
        try:
            # محاولة إضافة العمود؛ إذا كان موجوداً مسبقاً سيتجاهل الخطأ ويكمل بسلاسة
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN sync_status INTEGER DEFAULT 0")
            conn.commit()
            logging.info(f"تمت ترقية الجدول {table} بإضافة عمود sync_status.")
        except sqlite3.OperationalError:
            # العمود موجود مسبقاً، لا حاجة لأي إجراء
            pass

    conn.close()

# تنفيذ التهيئة تلقائياً عند استدعاء الملف
if __name__ == "__main__":
    init_db()
    print("✅ تمت تهيئة قاعدة بيانات محامص أبو زيد (mahamis.db) وتحديثها بنجاح!")
