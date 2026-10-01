import streamlit as st
import pandas as pd
from database import get_db_connection


def show_page():
    st.header("👥 إدارة المستخدمينئ والصلاحيات")
    st.info(
        "💡 من هنا يمكنك إضافة الموظفين، تحديد رتبهم، "
        "تعديل كلمات المرور، وربطهم بالفروع."
    )

    current_user_role = st.session_state.get("role", "")
    current_username = st.session_state.get("username", "")

    # ========================================================
    # تحميل الفروع
    # ========================================================

    conn = None

    try:
        conn = get_db_connection()

        branches_list = conn.execute(
            """
            SELECT id, branch_name
            FROM branches
            ORDER BY id ASC
            """
        ).fetchall()

    except Exception as e:
        st.error("❌ تعذر تحميل قائمة الفروع.")
        st.code(str(e))
        branches_list = []

    finally:
        if conn:
            conn.close()

    b_opts_dict = {
        "🌐 كافة الفروع (الكل)": None
    }

    for b in branches_list:
        b_opts_dict[b["branch_name"]] = b["id"]

    # ========================================================
    # إضافة مستخدم
    # ========================================================

    st.markdown("### ➕ إضافة مستخدم جديد")

    with st.form(
        "new_user_form",
        clear_on_submit=True
    ):

        col1, col2 = st.columns(2)

        with col1:
            uname = st.text_input(
                "اسم المستخدم (للدخول):"
            )

            uphone = st.text_input(
                "رقم الهاتف:"
            )

        with col2:
            upass = st.text_input(
                "كلمة المرور:",
                type="password"
            )

            if current_user_role == "Admin":
                available_roles = [
                    "Admin",
                    "General_Supervisor",
                    "Branch_Supervisor",
                    "Cashier",
                    "Viewer"
                ]
            else:
                available_roles = [
                    "General_Supervisor",
                    "Branch_Supervisor",
                    "Cashier",
                    "Viewer"
                ]

            urole = st.selectbox(
                "الرتبة (الصلاحية):",
                available_roles
            )

        sel_user_branch = st.selectbox(
            "الفرع التابع له:",
            list(b_opts_dict.keys())
        )

        save_new_user = st.form_submit_button(
            "💾 حفظ المستخدم الجديد",
            type="primary"
        )

    if save_new_user:

        if not uname or not uname.strip() or not upass:
            st.warning(
                "⚠️ يرجى إدخال اسم المستخدم وكلمة المرور."
            )

        elif (
            urole == "Admin"
            and current_user_role != "Admin"
        ):
            st.error(
                "❌ لا يمكن إضافة Admin "
                "إلا بواسطة Admin آخر."
            )

        else:

            conn = None

            try:
                conn = get_db_connection()

                assigned_b_id = b_opts_dict[
                    sel_user_branch
                ]

                conn.execute(
                    """
                    INSERT INTO users
                    (
                        username,
                        phone,
                        password,
                        role,
                        branch_id
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        uname.strip(),
                        uphone.strip(),
                        upass,
                        urole,
                        assigned_b_id
                    )
                )

                conn.commit()

                st.success(
                    f"✅ تم إضافة المستخدم "
                    f"({uname.strip()}) بنجاح!"
                )

                st.rerun()

            except Exception as e:

                if conn:
                    conn.rollback()

                st.error(
                    "❌ لم يتم حفظ المستخدم في قاعدة البيانات."
                )

                st.code(str(e))

            finally:
                if conn:
                    conn.close()

    # ========================================================
    # تحميل المستخدمين
    # ========================================================

    st.markdown("---")
    st.markdown("### 📋 قائمة المستخدمين الحاليين")

    conn = None

    try:
        conn = get_db_connection()

        rows = conn.execute(
            """
            SELECT
                users.id,
                users.username,
                users.phone,
                users.password,
                users.role,
                users.branch_id,
                COALESCE(
                    branches.branch_name,
                    '🌐 كافة الفروع (الكل)'
                ) AS branch_name
            FROM users
            LEFT JOIN branches
                ON users.branch_id = branches.id
            ORDER BY users.id ASC
            """
        ).fetchall()

    except Exception as e:
        st.error("❌ تعذر تحميل المستخدمين.")
        st.code(str(e))
        rows = []

    finally:
        if conn:
            conn.close()

    user_rows = []

    for row in rows:
        user_rows.append({
            "المسلسل": row["id"],
            "اسم المستخدم": row["username"],
            "رقم الهاتف": row["phone"] or "",
            "كلمة المرور": row["password"],
            "الرتبة": row["role"],
            "الفرع": row["branch_name"]
        })

    udf = pd.DataFrame(user_rows)

    # ========================================================
    # عرض المستخدمين
    # ========================================================

    if udf.empty:
        st.info("لا توجد حسابات مستخدمين.")
        return

    if current_user_role == "Admin":
        selectable_users_df = udf.copy()

        # لا نعرض كلمات المرور في الجدول
        udf_display = udf.drop(
            columns=["كلمة المرور"]
        )

    else:
        selectable_users_df = udf[
            udf["الرتبة"] != "Admin"
        ].copy()

        udf_display = udf.drop(
            columns=["كلمة المرور"]
        )

    st.dataframe(
        udf_display,
        use_container_width=True,
        hide_index=True
    )

    # ========================================================
    # تعديل المستخدم - Admin فقط
    # ========================================================

    if current_user_role == "Admin":

        st.markdown("---")
        st.markdown(
            "### ✏️ تعديل بيانات المستخدم"
        )

        user_ids = udf["المسلسل"].tolist()

        edit_u_id = st.selectbox(
            "اختر المستخدم للتعديل:",
            user_ids,
            format_func=lambda x: (
                f"رقم {x} - "
                f"{udf.loc[
                    udf['المسلسل'] == x,
                    'اسم المستخدم'
                ].iloc[0]}"
            )
        )

        conn = None

        try:
            conn = get_db_connection()

            target_user_data = conn.execute(
                """
                SELECT *
                FROM users
                WHERE id = ?
                """,
                (edit_u_id,)
            ).fetchone()

        except Exception as e:
            st.error(
                "❌ تعذر تحميل بيانات المستخدم."
            )
            st.code(str(e))
            target_user_data = None

        finally:
            if conn:
                conn.close()

        if target_user_data:

            roles_list = [
                "Admin",
                "General_Supervisor",
                "Branch_Supervisor",
                "Cashier",
                "Viewer"
            ]

            current_role_idx = (
                roles_list.index(
                    target_user_data["role"]
                )
                if target_user_data["role"]
                in roles_list
                else 0
            )

            branch_keys = list(
                b_opts_dict.keys()
            )

            curr_b_name = (
                "🌐 كافة الفروع (الكل)"
            )

            for b_name, b_id in b_opts_dict.items():

                if (
                    b_id
                    == target_user_data["branch_id"]
                ):
                    curr_b_name = b_name
                    break

            curr_b_idx = (
                branch_keys.index(curr_b_name)
                if curr_b_name in branch_keys
                else 0
            )

            with st.form("edit_user_form"):

                e_col1, e_col2 = st.columns(2)

                with e_col1:

                    new_uname = st.text_input(
                        "تعديل اسم المستخدم:",
                        value=target_user_data[
                            "username"
                        ]
                    )

                    new_pass = st.text_input(
                        "كلمة مرور جديدة "
                        "(اتركها فارغة إذا لم ترغب بتغييرها):",
                        type="password"
                    )

                with e_col2:

                    new_role = st.selectbox(
                        "تعديل الرتبة:",
                        roles_list,
                        index=current_role_idx
                    )

                    new_branch_sel = st.selectbox(
                        "تعديل الفرع:",
                        branch_keys,
                        index=curr_b_idx
                    )

                update_clicked = (
                    st.form_submit_button(
                        "💾 تحديث وحفظ التعديلات",
                        type="primary"
                    )
                )

            if update_clicked:

                if not new_uname.strip():

                    st.warning(
                        "⚠️ اسم المستخدم لا يمكن "
                        "أن يكون فارغاً."
                    )

                else:

                    conn = None

                    try:
                        conn = get_db_connection()

                        new_b_id = b_opts_dict[
                            new_branch_sel
                        ]

                        if new_pass.strip():

                            conn.execute(
                                """
                                UPDATE users
                                SET
                                    username = ?,
                                    password = ?,
                                    role = ?,
                                    branch_id = ?
                                WHERE id = ?
                                """,
                                (
                                    new_uname.strip(),
                                    new_pass,
                                    new_role,
                                    new_b_id,
                                    edit_u_id
                                )
                            )

                        else:

                            conn.execute(
                                """
                                UPDATE users
                                SET
                                    username = ?,
                                    role = ?,
                                    branch_id = ?
                                WHERE id = ?
                                """,
                                (
                                    new_uname.strip(),
                                    new_role,
                                    new_b_id,
                                    edit_u_id
                                )
                            )

                        conn.commit()

                        st.success(
                            "✅ تم تحديث بيانات "
                            "المستخدم بنجاح!"
                        )

                        st.rerun()

                    except Exception as e:

                        if conn:
                            conn.rollback()

                        st.error(
                            "❌ لم يتم حفظ التعديلات."
                        )

                        st.code(str(e))

                    finally:
                        if conn:
                            conn.close()

    # ========================================================
    # حذف المستخدم
    # ========================================================

    st.markdown("---")
    st.markdown("### 🗑️ حذف مستخدم")

    if selectable_users_df.empty:

        st.info(
            "لا توجد حسابات أخرى متاحة للحذف."
        )

        return

    del_u = st.selectbox(
        "اختر المستخدم للحذف:",
        selectable_users_df[
            "المسلسل"
        ].tolist(),
        format_func=lambda x: (
            f"رقم {x} - "
            f"{udf.loc[
                udf['المسلسل'] == x,
                'اسم المستخدم'
            ].iloc[0]} "
            f"({udf.loc[
                udf['المسلسل'] == x,
                'الرتبة'
            ].iloc[0]})"
        ),
        key="del_select_box"
    )

    conn = None

    try:
        conn = get_db_connection()

        selected_row_user = conn.execute(
            """
            SELECT username, role
            FROM users
            WHERE id = ?
            """,
            (del_u,)
        ).fetchone()

        admin_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE role = 'Admin'
            """
        ).fetchone()[0]

    except Exception as e:

        st.error(
            "❌ تعذر التحقق من المستخدم."
        )

        st.code(str(e))

        selected_row_user = None
        admin_count = 0

    finally:
        if conn:
            conn.close()

    if not selected_row_user:
        return

    selected_username = (
        selected_row_user["username"]
        .strip()
        .lower()
    )

    selected_role = selected_row_user["role"]

    is_admin_target = (
        selected_role == "Admin"
        or selected_username == "admin"
    )

    is_self_target = (
        selected_username
        == current_username.strip().lower()
    )

    can_delete = True
    delete_error_msg = ""

    if is_self_target:

        can_delete = False

        delete_error_msg = (
            "⚠️ لا يمكنك حذف حسابك الشخصي "
            "أثناء تسجيل الدخول به!"
        )

    elif is_admin_target:

        if current_user_role != "Admin":

            can_delete = False

            delete_error_msg = (
                "❌ لا تملك صلاحية حذف "
                "حسابات Admin."
            )

        elif admin_count <= 1:

            can_delete = False

            delete_error_msg = (
                "❌ لا يمكن حذف الأدمن الوحيد "
                "المتبقي في النظام!"
            )

    if not can_delete:

        st.warning(delete_error_msg)

    if st.button(
        "🗑️ حذف المستخدم المختار",
        type="primary",
        disabled=not can_delete
    ):

        conn = None

        try:
            conn = get_db_connection()

            conn.execute(
                """
                DELETE FROM users
                WHERE id = ?
                """,
                (del_u,)
            )

            conn.commit()

            st.success(
                "✅ تم حذف المستخدم بنجاح!"
            )

            st.rerun()

        except Exception as e:

            if conn:
                conn.rollback()

            st.error(
                "❌ لم يتم حذف المستخدم."
            )

            st.code(str(e))

        finally:
            if conn:
                conn.close()
