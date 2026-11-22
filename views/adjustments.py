_PAGE_ERROR_UI_REVISION = 68
from views.page_guard import show_operation_error
from views.dashboard import _validated_role
from views.ui_feedback import ui_field, ui_form, ui_submit, notify_success, reset_page_fields
from views.ui_common import back_button
from views.ui_common import item_alerts
import streamlit as st
from database import get_db_connection


# ============================================================
# نافذة التأكيد الأمني
# ============================================================

@st.dialog("🔒 تأكيد أمني لتنفيذ العملية")
def secure_action_dialog(action_title, callback_func, *args):

    _validated_role()
    st.warning(
        f"⚠️ أنت على وشك تنفيذ: **{action_title}**.\n\n"
        "يرجى إدخال كلمة المرور لتأكيد التنفيذ:"
    )

    password_input = ui_field(st.text_input, "adjustments:19", 
        "كلمة المرور:",
        type="password",
        key="sec_action_pass_input"
    )

    col_yes, col_no = st.columns(2)

    with col_yes:

        if st.button(
            "✅ تأكيد وتنفيذ",
            type="primary",
            use_container_width=True
        ):

            conn = None

            try:
                conn = get_db_connection()

                user_id = st.session_state.get("user_id")

                from branch_auth import verify_local_user_password
                user_chk = verify_local_user_password(user_id, password_input)

            except Exception as e:

                st.error("❌ تعذر التحقق من كلمة المرور.")
                show_operation_error(e, announce=False, context='views/adjustments.py:51')
                return

            finally:

                if conn:
                    conn.close()

            if user_chk:
                callback_func(*args)

            else:
                st.error("❌ كلمة المرور غير صحيحة!")

    with col_no:

        if st.button(
            "❌ إلغاء",
            use_container_width=True
        ):
            st.rerun()


# ============================================================
# إضافة فائض
# ============================================================

def _positive_adjustment_quantity(value):
    """Invalid quantities must never reach an inventory adjustment transaction."""
    import math
    if isinstance(value, bool):
        raise ValueError('الكمية يجب أن تكون رقماً موجباً صالحاً.')
    try:
        quantity = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('الكمية يجب أن تكون رقماً موجباً صالحاً.') from None
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError('الكمية يجب أن تكون أكبر من صفر ومحدودة.')
    return quantity


def _execute_linked_exception_settlement(branch_id,item_id,quantity,invoice_id,settlement_uuid):
    import json
    from control_services import apply_exception_settlement
    if not settlement_uuid:raise ValueError('مرجع طلب التسوية مفقود؛ أعد فتح تأكيد العملية')
    from offline_store import get_pos_connection,get_device_id,_erp_reference
    conn,_=get_pos_connection(st.session_state.get('user_id'))
    try:
        invoice_table='branch_exception_cache' if int(invoice_id)<0 else 'invoices'
        invoice_id=abs(int(invoice_id))
        invoice=conn.execute('SELECT offline_uuid FROM '+invoice_table+' WHERE id=? AND branch_id=?',(invoice_id,branch_id)).fetchone()
        authority=conn.execute('SELECT device_id,authority_uuid FROM branch_settlement_authorities WHERE branch_id=?',(branch_id,)).fetchone()
        if not invoice or not invoice['offline_uuid'] or not authority:raise ValueError('مرجع الفاتورة أو تفويض الجهاز غير متاح')
        device_id=get_device_id()
        payload={'settlement_uuid':settlement_uuid,'branch_id':int(branch_id),'invoice_uuid':invoice['offline_uuid'],
            'item_reference':_erp_reference(conn,'items',item_id),'quantity':str(quantity),
            'device_id':device_id,'authority_uuid':authority['authority_uuid'],'actor_id':int(st.session_state['user_id'])}
        encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'))
        apply_exception_settlement(conn,settlement_uuid=settlement_uuid,branch_id=branch_id,item_id=item_id,
            invoice_id=invoice_id,invoice_identity=invoice['offline_uuid'],device_id=device_id,
            authority_uuid=authority['authority_uuid'],quantity=quantity,actor_id=payload['actor_id'],payload_json=encoded,invoice_table=invoice_table)
        conn.commit()
    except Exception:
        conn.rollback();raise
    finally:conn.close()
    _adjustments_done('تم حفظ التسوية محلياً؛ سيُستكمل تأكيد السيرفر تلقائياً.')


