import streamlit as st
import pandas as pd
import io
from datetime import date, timedelta
from database import get_db_connection


# ============================================================
# تحويل DataFrame إلى Excel
# ============================================================

def dataframe_to_excel(df, sheet_name="Report"):

    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        df.to_excel(
            writer,
            index=False,
            sheet_name=sheet_name[:31]
        )

    return output.getvalue()


# ============================================================
# زر Excel
# ============================================================

def excel_button(
    df,
    label,
    filename,
    sheet_name,
    key
):

    if df.empty:
        return

    try:

        excel_data = dataframe_to_excel(
            df,
            sheet_name
        )

        st.download_button(
            label=label,
            data=excel_data,
            file_name=filename,
            mime=(
                "application/vnd.openxmlformats-"
                "officedocument.spreadsheetml.sheet"
            ),
            key=key
        )

    except Exception as e:

        st.error(
            "تعذر إنشاء ملف Excel."
        )

        st.code(str(e))


# ============================================================
# تنفيذ SELECT وتحويله إلى DataFrame
# ============================================================

def query_dataframe(
    query,
    params=None
):

    conn = None

    try:

        conn = get_db_connection()

        cursor = conn.execute(
            query,
            params or ()
        )

        rows = cursor.fetchall()

        if not rows:
            return pd.DataFrame()

        columns = [
            desc[0]
            for desc in cursor.description
        ]

        return pd.DataFrame(
            [
                [row[col] for col in columns]
                for row in rows
            ],
            columns=columns
        )

    finally:

        if conn:
            conn.close()


# ============================================================
# تحميل الفروع
# ============================================================

def get_branches():

    conn = None

    try:

        conn = get_db_connection()

        return conn.execute(
            """
            SELECT
                id,
                branch_name,
                branch_type
            FROM branches
            ORDER BY id ASC
            """
        ).fetchall()

    finally:

        if conn:
            conn.close()


# ============================================================
# فلتر الفرع
# ============================================================

def get_branch_filter(
    branches,
    label,
    key,
    include_all=True
):

    branch_dict = {
        b["branch_name"]: b["id"]
        for b in branches
    }

    options = list(
        branch_dict.keys()
    )

    if include_all:
        options = [
            "🌐 كل الفروع"
        ] + options

    selected = st.selectbox(
        label,
        options,
        key=key
    )

    if selected == "🌐 كل الفروع":
        return None, selected

    return (
        branch_dict[selected],
        selected
    )


# ============================================================
# فلتر التاريخ
# ============================================================

def date_filter(
    prefix,
    default_days=30
):

    today = date.today()

    default_from = (
        today
        - timedelta(
            days=default_days
        )
    )

    c1, c2 = st.columns(2)

    from_date = c1.date_input(
        "📅 من تاريخ:",
        value=default_from,
        key=f"{prefix}_from"
    )

    to_date = c2.date_input(
        "📅 إلى تاريخ:",
        value=today,
        key=f"{prefix}_to"
    )

    if from_date > to_date:

        st.error(
            "⚠️ تاريخ البداية يجب أن "
            "يكون قبل تاريخ النهاية."
        )

        return None, None

    return from_date, to_date


# ============================================================
# تبويب الملخص المالي
# ============================================================

