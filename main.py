import os
import re
import streamlit as st
from database import initialize_database, get_db_connection

# إعدادات الصفحة الأساسية
# يجب أن تكون أول أمر Streamlit في الملف.
st.set_page_config(
    page_title="مجموعة أبو زيد - نظام المحامص والمخازن الذكي",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# تهيئة PostgreSQL / Supabase مرة واحدة
# ============================================================

@st.cache_resource
def initialize_app_database():
    initialize_database()
    return True


try:
    initialize_app_database()
except Exception as e:
    st.error("❌ تعذر تهيئة قاعدة البيانات.")
    st.code(str(e))
    st.stop()

# إضافة ستايل CSS ومؤشر الاتصال (Online/Offline) في رأس الصفحة
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&display=swap');
    html, body, [class*="css"], p, span, div, label, h1, h2, h3, h4, h5, h6, table, th, td { 
        font-family: 'Tajawal', sans-serif !important; 
        color: #000000 !important; 
        font-weight: 900 !important;
        font-size: 17px !important;
    }
    .main { background-color: #f8fafc; }
    h1 { font-size: 28px !important; color: #0f172a !important; }
    h2 { font-size: 24px !important; color: #1e293b !important; }
    h3 { font-size: 20px !important; color: #334155 !important; }
    
    div.stButton > button, div.stButton > button * { color: #ffffff !important; }
    div.stButton > button { 
        border-radius: 8px; font-weight: 900 !important; transition: all 0.3s ease; height: 50px; 
        background: linear-gradient(135deg, #0284c7, #0369a1); border: none;
        box-shadow: 0 3px 6px rgba(0,0,0,0.15); font-size: 18px !important;
    }
    div.stButton > button:hover { background: linear-gradient(135deg, #0369a1, #075985); transform: translateY(-2px); }
    
    [data-testid="stSidebar"] { background-color: #0f172a; }
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] span, [data-testid="stSidebar"] p { color: #ffffff !important; font-size: 17px !important; }
    [data-testid="stSidebar"] .stButton>button {
        background-color: #1e293b; color: #ffffff !important; border: 1px solid #334155;
        border-radius: 10px; padding: 12px 15px; text-align: right; font-weight: 900 !important;
        transition: all 0.3s ease; margin-bottom: 8px; font-size: 17px !important; height: auto;
    }
    [data-testid="stSidebar"] .stButton>button:hover { background-color: #0284c7; color: white !important; border-color: #0284c7; transform: translateX(-5px); }
    
    div[data-testid="InputInstructions"] {
        display: none !important;
    }
    </style>

    <!-- 🌐 مؤشر حالة الاتصال (Online/Offline) في أعلى الصفحة -->
    <div id="connection-status" style="position: fixed; top: 10px; left: 10px; z-index: 999999; display: flex; align-items: center; background: #ffffff; padding: 6px 14px; border-radius: 20px; box-shadow: 0 3px 8px rgba(0,0,0,0.2); font-family: 'Tajawal', sans-serif; font-size: 14px; font-weight: bold;">
        <span id="status-dot" style="height: 12px; width: 12px; background-color: #22c55e; border-radius: 50%; display: inline-block; margin-left: 8px; transition: background-color 0.3s;"></span>
        <span id="status-text" style="color: #0f172a;">متصل بالسيرفر (Online)</span>
    </div>

    <script>
    function updateOnlineStatus() {
        const dot = document.getElementById('status-dot');
        const text = document.getElementById('status-text');
        
        if (navigator.onLine) {
            dot.style.backgroundColor = '#22c55e';
            text.innerHTML = 'متصل بالسيرفر (Online)';
        } else {
            dot.style.backgroundColor = '#dc2626';
            text.innerHTML = 'غير متصل بالإنترنت (Offline)';
        }
    }


    window.addEventListener('online', updateOnlineStatus);
    window.addEventListener('offline', updateOnlineStatus);
    
    updateOnlineStatus();
    setInterval(updateOnlineStatus, 5000);
    </script>
""", unsafe_allow_html=True)
