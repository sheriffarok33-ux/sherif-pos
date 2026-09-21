import os
import streamlit as st
import sqlite3

# محاولة استيراد مكتبة بوستجريس للاتصال السحابي
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

def get_db_connection():
    # التحقق مما إذا كان التطبيق يعمل على سحابة Streamlit ويحتوي على Secrets
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
            # إذا حدث خطأ في الاتصال السحابي، نطبع الخطأ لنعرف سببه
            print(f"Postgres Connection Error: {e}")
            raise e
    else:
        # الاتصال المحلي SQLite الافتراضي
        db_path = "abu_zaid_store.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