def show_financial_summary(
    branches,
    is_admin_or_supervisor
):

    st.markdown(
        "### 💰 الملخص المالي"
    )

    if not is_admin_or_supervisor:

        st.warning(
            "🔒 هذا التقرير مخصص "
            "للإدارة والمشرف العام."
        )

        return

    branch_id, branch_name = (
        get_branch_filter(
            branches,
            "اختر الفرع:",
            "financial_branch"
        )
    )

    from_date, to_date = date_filter(
        "financial",
        30
    )

    if not from_date:
        return

    # ========================================================
    # تجهيز شرط الفرع
    # ========================================================

    invoice_params = [
        from_date,
        to_date
    ]

    invoice_branch_sql = ""

    if branch_id:

        invoice_branch_sql = (
            " AND branch_id = ? "
        )

        invoice_params.append(
            branch_id
        )

    # ========================================================
    # المبيعات
    # ========================================================

    sales_df = query_dataframe(
        f"""
        SELECT
            COALESCE(
                SUM(total_amount),
                0
            ) AS total_sales
        FROM invoices
        WHERE DATE(created_at)
              BETWEEN ? AND ?
        {invoice_branch_sql}
        """,
        tuple(invoice_params)
    )

    total_sales = (
        float(
            sales_df.iloc[0][
                "total_sales"
            ] or 0
        )
        if not sales_df.empty
        else 0.0
    )

    # ========================================================
    # المصروفات
    # ========================================================

    expense_params = [
        from_date,
        to_date
    ]

    expense_branch_sql = ""

    if branch_id:

        expense_branch_sql = (
            " AND branch_id = ? "
        )

        expense_params.append(
            branch_id
        )

    expenses_df = query_dataframe(
        f"""
        SELECT
            COALESCE(
                SUM(amount),
                0
            ) AS total_expenses
        FROM expenses
        WHERE DATE(expense_date)
              BETWEEN ? AND ?
        {expense_branch_sql}
        """,
        tuple(expense_params)
    )

    total_expenses = (
        float(
            expenses_df.iloc[0][
                "total_expenses"
            ] or 0
        )
        if not expenses_df.empty
        else 0.0
    )

    # ========================================================
    # التوالف والخسائر
    # ========================================================

    adjustment_params = [
        from_date,
        to_date
    ]

    adjustment_branch_sql = ""

    if branch_id:

        adjustment_branch_sql = (
            " AND branch_id = ? "
        )

        adjustment_params.append(
            branch_id
        )

    damages_df = query_dataframe(
        f"""
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN
                            adjustment_type
                                LIKE '%تالف%'
                            OR adjustment_type
                                LIKE '%هالك%'
                            OR adjustment_type
                                LIKE '%منتهي%'
                        THEN
                            GREATEST(
                                COALESCE(
                                    loss_or_gain_value,
                                    0
                                ),
                                0
                            )
                        ELSE 0
                    END
                ),
                0
            ) AS total_damages
        FROM stock_adjustments
        WHERE DATE(created_at)
              BETWEEN ? AND ?
        {adjustment_branch_sql}
        """,
        tuple(adjustment_params)
    )

    total_damages = (
        float(
            damages_df.iloc[0][
                "total_damages"
            ] or 0
        )
        if not damages_df.empty
        else 0.0
    )

    # ========================================================
    # الإيرادات الأخرى
    # ========================================================

    revenue_params = [
        from_date,
        to_date
    ]

    revenue_branch_sql = ""

    if branch_id:
        revenue_branch_sql = (
            " AND branch_id = ? "
        )
        revenue_params.append(branch_id)

    revenues_df = query_dataframe(
        f"""
        SELECT
            COALESCE(SUM(amount), 0)
                AS total_revenues
        FROM revenues
        WHERE DATE(revenue_date)
              BETWEEN ? AND ?
        {revenue_branch_sql}
        """,
        tuple(revenue_params)
    )

    total_revenues = (
        float(
            revenues_df.iloc[0]["total_revenues"] or 0
        )
        if not revenues_df.empty
        else 0.0
    )

    # ========================================================
    # الناتج التشغيلي
    # ========================================================

    operating_result = (
        total_sales
        + total_revenues
        - total_expenses
        - total_damages
    )

    c1, c2, c3, c4, c5 = (
        st.columns(5)
    )

    c1.metric(
        "💰 المبيعات",
        f"{total_sales:,.2f} د.ل"
    )

    c2.metric(
        "💵 الإيرادات الأخرى",
        f"{total_revenues:,.2f} د.ل"
    )

    c3.metric(
        "💸 المصروفات",
        f"{total_expenses:,.2f} د.ل"
    )

    c4.metric(
        "🗑️ التوالف",
        f"{total_damages:,.2f} د.ل"
    )

    c5.metric(
        "📊 الناتج التشغيلي",
        f"{operating_result:,.2f} د.ل"
    )

    st.info(
        "ℹ️ الناتج التشغيلي هنا = "
        "المبيعات + الإيرادات الأخرى "
        "- المصروفات - التوالف. "
        "ولا نسميه صافي الربح النهائي "
        "لأن تكلفة البضاعة المباعة "
        "تحتاج حساباً مستقلاً."
    )

    summary_df = pd.DataFrame(
        [
            {
                "الفترة من":
                    from_date,

                "الفترة إلى":
                    to_date,

                "الفرع":
                    branch_name,

                "إجمالي المبيعات":
                    total_sales,

                "إجمالي الإيرادات الأخرى":
                    total_revenues,

                "إجمالي المصروفات":
                    total_expenses,

                "إجمالي التوالف":
                    total_damages,

                "الناتج التشغيلي":
                    operating_result
            }
        ]
    )

    excel_button(
        summary_df,
        "📥 تحميل الملخص المالي Excel",
        (
            f"Financial_Summary_"
            f"{from_date}_to_{to_date}.xlsx"
        ),
        "Financial_Summary",
        "financial_excel"
    )


