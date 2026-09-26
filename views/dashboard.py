import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    # تنسيق الخطوط والألوان العامة للوحة التحكم
    st.markdown("""
        <style>
        .dash-card {
            background: linear-gradient(135deg, #1e293b, #0f172a);
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            color: #ffffff !important;
            text-align: center;
            margin-bottom: 15px;
            border: 1px solid #334155;
        }
        .dash-card h3 {
            color: #94a3b8 !important;
            font-size: 16px !important;
            margin-bottom: 8px;
        }
        .dash-card h2 {
            color: #38bdf8 !important;
            font-size: 26px !important;
            font-weight: 900 !important;
            margin: 0;
        }
        .rtl-container { direction: rtl !important; text-align: right !important; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h2 class="rtl-container">🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية (Dashboard)</h2>', unsafe_allow_html=True)
    st.info("💡 مرحباً بك في النظام السحابي لإدارة المحامص والمخازن. إليك ملخصاً فورياً لحركة العمل والأداء المالي.")
    st.markdown("---")

    conn = get_db_connection()

    # جلب الإحصائيات العامة من قواعد البيانات
    try:
        sales_row = conn.execute("SELECT SUM(total_amount) FROM invoices").fetchone()
        total_sales = sales_row[0] if sales_row and sales_row[0] else 0.0

        branches_count = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]

        items_count = conn.execute("SELECT SUM(quantity) FROM items").fetchone()[0]
        total_items_qty = items_count if items_count else 0.0

        users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    except Exception as e:
        total_sales = 0.0
        branches_count = 0
        total_items_qty = 0.0
        users_count = 0

    # عرض المربعات الإحصائية (Cards)
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"""
            <div class="dash-card">
                <h3>💰 إجمالي المبيعات العامة</h3>
                <h2>{total_sales:,.2f} د.ل</h2>
            </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
            <div class="dash-card">
                <h3>🏢 الفروع والمخازن</h3>
                <h2>{branches_count} فرع</h2>
            </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
            <div class="dash-card">
                <h3>📦 إجمالي المخزون</h3>
                <h2>{total_items_qty:,.1f}</h2>
            </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
            <div class="dash-card">
                <h3>👥 طاقم العمل</h3>
                <h2>{users_count} موظف</h2>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📊 آخر الفواتير المسجلة في النظام")

    try:
        recent_invoices_df = pd.read_sql("""
            SELECT invoices.id AS 'رقم الفاتورة',
                   COALESCE(branches.branch_name, 'الفرع الرئيسي') AS 'الفرع',
                   invoices.customer_name AS 'اسم الزبون',
                   invoices.total_amount AS 'إجمالي المبلغ (د.ل)',
                   invoices.payment_method AS 'طريقة الدفع',
                   invoices.created_at AS 'وقت الإصدار'
            FROM invoices
            LEFT JOIN branches ON invoices.branch_id = branches.id
            ORDER BY invoices.id DESC
            LIMIT 10
        """, conn)

        if not recent_invoices_df.empty:
            st.dataframe(recent_invoices_df, use_container_width=True, hide_index=True)
        else:
            st.info("📭 لا توجد مبيعات مسجلة حتى الآن.")
    except Exception as ex:
        st.info("📭 جدول الفواتير قيد التجهيز أو بانتظار العمليات الأولى.")

    conn.close()
