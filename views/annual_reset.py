import json
import streamlit as st
from datetime import datetime
from database import get_db_connection


# ============================================================
# إقفال وأرشفة السنة المالية
# ============================================================

# ترتيب الحذف مهم لتقليل مشاكل العلاقات بين الجداول.
ARCHIVE_TABLES = [
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
    "المستخدمون والصلاحيات",
    "الموردون وأرصدتهم الحالية",
    "العملاء وأرصدتهم الحالية",
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
    row = conn.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _json_value(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _row_to_dict(cursor, row):
    columns = [desc[0] for desc in cursor.description]
    return {
        col: _json_value(row[col])
        for col in columns
    }


def get_reset_summary():
    conn = None
    try:
        conn = get_db_connection()
        result = []
        for table_name, label in ARCHIVE_TABLES:
            if _table_exists(conn, table_name):
                result.append(
                    (table_name, label, _count_rows(conn, table_name))
                )
        return result
    finally:
        if conn:
            conn.close()


def get_archived_years():
    conn = None
    try:
        conn = get_db_connection()
        if not _table_exists(conn, "financial_year_archives"):
            return []
        return conn.execute(
            """
            SELECT
                financial_year,
                closed_at,
                closed_by_username,
                summary_json
            FROM financial_year_archives
            ORDER BY financial_year DESC
            """
        ).fetchall()
    finally:
        if conn:
            conn.close()


def archive_and_reset(financial_year, user_id, username):
    conn = None
    try:
        conn = get_db_connection()

        # منع إقفال نفس السنة مرتين.
        exists = conn.execute(
            """
            SELECT id
            FROM financial_year_archives
            WHERE financial_year = ?
            FOR UPDATE
            """,
            (financial_year,)
        ).fetchone()

        if exists:
            raise ValueError(
                f"السنة المالية {financial_year} مؤرشفة بالفعل."
            )

        summary = {}
        table_rows = {}

        # نقرأ كل البيانات أولاً قبل أي DELETE.
        for table_name, label in ARCHIVE_TABLES:
            if not _table_exists(conn, table_name):
                continue

            cursor = conn.execute(
                f"SELECT * FROM {table_name} ORDER BY id ASC"
            )
            rows = cursor.fetchall()

            converted = [
                _row_to_dict(cursor, row)
                for row in rows
            ]

            table_rows[table_name] = converted
            summary[table_name] = {
                "label": label,
                "rows": len(converted),
            }

        # إنشاء رأس الأرشيف.
        archive_cursor = conn.execute(
            """
            INSERT INTO financial_year_archives
            (
                financial_year,
                closed_by,
                closed_by_username,
                summary_json
            )
            VALUES (?, ?, ?, ?)
            RETURNING id
            """,
            (
                financial_year,
                user_id,
                username,
                json.dumps(summary, ensure_ascii=False)
            )
        )

        archive_id = archive_cursor.fetchone()[0]

        # حفظ نسخة JSON كاملة لكل سجل.
        archived_counts = {}

        for table_name, rows in table_rows.items():
            archived_counts[table_name] = 0

            for row_data in rows:
                source_row_id = row_data.get("id")

                conn.execute(
                    """
                    INSERT INTO financial_year_archive_rows
                    (
                        archive_id,
                        source_table,
                        source_row_id,
                        row_data
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        archive_id,
                        table_name,
                        (
                            str(source_row_id)
                            if source_row_id is not None
                            else None
                        ),
                        json.dumps(
                            row_data,
                            ensure_ascii=False,
                            default=str
                        )
                    )
                )
                archived_counts[table_name] += 1

        # تحقق قبل الحذف: عدد المؤرشف = عدد المصدر.
        for table_name, rows in table_rows.items():
            if archived_counts.get(table_name, 0) != len(rows):
                raise RuntimeError(
                    f"فشل التحقق من أرشفة جدول {table_name}."
                )

        # لا يبدأ الحذف إلا بعد نجاح الأرشفة والتحقق.
        for table_name, _ in ARCHIVE_TABLES:
            if table_name in table_rows:
                conn.execute(f"DELETE FROM {table_name}")

        conn.commit()
        return True, archive_id, summary, None

    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        return False, None, None, str(e)

    finally:
        if conn:
            conn.close()


def show_page():
    st.markdown("## ⚙️ إقفال وأرشفة السنة المالية")

    role = st.session_state.get("role", "")

    if role != "Admin":
        st.error("🔒 إقفال السنة المالية متاح للمدير Admin فقط.")
        return

    st.info(
        "📚 عند التنفيذ يتم أولاً حفظ نسخة كاملة من الحركات "
        "في أرشيف السنوات المالية داخل قاعدة البيانات، ثم يتم "
        "التحقق من الأرشيف، وبعدها فقط يتم تصفير حركات السنة الحالية."
    )

    st.success(
        "✅ الأصناف وكمياتها وأسعارها والفروع والمستخدمون "
        "وأرصدة الموردين والعملاء لن يتم حذفها."
    )

    st.markdown("### البيانات التي ستبقى")
    for item in KEEP_DATA:
        st.write(f"• {item}")

    try:
        summary = get_reset_summary()
        archived_years = get_archived_years()
    except Exception as e:
        st.error("تعذر قراءة بيانات الإقفال السنوي.")
        st.code(str(e))
        return

    st.markdown("### الحركات التي ستتم أرشفتها ثم تصفيرها")

    total_rows = 0
    for _, label, count in summary:
        total_rows += count
        st.write(f"• {label}: **{count:,}** سجل")

    st.metric(
        "إجمالي السجلات التي ستدخل الأرشيف",
        f"{total_rows:,}"
    )

    if archived_years:
        st.markdown("### 📁 السنوات المؤرشفة")
        for row in archived_years:
            closed_by = row["closed_by_username"] or "غير محدد"
            st.write(
                f"• سنة **{row['financial_year']}** — "
                f"أغلقت بواسطة **{closed_by}** — "
                f"{row['closed_at']}"
            )

    st.markdown("---")
    st.markdown("### 🔐 تأكيد إقفال السنة")

    default_year = datetime.now().year

    financial_year = st.number_input(
        "السنة المالية المراد إقفالها:",
        min_value=2000,
        max_value=2100,
        value=default_year,
        step=1,
        key="annual_close_year"
    )

    expected = f"إقفال السنة {int(financial_year)}"

    st.warning(
        f"للتنفيذ اكتب العبارة التالية حرفياً: {expected}"
    )

    confirmation = st.text_input(
        "عبارة التأكيد:",
        key="annual_close_confirmation"
    )

    acknowledge = st.checkbox(
        "أؤكد أنني راجعت السنة المختارة وأوافق على أرشفة "
        "الحركات ثم تصفيرها لبدء سنة مالية جديدة.",
        key="annual_close_ack"
    )

    can_close = (
        total_rows > 0
        and confirmation.strip() == expected
        and acknowledge
    )

    if st.button(
        "📚 أرشفة السنة ثم بدء سنة مالية جديدة",
        type="primary",
        disabled=not can_close,
        use_container_width=True,
        key="annual_close_execute"
    ):
        with st.spinner(
            "جاري الأرشفة والتحقق ثم التصفير..."
        ):
            success, archive_id, saved_summary, error = (
                archive_and_reset(
                    int(financial_year),
                    st.session_state.get("user_id"),
                    st.session_state.get("username", "")
                )
            )

        if success:
            st.success(
                f"✅ تم إقفال وأرشفة السنة المالية "
                f"{int(financial_year)} بنجاح. "
                f"رقم الأرشيف: {archive_id}"
            )
            st.balloons()
            st.rerun()
        else:
            st.error(
                "❌ لم يتم إقفال السنة. تم تنفيذ Rollback "
                "ولم يتم اعتماد أرشفة أو حذف جزئي."
            )
            if error:
                st.code(error)
