import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("👥 إدارة المستخدمين والصلاحيات")
    st.info("💡 من هنا يمكنك إضافة الموظفين، تحديد رتبهم، وربطهم بالفروع أو إعطائهم صلاحية كافة الفروع.")
    
    conn = get_db_connection()
    current_user_role = st.session_state.get("role", "")
    current_username = st.session_state.get("username", "")
    
    # جلب قائمة الفروع مع خيار "كافة الفروع"
    branches_list = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    b_opts_dict = {"🌐 كافة الفروع (الكل)": None}
    for b in branches_list:
        b_opts_dict[b["branch_name"]] = b["id"]
        
    # --- قسم إضافة مستخدم جديد ---
    st.markdown("### ➕ إضافة مستخدم جديد")
    with st.form("new_user_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            uname = st.text_input("اسم المستخدم (للدخول):")
            uphone = st.text_input("رقم الهاتف:")
        with col2:
            upass = st.text_input("كلمة المرور:", type="password")
            
            # تطبيق قاعدة الصلاحيات: المدير العام لا يمكنه إنشاء أدمن
            if current_user_role == "Admin":
                available_roles = ["Admin", "General_Supervisor", "Branch_Supervisor", "Cashier", "Viewer"]
            else:
                available_roles = ["General_Supervisor", "Branch_Supervisor", "Cashier", "Viewer"]
                
            urole = st.selectbox("الرتبة (الصلاحية):", available_roles)
        
        sel_user_branch = st.selectbox("الفرع التابع له:", list(b_opts_dict.keys()))
        
        if st.form_submit_button("💾 حفظ المستخدم الجديد", type="primary"):
            if uname and upass:
                if urole == "Admin" and current_user_role != "Admin":
                    st.error("❌ عذراً، لا يمكن إضافة مشرف نظام (Admin) إلا بواسطة Admin آخر حصرياً!")
                else:
                    try:
                        # جلب الـ ID الحقيقي للفرع أو None إذا اختار الكل
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
    st.markdown("---")
    st.markdown("### 📋 قائمة المستخدمين الحاليين")
    
    udf = pd.read_sql("""
        SELECT users.id AS 'المسلسل', 
               users.username AS 'اسم المستخدم', 
               users.role AS 'الرتبة', 
               COALESCE(branches.branch_name, '🌐 كافة الفروع (الكل)') AS 'الفرع' 
        FROM users 
        LEFT JOIN branches ON users.branch_id = branches.id
    """, conn)
    
    if not udf.empty:
        st.dataframe(udf, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        del_u = st.selectbox("اختر المستخدم للحذف:", udf["المسلسل"].tolist(), 
                             format_func=lambda x: f"رقم {x} - {udf[udf['المسلسل']==x]['اسم المستخدم'].values[0]} ({udf[udf['المسلسل']==x]['الرتبة'].values[0]})")
                             
        selected_row_user = conn.execute("SELECT username, role FROM users WHERE id = ?", (del_u,)).fetchone()
        
        # قواعد الحماية والأمان للحذف
        is_admin_target = selected_row_user and (selected_row_user["role"] == "Admin" or selected_row_user["username"].strip().lower() == "admin")
        is_self_target = selected_row_user and (selected_row_user["username"].strip().lower() == current_username.strip().lower())
        
        can_delete = True
        delete_error_msg = ""
        
        if is_self_target:
            can_delete = False
            delete_error_msg = "⚠️ لا يمكنك حذف حسابك الشخصي أثناء تسجيل الدخول به!"
        elif is_admin_target:
            if current_user_role != "Admin":
                can_delete = False
                delete_error_msg = "❌ تحذير أمني: المدير العام لا يملك صلاحية حذف حسابات الأدمن (Admin)!"
            else:
                admin_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin'").fetchone()[0]
                if admin_count <= 1:
                    can_delete = False
                    delete_error_msg = "❌ لا يمكن حذف الأدمن الوحيد المتبقي في النظام!"
                    
        if not can_delete and delete_error_msg:
            st.warning(delete_error_msg)
            
        if st.button("🗑️ حذف المستخدم المختار", type="primary", disabled=not can_delete): 
            conn.execute("DELETE FROM users WHERE id = ?", (del_u,))
            conn.commit()
            st.toast("✅ تم حذف المستخدم بنجاح!")
            st.rerun()
            
    conn.close()
