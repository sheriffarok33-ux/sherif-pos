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
                    "الكود":
                        row["item_code"],

                    "اسم الصنف":
                        row["item_name"],

                    "الكمية الإجمالية (قطع)":
                        float(
                            row["quantity"] or 0
                        ),

                    "آخر تكلفة شراء للقطعة":
                        float(
                            row["buy_price"] or 0
                        ),

                    "متوسط تكلفة القطعة":
                        float(
                            row["avg_cost"] or 0
                        ),

                    "سعر بيع القطعة":
                        float(
                            row["sale_price"] or 0
                        )
                }
            )

        return pd.DataFrame(data)

    finally:

        if conn:
            conn.close()


# ============================================================
# إضافة / تحديث صنف
# ============================================================

def save_inventory_item(
    branch_id,
    item_code,
    item_name,
    pieces_per_carton,
    cartons_count,
    box_buy_price,
    sale_price_piece
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

        if pieces_per_carton <= 0:

            raise ValueError(
                "عدد القطع داخل الكرتون "
                "يجب أن يكون أكبر من صفر."
            )

        if cartons_count <= 0:

            raise ValueError(
                "عدد الكراتين المضافة "
                "يجب أن يكون أكبر من صفر."
            )

        total_pieces = (
            float(cartons_count)
            * int(pieces_per_carton)
        )

        unit_buy_price = (
            float(box_buy_price)
            / int(pieces_per_carton)
        )

        conn = get_db_connection()

        # قفل الصنف أثناء التحديث لمنع
        # عمليتين من تعديل نفس الرصيد معاً
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
            (
                item_code,
                branch_id
            )
        ).fetchone()

        # ====================================================
        # الصنف موجود
        # ====================================================

        if existing:

            old_qty = float(
                existing["quantity"] or 0
            )

            old_avg_cost = float(
                existing["avg_cost"] or 0
            )

            old_buy_price = float(
                existing["buy_price"] or 0
            )

            # في حالة عدم وجود متوسط تكلفة قديم
            if old_avg_cost <= 0:

                old_avg_cost = (
                    old_buy_price
                )

            new_qty = (
                old_qty
                + total_pieces
            )

            # المتوسط الموزون
            if new_qty > 0:

                new_avg_cost = (
                    (
                        old_qty
                        * old_avg_cost
                    )
                    +
                    (
                        total_pieces
                        * unit_buy_price
                    )
                ) / new_qty

            else:

                new_avg_cost = (
                    unit_buy_price
                )

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
                    sale_price_piece,
                    new_avg_cost,
                    existing["id"],
                    branch_id
                )
            )

            conn.commit()

            st.success(
                f"✅ الصنف موجود مسبقاً. "
                f"تمت إضافة "
                f"{total_pieces:,.0f} قطعة، "
                f"وأصبح إجمالي الرصيد "
                f"{new_qty:,.0f} قطعة."
            )

        # ====================================================
        # صنف جديد
        # ====================================================

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
                    total_pieces,
                    unit_buy_price,
                    sale_price_piece,
                    unit_buy_price
                )
            )

            conn.commit()

            st.success(
                f"✅ تمت إضافة الصنف "
                f"({item_name}) بنجاح "
                f"بإجمالي "
                f"{total_pieces:,.0f} قطعة."
            )

        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر حفظ الصنف."
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
        📦 إدارة المخزن -
        نظام الكراتين والقطع والباركود
        </h2>
        """,
        unsafe_allow_html=True
    )

    st.markdown("---")

    # ========================================================
    # الفروع
    # ========================================================

    try:

        branches = get_branches()

    except Exception as e:

        st.error(
            "❌ تعذر تحميل الفروع."
        )

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

    target_branch_id = b_dict[
        selected_branch
    ]

    # ========================================================
    # إضافة / تحديث صنف
    # ========================================================

    st.markdown(
        "### 🏷️ إضافة أو تحديث صنف "
        "(الكراتين والقطع والباركود)"
    )

    with st.form(
        "inventory_master_form",
        clear_on_submit=True
    ):

        col1, col2 = st.columns(2)

        item_code = col1.text_input(
            "كود الصنف "
            "(الباركود - مرر القارئ هنا):"
        )

        item_name = col2.text_input(
            "اسم الصنف:"
        )

        col3, col4 = st.columns(2)

        pieces_per_carton = (
            col3.number_input(
                "كم قطعة داخل الكرتون الواحد؟",
                min_value=1,
                value=1,
                step=1
            )
        )

        cartons_count = (
            col4.number_input(
                "عدد الكراتين المضافة:",
                min_value=0.0,
                value=1.0,
                step=1.0
            )
        )

        col5, col6 = st.columns(2)

        box_buy_price = (
            col5.number_input(
                "سعر شراء الكرتون بالكامل "
                "(د.ل):",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f"
            )
        )

        sale_price_piece = (
            col6.number_input(
                "سعر بيع القطعة المفردة "
                "(د.ل):",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f"
            )
        )

        # ====================================================
        # الحسابات التوضيحية
        # ====================================================

        total_pieces = (
            cartons_count
            * pieces_per_carton
        )

        if pieces_per_carton > 0:

            unit_buy_price = (
                box_buy_price
                / pieces_per_carton
            )

        else:

            unit_buy_price = 0.0

        st.info(
            f"📊 ملخص الحسبة التلقائية: "
            f"إجمالي القطع = "
            f"**{total_pieces:,.0f} قطعة** "
            f"| تكلفة القطعة الواحدة = "
            f"**{unit_buy_price:,.2f} د.ل**"
        )

        submitted = (
            st.form_submit_button(
                "💾 حفظ الصنف في المخزن",
                type="primary",
                use_container_width=True
            )
        )

    if submitted:

        save_inventory_item(
            target_branch_id,
            item_code,
            item_name,
            pieces_per_carton,
            cartons_count,
            box_buy_price,
            sale_price_piece
        )

    # ========================================================
    # جدول الأصناف
    # ========================================================

    st.markdown("---")

    st.markdown(
        "### 📋 جدول الأصناف المسجلة "
        "في هذا المخزن"
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
