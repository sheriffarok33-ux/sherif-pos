import streamlit as st
from database import get_db_connection

# دالة مساعدة لفلترة الصلاحيات داخل شاشة اللوحة الرئيسية
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
    st.markdown('<h2 style="color: #0f172a; text-align: right;">🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية (Dashboard)</h2>', unsafe_allow_html=True)
    st.info("💡 مرحباً بك في ادارة مجموعة ابو زيد. إليك ملخصاً فورياً لحركة العمل والأداء المالي.")
    
    # --- الإحصائيات العلوية بتنسيق فاتح وواضح جداً ---
    conn = get_db_connection()
    try:
        sales = conn.execute("SELECT SUM(total_amount) FROM invoices").fetchone()[0] or 0.0
        branches = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0] or 0
        inventory = conn.execute("SELECT SUM(quantity * avg_cost) FROM items").fetchone()[0] or 0.0
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0
    except:
        sales = 0.0; branches = 0; inventory = 0.0; users = 0
    conn.close()

    c1, c2, c3, c4 = st.columns(4)
    # تصميم المربعات العلوية بخلفية بيضاء نقية وإطار واضح
    box_style = "background-color:#ffffff; padding:15px; border-radius:8px; text-align:center; border:2px solid #cbd5e1; box-shadow: 0 4px 6px rgba(0,0,0,0.05);"
    
    c1.markdown(f"<div style='{box_style}'><b style='color:#0f172a !important; font-size:18px;'>💰 إجمالي المبيعات العامة</b><br><br><span style='font-size:22px; font-weight:900; color:#0284c7 !important;'>{sales:,.2f} د.ل</span></div>", unsafe_allow_html=True)
    c2.markdown(f"<div style='{box_style}'><b style='color:#0f172a !important; font-size:18px;'>🏢 الفروع والمخازن</b><br><br><span style='font-size:22px; font-weight:900; color:#0284c7 !important;'>فرع {branches}</span></div>", unsafe_allow_html=True)
    c3.markdown(f"<div style='{box_style}'><b style='color:#0f172a !important; font-size:18px;'>📦 إجمالي المخزون</b><br><br><span style='font-size:22px; font-weight:900; color:#0284c7 !important;'>{inventory:,.2f}</span></div>", unsafe_allow_html=True)
    c4.markdown(f"<div style='{box_style}'><b style='color:#0f172a !important; font-size:18px;'>👥 طاقم العمل</b><br><br><span style='font-size:22px; font-weight:900; color:#0284c7 !important;'>موظف {users}</span></div>", unsafe_allow_html=True)

    st.markdown("---")
    
    # --- كود CSS لإرجاع مربعات الشاشات مع إجبار النص على اللون الداكن ---
    st.markdown("""
        <style>
        div[data-testid="column"] .stButton > button {
            height: 130px; 
            font-size: 22px !important; 
            font-weight: 900 !important;
            border-radius: 15px;
            background: linear-gradient(135deg, #ffffff, #f8fafc) !important;
            border: 2px solid #cbd5e1 !important;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05) !important;
            white-space: normal; 
            transition: all 0.3s ease-in-out;
            width: 100%;
        }
        /* إجبار النصوص داخل المربعات على اللون الأزرق الداكن لتبقى مقروءة بوضوح */
        div[data-testid="column"] .stButton > button p, 
        div[data-testid="column"] .stButton > button div, 
        div[data-testid="column"] .stButton > button span {
            color: #0f172a !important; 
        }
        div[data-testid="column"] .stButton > button:hover {
            border-color: #0284c7 !important;
            background: linear-gradient(135deg, #f0f9ff, #e0f2fe) !important;
            transform: translateY(-5px); 
            box-shadow: 0 8px 15px rgba(2, 132, 199, 0.15) !important;
        }
        </style>
    """, unsafe_allow_html=True)

    role = st.session_state.get("role", "")
    
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
        "👥 جهات التعامل",
        "📥 المشتريات",
        "⚙️ الجرد والتصفير السنوي",
        "🥜 التحميص والخلط",
        "📊 التقارير والأرباح"
    ]
    
    allowed_screens = [s for s in all_screens if is_allowed(s, role)]
    
    if not allowed_screens:
        st.info("لا توجد شاشات متاحة لصلاحيتك حالياً.")
        return

    # --- رسم الشاشات المسموحة على هيئة شبكة (3 مربعات في كل صف) ---
    cols = st.columns(3)
    for i, screen_name in enumerate(allowed_screens):
        with cols[i % 3]:
            if st.button(screen_name, key=f"dash_btn_{i}", use_container_width=True):
                st.session_state["page"] = screen_name
                st.rerun()
            st.markdown("<br>", unsafe_allow_html=True)
