import streamlit as st
import os

# إعداد الصفحة وتكوين الواجهة (يجب أن يكون أول أمر في الملف)
st.set_page_config(
    page_title="برنامج محامص أبو زيد",
    page_icon="🥜",
    layout="wide",
    initial_sidebar_state="expanded"
)

# إنشاء مجلد للصور إذا لم يكن موجوداً
if not os.path.exists("item_images"):
    os.makedirs("item_images")

# تنسيق CSS لضبط الاتجاه والألوان
st.markdown("""
    <style>
    * { font-family: 'Tajawal', sans-serif !important; direction: rtl !important; text-align: right !important; }
    section[data-testid="stSidebar"] { background-color: #0f172a !important; border-left: 2px solid #334155 !important; }
    section[data-testid="stSidebar"] * { color: #f8fafc !important; }
    div.stButton > button { border-radius: 8px !important; font-weight: bold !important; }
    div.stButton > button[kind="primary"] { background-color: #0ea5e9 !important; color: white !important; border: none !important; }
    </style>
""", unsafe_allow_html=True)

# 🌟 الاستدعاء الصحيح للدوال من ملف database.py الأحدث
from database import create_tables, get_db_connection
import branches, users, pos, purchases, inventory, transfers, items_import, reports, favorites, parties, roasting_blending

# التأكد من إنشاء الجداول عند التشغيل
create_tables()

# ==========================================
# إدارة الجلسة (Session State) وتسجيل الدخول
# ==========================================
if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "username" not in st.session_state: st.session_state["username"] = ""
if "role" not in st.session_state: st.session_state["role"] = ""
if "branch_id" not in st.session_state: st.session_state["branch_id"] = None

def login():
    st.markdown('<div style="text-align: center; margin-bottom: 30px;"><h1 style="color: #0f172a;">🥜 محامص أبو زيد السحابي</h1><p style="color: #64748b; font-size: 18px;">تسجيل الدخول للموظفين والمدراء</p></div>', unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            username = st.text_input("👤 اسم المستخدم")
            password = st.text_input("🔑 كلمة المرور", type="password")
            submit = st.form_submit_button("تسجيل الدخول", type="primary", use_container_width=True)
            
            if submit:
                conn = get_db_connection()
                user = conn.execute("SELECT id, username, role, branch_id FROM users WHERE username = ? AND password = ?", (username, password)).fetchone()
                conn.close()
                if user:
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

if not st.session_state["logged_in"]:
    login()
else:
    with st.sidebar:
        st.markdown(f'<div style="text-align: center; margin-bottom: 20px; padding: 10px; background-color: rgba(255,255,255,0.1); border-radius: 10px;"><h3 style="margin: 0; color: #38bdf8;">🥜 محامص أبو زيد</h3><p style="margin: 5px 0 0 0; color: #cbd5e1; font-size: 14px;">المستخدم: <b>{st.session_state["username"]}</b></p><p style="margin: 0; color: #94a3b8; font-size: 12px;">الصلاحية: {st.session_state["role"]}</p></div>', unsafe_allow_html=True)
        
        role = st.session_state["role"]
        menu_options = []
        if role in ["Admin", "General_Supervisor"]:
            menu_options = ["🛒 نقطة البيع (POS)", "📊 التقارير والأرباح", "🏢 إدارة الفروع", "👥 إدارة المستخدمين", "📦 الجرد والمخازن", "🔄 نظام التزويد (الفواتير)", "📥 المشتريات (تجار الجملة)", "🤝 جهات التعامل (الموردين والديون)", "🥜 التحميص والخلط", "📁 استيراد الأصناف", "⭐ المفضلة والصور"]
        elif role == "Branch_Supervisor":
            menu_options = ["🛒 نقطة البيع (POS)", "📦 الجرد والمخازن", "📥 المشتريات (تجار الجملة)", "🤝 جهات التعامل (الموردين والديون)", "🥜 التحميص والخلط", "⭐ المفضلة والصور"]
        else:
            menu_options = ["🛒 نقطة البيع (POS)", "⭐ المفضلة والصور"]
            
        selected_page = st.radio("القائمة الرئيسية:", menu_options, label_visibility="collapsed")
        st.markdown("---")
        if st.button("🚪 تسجيل الخروج", use_container_width=True): logout()

    # التوجيه للصفحات
    if selected_page == "🛒 نقطة البيع (POS)": pos.show_page()
    elif selected_page == "📊 التقارير والأرباح": reports.show_page()
    elif selected_page == "🏢 إدارة الفروع": branches.show_page()
    elif selected_page == "👥 إدارة المستخدمين": users.show_page()
    elif selected_page == "📦 الجرد والمخازن": inventory.show_page()
    elif selected_page == "🔄 نظام التزويد (الفواتير)": transfers.show_page()
    elif selected_page == "📥 المشتريات (تجار الجملة)": purchases.show_page()
    elif selected_page == "🤝 جهات التعامل (الموردين والديون)": parties.show_page()
    elif selected_page == "🥜 التحميص والخلط": roasting_blending.show_page()
    elif selected_page == "📁 استيراد الأصناف": items_import.show_page()
    elif selected_page == "⭐ المفضلة والصور": favorites.show_page()
