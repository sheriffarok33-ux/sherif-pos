import os
import streamlit as st
import importlib

# إعدادات الصفحة الأساسية
st.set_page_config(
    page_title="مجموعة أبو زيد - نظام المحامص والمخازن الذكي",
    layout="wide",
    initial_sidebar_state="expanded",
)

# تنسيق الواجهة والأزرار
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
    div.stButton > button, div.stButton > button * { color: #ffffff !important; }
    div.stButton > button { 
        border-radius: 8px; font-weight: 900 !important; height: 50px; 
        background: linear-gradient(135deg, #0284c7, #0369a1); border: none;
        box-shadow: 0 3px 6px rgba(0,0,0,0.15); font-size: 18px !important;
    }
    [data-testid="stSidebar"] { background-color: #0f172a; }
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] span, [data-testid="stSidebar"] p { color: #ffffff !important; }
    [data-testid="stSidebar"] .stButton>button {
        background-color: #1e293b; color: #ffffff !important; border: 1px solid #334155;
        border-radius: 10px; padding: 12px 15px; text-align: right; font-weight: 900 !important;
        margin-bottom: 8px; height: auto;
    }
    </style>
""", unsafe_allow_html=True)

if not os.path.exists("item_images"): 
    os.makedirs("item_images")

# تهيئة قاعدة البيانات بأمان تام
try:
    from database import get_db_connection, create_tables
    create_tables()
except Exception as e:
    st.error(f"⚠️ خطأ في قاعدة البيانات: {e}")

# تحميل آمن للشاشات لمنع انهيار التطبيق نهائياً
def load_module(mod_name):
    try:
        return importlib.import_module(mod_name)
    except Exception:
        return None

pos = load_module("pos")
users = load_module("users")
inventory = load_module("inventory")
purchases = load_module("purchases")
parties = load_module("parties")
reports = load_module("reports")
transfers = load_module("transfers")
roasting_blending = load_module("roasting_blending")
items_import = load_module("items_import")
favorites = load_module("favorites")

# تهيئة متغيرات الجلسة
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "username" not in st.session_state: st.session_state["username"] = ""
if "role" not in st.session_state: st.session_state["role"] = ""
if "user_id" not in st.session_state: st.session_state["user_id"] = None
if "branch_id" not in st.session_state: st.session_state["branch_id"] = None
if "cart" not in st.session_state: st.session_state["cart"] = []
if "page" not in st.session_state: st.session_state["page"] = "🛒 نقطة البيع (POS)"

def set_page(page_name): 
    st.session_state["page"] = page_name
    st.rerun()

# نظام الصلاحيات
def check_user_permission(menu_name):
    role = st.session_state.get("role", "")
    if role in ["Admin", "General_Supervisor"]: return True
    if role == "Cashier": return menu_name in ["🛒 نقطة البيع (POS)", "⭐ لوحة المفضلة (1-20)"]
    if role == "Viewer": return menu_name in ["📊 التقارير والأرباح"]
    if role == "Branch_Supervisor": return menu_name in ["🛒 نقطة البيع (POS)", "📦 إدارة المخزن والفروع", "📥 المشتريات", "👥 جهات التعامل", "🥜 التحميص والخلط"]
    return False

# بوابة الدخول
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
                        st.session_state["logged_in"] = True
                        st.session_state["username"] = user["username"]
                        st.session_state["role"] = user["role"]
                        st.session_state["user_id"] = user["id"]
                        st.session_state["branch_id"] = user["branch_id"]
                        st.rerun()
                    else: 
                        st.error("🎭 اسم المستخدم أو كلمة المرور غير صحيحة! (الافتراضي: admin / admin123)")
                except Exception as ex:
                    st.error(f"خطأ في تسجيل الدخول: {ex}")
    st.stop()

# القائمة الجانبية
st.sidebar.markdown("<h2 style='text-align: center; color: white;'>🥜 مجموعة أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; color: white;'><b>{st.session_state['username']} | {st.session_state['role']}</b></p>", unsafe_allow_html=True)
st.sidebar.markdown("---")

DEFAULT_MENUS = [
    "🛒 نقطة البيع (POS)",
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
        btn_label = f"📍 {menu_name}" if st.session_state["page"] == menu_name else menu_name
        if st.sidebar.button(btn_label, use_container_width=True, key=f"sidebar_btn_{menu_name}"):
            set_page(menu_name)

st.sidebar.markdown("---")
if st.sidebar.button("🚪 تسجيل الخروج", use_container_width=True):
    st.session_state.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")

# موجه الشاشات الآمن
choice = st.session_state.get("page", "🛒 نقطة البيع (POS)")

if choice == "🛒 نقطة البيع (POS)":
    if pos and hasattr(pos, "show_page"): pos.show_page()
    else: st.error("⚠️ شاشة نقطة البيع قيد التحميل أو الملف غير موجود.")
elif choice == "👥 إدارة المستخدمين":
    if users and hasattr(users, "show_page"): users.show_page()
    else: st.error("⚠️ شاشة إدارة المستخدمين غير متوفرة.")
elif choice == "📦 إدارة المخزن والفروع":
    if inventory and hasattr(inventory, "show_page"): inventory.show_page()
    else: st.error("⚠️ شاشة إدارة المخزن غير متوفرة.")
elif choice == "📥 المشتريات":
    if purchases and hasattr(purchases, "show_page"): purchases.show_page()
    else: st.error("⚠️ شاشة المشتريات غير متوفرة.")
elif choice == "👥 جهات التعامل":
    if parties and hasattr(parties, "show_page"): parties.show_page()
    else: st.error("⚠️ شاشة جهات التعامل غير متوفرة.")
elif choice == "📊 التقارير والأرباح":
    if reports and hasattr(reports, "show_page"): reports.show_page()
    else: st.error("⚠️ شاشة التقارير غير متوفرة.")
elif choice == "🔄 تزويد الفروع والأرشيف":
    if transfers and hasattr(transfers, "show_page"): transfers.show_page()
    else: st.error("⚠️ شاشة التزويد غير متوفرة.")
elif choice == "🥜 التحميص والخلط":
    if roasting_blending and hasattr(roasting_blending, "show_page"): roasting_blending.show_page()
    else: st.error("⚠️ شاشة التحميص غير متوفرة.")
elif choice == "📁 استيراد Excel":
    if items_import and hasattr(items_import, "show_page"): items_import.show_page()
    else: st.error("⚠️ شاشة الاستيراد غير متوفرة.")
elif choice == "⭐ لوحة المفضلة (1-20)":
    if favorites and hasattr(favorites, "show_page"): favorites.show_page()
    else: st.error("⚠️ شاشة المفضلة غير متوفرة.")
else:
    st.info("يرجى اختيار شاشة صحيحة من القائمة الجانبية.")
