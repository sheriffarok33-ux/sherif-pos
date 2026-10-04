from ui_common import back_button
from ui_common import item_alerts
import streamlit as st
from database import get_db_connection


# ============================================================
# نافذة التأكيد الأمني
# ============================================================

@st.dialog("🔒 تأكيد أمني لتنفيذ العملية")
def secure_action_dialog(action_title, callback_func, *args):

    st.warning(
        f"⚠️ أنت على وشك تنفيذ: **{action_title}**.\n\n"
        "يرجى إدخال كلمة المرور لتأكيد التنفيذ:"
    )

    password_input = st.text_input(
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

                user_chk = conn.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE id = ?
                    AND password = ?
                    """,
                    (user_id, password_input)
                ).fetchone()

            except Exception as e:

                st.error("❌ تعذر التحقق من كلمة المرور.")
                st.code(str(e))
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

def execute_add_surplus(b_id, item_id, qty_val):

    conn = None

    try:
        conn = get_db_connection()

        # التأكد أن الصنف تابع للفرع
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

        # تحديث الكمية
        conn.execute(
            """
            UPDATE items
            SET quantity = quantity + ?
            WHERE id = ?
            AND branch_id = ?
            """,
            (qty_val, item_id, b_id)
        )

        # تسجيل حركة التسوية
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
                qty_val,
                "فائض",
                0.0,
                "إضافة فائض من شاشة تسويات المخزون"
            )
        )

        conn.commit()

        _adjustments_done("تمت إضافة الفائض وتحديث كمية الصنف بنجاح.")

    except Exception as e:

        if conn:
            conn.rollback()

        st.error("⚠️ حدث خطأ أثناء إضافة الفائض:")
        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# التوالف / المرتجعات
# ============================================================

def execute_damage_return(
    b_id,
    item_id,
    qty_val,
    reason_type
):

    conn = None

    try:
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
            SET quantity = GREATEST(
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
        st.code(str(e))

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

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# الواجهة
# ============================================================

@st.dialog("✅ تمت العملية بنجاح")
def _adjustments_success_dialog():
    st.success(st.session_state.get("adjustments_success_message", "تمت العملية بنجاح."))
    if st.button("موافق", type="primary", use_container_width=True, key="adjustments_success_ok"):
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


    st.header(
        "➕ الفائض، التوالف، المرتجعات وتعديل الأسعار"
    )

    st.info(
        "💡 إدارة دقيقة ومستقلة لتصحيح "
        "كميات المخزون وتعميم الأسعار."
    )

    role = st.session_state.get(
        "role",
        ""
    )

    if role not in [
        "Admin",
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

        st.code(str(e))

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

    sel_branch_name = st.selectbox(
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

        st.code(str(e))

        all_branch_items = []

    finally:

        if conn:
            conn.close()

    st.markdown("---")

    tab1, tab2, tab3 = st.tabs([
        "➕ إضافة فائض فرع (أصناف رصيدها صفر)",
        "♻️ تسجيل التوالف والمرتجعات",
        "✏️ تعديل وتعميم سعر الصنف"
    ])

    # ========================================================
    # إضافة فائض
    # ========================================================

    with tab1:

        st.subheader(
            "➕ إضافة كمية فائضة لفرع "
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

            with st.form("surplus_form"):

                sel_zero_label = st.selectbox(
                    "اختر الصنف (الرصيد صفر):",
                    list(zero_dict.keys())
                )

                surplus_qty = st.number_input(
                    "الكمية الفاضلة المراد إضافتها (كجم):",
                    min_value=0.0,
                    value=1.0,
                    step=0.5,
                    format="%.2f"
                )

                surplus_submit = (
                    st.form_submit_button(
                        "🚀 اعتماد وإضافة الفائض",
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
                            f"إضافة فائض بقيمة "
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

            with st.form(
                "damage_return_form"
            ):

                sel_item_label = st.selectbox(
                    "اختر الصنف:",
                    list(
                        branch_item_dict.keys()
                    )
                )

                qty_val = st.number_input(
                    "الكمية المراد خصمها:",
                    min_value=0.0,
                    value=1.0,
                    step=0.5,
                    format="%.2f"
                )

                reason_type = st.selectbox(
                    "سبب الخروج / الإرجاع:",
                    [
                        "تالف / هالك",
                        "منتهى الصلاحية"
                    ]
                )

                damage_submit = (
                    st.form_submit_button(
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

            with st.form(
                "price_update_form"
            ):

                sel_p_label = st.selectbox(
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

                new_price = st.number_input(
                    "سعر البيع الجديد (د.ل):",
                    min_value=0.0,
                    value=curr_sale_price,
                    step=0.5,
                    format="%.2f"
                )

                price_submit = (
                    st.form_submit_button(
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
