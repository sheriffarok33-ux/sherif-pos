import os
import streamlit as st
import sqlite3

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

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
            raise e
    else:
        db_path = "database.db"  # تأكد من اسم ملف قاعدة البيانات المحلي
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn

def initialize_database():
    """تهيئة الجداول الأساسية للقاعدة"""
    conn = get_db_connection()
    # هنا كود إنشاء الجداول (Tables creation) الذي تحدثنا عنه سابقاً
    conn.commit()
    conn.close()
