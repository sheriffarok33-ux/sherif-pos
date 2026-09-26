import os
import re
import io
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

# استيراد قاعدة البيانات مع معالجة الأخطاء
try:
    from database import initialize_database, get_db_connection
    initialize_database()
except Exception as e:
    st.error(f"⚠️ خطأ في تهيئة قاعدة البيانات: {e}")

# إعدادات الصفحة الأساسية
st.set_page_config(
    page_title="مجموعة أبو زيد - نظام المحامص والمخازن الذكي",
    layout="wide",
    initial_sidebar_state="expanded",
)

# إضافة ستايل CSS الموحد لضمان وضوح الخطوط والأزرار
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
    
    div.stButton > button, div.stButton > button * { 
        color: #ffffff !important; 
    }
    
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

def set_page(page_name): 
    st.session_state["page"] = page_name
    st.rerun()

# 🛡️ دالة فحص الصلاحيات المحمية بدقة عالية
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
            "📦 إدارة المخزن والفروع"
         ]
         return menu_name in allowed_for_bs

    return False

# --- استيراد الشاشات الآمن مع منع توقف التطبيق بالكامل ---
modules_dict = {}
screen_files = {
    "dashboard": "dashboard",
    "pos": "pos",
    "branches": "branches",
    "users": "users",
    "adjustments": "adjustments",
    "items_import": "items_import",
    "expenses": "expenses",
    "parties": "parties",
    "purchases": "purchases",
    "transfers": "transfers",
    "favorites": "favorites",
    "inventory": "inventory",
    "roasting_blending": "roasting_blending",
    "reports": "reports"
}

for mod_key, mod_name in screen_files.items():
    try:
        modules_dict[mod_key] = __import__(mod_name)
    except Exception as e:
        modules_dict[mod_key] = None

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
                try:
                    conn = get_db_connection()
                    user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (u_name, u_pass)).fetchone()
                    conn.close()
                    if user:
                        if "is_active" in user.keys() and user["is_active"] == 0:
                            st.error("🚫 هذا الحساب موقوف!")
                            st.stop()
                        st.session_state["logged_in"] = True
                        st.session_state["username"] = user["username"]
                        st.session_state["role"] = user["role"]
                        st.session_state["user_id"] = user["id"]
                        st.session_state["branch_id"] = user["branch_id"]
                        st.rerun()
                    else: 
                        st.error("🎭 **اسم المستخدم أو كلمة المرور غير صحيحة!** (التلقائي: admin / admin123)")
                except Exception as db_err:
                    st.error(f"⚠️ خطأ في الاتصال بقاعدة البيانات: {db_err}")
    st.stop()

# --- القائمة الجانبية (Navigation Menu) ---
st.sidebar.markdown("<h2 style='text-align: center; color: white;'>🥜 مجموعة أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; color: white;'><b>{st.session_state['username']} | {st.session_state['role']}</b></p>", unsafe_allow_html=True)
st.sidebar.markdown("---")

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
    "👥 جهات التعامل",
    "📥 المشتريات",
    "⚙️ الجرد والتصفير السنوي",
    "🥜 التحميص والخلط",
    "📊 التقارير والأرباح"
]

for menu_name in DEFAULT_MENUS:
    if check_user_permission(menu_name):
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

if not check_user_permission(choice):
    st.error("❌ غير مصرح لك بالوصول إلى هذه الشاشة.")
    st.stop()

# توجيه الشاشات بناءً على الاختيار
if choice == "🏠 الرئيسية واللوحة":
    if modules_dict["dashboard"] and hasattr(modules_dict["dashboard"], "show_page"):
        modules_dict["dashboard"].show_page()
    else:
        st.title("🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية")
        st.info("مرحباً بك في النظام السحابي. جاري تحميل لوحة التحكم...")

