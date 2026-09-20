import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("👥 إدارة المستخدمين والصلاحيات")
    st.info("💡 من هنا يمكنك إضافة الموظفين وتحديد صلاحياتهم والفروع التابعين لها.")
    
    conn = get_db_connection()
    current_user_role = st.session_state.get("role", "")
    
    # جلب قائمة الفروع لربط المستخدم بها
    branches_list = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    if not branches_list:
        st.warning("⚠️ الرجاء إضافة فروع أولاً قبل إضافة المستخدمين.")
        conn.close()
        return
        
    b_opts_dict = {b["branch_name"]: b["id"] for b in branches_list}
    
    # --- قسم إضافة مستخدم جديد ---
    with st.expander("➕ إضافة مستخدم جديد", expanded=True):
        with st.form("new_user_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                uname = st.text_input("اسم المستخدم (للدخول):")
                uphone = st.text_input("رقم الهاتف:")
            with col2:
                upass = st.text_input("كلمة المرور:", type="password")
                
                # تحديد الصلاحيات المتاحة بناءً على رتبة من يقوم بالإضافة
                if current_user_role == "Admin":
                    available_roles = ["Admin", "General_Supervisor", "Branch_Supervisor", "Cashier", "Viewer"]
                else:
                    available_roles = ["General_Supervisor", "Branch_Supervisor", "Cashier", "Viewer"]
                    
                urole = st.selectbox("الرتبة (الصلاحية):", available_roles)
            
            sel_user_branch = st.selectbox("الفرع التابع له:", list(b_opts_dict.keys()))
            
            if st.form_submit_button("💾 حفظ المستخدم", type="primary"):
                if uname and upass:
                    if urole == "Admin" and current_user_role != "Admin":
                        st.error("❌ عذراً، لا يمكن إضافة مشرف نظام (Admin) إلا بواسطة Admin آخر!")
                    else:
                        try:
                            assigned_b_id = b_opts_dict[sel_user_branch]
                            conn.execute("INSERT INTO users (username, phone, password, role, branch_id) VALUES (?, ?, ?, ?, ?)", 
                                         (uname.strip(), uphone.strip(), upass, urole, assigned_b_id))
                            conn.commit()
                            st.success(f"✅ تم إضافة المستخدم ({uname}) بنجاح!")
                        except Exception as e: 
                            st.error(f"⚠️ حدث خطأ، ربما اسم المستخدم موجود مسبقاً.")
                else:
                    st.warning("⚠️ يرجى إدخال اسم المستخدم وكلمة المرور.")

    # --- قسم عرض المستخدمين الحاليين ---
    st.markdown("### 📋 قائمة المستخدمين الحاليين")
    udf = pd.read_sql("""
        SELECT users.id AS 'المسلسل', 
               users.username AS 'اسم المستخدم', 
               users.role AS 'الرتبة', 
               branches.branch_name AS 'الفرع' 
        FROM users 
        LEFT JOIN branches ON users.branch_id = branches.id
    """, conn)
    
    if not udf.empty:
        st.dataframe(udf, use_container_width=True, hide_index=True)
        
        # قسم حذف المستخدمين (مع حماية حساب الأدمن)
        st.markdown("---")
        del_u = st.selectbox("اختر المستخدم للحذف:", udf["المسلسل"].tolist(), 
                             format_func=lambda x: f"رقم {x} - {udf[udf['المسلسل']==x]['اسم المستخدم'].values[0]}")
                             
        selected_row_user = conn.execute("SELECT username, role FROM users WHERE id = ?", (del_u,)).fetchone()
        is_admin_target = selected_row_user and (selected_row_user["role"] == "Admin" or selected_row_user["username"].strip().lower() == "admin")
        
        can_delete = True
        if is_admin_target or (current_user_role != "Admin" and is_admin_target):
            can_delete = False
            
        if st.button("🗑️ حذف المستخدم", type="primary", disabled=not can_delete): 
            conn.execute("DELETE FROM users WHERE id = ?", (del_u,))
            conn.commit()
            st.toast("✅ تم حذف المستخدم بنجاح!")
            st.rerun()
            
    conn.close()
