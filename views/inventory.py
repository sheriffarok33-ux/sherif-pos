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
# تحميل أصناف فرع
# ============================================================

def get_branch_items(branch_id):
    conn = None
    try:
        conn = get_db_connection()

        rows = conn.execute(
            """
            SELECT
                item_code,
                item_name,
                quantity,
                buy_price,
                avg_cost,
                sale_price
            FROM items
            WHERE branch_id = ?
            ORDER BY item_name ASC
            """,
            (branch_id,)
        ).fetchall()

        data = []

        for row in rows:
            data.append(
                {
                    "الكود": row["item_code"],
                    "اسم الصنف": row["item_name"],
                    "الرصيد": float(row["quantity"] or 0),
                    "آخر تكلفة للوحدة": float(
                        row["buy_price"] or 0
                    ),
                    "متوسط تكلفة الوحدة": float(
                        row["avg_cost"] or 0
                    ),
                    "سعر بيع الوحدة": float(
                        row["sale_price"] or 0
                    )
                }
            )

        return pd.DataFrame(data)

    finally:
        if conn:
            conn.close()


# ============================================================
# إضافة / تحديث صنف - بوحدة أساسية
# ============================================================

def save_inventory_item(
    branch_id,
    item_code,
    item_name,
    added_quantity,
    unit_buy_price,
    sale_price,
    unit_label
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

        added_quantity = float(added_quantity)
        unit_buy_price = float(unit_buy_price)
        sale_price = float(sale_price)

        if added_quantity <= 0:
            raise ValueError(
                "الكمية المضافة يجب أن تكون أكبر من صفر."
            )

        if unit_buy_price < 0 or sale_price < 0:
            raise ValueError(
                "الأسعار لا يمكن أن تكون سالبة."
            )

        conn = get_db_connection()

        existing = conn.execute(
            """
            SELECT
                id,
                item_name,
                quantity,
                buy_price,
                avg_cost
            FROM items
            WHERE item_code = ?
              AND branch_id = ?
            FOR UPDATE
            """,
            (item_code, branch_id)
        ).fetchone()

        if existing:
            old_qty = float(existing["quantity"] or 0)
            old_avg_cost = float(
                existing["avg_cost"] or 0
            )
            old_buy_price = float(
                existing["buy_price"] or 0
            )

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
                    item_name = ?,
                    quantity = ?,
                    buy_price = ?,
                    sale_price = ?,
                    avg_cost = ?
                WHERE id = ?
                  AND branch_id = ?
                """,
                (
                    item_name,
                    new_qty,
                    unit_buy_price,
                    sale_price,
                    new_avg_cost,
                    existing["id"],
                    branch_id
                )
            )

            conn.commit()

            st.success(
                f"✅ تم تحديث الصنف وإضافة "
                f"{added_quantity:,.3f} {unit_label}. "
                f"الرصيد الجديد: "
                f"{new_qty:,.3f} {unit_label}."
            )

        else:
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
                    added_quantity,
                    unit_buy_price,
                    sale_price,
                    unit_buy_price
                )
            )

            conn.commit()

            st.success(
                f"✅ تمت إضافة الصنف ({item_name}) "
                f"برصيد {added_quantity:,.3f} "
                f"{unit_label}."
            )

        st.rerun()

    except Exception as e:
        if conn:
            conn.rollback()

        st.error("❌ تعذر حفظ الصنف.")
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
        .rtl-container {
            direction: rtl !important;
            text-align: right !important;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <h2 class="rtl-container">
        📦 إدارة المخزن - الوحدات والباركود
        </h2>
        """,
        unsafe_allow_html=True
    )

    st.caption(
        "يدعم الكراتين والقطع والأصناف الموزونة "
        "بالكيلو والجرام."
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
        list(b_dict.keys())
    )

    target_branch_id = b_dict[selected_branch]

    st.markdown("### 🏷️ إضافة أو تحديث صنف")

    with st.form(
        "inventory_master_form",
        clear_on_submit=True
    ):

        c1, c2 = st.columns(2)

        item_code = c1.text_input(
            "كود الصنف / الباركود:"
        )

        item_name = c2.text_input(
            "اسم الصنف:"
        )

        inventory_mode = st.selectbox(
            "طريقة شراء وتخزين الصنف:",
            [
                "📦 كراتين وقطع",
                "⚖️ بالكيلو",
                "⚖️ بالجرام"
            ]
        )

        added_quantity = 0.0
        unit_buy_price = 0.0
        sale_price = 0.0
        unit_label = ""

        # ====================================================
        # كراتين / قطع
        # ====================================================
        if inventory_mode == "📦 كراتين وقطع":

            c3, c4 = st.columns(2)

            pieces_per_carton = c3.number_input(
                "عدد القطع داخل الكرتون:",
                min_value=1,
                value=1,
                step=1
            )

            cartons_count = c4.number_input(
                "عدد الكراتين المضافة:",
                min_value=0.0,
                value=1.0,
                step=1.0
            )

            c5, c6 = st.columns(2)

            box_buy_price = c5.number_input(
                "سعر شراء الكرتون بالكامل (د.ل):",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f"
            )

            sale_price = c6.number_input(
                "سعر بيع القطعة (د.ل):",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f"
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
                f"📊 سيتم إضافة "
                f"**{added_quantity:,.0f} قطعة** "
                f"| تكلفة القطعة "
                f"**{unit_buy_price:,.2f} د.ل**"
            )

        # ====================================================
        # كيلو
        # ====================================================
        elif inventory_mode == "⚖️ بالكيلو":

            c3, c4 = st.columns(2)

            kg_quantity = c3.number_input(
                "الوزن المضاف (كجم):",
                min_value=0.001,
                value=1.000,
                step=0.100,
                format="%.3f"
            )

            price_per_kg = c4.number_input(
                "سعر شراء الكيلو (د.ل):",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f"
            )

            sale_price = st.number_input(
                "سعر بيع الكيلو (د.ل):",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f"
            )

            added_quantity = float(kg_quantity)
            unit_buy_price = float(price_per_kg)
            unit_label = "كجم"

            purchase_total = (
                added_quantity * unit_buy_price
            )

            st.info(
                f"⚖️ سيتم إضافة "
                f"**{added_quantity:,.3f} كجم** "
                f"| قيمة الشراء "
                f"**{purchase_total:,.2f} د.ل** "
                f"| التكلفة "
                f"**{unit_buy_price:,.2f} د.ل/كجم**"
            )

        # ====================================================
        # جرام - التخزين الداخلي بالكيلو
        # ====================================================
        else:

            c3, c4 = st.columns(2)

            grams_quantity = c3.number_input(
                "الوزن المضاف (جرام):",
                min_value=1.0,
                value=1000.0,
                step=50.0,
                format="%.0f"
            )

            total_purchase_price = c4.number_input(
                "إجمالي سعر شراء هذه الكمية (د.ل):",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f"
            )

            sale_price = st.number_input(
                "سعر بيع الكيلو (د.ل):",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f"
            )

            # قاعدة موحدة: الأصناف الموزونة تخزن بالكيلو.
            added_quantity = (
                float(grams_quantity) / 1000.0
            )

            unit_buy_price = (
                float(total_purchase_price)
                / added_quantity
                if added_quantity > 0
                else 0.0
            )

            unit_label = "كجم"

            st.info(
                f"⚖️ {grams_quantity:,.0f} جرام = "
                f"**{added_quantity:,.3f} كجم** "
                f"| تكلفة الكيلو المحسوبة "
                f"**{unit_buy_price:,.2f} د.ل**"
            )

        submitted = st.form_submit_button(
            "💾 حفظ الصنف في المخزن",
            type="primary",
            use_container_width=True
        )

    if submitted:
        save_inventory_item(
            target_branch_id,
            item_code,
            item_name,
            added_quantity,
            unit_buy_price,
            sale_price,
            unit_label
        )

    st.markdown("---")
    st.markdown(
        "### 📋 جدول الأصناف المسجلة في هذا المخزن"
    )

    st.caption(
        "ملاحظة: الأصناف الموزونة تُخزن داخلياً بالكيلو، "
        "وبالتالي 250 جرام = 0.250 من الرصيد."
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
            hide_index=True
        )
    else:
        st.info(
            "لا توجد أصناف مسجلة "
            "في هذا المخزن حتى الآن."
        )
