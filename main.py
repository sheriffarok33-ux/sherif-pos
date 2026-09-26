import streamlit as st
import os

# إنشاء مجلد للصور إذا لم يكن موجوداً
if not os.path.exists("item_images"):
    os.makedirs("item_images")

# إعداد الصفحة وتكوين الواجهة العربية (يجب أن تكون أول أمر Streamlit)
st.set_page_config(
    page_title="برنامج محامص أبو زيد",
    page_icon="🥜",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 🌟 تنسيق CSS شامل لفرض الاتجاه العربي (RTL) والألوان الزاهية
st.markdown("""
    <style>
    /* تطبيق الاتجاه العربي على مستوى التطبيق بالكامل */
    * {
        font-family: 'Tajawal', sans-serif !important;
        direction: rtl !important;
        text-align: right !important;
    }
    
    /* تنسيق القائمة الجانبية Sidebar */
    section[data-testid="stSidebar"] {
        background-color: #0f172a !important; /* لون كحلي داكن راقي */
        border-left: 2px solid #334155 !important;
    }
    
    /* تنسيق نصوص وعناصر القائمة الجانبية */
    section[data-testid="stSidebar"] * {
        color: #f8fafc !important; /* لون خط فاتح وواضح */
    }
    
    /* تنسيق أزرار التنقل الراديوية في القائمة الجانبية */
    div.row-widget.stRadio > div {
        background-color: transparent !important;
        padding: 5px;
    }
    div.row-widget.stRadio > div label {
        font-size: 18px !important;
        font-weight: 900 !important;
        padding: 10px 15px !important;
        border-radius: 8px !important;
        margin-bottom: 5px !important;
        transition: all 0.3s ease !important;
        cursor: pointer !important;
        background-color: rgba(255, 255, 255, 0.05) !important;
    }
    /* تأثير التحويم والنشط للأزرار الراديوية */
    div.row-widget.stRadio > div label:hover {
        background-color: rgba(255, 255, 255, 0.15) !important;
        transform: translateX(-5px);
    }
    div[data-testid="stRadio"] div[role="radiogroup"] label[data-checked="true"] {
        background-color: #2563eb !important; /* لون أزرق جذاب للعنصر النشط */
        color: #ffffff !important;
        border-right: 4px solid #60a5fa !important;
    }

    /* إخفاء الدوائر الخاصة بالأزرار الراديوية لجعلها تبدو كأزرار قائمة حقيقية */
    div[data-testid="stRadio"] div[role="radiogroup"] div[data-testid="stMarkdownContainer"] p {
        margin: 0 !important;
    }
    .st-bc, .st-bb, .st-ba, .st-b8, .st-bj { 
        display: none !important; 
    }
    
    /* تنسيق الأزرار الرئيسية في واجهة العمل */
    div.stButton > button {
        border-radius: 8px !important;
        font-weight: bold !important;
        font-size: 16px !important;
        transition: all 0.2s;
    }
    div.stButton > button[kind="primary"] {
        background-color: #0ea5e9 !important;
        color: white !important;
        border: none !important;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #0284c7 !important;
    }
    </style>
""", unsafe_allow_html=True)

from database import create_tables, get_db_connection
import branches, users, pos, purchases, inventory, transfers, items_import, reports, favorites, parties, roasting_blending

# التأكد من إنشاء الجداول في قاعدة البيانات
create_tables()

# ==========================================
# إدارة الجلسة (Session State) وتسجيل الدخول
# ==========================================
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""
if "role" not in st.session_state:
    st.session_state["role"] = ""
if "branch_id" not in st.session_state:
    st.session_state["branch_id"] = None

def login():
    st.markdown("""
        <div style="text-align: center; margin-bottom: 30px;">
            <h1 style="color: #0f172a;">🥜 محامص أبو زيد السحابي</h1>
            <p style="color: #64748b; font-size: 18px;">تسجيل الدخول للموظفين والمدراء</p>
        </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("👤 اسم المستخدم")
            password = st.text_input("🔑 كلمة المرور", type="password")
            submit = st.form_submit_button("تسجيل الدخول", type="primary", use_container_width=True)
            
            if submit:
                conn = get_db_connection()
                # جلب بيانات المستخدم من قاعدة البيانات
                user = conn.execute("SELECT id, username, role, branch_id FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
                conn.close()
                
                if user:
                    # 🌟 تخزين بيانات الجلسة بشكل صحيح ومستمر
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = user["username"]
                    st.session_state["role"] = user["role"]
                    st.session_state["branch_id"] = user["branch_id"]
                    st.session_state["user_id"] = user["id"]
                    st.success(f"مرحباً بك، {user['username']}!")
                    st.rerun()
                else:
                    st.error("❌ بيانات الدخول غير صحيحة.")

def logout():
    st.session_state.clear()
    st.rerun()

# ==========================================
# التوجيه والقائمة الجانبية (Sidebar)
# ==========================================
if not st.session_state["logged_in"]:
    login()
else:
    # القائمة الجانبية
    with st.sidebar:
        st.markdown(f"""
            <div style="text-align: center; margin-bottom: 20px; padding: 10px; background-color: rgba(255,255,255,0.1); border-radius: 10px;">
                <h3 style="margin: 0; color: #38bdf8;">🥜 محامص أبو زيد</h3>
                <p style="margin: 5px 0 0 0; color: #cbd5e1; font-size: 14px;">المستخدم: <b>{st.session_state['username']}</b></p>
                <p style="margin: 0; color: #94a3b8; font-size: 12px;">الصلاحية: {st.session_state['role']}</p>
            </div>
        """, unsafe_allow_html=True)
        
        # بناء قائمة الصفحات المتاحة حسب صلاحية المستخدم (Role)
        role = st.session_state["role"]
        menu_options = []
        
        if role in ["Admin", "General_Supervisor"]:
            menu_options = [
                "🛒 نقطة البيع (POS)",
                "📊 التقارير والأرباح",
                "🏢 إدارة الفروع",
                "👥 إدارة المستخدمين",
                "📦 الجرد والمخازن",
                "🔄 نظام التزويد (الفواتير)",
                "📥 المشتريات (تجار الجملة)",
                "🤝 جهات التعامل (الموردين والديون)",
                "🥜 التحميص والخلط",
                "📁 استيراد الأصناف",
                "⭐ المفضلة والصور"
            ]
        elif role == "Branch_Supervisor":
            menu_options = [
                "🛒 نقطة البيع (POS)",
                "📦 الجرد والمخازن",
                "📥 المشتريات (تجار الجملة)",
                "🤝 جهات التعامل (الموردين والديون)",
                "🥜 التحميص والخلط",
                "⭐ المفضلة والصور"
            ]
        else: # Cashier or Viewer
            menu_options = [
                "🛒 نقطة البيع (POS)",
                "⭐ المفضلة والصور"
            ]
            
        selected_page = st.radio("القائمة الرئيسية:", menu_options, label_visibility="collapsed")
        
        st.markdown("---")
        if st.button("🚪 تسجيل الخروج", use_container_width=True):
            logout()

    # توجيه المستخدم إلى الصفحة المختارة
    if selected_page == "🛒 نقطة البيع (POS)":
        pos.show_page()
    elif selected_page == "📊 التقارير والأرباح":
        reports.show_page()
    elif selected_page == "🏢 إدارة الفروع":
        branches.show_page()
    elif selected_page == "👥 إدارة المستخدمين":
        users.show_page()
    elif selected_page == "📦 الجرد والمخازن":
        inventory.show_page()
    elif selected_page == "🔄 نظام التزويد (الفواتير)":
        transfers.show_page()
    elif selected_page == "📥 المشتريات (تجار الجملة)":
        purchases.show_page()
    elif selected_page == "🤝 جهات التعامل (الموردين والديون)":
        parties.show_page()
    elif selected_page == "🥜 التحميص والخلط":
        roasting_blending.show_page()
    elif selected_page == "📁 استيراد الأصناف":
        items_import.show_page()
    elif selected_page == "⭐ المفضلة والصور":
        favorites.show_page()
