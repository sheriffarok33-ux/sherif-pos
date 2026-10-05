from views.ui_common import back_button
from views.ui_common import item_alerts
import streamlit as st
import pandas as pd
from database import get_db_connection
from datetime import date, datetime, timedelta


# ============================================================
# تحميل المخزن الرئيسي وأصنافه
# ============================================================

def get_main_store_data():

    conn = None

    try:

        conn = get_db_connection()

        main_store = conn.execute(
            """
            SELECT
                id,
                branch_name
            FROM branches
            WHERE branch_type = 'مخزن'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()

        if not main_store:
            return None, []

        items = conn.execute(
            """
            SELECT
                id,
                item_code,
                item_name,
                quantity,
                buy_price,
                sale_price,
                avg_cost
            FROM items
            WHERE branch_id = ?
            ORDER BY item_name ASC
            """,
            (main_store["id"],)
        ).fetchall()

        return main_store, items

    finally:

        if conn:
            conn.close()


# ============================================================
# اعتماد الخلطة
# ============================================================

def execute_mix(
    store_id,
    mix_list,
    target_item_id,
    new_sale_price,
    username
):

    conn = None

    try:

        if not mix_list:
            raise ValueError(
                "قائمة الخلط فارغة."
            )

        if not target_item_id:
            raise ValueError(
                "يجب اختيار الصنف الناتج."
            )

        # تجميع نفس الخام لو اتضاف أكثر من مرة
        merged_materials = {}

        for material in mix_list:

            item_id = int(
                material["id"]
            )

            qty = float(
                material["qty"]
            )

            if qty <= 0:
                raise ValueError(
                    "يوجد وزن غير صحيح "
                    "في قائمة الخلط."
                )

            if item_id not in merged_materials:

                merged_materials[item_id] = {
                    "id": item_id,
                    "name": material["name"],
                    "code": material["code"],
                    "qty": 0.0
                }

            merged_materials[
                item_id
            ]["qty"] += qty

        conn = get_db_connection()

        total_mix_weight = 0.0
        total_mix_cost = 0.0

        # ====================================================
        # قفل وفحص الخامات
        # ====================================================

        for material in (
            merged_materials.values()
        ):

            row = conn.execute(
                """
                SELECT
                    id,
                    item_name,
                    item_code,
                    quantity,
                    buy_price,
                    avg_cost
                FROM items
                WHERE id = ?
                  AND branch_id = ?
                FOR UPDATE
                """,
                (
                    material["id"],
                    store_id
                )
            ).fetchone()

            if not row:

                raise ValueError(
                    f"الخامة "
                    f"({material['name']}) "
                    "لم تعد موجودة بالمخزن."
                )

            available_qty = float(
                row["quantity"] or 0
            )

            required_qty = float(
                material["qty"]
            )

            if required_qty > available_qty:

                raise ValueError(
                    f"الكمية غير كافية من "
                    f"({row['item_name']}). "
                    f"المتاح "
                    f"{available_qty:,.2f} كجم "
                    f"والمطلوب "
                    f"{required_qty:,.2f} كجم."
                )

            unit_cost = float(
                row["avg_cost"] or 0
            )

            if unit_cost <= 0:

                unit_cost = float(
                    row["buy_price"] or 0
                )

            material[
                "actual_cost"
            ] = unit_cost

            total_mix_weight += (
                required_qty
            )

            total_mix_cost += (
                required_qty
                * unit_cost
            )

        if total_mix_weight <= 0:

            raise ValueError(
                "إجمالي وزن الخلطة "
                "يجب أن يكون أكبر من صفر."
            )

        new_mix_cost = (
            total_mix_cost
            / total_mix_weight
        )

        # ====================================================
        # قفل الصنف الناتج
        # ====================================================

        target = conn.execute(
            """
            SELECT
                id,
                item_name,
                quantity,
                avg_cost,
                buy_price
            FROM items
            WHERE id = ?
              AND branch_id = ?
            FOR UPDATE
            """,
            (
                target_item_id,
                store_id
            )
        ).fetchone()

        if not target:

            raise ValueError(
                "الصنف الناتج غير موجود "
                "في المخزن."
            )

        # ====================================================
        # خصم الخامات
        # ====================================================

        for material in (
            merged_materials.values()
        ):

            conn.execute(
                """
                UPDATE items
                SET quantity =
                    quantity - ?
                WHERE id = ?
                  AND branch_id = ?
                """,
                (
                    material["qty"],
                    material["id"],
                    store_id
                )
            )

        # ====================================================
        # حساب متوسط تكلفة الصنف الناتج
        #
        # لو الصنف الناتج له رصيد قديم:
        # ندمج تكلفته القديمة مع تكلفة
        # الخلطة الجديدة.
        # ====================================================

        old_target_qty = float(
            target["quantity"] or 0
        )

        old_target_cost = float(
            target["avg_cost"] or 0
        )

        if old_target_cost <= 0:

            old_target_cost = float(
                target["buy_price"] or 0
            )

        # لو الصنف الناتج نفسه من الخامات
        # نحتاج حساب الرصيد المتبقي بعد الخصم
        target_consumed_qty = 0.0

        if (
            target_item_id
            in merged_materials
        ):

            target_consumed_qty = float(
                merged_materials[
                    target_item_id
                ]["qty"]
            )

        remaining_target_qty = max(
            0.0,
            old_target_qty
            - target_consumed_qty
        )

        final_target_qty = (
            remaining_target_qty
            + total_mix_weight
        )

        old_remaining_value = (
            remaining_target_qty
            * old_target_cost
        )

        final_target_value = (
            old_remaining_value
            + total_mix_cost
        )

        if final_target_qty > 0:

            final_avg_cost = (
                final_target_value
                / final_target_qty
            )

        else:

            final_avg_cost = (
                new_mix_cost
            )

        # لأننا خصمنا الخام بالفعل،
        # نضبط الرصيد النهائي مباشرة
        conn.execute(
            """
            UPDATE items
            SET
                quantity = ?,
                avg_cost = ?,
                buy_price = ?,
                sale_price = ?
            WHERE id = ?
              AND branch_id = ?
            """,
            (
                final_target_qty,
                final_avg_cost,
                new_mix_cost,
                float(new_sale_price),
                target_item_id,
                store_id
            )
        )

        materials_details = "\n".join(
            f"{m['name']} [{m['code']}] - {float(m['qty']):,.2f} كجم"
            for m in merged_materials.values()
        )

        production_notes = (
            f"الخامات:\n{materials_details}\n"
            f"الصنف الناتج: {target['item_name']}\n"
            f"وزن الناتج: {total_mix_weight:,.2f} كجم\n"
            f"إجمالي التكلفة: {total_mix_cost:,.2f} د.ل\n"
            f"تكلفة الكيلو: {new_mix_cost:,.2f} د.ل\n"
            f"سعر البيع: {float(new_sale_price):,.2f} د.ل\n"
            f"بواسطة: {username or 'غير محدد'}"
        )

        conn.execute(
            """
            INSERT INTO production_logs
            (
                branch_id,
                production_type,
                source_item_id,
                source_item_name,
                target_item_id,
                target_item_name,
                input_quantity,
                output_quantity,
                loss_quantity,
                total_cost,
                unit_cost,
                sale_price,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                store_id,
                "خلط",
                None,
                "خلطة متعددة الخامات",
                target_item_id,
                target["item_name"],
                total_mix_weight,
                total_mix_weight,
                0.0,
                total_mix_cost,
                new_mix_cost,
                float(new_sale_price),
                production_notes
            )
        )

        conn.commit()

        _production_done(
            "تم اعتماد الخلطة بنجاح. "
            f"الوزن الناتج: {total_mix_weight:,.2f} كجم — "
            f"تكلفة الخلطة: {total_mix_cost:,.2f} د.ل — "
            f"تكلفة الكيلو المنتج: {new_mix_cost:,.2f} د.ل — "
            f"متوسط تكلفة الرصيد بعد الدمج: {final_avg_cost:,.2f} د.ل"
        )

    except ValueError as e:

        if conn:
            conn.rollback()

        st.warning(
            f"⚠️ {e}"
        )

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تنفيذ عملية الخلط."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# اعتماد التحميص
# ============================================================

