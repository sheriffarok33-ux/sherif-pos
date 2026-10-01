import streamlit as st
from datetime import datetime
from database import get_db_connection


# ============================================================
# الجداول التي يتم تصفير حركاتها عند بدء سنة مالية جديدة
# ============================================================

RESET_TABLES = [
    ("negative_sales_logs", "سجل البيع بالسالب"),
    ("stock_adjustments", "حركات التوالف والفائض والتعديلات"),
    ("production_logs", "عمليات التحميص والخلط"),
    ("transfer_logs", "تحويلات وتزويد الفروع"),
    ("purchases", "المشتريات"),
    ("expenses", "المصروفات"),
    ("revenues", "الإيرادات"),
    ("invoices", "فواتير المبيعات"),
]

KEEP_DATA = [
    "الأصناف وكمياتها الحالية وأسعارها",
    "الفروع",
    "المستخدمون",
    "الصلاحيات وإعدادات القوائم",
    "الموردون والعملاء وأرصدتهم الحالية",
]


def _table_exists(conn, table_name):
    row = conn.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ?
        )
        """,
        (table_name,)
    ).fetchone()

    return bool(row[0]) if row else False


def _count_rows(conn, table_name):
    # table_name يأتي حصراً من RESET_TABLES الثابتة أعلاه
    row = conn.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def get_reset_summary():
    conn = None
    try:
        conn = get_db_connection()
        result = []

        for table_name, label in RESET_TABLES:
            if _table_exists(conn, table_name):
                count = _count_rows(conn, table_name)
                result.append((table_name, label, count))

        return result
    finally:
        if conn:
            conn.close()


def perform_annual_reset():
    conn = None

    try:
        conn = get_db_connection()

        # كل العملية Transaction واحدة:
        # أي خطأ = rollback وعدم تنفيذ تصفير جزئي.
        existing_tables = [
            table_name
            for table_name, _ in RESET_TABLES
            if _table_exists(conn, table_name)
        ]

        for table_name in existing_tables:
            conn.execute(f"DELETE FROM {table_name}")

        conn.commit()
        return True, None

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass

        return False, str(e)

    finally:
        if conn:
            conn.close()


def show_page():
    st.markdown("## ⚙️ الجرد والتصفير السنوي")

    role = st.session_state.get("role", "")

    if role != "Admin":
        st.error("🔒 هذه العملية متاحة للمدير Admin فقط.")
        return

    st.error(
        "⚠️ هذه شاشة إقفال السنة المالية وبدء سنة جديدة. "
        "التنفيذ يحذف الحركات المالية والتشغيلية القديمة نهائياً "
        "من قاعدة البيانات، ولا يمكن التراجع عنه من داخل البرنامج."
    )

    st.info(
        "✅ لن يتم تصفير المخزون. ستظل الأصناف وكمياتها الحالية "
        "والفروع والمستخدمون محفوظة كما هي."
    )

    st.markdown("### ✅ بيانات ستبقى محفوظة")

    for item in KEEP_DATA:
        st.write(f"• {item}")

    st.markdown("### 🗑️ بيانات سيتم تصفيرها")

    try:
        summary = get_reset_summary()
    except Exception as e:
        st.error("تعذر قراءة بيانات قاعدة البيانات.")
        st.code(str(e))
        return

    total_rows = 0

    if summary:
        for _, label, count in summary:
            total_rows += count
            st.write(f"• {label}: **{count:,}** سجل")
    else:
        st.info("لا توجد جداول تشغيلية متاحة للتصفير.")

    st.metric("إجمالي السجلات التي سيتم حذفها", f"{total_rows:,}")

    st.warning(
        "💡 أرصدة الموردين والعملاء لن يتم تصفيرها، لأنها قد تمثل "
        "ديوناً أو مستحقات تنتقل كرصد افتتاحي للسنة الجديدة."
    )

    st.markdown("---")
    st.markdown("### 🔐 تأكيد العملية")

    current_year = datetime.now().year

    st.caption(
        f"للتنفيذ اكتب العبارة التالية حرفياً: "
        f"تأكيد التصفير السنوي {current_year}"
    )

    confirmation = st.text_input(
        "عبارة التأكيد:",
        key="annual_reset_confirmation"
    )

    acknowledge = st.checkbox(
        "أؤكد أنني راجعت البيانات وأفهم أن الحركات القديمة سيتم حذفها.",
        key="annual_reset_ack"
    )

    expected_text = f"تأكيد التصفير السنوي {current_year}"

    can_reset = (
        confirmation.strip() == expected_text
        and acknowledge
        and total_rows > 0
    )

    if st.button(
        "🚨 تنفيذ التصفير السنوي وبدء سنة مالية جديدة",
        type="primary",
        disabled=not can_reset,
        use_container_width=True,
        key="annual_reset_execute"
    ):
        with st.spinner("جاري تنفيذ التصفير السنوي..."):
            success, error = perform_annual_reset()

        if success:
            st.success(
                "✅ تم تصفير الحركات السنوية بنجاح. "
                "الأصناف وكمياتها والفروع والمستخدمون لم تتغير."
            )

            st.session_state["annual_reset_confirmation"] = ""
            st.session_state["annual_reset_ack"] = False

            st.rerun()

        else:
            st.error(
                "❌ لم يتم تنفيذ التصفير. تم التراجع عن العملية "
                "ولم يتم اعتماد حذف جزئي."
            )
            if error:
                st.code(error)
