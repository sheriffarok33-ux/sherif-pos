import os
import streamlit as st
from database import initialize_database, get_db_connection

# تهيئة قاعدة البيانات عند بدء تشغيل التطبيق
initialize_database()

# إعدادات الصفحة الأساسية
st.set_page_config(
    page_title="مجموعة أبو زيد - نظام المحامص والمخازن الذكي",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ستايل CSS الموحد لضمان وضوح وتناسق الواجهة
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
    div[data-testid="InputInstructions"] { display: none !important; }
    </style>
""", unsafe_allow_html=True)

if not os.path.exists("item_images"): 
    os.makedirs("item_images")

# تهيئة متغيرات الجلسة
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

# نظام الصلاحيات الآمن
def check_user_permission(menu_name):
    role = st.session_state.get("role", "")
    if role in ["Admin", "General_Supervisor"]: return True
    if role == "Cashier":
        return menu_name in ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)", "⭐ لوحة المفضلة (1-20)"]
    if role == "Viewer":
        return menu_name in ["🏠 الرئيسية واللوحة", "📊 التقارير والأرباح"]
    if role == "Branch_Supervisor":
        return menu_name in ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)", "📦 إدارة المخزن والفروع"]
    return False

# --- استيراد كافة الشاشات من المجلد الرئيسي مباشرة ---
try:
    import pos
except ImportError:
    pos = None

try:
    import branches
except ImportError:
    branches = None

try:
    import users
except ImportError:
    users = None

try:
    import items_import
except ImportError:
    items_import = None

try:
    import parties
except ImportError:
    parties = None

try:
    import purchases
except ImportError:
    purchases = None

try:
    import transfers
except ImportError:
    transfers = None

try:
    import favorites
except ImportError:
    favorites = None

try:
    import inventory
except ImportError:
    inventory = None

try:
    import roasting_blending
except ImportError:
    roasting_blending = None

try:
    import reports
except ImportError:
    reports = None


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
                    st.error("🎭 **اسم المستخدم أو كلمة المرور غير صحيحة!** (الافتراضي: admin / admin123)")
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
    "🔄 تزويد الفروع والأرشيف",
    "📁 استيراد Excel",
    "👥 جهات التعامل",
    "📥 المشتريات",
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

# --- موجه الشاشات (Router) الرئيسي ---
choice = st.session_state.get("page", "🏠 الرئيسية واللوحة")

if not check_user_permission(choice):
    st.error("❌ غير مصرح لك بالوصول إلى هذه الشاشة.")
    st.stop()

if choice == "🏠 الرئيسية واللوحة":
    st.title("🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية")
    st.info("مرحباً بك في النظام السحابي لإدارة المحامص والمخازن. اختر الشاشة المطلوبة من القائمة الجانبية.")

elif choice == "🛒 نقطة البيع (POS)":
    if pos: pos.show_page()
    else: st.error("⚠️ شاشة نقطة البيع غير متوفرة.")

elif choice == "🏢 إدارة الفروع":
    if branches: branches.show_page()
    else: st.warning("⚠️ ملف شاشة إدارة الفروع غير موجود.")

elif choice == "👥 إدارة المستخدمين":
    if users: users.show_page()
    else: st.warning("⚠️ ملف شاشة إدارة المستخدمين غير موجود.")

elif choice == "📁 استيراد Excel":
    if items_import: items_import.show_page()
    else: st.warning("⚠️ ملف شاشة الاستيراد غير موجود.")

elif choice == "👥 جهات التعامل":
    if parties: parties.show_page()
    else: st.warning("⚠️ ملف شاشة جهات التعامل غير موجود.")

elif choice == "📥 المشتريات":
    if purchases: purchases.show_page()
    else: st.warning("⚠️ ملف شاشة المشتريات غير موجود.")

elif choice == "🔄 تزويد الفروع والأرشيف":
    if transfers: transfers.show_page()
    else: st.warning("⚠️ ملف شاشة التزويد غير موجود.")

elif choice == "⭐ لوحة المفضلة (1-20)":
    if favorites: favorites.show_page()
    else: st.warning("⚠️ ملف شاشة المفضلة غير موجود.")

elif choice == "📦 إدارة المخزن والفروع":
    if inventory: inventory.show_page()
    else: st.warning("⚠️ ملف شاشة إدارة المخزن غير موجود.")

elif choice == "🥜 التحميص والخلط":
    if roasting_blending: roasting_blending.show_page()
    else: st.warning("⚠️ ملف شاشة التحميص والخلط غير موجود.")

elif choice == "📊 التقارير والأرباح":
    if reports: reports.show_page()
    else: st.warning("⚠️ ملف شاشة التقارير غير موجود.")