def execute_roasting(
    store_id,
    raw_item_id,
    target_item_id,
    raw_weight,
    roasted_weight,
    sale_price,
    username
):

    conn = None

    try:

        raw_weight = float(
            raw_weight
        )

        roasted_weight = float(
            roasted_weight
        )

        sale_price = float(
            sale_price
        )

        if raw_weight <= 0:

            raise ValueError(
                "الوزن الخام يجب أن "
                "يكون أكبر من صفر."
            )

        if roasted_weight <= 0:

            raise ValueError(
                "الوزن بعد التحميص يجب "
                "أن يكون أكبر من صفر."
            )

        if roasted_weight > raw_weight:

            raise ValueError(
                "الوزن بعد التحميص لا يمكن "
                "أن يكون أكبر من الوزن الخام."
            )

        if not target_item_id:

            raise ValueError(
                "يجب اختيار الصنف الناتج "
                "بعد التحميص."
            )

        conn = get_db_connection()

        # ====================================================
        # الخام
        # ====================================================

        raw_item = conn.execute(
            """
            SELECT
                id,
                item_code,
                item_name,
                quantity,
                buy_price,
                avg_cost
            FROM items
            WHERE id = ?
              AND branch_id = ?
            FOR UPDATE
            """,
            (
                raw_item_id,
                store_id
            )
        ).fetchone()

        if not raw_item:

            raise ValueError(
                "الصنف الخام غير موجود."
            )

        available_qty = float(
            raw_item["quantity"] or 0
        )

        if raw_weight > available_qty:

            raise ValueError(
                f"الكمية غير كافية من "
                f"({raw_item['item_name']}). "
                f"المتاح "
                f"{available_qty:,.2f} كجم."
            )

        raw_unit_cost = float(
            raw_item["avg_cost"] or 0
        )

        if raw_unit_cost <= 0:

            raw_unit_cost = float(
                raw_item["buy_price"] or 0
            )

        total_raw_cost = (
            raw_weight
            * raw_unit_cost
        )

        # ====================================================
        # تكلفة المنتج بعد الفقد
        # ====================================================

        roasted_unit_cost = (
            total_raw_cost
            / roasted_weight
        )

        loss_weight = (
            raw_weight
            - roasted_weight
        )

        loss_percent = (
            (
                loss_weight
                / raw_weight
            )
            * 100
        )

        # ====================================================
        # الصنف الناتج
        # ====================================================

        target = conn.execute(
            """
            SELECT
                id,
                item_name,
                quantity,
                buy_price,
                avg_cost
            FROM items
            WHERE id = ?
              AND branch_id = ?
            FOR UPDATE
            """,
            (
                target_item_id,
                store_id
            )
        ).fetchone()

        if not target:

            raise ValueError(
                "الصنف الناتج بعد التحميص "
                "غير موجود."
            )

        old_target_qty = float(
            target["quantity"] or 0
        )

        old_target_cost = float(
            target["avg_cost"] or 0
        )

        if old_target_cost <= 0:

            old_target_cost = float(
                target["buy_price"] or 0
            )

        # ====================================================
        # لو الخام والناتج نفس الصنف
        # ====================================================

        if raw_item_id == target_item_id:

            remaining_qty = (
                old_target_qty
                - raw_weight
            )

            final_qty = (
                remaining_qty
                + roasted_weight
            )

            remaining_value = (
                remaining_qty
                * old_target_cost
            )

            final_value = (
                remaining_value
                + total_raw_cost
            )

            final_avg_cost = (
                final_value
                / final_qty
                if final_qty > 0
                else roasted_unit_cost
            )

            conn.execute(
                """
                UPDATE items
                SET
                    quantity = ?,
                    avg_cost = ?,
                    buy_price = ?,
                    sale_price = ?
                WHERE id = ?
                  AND branch_id = ?
                """,
                (
                    final_qty,
                    final_avg_cost,
                    roasted_unit_cost,
                    sale_price,
                    target_item_id,
                    store_id
                )
            )

        # ====================================================
        # لو الخام والناتج صنفين مختلفين
        # ====================================================

        else:

            conn.execute(
                """
                UPDATE items
                SET quantity =
                    quantity - ?
                WHERE id = ?
                  AND branch_id = ?
                """,
                (
                    raw_weight,
                    raw_item_id,
                    store_id
                )
            )

            new_target_qty = (
                old_target_qty
                + roasted_weight
            )

            old_target_value = (
                old_target_qty
                * old_target_cost
            )

            new_target_value = (
                old_target_value
                + total_raw_cost
            )

            if new_target_qty > 0:

                final_avg_cost = (
                    new_target_value
                    / new_target_qty
                )

            else:

                final_avg_cost = (
                    roasted_unit_cost
                )

            conn.execute(
                """
                UPDATE items
                SET
                    quantity = ?,
                    avg_cost = ?,
                    buy_price = ?,
                    sale_price = ?
                WHERE id = ?
                  AND branch_id = ?
                """,
                (
                    new_target_qty,
                    final_avg_cost,
                    roasted_unit_cost,
                    sale_price,
                    target_item_id,
                    store_id
                )
            )

        production_notes = (
            f"الخام: {raw_item['item_name']} [{raw_item['item_code']}]\n"
            f"الصنف الناتج: {target['item_name']}\n"
            f"الوزن الخام: {raw_weight:,.2f} كجم\n"
            f"الوزن الناتج: {roasted_weight:,.2f} كجم\n"
            f"الفقد: {loss_weight:,.2f} كجم ({loss_percent:,.2f}%)\n"
            f"إجمالي تكلفة الخام: {total_raw_cost:,.2f} د.ل\n"
            f"تكلفة كيلو الناتج: {roasted_unit_cost:,.2f} د.ل\n"
            f"سعر البيع: {sale_price:,.2f} د.ل\n"
            f"بواسطة: {username or 'غير محدد'}"
        )

        conn.execute(
            """
            INSERT INTO production_logs
            (
                branch_id,
                production_type,
                source_item_id,
                source_item_name,
                target_item_id,
                target_item_name,
                input_quantity,
                output_quantity,
                loss_quantity,
                total_cost,
                unit_cost,
                sale_price,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                store_id,
                "تحميص",
                raw_item_id,
                raw_item["item_name"],
                target_item_id,
                target["item_name"],
                raw_weight,
                roasted_weight,
                loss_weight,
                total_raw_cost,
                roasted_unit_cost,
                sale_price,
                production_notes
            )
        )

        conn.commit()

        # تجهيز شاشة التحميص لعملية جديدة بعد نجاح الحفظ.
        # نحذف قيم الحقول فقط بعد نجاح المعاملة، لذلك لا تضيع المدخلات عند الخطأ.
        for _key in (
            "roast_raw_weight",
            "roast_finished_weight",
            "roast_raw_item",
            "roast_target_item",
        ):
            st.session_state.pop(_key, None)
        # سعر البيع مفتاحه ديناميكي حسب الصنف الناتج.
        for _key in list(st.session_state.keys()):
            if str(_key).startswith("roast_sale_"):
                st.session_state.pop(_key, None)

        profit_per_kg = (
            sale_price
            - roasted_unit_cost
        )

        profit_margin_sale = (
            (
                profit_per_kg
                / sale_price
            )
            * 100
            if sale_price > 0
            else 0.0
        )

        _production_done(
            "تمت عملية التحميص بنجاح. "
            f"الخام: {raw_weight:,.2f} كجم — الناتج: {roasted_weight:,.2f} كجم — "
            f"الفقد: {loss_weight:,.2f} كجم ({loss_percent:,.2f}%) — "
            f"إجمالي تكلفة الخام: {total_raw_cost:,.2f} د.ل — "
            f"تكلفة كيلو المنتج: {roasted_unit_cost:,.2f} د.ل — "
            f"ربح الكيلو المتوقع: {profit_per_kg:,.2f} د.ل "
            f"({profit_margin_sale:,.2f}% من سعر البيع)"
        )

    except ValueError as e:

        if conn:
            conn.rollback()

        st.warning(
            f"⚠️ {e}"
        )

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تنفيذ عملية التحميص."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# الصفحة
# ============================================================

@st.dialog("✅ تمت العملية بنجاح")
def _production_success_dialog():
    st.success(st.session_state.get("production_success_message", "تمت العملية بنجاح."))
    if st.button("موافق", type="primary", use_container_width=True, key="production_success_ok"):
        for _key in ['mix_list_state', 'roast_raw_weight', 'roast_finished_weight', 'roast_raw_item', 'roast_target_item']:
            st.session_state.pop(_key, None)
        for _key in list(st.session_state.keys()):
            if str(_key).startswith("roast_sale_"):
                st.session_state.pop(_key, None)
        st.session_state.pop("production_success_pending", None)
        st.session_state.pop("production_success_message", None)
        st.rerun()


def _production_done(message):
    st.session_state["production_success_message"] = message
    st.session_state["production_success_pending"] = True
    st.rerun()



@st.dialog("⚠️ مراجعة العملية قبل التنفيذ")
def _production_confirm_dialog():
    pending = st.session_state.get("production_pending_action")
    if not pending:
        return
    st.warning("راجع البيانات جيدًا. لن يتم تنفيذ أي تغيير قبل التأكيد.")
    for label, value in pending.get("summary", []):
        st.write(f"**{label}:** {value}")
    c1, c2 = st.columns(2)
    if c1.button("✅ تأكيد التنفيذ", type="primary", use_container_width=True, key="production_confirm_yes"):
        callback = pending.get("callback")
        args = pending.get("args", [])
        kwargs = pending.get("kwargs", {})
        st.session_state.pop("production_pending_action", None)
        callback(*args, **kwargs)
    if c2.button("❌ إلغاء", use_container_width=True, key="production_confirm_no"):
        st.session_state.pop("production_pending_action", None)
        st.rerun()


def show_page():
    back_button(key="back_roasting_blending")
    item_alerts(st.session_state.get("branch_id"), key="alerts_roasting_blending")

    if st.session_state.get("production_pending_action"):
        _production_confirm_dialog()
        st.stop()

    if st.session_state.get("production_success_pending"):
        _production_success_dialog()


    st.markdown(
        """
        <style>

        .stDataFrame,
        .stDataFrame *,
        div[data-testid="stTable"] *,
        th,
        td {
            color: #000000 !important;
            font-weight: 800 !important;
            text-align: right !important;
        }

        th {
            background-color:
                #e2e8f0 !important;
        }

        </style>
        """,
        unsafe_allow_html=True
    )

    st.header(
        "🥜 التحميص والخلط "
        "وحساب التكلفة"
    )

    st.info(
        "💡 العمليات تتم داخل المخزن "
        "الرئيسي، ويتم حساب تكلفة المنتج "
        "الناتج بناءً على التكلفة الفعلية "
        "للخامات."
    )

    username = st.session_state.get(
        "username",
        "غير محدد"
    )

    # ========================================================
    # تحميل البيانات
    # ========================================================

    try:

        main_store, store_items = (
            get_main_store_data()
        )

    except Exception as e:

        st.error(
            "❌ تعذر تحميل بيانات المخزن."
        )

        st.code(str(e))

        return

    if not main_store:

        st.error(
            "❌ لا يوجد مخزن رئيسي "
            "معرف في النظام."
        )

        return

    main_store_id = (
        main_store["id"]
    )

    st.caption(
        f"🏢 المخزن المستخدم: "
        f"{main_store['branch_name']}"
    )

    if not store_items:

        st.warning(
            "⚠️ لا توجد أصناف "
            "في المخزن الرئيسي."
        )

        return

    if "production_screen_mode" not in st.session_state:
        st.session_state["production_screen_mode"] = "mix"

    if not st.session_state.get("production_entry_lock"):
        nav1, nav2, nav3 = st.columns(3)
    
        if nav1.button(
            "🧪 خلط",
            use_container_width=True,
            type="primary" if st.session_state["production_screen_mode"] == "mix" else "secondary"
        ):
            st.session_state["production_screen_mode"] = "mix"
            st.rerun()
    
        if nav2.button(
            "🔥 تحميص",
            use_container_width=True,
            type="primary" if st.session_state["production_screen_mode"] == "roast" else "secondary"
        ):
            st.session_state["production_screen_mode"] = "roast"
            st.rerun()
    
        if nav3.button(
            "📋 سجل الإنتاج",
            use_container_width=True,
            type="primary" if st.session_state["production_screen_mode"] == "log" else "secondary"
        ):
            st.session_state["production_screen_mode"] = "log"
            st.rerun()
    
    if st.session_state["production_screen_mode"] == "log":
        st.markdown("### 📋 سجل وتقارير عمليات التحميص والخلط")

        conn_log = get_db_connection()
        try:
            type_filter, date_from_col, date_to_col = st.columns(3)
            selected_type = type_filter.selectbox(
                "نوع العملية:",
                ["الكل", "خلط", "تحميص"],
                key="production_log_type"
            )
            today = date.today()
            from_date = date_from_col.date_input(
                "من تاريخ:",
                value=today - timedelta(days=30),
                key="production_log_from"
            )
            to_date = date_to_col.date_input(
                "إلى تاريخ:",
                value=today,
                key="production_log_to"
            )

            if from_date > to_date:
                st.error("⚠️ تاريخ البداية يجب أن يكون قبل أو مساوياً لتاريخ النهاية.")
                return

            where = ["DATE(created_at) BETWEEN ? AND ?"]
            params = [from_date.isoformat(), to_date.isoformat()]
            if selected_type != "الكل":
                where.append("production_type = ?")
                params.append(selected_type)

            rows_log = conn_log.execute(
                f"""
                SELECT
                    id,
                    production_type,
                    source_item_name,
                    target_item_name,
                    COALESCE(input_quantity, 0) AS input_quantity,
                    COALESCE(output_quantity, 0) AS output_quantity,
                    COALESCE(loss_quantity, 0) AS loss_quantity,
                    COALESCE(total_cost, 0) AS total_cost,
                    COALESCE(unit_cost, 0) AS unit_cost,
                    COALESCE(sale_price, 0) AS sale_price,
                    notes,
                    created_at
                FROM production_logs
                WHERE {' AND '.join(where)}
                ORDER BY datetime(created_at) DESC, id DESC
                LIMIT 2000
                """,
                tuple(params)
            ).fetchall()

            if rows_log:
                report_rows = []
                for r in rows_log:
                    report_rows.append({
                        "رقم العملية": r["id"],
                        "نوع العملية": r["production_type"],
                        "الخامة / المصدر": r["source_item_name"],
                        "الصنف الناتج": r["target_item_name"],
                        "كمية الإدخال": float(r["input_quantity"] or 0),
                        "كمية الناتج": float(r["output_quantity"] or 0),
                        "الفقد": float(r["loss_quantity"] or 0),
                        "إجمالي التكلفة": float(r["total_cost"] or 0),
                        "تكلفة الوحدة": float(r["unit_cost"] or 0),
                        "سعر البيع": float(r["sale_price"] or 0),
                        "التاريخ والوقت": r["created_at"],
                        "التفاصيل": r["notes"] or "",
                    })

                df_log = pd.DataFrame(report_rows)

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("عدد العمليات", f"{len(df_log):,}")
                m2.metric("إجمالي الإدخال", f"{df_log['كمية الإدخال'].sum():,.2f}")
                m3.metric("إجمالي الناتج", f"{df_log['كمية الناتج'].sum():,.2f}")
                m4.metric("إجمالي الفقد", f"{df_log['الفقد'].sum():,.2f}")

                st.dataframe(
                    df_log.drop(columns=["التفاصيل"]),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "كمية الإدخال": st.column_config.NumberColumn("كمية الإدخال", format="%.2f"),
                        "كمية الناتج": st.column_config.NumberColumn("كمية الناتج", format="%.2f"),
                        "الفقد": st.column_config.NumberColumn("الفقد", format="%.2f"),
                        "إجمالي التكلفة": st.column_config.NumberColumn("إجمالي التكلفة", format="%.2f د.ل"),
                        "تكلفة الوحدة": st.column_config.NumberColumn("تكلفة الوحدة", format="%.2f د.ل"),
                        "سعر البيع": st.column_config.NumberColumn("سعر البيع", format="%.2f د.ل"),
                    }
                )

                st.markdown("#### 🔎 استخراج عملية واحدة")
                operation_options = {}
                for _, row in df_log.iterrows():
                    label = (
                        f"#{int(row['رقم العملية'])} | {row['نوع العملية']} | "
                        f"{row['الصنف الناتج']} | {row['التاريخ والوقت']}"
                    )
                    operation_options[label] = row

                selected_operation = st.selectbox(
                    "اختر العملية:",
                    ["-- اختر عملية --"] + list(operation_options.keys()),
                    key="production_single_operation"
                )
                if selected_operation != "-- اختر عملية --":
                    op = operation_options[selected_operation]
                    d1, d2, d3 = st.columns(3)
                    d1.metric("كمية الإدخال", f"{op['كمية الإدخال']:,.2f}")
                    d2.metric("كمية الناتج", f"{op['كمية الناتج']:,.2f}")
                    d3.metric("الفقد", f"{op['الفقد']:,.2f}")
                    st.write(f"**رقم العملية:** {int(op['رقم العملية'])}")
                    st.write(f"**النوع:** {op['نوع العملية']}")
                    st.write(f"**التاريخ والوقت:** {op['التاريخ والوقت']}")
                    st.write(f"**الخامة / المصدر:** {op['الخامة / المصدر']}")
                    st.write(f"**الصنف الناتج:** {op['الصنف الناتج']}")
                    st.text_area(
                        "تفاصيل العملية:",
                        value=str(op["التفاصيل"] or ""),
                        height=180,
                        disabled=True,
                        key=f"production_details_{int(op['رقم العملية'])}"
                    )

                import io
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df_log.to_excel(writer, index=False, sheet_name="Production_Log")

                st.download_button(
                    "📥 تصدير التقرير المحدد إلى Excel",
                    output.getvalue(),
                    f"production_log_{from_date}_to_{to_date}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            else:
                st.info("لا توجد عمليات إنتاج مطابقة للفترة ونوع العملية المحددين.")
        except Exception as e:
            st.error("❌ تعذر تحميل سجل الإنتاج.")
            st.code(str(e))
        finally:
            conn_log.close()
        return

    # ========================================================
    # الخلط
    # ========================================================

    if st.session_state["production_screen_mode"] == "mix":

        st.markdown(
            "### 🥜 تكوين خلطة جديدة"
        )

        st.caption(
            "اختر الخامات وأوزانها، "
            "ثم اختر الصنف النهائي الذي "
            "سيستقبل الكمية الناتجة."
        )

        item_choices = {}

        for item in store_items:

            cost = float(
                item["avg_cost"] or 0
            )

            if cost <= 0:
                cost = float(
                    item["buy_price"] or 0
                )

            label = (
                f"[{item['item_code']}] "
                f"{item['item_name']} "
                f"| المتاح: "
                f"{float(item['quantity'] or 0):,.2f} كجم "
                f"| التكلفة: "
                f"{cost:,.2f} د.ل"
            )

            item_choices[label] = item

        if (
            "mix_list_state"
            not in st.session_state
        ):

            st.session_state[
                "mix_list_state"
            ] = []

        # ====================================================
        # إضافة خام
        # ====================================================

        with st.form(
            "mix_form",
            clear_on_submit=True
        ):

            selected_label = (
                st.selectbox(
                    "اختر الخام:",
                    list(
                        item_choices.keys()
                    )
                )
            )

            mix_qty = st.number_input(
                "الوزن المستخدم (كجم):",
                min_value=0.01,
                value=1.0,
                step=0.1,
                format="%.2f"
            )

            add_mix_btn = (
                st.form_submit_button(
                    "➕ إضافة الخام "
                    "لقائمة الخلط"
                )
            )

        if add_mix_btn:

            selected_item = (
                item_choices[
                    selected_label
                ]
            )

            available = float(
                selected_item[
                    "quantity"
                ] or 0
            )

            if mix_qty > available:

                st.warning(
                    f"⚠️ المتاح من الصنف "
                    f"{available:,.2f} كجم فقط."
                )

            else:

                cost = float(
                    selected_item[
                        "avg_cost"
                    ] or 0
                )

                if cost <= 0:

                    cost = float(
                        selected_item[
                            "buy_price"
                        ] or 0
                    )

                # لو الخام موجود بالقائمة
                # نزود وزنه بدل تكرار السطر
                existing = None

                for material in (
                    st.session_state[
                        "mix_list_state"
                    ]
                ):

                    if (
                        material["id"]
                        == selected_item["id"]
                    ):

                        existing = material
                        break

                if existing:

                    new_qty = (
                        float(
                            existing["qty"]
                        )
                        + float(
                            mix_qty
                        )
                    )

                    if new_qty > available:

                        st.warning(
                            "⚠️ إجمالي الوزن "
                            "المضاف من هذا الخام "
                            "أكبر من المتاح."
                        )

                    else:

                        existing[
                            "qty"
                        ] = new_qty

                        existing[
                            "cost"
                        ] = cost

                        st.rerun()

                else:

                    st.session_state[
                        "mix_list_state"
                    ].append(
                        {
                            "id":
                                selected_item[
                                    "id"
                                ],

                            "code":
                                selected_item[
                                    "item_code"
                                ],

                            "name":
                                selected_item[
                                    "item_name"
                                ],

                            "qty":
                                float(
                                    mix_qty
                                ),

                            "cost":
                                cost
                        }
                    )

                    st.rerun()

        # ====================================================
        # عرض الخلطة
        # ====================================================

        if st.session_state[
            "mix_list_state"
        ]:

            st.markdown(
                "#### 📋 خامات "
                "الخلطة الحالية"
            )

            mix_rows = []

            for index, material in enumerate(
                st.session_state[
                    "mix_list_state"
                ]
            ):

                total_cost = (
                    float(material["qty"])
                    * float(material["cost"])
                )

                mix_rows.append(
                    {
                        "كود الصنف":
                            material["code"],

                        "اسم الخام":
                            material["name"],

                        "الوزن (كجم)":
                            material["qty"],

                        "تكلفة الكيلو":
                            material["cost"],

                        "إجمالي التكلفة":
                            total_cost
                    }
                )

            df_mix = pd.DataFrame(
                mix_rows
            )

            st.dataframe(
                df_mix,
                use_container_width=True,
                hide_index=True
            )

            # ================================================
            # حذف خام
            # ================================================

            remove_options = {
                (
                    f"{index + 1} - "
                    f"{material['name']} "
                    f"({material['qty']} كجم)"
                ): index

                for index, material in enumerate(
                    st.session_state[
                        "mix_list_state"
                    ]
                )
            }

            c_remove1, c_remove2 = (
                st.columns([3, 1])
            )

            remove_selected = (
                c_remove1.selectbox(
                    "حذف خام من الخلطة:",
                    list(
                        remove_options.keys()
                    ),
                    key="remove_mix_item"
                )
            )

            if c_remove2.button(
                "🗑️ حذف الخام",
                use_container_width=True
            ):

                del st.session_state[
                    "mix_list_state"
                ][
                    remove_options[
                        remove_selected
                    ]
                ]

                st.rerun()

            # ================================================
            # حساب الخلطة
            # ================================================

            total_mix_weight = sum(
                float(m["qty"])
                for m in st.session_state[
                    "mix_list_state"
                ]
            )

            total_mix_cost = sum(
                (
                    float(m["qty"])
                    * float(m["cost"])
                )
                for m in st.session_state[
                    "mix_list_state"
                ]
            )

            mix_unit_cost = (
                total_mix_cost
                / total_mix_weight
                if total_mix_weight > 0
                else 0.0
            )

            c_mix1, c_mix2, c_mix3 = (
                st.columns(3)
            )

            c_mix1.metric(
                "⚖️ وزن الخلطة",
                f"{total_mix_weight:,.2f} كجم"
            )

            c_mix2.metric(
                "💰 تكلفة الخامات",
                f"{total_mix_cost:,.2f} د.ل"
            )

            c_mix3.metric(
                "📊 تكلفة الكيلو",
                f"{mix_unit_cost:,.2f} د.ل"
            )

            st.markdown("---")

            # ================================================
            # الصنف الناتج
            # ================================================

            target_options = {
                (
                    f"[{item['item_code']}] "
                    f"{item['item_name']}"
                ): item

                for item in store_items
            }

            target_label = st.selectbox(
                "🎯 اختر الصنف الناتج "
                "بعد الخلط:",
                list(
                    target_options.keys()
                ),
                key="mix_target_item"
            )

            target_item = (
                target_options[
                    target_label
                ]
            )

            mix_sale_price = (
                st.number_input(
                    "سعر بيع الكيلو "
                    "للصنف الناتج:",
                    min_value=0.0,
                    value=float(
                        target_item[
                            "sale_price"
                        ] or 0
                    ),
                    step=0.5,
                    format="%.2f",
                    key=(
                        f"mix_sale_price_"
                        f"{target_item['id']}"
                    )
                )
            )

            expected_profit = (
                float(mix_sale_price)
                - mix_unit_cost
            )

            expected_margin = (
                (
                    expected_profit
                    / float(
                        mix_sale_price
                    )
                )
                * 100
                if mix_sale_price > 0
                else 0.0
            )

            st.info(
                f"📈 الربح المتوقع للكيلو: "
                f"**{expected_profit:,.2f} د.ل** "
                f"({expected_margin:,.2f}% "
                f"من سعر البيع)"
            )

            c_confirm, c_clear = (
                st.columns(2)
            )

            if c_confirm.button(
                "⚙️ اعتماد الخلطة "
                "وتحديث المخزون",
                type="primary",
                use_container_width=True
            ):

                st.session_state["production_pending_action"] = {
                    "callback": execute_mix,
                    "kwargs": {
                        "store_id": main_store_id,
                        "mix_list": list(st.session_state["mix_list_state"]),
                        "target_item_id": target_item["id"],
                        "new_sale_price": mix_sale_price,
                        "username": username,
                    },
                    "summary": [
                        ("العملية", "خلط"),
                        ("عدد الخامات", str(len(st.session_state["mix_list_state"]))),
                        ("إجمالي الوزن", f"{total_mix_weight:,.2f} كجم"),
                        ("الصنف الناتج", target_item["item_name"]),
                        ("سعر البيع", f"{float(mix_sale_price):,.2f} د.ل"),
                    ],
                }
                st.rerun()

            if c_clear.button(
                "🗑️ تفريغ الخلطة",
                use_container_width=True
            ):

                st.session_state[
                    "mix_list_state"
                ] = []

                st.rerun()

        else:

            st.info(
                "أضف الخامات المطلوبة "
                "لبدء تكوين الخلطة."
            )

    # ========================================================
    # التحميص
    # ========================================================

    if st.session_state["production_screen_mode"] == "roast":

        st.markdown(
            "### 🔥 عملية تحميص جديدة"
        )

        st.caption(
            "اختر الخام ثم اختر الصنف "
            "الناتج بعد التحميص. "
            "يمكن أن يكون نفس الصنف، "
            "لكن الأفضل فصل الخام عن "
            "المحمص إذا كانا يباعان "
            "كصنفين مختلفين."
        )

        raw_options = {}

        for item in store_items:

            cost = float(
                item["avg_cost"] or 0
            )

            if cost <= 0:

                cost = float(
                    item["buy_price"] or 0
                )

            label = (
                f"[{item['item_code']}] "
                f"{item['item_name']} "
                f"| المتاح: "
                f"{float(item['quantity'] or 0):,.2f} كجم "
                f"| التكلفة: "
                f"{cost:,.2f} د.ل"
            )

            raw_options[label] = item

        selected_raw_label = (
            st.selectbox(
                "اختر الخام المراد تحميصه:",
                list(
                    raw_options.keys()
                ),
                key="roast_raw_item"
            )
        )

        raw_item = raw_options[
            selected_raw_label
        ]

        target_options = {
            (
                f"[{item['item_code']}] "
                f"{item['item_name']}"
            ): item

            for item in store_items
        }

        selected_target_label = (
            st.selectbox(
                "🎯 اختر الصنف الناتج "
                "بعد التحميص:",
                list(
                    target_options.keys()
                ),
                key="roast_target_item"
            )
        )

        target_item = target_options[
            selected_target_label
        ]

        c_r1, c_r2 = st.columns(2)

        raw_weight = c_r1.number_input(
            "الوزن الخام قبل التحميص (كجم):",
            min_value=0.0,
            value=0.0,
            step=0.1,
            format="%.2f",
            key="roast_raw_weight"
        )

        roasted_weight = c_r2.number_input(
            "الوزن بعد التحميص (كجم):",
            min_value=0.0,
            value=0.0,
            step=0.1,
            format="%.2f",
            key="roast_finished_weight"
        )

        raw_cost = float(
            raw_item["avg_cost"] or 0
        )

        if raw_cost <= 0:

            raw_cost = float(
                raw_item["buy_price"] or 0
            )

        total_raw_cost = (
            float(raw_weight)
            * raw_cost
        )

        if (
            raw_weight > 0
            and roasted_weight > 0
            and roasted_weight <= raw_weight
        ):

            roasted_cost = (
                total_raw_cost
                / float(
                    roasted_weight
                )
            )

            weight_loss = (
                float(raw_weight)
                - float(roasted_weight)
            )

            weight_loss_pct = (
                weight_loss
                / float(raw_weight)
                * 100
            )

        else:

            roasted_cost = 0.0
            weight_loss = 0.0
            weight_loss_pct = 0.0

        c_info1, c_info2, c_info3 = (
            st.columns(3)
        )

        c_info1.metric(
            "💰 تكلفة الخام",
            f"{total_raw_cost:,.2f} د.ل"
        )

        c_info2.metric(
            "📉 الفقد الوزني",
            (
                f"{weight_loss:,.2f} كجم "
                f"({weight_loss_pct:,.2f}%)"
            )
        )

        c_info3.metric(
            "📊 تكلفة كيلو المحمص",
            f"{roasted_cost:,.2f} د.ل"
        )

        roast_sale_price = (
            st.number_input(
                "سعر بيع كيلو "
                "الصنف المحمص:",
                min_value=0.0,
                value=float(
                    target_item[
                        "sale_price"
                    ] or 0
                ),
                step=0.5,
                format="%.2f",
                key=(
                    f"roast_sale_"
                    f"{target_item['id']}"
                )
            )
        )

        profit_per_kg = (
            float(roast_sale_price)
            - roasted_cost
        )

        profit_pct = (
            (
                profit_per_kg
                / float(
                    roast_sale_price
                )
            )
            * 100
            if roast_sale_price > 0
            else 0.0
        )

        if (
            raw_weight > 0
            and roasted_weight > 0
        ):

            st.info(
                f"📈 ربح الكيلو المتوقع: "
                f"**{profit_per_kg:,.2f} د.ل** "
                f"({profit_pct:,.2f}% "
                f"من سعر البيع)"
            )

        if st.button(
            "🔥 اعتماد التحميص "
            "وتحديث المخزون",
            type="primary",
            use_container_width=True
        ):

            st.session_state["production_pending_action"] = {
                "callback": execute_roasting,
                "kwargs": {
                    "store_id": main_store_id,
                    "raw_item_id": raw_item["id"],
                    "target_item_id": target_item["id"],
                    "raw_weight": raw_weight,
                    "roasted_weight": roasted_weight,
                    "sale_price": roast_sale_price,
                    "username": username,
                },
                "summary": [
                    ("العملية", "تحميص"),
                    ("الخامة", raw_item["item_name"]),
                    ("الوزن الخام", f"{float(raw_weight):,.2f} كجم"),
                    ("الناتج", target_item["item_name"]),
                    ("الوزن بعد التحميص", f"{float(roasted_weight):,.2f} كجم"),
                    ("الفاقد", f"{max(float(raw_weight)-float(roasted_weight),0):,.2f} كجم"),
                    ("سعر البيع", f"{float(roast_sale_price):,.2f} د.ل"),
                ],
            }
            st.rerun()
