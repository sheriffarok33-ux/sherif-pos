import os
import streamlit as st

# ==========================================
# 1. إعداد الصفحة والتنسيق
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
# 2. استدعاء قاعدة البيانات
# ==========================================
try:
    from database import create_tables as init_db, get_db_connection
    init_db()
except Exception as e:
    st.error("⚠️ خطأ في تحميل قاعدة البيانات. تأكد من وجود ملف database.py")
    st.stop()

# ==========================================
# 3. الاستدعاء الآمن للشاشات (لمنع انهيار النظام)
# ==========================================
modules = {}
missing_modules = []

# قائمة بجميع ملفات النظام المطلوبة
core_files = ["users", "pos", "transfers", "roasting_blending", "reports", "purchases", "parties", "items_import", "inventory", "favorites", "branches"]

for mod in core_files:
    try:
        modules[mod] = __import__(mod)
    except Exception:
        modules[mod] = None
        missing_modules.append(mod)

# ==========================================
# 4. إدارة الجلسات
# ==========================================
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "username" not in st.session_state: st.session_state["username"] = ""
if "role" not in st.session_state: st.session_state["role"] = ""
if "user_id" not in st.session_state: st.session_state["user_id"] = None
if "branch_id" not in st.session_state: st.session_state["branch_id"] = None
if "page" not in st.session_state: st.session_state["page"] = "🛒 نقطة البيع (POS)"

def set_page(page_name):
    st.session_state["page"] = page_name
    st.rerun()

def check_user_permission(menu_name):
    role = st.session_state.get("role", "")
    if role in ["Admin", "General_Supervisor"]: return True
    if role == "Cashier": return menu_name in ["🛒 نقطة البيع (POS)", "⭐ لوحة المفضلة (1-20)"]
    if role == "Viewer": return menu_name in ["📊 التقارير والأرباح"]
    if role == "Branch_Supervisor": return menu_name in ["🛒 نقطة البيع (POS)", "📦 إدارة المخزن والفروع", "📥 المشتريات", "👥 جهات التعامل", "🥜 التحميص والخلط", "⭐ لوحة المفضلة (1-20)"]
    return False

# ==========================================
# 5. شاشة الدخول (Login)
# ==========================================
if not st.session_state["logged_in"]:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown('<h1 style="text-align: center; color: #0f172a;">🔐 نظام محامص أبو زيد</h1>', unsafe_allow_html=True)

        if missing_modules:
            st.warning(f"⚠️ تنبيه إداري: الملفات التالية غير موجودة في الخادم وتم إيقاف شاشاتها مؤقتاً: {', '.join(missing_modules)}")

        with st.form("login_form"):
            u_name = st.text_input("اسم المستخدم")
            u_pass = st.text_input("كلمة المرور", type="password")
            submit = st.form_submit_button("🚀 دخول للنظام", use_container_width=True)

            if submit:
                conn = get_db_connection()
                user = conn.execute("SELECT id, username, role, branch_id FROM users WHERE username = ? AND password = ?", (u_name, u_pass)).fetchone()
                conn.close()
                if user:
                    st.session_state.update({"logged_in": True, "username": user["username"], "role": user["role"], "user_id": user["id"], "branch_id": user["branch_id"]})
                    st.rerun()
                else:
                    st.error("🎭 **اسم المستخدم أو كلمة المرور غير صحيحة!**")
    st.stop()

# ==========================================
# 6. القائمة الجانبية (Sidebar) والتوجيه الآمن
# ==========================================
with st.sidebar:
    st.markdown("<h2 style='text-align: center; color: #38bdf8;'>🥜 أبو زيد</h2>", unsafe_allow_html=True)
    st.markdown(f"<p style='text-align: center; font-size:14px;'>المستخدم: <b>{st.session_state['username']}</b> | الصلاحية: <b>{st.session_state['role']}</b></p>", unsafe_allow_html=True)
    st.markdown("---")

    menus_map = {
        "🛒 نقطة البيع (POS)": "pos",
        "🏢 إدارة الفروع": "branches",
        "👥 إدارة المستخدمين": "users",
        "⭐ لوحة المفضلة (1-20)": "favorites",
        "📦 إدارة المخزن والفروع": "inventory",
        "🔄 تزويد الفروع والأرشيف": "transfers",
        "📁 استيراد Excel": "items_import",
        "👥 جهات التعامل": "parties",
        "📥 المشتريات": "purchases",
        "🥜 التحميص والخلط": "roasting_blending",
        "📊 التقارير والأرباح": "reports"
    }

    for menu_name, mod_key in menus_map.items():
        if check_user_permission(menu_name):
            # وضع علامة تحذير إذا كان الملف مفقوداً
            btn_label = f"📍 {menu_name}" if st.session_state["page"] == menu_name else menu_name
            if modules[mod_key] is None:
                btn_label = f"⚠️ {menu_name} (معطل)"

            if st.button(btn_label, use_container_width=True, key=f"btn_{mod_key}"):
                set_page(menu_name)

    st.markdown("---")
    if st.button("🚪 تسجيل الخروج", use_container_width=True):
        st.session_state.clear()
        st.rerun()

# ==========================================
# 7. عرض الشاشات وإدارة الأخطاء
# ==========================================
choice = st.session_state.get("page")
if not check_user_permission(choice):
    st.error("❌ غير مصرح لك بالوصول إلى هذه الشاشة.")
    st.stop()

target_module_key = menus_map.get(choice)
target_module = modules.get(target_module_key)

if target_module:
    target_module.show_page()
else:
    st.error(f"❌ عذراً يا مهندس شريف، لا يمكن فتح هذه الشاشة لأن ملف `{target_module_key}.py` غير موجود في مستودعك أو به خطأ داخلي.")
    st.info("💡 **طريقة الحل:** افتح GitHub، وتأكد أن الملف موجود تماماً بهذا الاسم (حروف صغيرة)، أو قم برفعه من جديد.")
