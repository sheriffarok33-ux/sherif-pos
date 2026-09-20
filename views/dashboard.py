import streamlit as st

# 🛡️ دالة مساعدة لفلترة الصلاحيات داخل شاشة اللوحة الرئيسية
def is_allowed(menu_name, role):
    if role in ["Admin", "General_Supervisor"]: 
        return True
    if role == "Cashier":
        return menu_name in ["🛒 نقطة البيع (POS)", "⭐ لوحة المفضلة (1-20)", "🔄 تزويد الفروع والأرشيف"]
    if role == "Branch_Supervisor":
        return menu_name in ["🛒 نقطة البيع (POS)", "📦 إدارة المخزن والفروع", "🔄 تزويد الفروع والأرشيف"]
    if role == "Viewer":
        return menu_name in ["📊 التقارير والأرباح"]
    return False

def show_page():
    st.title("🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية")
    st.markdown("---")
    
    # 🎨 كود CSS سحري يحول زر Streamlit العادي إلى كارت (مربع كبير) قابل للضغط
    st.markdown("""
        <style>
        div[data-testid="column"] .stButton > button {
            height: 130px; /* ارتفاع المربع */
            font-size: 22px !important; /* حجم الخط */
            font-weight: bold !important;
            border-radius: 15px;
            background: linear-gradient(135deg, #ffffff, #f8fafc);
            color: #0f172a !important;
            border: 2px solid #cbd5e1;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05);
            white-space: normal; /* يسمح بنزول النص لسطر جديد إذا كان طويلاً */
            transition: all 0.3s ease-in-out;
        }
        div[data-testid="column"] .stButton > button:hover {
            border-color: #0284c7;
            background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
            transform: translateY(-5px); /* حركة خفيفة للأعلى عند مرور الماوس */
            box-shadow: 0 8px 15px rgba(2, 132, 199, 0.15);
        }
        </style>
    """, unsafe_allow_html=True)

    role = st.session_state.get("role", "")
    
    # قائمة بكل الشاشات الموجودة في النظام (بدون شاشة الرئيسية نفسها)
    all_screens = [
        "🛒 نقطة البيع (POS)",
        "🏢 إدارة الفروع",
        "👥 إدارة المستخدمين",
        "⭐ لوحة المفضلة (1-20)",
        "📦 إدارة المخزن والفروع",
        "➕ الفائض والتوالف والمرتجعات وتعديل السعر",
        "🔄 تزويد الفروع والأرشيف",
        "📁 استيراد Excel",
        "💰 المصروفات",
        "📥 المشتريات والموردين",
        "⚙️ الجرد والتصفير السنوي",
        "🥜 التحميص والخلط",
        "📊 التقارير والأرباح"
    ]
    
    # 🛡️ فلترة الكروت: النظام هيجيب الشاشات المسموحة فقط للرتبة الحالية
    allowed_screens = [s for s in all_screens if is_allowed(s, role)]
    
    if not allowed_screens:
        st.info("لا توجد شاشات متاحة لصلاحيتك حالياً.")
        return

    # رسم الشاشات المسموحة على هيئة شبكة (3 كروت في كل صف)
    cols = st.columns(3)
    for i, screen_name in enumerate(allowed_screens):
        with cols[i % 3]:
            # المربع نفسه هو الزر! بمجرد الضغط يتم توجيهه للشاشة المطلوبة
            if st.button(screen_name, key=f"dash_btn_{i}", use_container_width=True):
                st.session_state["page"] = screen_name
                st.rerun()
            st.markdown("<br>", unsafe_allow_html=True)
