import streamlit as st
from database import get_db_connection

def show_dashboard():
    # جلب دور المستخدم الحالي من الجلسة
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
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h3 class="rtl-container">🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية</h3>', unsafe_allow_html=True)
    
    # رسالة ترحيبية عامة تظهر للجميع
    st.markdown(f"""
        <div class="dashboard-banner">
            <h4 style="margin-top:0; color:#16a34a;">👋 مرحباً بك يا {username} في النظام السحابي لإدارة المحامص والمخازن.</h4>
            <p style="font-size: 16px; margin: 0;">نتمنى لك وقتاً موفقاً في عملك اليومي.</p>
        </div>
    """, unsafe_allow_html=True)

    # 🔒 الشرط الأمني: البطاقات الإحصائية والمالية تظهر حصرياً للأدمن والمشرف العام فقط
    if role in ["Admin", "General_Supervisor"]:
        conn = get_db_connection()
        
        # استخراج الإحصائيات المالية والمخزنية
        total_sales_res = conn.execute("SELECT SUM(total_amount) FROM invoices").fetchone()
        total_sales = total_sales_res[0] if total_sales_res and total_sales_res[0] else 0.0

        branches_count = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
        
        total_stock_res = conn.execute("SELECT SUM(quantity) FROM items").fetchone()
        total_stock = total_stock_res[0] if total_stock_res and total_stock_res[0] else 0.0

        users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        
        conn.close()

        st.markdown('<p class="rtl-container" style="font-weight: bold; font-size: 16px;">📊 ملخص حركة العمل والأداء المالي:</p>', unsafe_allow_html=True)
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(label="💰 إجمالي المبيعات العامة", value=f"{total_sales:,.2f} د.ل")
        with col2:
            st.metric(label="🏢 الفروع والمخازن", value=f"{branches_count} فرع")
        with col3:
            st.metric(label="📦 إجمالي المخزون", value=f"{total_stock:,.2f}")
        with col4:
            st.metric(label="👥 طاقم العمل", value=f"{users_count} موظف")
            
        st.markdown("---")
    else:
        # لو المستخدم كاشير أو دور آخر، يتم عرض رسالة مبسطة أو ترك الشاشة نظيفة ومخصصة لنقطة البيع
        st.info("🛒 يمكنك الانتقال مباشرة إلى قسم (نقطة البيع POS) لبدء تسجيل الفواتير وخدمة الزبائن.")