# ============================================================
# تقرير المبيعات
# ============================================================

def show_sales_report(
    branches,
    is_admin_or_supervisor
):

    st.markdown(
        "### 🧾 تقرير المبيعات والفواتير"
    )

    branch_id, branch_name = (
        get_branch_filter(
            branches,
            "اختر الفرع:",
            "sales_branch"
        )
    )

    from_date, to_date = date_filter(
        "sales",
        30
    )

    if not from_date:
        return

    params = [
        from_date,
        to_date
    ]

    branch_sql = ""

    if branch_id:

        branch_sql = (
            " AND i.branch_id = ? "
        )

        params.append(
            branch_id
        )

    df = query_dataframe(
        f"""
        SELECT
            i.id AS "رقم الفاتورة",
            DATE(i.created_at) AS "التاريخ",
            i.created_at AS "التاريخ والوقت",
            b.branch_name AS "الفرع",
            COALESCE(
                u.username,
                'غير محدد'
            ) AS "الكاشير",
            i.customer_name AS "الزبون",
            i.customer_phone AS "الهاتف",
            i.payment_method AS "طريقة الدفع",
            i.total_amount AS "صافي الفاتورة",
            i.shift_status AS "الوردية"
        FROM invoices i

        LEFT JOIN branches b
            ON b.id = i.branch_id

        LEFT JOIN users u
            ON u.id = i.user_id

        WHERE DATE(i.created_at)
              BETWEEN ? AND ?

        {branch_sql}

        ORDER BY i.created_at DESC
        """,
        tuple(params)
    )

    if df.empty:

        st.info(
            "لا توجد مبيعات في الفترة "
            "المحددة."
        )

        return

    total_sales = pd.to_numeric(
        df["صافي الفاتورة"],
        errors="coerce"
    ).fillna(0).sum()

    st.metric(
        "إجمالي المبيعات في الفترة",
        f"{total_sales:,.2f} د.ل"
    )

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    excel_button(
        df,
        "📥 تحميل تقرير المبيعات Excel",
        (
            f"Sales_"
            f"{from_date}_to_{to_date}.xlsx"
        ),
        "Sales",
        "sales_excel"
    )


# ============================================================
# تقرير المشتريات
# ============================================================

def show_purchases_report(
    branches,
    is_admin_or_supervisor
):

    st.markdown(
        "### 📥 تقرير المشتريات"
    )

    if not is_admin_or_supervisor:

        st.warning(
            "🔒 تقرير المشتريات التفصيلي "
            "مخصص للإدارة."
        )

        return

    branch_id, branch_name = (
        get_branch_filter(
            branches,
            "اختر الفرع / المخزن:",
            "purchase_branch"
        )
    )

    from_date, to_date = date_filter(
        "purchases",
        30
    )

    if not from_date:
        return

    params = [
        from_date,
        to_date
    ]

    branch_sql = ""

    if branch_id:

        branch_sql = (
            " AND p.branch_id = ? "
        )

        params.append(
            branch_id
        )

    df = query_dataframe(
        f"""
        SELECT
            p.id AS "رقم الحركة",
            p.invoice_date AS "التاريخ",
            b.branch_name AS "الفرع / المخزن",
            p.supplier_name AS "المورد",
            p.invoice_number AS "رقم فاتورة المورد",
            p.payment_type AS "طريقة الدفع",
            p.total_cost AS "إجمالي التكلفة",
            p.items_details AS "تفاصيل الأصناف"
        FROM purchases p

        LEFT JOIN branches b
            ON b.id = p.branch_id

        WHERE DATE(p.invoice_date)
              BETWEEN ? AND ?

        {branch_sql}

        ORDER BY
            p.invoice_date DESC,
            p.id DESC
        """,
        tuple(params)
    )

    if df.empty:

        st.info(
            "لا توجد مشتريات في الفترة "
            "المحددة."
        )

        return

    total_purchases = pd.to_numeric(
        df["إجمالي التكلفة"],
        errors="coerce"
    ).fillna(0).sum()

    st.metric(
        "إجمالي المشتريات",
        f"{total_purchases:,.2f} د.ل"
    )

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    excel_button(
        df,
        "📥 تحميل تقرير المشتريات Excel",
        (
            f"Purchases_"
            f"{from_date}_to_{to_date}.xlsx"
        ),
        "Purchases",
        "purchases_excel"
    )


