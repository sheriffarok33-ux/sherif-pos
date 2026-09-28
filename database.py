import os
import sqlite3
from pathlib import Path
import streamlit as st

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# 🌟 تحديد مسار ثابت ومطلق لملف قاعدة البيانات داخل مجلد المشروع
BASE_DIR = Path(__file__).resolve().parent  # مجلد ملف database.py
DB_PATH = BASE_DIR / "data" / "abu_zaid_new_system.db"  # مسار ثابت

# التأكد من إنشاء مجلد data تلقائياً إذا لم يكن موجوداً
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

def get_db_connection():
    db_type = os.getenv("DB_TYPE", "")
    postgres_url = os.getenv("DATABASE_URL", "")

    if hasattr(st, "secrets"):
        if "DB_TYPE" in st.secrets:
            db_type = st.secrets["DB_TYPE"]
        if "DATABASE_URL" in st.secrets:
            postgres_url = st.secrets["DATABASE_URL"]

    if db_type == "postgres" and POSTGRES_AVAILABLE and postgres_url:
        conn = psycopg2.connect(postgres_url, cursor_factory=RealDictCursor)
        return conn
    else:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. جدول الفروع والمخازن
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_name TEXT UNIQUE NOT NULL,
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
            FOREIGN KEY (branch_id) REFERENCES branches (id)
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
            expiry_date TEXT,
            favorite_rank INTEGER DEFAULT 0,
            FOREIGN KEY (branch_id) REFERENCES branches (id)
        )
    """)
    
    # 4. جدول الموردين
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
            phone TEXT UNIQUE,
            total_purchases REAL DEFAULT 0.0,
            balance REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 6. جدول الفواتير ومبيعات نقاط البيع (POS)
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (branch_id) REFERENCES branches (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    
    # 7. جدول فواتير ومشتريات البضاعة
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
            FOREIGN KEY (branch_id) REFERENCES branches (id),
            FOREIGN KEY (supplier_id) REFERENCES suppliers (id)
        )
    """)
    
    # 8. جدول حركات تزويد الفروع (Transfer Logs)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transfer_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_branch_id INTEGER,
            to_branch_id INTEGER,
            transfer_type TEXT,
            items_details TEXT,
            status TEXT,
            transfer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (from_branch_id) REFERENCES branches (id),
            FOREIGN KEY (to_branch_id) REFERENCES branches (id)
        )
    """)
    
    # 9. جدول المصروفات (إن وجدت)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER,
            expense_name TEXT,
            amount REAL,
            expense_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (branch_id) REFERENCES branches (id)
        )
    """)

    conn.commit()
    conn.close()

# تهيئة قاعدة البيانات تلقائياً عند استيراد الملف لضمان إنشاء الجداول بالمسار الجديد
init_db()
