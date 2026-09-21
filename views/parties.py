import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("👥 جهات التعامل المعتمدة (الموردين والزبائن الآجلين)")
    
    conn = get_db_connection()
    tab_sup, tab_cust = st.tabs(["🚛 الموردين (تجار الجملة والديون)", "🤝 الزبائن المعتمدين للبيع الآجل والولاء"])
    
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

        st.markdown("### 📋 كشف حساب الموردين والديون")
        supp_df = pd.read_sql("SELECT id AS 'رقم المورد', supplier_name AS 'اسم المورد', phone AS 'الهاتف', balance AS 'الرصيد المستحق (له/عليه) د.ل' FROM suppliers", conn)
        
        if not supp_df.empty: 
            st.dataframe(supp_df, use_container_width=True, hide_index=True)
            
            st.markdown("**💰 سداد دفعة لمورد (إرسال نقدية):**")
            col_pay1, col_pay2 = st.columns(2)
            sup_list = {s["supplier_name"]: s["id"] for s in conn.execute("SELECT id, supplier_name FROM suppliers").fetchall()}
            sel_pay_sup = col_pay1.selectbox("اختر المورد للسداد:", list(sup_list.keys()))
            pay_amount = col_pay2.number_input("المبلغ المدفوع له (د.ل):", min_value=0.0, step=10.0, key="sup_pay_input")
            
            if st.button("✅ تسجيل الدفعة وخصمها من حساب المورد", key="btn_sup_pay"):
                if pay_amount > 0:
                    conn.execute("UPDATE suppliers SET balance = balance - ? WHERE id = ?", (pay_amount, sup_list[sel_pay_sup]))
                    conn.commit()
                    st.success("تم تسجيل الدفعة وخصمها من حساب المورد بنجاح.")
                    st.rerun()
        else:
            st.info("لا توجد مبالغ أو موردين مسجلين.")

    # ==========================================
    # 2. إدارة الزبائن المعتمدين للآجل والولاء
    # ==========================================
    with tab_cust:
        st.markdown("### ➕ إضافة زبون جديد مسموح له بالشراء بالآجل")
        with st.form("new_credit_customer_form", clear_on_submit=True):
            col_c1, col_c2 = st.columns(2)
            c_name = col_c1.text_input("اسم الزبون المعتمد:")
            c_phone = col_c2.text_input("رقم الهاتف (أساسي للتعرف عليه بالكاشير):")
            
            if st.form_submit_button("💾 اعتماد وحفظ الزبون الآجل", type="primary"):
                if c_name.strip() and c_phone.strip():
                    try:
                        # التأكد من إنشاء العمود balance إن لم يكن موجوداً
                        try:
                            conn.execute("SELECT balance FROM customers LIMIT 1")
                        except:
                            conn.execute("ALTER TABLE customers ADD COLUMN balance REAL DEFAULT 0.0")
                        
                        conn.execute("INSERT INTO customers (customer_name, phone, total_purchases, balance) VALUES (?, ?, 0.0, 0.0)", (c_name.strip(), c_phone.strip()))
                        conn.commit()
                        st.success(f"✅ تم اعتماد الزبون الآجل ({c_name}) بنجاح! أصبح ظاهراً للكاشير.")
                        st.rerun()
                    except Exception as e:
                        st.error("⚠️ رقم الهاتف أو اسم الزبون مسجل مسبقاً.")
                else:
                    st.warning("⚠️ يجب إدخال اسم الزبون ورقم هاتفه.")

        st.markdown("### 📊 قائمة الزبائن المعتمدين والديون المستحقة")
        
        try:
            conn.execute("SELECT balance FROM customers LIMIT 1")
        except:
            try:
                conn.execute("ALTER TABLE customers ADD COLUMN balance REAL DEFAULT 0.0")
                conn.commit()
            except:
                pass

        cust_df = pd.read_sql("SELECT id AS 'رقم الزبون', customer_name AS 'اسم الزبون', phone AS 'الهاتف', total_purchases AS 'إجمالي المشتريات (د.ل)', balance AS 'الرصيد الآجل المستحق (د.ل)', created_at AS 'تاريخ التسجيل' FROM customers ORDER BY total_purchases DESC", conn)
        
        if not cust_df.empty:
            st.dataframe(cust_df, use_container_width=True, hide_index=True)
            
            st.markdown("**💵 تحصيل دفعة من زبون آجل (قبض نقدية):**")
            col_cp1, col_cp2 = st.columns(2)
            cust_list = {c["customer_name"] + f" ({c['phone']})": c["id"] for c in conn.execute("SELECT id, customer_name, phone FROM customers").fetchall()}
            
            if cust_list:
                sel_pay_cust = col_cp1.selectbox("اختر الزبون للتحصيل منه:", list(cust_list.keys()))
                cust_pay_amount = col_cp2.number_input("المبلغ المحصول المقبوض (د.ل):", min_value=0.0, step=10.0, key="cust_pay_input")
                
                if st.button("✅ تسجيل القبض وخصمه من مديونية الزبون", key="btn_cust_pay"):
                    if cust_pay_amount > 0:
                        conn.execute("UPDATE customers SET balance = balance - ? WHERE id = ?", (cust_pay_amount, cust_list[sel_pay_cust]))
                        conn.commit()
                        st.success("تم قبض الدفعة من الزبون بنجاح وتحديث رصيده.")
                        st.rerun()
            else:
                st.info("لا يوجد زبائن مسجلين.")
        else:
            st.info("لا توجد عملاء مسجلين حالياً.")
            
    conn.close()