# ============================================================
# تقرير المصروفات
# ============================================================

def show_expenses_report(
    branches,
    is_admin_or_supervisor
):

    st.markdown(
        "### 💸 تقرير المصروفات"
    )

    if not is_admin_or_supervisor:

        st.warning(
            "🔒 تقرير المصروفات "
            "مخصص للإدارة."
        )

        return

    branch_id, branch_name = (
        get_branch_filter(
            branches,
            "اختر الفرع:",
            "expenses_branch"
        )
    )

    from_date, to_date = date_filter(
        "expenses",
        30
    )

    if not from_date:
        return

    params = [
        from_date,
        to_date
    ]

    branch_sql = ""

    if branch_id:

        branch_sql = (
            " AND e.branch_id = ? "
        )

        params.append(
            branch_id
        )

    df = query_dataframe(
        f"""
        SELECT
            e.id AS "رقم المصروف",
            e.expense_date AS "التاريخ",
            b.branch_name AS "الفرع",
            e.amount AS "المبلغ",
            e.description AS "البيان",
            CASE
                WHEN e.is_general_store = 1
                THEN 'مصروف عام موزع'
                ELSE 'مصروف مباشر'
            END AS "نوع المصروف"
        FROM expenses e

        LEFT JOIN branches b
            ON b.id = e.branch_id

        WHERE DATE(e.expense_date)
              BETWEEN ? AND ?

        {branch_sql}

        ORDER BY
            e.expense_date DESC,
            e.id DESC
        """,
        tuple(params)
    )

    if df.empty:

        st.info(
            "لا توجد مصروفات في الفترة "
            "المحددة."
        )

        return

    total_expenses = pd.to_numeric(
        df["المبلغ"],
        errors="coerce"
    ).fillna(0).sum()

    st.metric(
        "إجمالي المصروفات",
        f"{total_expenses:,.2f} د.ل"
    )

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    excel_button(
        df,
        "📥 تحميل تقرير المصروفات Excel",
        (
            f"Expenses_"
            f"{from_date}_to_{to_date}.xlsx"
        ),
        "Expenses",
        "expenses_excel"
    )


# ============================================================
# تقرير حركات المخزون اليدوية
# ============================================================

def show_adjustments_report(
    branches,
    is_admin_or_supervisor
):

    st.markdown(
        "### ✍️ تقرير الحركات اليدوية "
        "والتوالف والفائض"
    )

    branch_id, branch_name = (
        get_branch_filter(
            branches,
            "اختر الفرع:",
            "adjustment_branch"
        )
    )

    from_date, to_date = date_filter(
        "adjustments",
        30
    )

    if not from_date:
        return

    params = [
        from_date,
        to_date
    ]

    branch_sql = ""

    if branch_id:

        branch_sql = (
            " AND a.branch_id = ? "
        )

        params.append(
            branch_id
        )

    df = query_dataframe(
        f"""
        SELECT
            a.id AS "رقم الحركة",
            a.created_at AS "التاريخ والوقت",
            b.branch_name AS "الفرع",
            a.item_name AS "الصنف",
            a.quantity AS "الكمية",
            a.adjustment_type AS "نوع الحركة",
            a.loss_or_gain_value
                AS "قيمة الخسارة / الزيادة",
            a.notes AS "ملاحظات"
        FROM stock_adjustments a

        LEFT JOIN branches b
            ON b.id = a.branch_id

        WHERE DATE(a.created_at)
              BETWEEN ? AND ?

        {branch_sql}

        ORDER BY a.created_at DESC
        """,
        tuple(params)
    )

    if df.empty:

        st.info(
            "لا توجد حركات مخزون يدوية "
            "في الفترة المحددة."
        )

        return

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    excel_button(
        df,
        "📥 تحميل تقرير الحركات اليدوية Excel",
        (
            f"Adjustments_"
            f"{from_date}_to_{to_date}.xlsx"
        ),
        "Adjustments",
        "adjustments_excel"
    )



