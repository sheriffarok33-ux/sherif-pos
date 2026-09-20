import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("👥 جهات التعامل (الموردين والزبائن)")
    
    conn = get_db_connection()
    tab_sup, tab_cust = st.tabs(["🚛 الموردين (تجار الجملة)", "🤝 الزبائن (نظام الولاء الدائم)"])
    
    # ==========================================
    # 1. إدارة الموردين
    # ==========================================
    with tab_sup:
        with st.form("new_sup_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            sname = col1.text_input("اسم المورد / الشركة:")
            sphone = col2.text_input("رقم الهاتف:")
            
            if st.form_submit_button("💾 حفظ مورد جديد", type="primary"):
                if sname:
                    try:
                        conn.execute("INSERT INTO suppliers (supplier_name, phone, balance) VALUES (?, ?, 0.0)", (sname.strip(), sphone.strip()))
                        conn.commit()
                        st.success("تم حفظ المورد بنجاح!")
                        st.rerun()
                    except:
                        st.error("⚠️ هذا الاسم موجود مسبقاً في قاعدة البيانات.")
                else:
                    st.warning("يرجى إدخال اسم المورد.")

        st.markdown("### 📋 كشف حساب الموردين")
        supp_df = pd.read_sql("SELECT id AS 'رقم المورد', supplier_name AS 'اسم المورد', phone AS 'الهاتف', balance AS 'الرصيد المستحق (له/عليه) د.ل' FROM suppliers", conn)
        
        if not supp_df.empty: 
            st.dataframe(supp_df, use_container_width=True, hide_index=True)
            
            st.markdown("**💰 سداد دفعة لمورد:**")
            col_pay1, col_pay2 = st.columns(2)
            sup_list = {s["supplier_name"]: s["id"] for s in conn.execute("SELECT id, supplier_name FROM suppliers").fetchall()}
            sel_pay_sup = col_pay1.selectbox("اختر المورد للسداد:", list(sup_list.keys()))
            pay_amount = col_pay2.number_input("المبلغ المدفوع له (د.ل):", min_value=0.0, step=10.0)
            
            if st.button("✅ تسجيل الدفعة وخصمها من حسابه"):
                if pay_amount > 0:
                    conn.execute("UPDATE suppliers SET balance = balance - ? WHERE id = ?", (pay_amount, sup_list[sel_pay_sup]))
                    conn.commit()
                    st.success("تم تسجيل الدفعة وخصمها من حساب المورد بنجاح.")
                    st.rerun()

    # ==========================================
    # 2. إدارة الزبائن
    # ==========================================
    with tab_cust:
        st.markdown("### 📊 قائمة زبائن المحل ونظام الولاء")
        cust_df = pd.read_sql("SELECT id AS 'رقم الزبون', customer_name AS 'اسم الزبون', phone AS 'الهاتف', total_purchases AS 'إجمالي مشترياته (د.ل)', created_at AS 'تاريخ التسجيل' FROM customers ORDER BY total_purchases DESC", conn)
        
        if not cust_df.empty:
            st.dataframe(cust_df, use_container_width=True, hide_index=True)
        else:
            st.info("لا يوجد زبائن مسجلين حالياً. يتم تسجيلهم تلقائياً من شاشة الكاشير عند إدخال هواتفهم.")
            
    conn.close()
