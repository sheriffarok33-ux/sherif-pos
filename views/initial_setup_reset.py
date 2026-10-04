from ui_common import back_button
import streamlit as st
from database import get_db_connection


# الجداول التشغيلية التي سيتم تنظيفها فقط.
# لا نحذف الفروع أو المستخدمين أو الصلاحيات أو إعدادات القوائم.
RESET_TABLES = [
    "inventory_batches",
    "negative_sales_logs",
    "stock_adjustments",
    "production_logs",
    "transfer_logs",
    "purchases",
    "expenses",
    "revenues",
    "invoices",
    "activity_logs",
    "items",
]

PRESERVED_TABLES = [
    "branches",
    "users",
    "role_permissions",
    "custom_labels",
    "suppliers",
    "customers",
    "financial_year_archives",
    "financial_year_archive_rows",
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
    return bool(row and row[0])


def _count_rows(conn, table_name):
    if not _table_exists(conn, table_name):
        return None

    # الأسماء هنا ثابتة من RESET_TABLES وليست مدخلة من المستخدم.
    row = conn.execute(
        f'SELECT COUNT(*) FROM "{table_name}"'
    ).fetchone()
    return int(row[0] or 0)


def _reset_sequences(conn, table_names):
    for table_name in table_names:
        if not _table_exists(conn, table_name):
            continue

        # إعادة تسلسل id إن كان الجدول يستخدم sequence.
        seq = conn.execute(
            "SELECT pg_get_serial_sequence(?, 'id')",
            (f"public.{table_name}",)
        ).fetchone()

        if seq and seq[0]:
            conn.execute(
                f'ALTER SEQUENCE {seq[0]} RESTART WITH 1'
            )


def reset_startup_data():
    conn = None

    try:
        conn = get_db_connection()

        existing_tables = [
            table_name
            for table_name in RESET_TABLES
            if _table_exists(conn, table_name)
        ]

        if not existing_tables:
            raise RuntimeError(
                "لم يتم العثور على جداول تشغيلية للتصفير."
            )

        # DELETE بدلاً من TRUNCATE CASCADE حتى لا نمس أي جدول
        # غير موجود صراحة في القائمة.
        for table_name in existing_tables:
            conn.execute(
                f'DELETE FROM "{table_name}"'
            )

        _reset_sequences(conn, existing_tables)

        # إعادة أرصدة الموردين والعملاء إلى بداية نظيفة،
        # مع الإبقاء على بياناتهم الأساسية.
        if _table_exists(conn, "suppliers"):
            conn.execute(
                "UPDATE suppliers SET balance = 0"
            )

        if _table_exists(conn, "customers"):
            conn.execute(
                """
                UPDATE customers
                SET balance = 0,
                    total_purchases = 0
                """
            )

        conn.commit()
        return existing_tables

    except Exception:
        if conn:
            conn.rollback()
        raise

    finally:
        if conn:
            conn.close()


def show_page():
    back_button(key="back_initial_setup_reset")

    role = st.session_state.get("role", "")

    if role != "Admin":
        st.error("⛔ هذه الشاشة متاحة للمدير فقط.")
        return

    st.markdown("## 🧹 تهيئة النظام لأول تشغيل")

    st.warning(
        "هذه العملية مخصصة لبداية المشروع فقط. "
        "ستحذف بيانات التشغيل الحالية نهائياً، "
        "ولا تنشئ أرشيف سنة مالية."
    )

    st.success(
        "سيتم الإبقاء على الفروع والمستخدمين والصلاحيات "
        "وأسماء الموردين والعملاء. "
        "وسيتم تصفير أرصدة الموردين والعملاء."
    )

    st.markdown(
        """
        **سيتم حذف:**
        الأصناف والأرصدة، دفعات الصلاحية، المبيعات والفواتير،
        المشتريات، التحويلات، التسويات، الإنتاج،
        المصروفات، الإيرادات وسجل النشاط.
        """
    )

    conn = None

    try:
        conn = get_db_connection()

        preview = []
        for table_name in RESET_TABLES:
            count = _count_rows(conn, table_name)
            if count is not None:
                preview.append({
                    "الجدول": table_name,
                    "عدد السجلات الحالية": count
                })

        if preview:
            st.dataframe(
                preview,
                use_container_width=True,
                hide_index=True
            )

    except Exception as e:
        st.error("❌ تعذر قراءة حالة قاعدة البيانات.")
        st.code(str(e))
        return

    finally:
        if conn:
            conn.close()

    phrase = "تهيئة النظام من البداية"

    confirm_text = st.text_input(
        f"للتأكيد اكتب العبارة التالية: {phrase}"
    )

    confirm_check = st.checkbox(
        "أؤكد أن بيانات التشغيل الحالية تجريبية "
        "وأريد حذفها نهائياً."
    )

    disabled = (
        confirm_text.strip() != phrase
        or not confirm_check
    )

    if st.button(
        "🧹 تنفيذ التهيئة الكاملة",
        type="primary",
        use_container_width=True,
        disabled=disabled
    ):
        try:
            cleaned = reset_startup_data()

            st.success(
                "✅ تمت تهيئة بيانات التشغيل بنجاح. "
                "الفروع والمستخدمون والصلاحيات محفوظة."
            )

            st.info(
                "الخطوة التالية: افتح شاشة استيراد Excel "
                "وارفع ملف الأصناف الجديد بالوحدات "
                "وتواريخ الصلاحية."
            )

            st.caption(
                "الجداول التي تم تنظيفها: "
                + "، ".join(cleaned)
            )

        except Exception as e:
            st.error(
                "❌ فشلت التهيئة وتم التراجع عن العملية بالكامل."
            )
            st.code(str(e))
