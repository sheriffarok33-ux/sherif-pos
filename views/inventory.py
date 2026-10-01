import streamlit as st
import pandas as pd
from database import get_db_connection


# ============================================================
# تحميل الفروع
# ============================================================

def get_branches():
    conn = None
    try:
        conn = get_db_connection()
        return conn.execute(
            """
            SELECT id, branch_name
            FROM branches
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        if conn:
            conn.close()


# ============================================================
# تحميل أصناف الفرع للاختيار
# ============================================================

def get_branch_items_rows(branch_id):
    conn = None
    try:
        conn = get_db_connection()
        return conn.execute(
            """
            SELECT
                id,
                item_code,
                item_name,
                quantity,
                buy_price,
                avg_cost,
                sale_price
            FROM items
            WHERE branch_id = ?
            ORDER BY item_name ASC, item_code ASC
            """,
            (branch_id,)
        ).fetchall()
    finally:
        if conn:
            conn.close()


# ============================================================
# جدول أصناف الفرع
# ============================================================

def get_branch_items(branch_id):
    rows = get_branch_items_rows(branch_id)
    data = []

    for row in rows:
        data.append(
            {
                "الكود": row["item_code"],
                "اسم الصنف": row["item_name"],
                "الرصيد": float(row["quantity"] or 0),
                "آخر تكلفة للوحدة": float(row["buy_price"] or 0),
                "متوسط تكلفة الوحدة": float(row["avg_cost"] or 0),
                "سعر بيع الوحدة": float(row["sale_price"] or 0),
            }
        )

    return pd.DataFrame(data)


# ============================================================
# إضافة كمية لصنف موجود
# ============================================================

def add_stock_to_existing_item(
    branch_id,
    item_id,
    added_quantity,
    unit_buy_price,
    unit_label,
):
    conn = None

    try:
        added_quantity = float(added_quantity)
        unit_buy_price = float(unit_buy_price)

        if added_quantity <= 0:
            raise ValueError(
                "الكمية المضافة يجب أن تكون أكبر من صفر."
            )

        if unit_buy_price < 0:
            raise ValueError(
                "سعر الشراء لا يمكن أن يكون سالباً."
            )

        conn = get_db_connection()

        existing = conn.execute(
            """
            SELECT
                id,
                item_code,
                item_name,
                quantity,
                buy_price,
                avg_cost,
                sale_price
            FROM items
            WHERE id = ?
              AND branch_id = ?
            FOR UPDATE
            """,
            (item_id, branch_id)
        ).fetchone()

        if not existing:
            raise ValueError(
                "الصنف المحدد غير موجود في هذا الفرع."
            )

        old_qty = float(existing["quantity"] or 0)
        old_avg_cost = float(existing["avg_cost"] or 0)
        old_buy_price = float(existing["buy_price"] or 0)

        if old_avg_cost <= 0:
            old_avg_cost = old_buy_price

        new_qty = old_qty + added_quantity

        if new_qty > 0:
            new_avg_cost = (
                (old_qty * old_avg_cost)
                + (added_quantity * unit_buy_price)
            ) / new_qty
        else:
            new_avg_cost = unit_buy_price

        conn.execute(
            """
            UPDATE items
            SET
                quantity = ?,
                buy_price = ?,
                avg_cost = ?
            WHERE id = ?
              AND branch_id = ?
            """,
            (
                new_qty,
                unit_buy_price,
                new_avg_cost,
                item_id,
                branch_id,
            )
        )

        conn.commit()

        st.success(
            f"✅ تمت إضافة {added_quantity:,.3f} {unit_label} "
            f"إلى ({existing['item_name']}). "
            f"الرصيد الجديد: {new_qty:,.3f} {unit_label}."
        )

        st.rerun()

    except Exception as e:
        if conn:
            conn.rollback()

        st.error("❌ تعذر إضافة الكمية للصنف.")
        st.code(str(e))

    finally:
        if conn:
            conn.close()


# ============================================================
# إنشاء صنف جديد فقط
# ============================================================

def create_new_inventory_item(
    branch_id,
    item_code,
    item_name,
    initial_quantity,
    unit_buy_price,
    sale_price,
    unit_label,
):
    conn = None

    try:
        item_code = item_code.strip()
        item_name = item_name.strip()

        if not item_code:
            raise ValueError(
                "يجب إدخال كود الصنف / الباركود."
            )

        if not item_name:
            raise ValueError(
                "يجب إدخال اسم الصنف."
            )

        initial_quantity = float(initial_quantity)
        unit_buy_price = float(unit_buy_price)
        sale_price = float(sale_price)

        if initial_quantity <= 0:
            raise ValueError(
                "الكمية الأولية يجب أن تكون أكبر من صفر."
            )

        if unit_buy_price < 0 or sale_price < 0:
            raise ValueError(
                "الأسعار لا يمكن أن تكون سالبة."
            )

        conn = get_db_connection()

        duplicate = conn.execute(
            """
            SELECT id, item_name
            FROM items
            WHERE branch_id = ?
              AND (
                    item_code = ?
                    OR LOWER(TRIM(item_name)) = LOWER(TRIM(?))
                  )
            LIMIT 1
            """,
            (
                branch_id,
                item_code,
                item_name,
            )
        ).fetchone()

        if duplicate:
            raise ValueError(
                "هذا الصنف موجود بالفعل في الفرع. "
                "استخدم خيار «إضافة كمية لصنف موجود» "
                "بدلاً من إنشاء صنف جديد."
            )

        conn.execute(
            """
            INSERT INTO items
            (
                item_code,
                item_name,
                branch_id,
                quantity,
                buy_price,
                sale_price,
                avg_cost
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_code,
                item_name,
                branch_id,
                initial_quantity,
                unit_buy_price,
                sale_price,
                unit_buy_price,
            )
        )

        conn.commit()

        st.success(
            f"✅ تم إنشاء الصنف ({item_name}) "
            f"برصيد أولي {initial_quantity:,.3f} "
            f"{unit_label}."
        )

        st.rerun()

    except Exception as e:
        if conn:
            conn.rollback()

        st.error("❌ تعذر إنشاء الصنف الجديد.")
        st.code(str(e))

    finally:
        if conn:
            conn.close()


