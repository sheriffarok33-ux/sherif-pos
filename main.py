import os
import streamlit as st

# ==========================================
# 1. إعداد الصفحة وتكوين الواجهة
# ==========================================
st.set_page_config(
    page_title="مجموعة أبو زيد - نظام المحامص والمخازن الذكي",
    page_icon="🥜",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&display=swap');
    * { font-family: 'Tajawal', sans-serif !important; direction: rtl !important; text-align: right !important; }
    div.stButton > button { border-radius: 8px; font-weight: 900 !important; height: 50px; background: linear-gradient(135deg, #0284c7, #0369a1); color: #ffffff !important; border: none; }
    div.stButton > button:hover { background: linear-gradient(135deg, #0369a1, #075985); }
    [data-testid="stSidebar"] { background-color: #0f172a; }
    [data-testid="stSidebar"] * { color: #ffffff !important; }
    </style>
""", unsafe_allow_html=True)

if not os.path.exists("item_images"):
    os.makedirs("item_images")

# ==========================================
# 2. استدعاء قاعدة البيانات وتجنب أخطاء الاستيراد
# ==========================================
try:
    from database import create_tables, get_db_connection
    create_tables()
except ImportError:
    try:
        from database import initialize_database as create_tables, get_db_connection
        create_tables()
    except Exception as e:
        st.error(f"خطأ في الاتصال بقاعدة البيانات: {e}")

# ==========================================
# 3. استدعاء كافة شاشات المشروع الموجودة
# ==========================================
import users
import pos
import transfers
import roasting_blending
import reports
import purchases
import parties
import items_import
import inventory
import favorites

try:
    import branches
except ImportError:
    branches = None

try:
    import dashboard
except ImportError:
    dashboard = None

# ==========================================
# 4. إدارة الجلسات (Session State)
# ==========================================
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "username" not in st.session_state: st.session_state["username"] = ""
if "role" not in st.session_state: st.session_state["role"] = ""
if "user_id" not in st.session_state: st.session_state["user_id"] = None
if "branch_id" not in st.session_state: st.session_state["branch_id"] = None
if "page" not in st.session_state: st.session_state["page"] = "🛒 نقطة البيع (POS)"
if "cart" not in st.session_state: st.session_state["cart"] = []

def set_page(page_name):
    st.session_state["page"] = page_name
    st.rerun()

# ==========================================
# 5. نظام الصلاحيات الأمني
# ==========================================
def check_user_permission(menu_name):
    role = st.session_state.get("role", "")
    if role in ["Admin", "General_Supervisor"]: 
        return True
    if role == "Cashier": 
        return menu_name in ["🛒 نقطة البيع (POS)", "⭐ لوحة المفضلة (1-20)"]
    if role == "Viewer": 
        return menu_name in ["📊 التقارير والأرباح"]
    if role == "Branch_Supervisor": 
        return menu_name in ["🛒 نقطة البيع (POS)", "📦 إدارة المخزن والفروع", "📥 المشتريات", "👥 جهات التعامل", "🥜 التحميص والخلط", "⭐ لوحة المفضلة (1-20)"]
    return False

# ==========================================
# 6. بوابة الدخول (Login)
# ==========================================
if not st.session_state["logged_in"]:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown('<h1 style="text-align: center; color: #0f172a;">🔐 بوابة دخول نظام محامص أبو زيد</h1>', unsafe_allow_html=True)
        
        with st.form("login_form"):
            u_name = st.text_input("اسم المستخدم")
            u_pass = st.text_input("كلمة المرور", type="password")
            submit = st.form_submit_button("🚀 دخول للنظام", use_container_width=True)
            
            if submit:
                conn = get_db_connection()
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
# 7. القائمة الجانبية (Sidebar)
# ==========================================
with st.sidebar:
    st.markdown("<h2 style='text-align: center; color: #38bdf8;'>🥜 مجموعة أبو زيد</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; font-size:14px;'>المستخدم: <b>{st.session_state['username']}</b> | الصلاحية: <b>{st.session_state['role']}</b></p>", unsafe_allow_html=True)
    st.markdown("---")

    menus_map = {
        "🏠 الرئيسية واللوحة": dashboard,
        "🛒 نقطة البيع (POS)": pos,
        "🏢 إدارة الفروع": branches,
        "👥 إدارة المستخدمين": users,
        "⭐ لوحة المفضلة (1-20)": favorites,
        "📦 إدارة المخزن والفروع": inventory,
        "🔄 تزويد الفروع والأرشيف": transfers,
        "📁 استيراد Excel": items_import,
        "👥 جهات التعامل": parties,
        "📥 المشتريات": purchases,
        "🥜 التحميص والخلط": roasting_blending,
        "📊 التقارير والأرباح": reports
    }

    for menu_name, mod_obj in menus_map.items():
        if mod_obj is not None and check_user_permission(menu_name):
            btn_label = f"📍 {menu_name}" if st.session_state["page"] == menu_name else menu_name
            if st.button(btn_label, use_container_width=True, key=f"btn_{menu_name}"):
                set_page(menu_name)

    st.markdown("---")
    if st.button("🚪 تسجيل الخروج", use_container_width=True):
        st.session_state.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("<p style='text-align: center; font-size:12px; color: #94a3b8;'>ENG: SHERIF M. FAROK</p>", unsafe_allow_html=True)

# ==========================================
# 8. موجه الشاشات (Router)
# ==========================================
choice = st.session_state.get("page", "🛒 نقطة البيع (POS)")

if not check_user_permission(choice):
    st.error("❌ غير مصرح لك بالوصول إلى هذه الشاشة.")
    st.stop()

if choice == "🏠 الرئيسية واللوحة" and dashboard:
    dashboard.show_page()
elif choice == "🛒 نقطة البيع (POS)":
    pos.show_page()
elif choice == "🏢 إدارة الفروع" and branches:
    branches.show_page()
elif choice == "👥 إدارة المستخدمين":
    users.show_page()
elif choice == "📁 استيراد Excel":
    items_import.show_page()
elif choice == "👥 جهات التعامل":
    parties.show_page()
elif choice == "📥 المشتريات":
    purchases.show_page()
elif choice == "🔄 تزويد الفروع والأرشيف":
    transfers.show_page()
elif choice == "⭐ لوحة المفضلة (1-20)":
    favorites.show_page()
elif choice == "📦 إدارة المخزن والفروع":
    inventory.show_page()
elif choice == "🥜 التحميص والخلط":
    roasting_blending.show_page()
elif choice == "📊 التقارير والأرباح":
    reports.show_page()
else:
    pos.show_page()