def execute_add_surplus(b_id,item_id,qty_val,exception_invoice_id=None,settlement_uuid=None):
    _validated_role()
    if exception_invoice_id is not None:
        return _execute_linked_exception_settlement(b_id,item_id,qty_val,exception_invoice_id,settlement_uuid)
    conn=None
    try:
        import uuid
        from views.item_surplus import add_surplus
        identity=st.session_state.setdefault('adjustment_surplus_uuid',str(uuid.uuid4()))
        conn=get_db_connection()
        add_surplus(conn,b_id,item_id,qty_val,st.session_state.get('user_id'),identity)
        conn.commit()
        st.session_state.pop('adjustment_surplus_uuid',None)
        _adjustments_done('تم تسجيل فائض صنف.')
    except Exception as e:
        if conn:conn.rollback()
        st.error('تعذر تسجيل فائض صنف.')
        show_operation_error(e,announce=False,context='فائض صنف')
    finally:
        if conn:conn.close()



# ============================================================
# التوالف / المرتجعات
# ============================================================

def execute_damage_return(
    b_id,
    item_id,
    qty_val,
    reason_type
):

    _validated_role()
    conn = None

    try:
        qty_val = _positive_adjustment_quantity(qty_val)
        conn = get_db_connection()

        # قفل السجل أثناء تنفيذ العملية
        item = conn.execute(
            """
            SELECT id, item_name, quantity
            FROM items
            WHERE id = ?
            AND branch_id = ?
            FOR UPDATE
            """,
            (item_id, b_id)
        ).fetchone()

        if not item:
            raise ValueError(
                "الصنف غير موجود في الفرع المحدد."
            )

        current_qty = float(
            item["quantity"] or 0
        )

        if qty_val <= 0:
            raise ValueError(
                "الكمية يجب أن تكون أكبر من صفر."
            )

        if qty_val > current_qty:
            raise ValueError(
                f"الكمية المطلوبة ({qty_val}) "
                f"أكبر من الرصيد المتاح ({current_qty})."
            )

        # PostgreSQL يستخدم GREATEST بدلاً من MAX
        conn.execute(
            """
            UPDATE items
            SET quantity = MAX(
                0,
                quantity - ?
            )
            WHERE id = ?
            AND branch_id = ?
            """,
            (
                qty_val,
                item_id,
                b_id
            )
        )

        # تسجيل الحركة
        conn.execute(
            """
            INSERT INTO stock_adjustments
            (
                branch_id,
                item_id,
                item_name,
                quantity,
                adjustment_type,
                loss_or_gain_value,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                b_id,
                item_id,
                item["item_name"],
                -qty_val,
                reason_type,
                0.0,
                f"خصم مخزون بسبب: {reason_type}"
            )
        )

        conn.commit()

        _adjustments_done(f"تم تسجيل العملية بنجاح (السبب: {reason_type}) وخصم الكمية.")

    except Exception as e:

        if conn:
            conn.rollback()

        st.error("⚠️ حدث خطأ أثناء تنفيذ العملية:")
        show_operation_error(e, announce=False, context='views/adjustments.py:333')

    finally:

        if conn:
            conn.close()


# ============================================================
# تعديل السعر على كافة الفروع
# ============================================================

def execute_global_price_update(
    item_code,
    new_sale_price
):

    _validated_role()
    conn = None

    try:
        conn = get_db_connection()

        if not item_code:
            raise ValueError(
                "الصنف لا يمتلك كوداً صالحاً."
            )

        if new_sale_price < 0:
            raise ValueError(
                "سعر البيع لا يمكن أن يكون سالباً."
            )

        result = conn.execute(
            """
            UPDATE items
            SET sale_price = ?
            WHERE item_code = ?
            """,
            (
                new_sale_price,
                item_code
            )
        )

        if result.rowcount == 0:
            raise ValueError(
                "لم يتم العثور على الصنف "
                "في أي فرع."
            )

        conn.commit()

        _adjustments_done("تم تعديل سعر البيع وتعميمه على كافة الفروع بنجاح.")

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "⚠️ حدث خطأ أثناء تعميم السعر:"
        )

        show_operation_error(e, announce=False, context='views/adjustments.py:397')

    finally:

        if conn:
            conn.close()


# ============================================================
# الواجهة
# ============================================================

@st.dialog("✅ تمت العملية بنجاح", dismissible=False)
def _adjustments_success_dialog():
    _validated_role()
    st.success(st.session_state.get("adjustments_success_message", "تمت العملية بنجاح."))
    if st.button("موافق", type="primary", use_container_width=True, key="adjustments_success_ok"):
        reset_page_fields()
        st.session_state.pop("adjustments_success_pending", None)
        st.session_state.pop("adjustments_success_message", None)
        st.rerun()


def _adjustments_done(message):
    st.session_state["adjustments_success_message"] = message
    st.session_state["adjustments_success_pending"] = True
    st.rerun()


def show_page():
    back_button(key="back_adjustments")

    item_alerts(st.session_state.get("branch_id"), key="alerts_adjustments")

    if st.session_state.get("adjustments_success_pending"):
        _adjustments_success_dialog()
        st.stop()


    st.header(
        "➕ الفائض، التوالف، المرتجعات وتعديل الأسعار"
    )

    st.info(
        "💡 إدارة دقيقة ومستقلة لتصحيح "
        "كميات المخزون وتعميم الأسعار."
    )

    role = _validated_role()

    if role not in [
        "Super_Admin", "Admin",
        "General_Supervisor",
        "Manager"
    ]:

        st.error(
            "❌ هذه الصفحة مخصصة "
            "للإدارة والمشرفين فقط!"
        )

        return

    # ========================================================
    # تحميل الفروع
    # ========================================================

    conn = None

    try:
        conn = get_db_connection()

        branches = conn.execute(
            """
            SELECT id, branch_name
            FROM branches
            ORDER BY id ASC
            """
        ).fetchall()

    except Exception as e:

        st.error(
            "❌ تعذر تحميل الفروع."
        )

        show_operation_error(e, announce=False, context='views/adjustments.py:483')

        return

    finally:

        if conn:
            conn.close()

    if not branches:

        st.warning(
            "⚠️ لا توجد فروع مسجلة في النظام."
        )

        return

    branch_dict = {
        b["branch_name"]: b["id"]
        for b in branches
    }

    sel_branch_name = ui_field(st.selectbox, "adjustments:434", 
        "اختر الفرع المستهدف:",
        list(branch_dict.keys())
    )

    sel_b_id = branch_dict[
        sel_branch_name
    ]

    # ========================================================
    # تحميل أصناف الفرع
    # ========================================================

    conn = None

    try:
        conn = get_db_connection()

        all_branch_items = conn.execute(
            """
            SELECT
                id,
                item_code,
                item_name,
                quantity,
                sale_price
            FROM items
            WHERE branch_id = ?
            ORDER BY item_name ASC
            """,
            (sel_b_id,)
        ).fetchall()

    except Exception as e:

        st.error(
            "❌ تعذر تحميل أصناف الفرع."
        )

        show_operation_error(e, announce=False, context='views/adjustments.py:544')

        all_branch_items = []

    finally:

        if conn:
            conn.close()

    st.markdown("---")

    tab1, tab2, tab3 = st.tabs([
        "فائض صنف",
        "♻️ تسجيل التوالف والمرتجعات",
        "✏️ تعديل وتعميم سعر الصنف"
    ])

    # ========================================================
    # إضافة فائض
    # ========================================================

    with tab1:

        st.subheader(
            "فائض صنف "
            "(الأصناف التي كميتها صفر)"
        )

        zero_items = [
            item
            for item in all_branch_items
            if float(item["quantity"] or 0) <= 0
        ]

        if zero_items:

            zero_dict = {
                (
                    f"[{it['item_code'] or 'بدون'}] "
                    f"{it['item_name']}"
                ): it
                for it in zero_items
            }

            with ui_form("surplus_form"):

                sel_zero_label = ui_field(st.selectbox, "adjustments:519", 
                    "اختر الصنف (الرصيد صفر):",
                    list(zero_dict.keys())
                )

                surplus_qty = ui_field(st.number_input, "adjustments:524", 
                    "الكمية الفاضلة المراد إضافتها (كجم):",
                    min_value=0.0,
                    value=1.0,
                    step=0.5,
                    format="%.2f"
                )

                surplus_submit = (
                    ui_submit(
                        "فائض صنف",
                        type="primary"
                    )
                )

            if surplus_submit:

                chosen_item = zero_dict[
                    sel_zero_label
                ]

                if surplus_qty > 0:

                    secure_action_dialog(
                        (
                            f"فائض صنف بقيمة "
                            f"{surplus_qty} للصنف "
                            f"({chosen_item['item_name']})"
                        ),
                        execute_add_surplus,
                        sel_b_id,
                        chosen_item["id"],
                        surplus_qty
                    )

                else:

                    st.warning(
                        "⚠️ يرجى إدخال كمية صحيحة."
                    )

        else:

            st.success(
                f"🎉 لا توجد أصناف برصيد صفر "
                f"في فرع ({sel_branch_name})."
            )

    # ========================================================
    # التوالف والمرتجعات
    # ========================================================

    with tab2:

        st.subheader(
            "♻️ تسجيل التوالف أو منتهي الصلاحية"
        )

        if all_branch_items:

            branch_item_dict = {
                (
                    f"[{it['item_code'] or 'بدون'}] "
                    f"{it['item_name']} "
                    f"(المتاح: {it['quantity']})"
                ): it
                for it in all_branch_items
            }

            with ui_form(
                "damage_return_form"
            ):

                sel_item_label = ui_field(st.selectbox, "adjustments:597", 
                    "اختر الصنف:",
                    list(
                        branch_item_dict.keys()
                    )
                )

                qty_val = ui_field(st.number_input, "adjustments:604", 
                    "الكمية المراد خصمها:",
                    min_value=0.0,
                    value=1.0,
                    step=0.5,
                    format="%.2f"
                )

                reason_type = ui_field(st.selectbox, "adjustments:612", 
                    "سبب الخروج / الإرجاع:",
                    [
                        "تالف / هالك",
                        "منتهى الصلاحية"
                    ]
                )

                damage_submit = (
                    ui_submit(
                        "🚀 تنفيذ وخصم الكمية",
                        type="primary"
                    )
                )

            if damage_submit:

                chosen_item = branch_item_dict[
                    sel_item_label
                ]

                available_qty = float(
                    chosen_item["quantity"] or 0
                )

                if qty_val <= 0:

                    st.warning(
                        "⚠️ يرجى إدخال كمية صحيحة."
                    )

                elif qty_val > available_qty:

                    st.error(
                        f"⚠️ الكمية المطلوبة أكبر "
                        f"من الرصيد المتاح حالياً "
                        f"({available_qty})!"
                    )

                else:

                    secure_action_dialog(
                        (
                            f"تسجيل ({reason_type}) "
                            f"للصنف "
                            f"({chosen_item['item_name']}) "
                            f"بكمية {qty_val}"
                        ),
                        execute_damage_return,
                        sel_b_id,
                        chosen_item["id"],
                        qty_val,
                        reason_type
                    )

        else:

            st.info(
                "لا توجد أصناف في هذا الفرع."
            )

    # ========================================================
    # تعديل السعر
    # ========================================================

    with tab3:

        st.subheader(
            "✏️ تعديل سعر البيع "
            "وتعميمه على كافة الفروع"
        )

        if all_branch_items:

            price_dict = {
                (
                    f"[{it['item_code'] or 'بدون'}] "
                    f"{it['item_name']}"
                ): it
                for it in all_branch_items
            }

            with ui_form(
                "price_update_form"
            ):

                sel_p_label = ui_field(st.selectbox, "adjustments:698", 
                    "اختر الصنف لتعديل سعره:",
                    list(price_dict.keys())
                )

                chosen_p_item = price_dict[
                    sel_p_label
                ]

                curr_sale_price = float(
                    chosen_p_item[
                        "sale_price"
                    ] or 0
                )

                new_price = ui_field(st.number_input, "adjustments:713", 
                    "سعر البيع الجديد (د.ل):",
                    min_value=0.0,
                    value=curr_sale_price,
                    step=0.5,
                    format="%.2f"
                )

                price_submit = (
                    ui_submit(
                        "🚀 حفظ وتعميم السعر الجديد "
                        "على كل الفروع",
                        type="primary"
                    )
                )

            if price_submit:

                if chosen_p_item["item_code"]:

                    secure_action_dialog(
                        (
                            f"تعديل وتعميم سعر الصنف "
                            f"({chosen_p_item['item_name']}) "
                            f"إلى {new_price} د.ل "
                            "لكل الفروع"
                        ),
                        execute_global_price_update,
                        chosen_p_item[
                            "item_code"
                        ],
                        new_price
                    )

                else:

                    st.error(
                        "❌ هذا الصنف لا يمتلك "
                        "كود/باركود، ولا يمكن تعميم "
                        "السعر بدونه."
                    )

        else:

            st.info(
                "لا توجد أصناف في هذا الفرع."
            )
