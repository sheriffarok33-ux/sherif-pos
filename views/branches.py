import streamlit as st
import pandas as pd

from database import get_db_connection


# ============================================================
# حذف فرع / مخزن
# ============================================================

@st.dialog("🔒 تأكيد أمني لحذف الفرع أو المخزن")
def confirm_delete_branch_dialog(branch_id, branch_name):

    st.warning(
        f"⚠️ تنبيه خطير: أنت على وشك حذف الكيان "
        f"(**{branch_name}**).\n\n"
        "لا يمكن التراجع عن هذه الخطوة بعد تنفيذها!"
    )

    admin_pass = st.text_input(
        "أدخل كلمة المرور الخاصة بك للتأكيد:",
        type="password",
        key="del_branch_pass_input"
    )

    col_yes, col_no = st.columns(2)

    with col_yes:

        if st.button(
            "✅ تأكيد الحذف",
            type="primary",
            use_container_width=True
        ):

            conn = None

            try:

                conn = get_db_connection()

                user_id = st.session_state.get("user_id")

                user_check = conn.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE id = ?
                    AND password = ?
                    """,
                    (user_id, admin_pass)
                ).fetchone()

                if not user_check:

                    st.error("❌ كلمة المرور غير صحيحة!")
                    return

                conn.execute(
                    "DELETE FROM branches WHERE id = ?",
                    (branch_id,)
                )

                conn.commit()

                st.success("✅ تم حذف الفرع بنجاح!")

                st.rerun()

            except Exception as e:

                if conn:
                    conn.rollback()

                st.error(
                    f"❌ تعذر حذف الفرع.\n\n"
                    f"تفاصيل الخطأ: {e}"
                )

            finally:

                if conn:
                    conn.close()

    with col_no:

        if st.button(
            "❌ إلغاء",
            use_container_width=True
        ):

            st.rerun()


# ============================================================
# الصفحة الرئيسية
# ============================================================

def show_page():

    st.header("🏢 إدارة الفروع والمخازن المستقلة")

    st.info(
        "💡 من هنا يمكنك إضافة الفروع الجديدة للبيع اليومي "
        "أو المخازن الرئيسية، وتعديل أو حذف الفروع الحالية."
    )

    current_user_role = st.session_state.get("role", "")

    if current_user_role == "Admin":

        st.caption(
            "تلميح للإدارة: تحكم كامل في البنية "
            "التنظيمية للشركة وفروعها."
        )

    st.markdown("---")

    if "branches_ui_mode" not in st.session_state:


        st.session_state["branches_ui_mode"] = "manage"



    bnav1, bnav2 = st.columns(2)


    if bnav1.button(


        '📋 عرض وتعديل الفروع الحالية',


        use_container_width=True,


        type="primary" if st.session_state["branches_ui_mode"] == "manage" else "secondary"


    ):


        st.session_state["branches_ui_mode"] = "manage"


        st.rerun()



    if bnav2.button(


        '➕ إضافة فرع أو مخزن جديد',


        use_container_width=True,


        type="primary" if st.session_state["branches_ui_mode"] == "add" else "secondary"


    ):


        st.session_state["branches_ui_mode"] = "add"


        st.rerun()


    # ========================================================
    # إضافة فرع
    # ========================================================

    if st.session_state["branches_ui_mode"] == "add":

        st.subheader("➕ إضافة فرع أو مخزن جديد للنظام")

        with st.form(
            "new_branch_form_unique",
            clear_on_submit=True
        ):

            col1, col2 = st.columns(2)

            with col1:

                nb_name = st.text_input(
                    "اسم الفرع أو المخزن الجديد:"
                )

            with col2:

                nb_type = st.selectbox(
                    "نوع الكيان:",
                    ["فرع", "مخزن"]
                )

            save_new = st.form_submit_button(
                "💾 حفظ الكيان الجديد",
                type="primary"
            )

        if save_new:

            if not nb_name or not nb_name.strip():

                st.warning(
                    "⚠️ يرجى إدخال اسم صحيح."
                )

            else:

                conn = None

                try:

                    conn = get_db_connection()

                    conn.execute(
                        """
                        INSERT INTO branches
                        (branch_name, branch_type)
                        VALUES (?, ?)
                        """,
                        (
                            nb_name.strip(),
                            nb_type
                        )
                    )

                    conn.commit()

                    st.success(
                        f"✅ تم إضافة ({nb_name.strip()}) "
                        f"بنجاح كـ ({nb_type})!"
                    )

                    st.rerun()

                except Exception as e:

                    if conn:
                        conn.rollback()

                    st.error(
                        "❌ لم يتم حفظ الفرع في قاعدة البيانات."
                    )

                    st.code(str(e))

                finally:

                    if conn:
                        conn.close()

    # ========================================================
    # عرض الفروع
    # ========================================================

    if st.session_state["branches_ui_mode"] == "manage":

        st.subheader(
            "📋 الفروع والمخازن المسجلة حالياً"
        )

        conn = None

        try:

            conn = get_db_connection()

            raw_branches = conn.execute(
                """
                SELECT
                    id,
                    branch_name,
                    branch_type
                FROM branches
                ORDER BY id ASC
                """
            ).fetchall()

        except Exception as e:

            st.error(
                "❌ تعذر تحميل بيانات الفروع."
            )

            st.code(str(e))

            raw_branches = []

        finally:

            if conn:
                conn.close()

        # ====================================================
        # عرض الجدول
        # ====================================================

        if raw_branches:

            branch_rows = []

            branch_options = {}

            for row in raw_branches:

                branch_rows.append({

                    "المسلسل":
                        row["id"],

                    "اسم الفرع أو المخزن":
                        row["branch_name"],

                    "النوع":
                        row["branch_type"]

                })

                label = (
                    f"رقم {row['id']} - "
                    f"{row['branch_name']} "
                    f"({row['branch_type']})"
                )

                branch_options[label] = row["id"]

            branches_df = pd.DataFrame(
                branch_rows
            )

            st.dataframe(
                branches_df,
                use_container_width=True,
                hide_index=True
            )

            st.markdown("---")

            st.markdown(
                "### ⚙️ تعديل أو حذف فرع / مخزن معين"
            )

            selected_branch_label = st.selectbox(
                "اختر الفرع أو المخزن للتحكم به:",
                list(branch_options.keys())
            )

            selected_b_id = branch_options[
                selected_branch_label
            ]

            # ================================================
            # تحميل الفرع المختار
            # ================================================

            conn = None

            try:

                conn = get_db_connection()

                b_data = conn.execute(
                    """
                    SELECT
                        branch_name,
                        branch_type
                    FROM branches
                    WHERE id = ?
                    """,
                    (selected_b_id,)
                ).fetchone()

            except Exception as e:

                st.error(
                    "❌ تعذر تحميل بيانات الفرع."
                )

                st.code(str(e))

                b_data = None

            finally:

                if conn:
                    conn.close()

            # ================================================
            # تعديل / حذف
            # ================================================

            if b_data:

                with st.form(
                    "edit_branch_form_unique"
                ):

                    e_name = st.text_input(
                        "تعديل الاسم:",
                        value=b_data["branch_name"]
                    )

                    e_type = st.selectbox(
                        "تعديل النوع:",
                        ["فرع", "مخزن"],
                        index=(
                            0
                            if b_data["branch_type"] == "فرع"
                            else 1
                        )
                    )

                    col_save, col_del = st.columns(2)

                    with col_save:

                        save_clicked = (
                            st.form_submit_button(
                                "💾 حفظ التعديلات",
                                type="primary"
                            )
                        )

                    with col_del:

                        del_clicked = (
                            st.form_submit_button(
                                "🗑️ حذف هذا الكيان"
                            )
                        )

                # ============================================
                # حفظ التعديل
                # ============================================

                if save_clicked:

                    if not e_name.strip():

                        st.warning(
                            "⚠️ لا يمكن ترك الاسم فارغاً."
                        )

                    else:

                        conn = None

                        try:

                            conn = get_db_connection()

                            conn.execute(
                                """
                                UPDATE branches

                                SET
                                    branch_name = ?,
                                    branch_type = ?

                                WHERE id = ?
                                """,
                                (
                                    e_name.strip(),
                                    e_type,
                                    selected_b_id
                                )
                            )

                            conn.commit()

                            st.success(
                                "✅ تم تحديث بيانات "
                                "الكيان بنجاح!"
                            )

                            st.rerun()

                        except Exception as e:

                            if conn:
                                conn.rollback()

                            st.error(
                                "❌ لم يتم حفظ التعديل."
                            )

                            st.code(str(e))

                        finally:

                            if conn:
                                conn.close()

                # ============================================
                # طلب الحذف
                # ============================================

                if del_clicked:

                    if current_user_role != "Admin":

                        st.error(
                            "❌ عملية حذف الفروع مقتصرة "
                            "على الأدمن (Admin) فقط."
                        )

                    else:

                        confirm_delete_branch_dialog(
                            selected_b_id,
                            b_data["branch_name"]
                        )

        else:

            st.info(
                "لا توجد فروع أو مخازن مسجلة حالياً."
            )
