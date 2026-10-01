import streamlit as st
import pandas as pd
from datetime import date, datetime
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


def clean_unit(value):
    """توحيد اسم الوحدة القادمة من الملف."""
    text = clean_text(value).lower()

    piece_values = {
        "قطعة", "قطع", "piece", "pieces",
        "كرتون", "كرتونة", "قطعة / كرتون", "قطعة/كرتون"
    }
    kg_values = {
        "كجم", "كيلو", "كيلوجرام", "kg",
        "جرام", "وزن", "وزن (كجم / جرام)"
    }

    if text in piece_values:
        return "piece"

    if text in kg_values:
        return "kg"

    raise ValueError(
        f"الوحدة ({value}) غير معروفة. استخدم «قطعة» أو «كجم»."
    )


def clean_expiry(value):
    """تحويل تاريخ الصلاحية إلى DATE أو None."""
    if pd.isna(value) or clean_text(value) == "":
        return None

    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)

    if pd.isna(parsed):
        raise ValueError(
            f"تاريخ الصلاحية ({value}) غير صحيح."
        )

    return parsed.date()


def ensure_import_schema(conn):
    """تجهيز حقول الوحدات وجدول دفعات الصلاحية."""
    conn.execute(
        """
        ALTER TABLE items
        ADD COLUMN IF NOT EXISTS unit_type TEXT DEFAULT 'piece'
        """
    )
    conn.execute(
        """
        ALTER TABLE items
        ADD COLUMN IF NOT EXISTS pieces_per_carton INTEGER DEFAULT 1
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_batches
        (
            id BIGSERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL,
            branch_id INTEGER NOT NULL,
            quantity NUMERIC DEFAULT 0,
            remaining_quantity NUMERIC DEFAULT 0,
            received_date DATE DEFAULT CURRENT_DATE,
            expiry_date DATE,
            unit_cost NUMERIC DEFAULT 0,
            source_type TEXT DEFAULT 'inventory',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
            FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_inventory_batches_expiry
        ON inventory_batches(branch_id, expiry_date)
        """
    )