# ============================================================
# تقرير الإيرادات
# ============================================================

def show_revenues_report(branches, is_admin_or_supervisor):

    st.markdown("### 💵 تقرير الإيرادات")

    if not is_admin_or_supervisor:
        st.warning("🔒 تقرير الإيرادات مخصص للإدارة.")
        return

    branch_id, branch_name = get_branch_filter(
        branches,
        "اختر الفرع:",
        "revenues_branch"
    )

    from_date, to_date = date_filter("revenues", 30)

    if not from_date:
        return

    params = [from_date, to_date]
    branch_sql = ""

    if branch_id:
        branch_sql = " AND r.branch_id = ? "
        params.append(branch_id)

    df = query_dataframe(
        f"""
        SELECT
            r.id AS "رقم الإيراد",
            r.revenue_date AS "التاريخ",
            b.branch_name AS "الفرع",
            r.amount AS "المبلغ",
            r.description AS "البيان"
        FROM revenues r
        LEFT JOIN branches b
            ON b.id = r.branch_id
        WHERE DATE(r.revenue_date)
              BETWEEN ? AND ?
        {branch_sql}
        ORDER BY r.revenue_date DESC, r.id DESC
        """,
        tuple(params)
    )

    if df.empty:
        st.info("لا توجد إيرادات في الفترة المحددة.")
        return

    total_revenues = pd.to_numeric(
        df["المبلغ"],
        errors="coerce"
    ).fillna(0).sum()

    st.metric(
        "إجمالي الإيرادات",
        f"{total_revenues:,.2f} د.ل"
    )

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    excel_button(
        df,
        "📥 تحميل تقرير الإيرادات Excel",
        f"Revenues_{from_date}_to_{to_date}.xlsx",
        "Revenues",
        "revenues_excel"
    )


# ============================================================
# تقرير التحويلات / التزويد
# ============================================================

def show_transfers_report(branches, is_admin_or_supervisor):

    st.markdown("### 🔄 تقرير تحويلات وتزويد الفروع")

    branch_id, branch_name = get_branch_filter(
        branches,
        "اختر الفرع المستلم:",
        "reports_transfers_branch"
    )

    from_date, to_date = date_filter(
        "reports_transfers",
        30
    )

    if not from_date:
        return

    params = [from_date, to_date]
    branch_sql = ""

    if branch_id:
        branch_sql = " AND t.to_branch_id = ? "
        params.append(branch_id)

    df = query_dataframe(
        f"""
        SELECT
            t.id AS "رقم التحويل",
            t.transfer_date AS "التاريخ والوقت",
            b1.branch_name AS "من",
            b2.branch_name AS "إلى",
            t.transfer_type AS "نوع التحويل",
            t.items_details AS "تفاصيل الأصناف",
            t.status AS "الحالة"
        FROM transfer_logs t
        LEFT JOIN branches b1
            ON b1.id = t.from_branch_id
        LEFT JOIN branches b2
            ON b2.id = t.to_branch_id
        WHERE DATE(t.transfer_date)
              BETWEEN ? AND ?
        {branch_sql}
        ORDER BY t.transfer_date DESC, t.id DESC
        """,
        tuple(params)
    )

    if df.empty:
        st.info("لا توجد تحويلات في الفترة المحددة.")
        return

    st.metric("عدد التحويلات", f"{len(df):,}")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    excel_button(
        df,
        "📥 تحميل تقرير التحويلات Excel",
        f"Transfers_{from_date}_to_{to_date}.xlsx",
        "Transfers",
        "reports_transfers_excel"
    )


# ============================================================
# تقرير الإنتاج: الخلط والتحميص
# ============================================================

