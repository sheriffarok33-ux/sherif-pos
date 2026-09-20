import os
import re
import io
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta
from database import initialize_database, get_db_connection

# تهيئة قاعدة البيانات عند بدء تشغيل التطبيق
initialize_database()

# إعدادات الصفحة الأساسية
st.set_page_config(
    page_title="مجموعة أبو زيد - نظام المحامص والمخازن الذكي",
    layout="wide",
    initial_sidebar_state="expanded",
)

# إضافة ستايل CSS
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
    
    div.stButton > button { 
        border-radius: 8px; font-weight: 900 !important; transition: all 0.3s ease; height: 50px; 
        background: linear-gradient(135deg, #0284c7, #0369a1); color: white !important; border: none;
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
    </style>
""", unsafe_allow_html=True)

# إنشاء مجلد الصور إذا لم يكن موجوداً
if not os.path.exists("item_images"): 
    os.makedirs("item_images")

# تهيئة متغيرات الجلسة (Session State)
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "username" not in st.session_state: st.session_state["username"] = ""
if "role" not in st.session_state: st.session_state["role"] = ""
if "user_id" not in st.session_state: st.session_state["user_id"] = None
if "branch_id" not in st.session_state: st.session_state["branch_id"] = None
if "cart" not in st.session_state: st.session_state["cart"] = []
if "page" not in st.session_state: st.session_state["page"] = "🏠 الرئيسية واللوحة"
if "success_alert_msg" not in st.session_state: st.session_state["success_alert_msg"] = ""

def set_page(page_name): 
    st.session_state["page"] = page_name
    st.rerun()

# --- بوابة الدخول ---
if not st.session_state["logged_in"]:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.title("🔐 بوابة دخول نظام المحامص")
        st.subheader("مجموعة أبو زيد التجارية")
        
        with st.form("login_form"):
            u_name = st.text_input("اسم المستخدم")
            u_pass = st.text_input("كلمة المرور", type="password")
            submit = st.form_submit_button("🚀 دخول للنظام", use_container_width=True)
            if submit:
                conn = get_db_connection()
                user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (u_name, u_pass)).fetchone()
                conn.close()
                if user:
                    if user["is_active"] == 0:
                        st.error("🚫 هذا الحساب موقوف!")
                        st.stop()
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = user["username"]
                    st.session_state["role"] = user["role"]
                    st.session_state["user_id"] = user["id"]
                    st.session_state["branch_id"] = user["branch_id"]
                    st.rerun()
                else: 
                    st.error("🎭 **اسم المستخدم أو كلمة المرور غير صحيحة!**")
    st.stop()

# --- القائمة الجانبية (Navigation Menu) مرتبة ومنظمة ---
st.sidebar.markdown("<h2 style='text-align: center; color: white;'>🥜 مجموعة أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; color: white;'><b>{st.session_state['username']} | {st.session_state['role']}</b></p>", unsafe_allow_html=True)
st.sidebar.markdown("---")

# قائمة الشاشات المتاحة في النظام
DEFAULT_MENUS = [
    "🏠 الرئيسية واللوحة",
    "🛒 نقطة البيع (POS)",
    "🏢 إدارة الفروع",
    "👥 إدارة المستخدمين",
    "⭐ لوحة المفضلة (1-20)",
    "📦 إدارة المخزن والفروع",
    "➕ الفائض والتوالف والمرتجعات وتعديل السعر",
    "🔄 تزويد الفروع والأرشيف",
    "📁 استيراد Excel",
    "💰 المصروفات",
    "📥 المشتريات والموردين",
    "⚙️ الجرد والتصفير السنوي",
    "🥜 التحميص والخلط",
    "📊 التقارير والأرباح"
]

# عرض أزرار القائمة الجانبية بشكل ديناميكي وآمن
for menu_name in DEFAULT_MENUS:
    if st.sidebar.button(menu_name, use_container_width=True, key=f"sidebar_btn_{menu_name}"):
        set_page(menu_name)

st.sidebar.markdown("---")
if st.sidebar.button("🚪 تسجيل الخروج", use_container_width=True):
    st.session_state.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")

# --- منطقة توجيه الشاشات (Router) الآمنة ---
choice = st.session_state.get("page", "🏠 الرئيسية واللوحة")

if choice == "🏠 الرئيسية واللوحة":
    try:
        from views import dashboard
        dashboard.show_page()
    except ImportError:
        st.title("🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية")
        st.info("مرحباً بك في النظام السحابي. شاشة الرئيسية قيد التجهيز.")

elif choice == "🛒 نقطة البيع (POS)":
    try:
        from views import pos
        pos.show_page()
    except ImportError:
        st.info("🛒 شاشة نقطة البيع قيد الترتيب وفق الهيكل الجديد...")

elif choice == "🏢 إدارة الفروع":
    try:
        from views import branches
        branches.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة إدارة الفروع (views/branches.py) غير موجود في المجلد.")

elif choice == "👥 إدارة المستخدمين":
    try:
        from views import users
        users.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة إدارة المستخدمين (views/users.py) غير موجود في المجلد.")

elif choice == "➕ الفائض والتوالف والمرتجعات وتعديل السعر":
    try:
        from views import adjustments
        adjustments.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة الفائض والتوالف (views/adjustments.py) غير موجود.")

else:
    st.info(f"🚧 الشاشة ({choice}) يتم العمل على تجهيزها برمجياً ضمن الخطة الجديدة.")
