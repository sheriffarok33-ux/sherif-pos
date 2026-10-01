import streamlit as st
import pandas as pd
from database import get_db_connection


def clean_text(value):
    """تنظيف القيم النصية القادمة من Excel / CSV."""
    if pd.isna(value):
        return ""
    return str(value).strip()


def clean_number(value, default=0.0):
    """تحويل القيم الرقمية بأمان."""
    if pd.isna(value) or value == "":
        return default

    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def show_page():

    st.header("📁 إدارة الأصناف: الاستيراد والإدخال اليدوي")

    st.info(
        "💡 قم برفع ملف Excel الخاص بالأصناف أو إضافتها "
        "يدوياً مع خيار تعميمها على كافة الفروع "
        "أو فرع محدد."
    )

    # ========================================================
    # تحميل الفروع
    # ========================================================

    conn = None

    try:
        conn = get_db_connection()

        branches = conn.execute(
            """
            SELECT id, branch_name
            FROM branches
            ORDER BY id ASC
            """
        ).fetchall()

    except Exception as e:

        st.error("❌ تعذر تحميل الفروع من قاعدة البيانات.")
        st.code(str(e))
        return

    finally:
        if conn:
            conn.close()

    if not branches:

        st.warning(
            "⚠️ يرجى إضافة فروع أولاً "
            "من شاشة إدارة الفروع."
        )

        return

    branch_dict = {
        b["branch_name"]: b["id"]
        for b in branches
    }

    # ========================================================
    # نطاق الترحيل
    # ========================================================

    st.markdown(
        "### 🎯 نطاق تطبيق الأصناف (الترحيل)"
    )

    target_mode = st.radio(
        "اختر طريقة توزيع الأصناف:",
        [
            "🌐 ترحيل لكافة الفروع والمخازن تلقائياً",
            "📍 فرع أو مخزن محدد (من القائمة المنسدلة)"
        ],
        horizontal=True
    )

    selected_branch_id = None

    if "فرع أو مخزن محدد" in target_mode:

        sel_b_name = st.selectbox(
            "اختر الفرع المستهدف من القائمة:",
            list(branch_dict.keys())
        )

        selected_branch_id = branch_dict[
            sel_b_name
        ]

    if "كافة الفروع" in target_mode:

        target_branches = [
            b["id"]
            for b in branches
        ]

    else:

        target_branches = [
            selected_branch_id
        ]

    st.markdown("---")

    # ========================================================
    # التبويبات
    # ========================================================

    tab1, tab2 = st.tabs([
        "📊 استيراد ملف أصناف (Excel / CSV)",
        "✍️ إدخال صنف جديد يدوياً"
    ])

    # ========================================================
    # استيراد Excel / CSV
    # ========================================================

    with tab1:

        st.subheader("📁 رفع ملف الأصناف")

        st.markdown(
            """
            **يجب أن يحتوي الملف على الأعمدة التالية:**

            `كود الصنف` |
            `اسم الصنف` |
            `سعر البيع` |
            `سعر الشراء` |
            `الكمية` |
            `تاريخ الصلاحية`
            """
        )

        uploaded_file = st.file_uploader(
            "اختر ملف Excel أو CSV",
            type=["xlsx", "csv"]
        )

        if uploaded_file is not None:

            try:

                if uploaded_file.name.lower().endswith(
                    ".csv"
                ):

                    df = pd.read_csv(
                        uploaded_file
                    )

                else:

                    df = pd.read_excel(
                        uploaded_file
                    )

                # ============================================
                # التأكد من الأعمدة الأساسية
                # ============================================

                required_columns = [
                    "اسم الصنف",
                    "سعر البيع",
                    "سعر الشراء",
                    "الكمية"
                ]

                missing_columns = [
                    col
                    for col in required_columns
                    if col not in df.columns
                ]

                if missing_columns:

                    st.error(
                        "❌ الملف يفتقد الأعمدة التالية:"
                    )

                    st.write(missing_columns)

                    return

                st.markdown(
                    "### 🔍 معاينة البيانات المستوردة:"
                )

                st.dataframe(
                    df.head(20),
                    use_container_width=True
                )

                import_clicked = st.button(
                    "🚀 اعتماد وترحيل الأصناف من الملف",
                    type="primary"
                )

                if import_clicked:

                    conn_imp = None

                    try:

                        conn_imp = get_db_connection()

                        success_count = 0

                        for _, row in df.iterrows():

                            code = clean_text(
                                row.get(
                                    "كود الصنف",
                                    ""
                                )
                            )

                            name = clean_text(
                                row.get(
                                    "اسم الصنف",
                                    ""
                                )
                            )

                            sale_p = clean_number(
                                row.get(
                                    "سعر البيع",
                                    0
                                )
                            )

                            buy_p = clean_number(
                                row.get(
                                    "سعر الشراء",
                                    0
                                )
                            )

                            qty = clean_number(
                                row.get(
                                    "الكمية",
                                    0
                                )
                            )

                            expiry = clean_text(
                                row.get(
                                    "تاريخ الصلاحية",
                                    ""
                                )
                            )

                            # تجاهل السطر بدون اسم
                            if not name:
                                continue

                            for b_id in target_branches:

                                # --------------------------------
                                # البحث عن الصنف
                                # --------------------------------

                                if code:

                                    existing = (
                                        conn_imp.execute(
                                            """
                                            SELECT id
                                            FROM items

                                            WHERE branch_id = ?

                                            AND (
                                                item_code = ?
                                                OR item_name = ?
                                            )

                                            LIMIT 1
                                            """,
                                            (
                                                b_id,
                                                code,
                                                name
                                            )
                                        ).fetchone()
                                    )

                                else:

                                    # لو الباركود فارغ
                                    # لا نقارن الباركود الفارغ
                                    existing = (
                                        conn_imp.execute(
                                            """
                                            SELECT id
                                            FROM items

                                            WHERE branch_id = ?
                                            AND item_name = ?

                                            LIMIT 1
                                            """,
                                            (
                                                b_id,
                                                name
                                            )
                                        ).fetchone()
                                    )

                                # --------------------------------
                                # تحديث الصنف الموجود
                                # --------------------------------

                                if existing:

                                    conn_imp.execute(
                                        """
                                        UPDATE items

                                        SET
                                            quantity =
                                                quantity + ?,

                                            sale_price = ?,

                                            buy_price = ?,

                                            expiry_date = ?

                                        WHERE id = ?
                                        """,
                                        (
                                            qty,
                                            sale_p,
                                            buy_p,
                                            expiry,
                                            existing["id"]
                                        )
                                    )

                                # --------------------------------
                                # إضافة صنف جديد
                                # --------------------------------

                                else:

                                    conn_imp.execute(
                                        """
                                        INSERT INTO items
                                        (
                                            branch_id,
                                            item_code,
                                            item_name,
                                            quantity,
                                            buy_price,
                                            sale_price,
                                            avg_cost,
                                            expiry_date
                                        )

                                        VALUES
                                        (?, ?, ?, ?, ?, ?, ?, ?)
                                        """,
                                        (
                                            b_id,
                                            code,
                                            name,
                                            qty,
                                            buy_p,
                                            sale_p,
                                            buy_p,
                                            expiry
                                        )
                                    )

                            success_count += 1

                        conn_imp.commit()

                        st.success(
                            f"✅ تمت معالجة وترحيل "
                            f"{success_count} صنف بنجاح."
                        )

                    except Exception as e:

                        if conn_imp:
                            conn_imp.rollback()

                        st.error(
                            "❌ حدث خطأ أثناء ترحيل "
                            "الأصناف إلى قاعدة البيانات."
                        )

                        st.code(str(e))

                    finally:

                        if conn_imp:
                            conn_imp.close()

            except Exception as e:

                st.error(
                    "❌ تعذر قراءة ملف Excel / CSV."
                )

                st.code(str(e))

    # ========================================================
    # إضافة صنف يدوي
    # ========================================================

    with tab2:

        st.subheader(
            "✍️ إضافة صنف جديد للنظام"
        )

        with st.form(
            "manual_item_form",
            clear_on_submit=True
        ):

            col1, col2 = st.columns(2)

            with col1:

                m_code = st.text_input(
                    "كود الصنف (الباركود):"
                )

                m_name = st.text_input(
                    "اسم الصنف *:"
                )

                m_buy = st.number_input(
                    "سعر الشراء (د.ل):",
                    min_value=0.0,
                    value=0.0,
                    step=0.5
                )

            with col2:

                m_sale = st.number_input(
                    "سعر البيع (د.ل):",
                    min_value=0.0,
                    value=0.0,
                    step=0.5
                )

                m_qty = st.number_input(
                    "الكمية الابتدائية:",
                    min_value=0.0,
                    value=0.0,
                    step=0.5
                )

                m_expiry = st.text_input(
                    "تاريخ الصلاحية (اختياري):",
                    value=""
                )

            if m_sale > 0 and m_buy > 0:

                profit_margin = (
                    m_sale - m_buy
                )

                profit_percent = (
                    profit_margin / m_buy
                ) * 100

                st.info(
                    f"📊 معاينة حسابية: "
                    f"هامش الربح للقطعة = "
                    f"**{profit_margin:.2f} د.ل** "
                    f"({profit_percent:.1f}%)"
                )

            submitted_manual = (
                st.form_submit_button(
                    "💾 حفظ وإضافة الصنف",
                    type="primary",
                    use_container_width=True
                )
            )

        # ====================================================
        # تنفيذ الحفظ اليدوي
        # ====================================================

        if submitted_manual:

            if not m_name.strip():

                st.warning(
                    "⚠️ اسم الصنف حقل إلزامي!"
                )

            elif m_sale <= 0:

                st.warning(
                    "⚠️ يجب إدخال سعر بيع أكبر من صفر."
                )

            else:

                conn_m = None

                try:

                    conn_m = get_db_connection()

                    for b_id in target_branches:

                        # منع تكرار نفس الصنف
                        if m_code.strip():

                            existing = (
                                conn_m.execute(
                                    """
                                    SELECT id
                                    FROM items

                                    WHERE branch_id = ?

                                    AND (
                                        item_code = ?
                                        OR item_name = ?
                                    )

                                    LIMIT 1
                                    """,
                                    (
                                        b_id,
                                        m_code.strip(),
                                        m_name.strip()
                                    )
                                ).fetchone()
                            )

                        else:

                            existing = (
                                conn_m.execute(
                                    """
                                    SELECT id
                                    FROM items

                                    WHERE branch_id = ?
                                    AND item_name = ?

                                    LIMIT 1
                                    """,
                                    (
                                        b_id,
                                        m_name.strip()
                                    )
                                ).fetchone()
                            )

                        if existing:

                            raise ValueError(
                                f"الصنف ({m_name.strip()}) "
                                "موجود بالفعل في أحد "
                                "الفروع المحددة."
                            )

                        conn_m.execute(
                            """
                            INSERT INTO items
                            (
                                branch_id,
                                item_code,
                                item_name,
                                quantity,
                                buy_price,
                                sale_price,
                                avg_cost,
                                expiry_date
                            )

                            VALUES
                            (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                b_id,
                                m_code.strip(),
                                m_name.strip(),
                                m_qty,
                                m_buy,
                                m_sale,
                                m_buy,
                                m_expiry.strip()
                            )
                        )

                    conn_m.commit()

                    st.success(
                        f"✅ تم إضافة الصنف "
                        f"({m_name.strip()}) "
                        "وتعميمه حسب النطاق المحدد."
                    )

                    st.rerun()

                except Exception as e:

                    if conn_m:
                        conn_m.rollback()

                    st.error(
                        "❌ لم يتم حفظ الصنف."
                    )

                    st.code(str(e))

                finally:

                    if conn_m:
                        conn_m.close()