# ============================================================
# حقول تحديد كمية وتكلفة الإضافة
# ============================================================

def stock_input_fields(prefix, existing_sale_price=None):
    inventory_mode = st.selectbox(
        "طريقة شراء / تخزين الكمية:",
        [
            "📦 كراتين وقطع",
            "⚖️ بالكيلو",
            "⚖️ بالجرام",
        ],
        key=f"{prefix}_inventory_mode",
    )

    added_quantity = 0.0
    unit_buy_price = 0.0
    unit_label = ""

    if inventory_mode == "📦 كراتين وقطع":
        c1, c2 = st.columns(2)

        pieces_per_carton = c1.number_input(
            "عدد القطع داخل الكرتون:",
            min_value=1,
            value=1,
            step=1,
            key=f"{prefix}_pieces_per_carton",
        )

        cartons_count = c2.number_input(
            "عدد الكراتين المضافة:",
            min_value=0.0,
            value=1.0,
            step=1.0,
            key=f"{prefix}_cartons_count",
        )

        box_buy_price = st.number_input(
            "سعر شراء الكرتون بالكامل (د.ل):",
            min_value=0.0,
            value=0.0,
            step=0.5,
            format="%.2f",
            key=f"{prefix}_box_buy_price",
        )

        added_quantity = (
            float(cartons_count)
            * int(pieces_per_carton)
        )

        unit_buy_price = (
            float(box_buy_price)
            / int(pieces_per_carton)
            if pieces_per_carton > 0
            else 0.0
        )

        unit_label = "قطعة"

        st.info(
            f"📊 سيتم إضافة **{added_quantity:,.0f} قطعة** "
            f"| تكلفة القطعة **{unit_buy_price:,.2f} د.ل**"
        )

    elif inventory_mode == "⚖️ بالكيلو":
        c1, c2 = st.columns(2)

        kg_quantity = c1.number_input(
            "الوزن المضاف (كجم):",
            min_value=0.001,
            value=1.000,
            step=0.100,
            format="%.3f",
            key=f"{prefix}_kg_quantity",
        )

        price_per_kg = c2.number_input(
            "سعر شراء الكيلو (د.ل):",
            min_value=0.0,
            value=0.0,
            step=0.5,
            format="%.2f",
            key=f"{prefix}_price_per_kg",
        )

        added_quantity = float(kg_quantity)
        unit_buy_price = float(price_per_kg)
        unit_label = "كجم"

        st.info(
            f"⚖️ سيتم إضافة **{added_quantity:,.3f} كجم** "
            f"| قيمة الشراء "
            f"**{added_quantity * unit_buy_price:,.2f} د.ل**"
        )

    else:
        c1, c2 = st.columns(2)

        grams_quantity = c1.number_input(
            "الوزن المضاف (جرام):",
            min_value=1.0,
            value=1000.0,
            step=50.0,
            format="%.0f",
            key=f"{prefix}_grams_quantity",
        )

        total_purchase_price = c2.number_input(
            "إجمالي سعر شراء هذه الكمية (د.ل):",
            min_value=0.0,
            value=0.0,
            step=0.5,
            format="%.2f",
            key=f"{prefix}_grams_total_price",
        )

        added_quantity = float(grams_quantity) / 1000.0

        unit_buy_price = (
            float(total_purchase_price) / added_quantity
            if added_quantity > 0
            else 0.0
        )

        unit_label = "كجم"

        st.info(
            f"⚖️ {grams_quantity:,.0f} جرام = "
            f"**{added_quantity:,.3f} كجم** "
            f"| تكلفة الكيلو "
            f"**{unit_buy_price:,.2f} د.ل**"
        )

    return (
        inventory_mode,
        added_quantity,
        unit_buy_price,
        unit_label,
    )