elif choice == "🛒 نقطة البيع (POS)":
    if modules_dict["pos"] and hasattr(modules_dict["pos"], "show_page"):
        modules_dict["pos"].show_page()
    else: st.error("⚠️ شاشة نقطة البيع غير متوفرة أو حدث خطأ في تحميل ملف pos.py")

elif choice == "🏢 إدارة الفروع":
    if modules_dict["branches"] and hasattr(modules_dict["branches"], "show_page"):
        modules_dict["branches"].show_page()
    else: st.warning("⚠️ ملف شاشة إدارة الفروع (branches.py) غير متاح.")

elif choice == "👥 إدارة المستخدمين":
    if modules_dict["users"] and hasattr(modules_dict["users"], "show_page"):
        modules_dict["users"].show_page()
    else: st.warning("⚠️ ملف شاشة إدارة المستخدمين (users.py) غير متاح.")

elif choice == "➕ الفائض والتوالف والمرتجعات وتعديل السعر":
    if modules_dict["adjustments"] and hasattr(modules_dict["adjustments"], "show_page"):
        modules_dict["adjustments"].show_page()
    else: st.warning("⚠️ ملف شاشة الفائض والتوالف (adjustments.py) غير متاح.")

elif choice == "📁 استيراد Excel":
    if modules_dict["items_import"] and hasattr(modules_dict["items_import"], "show_page"):
        modules_dict["items_import"].show_page()
    else: st.warning("⚠️ ملف شاشة الاستيراد (items_import.py) غير متاح.")

elif choice == "💰 المصروفات":
    if modules_dict["expenses"] and hasattr(modules_dict["expenses"], "show_page"):
        modules_dict["expenses"].show_page()
    else: st.warning("⚠️ ملف شاشة المصروفات (expenses.py) غير متاح.")

elif choice == "👥 جهات التعامل":
    if modules_dict["parties"] and hasattr(modules_dict["parties"], "show_page"):
        modules_dict["parties"].show_page()
    else: st.warning("⚠️ ملف شاشة جهات التعامل (parties.py) غير متاح.")

elif choice == "📥 المشتريات":
    if modules_dict["purchases"] and hasattr(modules_dict["purchases"], "show_page"):
        modules_dict["purchases"].show_page()
    else: st.warning("⚠️ ملف شاشة المشتريات (purchases.py) غير متاح.")

elif choice == "🔄 تزويد الفروع والأرشيف":
    if modules_dict["transfers"] and hasattr(modules_dict["transfers"], "show_page"):
        modules_dict["transfers"].show_page()
    else: st.info("🔄 شاشة تزويد الفروع والأرشيف قيد التجهيز.")

elif choice == "⭐ لوحة المفضلة (1-20)":
    if modules_dict["favorites"] and hasattr(modules_dict["favorites"], "show_page"):
        modules_dict["favorites"].show_page()
    else: st.warning("⚠️ ملف شاشة المفضلة (favorites.py) غير متاح.")

elif choice == "📦 إدارة المخزن والفروع":
    if modules_dict["inventory"] and hasattr(modules_dict["inventory"], "show_page"):
        modules_dict["inventory"].show_page()
    else: st.warning("⚠️ ملف شاشة إدارة المخزن والفروع (inventory.py) غير متاح.")

elif choice == "⚙️ الجرد والتصفير السنوي":
    st.info("⚙️ شاشة الجرد السنوي قيد التجهيز.")

elif choice == "🥜 التحميص والخلط":
    if modules_dict["roasting_blending"] and hasattr(modules_dict["roasting_blending"], "show_page"):
        modules_dict["roasting_blending"].show_page()
    else: st.warning("⚠️ ملف شاشة التحميص والخلط (roasting_blending.py) غير متاح.")

elif choice == "📊 التقارير والأرباح":
    if modules_dict["reports"] and hasattr(modules_dict["reports"], "show_page"):
        modules_dict["reports"].show_page()
    else: st.warning("⚠️ ملف شاشة التقارير والأرباح (reports.py) غير متاح.")
