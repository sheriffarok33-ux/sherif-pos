import streamlit as st
import pandas as pd
from database import get_db_connection


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

        st.session_state[
            "mix_list_state"
        ] = []

        st.success(
            "🎉 تم اعتماد الخلطة بنجاح.\n\n"
            f"⚖️ الوزن الناتج: "
            f"{total_mix_weight:,.2f} كجم\n\n"
            f"💰 تكلفة الخلطة: "
            f"{total_mix_cost:,.2f} د.ل\n\n"
            f"📊 تكلفة الكيلو المنتج: "
            f"{new_mix_cost:,.2f} د.ل\n\n"
            f"📦 متوسط تكلفة رصيد "
            f"الصنف الناتج بعد الدمج: "
            f"{final_avg_cost:,.2f} د.ل"
        )

        st.rerun()

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

        st.success(
            "🎉 تمت عملية التحميص بنجاح.\n\n"
            f"⚖️ الخام: "
            f"{raw_weight:,.2f} كجم\n\n"
            f"🔥 الناتج: "
            f"{roasted_weight:,.2f} كجم\n\n"
            f"📉 الفقد: "
            f"{loss_weight:,.2f} كجم "
            f"({loss_percent:,.2f}%)\n\n"
            f"💰 إجمالي تكلفة الخام: "
            f"{total_raw_cost:,.2f} د.ل\n\n"
            f"📊 تكلفة كيلو المنتج "
            f"بعد الفقد: "
            f"{roasted_unit_cost:,.2f} د.ل\n\n"
            f"📈 ربح الكيلو المتوقع: "
            f"{profit_per_kg:,.2f} د.ل "
            f"({profit_margin_sale:,.2f}% "
            f"من سعر البيع)"
        )

        st.rerun()

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

def show_page():

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

    (
        mix_tab,
        roast_tab
    ) = st.tabs(
        [
            "🥜 خلط المكسرات",
            "🔥 التحميص"
        ]
    )

    # ========================================================
    # الخلط
    # ========================================================

    with mix_tab:

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

                execute_mix(
                    store_id=main_store_id,
                    mix_list=st.session_state[
                        "mix_list_state"
                    ],
                    target_item_id=target_item[
                        "id"
                    ],
                    new_sale_price=(
                        mix_sale_price
                    ),
                    username=username
                )

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

    with roast_tab:

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

            execute_roasting(
                store_id=main_store_id,
                raw_item_id=raw_item["id"],
                target_item_id=target_item[
                    "id"
                ],
                raw_weight=raw_weight,
                roasted_weight=(
                    roasted_weight
                ),
                sale_price=(
                    roast_sale_price
                ),
                username=username
            )
