import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    # 🌟 تنسيق الصفحة والاتجاه
    st.markdown("""
        <style>
        .rtl-container { direction: rtl !important; text-align: right !important; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h2 class="rtl-container">🏢 إدارة الفروع والمخازن</h2>', unsafe_allow_html=True)
    st.info("💡 من هنا يمكنك إضافة الفروع والمخازن الجديدة الخاصة بالمؤسسة لعرضها في باقي شاشات النظام.")

    conn = get_db_connection()
    current_user_role = st.session_state.get("role", "")

    # --- قسم إضافة فرع / مخزن جديد ---
    st.markdown("### ➕ إضافة فرع أو مخزن جديد")
    with st.form("new_branch_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            b_name = st.text_input("اسم الفرع / المخزن:")
        with col2:
            b_type = st.selectbox("النوع:", ["فرع مبيعات", "مخزن"])
        
        submit_btn = st.form_submit_button("💾 حفظ وإضافة", type="primary")
        
        if submit_btn:
            if current_user_role not in ["Admin", "General_Supervisor"]:
                st.error("❌ عذراً، الإدارة العليا فقط من تملك صلاحية إضافة فروع جديدة.")
            elif b_name.strip():
                try:
                    conn.execute("INSERT INTO branches (branch_name, branch_type) VALUES (?, ?)", (b_name.strip(), b_type))
                    conn.commit()
                    st.success(f"✅ تم إضافة ({b_name}) بنجاح!")
                    st.rerun()
                except Exception as e:
                    st.error(f"⚠️ حدث خطأ أثناء الحفظ: {e}")
            else:
                st.warning("⚠️ يرجى إدخال اسم الفرع.")

    # --- قسم عرض الفروع الحالية ---
    st.markdown("---")
    st.markdown("### 📋 قائمة الفروع والمخازن المسجلة")
    
    try:
        query = """
            SELECT id AS 'المسلسل', 
                   branch_name AS 'اسم الفرع / المخزن', 
                   branch_type AS 'النوع' 
            FROM branches
        """
        branches_df = pd.read_sql(query, conn)
        
        if not branches_df.empty:
            st.dataframe(branches_df, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد فروع أو مخازن مسجلة حتى الآن. يرجى إضافة مخزن رئيسي أولاً لضمان عمل باقي شاشات النظام.")
    except Exception as e:
        st.error("⚠️ لم يتم العثور على جدول الفروع. تأكد من تحديث قاعدة البيانات.")

    conn.close()
