import streamlit as st
import pandas as pd
import io
from datetime import datetime, date, timedelta
from database import get_db_connection


# ============================================================
# Excel
# ============================================================

def to_excel(df):

    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        df.to_excel(
            writer,
            index=False,
            sheet_name="Transfers_Archive"
        )

    return output.getvalue()


# ============================================================
# تحميل الفروع والمخزن الرئيسي
# ============================================================

def get_branches_and_warehouse():

    conn = None

    try:

        conn = get_db_connection()

        branches = conn.execute(
            """
            SELECT
                id,
                branch_name,
                branch_type
            FROM branches
            ORDER BY id ASC
            """
        ).fetchall()

        warehouse = conn.execute(
            """
            SELECT
                id,
                branch_name
            FROM branches
            WHERE branch_type = 'مخزن'
            ORDER BY id ASC
            LIMIT 1
            """
        ).fetchone()

        return branches, warehouse

    finally:

        if conn:
            conn.close()


# ============================================================
# أصناف المخزن
# ============================================================

def get_warehouse_items(warehouse_id):

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
                sale_price,
                buy_price,
                avg_cost
            FROM items
            WHERE branch_id = ?
              AND quantity > 0
            ORDER BY item_name ASC
            """,
            (warehouse_id,)
        ).fetchall()

    finally:

        if conn:
            conn.close()


# ============================================================
# تنفيذ فاتورة التزويد
# ============================================================

def execute_transfer(
    warehouse_id,
    target_branch_id,
    target_branch_name,
    transfer_cart,
    transfer_notes,
    username
):

    conn = None

    try:

        if not transfer_cart:
            raise ValueError(
                "فاتورة التزويد فارغة."
            )

        if warehouse_id == target_branch_id:
            raise ValueError(
                "لا يمكن التزويد من المخزن "
                "إلى نفس المخزن."
            )

        conn = get_db_connection()

        # ====================================================
        # التأكد من الفرع المستهدف
        # ====================================================

        target_branch = conn.execute(
            """
            SELECT
                id,
                branch_name
            FROM branches
            WHERE id = ?
            """,
            (target_branch_id,)
        ).fetchone()

        if not target_branch:

            raise ValueError(
                "الفرع المستهدف غير موجود."
            )

        # ====================================================
        # دمج أي صنف مكرر في السلة
        # ====================================================

        merged_cart = {}

        for cart_item in transfer_cart:

            item_id = int(
                cart_item["id"]
            )

            qty = float(
                cart_item["qty"]
            )

            if qty <= 0:

                raise ValueError(
                    f"كمية الصنف "
                    f"({cart_item['name']}) "
                    "غير صحيحة."
                )

            if item_id not in merged_cart:

                merged_cart[item_id] = {
                    "id": item_id,
                    "code": cart_item["code"],
                    "name": cart_item["name"],
                    "qty": 0.0
                }

            merged_cart[
                item_id
            ]["qty"] += qty

        items_summary = []

        # ====================================================
        # قفل وفحص كل أصناف المخزن أولاً
        # ====================================================

        for cart_item in merged_cart.values():

            warehouse_item = conn.execute(
                """
                SELECT
                    id,
                    branch_id,
                    item_code,
                    item_name,
                    quantity,
                    buy_price,
                    sale_price,
                    avg_cost
                FROM items
                WHERE id = ?
                  AND branch_id = ?
                FOR UPDATE
                """,
                (
                    cart_item["id"],
                    warehouse_id
                )
            ).fetchone()

            if not warehouse_item:

                raise ValueError(
                    f"الصنف "
                    f"({cart_item['name']}) "
                    "غير موجود بالمخزن الرئيسي."
                )

            available_qty = float(
                warehouse_item[
                    "quantity"
                ] or 0
            )

            required_qty = float(
                cart_item["qty"]
            )

            if required_qty > available_qty:

                raise ValueError(
                    f"الكمية غير كافية من "
                    f"({warehouse_item['item_name']}). "
                    f"المتاح "
                    f"{available_qty:,.2f} "
                    f"والمطلوب "
                    f"{required_qty:,.2f}."
                )

            cart_item[
                "warehouse_data"
            ] = warehouse_item

        # ====================================================
        # تنفيذ النقل
        # ====================================================

        for cart_item in merged_cart.values():

            source = cart_item[
                "warehouse_data"
            ]

            qty = float(
                cart_item["qty"]
            )

            # -----------------------------------------------
            # خصم المخزن
            # -----------------------------------------------

            conn.execute(
                """
                UPDATE items
                SET quantity = quantity - ?
                WHERE id = ?
                  AND branch_id = ?
                """,
                (
                    qty,
                    source["id"],
                    warehouse_id
                )
            )

            # -----------------------------------------------
            # البحث في الفرع بالكود أولاً
            # -----------------------------------------------

            target_item = None

            if source["item_code"]:

                target_item = conn.execute(
                    """
                    SELECT
                        id,
                        quantity
                    FROM items
                    WHERE branch_id = ?
                      AND item_code = ?
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (
                        target_branch_id,
                        source["item_code"]
                    )
                ).fetchone()

            # -----------------------------------------------
            # fallback بالاسم للأصناف القديمة
            # -----------------------------------------------

            if not target_item:

                target_item = conn.execute(
                    """
                    SELECT
                        id,
                        quantity
                    FROM items
                    WHERE branch_id = ?
                      AND item_name = ?
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (
                        target_branch_id,
                        source["item_name"]
                    )
                ).fetchone()

            # -----------------------------------------------
            # الصنف موجود في الفرع
            # -----------------------------------------------

            if target_item:

                conn.execute(
                    """
                    UPDATE items
                    SET
                        avg_cost =
                            CASE
                                WHEN (quantity + ?) > 0
                                THEN (
                                    (quantity * COALESCE(avg_cost, buy_price, 0))
                                    + (? * ?)
                                ) / (quantity + ?)
                                ELSE ?
                            END,
                        quantity = quantity + ?,
                        buy_price = ?,
                        sale_price = ?
                    WHERE id = ?
                    """,
                    (
                        qty,
                        qty,
                        float(source["avg_cost"] or source["buy_price"] or 0),
                        qty,
                        float(source["avg_cost"] or source["buy_price"] or 0),
                        qty,
                        float(source["buy_price"] or 0),
                        float(source["sale_price"] or 0),
                        target_item["id"]
                    )
                )

            # -----------------------------------------------
            # الصنف غير موجود في الفرع
            # -----------------------------------------------

            else:

                conn.execute(
                    """
                    INSERT INTO items
                    (
                        branch_id,
                        item_code,
                        item_name,
                        quantity,
                        buy_price,
                        sale_price,
                        avg_cost
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        target_branch_id,
                        source["item_code"],
                        source["item_name"],
                        qty,
                        float(
                            source[
                                "buy_price"
                            ] or 0
                        ),
                        float(
                            source[
                                "sale_price"
                            ] or 0
                        ),
                        float(
                            source[
                                "avg_cost"
                            ] or
                            source[
                                "buy_price"
                            ] or 0
                        )
                    )
                )

            items_summary.append(
                (
                    f"▪ {source['item_name']} "
                    f"[{source['item_code']}] "
                    f"(الكمية: {qty:,.2f})"
                )
            )

        # ====================================================
        # تفاصيل الفاتورة
        # ====================================================

        items_details = "\n".join(
            items_summary
        )

        if transfer_notes.strip():

            items_details += (
                "\nملاحظات: "
                + transfer_notes.strip()
            )

        if username:

            items_details += (
                f"\nبواسطة: {username}"
            )

        # ====================================================
        # تسجيل فاتورة التزويد
        # ====================================================

        conn.execute(
            """
            INSERT INTO transfer_logs
            (
                from_branch_id,
                to_branch_id,
                transfer_type,
                items_details,
                status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                warehouse_id,
                target_branch_id,
                "فاتورة تزويد مجمعة",
                items_details,
                "بانتظار تأكيد الكاشير"
            )
        )

        conn.commit()

        st.session_state[
            "transfer_cart"
        ] = []

        st.session_state.pop(
            "transfer_target_branch",
            None
        )

        st.success(
            f"✅ تم ترحيل فاتورة التزويد "
            f"إلى ({target_branch_name}) "
            "بنجاح."
        )

        st.rerun()

    except ValueError as e:

        if conn:
            conn.rollback()

        st.warning(
            f"⚠️ {e}"
        )

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ حدث خطأ أثناء ترحيل "
            "فاتورة التزويد."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# تحميل أرشيف التحويلات
# ============================================================

def load_transfer_archive(
    from_date,
    to_date,
    target_branch_id=None
):

    conn = None

    try:

        conn = get_db_connection()

        params = [
            from_date,
            to_date
        ]

        branch_sql = ""

        if target_branch_id:

            branch_sql = (
                " AND t.to_branch_id = ? "
            )

            params.append(
                target_branch_id
            )

        cursor = conn.execute(
            f"""
            SELECT
                t.id
                    AS "رقم الفاتورة",

                b1.branch_name
                    AS "المرسل",

                b2.branch_name
                    AS "المستهدف",

                t.items_details
                    AS "تفاصيل الأصناف والكميات",

                t.status
                    AS "الحالة",

                t.transfer_date
                    AS "تاريخ الإصدار"

            FROM transfer_logs t

            LEFT JOIN branches b1
                ON t.from_branch_id = b1.id

            LEFT JOIN branches b2
                ON t.to_branch_id = b2.id

            WHERE DATE(t.transfer_date)
                  BETWEEN ? AND ?

            {branch_sql}

            ORDER BY
                t.transfer_date DESC,
                t.id DESC
            """,
            tuple(params)
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
# الصفحة
# ============================================================

def show_page():

    st.markdown(
        """
        <style>

        .dataframe-container td,
        .dataframe-container th {
            white-space: pre-wrap !important;
            word-wrap: break-word !important;
        }

        .rtl-container {
            direction: rtl !important;
            text-align: right !important;
        }

        </style>
        """,
        unsafe_allow_html=True
    )

    st.header(
        "🔄 نظام تزويد الفروع والأرشيف"
    )

    st.info(
        "💡 إنشاء فاتورة تزويد مجمعة "
        "من المخزن الرئيسي إلى الفروع، "
        "مع أرشيف كامل وفلترة بالتاريخ."
    )

    username = st.session_state.get(
        "username",
        "غير محدد"
    )

    if (
        "transfer_cart"
        not in st.session_state
    ):

        st.session_state[
            "transfer_cart"
        ] = []

    # ========================================================
    # تحميل الفروع
    # ========================================================

    try:

        branches, warehouse = (
            get_branches_and_warehouse()
        )

    except Exception as e:

        st.error(
            "❌ تعذر تحميل بيانات الفروع."
        )

        st.code(str(e))

        return

    if not branches:

        st.warning(
            "⚠️ يرجى إضافة الفروع "
            "والمخزن أولاً."
        )

        return

    if not warehouse:

        st.warning(
            "⚠️ لا يوجد مخزن رئيسي "
            "معرف في النظام."
        )

        return

    warehouse_id = warehouse["id"]
    warehouse_name = (
        warehouse["branch_name"]
    )

    target_branches = [
        b
        for b in branches
        if b["id"] != warehouse_id
    ]

    if not target_branches:

        st.warning(
            "⚠️ لا يوجد فرع متاح "
            "لإرسال التزويد إليه."
        )

        return

    branch_dict = {
        b["branch_name"]: b["id"]
        for b in target_branches
    }

    if "transfers_mode" not in st.session_state:
        st.session_state["transfers_mode"] = "new"

    st.markdown("### 🎯 اختر العملية")
    nav1, nav2 = st.columns(2)

    if nav1.button(
        "📦 إنشاء فاتورة تزويد جديدة",
        use_container_width=True,
        type="primary" if st.session_state["transfers_mode"] == "new" else "secondary",
        key="transfers_btn_new"
    ):
        st.session_state["transfers_mode"] = "new"
        st.rerun()

    if nav2.button(
        "📋 الأرشيف وإعادة الطباعة",
        use_container_width=True,
        type="primary" if st.session_state["transfers_mode"] == "archive" else "secondary",
        key="transfers_btn_archive"
    ):
        st.session_state["transfers_mode"] = "archive"
        st.rerun()

    transfer_mode = (
        "📦 إنشاء فاتورة تزويد جديدة"
        if st.session_state["transfers_mode"] == "new"
        else "📋 أرشيف فواتير التزويد وإعادة الطباعة"
    )

    st.markdown("---")

    # ========================================================
    # إنشاء فاتورة
    # ========================================================

    if transfer_mode.startswith("📦"):

        c1, c2 = st.columns(2)

        target_branch_name = (
            c1.selectbox(
                "اختر الفرع المستهدف:",
                list(
                    branch_dict.keys()
                )
            )
        )

        target_branch_id = (
            branch_dict[
                target_branch_name
            ]
        )

        transfer_notes = (
            c2.text_input(
                "ملاحظات الفاتورة:",
                value=""
            )
        )

        st.caption(
            f"📤 التزويد من: "
            f"{warehouse_name}"
        )

        # ====================================================
        # تثبيت الفرع للسلة
        # ====================================================

        if st.session_state[
            "transfer_cart"
        ]:

            cart_target = (
                st.session_state.get(
                    "transfer_target_branch"
                )
            )

            if (
                cart_target
                != target_branch_id
            ):

                st.warning(
                    "⚠️ السلة الحالية مرتبطة "
                    "بفرع مختلف. أكمل الفاتورة "
                    "أو قم بتفريغها قبل تغيير "
                    "الفرع المستهدف."
                )

                if st.button(
                    "🗑️ تفريغ السلة "
                    "والبدء للفرع الجديد"
                ):

                    st.session_state[
                        "transfer_cart"
                    ] = []

                    st.session_state.pop(
                        "transfer_target_branch",
                        None
                    )

                    st.rerun()

                return

        # ====================================================
        # أصناف المخزن
        # ====================================================

        try:

            warehouse_items = (
                get_warehouse_items(
                    warehouse_id
                )
            )

        except Exception as e:

            st.error(
                "❌ تعذر تحميل أصناف المخزن."
            )

            st.code(str(e))

            return

        st.markdown(
            "### 🛒 إضافة أصناف "
            "لفاتورة التزويد"
        )

        if warehouse_items:

            item_options = {}

            for item in warehouse_items:

                label = (
                    f"[{item['item_code']}] "
                    f"{item['item_name']} "
                    f"| المتوفر: "
                    f"{float(item['quantity'] or 0):,.2f}"
                )

                item_options[
                    label
                ] = item

            with st.form(
                "add_transfer_item",
                clear_on_submit=True
            ):

                ci1, ci2 = st.columns(
                    [3, 1]
                )

                selected_label = (
                    ci1.selectbox(
                        "اختر الصنف:",
                        list(
                            item_options.keys()
                        )
                    )
                )

                selected_item = (
                    item_options[
                        selected_label
                    ]
                )

                max_qty = float(
                    selected_item[
                        "quantity"
                    ] or 0
                )

                transfer_qty = (
                    ci2.number_input(
                        "الكمية:",
                        min_value=0.01,
                        max_value=max_qty,
                        value=min(
                            1.0,
                            max_qty
                        ),
                        step=1.0
                    )
                )

                add_btn = (
                    st.form_submit_button(
                        "➕ إضافة للسلة",
                        type="primary"
                    )
                )

            if add_btn:

                existing = None

                for cart_item in (
                    st.session_state[
                        "transfer_cart"
                    ]
                ):

                    if (
                        cart_item["id"]
                        == selected_item["id"]
                    ):

                        existing = cart_item
                        break

                if existing:

                    new_qty = (
                        float(
                            existing["qty"]
                        )
                        + float(
                            transfer_qty
                        )
                    )

                    if new_qty > max_qty:

                        st.warning(
                            f"⚠️ إجمالي الكمية "
                            f"المطلوبة أكبر من "
                            f"المتوفر "
                            f"({max_qty:,.2f})."
                        )

                    else:

                        existing[
                            "qty"
                        ] = new_qty

                        st.rerun()

                else:

                    st.session_state[
                        "transfer_cart"
                    ].append(
                        {
                            "id":
                                selected_item[
                                    "id"
                                ],

                            "code":
                                selected_item[
                                    "item_code"
                                ],

                            "name":
                                selected_item[
                                    "item_name"
                                ],

                            "qty":
                                float(
                                    transfer_qty
                                )
                        }
                    )

                    st.session_state[
                        "transfer_target_branch"
                    ] = target_branch_id

                    st.rerun()

        else:

            st.warning(
                f"⚠️ المخزن الرئيسي "
                f"({warehouse_name}) "
                "لا يحتوي على رصيد متاح."
            )

        # ====================================================
        # عرض السلة
        # ====================================================

        st.markdown(
            "### 📋 فاتورة التزويد الحالية"
        )

        if st.session_state[
            "transfer_cart"
        ]:

            total_units = 0.0

            for index, cart_item in enumerate(
                st.session_state[
                    "transfer_cart"
                ]
            ):

                total_units += float(
                    cart_item["qty"]
                )

                c1, c2, c3 = st.columns(
                    [3, 2, 1]
                )

                c1.write(
                    f"🏷️ "
                    f"{cart_item['name']} "
                    f"[{cart_item['code']}]"
                )

                c2.write(
                    f"الكمية: "
                    f"{cart_item['qty']:,.2f}"
                )

                if c3.button(
                    "🗑️ حذف",
                    key=(
                        f"del_transfer_"
                        f"{index}"
                    )
                ):

                    st.session_state[
                        "transfer_cart"
                    ].pop(index)

                    if not st.session_state[
                        "transfer_cart"
                    ]:

                        st.session_state.pop(
                            "transfer_target_branch",
                            None
                        )

                    st.rerun()

            st.metric(
                "📦 إجمالي الوحدات المحولة",
                f"{total_units:,.2f}"
            )

            st.markdown("---")

            ca1, ca2 = st.columns(2)

            confirm_transfer = (
                ca1.button(
                    "🚀 اعتماد وترحيل "
                    "فاتورة التزويد",
                    type="primary",
                    use_container_width=True
                )
            )

            clear_transfer = (
                ca2.button(
                    "🗑️ تفريغ السلة بالكامل",
                    use_container_width=True
                )
            )

            if clear_transfer:

                st.session_state[
                    "transfer_cart"
                ] = []

                st.session_state.pop(
                    "transfer_target_branch",
                    None
                )

                st.rerun()

            if confirm_transfer:

                execute_transfer(
                    warehouse_id=warehouse_id,
                    target_branch_id=(
                        target_branch_id
                    ),
                    target_branch_name=(
                        target_branch_name
                    ),
                    transfer_cart=(
                        st.session_state[
                            "transfer_cart"
                        ]
                    ),
                    transfer_notes=(
                        transfer_notes
                    ),
                    username=username
                )

        else:

            st.info(
                "🛒 السلة فارغة."
            )

    # ========================================================
    # الأرشيف
    # ========================================================

    else:

        st.subheader(
            "📋 أرشيف فواتير التزويد"
        )

        fc1, fc2 = st.columns(2)

        from_date = fc1.date_input(
            "📅 من تاريخ:",
            value=(
                date.today()
                - timedelta(days=30)
            ),
            key="transfer_from_date"
        )

        to_date = fc2.date_input(
            "📅 إلى تاريخ:",
            value=date.today(),
            key="transfer_to_date"
        )

        archive_branch_options = (
            ["🌐 كل الفروع"]
            + list(
                branch_dict.keys()
            )
        )

        archive_branch = st.selectbox(
            "🏢 فلترة حسب الفرع المستلم:",
            archive_branch_options,
            key="transfer_archive_branch"
        )

        if from_date > to_date:

            st.error(
                "⚠️ تاريخ البداية يجب "
                "أن يكون قبل تاريخ النهاية."
            )

            return

        if archive_branch == "🌐 كل الفروع":

            archive_branch_id = None

        else:

            archive_branch_id = (
                branch_dict[
                    archive_branch
                ]
            )

        try:

            logs_df = load_transfer_archive(
                from_date,
                to_date,
                archive_branch_id
            )

        except Exception as e:

            st.error(
                "❌ تعذر تحميل "
                "أرشيف التزويد."
            )

            st.code(str(e))

            return

        if logs_df.empty:

            st.info(
                "📌 لا توجد فواتير تزويد "
                "ضمن الفترة المحددة."
            )

            return

        st.metric(
            "عدد فواتير التزويد",
            f"{len(logs_df):,}"
        )

        st.markdown(
            '<div class="dataframe-container">',
            unsafe_allow_html=True
        )

        st.dataframe(
            logs_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "تفاصيل الأصناف والكميات":
                    st.column_config.TextColumn(
                        "تفاصيل الأصناف والكميات",
                        width="large"
                    )
            }
        )

        st.markdown(
            "</div>",
            unsafe_allow_html=True
        )

        # ====================================================
        # Excel
        # ====================================================

        try:

            excel_bytes = to_excel(
                logs_df
            )

            st.download_button(
                label=(
                    "📥 تصدير الأرشيف "
                    "إلى Excel"
                ),
                data=excel_bytes,
                file_name=(
                    f"transfers_"
                    f"{from_date}_to_"
                    f"{to_date}.xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"
                ),
                use_container_width=True
            )

        except Exception as e:

            st.error(
                "تعذر إنشاء ملف Excel."
            )

            st.code(str(e))

        # ====================================================
        # إعادة الطباعة
        # ====================================================

        st.markdown("---")

        st.markdown(
            '<h3 class="rtl-container">'
            '🖨️ إعادة طباعة فاتورة تزويد'
            '</h3>',
            unsafe_allow_html=True
        )

        invoice_options = {}

        for _, row in logs_df.iterrows():

            label = (
                f"فاتورة "
                f"#{row['رقم الفاتورة']} "
                f"| إلى: "
                f"{row['المستهدف']} "
                f"| التاريخ: "
                f"{row['تاريخ الإصدار']}"
            )

            invoice_options[
                label
            ] = row

        selected_invoice_label = (
            st.selectbox(
                "🔍 اختر الفاتورة:",
                [
                    "-- اختر الفاتورة --"
                ]
                + list(
                    invoice_options.keys()
                )
            )
        )

        if (
            selected_invoice_label
            != "-- اختر الفاتورة --"
        ):

            selected_row = (
                invoice_options[
                    selected_invoice_label
                ]
            )

            items_text = str(
                selected_row[
                    "تفاصيل الأصناف والكميات"
                ] or ""
            )

            items_html = ""
            notes_text = ""
            created_by = ""

            lines = items_text.splitlines()

            for line in lines:

                line = line.strip()

                if not line:
                    continue

                if line.startswith(
                    "ملاحظات:"
                ):

                    notes_text = (
                        line.replace(
                            "ملاحظات:",
                            "",
                            1
                        ).strip()
                    )

                    continue

                if line.startswith(
                    "بواسطة:"
                ):

                    created_by = (
                        line.replace(
                            "بواسطة:",
                            "",
                            1
                        ).strip()
                    )

                    continue

                clean_line = (
                    line.replace(
                        "▪",
                        ""
                    ).strip()
                )

                if (
                    "(" in clean_line
                    and ")" in clean_line
                ):

                    name_part = (
                        clean_line[
                            :clean_line.rfind(
                                "("
                            )
                        ].strip()
                    )

                    qty_part = (
                        clean_line[
                            clean_line.rfind(
                                "("
                            ) + 1:
                            clean_line.rfind(
                                ")"
                            )
                        ]
                        .replace(
                            "الكمية:",
                            ""
                        )
                        .strip()
                    )

                    items_html += (
                        "<tr>"
                        f"<td>{name_part}</td>"
                        f"<td>{qty_part}</td>"
                        "</tr>"
                    )

                else:

                    items_html += (
                        "<tr>"
                        "<td colspan='2'>"
                        f"{clean_line}"
                        "</td>"
                        "</tr>"
                    )

            notes_html = ""

            if notes_text:

                notes_html = (
                    "<p style='text-align:right;'>"
                    "<b>ملاحظات:</b> "
                    f"{notes_text}"
                    "</p>"
                )

            created_by_html = ""

            if created_by:

                created_by_html = (
                    "<p style='text-align:right;'>"
                    "<b>أنشأ الفاتورة:</b> "
                    f"{created_by}"
                    "</p>"
                )

            html_content = f"""
            <html dir="rtl">

            <head>
                <meta charset="utf-8">
                <title>فاتورة تزويد #{selected_row['رقم الفاتورة']}</title>
                <style>
                    @page {{
                        size: 80mm auto;
                        margin: 3mm;
                    }}
                    @media print {{
                        .no-print {{
                            display: none !important;
                        }}
                        body {{
                            border: none !important;
                            padding: 0 !important;
                        }}
                    }}
                </style>
            </head>

            <body style="
                font-family: Arial;
                text-align: center;
                max-width: 420px;
                margin: auto;
                padding: 20px;
                border: 1px solid #000;
                background-color: #fff;
            ">

                <h2>
                    مجموعة أبو زيد التجارية
                </h2>

                <p style="
                    font-weight: bold;
                    background-color: #e2e8f0;
                    padding: 7px;
                ">
                    فاتورة تزويد فرع
                </p>

                <hr>

                <p style="text-align:right;">

                    <b>رقم الفاتورة:</b>
                    #{selected_row['رقم الفاتورة']}
                    <br>

                    <b>التاريخ:</b>
                    {selected_row['تاريخ الإصدار']}
                    <br>

                    <b>من:</b>
                    {selected_row['المرسل']}
                    <br>

                    <b>إلى:</b>
                    {selected_row['المستهدف']}
                    <br>

                    <b>الحالة:</b>
                    {selected_row['الحالة']}

                </p>

                <hr>

                <table style="
                    width:100%;
                    text-align:right;
                    border-collapse:collapse;
                ">

                    <tr style="
                        border-bottom:1px solid #000;
                        background-color:#f1f5f9;
                    ">
                        <th>الصنف</th>
                        <th>الكمية</th>
                    </tr>

                    {items_html}

                </table>

                <hr>

                {notes_html}

                {created_by_html}

                <p style="
                    font-size:14px;
                    margin-top:30px;
                    text-align:right;
                ">
                    توقيع المستلم:
                    ........................
                </p>

                <div class="no-print" style="margin-top:15px;">
                    <button
                        onclick="window.print()"
                        style="
                            width:100%;
                            padding:10px;
                            font-size:16px;
                            font-weight:bold;
                            cursor:pointer;
                        "
                    >
                        🖨️ طباعة الآن
                    </button>
                </div>

            </body>

            </html>
            """

            st.components.v1.html(
                html_content,
                height=500,
                scrolling=True
            )

            st.download_button(
                label=(
                    "📥 تحميل نسخة "
                    "الفاتورة HTML"
                ),
                data=html_content.encode(
                    "utf-8"
                ),
                file_name=(
                    "Transfer_Invoice_"
                    f"{selected_row['رقم الفاتورة']}"
                    ".html"
                ),
                mime="text/html",
                use_container_width=True
            )
