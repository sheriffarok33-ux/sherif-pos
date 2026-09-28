import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("👥 جهات التعامل المعتمدة (الموردين والزبائن الآجلين)")
    st.info("💡 إدارة وتصنيف الموردين (تجار الجملة والديون) والزبائن المعتمدين للبيع الآجل والتحصيل في مكان واحد.")
    
    conn = get_db_connection()
    
    # التأكد من وجود عمود الرصيد للزبائن
    try:
        conn.execute("SELECT balance FROM customers LIMIT 1")
    except:
        try:
            conn.execute("ALTER TABLE customers ADD COLUMN balance REAL DEFAULT 0.0")
            conn.commit()
        except:
            pass

    # --- قسم الإدخال الموحد (أوبشن واختيارات) ---
    st.markdown("### ➕ إضافة جهة تعامل جديدة (مورد أو زبون آجل)")
    with st.form("unified_party_form", clear_on_submit=True):
        col_u1, col_u2, col_u3 = st.columns(3)
        party_type = col_u1.selectbox("اختر نوع جهة التعامل:", ["🚛 مورد (تاجر جملة)", "🤝 زبون آجل (مسموح له بالدين)"])
        p_name = col_u2.text_input("اسم الجهة / الشخص:")
        p_phone = col_u3.text_input("رقم الهاتف:")
        
        if st.form_submit_button("💾 حفظ واعتماد جهة التعامل", type="primary"):
            if p_name and p_name.strip() and p_phone and p_phone.strip():
                try:
                    if "مورد" in party_type:
                        conn.execute("INSERT INTO suppliers (supplier_name, phone, balance) VALUES (?, ?, 0.0)", (p_name.strip(), p_phone.strip()))
                        st.success(f"✅ تمت إضافة المورد ({p_name}) بنجاح!")
                    else:
                        conn.execute("INSERT INTO customers (customer_name, phone, total_purchases, balance) VALUES (?, ?, 0.0, 0.0)", (p_name.strip(), p_phone.strip()))
                        st.success(f"✅ تم اعتماد الزبون الآجل ({p_name}) بنجاح!")
                    conn.commit()
                    st.rerun()
                except Exception as e:
                    st.error(f"⚠️ خطأ: هذا الاسم أو رقم الهاتف مسجل مسبقاً.")
            else:
                st.warning("⚠️ يرجى إدخال اسم الجهة ورقم الهاتف معاً.")

    st.markdown("---")

    # التبويبات لعرض كشوفات الحسابات والسداد
    tab_sup, tab_cust = st.tabs(["🚛 جدول الموردين والديون", "🤝 جدول الزبائن الآجلين والتحصيل"])
    
    # ==========================================
    # 1. إدارة الموردين
    # ==========================================
    with tab_sup:
        st.markdown("### 📋 كشف حساب الموردين والديون المستحقة")
        supp_df = pd.read_sql("SELECT id AS 'رقم المورد', supplier_name AS 'اسم المورد', phone AS 'الهاتف', balance AS 'الرصيد المستحق (له/عليه) د.ل' FROM suppliers", conn)
        
        if not supp_df.empty: 
            st.dataframe(supp_df, use_container_width=True, hide_index=True)
            
            st.markdown("**💰 سداد دفعة لمورد (إرسال نقدية):**")
            col_pay1, col_pay2 = st.columns(2)
            sup_list = {s["supplier_name"]: s["id"] for s in conn.execute("SELECT id, supplier_name FROM suppliers").fetchall()}
            if sup_list:
                sel_pay_sup = col_pay1.selectbox("اختر المورد للسداد:", list(sup_list.keys()), key="sel_sup_pay_box")
                pay_amount = col_pay2.number_input("المبلغ المدفوع له (د.ل):", min_value=0.0, step=10.0, key="sup_pay_val_input")
                
                if st.button("✅ تسجيل الدفعة وخصمها من حساب المورد", key="btn_execute_sup_pay"):
                    if pay_amount > 0:
                        conn.execute("UPDATE suppliers SET balance = balance - ? WHERE id = ?", (pay_amount, sup_list[sel_pay_sup]))
                        conn.commit()
                        st.success("تم تسجيل الدفعة وخصمها من حساب المورد بنجاح.")
                        st.rerun()
        else:
            st.info("لا توجد موردين مسجلين.")

    # ==========================================
    # 2. إدارة الزبائن المعتمدين للآجل
    # ==========================================
    with tab_cust:
        st.markdown("### 📊 قائمة الزبائن المعتمدين والديون المستحقة")
        cust_df = pd.read_sql("SELECT id AS 'رقم الزبون', customer_name AS 'اسم الزبون', phone AS 'الهاتف', total_purchases AS 'إجمالي المشتريات (د.ل)', balance AS 'الرصيد الآجل المستحق (د.ل)', created_at AS 'تاريخ التسجيل' FROM customers ORDER BY total_purchases DESC", conn)
        
        if not cust_df.empty:
            st.dataframe(cust_df, use_container_width=True, hide_index=True)
            
            st.markdown("**💵 تحصيل دفعة من زبون آجل (قبض نقدية):**")
            col_cp1, col_cp2 = st.columns(2)
            cust_list = {c["customer_name"] + f" ({c['phone']})": c["id"] for c in conn.execute("SELECT id, customer_name, phone FROM customers").fetchall()}
            
            if cust_list:
                sel_pay_cust = col_cp1.selectbox("اختر الزبون للتحصيل منه:", list(cust_list.keys()), key="sel_cust_pay_box")
                cust_pay_amount = col_cp2.number_input("المبلغ المحصول المقبوض (د.ل):", min_value=0.0, step=10.0, key="cust_pay_val_input")
                
                if st.button("✅ تسجيل القبض وخصمه من مديونية الزبون", key="btn_execute_cust_pay"):
                    if cust_pay_amount > 0:
                        conn.execute("UPDATE customers SET balance = balance - ? WHERE id = ?", (cust_pay_amount, cust_list[sel_pay_cust]))
                        conn.commit()
                        st.success("تم قبض الدفعة من الزبون بنجاح وتحديث رصيده.")
                        st.rerun()
            else:
                st.info("لا يوجد زبائن مسجلين للتحصيل.")
        else:
            st.info("لا توجد عملاء مسجلين حالياً.")
            
    conn.close()
