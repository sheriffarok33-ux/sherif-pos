import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("👥 إدارة المستخدمين والصلاحيات")
    st.info("💡 من هنا يمكنك إضافة الموظفين، تحديد رتبهم، تعديل كلمات المرور، وربطهم بالفروع.")

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

            # 🌟 تطبيق قاعدة الصلاحيات بدقة: الأدمن فقط يستطيع إضافة أدمن آخر
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
                        assigned_b_id = b_opts_dict[sel_user_branch]
                        conn.execute("INSERT INTO users (username, phone, password, role, branch_id) VALUES (?, ?, ?, ?, ?)", 
                                   (uname.strip(), uphone.strip(), upass, urole, assigned_b_id))
                        conn.commit()
                        st.success(f"✅ تم إضافة المستخدم ({uname}) بنجاح!")
                        st.rerun()
                    except Exception as e: 
                        st.error(f"⚠️ حدث خطأ، ربما اسم المستخدم موجود مسبقاً.")
            else:
                st.warning("⚠️ يرجى إدخال اسم المستخدم وكلمة المرور.")

    # --- قسم عرض المستخدمين الحاليين ---
    st.markdown("---")
    st.markdown("### 📋 قائمة المستخدمين الحاليين")

    # للأدمن نظهر كلمة المرور، لغيره نخفيها أو نظهرها بصلاحيات أضيق
    query = """
        SELECT users.id AS 'المسلسل', 
               users.username AS 'اسم المستخدم', 
               users.password AS 'كلمة المرور',
               users.role AS 'الرتبة', 
               COALESCE(branches.branch_name, '🌐 كافة الفروع (الكل)') AS 'الفرع' 
        FROM users 
        LEFT JOIN branches ON users.branch_id = branches.id
    """
    udf = pd.read_sql(query, conn)

    if not udf.empty:
        if current_user_role != "Admin":
            selectable_users_df = udf[udf['الرتبة'] != 'Admin']
            # إخفاء كلمة المرور لو لم يكن أدمن لحماية الخصوصية
            udf_display = udf.drop(columns=['كلمة المرور'])
        else:
            selectable_users_df = udf
            udf_display = udf

        st.dataframe(udf_display, use_container_width=True, hide_index=True)

        # --- قسم تعديل بيانات أو كلمة مرور مستخدم (خاص بالأدمن) ---
        if current_user_role == "Admin":
            st.markdown("---")
            st.markdown("### ✏️ تعديل بيانات أو كلمة مرور مستخدم")
            edit_u_id = st.selectbox("اختر المستخدم للتعديل:", udf["المسلسل"].tolist(), 
                                    format_func=lambda x: f"رقم {x} - {udf[udf['المسلسل']==x]['اسم المستخدم'].values[0]}")
            
            target_user_data = conn.execute("SELECT * FROM users WHERE id = ?", (edit_u_id,)).fetchone()
            
            if target_user_data:
                with st.form("edit_user_form"):
                    e_col1, e_col2 = st.columns(2)
                    with e_col1:
                        new_uname = st.text_input("تعديل اسم المستخدم:", value=target_user_data["username"])
                        new_pass = st.text_input("تعديل كلمة المرور:", value=target_user_data["password"])
                    with e_col2:
                        roles_list = ["Admin", "General_Supervisor", "Branch_Supervisor", "Cashier", "Viewer"]
                        current_role_idx = roles_list.index(target_user_data["role"]) if target_user_data["role"] in roles_list else 0
                        new_role = st.selectbox("تعديل الرتبة:", roles_list, index=current_role_idx)
                        
                        branch_keys = list(b_opts_dict.keys())
                        # العثور على اسم الفرع الحالي للمستخدم
                        curr_b_name = "🌐 كافة الفروع (الكل)"
                        for b_name, b_id in b_opts_dict.items():
                            if b_id == target_user_data["branch_id"]:
                                curr_b_name = b_name
                                break
                        curr_b_idx = branch_keys.index(curr_b_name) if curr_b_name in branch_keys else 0
                        new_branch_sel = st.selectbox("تعديل الفرع:", branch_keys, index=curr_b_idx)

                    if st.form_submit_button("💾 تحديث وحفظ التعديلات", type="primary"):
                        new_b_id = b_opts_dict[new_branch_sel]
                        conn.execute("""
                            UPDATE users SET username = ?, password = ?, role = ?, branch_id = ? WHERE id = ?
                        """, (new_uname.strip(), new_pass.strip(), new_role, new_b_id, edit_u_id))
                        conn.commit()
                        st.success("✅ تم تحديث بيانات المستخدم بنجاح!")
                        st.rerun()

        # --- قسم الحذف الآمن ---
        st.markdown("---")
        st.markdown("### 🗑️ حذف مستخدم")
        if not selectable_users_df.empty:
            del_u = st.selectbox("اختر المستخدم للحذف:", selectable_users_df["المسلسل"].tolist(), 
                                   format_func=lambda x: f"رقم {x} - {udf[udf['المسلسل']==x]['اسم المستخدم'].values[0]} ({udf[udf['المسلسل']==x]['الرتبة'].values[0]})", key="del_select_box")

            selected_row_user = conn.execute("SELECT username, role FROM users WHERE id = ?", (del_u,)).fetchone()

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
        else:
            st.info("لا توجد حسابات أخرى متاحة للحذف.")

    conn.close()