# ============================================================
# الصفحة
# ============================================================

def show_page():

    st.markdown(
        """
        <style>
        .rtl-container {
            direction: rtl !important;
            text-align: right !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <h2 class="rtl-container">
        📦 إدارة المخزن - الأصناف والكميات والباركود
        </h2>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        "اختر صنفاً موجوداً لإضافة رصيد جديد، "
        "أو أنشئ صنفاً جديداً لأول مرة."
    )

    st.markdown("---")

    try:
        branches = get_branches()
    except Exception as e:
        st.error("❌ تعذر تحميل الفروع.")
        st.code(str(e))
        return

    if not branches:
        st.warning(
            "⚠️ يرجى إنشاء مخزن أو فرع أولاً "
            "من إدارة الفروع."
        )
        return

    b_dict = {
        b["branch_name"]: b["id"]
        for b in branches
    }

    selected_branch = st.selectbox(
        "اختر المخزن أو الفرع الحالي:",
        list(b_dict.keys()),
    )

    target_branch_id = b_dict[selected_branch]

    try:
        existing_items = get_branch_items_rows(
            target_branch_id
        )
    except Exception as e:
        st.error("❌ تعذر تحميل أصناف الفرع.")
        st.code(str(e))
        existing_items = []

    operation = st.radio(
        "ماذا تريد أن تفعل؟",
        [
            "📦 إضافة كمية لصنف موجود",
            "➕ إنشاء صنف جديد",
        ],
        horizontal=True,
    )

    st.markdown("---")

    # ========================================================
    # إضافة كمية لصنف موجود
    # ========================================================
    if operation == "📦 إضافة كمية لصنف موجود":

        st.markdown(
            "### 📦 إضافة مخزون لصنف مسجل"
        )

        if not existing_items:
            st.info(
                "لا توجد أصناف في هذا الفرع حتى الآن. "
                "اختر «إنشاء صنف جديد» أولاً."
            )
        else:
            item_map = {}

            for item in existing_items:
                label = (
                    f"{item['item_name']} "
                    f"— {item['item_code']} "
                    f"— الرصيد: "
                    f"{float(item['quantity'] or 0):,.3f}"
                )
                item_map[label] = item

            selected_item_label = st.selectbox(
                "اختر الصنف:",
                list(item_map.keys()),
            )

            selected_item = item_map[
                selected_item_label
            ]

            c1, c2, c3 = st.columns(3)

            c1.metric(
                "الرصيد الحالي",
                f"{float(selected_item['quantity'] or 0):,.3f}",
            )

            c2.metric(
                "متوسط التكلفة",
                f"{float(selected_item['avg_cost'] or 0):,.2f} د.ل",
            )

            c3.metric(
                "سعر البيع الحالي",
                f"{float(selected_item['sale_price'] or 0):,.2f} د.ل",
            )

            st.caption(
                "اسم الصنف والباركود وسعر البيع الحالي "
                "لن يتغيروا من هذه العملية؛ "
                "سيتم فقط إضافة الرصيد وتحديث متوسط التكلفة."
            )

            with st.form(
                "add_existing_stock_form",
                clear_on_submit=True,
            ):
                (
                    _mode,
                    added_quantity,
                    unit_buy_price,
                    unit_label,
                ) = stock_input_fields(
                    "existing"
                )

                submitted_existing = (
                    st.form_submit_button(
                        "➕ إضافة الكمية للصنف",
                        type="primary",
                        use_container_width=True,
                    )
                )

            if submitted_existing:
                add_stock_to_existing_item(
                    target_branch_id,
                    selected_item["id"],
                    added_quantity,
                    unit_buy_price,
                    unit_label,
                )

    # ========================================================
    # إنشاء صنف جديد
    # ========================================================
    else:

        st.markdown(
            "### ➕ إنشاء صنف جديد لأول مرة"
        )

        with st.form(
            "create_new_item_form",
            clear_on_submit=True,
        ):
            c1, c2 = st.columns(2)

            item_code = c1.text_input(
                "كود الصنف / الباركود:"
            )

            item_name = c2.text_input(
                "اسم الصنف:"
            )

            (
                inventory_mode,
                initial_quantity,
                unit_buy_price,
                unit_label,
            ) = stock_input_fields(
                "new"
            )

            sale_label = (
                "سعر بيع القطعة (د.ل):"
                if inventory_mode == "📦 كراتين وقطع"
                else "سعر بيع الكيلو (د.ل):"
            )

            sale_price = st.number_input(
                sale_label,
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f",
                key="new_sale_price",
            )

            submitted_new = (
                st.form_submit_button(
                    "💾 إنشاء الصنف وحفظ الرصيد",
                    type="primary",
                    use_container_width=True,
                )
            )

        if submitted_new:
            create_new_inventory_item(
                target_branch_id,
                item_code,
                item_name,
                initial_quantity,
                unit_buy_price,
                sale_price,
                unit_label,
            )

    # ========================================================
    # جدول الأصناف
    # ========================================================

    st.markdown("---")
    st.markdown(
        "### 📋 جدول الأصناف المسجلة في هذا المخزن"
    )

    st.caption(
        "الأصناف الموزونة تُحسب داخلياً بالكيلو: "
        "250 جرام = 0.250 كجم."
    )

    try:
        items_df = get_branch_items(
            target_branch_id
        )
    except Exception as e:
        st.error(
            "❌ تعذر تحميل أصناف المخزن."
        )
        st.code(str(e))
        items_df = pd.DataFrame()

    if not items_df.empty:
        st.dataframe(
            items_df,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "لا توجد أصناف مسجلة "
            "في هذا المخزن حتى الآن."
        )