def add_import_batch(
    conn, item_id, branch_id, qty, buy_price, expiry_date,
    source_type="items_import"
):
    """إنشاء دفعة صلاحية فقط عند وجود تاريخ انتهاء وكمية موجبة."""
    if expiry_date is None or float(qty) <= 0:
        return

    conn.execute(
        """
        INSERT INTO inventory_batches
        (
            item_id, branch_id, quantity, remaining_quantity,
            received_date, expiry_date, unit_cost, source_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item_id,
            branch_id,
            float(qty),
            float(qty),
            date.today(),
            expiry_date,
            float(buy_price),
            source_type
        )
    )


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
            **أعمدة ملف الأصناف:**

            `كود الصنف` |
            `اسم الصنف` |
            `الوحدة` |
            `عدد القطع بالكرتون` |
            `سعر البيع` |
            `سعر الشراء` |
            `الكمية` |
            `تاريخ الصلاحية`

            **ملاحظات:**  
            - `الوحدة` تكون `قطعة` أو `كجم`.  
            - `عدد القطع بالكرتون` يستخدم لأصناف القطع، وللكيلو يمكن تركه فارغاً أو وضع `1`.  
            - `الكمية` هي الرصيد بالوحدة الأساسية: عدد القطع للصنف القطعي، أو عدد الكيلوجرامات للصنف الوزني.  
            - `تاريخ الصلاحية` اختياري، ويمكن تركه فارغاً.
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
                    "كود الصنف",
                    "اسم الصنف",
                    "الوحدة",
                    "عدد القطع بالكرتون",
                    "سعر البيع",
                    "سعر الشراء",
                    "الكمية",
                    "تاريخ الصلاحية"
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
                        ensure_import_schema(conn_imp)

                        success_count = 0
                        processed_rows = 0

                        for excel_index, row in df.iterrows():
                            excel_row = int(excel_index) + 2

                            code_value = clean_text(
                                row.get("كود الصنف", "")
                            )
                            name = clean_text(
                                row.get("اسم الصنف", "")
                            )

                            if not name:
                                raise ValueError(
                                    f"الصف {excel_row}: اسم الصنف فارغ."
                                )

                            if not code_value:
                                raise ValueError(
                                    f"الصف {excel_row}: كود الصنف فارغ."
                                )

                            unit_type = clean_unit(
                                row.get("الوحدة", "")
                            )

                            pieces_per_carton = int(
                                clean_number(
                                    row.get(
                                        "عدد القطع بالكرتون",
                                        1
                                    ),
                                    1
                                )
                            )

                            if unit_type == "piece":
                                if pieces_per_carton < 1:
                                    raise ValueError(
                                        f"الصف {excel_row}: عدد القطع "
                                        "بالكرتون يجب أن يكون 1 أو أكثر."
                                    )
                            else:
                                pieces_per_carton = 1

                            sale_p = clean_number(
                                row.get("سعر البيع", 0)
                            )
                            buy_p = clean_number(
                                row.get("سعر الشراء", 0)
                            )
                            qty = clean_number(
                                row.get("الكمية", 0)
                            )
                            expiry = clean_expiry(
                                row.get("تاريخ الصلاحية", "")
                            )

                            if sale_p < 0:
                                raise ValueError(
                                    f"الصف {excel_row}: سعر البيع سالب."
                                )

                            if buy_p < 0:
                                raise ValueError(
                                    f"الصف {excel_row}: سعر الشراء سالب."
                                )

                            if qty < 0:
                                raise ValueError(
                                    f"الصف {excel_row}: الكمية سالبة."
                                )

                            for b_id in target_branches:
                                existing = conn_imp.execute(
                                    """
                                    SELECT
                                        id, quantity, avg_cost,
                                        buy_price,
                                        COALESCE(
                                            unit_type,
                                            'piece'
                                        ) AS unit_type
                                    FROM items
                                    WHERE branch_id = ?
                                      AND (
                                            item_code = ?
                                            OR LOWER(TRIM(item_name))
                                               = LOWER(TRIM(?))
                                          )
                                    LIMIT 1
                                    FOR UPDATE
                                    """,
                                    (
                                        b_id,
                                        code_value,
                                        name
                                    )
                                ).fetchone()

                                if existing:
                                    stored_unit = (
                                        existing["unit_type"]
                                        or "piece"
                                    )

                                    if stored_unit != unit_type:
                                        raise ValueError(
                                            f"الصف {excel_row}: الصنف "
                                            f"({name}) موجود بوحدة مختلفة."
                                        )

                                    old_qty = float(
                                        existing["quantity"] or 0
                                    )
                                    old_avg = float(
                                        existing["avg_cost"] or 0
                                    )
                                    old_buy = float(
                                        existing["buy_price"] or 0
                                    )

                                    if old_avg <= 0:
                                        old_avg = old_buy

                                    new_qty = old_qty + float(qty)

                                    if new_qty > 0:
                                        new_avg = (
                                            (
                                                old_qty * old_avg
                                            )
                                            +
                                            (
                                                float(qty) * buy_p
                                            )
                                        ) / new_qty
                                    else:
                                        new_avg = buy_p

                                    conn_imp.execute(
                                        """
                                        UPDATE items
                                        SET
                                            quantity = ?,
                                            sale_price = ?,
                                            buy_price = ?,
                                            avg_cost = ?,
                                            unit_type = ?,
                                            pieces_per_carton = ?
                                        WHERE id = ?
                                        """,
                                        (
                                            new_qty,
                                            sale_p,
                                            buy_p,
                                            new_avg,
                                            unit_type,
                                            pieces_per_carton,
                                            existing["id"]
                                        )
                                    )

                                    item_id = existing["id"]

                                else:
                                    inserted = conn_imp.execute(
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
                                            unit_type,
                                            pieces_per_carton
                                        )
                                        VALUES
                                        (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                        RETURNING id
                                        """,
                                        (
                                            b_id,
                                            code_value,
                                            name,
                                            qty,
                                            buy_p,
                                            sale_p,
                                            buy_p,
                                            unit_type,
                                            pieces_per_carton
                                        )
                                    ).fetchone()

                                    item_id = inserted[0]

                                add_import_batch(
                                    conn_imp,
                                    item_id,
                                    b_id,
                                    qty,
                                    buy_p,
                                    expiry
                                )

                                success_count += 1

                            processed_rows += 1

                        conn_imp.commit()

                        st.success(
                            f"✅ تم اعتماد {processed_rows} صف "
                            f"وترحيل {success_count} سجل للفرع/الفروع "
                            "بنجاح، مع حفظ الوحدات ودفعات الصلاحية."
                        )

                    except Exception as e:
                        if conn_imp:
                            conn_imp.rollback()

                        st.error(
                            "❌ لم يتم استيراد الملف. "
                            "تم التراجع عن العملية بالكامل."
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

                m_unit_label = st.selectbox(
                    "الوحدة الأساسية:",
                    ["قطعة", "كجم"]
                )

                m_qty = st.number_input(
                    "الكمية الابتدائية:",
                    min_value=0.0,
                    value=0.0,
                    step=0.5
                )

            m_pieces_per_carton = 1

            if m_unit_label == "قطعة":
                m_pieces_per_carton = st.number_input(
                    "عدد القطع داخل الكرتون:",
                    min_value=1,
                    value=1,
                    step=1
                )

            m_has_expiry = st.checkbox(
                "له تاريخ انتهاء صلاحية"
            )

            m_expiry = None

            if m_has_expiry:
                m_expiry = st.date_input(
                    "تاريخ الصلاحية:",
                    value=date.today(),
                    min_value=date.today()
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
                    ensure_import_schema(conn_m)

                    m_unit_type = (
                        "piece"
                        if m_unit_label == "قطعة"
                        else "kg"
                    )

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

                        inserted = conn_m.execute(
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
                                unit_type,
                                pieces_per_carton
                            )
                            VALUES
                            (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            RETURNING id
                            """,
                            (
                                b_id,
                                m_code.strip(),
                                m_name.strip(),
                                m_qty,
                                m_buy,
                                m_sale,
                                m_buy,
                                m_unit_type,
                                int(m_pieces_per_carton)
                            )
                        ).fetchone()

                        add_import_batch(
                            conn_m,
                            inserted[0],
                            b_id,
                            m_qty,
                            m_buy,ث
                            m_expiry,
                            source_type="manual_item"
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
