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
                            MAX(
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
        WHERE DATE(created_at)
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
            DATE(r.created_at) AS "التاريخ",
            b.branch_name AS "الفرع",
            r.amount AS "المبلغ",
            COALESCE(
                NULLIF(r.notes, ''),
                NULLIF(r.revenue_source, ''),
                'إيراد'
            ) AS "البيان"
        FROM revenues r
        LEFT JOIN branches b
            ON b.id = r.branch_id
        WHERE DATE(r.created_at)
              BETWEEN ? AND ?
        {branch_sql}
        ORDER BY r.created_at DESC, r.id DESC
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
            p.operation_type AS "نوع العملية",
            p.source_details AS "الخامة / المصدر",
            p.target_item_name AS "الصنف الناتج",
            p.input_weight AS "الكمية الداخلة",
            p.output_weight AS "الكمية الناتجة",
            p.loss_weight AS "الفقد",
            p.total_cost AS "إجمالي التكلفة",
            p.unit_cost AS "تكلفة الوحدة",
            0.0 AS "سعر البيع",
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
# تقرير حركة الأصناف الشامل
# ============================================================

def _movement_parse_purchase_details(details):
    import re
    result = []
    for part in str(details or "").split(" | "):
        code_m = re.search(r"\[([^\]]+)\]", part)
        qty_m = re.search(r"-\s*كمية:\s*([\d.,]+)", part)
        price_m = re.search(r"-\s*سعر:\s*([\d.,]+)", part)
        if not code_m or not qty_m:
            continue
        try:
            qty = float(qty_m.group(1).replace(",", ""))
            price = float(price_m.group(1).replace(",", "")) if price_m else 0.0
        except Exception:
            continue
        result.append((code_m.group(1).strip(), qty, price))
    return result


def _movement_parse_transfer_details(details):
    import re
    result = []
    for line in str(details or "").splitlines():
        code_m = re.search(r"\[([^\]]+)\]", line)
        qty_m = re.search(r"الكمية:\s*([\d.,]+)", line)
        if not code_m or not qty_m:
            continue
        try:
            qty = float(qty_m.group(1).replace(",", ""))
        except Exception:
            continue
        result.append((code_m.group(1).strip(), qty))
    return result


def _movement_parse_invoice_notes(notes):
    import json
    try:
        data = json.loads(notes or "")
    except Exception:
        return []
    if isinstance(data, dict):
        return data.get("items", []) or []
    if isinstance(data, list):
        return data
    return []


def show_item_movement_report(branches, is_admin_or_supervisor):
    st.markdown("### 📈 حركة الأصناف خلال فترة")

    conn = get_db_connection()
    try:
        branch_rows = conn.execute(
            "SELECT id, branch_name FROM branches ORDER BY branch_name"
        ).fetchall()
        item_rows = conn.execute(
            """
            SELECT DISTINCT item_code, item_name
            FROM items
            WHERE COALESCE(item_code, '') <> ''
            ORDER BY item_name
            """
        ).fetchall()

        branch_options = {"🌐 كل الفروع والمخازن": None}
        branch_options.update({r["branch_name"]: r["id"] for r in branch_rows})

        item_options = {"📦 كل الأصناف": None}
        for r in item_rows:
            item_options[f"{r['item_name']} [{r['item_code']}]"] = r["item_code"]

        f1, f2 = st.columns(2)
        branch_label = f1.selectbox(
            "الفرع / المخزن:",
            list(branch_options.keys()),
            key="movement_branch"
        )
        item_label = f2.selectbox(
            "الصنف:",
            list(item_options.keys()),
            key="movement_item"
        )

        from_date, to_date = date_filter("item_movement", 30)
        if not from_date:
            return

        branch_id = branch_options[branch_label]
        selected_code = item_options[item_label]
        movements = []

        def add_move(dt, bid, bname, code, name, kind, incoming, outgoing, unit_cost, ref, notes=""):
            if selected_code and str(code) != str(selected_code):
                return
            if branch_id and int(bid or 0) != int(branch_id):
                return
            movements.append({
                "التاريخ والوقت": dt,
                "الفرع / المخزن": bname or "",
                "كود الصنف": code or "",
                "الصنف": name or "",
                "نوع الحركة": kind,
                "وارد": float(incoming or 0),
                "صادر": float(outgoing or 0),
                "متوسط / تكلفة الوحدة": float(unit_cost or 0),
                "قيمة الحركة": float((incoming or outgoing or 0) * (unit_cost or 0)),
                "المرجع": ref,
                "ملاحظات": notes or ""
            })

        # خريطة الأصناف والتكلفة الحالية، لاستخدامها عند السجلات القديمة
        items = conn.execute(
            """
            SELECT id, branch_id, item_code, item_name,
                   COALESCE(avg_cost, buy_price, 0) AS unit_cost
            FROM items
            """
        ).fetchall()
        by_id = {(r["branch_id"], r["id"]): r for r in items}
        by_code_branch = {(r["branch_id"], str(r["item_code"])): r for r in items}
        by_name_branch = {(r["branch_id"], str(r["item_name"])): r for r in items}
        branch_names = {r["id"]: r["branch_name"] for r in branch_rows}

        # المبيعات: تفاصيل الأصناف محفوظة JSON داخل invoices.notes
        inv_params = [from_date, to_date]
        inv_branch = ""
        if branch_id:
            inv_branch = " AND v.branch_id=? "
            inv_params.append(branch_id)
        invoices = conn.execute(
            f"""
            SELECT v.id, v.branch_id, v.created_at, v.notes
            FROM invoices v
            WHERE DATE(v.created_at) BETWEEN ? AND ?
            {inv_branch}
            ORDER BY v.created_at
            """,
            tuple(inv_params)
        ).fetchall()
        for inv in invoices:
            for ci in _movement_parse_invoice_notes(inv["notes"]):
                if ci.get("id") == 99999:
                    continue
                code = ci.get("code") or ci.get("item_code")
                item = None
                if code:
                    item = by_code_branch.get((inv["branch_id"], str(code)))
                if item is None and ci.get("id") is not None:
                    item = by_id.get((inv["branch_id"], ci.get("id")))
                if item is None:
                    item = by_name_branch.get((inv["branch_id"], str(ci.get("name") or "")))
                code = code or (item["item_code"] if item else "")
                name = ci.get("name") or (item["item_name"] if item else "")
                qty = float(ci.get("qty", 0) or 0)
                cost = float(item["unit_cost"] or 0) if item else 0.0
                add_move(
                    inv["created_at"], inv["branch_id"], branch_names.get(inv["branch_id"]),
                    code, name, "بيع", 0, qty, cost, f"فاتورة بيع #{inv['id']}"
                )

        # المشتريات
        pur_params = [from_date, to_date]
        pur_branch = ""
        if branch_id:
            pur_branch = " AND p.branch_id=? "
            pur_params.append(branch_id)
        purchases = conn.execute(
            f"""
            SELECT p.id, p.branch_id, p.invoice_date, p.invoice_number, p.items_details
            FROM purchases p
            WHERE DATE(p.invoice_date) BETWEEN ? AND ?
            {pur_branch}
            ORDER BY p.invoice_date
            """,
            tuple(pur_params)
        ).fetchall()
        for p in purchases:
            for code, qty, price in _movement_parse_purchase_details(p["items_details"]):
                item = by_code_branch.get((p["branch_id"], str(code)))
                add_move(
                    p["invoice_date"], p["branch_id"], branch_names.get(p["branch_id"]),
                    code, item["item_name"] if item else code, "شراء",
                    qty, 0, price, f"مشتريات #{p['id']} / {p['invoice_number'] or '-'}"
                )

        # التحويلات: حركة صادرة من المرسل وواردة للمستلم
        transfers = conn.execute(
            """
            SELECT id, from_branch_id, to_branch_id, transfer_date, items_details, status
            FROM transfer_logs
            WHERE DATE(transfer_date) BETWEEN ? AND ?
            ORDER BY transfer_date
            """,
            (from_date, to_date)
        ).fetchall()
        for t in transfers:
            for code, qty in _movement_parse_transfer_details(t["items_details"]):
                src_item = by_code_branch.get((t["from_branch_id"], str(code)))
                dst_item = by_code_branch.get((t["to_branch_id"], str(code)))
                cost = float(src_item["unit_cost"] or 0) if src_item else 0.0
                name = (src_item or dst_item)["item_name"] if (src_item or dst_item) else code
                add_move(
                    t["transfer_date"], t["from_branch_id"], branch_names.get(t["from_branch_id"]),
                    code, name, "تحويل صادر", 0, qty, cost, f"تحويل #{t['id']}", t["status"]
                )
                add_move(
                    t["transfer_date"], t["to_branch_id"], branch_names.get(t["to_branch_id"]),
                    code, name, "تحويل وارد", qty, 0, cost, f"تحويل #{t['id']}", t["status"]
                )

        # التعديلات اليدوية / التوالف / الفائض
        adj_params = [from_date, to_date]
        adj_branch = ""
        if branch_id:
            adj_branch = " AND a.branch_id=? "
            adj_params.append(branch_id)
        adjustments = conn.execute(
            f"""
            SELECT a.id, a.branch_id, a.created_at, a.item_name, a.quantity,
                   a.adjustment_type, a.loss_or_gain_value, a.notes
            FROM stock_adjustments a
            WHERE DATE(a.created_at) BETWEEN ? AND ?
            {adj_branch}
            ORDER BY a.created_at
            """,
            tuple(adj_params)
        ).fetchall()
        for a in adjustments:
            item = by_name_branch.get((a["branch_id"], str(a["item_name"])))
            qty = abs(float(a["quantity"] or 0))
            typ = str(a["adjustment_type"] or "")
            is_out = any(k in typ for k in ["تالف", "هالك", "منتهي", "نقص", "خصم", "سحب"])
            if not is_out and float(a["quantity"] or 0) < 0:
                is_out = True
            cost = float(item["unit_cost"] or 0) if item else 0.0
            add_move(
                a["created_at"], a["branch_id"], branch_names.get(a["branch_id"]),
                item["item_code"] if item else "", a["item_name"],
                f"تعديل مخزون - {typ}", 0 if is_out else qty, qty if is_out else 0,
                cost, f"تعديل #{a['id']}", a["notes"]
            )

        # الإنتاج: الناتج يدخل للمخزون. بيانات المصدر القديمة نصية وقد لا تحمل كوداً ثابتاً،
        # لذلك نعرض الناتج المؤكد فقط بدلاً من اختلاق حركة خامة غير قابلة للإسناد.
        prod_params = [from_date, to_date]
        prod_branch = ""
        if branch_id:
            prod_branch = " AND p.branch_id=? "
            prod_params.append(branch_id)
        production = conn.execute(
            f"""
            SELECT p.id, p.branch_id, p.created_at, p.operation_type,
                   p.target_item_name, p.output_weight, p.unit_cost, p.notes
            FROM production_logs p
            WHERE DATE(p.created_at) BETWEEN ? AND ?
            {prod_branch}
            ORDER BY p.created_at
            """,
            tuple(prod_params)
        ).fetchall()
        for p in production:
            item = by_name_branch.get((p["branch_id"], str(p["target_item_name"])))
            add_move(
                p["created_at"], p["branch_id"], branch_names.get(p["branch_id"]),
                item["item_code"] if item else "", p["target_item_name"],
                f"إنتاج - {p['operation_type']}", float(p["output_weight"] or 0), 0,
                float(p["unit_cost"] or 0), f"إنتاج #{p['id']}", p["notes"]
            )

        if not movements:
            st.info("لا توجد حركات مطابقة للفترة والفرع والصنف المحدد.")
            return

        df = pd.DataFrame(movements)
        df["التاريخ والوقت"] = pd.to_datetime(df["التاريخ والوقت"], errors="coerce")
        df = df.sort_values(["التاريخ والوقت", "الفرع / المخزن", "الصنف"])

        total_in = df["وارد"].sum()
        total_out = df["صادر"].sum()
        net = total_in - total_out
        total_value = df["قيمة الحركة"].sum()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("إجمالي الوارد", f"{total_in:,.2f}")
        c2.metric("إجمالي الصادر", f"{total_out:,.2f}")
        c3.metric("صافي الحركة", f"{net:,.2f}")
        c4.metric("قيمة الحركات", f"{total_value:,.2f} د.ل")

        if not is_admin_or_supervisor:
            df = df.drop(
                columns=["متوسط / تكلفة الوحدة", "قيمة الحركة"],
                errors="ignore"
            )

        st.dataframe(
            df.sort_values("التاريخ والوقت", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "وارد": st.column_config.NumberColumn("وارد", format="%.2f"),
                "صادر": st.column_config.NumberColumn("صادر", format="%.2f"),
                "متوسط / تكلفة الوحدة": st.column_config.NumberColumn(
                    "متوسط / تكلفة الوحدة", format="%.2f د.ل"
                ),
                "قيمة الحركة": st.column_config.NumberColumn(
                    "قيمة الحركة", format="%.2f د.ل"
                ),
            }
        )

        excel_button(
            df,
            "📥 تحميل حركة الأصناف Excel",
            f"Item_Movement_{from_date}_to_{to_date}.xlsx",
            "Item_Movement",
            "item_movement_excel"
        )
    finally:
        conn.close()


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

    report_pages = [
        ("financial", "💰 الملخص المالي"),
        ("sales", "🧾 المبيعات"),
        ("purchases", "📥 المشتريات"),
        ("expenses", "💸 المصروفات"),
        ("revenues", "💵 الإيرادات"),
        ("adjustments", "✍️ الحركات اليدوية"),
        ("transfers", "🔄 التحويلات"),
        ("production", "🔥🥜 الخلط والتحميص"),
        ("inventory", "📦 المخزون والتكلفة"),
        ("item_movement", "📈 حركة الأصناف"),
    ]

    if "reports_page_mode" not in st.session_state:
        st.session_state["reports_page_mode"] = "financial"

    st.markdown("### 📊 اختر التقرير")

    for row_start in range(0, len(report_pages), 3):
        current = report_pages[row_start:row_start + 3]
        cols = st.columns(len(current))

        for idx, (page_key, page_label) in enumerate(current):
            if cols[idx].button(
                page_label,
                use_container_width=True,
                type="primary"
                if st.session_state["reports_page_mode"] == page_key
                else "secondary",
                key=f"reports_nav_{page_key}"
            ):
                st.session_state["reports_page_mode"] = page_key
                st.rerun()

    st.markdown("---")

    selected_report = st.session_state["reports_page_mode"]

    if selected_report == "financial":
        show_financial_summary(
            branches,
            is_admin_or_supervisor
        )

    elif selected_report == "sales":
        show_sales_report(
            branches,
            is_admin_or_supervisor
        )

    elif selected_report == "purchases":
        show_purchases_report(
            branches,
            is_admin_or_supervisor
        )

    elif selected_report == "expenses":
        show_expenses_report(
            branches,
            is_admin_or_supervisor
        )

    elif selected_report == "revenues":
        show_revenues_report(
            branches,
            is_admin_or_supervisor
        )

    elif selected_report == "adjustments":
        show_adjustments_report(
            branches,
            is_admin_or_supervisor
        )

    elif selected_report == "transfers":
        show_transfers_report(
            branches,
            is_admin_or_supervisor
        )

    elif selected_report == "production":
        show_production_report(
            branches,
            is_admin_or_supervisor
        )

    elif selected_report == "inventory":
        show_inventory_report(
            branches,
            is_admin_or_supervisor
        )

    elif selected_report == "item_movement":
        show_item_movement_report(
            branches,
            is_admin_or_supervisor
        )

