import streamlit as st
import pandas as pd
from database import get_db_connection


# ============================================================
# أدوات مساعدة
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


def get_branch_items(branch_id):
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
            ORDER BY item_name ASC
            """,
            (branch_id,)
        ).fetchall()

    finally:
        if conn:
            conn.close()


# ============================================================
# تسجيل تلف / مرتجع
# ============================================================

def execute_adjustment(
    branch_id,
    item_id,
    qty,
    adj_type,
    notes
):

    conn = None

    try:
        conn = get_db_connection()

        # قفل الصنف أثناء الحركة
        item = conn.execute(
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
            (item_id, branch_id)
        ).fetchone()

        if not item:
            raise ValueError(
                "الصنف غير موجود في الفرع المحدد."
            )

        current_qty = float(
            item["quantity"] or 0
        )

        avg_cost = float(
            item["avg_cost"] or 0
        )

        buy_price = float(
            item["buy_price"] or 0
        )

        unit_cost = (
            avg_cost
            if avg_cost > 0
            else buy_price
        )

        total_value = (
            float(qty) * unit_cost
        )

        # ----------------------------------------------------
        # مرتجع صالح / إعادة صنف مُصلح
        # ----------------------------------------------------

        if (
            "صالح للبيع" in adj_type
            or "إعادة صنف تالف/مُصلح" in adj_type
        ):

            conn.execute(
                """
                UPDATE items
                SET quantity = quantity + ?
                WHERE id = ?
                AND branch_id = ?
                """,
                (
                    qty,
                    item_id,
                    branch_id
                )
            )

            if "إعادة صنف تالف/مُصلح" in adj_type:

                db_type = (
                    "إعادة صنف مُصلح للخدمة"
                )

                # تخفيض قيمة الخسائر السابقة
                total_value = -total_value

            else:

                db_type = (
                    "مرتجع صالح للبيع"
                )

                # المرتجع الصالح ليس خسارة
                total_value = 0.0

        # ----------------------------------------------------
        # تلف / منتهي / مرتجع تالف
        # ----------------------------------------------------

        elif (
            "تلف" in adj_type
            or "منتهي" in adj_type
            or "مرتجع زبون - تالف" in adj_type
        ):

            if float(qty) > current_qty:

                raise ValueError(
                    f"الكمية المطلوبة ({qty}) "
                    f"أكبر من الرصيد المتاح "
                    f"({current_qty})."
                )

            conn.execute(
                """
                UPDATE items
                SET quantity = quantity - ?
                WHERE id = ?
                AND branch_id = ?
                """,
                (
                    qty,
                    item_id,
                    branch_id
                )
            )

            if "منتهي" in adj_type:

                db_type = (
                    "منتهي الصلاحية"
                )

            elif "مرتجع زبون - تالف" in adj_type:

                db_type = (
                    "مرتجع زبون - تالف"
                )

            else:

                db_type = (
                    "تالف / هالك"
                )

        else:

            raise ValueError(
                "نوع الحركة غير معروف."
            )

        # ----------------------------------------------------
        # تسجيل الحركة
        # ----------------------------------------------------

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
                branch_id,
                item_id,
                item["item_name"],
                qty,
                db_type,
                total_value,
                notes.strip()
            )
        )

        conn.commit()

        st.success(
            "✅ تم تسجيل الحركة وتحديث "
            "المخزون بنجاح."
        )

        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تنفيذ حركة المخزون."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# إضافة فائض
# ============================================================

def execute_surplus(
    branch_id,
    item_id,
    qty,
    notes
):

    conn = None

    try:
        conn = get_db_connection()

        item = conn.execute(
            """
            SELECT
                id,
                item_name,
                quantity
            FROM items
            WHERE id = ?
            AND branch_id = ?
            FOR UPDATE
            """,
            (
                item_id,
                branch_id
            )
        ).fetchone()

        if not item:

            raise ValueError(
                "الصنف غير موجود في الفرع المحدد."
            )

        if float(qty) <= 0:

            raise ValueError(
                "كمية الفائض يجب أن تكون "
                "أكبر من صفر."
            )

        conn.execute(
            """
            UPDATE items
            SET quantity = quantity + ?
            WHERE id = ?
            AND branch_id = ?
            """,
            (
                qty,
                item_id,
                branch_id
            )
        )

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
                branch_id,
                item_id,
                item["item_name"],
                qty,
                "فائض مخزني",
                0.0,
                notes.strip()
            )
        )

        conn.commit()

        st.success(
            f"✅ تمت إضافة الفائض "
            f"({qty}) للصنف بنجاح."
        )

        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر إضافة الفائض."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# تحديث السعر
# ============================================================

def execute_price_update(
    item_code,
    item_name,
    new_price
):

    conn = None

    try:
        conn = get_db_connection()

        if new_price < 0:

            raise ValueError(
                "السعر لا يمكن أن يكون سالباً."
            )

        # نعتمد على الكود أولاً لأنه الأدق
        if item_code:

            result = conn.execute(
                """
                UPDATE items
                SET sale_price = ?
                WHERE item_code = ?
                """,
                (
                    new_price,
                    item_code
                )
            )

        else:

            # احتياطياً للصنف بدون باركود
            result = conn.execute(
                """
                UPDATE items
                SET sale_price = ?
                WHERE item_name = ?
                """,
                (
                    new_price,
                    item_name
                )
            )

        if result.rowcount == 0:

            raise ValueError(
                "لم يتم العثور على الصنف."
            )

        conn.commit()

        st.success(
            f"✅ تم تحديث وتعميم السعر الجديد "
            f"({new_price:.2f} د.ل) بنجاح."
        )

        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تحديث سعر الصنف."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# الصفحة
# ============================================================

def show_page():

    # ========================================================
    # التنسيق
    # ========================================================

    st.markdown(
        """
        <style>
        .stDataFrame div,
        .stDataFrame span,
        .stDataFrame p,
        div[data-testid="stTable"] *,
        th, td,
        div[data-baseweb="select"] *,
        span, p, label, h3, h4 {
            color: #000000 !important;
            font-family: 'Tajawal', sans-serif !important;
            font-weight: 900 !important;
        }

        th {
            background-color: #94a3b8 !important;
            color: #000000 !important;
            font-size: 19px !important;
            text-align: right !important;
        }

        td {
            color: #000000 !important;
            font-size: 18px !important;
            background-color: #f8fafc !important;
            text-align: right !important;
        }

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
        ➕ الفائض، التوالف، والمرتجعات،
        وتعديل الأسعار
        </h2>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        "💡 إدارة التوالف، منتهيات الصلاحية، "
        "المرتجعات، تسجيل الفائض المخزني للفرع، "
        "وتعديل وتعميم الأسعار على كافة الفروع."
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
            "⚠️ لا توجد فروع مسجلة في النظام."
        )

        return

    b_dict = {
        b["branch_name"]: b["id"]
        for b in branches
    }

    tab1, tab2, tab3 = st.tabs([
        "🗑️ التوالف، منتهيات الصلاحية، والمرتجعات",
        "➕ إضافة فائض مخزني لفرع معين",
        "💲 تعديل وتعميم السعر على الفروع"
    ])

    # ========================================================
    # 1 - التوالف والمرتجعات
    # ========================================================

    with tab1:

        st.markdown(
            "### 🗑️ تسجيل وإدارة "
            "التوالف والمرتجعات"
        )

        sel_branch_name = st.selectbox(
            "اختر الفرع / المخزن:",
            list(b_dict.keys()),
            key="dam_branch_sel"
        )

        b_id = b_dict[
            sel_branch_name
        ]

        # ----------------------------------------------------
        # الإجماليات
        # ----------------------------------------------------

        conn = None

        try:

            conn = get_db_connection()

            dam_totals = conn.execute(
                """
                SELECT

                    COALESCE(
                        SUM(
                            CASE
                                WHEN adjustment_type LIKE '%تالف%'
                                OR adjustment_type LIKE '%هالك%'
                                OR adjustment_type LIKE '%منتهي%'
                                THEN quantity
                                ELSE 0
                            END
                        ),
                        0
                    ) AS total_dam_qty,

                    COALESCE(
                        SUM(
                            CASE
                                WHEN adjustment_type LIKE '%تالف%'
                                OR adjustment_type LIKE '%هالك%'
                                OR adjustment_type LIKE '%منتهي%'
                                THEN loss_or_gain_value
                                ELSE 0
                            END
                        ),
                        0
                    ) AS total_dam_val,

                    COALESCE(
                        SUM(
                            CASE
                                WHEN adjustment_type LIKE '%صالح%'
                                OR adjustment_type LIKE '%مُصلح%'
                                THEN quantity
                                ELSE 0
                            END
                        ),
                        0
                    ) AS total_ret_qty

                FROM stock_adjustments

                WHERE branch_id = ?
                """,
                (b_id,)
            ).fetchone()

        except Exception as e:

            st.error(
                "❌ تعذر حساب إجماليات الحركات."
            )

            st.code(str(e))

            dam_totals = {
                "total_dam_qty": 0,
                "total_dam_val": 0,
                "total_ret_qty": 0
            }

        finally:

            if conn:
                conn.close()

        col_m1, col_m2, col_m3 = (
            st.columns(3)
        )

        with col_m1:

            st.metric(
                "🗑️ إجمالي كمية التوالف والتالف",
                f"{float(dam_totals['total_dam_qty'] or 0):,.2f} "
                "كجم/قطعة"
            )

        with col_m2:

            st.metric(
                "💸 إجمالي قيمة خسائر التوالف",
                f"{float(dam_totals['total_dam_val'] or 0):,.2f} "
                "د.ل"
            )

        with col_m3:

            st.metric(
                "🔄 إجمالي المرتجعات السليمة",
                f"{float(dam_totals['total_ret_qty'] or 0):,.2f} "
                "كجم/قطعة"
            )

        st.markdown("---")

        # ----------------------------------------------------
        # أصناف الفرع
        # ----------------------------------------------------

        try:

            items_in_branch = (
                get_branch_items(b_id)
            )

        except Exception as e:

            st.error(
                "❌ تعذر تحميل أصناف الفرع."
            )

            st.code(str(e))

            items_in_branch = []

        if items_in_branch:

            item_options = {
                (
                    f"[{it['item_code'] or 'بدون'}] "
                    f"{it['item_name']} "
                    f"(متاح: {it['quantity']})"
                ): it
                for it in items_in_branch
            }

            with st.form(
                "damage_return_form",
                clear_on_submit=True
            ):

                sel_item_label = st.selectbox(
                    "اختر الصنف:",
                    list(item_options.keys())
                )

                selected_item = item_options[
                    sel_item_label
                ]

                col1, col2 = st.columns(2)

                qty = col1.number_input(
                    "الكمية:",
                    min_value=0.01,
                    value=1.0,
                    step=0.5
                )

                adj_type = col2.selectbox(
                    "نوع الحركة (التصنيف):",
                    [
                        "🗑️ تلف / كسر (خسارة تشغيلية)",
                        "⏳ منتهي الصلاحية (خسارة تشغيلية)",
                        "🔄 مرتجع زبون - صالح للبيع (يعود للمخزن)",
                        "⚠️ مرتجع زبون - تالف (لا يعود للبيع)",
                        "🔄 إعادة صنف تالف/مُصلح إلى المخزن (إلغاء إتلاف)"
                    ]
                )

                notes = st.text_input(
                    "ملاحظات أو سبب الحركة (اختياري):",
                    value=""
                )

                submitted = (
                    st.form_submit_button(
                        "💾 اعتماد وتحديث المخزن "
                        "وتسجيل الحركة",
                        type="primary"
                    )
                )

            if submitted:

                execute_adjustment(
                    b_id,
                    selected_item["id"],
                    qty,
                    adj_type,
                    notes
                )

        else:

            st.info(
                "📭 لا توجد أصناف في هذا الفرع."
            )

        # ----------------------------------------------------
        # سجل الحركات
        # ----------------------------------------------------

        st.markdown("---")

        st.markdown(
            "### 📊 سجل الحركات والتوالف لهذا الفرع"
        )

        conn = None

        try:

            conn = get_db_connection()

            adjustment_rows = conn.execute(
                """
                SELECT
                    id,
                    item_name,
                    quantity,
                    adjustment_type,
                    loss_or_gain_value,
                    notes,
                    created_at

                FROM stock_adjustments

                WHERE branch_id = ?

                ORDER BY id DESC
                """,
                (b_id,)
            ).fetchall()

        except Exception as e:

            st.error(
                "❌ تعذر تحميل سجل الحركات."
            )

            st.code(str(e))

            adjustment_rows = []

        finally:

            if conn:
                conn.close()

        if adjustment_rows:

            adjustments_df = pd.DataFrame([
                {
                    "رقم الحركة":
                        row["id"],

                    "اسم الصنف":
                        row["item_name"],

                    "الكمية":
                        row["quantity"],

                    "نوع الحركة":
                        row["adjustment_type"],

                    "قيمة الخسارة (د.ل)":
                        row["loss_or_gain_value"],

                    "الملاحظات":
                        row["notes"],

                    "التاريخ والوقت":
                        row["created_at"]
                }

                for row in adjustment_rows
            ])

            st.dataframe(
                adjustments_df,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.info(
                "📭 لا توجد حركات توالف "
                "أو مرتجعات مسجلة لهذا الفرع."
            )

    # ========================================================
    # 2 - الفائض
    # ========================================================

    with tab2:

        st.markdown(
            "### ➕ إضافة فائض مخزني لفرع معين"
        )

        sel_surplus_branch = st.selectbox(
            "اختر الفرع لإضافة الفائض:",
            list(b_dict.keys()),
            key="surplus_branch_sel"
        )

        b_surplus_id = b_dict[
            sel_surplus_branch
        ]

        try:

            surplus_items = (
                get_branch_items(
                    b_surplus_id
                )
            )

        except Exception as e:

            st.error(
                "❌ تعذر تحميل أصناف الفرع."
            )

            st.code(str(e))

            surplus_items = []

        if surplus_items:

            surplus_opts = {
                (
                    f"[{it['item_code'] or 'بدون'}] "
                    f"{it['item_name']} "
                    f"(الحالي: {it['quantity']})"
                ): it

                for it in surplus_items
            }

            with st.form(
                "surplus_form",
                clear_on_submit=True
            ):

                sel_sur_item_lbl = st.selectbox(
                    "اختر الصنف للفائض:",
                    list(surplus_opts.keys())
                )

                sur_item_obj = surplus_opts[
                    sel_sur_item_lbl
                ]

                sur_qty = st.number_input(
                    "كمية الفائض المضافة:",
                    min_value=0.01,
                    value=1.0,
                    step=0.5
                )

                sur_notes = st.text_input(
                    "سبب الفائض (اختياري):",
                    value="جرد / فائض مخزني"
                )

                surplus_submit = (
                    st.form_submit_button(
                        "💾 اعتماد وإضافة "
                        "الفائض للمخزن",
                        type="primary"
                    )
                )

            if surplus_submit:

                execute_surplus(
                    b_surplus_id,
                    sur_item_obj["id"],
                    sur_qty,
                    sur_notes
                )

        else:

            st.info(
                "لا توجد أصناف في هذا الفرع."
            )

    # ========================================================
    # 3 - تعميم السعر
    # ========================================================

    with tab3:

        st.markdown(
            "### 💲 تعديل وتعميم السعر "
            "على كافة الفروع"
        )

        st.markdown(
            "يمكنك تعديل سعر البيع لأي صنف "
            "وتعميمه فوراً على كافة الفروع "
            "والمخازن في النظام."
        )

        conn = None

        try:

            conn = get_db_connection()

            all_unique_items = conn.execute(
                """
                SELECT DISTINCT
                    item_code,
                    item_name,
                    sale_price
                FROM items
                ORDER BY item_name ASC
                """
            ).fetchall()

        except Exception as e:

            st.error(
                "❌ تعذر تحميل الأصناف."
            )

            st.code(str(e))

            all_unique_items = []

        finally:

            if conn:
                conn.close()

        if all_unique_items:

            item_price_opts = {
                (
                    f"[{it['item_code'] or 'بدون'}] "
                    f"{it['item_name']} "
                    f"(السعر الحالي: "
                    f"{it['sale_price']} د.ل)"
                ): it

                for it in all_unique_items
            }

            with st.form(
                "price_generalize_form",
                clear_on_submit=True
            ):

                sel_p_lbl = st.selectbox(
                    "اختر الصنف لتعديل وتعميم سعره:",
                    list(item_price_opts.keys())
                )

                p_obj = item_price_opts[
                    sel_p_lbl
                ]

                new_general_price = (
                    st.number_input(
                        "سعر البيع الجديد (د.ل):",
                        min_value=0.0,
                        value=float(
                            p_obj[
                                "sale_price"
                            ] or 0
                        ),
                        step=0.5
                    )
                )

                generalize_all = st.checkbox(
                    "تعميم هذا السعر على كافة "
                    "الفروع والمخازن لنفس الصنف",
                    value=True
                )

                price_submit = (
                    st.form_submit_button(
                        "💾 حفظ وتحديث السعر",
                        type="primary"
                    )
                )

            if price_submit:

                if generalize_all:

                    execute_price_update(
                        p_obj["item_code"],
                        p_obj["item_name"],
                        new_general_price
                    )

                else:

                    st.info(
                        "يرجى تفعيل خيار تعميم السعر "
                        "لتطبيق التعديل على جميع الفروع."
                    )

        else:

            st.info(
                "لا توجد أصناف مسجلة في النظام."
            )