def show_production_report(branches, is_admin_or_supervisor):

    st.markdown("### 🔥🥜 تقرير الخلط والتحميص")

    if not is_admin_or_supervisor:
        st.warning("🔒 تقرير تكلفة الإنتاج مخصص للإدارة.")
        return

    branch_id, branch_name = get_branch_filter(
        branches,
        "اختر المخزن / الفرع:",
        "production_branch"
    )

    from_date, to_date = date_filter(
        "production",
        30
    )

    if not from_date:
        return

    params = [from_date, to_date]
    branch_sql = ""

    if branch_id:
        branch_sql = " AND p.branch_id = ? "
        params.append(branch_id)

    df = query_dataframe(
        f"""
        SELECT
            p.id AS "رقم العملية",
            p.created_at AS "التاريخ والوقت",
            b.branch_name AS "المخزن / الفرع",
            p.production_type AS "نوع العملية",
            p.source_item_name AS "الخامة / المصدر",
            p.target_item_name AS "الصنف الناتج",
            p.input_quantity AS "الكمية الداخلة",
            p.output_quantity AS "الكمية الناتجة",
            p.loss_quantity AS "الفقد",
            p.total_cost AS "إجمالي التكلفة",
            p.unit_cost AS "تكلفة الوحدة",
            p.sale_price AS "سعر البيع",
            p.notes AS "التفاصيل"
        FROM production_logs p
        LEFT JOIN branches b
            ON b.id = p.branch_id
        WHERE DATE(p.created_at)
              BETWEEN ? AND ?
        {branch_sql}
        ORDER BY p.created_at DESC, p.id DESC
        """,
        tuple(params)
    )

    if df.empty:
        st.info("لا توجد عمليات خلط أو تحميص في الفترة المحددة.")
        return

    total_input = pd.to_numeric(
        df["الكمية الداخلة"], errors="coerce"
    ).fillna(0).sum()

    total_output = pd.to_numeric(
        df["الكمية الناتجة"], errors="coerce"
    ).fillna(0).sum()

    total_loss = pd.to_numeric(
        df["الفقد"], errors="coerce"
    ).fillna(0).sum()

    total_cost = pd.to_numeric(
        df["إجمالي التكلفة"], errors="coerce"
    ).fillna(0).sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("الكمية الداخلة", f"{total_input:,.2f}")
    c2.metric("الكمية الناتجة", f"{total_output:,.2f}")
    c3.metric("إجمالي الفقد", f"{total_loss:,.2f}")
    c4.metric("تكلفة العمليات", f"{total_cost:,.2f} د.ل")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    excel_button(
        df,
        "📥 تحميل تقرير الإنتاج Excel",
        f"Production_{from_date}_to_{to_date}.xlsx",
        "Production",
        "production_excel"
    )


# ============================================================
# تقرير المخزون والتكلفة
# ============================================================

def show_inventory_report(
    branches,
    is_admin_or_supervisor
):

    st.markdown(
        "### 📦 تقرير المخزون "
        "ومتوسط التكلفة"
    )

    branch_id, branch_name = (
        get_branch_filter(
            branches,
            "اختر الفرع:",
            "inventory_report_branch"
        )
    )

    params = []
    branch_sql = ""

    if branch_id:

        branch_sql = (
            " WHERE i.branch_id = ? "
        )

        params.append(
            branch_id
        )

    df = query_dataframe(
        f"""
        SELECT
            i.item_code AS "كود الصنف",
            i.item_name AS "اسم الصنف",
            b.branch_name AS "الفرع",
            i.quantity AS "الكمية المتاحة",
            i.buy_price AS "آخر سعر شراء",
            i.avg_cost AS "متوسط التكلفة",
            i.sale_price AS "سعر البيع"
        FROM items i

        LEFT JOIN branches b
            ON b.id = i.branch_id

        {branch_sql}

        ORDER BY
            b.branch_name,
            i.item_name
        """,
        tuple(params)
    )

    if df.empty:

        st.info(
            "لا توجد أصناف."
        )

        return

    # ========================================================
    # الأرقام
    # ========================================================

    for column in [
        "الكمية المتاحة",
        "آخر سعر شراء",
        "متوسط التكلفة",
        "سعر البيع"
    ]:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        ).fillna(0.0)

    # ========================================================
    # الإدارة فقط ترى التكلفة والأرباح
    # ========================================================

    if is_admin_or_supervisor:

        # لو المتوسط صفر نستخدم آخر سعر شراء
        df["التكلفة المعتمدة"] = (
            df.apply(
                lambda row:
                    row["متوسط التكلفة"]
                    if row["متوسط التكلفة"] > 0
                    else row["آخر سعر شراء"],
                axis=1
            )
        )

        df["قيمة المخزون بالتكلفة"] = (
            df["الكمية المتاحة"]
            * df["التكلفة المعتمدة"]
        )

        df["ربح الوحدة المتوقع"] = (
            df["سعر البيع"]
            - df["التكلفة المعتمدة"]
        )

        df["نسبة الزيادة على التكلفة %"] = (
            df.apply(
                lambda row:
                    round(
                        (
                            row[
                                "ربح الوحدة المتوقع"
                            ]
                            / row[
                                "التكلفة المعتمدة"
                            ]
                        )
                        * 100,
                        2
                    )
                    if row[
                        "التكلفة المعتمدة"
                    ] > 0
                    else 0.0,
                axis=1
            )
        )

        total_stock_value = (
            df[
                "قيمة المخزون بالتكلفة"
            ].sum()
        )

        st.metric(
            "💰 قيمة المخزون بالتكلفة",
            f"{total_stock_value:,.2f} د.ل"
        )

    else:

        df = df.drop(
            columns=[
                "آخر سعر شراء",
                "متوسط التكلفة"
            ],
            errors="ignore"
        )

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )

    excel_button(
        df,
        "📥 تحميل تقرير المخزون Excel",
        "Inventory_Report.xlsx",
        "Inventory",
        "inventory_excel"
    )


