import os
import sys
import sqlite3
import pandas as pd
import streamlit as st
import importlib.util
from datetime import datetime, timedelta

# ضبط مسار الجذر وضمان رؤية الملفات
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# استيراد قاعدة البيانات الأساسية مع الحماية
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

# ستايل CSS الموحد لضمان وضوح الخطوط والأزرار
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
    </style>
""", unsafe_allow_html=True)

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

# دالة فحص الصلاحيات
def check_user_permission(menu_name):
    role = st.session_state.get("role", "")
    if role in ["Admin", "General_Supervisor"]: return True
    if role == "Cashier":
        return menu_name in ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)", "⭐ لوحة المفضلة (1-20)", "🔄 تزويد الفروع والأرشيف"]
    if role == "Viewer":
        return menu_name in ["🏠 الرئيسية واللوحة", "📊 التقارير والأرباح"]
    if role == "Branch_Supervisor":
        return menu_name in ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)", "📦 إدارة المخزن والفروع", "🔄 تزويد الفروع والأرشيف"]
    return False

# --- دالة تحميل الشاشات بمرونة تامة (تمنع انهيار التطبيق كلياً) ---
def load_screen_module(module_name):
    # محاولة البحث عن الملف بالاسم العادي أو بلاحقة _2
    possible_files = [f"{module_name}.py", f"{module_name}_2.py"]
    target_file = None
    
    for f in possible_files:
        full_path = os.path.join(current_dir, f)
        if os.path.exists(full_path):
            target_file = full_path
            break
            
    if not target_file:
        return None
        
    try:
        spec = importlib.util.spec_from_file_location(module_name, target_file)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        st.error(f"⚠️ خطأ أثناء تحميل شاشة ({module_name}): {e}")
        return None

# تحميل كافة وحدات الشاشات
screens_mapping = {
    "dashboard": load_screen_module("dashboard"),
    "pos": load_screen_module("pos"),
    "branches": load_screen_module("branches"),
    "users": load_screen_module("users"),
    "adjustments": load_screen_module("adjustments"),
    "items_import": load_screen_module("items_import"),
    "expenses": load_screen_module("expenses"),
    "parties": load_screen_module("parties"),
    "purchases": load_screen_module("purchases"),
    "transfers": load_screen_module("transfers"),
    "favorites": load_screen_module("favorites"),
    "inventory": load_screen_module("inventory"),
    "roasting_blending": load_screen_module("roasting_blending"),
    "reports": load_screen_module("reports")
}

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
                        st.error("🎭 **اسم المستخدم أو كلمة المرور غير صحيحة!** (التلقائي: admin / admin)")
                except Exception as db_err:
                    st.error(f"⚠️ خطأ في الاتصال بقاعدة البيانات: {db_err}")
    st.stop()

# --- القائمة الجانبية ---
st.sidebar.markdown("<h2 style='text-align: center; color: white;'>🥜 مجموعة أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; color: white;'><b>{st.session_state['username']} | {st.session_state['role']}</b></p>", unsafe_allow_html=True)
st.sidebar.markdown("---")

DEFAULT_MENUS = [
    "🏠 الرئيسية واللوحة",
    "🛒 نقطة البيع (POS)",
    "⭐ لوحة المفضلة (1-20)",
    "📦 إدارة المخزن والفروع",
    "➕ الفائض والتوالف والمرتجعات وتعديل السعر",
    "🔄 تزويد الفروع والأرشيف",
    "🏢 إدارة الفروع",
    "📁 استيراد Excel",
    "💰 المصروفات",
    "📥 المشتريات والموردين",
    "⚙️ الجرد والتصفير السنوي",
    "🥜 التحميص والخلط",
    "📊 التقارير والأرباح",
    "👥 إدارة المستخدمين"
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

# --- التوجيه الآمن للشاشات (Router) ---
choice = st.session_state.get("page", "🏠 الرئيسية واللوحة")

if not check_user_permission(choice):
    st.error("❌ غير مصرح لك بالوصول إلى هذه الشاشة.")
    st.stop()

# ربط القوائم بالوحدات المحملة بأمان
screens_routing = {
    "🏠 الرئيسية واللوحة": ("dashboard", "لوحة التحكم الرئيسية"),
    "🛒 نقطة البيع (POS)": ("pos", "شاشة نقطة البيع"),
    "🏢 إدارة الفروع": ("branches", "شاشة إدارة الفروع"),
    "👥 إدارة المستخدمين": ("users", "شاشة إدارة المستخدمين"),
    "⭐ لوحة المفضلة (1-20)": ("favorites", "شاشة لوحة المفضلة"),
    "📦 إدارة المخزن والفروع": ("inventory", "شاشة إدارة المخزن والفروع"),
    "➕ الفائض والتوالف والمرتجعات وتعديل السعر": ("adjustments", "شاشة الفائض والتوالف"),
    "🔄 تزويد الفروع والأرشيف": ("transfers", "شاشة تزويد الفروع والأرشيف"),
    "📁 استيراد Excel": ("items_import", "شاشة استيراد Excel"),
    "💰 المصروفات": ("expenses", "شاشة المصروفات"),
    "📥 المشتريات والموردين": ("purchases", "شاشة المشتريات"),
    "🥜 التحميص والخلط": ("roasting_blending", "شاشة التحميص والخلط"),
    "📊 التقارير والأرباح": ("reports", "شاشة التقارير والأرباح")
}

if choice in screens_routing:
    mod_key, screen_title = screens_routing[choice]
    mod_obj = screens_mapping.get(mod_key)
    if mod_obj and hasattr(mod_obj, "show_page"):
        mod_obj.show_page()
    else:
        st.warning(f"⚠️ {screen_title} (`{mod_key}.py`) غير متاحة حالياً أو جاري تجهيزها.")
elif choice == "⚙️ الجرد والتصفير السنوي":
    st.info("⚙️ شاشة الجرد والتصفير السنوي قيد التجهيز.")
else:
    st.error("❌ الشاشة غير مطلوبة أو غير معرفة.")
