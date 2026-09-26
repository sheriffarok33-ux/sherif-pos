import os
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime

# ==========================================
# 1. إعداد الصفحة وتكوين الواجهة (يجب أن يكون أول أمر في الملف)
# ==========================================
st.set_page_config(
    page_title="مجموعة أبو زيد - نظام المحامص والمخازن الذكي",
    page_icon="🥜",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==========================================
# 2. استدعاء قاعدة البيانات بمرونة
# ==========================================
# محاولة استدعاء دالة تهيئة الجداول بغض النظر عن اسمها (لتفادي تعارض الأسماء)
try:
    from database import create_tables as init_db, get_db_connection
except ImportError:
    from database import initialize_database as init_db, get_db_connection

# تهيئة قاعدة البيانات عند بدء تشغيل التطبيق
init_db()

# ==========================================
# 3. استدعاء ملفات الشاشات بشكل مباشر وآمن
# ==========================================
# يتم استدعاء الملفات الموجودة في المسار الرئيسي، مع تجاهل الملفات غير الموجودة مؤقتاً
try: import users
except ImportError: users = None

try: import pos
except ImportError: pos = None

try: import transfers
except ImportError: transfers = None

try: import roasting_blending
except ImportError: roasting_blending = None

try: import reports
except ImportError: reports = None

try: import purchases
except ImportError: purchases = None

try: import parties
except ImportError: parties = None

try: import items_import
except ImportError: items_import = None

try: import inventory
except ImportError: inventory = None

try: import favorites
except ImportError: favorites = None

try: import branches
except ImportError: branches = None

# ==========================================
# 4. التنسيق العام (CSS) للواجهة
# ==========================================
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&display=swap');
    html, body, [class*="css"], p, span, div, label, h1, h2, h3, h4, h5, h6, table, th, td { 
        font-family: 'Tajawal', sans-serif !important; 
        color: #000000 !important; 
        font-weight: 900 !important;
        font-size: 17px !important;
        direction: rtl !important;
        text-align: right !important;
    }
    .main { background-color: #f8fafc; }
    h1 { font-size: 28px !important; color: #0f172a !important; }
    h2 { font-size: 24px !important; color: #1e293b !important; }
    h3 { font-size: 20px !important; color: #334155 !important; }
    
    div.stButton > button, div.stButton > button * { 
        color: #ffffff !important; 
    }
    
    div.stButton > button { 
        border-radius: 8px; font-weight: 900 !important; transition: all 0.3s ease; height: 50px; 
        background: linear-gradient(135deg, #0284c7, #0369a1); border: none;
        box-shadow: 0 3px 6px rgba(0,0,0,0.15); font-size: 18px !important;
    }
    div.stButton > button:hover { background: linear-gradient(135deg, #0369a1, #075985); transform: translateY(-2px); }
    
    [data-testid="stSidebar"] { background-color: #0f172a; border-left: 2px solid #334155 !important; }
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

# ==========================================
# 5. إدارة الجلسات (Session State)
# ==========================================
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "username" not in st.session_state: st.session_state["username"] = ""
if "role" not in st.session_state: st.session_state["role"] = ""
if "user_id" not in st.session_state: st.session_state["user_id"] = None
if "branch_id" not in st.session_state: st.session_state["branch_id"] = None
if "cart" not in st.session_state: st.session_state["cart"] = []
if "page" not in st.session_state: st.session_state["page"] = "🏠 الرئيسية واللوحة"

def set_page(page_name): 
    st.session_state["page"] = page_name
    st.rerun()

# ==========================================
# 6. نظام الصلاحيات الأمني
# ==========================================
def check_user_permission(menu_name):
    role = st.session_state.get("role", "")
    if role in ["Admin", "General_Supervisor"]: 
        return True
        
    if role == "Cashier":
        allowed_for_cashier = [
            "🏠 الرئيسية واللوحة", 
            "🛒 نقطة البيع (POS)", 
            "⭐ لوحة المفضلة (1-20)"
        ]
        return menu_name in allowed_for_cashier

    if role == "Viewer":
        allowed_for_viewer = [
            "🏠 الرئيسية واللوحة",
            "📊 التقارير والأرباح"
        ]
        return menu_name in allowed_for_viewer
        
    if role == "Branch_Supervisor":
         allowed_for_bs = [
            "🏠 الرئيسية واللوحة",
            "🛒 نقطة البيع (POS)",
            "📦 إدارة المخزن والفروع",
            "📥 المشتريات",
            "👥 جهات التعامل",
            "🥜 التحميص والخلط",
            "⭐ لوحة المفضلة (1-20)"
         ]
         return menu_name in allowed_for_bs

    return False

# ==========================================
# 7. بوابة الدخول (Login)
# ==========================================
if not st.session_state["logged_in"]:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown('<h1 style="text-align: center; color: #0f172a;">🔐 بوابة دخول نظام المحامص</h1>', unsafe_allow_html=True)
        st.markdown('<h3 style="text-align: center; color: #64748b;">مجموعة أبو زيد التجارية</h3>', unsafe_allow_html=True)
        
        with st.form("login_form"):
            u_name = st.text_input("اسم المستخدم")
            u_pass = st.text_input("كلمة المرور", type="password")
            submit = st.form_submit_button("🚀 دخول للنظام", use_container_width=True)
            
            if submit:
                conn = get_db_connection()
                # جلب بيانات المستخدم كاملة
                user = conn.execute("SELECT id, username, role, branch_id FROM users WHERE username = ? AND password = ?", (u_name, u_pass)).fetchone()
                conn.close()
                
                if user:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = user["username"]
                    st.session_state["role"] = user["role"]
                    st.session_state["user_id"] = user["id"]
                    st.session_state["branch_id"] = user["branch_id"]
                    st.rerun()
                else: 
                    st.error("🎭 **اسم المستخدم أو كلمة المرور غير صحيحة!**")
    st.stop()

# ==========================================
# 8. القائمة الجانبية (Sidebar)
# ==========================================
st.sidebar.markdown("<h2 style='text-align: center; color: #38bdf8;'>🥜 مجموعة أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; color: #cbd5e1; font-size:14px;'>المستخدم: <b>{st.session_state['username']}</b></p>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; color: #94a3b8; font-size:12px;'>الصلاحية: {st.session_state['role']}</p>", unsafe_allow_html=True)
st.sidebar.markdown("---")

DEFAULT_MENUS = [
    "🏠 الرئيسية واللوحة",
    "🛒 نقطة البيع (POS)",
    "🏢 إدارة الفروع",
    "👥 إدارة المستخدمين",
    "⭐ لوحة المفضلة (1-20)",
    "📦 إدارة المخزن والفروع",
    "🔄 تزويد الفروع والأرشيف",
    "📁 استيراد Excel",
    "👥 جهات التعامل",
    "📥 المشتريات",
    "🥜 التحميص والخلط",
    "📊 التقارير والأرباح"
]

for menu_name in DEFAULT_MENUS:
    if check_user_permission(menu_name):
        # تلوين الزر النشط لتمييز الشاشة الحالية
        if st.session_state["page"] == menu_name:
            st.sidebar.button(f"📍 {menu_name}", use_container_width=True, key=f"sidebar_btn_active_{menu_name}")
        else:
            if st.sidebar.button(menu_name, use_container_width=True, key=f"sidebar_btn_{menu_name}"):
                set_page(menu_name)

st.sidebar.markdown("---")
if st.sidebar.button("🚪 تسجيل الخروج", use_container_width=True):
    st.session_state.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("<p style='text-align: center; font-size:12px; color: #64748b;'>ENG: SHERIF M. FAROK</p>", unsafe_allow_html=True)

# ==========================================
# 9. موجه الشاشات (Router) الآمن
# ==========================================
choice = st.session_state.get("page", "🏠 الرئيسية واللوحة")

if not check_user_permission(choice):
    st.error("❌ غير مصرح لك بالوصول إلى هذه الشاشة.")
    st.stop()

if choice == "🏠 الرئيسية واللوحة":
    st.title("🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية")
    st.info("مرحباً بك في النظام السحابي الموحد. استخدم القائمة الجانبية للتنقل بين شاشات الإدارة والمبيعات.")

elif choice == "🛒 نقطة البيع (POS)":
    if pos: pos.show_page()
    else: st.warning("⚠️ ملف شاشة نقطة البيع (pos.py) غير متوفر.")

elif choice == "🏢 إدارة الفروع":
    if branches: branches.show_page()
    else: st.warning("⚠️ ملف شاشة إدارة الفروع (branches.py) غير متوفر.")

elif choice == "👥 إدارة المستخدمين":
    if users: users.show_page()
    else: st.warning("⚠️ ملف شاشة إدارة المستخدمين (users.py) غير متوفر.")

elif choice == "📁 استيراد Excel":
    if items_import: items_import.show_page()
    else: st.warning("⚠️ ملف شاشة الاستيراد (items_import.py) غير متوفر.")

elif choice == "👥 جهات التعامل":
    if parties: parties.show_page()
    else: st.warning("⚠️ ملف شاشة جهات التعامل (parties.py) غير متوفر.")

elif choice == "📥 المشتريات":
    if purchases: purchases.show_page()
    else: st.warning("⚠️ ملف شاشة المشتريات (purchases.py) غير متوفر.")

elif choice == "🔄 تزويد الفروع والأرشيف":
    if transfers: transfers.show_page()
    else: st.warning("⚠️ ملف شاشة التزويد (transfers.py) غير متوفر.")

elif choice == "⭐ لوحة المفضلة (1-20)":
    if favorites: favorites.show_page()
    else: st.warning("⚠️ ملف شاشة المفضلة (favorites.py) غير متوفر.")

elif choice == "📦 إدارة المخزن والفروع":
    if inventory: inventory.show_page()
    else: st.warning("⚠️ ملف شاشة الجرد (inventory.py) غير متوفر.")

elif choice == "🥜 التحميص والخلط":
    if roasting_blending: roasting_blending.show_page()
    else: st.warning("⚠️ ملف شاشة التحميص (roasting_blending.py) غير متوفر.")

elif choice == "📊 التقارير والأرباح":
    if reports: reports.show_page()
    else: st.warning("⚠️ ملف شاشة التقارير (reports.py) غير متوفر.")