# ============================================================
# الصفحة الرئيسية
# ============================================================

def show_page():

    st.markdown(
        """
        <style>

        .stDataFrame div,
        .stDataFrame span,
        .stDataFrame p,
        div[data-testid="stTable"] *,
        th,
        td {
            color: #000000 !important;
            font-weight: 700 !important;
        }

        th {
            background-color: #94a3b8 !important;
            color: #000000 !important;
            text-align: right !important;
        }

        td {
            background-color: #f8fafc !important;
            text-align: right !important;
        }

        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <h2 style="
            color:#0f172a;
            font-weight:900;
        ">
        📊 مركز التقارير الشامل
        </h2>
        """,
        unsafe_allow_html=True
    )

    st.info(
        "💡 جميع تقارير الحركات متاحة "
        "بفلترة من تاريخ إلى تاريخ، "
        "مع إمكانية التصفية حسب الفرع "
        "والتصدير إلى Excel."
    )

    st.markdown("---")

    role = st.session_state.get(
        "role",
        ""
    )

    is_admin_or_supervisor = (
        role in [
            "Admin",
            "General_Supervisor"
        ]
    )

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
            "لا توجد فروع مسجلة."
        )

        return

    (
        tab_financial,
        tab_sales,
        tab_purchases,
        tab_expenses,
        tab_revenues,
        tab_adjustments,
        tab_transfers,
        tab_production,
        tab_inventory
    ) = st.tabs(
        [
            "💰 الملخص المالي",
            "🧾 المبيعات",
            "📥 المشتريات",
            "💸 المصروفات",
            "💵 الإيرادات",
            "✍️ الحركات اليدوية",
            "🔄 التحويلات",
            "🔥🥜 الخلط والتحميص",
            "📦 المخزون والتكلفة"
        ]
    )

    with tab_financial:

        show_financial_summary(
            branches,
            is_admin_or_supervisor
        )

    with tab_sales:

        show_sales_report(
            branches,
            is_admin_or_supervisor
        )

    with tab_purchases:

        show_purchases_report(
            branches,
            is_admin_or_supervisor
        )

    with tab_expenses:

        show_expenses_report(
            branches,
            is_admin_or_supervisor
        )

    with tab_revenues:

        show_revenues_report(
            branches,
            is_admin_or_supervisor
        )

    with tab_adjustments:

        show_adjustments_report(
            branches,
            is_admin_or_supervisor
        )

    with tab_transfers:

        show_transfers_report(
            branches,
            is_admin_or_supervisor
        )

    with tab_production:

        show_production_report(
            branches,
            is_admin_or_supervisor
        )

    with tab_inventory:

        show_inventory_report(
            branches,
            is_admin_or_supervisor
        )
