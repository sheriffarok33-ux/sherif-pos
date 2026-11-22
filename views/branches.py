_PAGE_ERROR_UI_REVISION = 60
from views.page_guard import show_operation_error
from views.dashboard import _validated_role
from views.ui_feedback import ui_field, ui_form, ui_submit, notify_success, reset_page_fields
from views.ui_common import back_button
import streamlit as st
import pandas as pd

from database import get_db_connection


# ============================================================
# حذف فرع / مخزن
# ============================================================

@st.dialog("🔒 تأكيد أمني لحذف الفرع أو المخزن")
def confirm_delete_branch_dialog(branch_id, branch_name):

    _validated_role()
    st.warning(
        f"⚠️ تنبيه خطير: أنت على وشك حذف الكيان "
        f"(**{branch_name}**).\n\n"
        "لا يمكن التراجع عن هذه الخطوة بعد تنفيذها!"
    )

    admin_pass = ui_field(st.text_input, "branches:21", 
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

                from branch_auth import verify_local_user_password
                user_check = verify_local_user_password(user_id, admin_pass)

                if not user_check:

                    st.error("❌ كلمة المرور غير صحيحة!")
                    return

                conn.execute(
                    "DELETE FROM branches WHERE id = ?",
                    (branch_id,)
                )

                conn.commit()

                notify_success("✅ تم حذف الفرع بنجاح!")

                st.rerun()

            except Exception as e:

                if conn:
                    conn.rollback()

                show_operation_error(e, announce=True, context='views/branches.py:72')

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

def _confirm_settlement_device(branch_id,device_id):
    from branch_auth import admin_assign_settlement_device
    admin_assign_settlement_device(branch_id,device_id)
    from offline_store import sync_exception_settlements
    sync_exception_settlements()
    notify_success('تم اعتماد جهاز التسويات وحفظ تفويض الجهاز محلياً عند تطابق الفرع.')
    st.rerun()


def show_page():
    _validated_role()
    back_button(key="back_branches")


    st.header("🏢 إدارة الفروع والمخازن المستقلة")

    if _validated_role() in ('Super_Admin','Admin','Manager'):
        try:
            from views.branch_sync_state import display_receipt_summary,invoice_receipt_summary
            if __import__('os').name=='nt':
                from central_inventory import load_overview
                data,_,_=load_overview(st.session_state.get('user_id'),_validated_role(),False,None)
            else:
                c=get_db_connection()
                try:
                    branches=[dict(row) for row in c.execute('SELECT id,branch_name FROM branches ORDER BY id').fetchall()]
                    data={'branches':branches,'last_synced_invoices':invoice_receipt_summary(c,[row['id'] for row in branches])}
                finally:c.close()
            display_receipt_summary(data,[row['id'] for row in data['branches']])
        except Exception as exc:st.warning('تعذر جلب آخر الفواتير المؤكدة: '+str(exc))

    if _validated_role() == 'Super_Admin':
        with st.expander('🖥️ إدارة وتهيئة أجهزة الفروع', expanded=True):
            from branch_auth import local_device_info, configure_local_device
            from offline_store import get_device_id
            info = local_device_info()
            st.caption('اعتماد مركزي من Super Admin؛ لا يمكن تكرار رقم جهاز نشط داخل الفرع.')
            st.code(get_device_id(), language=None)
            conn_device = get_db_connection()
            try:
                branch_options = conn_device.execute('SELECT id,branch_name FROM branches ORDER BY id').fetchall()
            finally:
                conn_device.close()
            if branch_options:
                ids = [int(b[0]) for b in branch_options]
                existing = info.get('bound_branch_id')
                current_index = ids.index(int(existing)) if existing and int(existing) in ids else 0
                with st.form('branch_device_local_config'):
                    target = st.selectbox('الفرع المرتبط بالجهاز', ids, index=current_index,
                        format_func=lambda x, _choices=tuple(branch_options): next(str(b[1]) for b in _choices if int(b[0]) == x))
                    device_name = st.text_input('اسم الجهاز', value=info.get('device_name') or '', max_chars=80)
                    device_num = st.text_input('رقم الجهاز', value=info.get('device_number') or '01', max_chars=24)
                    active = st.checkbox('الجهاز مفعل', value=info.get('device_active','1') == '1')
                    save = st.form_submit_button('💾 حفظ إعدادات الجهاز', use_container_width=True)
                if save:
                    try:
                        configure_local_device(target, device_name, device_num, active)
                        notify_success('تم اعتماد الجهاز مركزيًا وحفظ تعريفه محليًا')
                        st.rerun()
                    except Exception as exc:
                        show_operation_error(exc, announce=True, context='views/branches.py:156')
                st.caption('المزامنة لا تُغيّر الفرع أو رقم الجهاز تلقائيًا. لا تنقل الجهاز مع وجود معاملات معلقة.')

                if st.button('تحرير تفويض التسويات لهذا الجهاز',key='release_settlement_authority'):
                    from branch_auth import admin_release_settlement_device
                    from views.adjustments import secure_action_dialog
                    secure_action_dialog('تحرير تفويض جهاز التسويات',admin_release_settlement_device)
                if st.button('تحميل الأجهزة المعتمدة للتسويات',key='load_settlement_devices'):
                    from branch_auth import admin_list_devices
                    try:st.session_state['settlement_device_choices']=admin_list_devices()
                    except Exception:st.error('تعذر تحميل الأجهزة؛ يلزم دخول الإدارة أونلاين.')
                choices=[d for d in st.session_state.get('settlement_device_choices',[]) if int(d.get('branch_id') or 0)==int(target) and d.get('is_active')]
                if choices:
                    selected=st.selectbox('جهاز التسويات المعتمد للفرع',choices,format_func=lambda d:str(d.get('device_number') or d['device_id']),key='settlement_authority_choice')
                    if st.button('اعتماد جهاز التسويات',key='grant_settlement_authority'):
                        from views.adjustments import secure_action_dialog
                        secure_action_dialog('اعتماد جهاز التسويات',_confirm_settlement_device,target,selected['device_id'])




    st.info(
        "💡 من هنا يمكنك إضافة الفروع الجديدة للبيع اليومي "
        "أو المخازن الرئيسية، وتعديل أو حذف الفروع الحالية."
    )

    current_user_role = _validated_role()

    if current_user_role in ("Super_Admin", "Admin", "Manager", "General_Supervisor"):

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

        with ui_form(
            "new_branch_form_unique",
            clear_on_submit=False
        ):

            col1, col2 = st.columns(2)

            with col1:

                nb_name = ui_field(st.text_input, "branches:192", 
                    "اسم الفرع أو المخزن الجديد:"
                )

            with col2:

                nb_type = ui_field(st.selectbox, "branches:198", 
                    "نوع الكيان:",
                    ["فرع", "مخزن"]
                )

            save_new = ui_submit(
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

                    notify_success(
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

                    show_operation_error(e, announce=False, context='views/branches.py:325')

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

            show_operation_error(e, announce=False, context='views/branches.py:365')

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

            selected_branch_label = ui_field(st.selectbox, "branches:352", 
                "اختر الفرع أو المخزن للتحكم به:",
                list(branch_options.keys())
            )

            selected_b_id = branch_options[
                selected_branch_label
            ]
            if _validated_role() in ('Super_Admin','Manager'):
                try:
                    from views.branch_devices import render_branch_devices
                    render_branch_devices(selected_b_id)
                except Exception:
                    st.warning('تعذر تحميل أجهزة الفرع وتحديثاتها الآن؛ لا تغييرات على تسجيلها أو فواتيرها.')


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

                show_operation_error(e, announce=False, context='views/branches.py:466')

                b_data = None

            finally:

                if conn:
                    conn.close()

            # ================================================
            # تعديل / حذف
            # ================================================

            if b_data:

                with ui_form(
                    "edit_branch_form_unique"
                ):

                    e_name = ui_field(st.text_input, "branches:407", 
                        "تعديل الاسم:",
                        value=b_data["branch_name"]
                    )

                    e_type = ui_field(st.selectbox, "branches:412", 
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
                            ui_submit(
                                "💾 حفظ التعديلات",
                                type="primary"
                            )
                        )

                    with col_del:

                        del_clicked = (
                            ui_submit(
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

                            notify_success(
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

                            show_operation_error(e, announce=False, context='views/branches.py:574')

                        finally:

                            if conn:
                                conn.close()

                # ============================================
                # طلب الحذف
                # ============================================

                if del_clicked:

                    if current_user_role not in ("Super_Admin", "Admin", "Manager", "General_Supervisor"):

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
