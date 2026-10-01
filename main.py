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


def load_appearance_settings():
    defaults = {
        "app_bg_color": "#f8fafc",
        "sidebar_bg_color": "#0f172a",
        "sidebar_button_color": "#1e293b",
        "button_color": "#0284c7",
        "button_hover_color": "#0369a1",
        "text_color": "#000000",
        "font_size": "17",
        "font_weight": "900",
        "logo_data": "",
        "login_bg_data": "",
    }
    conn = None
    try:
        conn = get_db_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        rows = conn.execute(
            "SELECT setting_key, setting_value FROM app_settings"
        ).fetchall()
        for row in rows:
            defaults[row["setting_key"]] = row["setting_value"] or ""
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
    return defaults


appearance = load_appearance_settings()

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


# تطبيق إعدادات المظهر المحفوظة فوق التنسيق الافتراضي
_login_bg_css = ""
if appearance.get("login_bg_data") and not st.session_state.get("logged_in"):
    _login_bg_css = f"""
        background-image:
            linear-gradient(rgba(255,255,255,0.78), rgba(255,255,255,0.78)),
            url("{appearance['login_bg_data']}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    """

st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {appearance['app_bg_color']} !important;
        {_login_bg_css}
    }}
    html, body, [class*="css"], p, span, div, label,
    h1, h2, h3, h4, h5, h6, table, th, td {{
        color: {appearance['text_color']} !important;
        font-weight: {appearance['font_weight']} !important;
        font-size: {appearance['font_size']}px !important;
    }}
    div.stButton > button {{
        background: {appearance['button_color']} !important;
        font-weight: {appearance['font_weight']} !important;
    }}
    div.stButton > button:hover {{
        background: {appearance['button_hover_color']} !important;
    }}
    [data-testid="stSidebar"] {{
        background-color: {appearance['sidebar_bg_color']} !important;
    }}
    [data-testid="stSidebar"] .stButton > button {{
        background: {appearance['sidebar_button_color']} !important;
    }}
    [data-testid="stSidebar"] .stButton > button:hover {{
        background: {appearance['button_color']} !important;
    }}
    </style>
    """,
    unsafe_allow_html=True
)

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

def check_user_permission(menu_name):
    role = st.session_state.get("role", "")
    if menu_name == "🧹 تهيئة النظام لأول تشغيل":
        return role == "Admin"
    if role in ["Admin", "General_Supervisor"]: return True
    if role == "Cashier": return menu_name in ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)"]
    if role == "Viewer": return menu_name in ["🏠 الرئيسية واللوحة", "📊 التقارير والأرباح"]
    if role == "Branch_Supervisor": return menu_name in ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)", "📦 إدارة المخزن والفروع"]
    return False

# --- بوابة الدخول ---
if not st.session_state["logged_in"]:
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        if appearance.get("logo_data"):
            st.image(appearance["logo_data"], width=180)

        st.title("🔐 بوابة دخول نظام المحامص")
        st.subheader("مجموعة أبو زيد التجارية")

        with st.form("login_form"):
            u_name = st.text_input("اسم المستخدم")
            u_pass = st.text_input("كلمة المرور", type="password")
            submit = st.form_submit_button("🚀 دخول للنظام", use_container_width=True)

        if submit:
            conn = None
            try:
                conn = get_db_connection()
                user = conn.execute(
                    """
                    SELECT *
                    FROM users
                    WHERE username = ?
                      AND password = ?
                      AND is_active = 1
                    """,
                    (u_name.strip(), u_pass)
                ).fetchone()

                if user:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = user["username"]
                    st.session_state["role"] = user["role"]
                    st.session_state["user_id"] = user["id"]
                    st.session_state["branch_id"] = user["branch_id"]
                    st.session_state["page"] = "🏠 الرئيسية واللوحة"
                    st.rerun()
                else:
                    st.error("❌ اسم المستخدم أو كلمة المرور غير صحيحة، أو الحساب موقوف.")

            except Exception as e:
                st.error("❌ تعذر تسجيل الدخول حالياً.")
                st.code(str(e))
            finally:
                if conn:
                    conn.close()

    st.stop()


# --- القائمة الجانبية الجديدة (أقسام رئيسية فقط) ---
st.sidebar.markdown("<h2 style='text-align: center; color: white;'>🥜 مجموعة أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(
    f"<p style='text-align: center; color: white;'><b>{st.session_state['username']} | {st.session_state['role']}</b></p>",
    unsafe_allow_html=True
)
st.sidebar.markdown("---")

MENU_GROUPS = {
    "🏠 الرئيسية": [
        ("🏠 الرئيسية واللوحة", "🏠 لوحة التحكم"),
    ],
    "🛒 المبيعات والعملاء": [
        ("🛒 نقطة البيع (POS)", "🛒 فاتورة بيع"),
        ("👥 جهات التعامل", "👥 العملاء والحسابات"),
        ("📊 التقارير والأرباح", "📋 تقارير وأرشيف المبيعات"),
    ],
    "📥 المشتريات والموردون": [
        ("📥 المشتريات", "➕ فاتورة توريد"),
        ("👥 جهات التعامل", "👥 الموردون والحسابات"),
        ("📊 التقارير والأرباح", "📋 أرشيف وتقارير المشتريات"),
    ],
    "📦 المخزون والأصناف": [
        ("📦 إدارة المخزن والفروع", "📦 الأصناف والأرصدة"),
        ("➕ الفائض والتوالف والمرتجعات وتعديل السعر", "♻️ التالف والمرتجع والتسويات"),
        ("📁 استيراد Excel", "📥 استيراد Excel"),
    ],
    "☕ التحميص والخلط": [
        ("🥜 التحميص والخلط", "🔥 التحميص والخلط"),
    ],
    "🔄 التحويلات والفروع": [
        ("🔄 تزويد الفروع والأرشيف", "🔄 التزويد والتحويلات"),
        ("🏢 إدارة الفروع", "🏢 إدارة الفروع"),
    ],
    "💰 المالية": [
        ("💰 المصروفات", "💰 المصروفات والإيرادات"),
    ],
    "📊 التقارير": [
        ("📊 التقارير والأرباح", "📊 التقارير والأرباح"),
    ],
    "⚙️ الإدارة والإعدادات": [
        ("🎨 تخصيص المظهر", "🎨 تخصيص المظهر"),
        ("👥 إدارة المستخدمين", "👥 المستخدمون والصلاحيات"),
        ("⚙️ الجرد والتصفير السنوي", "📆 إقفال وأرشفة السنة"),
        ("🧹 تهيئة النظام لأول تشغيل", "🧹 تهيئة النظام"),
    ],
}

def allowed_group_entries(group_name):
    return [
        (target, label)
        for target, label in MENU_GROUPS.get(group_name, [])
        if check_user_permission(target)
    ]

for group_name in MENU_GROUPS:
    entries = allowed_group_entries(group_name)
    if entries:
        if st.sidebar.button(
            group_name,
            use_container_width=True,
            key=f"sidebar_group_{group_name}"
        ):
            if group_name == "🏠 الرئيسية":
                set_page("🏠 الرئيسية واللوحة")
            else:
                st.session_state["page"] = f"__GROUP__::{group_name}"
                st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("🚪 تسجيل الخروج", use_container_width=True):
    st.session_state.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")

# --- منطقة توجيه الشاشات واللوحة الرئيسية ---
choice = st.session_state.get("page", "🏠 الرئيسية واللوحة")

# لو المستخدم داخل قسم رئيسي، نعرض لوحة أزرار داخلية.
if choice.startswith("__GROUP__::"):
    group_name = choice.split("::", 1)[1]
    entries = allowed_group_entries(group_name)

    st.markdown(
        f"<h2 style='direction:rtl;text-align:right;'>"
        f"{group_name}</h2>",
        unsafe_allow_html=True
    )
    st.caption("اختر العملية المطلوبة من الأزرار التالية.")

    if not entries:
        st.warning("⚠️ لا توجد عمليات متاحة لك داخل هذا القسم حسب صلاحياتك.")
        st.stop()

    cols = st.columns(3)
    for idx, (target, label) in enumerate(entries):
        if cols[idx % 3].button(
            label,
            use_container_width=True,
            key=f"group_action_{group_name}_{target}_{idx}"
        ):
            set_page(target)

    st.stop()

if not check_user_permission(choice):
    st.error("❌ غير مصرح لك بالوصول إلى هذه الشاشة.")
    st.stop()

if choice == "🏠 الرئيسية واللوحة":
    role = st.session_state.get("role", "")
    username = st.session_state.get("username", "")

    st.markdown("""
        <style>
        .rtl-container { direction: rtl !important; text-align: right !important; }
        .dashboard-banner { 
            background-color: #f0fdf4; 
            padding: 18px; 
            border-radius: 10px; 
            border: 2px solid #22c55e; 
            margin-bottom: 20px; 
            color: #166534; 
            direction: rtl; 
            text-align: right; 
        }
        .dashboard-banner * {
            color: #000000 !important;
            font-family: 'Tajawal', sans-serif !important;
            font-weight: 900 !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h3 class="rtl-container" style="color: #0f172a; font-weight: 900;">🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية</h3>', unsafe_allow_html=True)
    
    st.markdown(f"""
        <div class="dashboard-banner">
            <h4 style="margin-top:0; color:#16a34a;">👋 مرحباً بك يا {username} في النظام السحابي لإدارة المحامص والمخازن.</h4>
            <p style="font-size: 16px; margin: 0;">نتمنى لك وقتاً موفقاً في إنجاز مهامك اليومية.</p>
        </div>
    """, unsafe_allow_html=True)

    if role in ["Admin", "General_Supervisor"]:
        conn = get_db_connection()
        total_sales_res = conn.execute("SELECT SUM(total_amount) FROM invoices").fetchone()
        total_sales = total_sales_res[0] if total_sales_res and total_sales_res[0] else 0.0

        branches_count = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
        
        total_stock_res = conn.execute("SELECT SUM(quantity) FROM items").fetchone()
        total_stock = total_stock_res[0] if total_stock_res and total_stock_res[0] else 0.0

        users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()

        st.markdown('<p class="rtl-container" style="font-weight: 900; font-size: 18px; color: #0f172a;">📊 ملخص حركة العمل والأداء المالي العام:</p>', unsafe_allow_html=True)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1: st.metric(label="💰 إجمالي المبيعات العامة", value=f"{total_sales:,.2f} د.ل")
        with col2: st.metric(label="🏢 الفروع والمخازن", value=f"{branches_count} فرع")
        with col3: st.metric(label="📦 إجمالي المخزون", value=f"{total_stock:,.2f}")
        with col4: st.metric(label="👥 طاقم العمل", value=f"{users_count} موظف")
        st.markdown("---")
    else:
        st.info("🛒 تم إعداد الشاشة بنجاح. يمكنك الانتقال مباشرة عبر القائمة الجانبية إلى قسم (نقطة البيع POS) لبدء تسجيل الفواتير وخدمة الزبائن.")

elif choice == "🛒 نقطة البيع (POS)":
    try:
        from views import pos
        pos.show_page()
    except ImportError:
        st.info("🛒 شاشة نقطة البيع قيد الترتيب...")
elif choice == "🏢 إدارة الفروع":
    try:
        from views import branches
        branches.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة إدارة الفروع غير موجود.")
elif choice == "👥 إدارة المستخدمين":
    try:
        from views import users
        users.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة إدارة المستخدمين غير موجود.")
elif choice == "➕ الفائض والتوالف والمرتجعات وتعديل السعر":
    try:
        from views import damages_returns
        damages_returns.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة الفائض والتوالف والمرتجعات غير موجود.")
elif choice == "📁 استيراد Excel":
    try:
        from views import items_import
        items_import.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة الاستيراد غير موجود.")
elif choice == "💰 المصروفات":
    try:
        from views import expenses
        expenses.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة المصروفات غير موجود.")
elif choice == "👥 جهات التعامل":
    try:
        from views import parties
        parties.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة جهات التعامل غير موجود.")
elif choice == "📥 المشتريات":
    try:
        from views import purchases
        purchases.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة المشتريات غير موجود.")
elif choice == "🔄 تزويد الفروع والأرشيف":
    try:
        from views import transfers
        transfers.show_page()
    except ImportError:
        st.info("🔄 شاشة تزويد الفروع والأرشيف قيد التجهيز.")
elif choice == "📦 إدارة المخزن والفروع":
    try:
        from views import inventory
        inventory.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة إدارة المخزن والفروع غير موجود.")
elif choice == "⚙️ الجرد والتصفير السنوي":
    try:
        from views import annual_reset
        annual_reset.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة الجرد والتصفير السنوي غير موجود.")
elif choice == "🧹 تهيئة النظام لأول تشغيل":
    try:
        from views import initial_setup_reset
        initial_setup_reset.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة تهيئة النظام لأول تشغيل غير موجود.")
elif choice == "🥜 التحميص والخلط":
    try:
        from views import roasting_blending
        roasting_blending.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة التحميص والخلط غير موجود.")
elif choice == "📊 التقارير والأرباح":
    try:
        from views import reports
        reports.show_page()
    except ImportError:
        st.warning("⚠️ ملف شاشة التقارير والأرباح غير موجود.")
