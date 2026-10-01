import streamlit as st
from datetime import datetime
from database import get_db_connection


# ============================================================
# تحميل البيانات الأساسية
# ============================================================

def get_master_data():

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

        suppliers = conn.execute(
            """
            SELECT
                id,
                supplier_name,
                phone,
                balance
            FROM suppliers
            ORDER BY supplier_name ASC
            """
        ).fetchall()

        customers = conn.execute(
            """
            SELECT
                id,
                customer_name,
                phone,
                balance
            FROM customers
            ORDER BY customer_name ASC
            """
        ).fetchall()

        return branches, suppliers, customers

    finally:
        if conn:
            conn.close()


# ============================================================
# إضافة مورد سريع
# ============================================================

def add_supplier(name, phone):

    conn = None

    try:

        name = name.strip()
        phone = phone.strip()

        if not name:
            raise ValueError(
                "يرجى إدخال اسم المورد."
            )

        conn = get_db_connection()

        if phone:
            duplicate = conn.execute(
                """
                SELECT id
                FROM suppliers
                WHERE supplier_name = ?
                   OR phone = ?
                LIMIT 1
                """,
                (name, phone)
            ).fetchone()

        else:
            duplicate = conn.execute(
                """
                SELECT id
                FROM suppliers
                WHERE supplier_name = ?
                LIMIT 1
                """,
                (name,)
            ).fetchone()

        if duplicate:
            raise ValueError(
                "هذا المورد أو رقم الهاتف "
                "مسجل مسبقاً."
            )

        conn.execute(
            """
            INSERT INTO suppliers
            (
                supplier_name,
                phone,
                balance
            )
            VALUES (?, ?, ?)
            """,
            (
                name,
                phone,
                0.0
            )
        )

        conn.commit()

        st.success(
            f"✅ تمت إضافة المورد "
            f"({name}) بنجاح."
        )

        st.rerun()

    except ValueError as e:

        if conn:
            conn.rollback()

        st.warning(f"⚠️ {e}")

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر إضافة المورد."
        )

        st.code(str(e))

    finally:
        if conn:
            conn.close()


# ============================================================
# إضافة زبون آجل سريع
# ============================================================

def add_customer(name, phone):

    conn = None

    try:

        name = name.strip()
        phone = phone.strip()

        if not name or not phone:
            raise ValueError(
                "يرجى إدخال اسم الزبون "
                "ورقم الهاتف."
            )

        conn = get_db_connection()

        duplicate = conn.execute(
            """
            SELECT id
            FROM customers
            WHERE customer_name = ?
               OR phone = ?
            LIMIT 1
            """,
            (
                name,
                phone
            )
        ).fetchone()

        if duplicate:
            raise ValueError(
                "هذا الزبون أو رقم الهاتف "
                "مسجل مسبقاً."
            )

        conn.execute(
            """
            INSERT INTO customers
            (
                customer_name,
                phone,
                total_purchases,
                balance
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                name,
                phone,
                0.0,
                0.0
            )
        )

        conn.commit()

        st.success(
            f"✅ تم اعتماد الزبون الآجل "
            f"({name}) بنجاح."
        )

        st.rerun()

    except ValueError as e:

        if conn:
            conn.rollback()

        st.warning(f"⚠️ {e}")

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر إضافة الزبون."
        )

        st.code(str(e))

    finally:
        if conn:
            conn.close()


# ============================================================
# تحميل أصناف الفرع
# ============================================================

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
                avg_cost
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
# ترحيل فاتورة المشتريات
# ============================================================

def post_purchase_invoice(
    branch_id,
    supplier_id,
    supplier_name,
    invoice_number,
    payment_type,
    purchase_cart
):

    conn = None

    try:

        invoice_number = (
            invoice_number.strip()
        )

        if not invoice_number:
            raise ValueError(
                "يرجى إدخال رقم فاتورة المورد."
            )

        if not purchase_cart:
            raise ValueError(
                "فاتورة المشتريات فارغة."
            )

        # إجمالي الفاتورة
        grand_total = sum(
            float(item["total"])
            for item in purchase_cart
        )

        if grand_total <= 0:
            raise ValueError(
                "إجمالي الفاتورة يجب "
                "أن يكون أكبر من صفر."
            )

        conn = get_db_connection()

        # ====================================================
        # التحقق من المورد
        # ====================================================

        supplier = conn.execute(
            """
            SELECT
                id,
                supplier_name,
                balance
            FROM suppliers
            WHERE id = ?
            FOR UPDATE
            """,
            (supplier_id,)
        ).fetchone()

        if not supplier:
            raise ValueError(
                "المورد المحدد غير موجود."
            )

        # ====================================================
        # منع تكرار نفس فاتورة المورد
        # لنفس المورد
        # ====================================================

        duplicate_invoice = conn.execute(
            """
            SELECT id
            FROM purchases
            WHERE supplier_id = ?
              AND invoice_number = ?
            LIMIT 1
            """,
            (
                supplier_id,
                invoice_number
            )
        ).fetchone()

        if duplicate_invoice:
            raise ValueError(
                f"فاتورة المورد رقم "
                f"({invoice_number}) "
                "مسجلة مسبقاً لهذا المورد."
            )

        details = []

        # ====================================================
        # تحديث المخزون ومتوسط التكلفة
        # ====================================================

        for purchase_item in purchase_cart:

            item_id = purchase_item["id"]

            purchased_qty = float(
                purchase_item["qty"]
            )

            purchase_price = float(
                purchase_item["price"]
            )

            if purchased_qty <= 0:
                raise ValueError(
                    f"كمية الصنف "
                    f"({purchase_item['name']}) "
                    "غير صحيحة."
                )

            if purchase_price <= 0:
                raise ValueError(
                    f"سعر شراء الصنف "
                    f"({purchase_item['name']}) "
                    "غير صحيح."
                )

            # قفل الصنف حتى نهاية العملية
            old_row = conn.execute(
                """
                SELECT
                    id,
                    branch_id,
                    item_code,
                    item_name,
                    quantity,
                    avg_cost,
                    buy_price
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

            if not old_row:
                raise ValueError(
                    f"الصنف "
                    f"({purchase_item['name']}) "
                    "غير موجود في الفرع المحدد."
                )

            old_qty = float(
                old_row["quantity"] or 0
            )

            old_avg = float(
                old_row["avg_cost"] or 0
            )

            old_buy_price = float(
                old_row["buy_price"] or 0
            )

            # إذا لم يكن هناك متوسط قديم
            # نستخدم آخر سعر شراء
            if old_avg <= 0:
                old_avg = old_buy_price

            new_total_qty = (
                old_qty
                + purchased_qty
            )

            # =================================================
            # المتوسط الموزون
            # =================================================

            if new_total_qty > 0:

                new_avg_cost = (
                    (
                        old_qty
                        * old_avg
                    )
                    +
                    (
                        purchased_qty
                        * purchase_price
                    )
                ) / new_total_qty

            else:
                new_avg_cost = purchase_price

            conn.execute(
                """
                UPDATE items
                SET
                    quantity = ?,
                    buy_price = ?,
                    avg_cost = ?
                WHERE id = ?
                  AND branch_id = ?
                """,
                (
                    new_total_qty,
                    purchase_price,
                    new_avg_cost,
                    item_id,
                    branch_id
                )
            )

            details.append(
                (
                    f"{purchase_item['name']} "
                    f"[{purchase_item['code']}] "
                    f"- كمية: "
                    f"{purchased_qty:,.2f} "
                    f"- سعر: "
                    f"{purchase_price:,.2f} د.ل "
                    f"- إجمالي: "
                    f"{purchased_qty * purchase_price:,.2f} د.ل"
                )
            )

        # ====================================================
        # تسجيل فاتورة المشتريات
        # ====================================================

        conn.execute(
            """
            INSERT INTO purchases
            (
                branch_id,
                supplier_id,
                supplier_name,
                invoice_number,
                total_cost,
                payment_type,
                items_details,
                invoice_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                branch_id,
                supplier_id,
                supplier_name,
                invoice_number,
                grand_total,
                payment_type,
                " | ".join(details),
                datetime.now().date()
            )
        )

        # ====================================================
        # لو الفاتورة آجل
        # نضيفها إلى رصيد المورد
        # ====================================================

        if (
            payment_type
            == "آجل (تسجل على حساب المورد)"
        ):

            conn.execute(
                """
                UPDATE suppliers
                SET balance =
                    COALESCE(balance, 0) + ?
                WHERE id = ?
                """,
                (
                    grand_total,
                    supplier_id
                )
            )

        conn.commit()

        st.session_state[
            "purch_cart"
        ] = []

        # مسح هوية السلة
        st.session_state.pop(
            "purch_cart_branch_id",
            None
        )

        st.session_state.pop(
            "purch_cart_supplier_id",
            None
        )

        st.success(
            f"✅ تم ترحيل فاتورة المشتريات "
            f"بنجاح.\n\n"
            f"إجمالي الفاتورة: "
            f"{grand_total:,.2f} د.ل"
        )

        st.rerun()

    except ValueError as e:

        if conn:
            conn.rollback()

        st.warning(f"⚠️ {e}")

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر ترحيل فاتورة المشتريات."
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
    # CSS
    # ========================================================

    st.markdown(
        """
        <style>

        .rtl-box {
            direction: rtl !important;
            text-align: right !important;
            background-color: #f8fafc;
            padding: 15px;
            border-radius: 8px;
            border: 1px solid #cbd5e1;
            margin-bottom: 15px;
        }

        .rtl-box * {
            direction: rtl !important;
            text-align: right !important;
        }

        </style>
        """,
        unsafe_allow_html=True
    )

    st.header(
        "📥 إدارة المشتريات "
        "والموردين والزبائن الآجلين"
    )

    st.markdown("---")

    # ========================================================
    # تحميل البيانات
    # ========================================================

    try:

        (
            branches,
            suppliers_data,
            customers_data
        ) = get_master_data()

    except Exception as e:

        st.error(
            "❌ تعذر تحميل بيانات المشتريات."
        )

        st.code(str(e))

        return

    # ========================================================
    # الإدارة السريعة
    # ========================================================

    st.markdown(
        "### ⚙️ الإدارة السريعة "
        "لجهات التعامل"
    )

    quick_tab1, quick_tab2 = st.tabs(
        [
            "➕ إضافة مورد جديد",
            "➕ إضافة زبون آجل جديد"
        ]
    )

    # ========================================================
    # مورد جديد
    # ========================================================

    with quick_tab1:

        with st.form(
            "quick_sup_form_clean",
            clear_on_submit=True
        ):

            qc1, qc2 = st.columns(2)

            q_sname = qc1.text_input(
                "اسم المورد / الشركة:"
            )

            q_sphone = qc2.text_input(
                "رقم الهاتف:"
            )

            submit_supplier = (
                st.form_submit_button(
                    "💾 حفظ المورد الجديد",
                    type="primary"
                )
            )

        if submit_supplier:

            add_supplier(
                q_sname,
                q_sphone
            )

    # ========================================================
    # زبون آجل جديد
    # ========================================================

    with quick_tab2:

        with st.form(
            "quick_cust_form_clean",
            clear_on_submit=True
        ):

            qcc1, qcc2 = st.columns(2)

            q_cname = qcc1.text_input(
                "اسم الزبون الآجل:"
            )

            q_cphone = qcc2.text_input(
                "رقم الهاتف:"
            )

            submit_customer = (
                st.form_submit_button(
                    "💾 حفظ واعتماد الزبون الآجل",
                    type="primary"
                )
            )

        if submit_customer:

            add_customer(
                q_cname,
                q_cphone
            )

    st.markdown("---")

    # ========================================================
    # التأكد من وجود فرع ومورد
    # ========================================================

    if not branches:

        st.warning(
            "⚠️ لا يمكن إدخال مشتريات. "
            "يجب إنشاء فرع أو مخزن أولاً."
        )

        return

    if not suppliers_data:

        st.warning(
            "⚠️ لا يوجد مورد مسجل. "
            "أضف مورداً من الأعلى أولاً."
        )

        return

    # ========================================================
    # القواميس
    # ========================================================

    branch_dict = {
        b["branch_name"]: b["id"]
        for b in branches
    }

    supplier_dict = {
        s["supplier_name"]: s["id"]
        for s in suppliers_data
    }

    supplier_balance_dict = {
        s["supplier_name"]:
            float(s["balance"] or 0)
        for s in suppliers_data
    }

    # ========================================================
    # فاتورة المشتريات
    # ========================================================

    st.markdown(
        "### 🛒 إدخال فاتورة "
        "مشتريات البضاعة"
    )

    col_h1, col_h2, col_h3, col_h4 = (
        st.columns(4)
    )

    pb = col_h1.selectbox(
        "🏢 الفرع / المخزن المستلم:",
        list(branch_dict.keys())
    )

    ps = col_h2.selectbox(
        "🚛 المورد:",
        list(supplier_dict.keys())
    )

    inv_num = col_h3.text_input(
        "🧾 رقم فاتورة المورد:"
    )

    payment_type = col_h4.selectbox(
        "💳 طريقة الدفع:",
        [
            "كاش (مدفوعة بالكامل)",
            "آجل (تسجل على حساب المورد)"
        ]
    )

    selected_branch_id = (
        branch_dict[pb]
    )

    selected_supplier_id = (
        supplier_dict[ps]
    )

    # ========================================================
    # رصيد المورد
    # ========================================================

    current_supplier_balance = (
        supplier_balance_dict.get(
            ps,
            0.0
        )
    )

    if current_supplier_balance > 0:

        st.warning(
            f"⚠️ علينا للمورد ({ps}): "
            f"{current_supplier_balance:,.2f} د.ل"
        )

    elif current_supplier_balance < 0:

        st.success(
            f"✅ لنا رصيد عند المورد ({ps}): "
            f"{abs(current_supplier_balance):,.2f} د.ل"
        )

    else:

        st.info(
            f"ℹ️ حساب المورد ({ps}) "
            "رصيده صفر."
        )

    # ========================================================
    # استعراض أرصدة الزبائن
    # ========================================================

    with st.expander(
        "👁️ استعراض مديونية "
        "الزبائن الآجلين"
    ):

        if customers_data:

            customer_dict = {
                (
                    f"{c['customer_name']} "
                    f"({c['phone'] or '-'})"
                ): c

                for c in customers_data
            }

            selected_customer_label = (
                st.selectbox(
                    "اختر الزبون:",
                    list(
                        customer_dict.keys()
                    ),
                    key="check_cust_balance_box"
                )
            )

            selected_customer = (
                customer_dict[
                    selected_customer_label
                ]
            )

            customer_balance = float(
                selected_customer[
                    "balance"
                ] or 0
            )

            if customer_balance > 0:

                st.warning(
                    f"مديونية الزبون: "
                    f"{customer_balance:,.2f} د.ل"
                )

            elif customer_balance < 0:

                st.success(
                    f"رصيد لصالح الزبون: "
                    f"{abs(customer_balance):,.2f} د.ل"
                )

            else:

                st.info(
                    "رصيد الزبون صفر."
                )

        else:

            st.info(
                "لا توجد زبائن آجلين."
            )

    # ========================================================
    # سلة المشتريات
    # ========================================================

    if "purch_cart" not in st.session_state:
        st.session_state[
            "purch_cart"
        ] = []

    # ========================================================
    # منع انتقال السلة بين الفروع أو الموردين
    # ========================================================

    if st.session_state["purch_cart"]:

        cart_branch_id = (
            st.session_state.get(
                "purch_cart_branch_id"
            )
        )

        cart_supplier_id = (
            st.session_state.get(
                "purch_cart_supplier_id"
            )
        )

        if (
            cart_branch_id
            != selected_branch_id
            or cart_supplier_id
            != selected_supplier_id
        ):

            st.warning(
                "⚠️ لديك فاتورة مشتريات "
                "مفتوحة لفرع أو مورد مختلف. "
                "أكملها أو فرّغ السلة قبل "
                "تغيير الفرع أو المورد."
            )

            if st.button(
                "🗑️ تفريغ فاتورة المشتريات "
                "الحالية والبدء من جديد"
            ):

                st.session_state[
                    "purch_cart"
                ] = []

                st.session_state.pop(
                    "purch_cart_branch_id",
                    None
                )

                st.session_state.pop(
                    "purch_cart_supplier_id",
                    None
                )

                st.rerun()

            return

    st.markdown("---")

    # ========================================================
    # أصناف الفرع
    # ========================================================

    try:

        db_items = get_branch_items(
            selected_branch_id
        )

    except Exception as e:

        st.error(
            "❌ تعذر تحميل أصناف الفرع."
        )

        st.code(str(e))

        return

    item_options = {
        (
            f"[{item['item_code']}] "
            f"{item['item_name']} "
            f"- الرصيد: "
            f"{float(item['quantity'] or 0):,.2f}"
        ): item

        for item in db_items
    }

    # ========================================================
    # إضافة صنف للفاتورة
    # ========================================================

    if item_options:

        with st.form(
            "add_purch_item_form_clean",
            clear_on_submit=True
        ):

            col_i1, col_i2, col_i3 = (
                st.columns([2, 1, 1])
            )

            selected_item_label = (
                col_i1.selectbox(
                    "اختر الصنف:",
                    list(
                        item_options.keys()
                    )
                )
            )

            purchase_qty = (
                col_i2.number_input(
                    "الكمية المشتراة:",
                    min_value=0.01,
                    value=1.0,
                    step=1.0
                )
            )

            purchase_price = (
                col_i3.number_input(
                    "سعر شراء الوحدة (د.ل):",
                    min_value=0.0,
                    value=0.0,
                    step=0.5,
                    format="%.2f"
                )
            )

            add_item_btn = (
                st.form_submit_button(
                    "➕ إضافة الصنف "
                    "لفاتورة المشتريات",
                    type="primary"
                )
            )

        if add_item_btn:

            if (
                purchase_qty <= 0
                or purchase_price <= 0
            ):

                st.warning(
                    "⚠️ أدخل كمية وسعر شراء "
                    "صحيحين."
                )

            else:

                selected_item = (
                    item_options[
                        selected_item_label
                    ]
                )

                # تثبيت الفرع والمورد للسلة
                if not st.session_state[
                    "purch_cart"
                ]:

                    st.session_state[
                        "purch_cart_branch_id"
                    ] = selected_branch_id

                    st.session_state[
                        "purch_cart_supplier_id"
                    ] = selected_supplier_id

                # لو الصنف موجود بالسلة
                # ندمج الكمية مع الحفاظ على
                # متوسط سعر الشراء داخل الفاتورة
                existing_cart_item = None

                for cart_item in (
                    st.session_state[
                        "purch_cart"
                    ]
                ):

                    if (
                        cart_item["id"]
                        == selected_item["id"]
                    ):

                        existing_cart_item = (
                            cart_item
                        )

                        break

                if existing_cart_item:

                    old_cart_qty = float(
                        existing_cart_item[
                            "qty"
                        ]
                    )

                    old_cart_price = float(
                        existing_cart_item[
                            "price"
                        ]
                    )

                    new_cart_qty = (
                        old_cart_qty
                        + float(purchase_qty)
                    )

                    new_cart_price = (
                        (
                            old_cart_qty
                            * old_cart_price
                        )
                        +
                        (
                            float(purchase_qty)
                            * float(
                                purchase_price
                            )
                        )
                    ) / new_cart_qty

                    existing_cart_item[
                        "qty"
                    ] = new_cart_qty

                    existing_cart_item[
                        "price"
                    ] = new_cart_price

                    existing_cart_item[
                        "total"
                    ] = (
                        new_cart_qty
                        * new_cart_price
                    )

                else:

                    st.session_state[
                        "purch_cart"
                    ].append(
                        {
                            "id":
                                selected_item["id"],

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
                                    purchase_qty
                                ),

                            "price":
                                float(
                                    purchase_price
                                ),

                            "total":
                                (
                                    float(
                                        purchase_qty
                                    )
                                    * float(
                                        purchase_price
                                    )
                                )
                        }
                    )

                st.success(
                    "✅ تمت إضافة الصنف "
                    "لفاتورة المشتريات."
                )

                st.rerun()

    else:

        st.info(
            f"لا توجد أصناف معرفة "
            f"في ({pb})."
        )

    # ========================================================
    # عرض السلة
    # ========================================================

    if st.session_state["purch_cart"]:

        st.markdown("---")

        st.markdown(
            "### 🛒 محتويات "
            "فاتورة الشراء الحالية"
        )

        for index, purchase_item in enumerate(
            st.session_state[
                "purch_cart"
            ]
        ):

            (
                p_col1,
                p_col2,
                p_col3,
                p_col4,
                p_col5
            ) = st.columns(
                [2, 1, 1, 1, 0.6]
            )

            p_col1.write(
                f"🏷️ "
                f"{purchase_item['name']} "
                f"({purchase_item['code']})"
            )

            p_col2.write(
                f"كمية: "
                f"{purchase_item['qty']:,.2f}"
            )

            p_col3.write(
                f"سعر: "
                f"{purchase_item['price']:,.2f} "
                "د.ل"
            )

            p_col4.write(
                f"إجمالي: "
                f"{purchase_item['total']:,.2f} "
                "د.ل"
            )

            if p_col5.button(
                "🗑️",
                key=(
                    f"del_purch_item_"
                    f"{index}"
                ),
                help="حذف الصنف"
            ):

                st.session_state[
                    "purch_cart"
                ].pop(index)

                if not st.session_state[
                    "purch_cart"
                ]:

                    st.session_state.pop(
                        "purch_cart_branch_id",
                        None
                    )

                    st.session_state.pop(
                        "purch_cart_supplier_id",
                        None
                    )

                st.rerun()

        st.markdown("---")

        grand_total = sum(
            float(item["total"])
            for item
            in st.session_state[
                "purch_cart"
            ]
        )

        st.metric(
            "📌 إجمالي فاتورة المشتريات",
            f"{grand_total:,.2f} د.ل"
        )

        col_act1, col_act2 = (
            st.columns(2)
        )

        with col_act1:

            confirm_btn = st.button(
                "💾 اعتماد فاتورة المشتريات "
                "وترحيلها للمخزون",
                type="primary",
                use_container_width=True
            )

        with col_act2:

            if st.button(
                "❌ تفريغ السلة بالكامل",
                use_container_width=True
            ):

                st.session_state[
                    "purch_cart"
                ] = []

                st.session_state.pop(
                    "purch_cart_branch_id",
                    None
                )

                st.session_state.pop(
                    "purch_cart_supplier_id",
                    None
                )

                st.rerun()

        # ====================================================
        # اعتماد الفاتورة
        # ====================================================

        if confirm_btn:

            post_purchase_invoice(
                branch_id=selected_branch_id,
                supplier_id=selected_supplier_id,
                supplier_name=ps,
                invoice_number=inv_num,
                payment_type=payment_type,
                purchase_cart=st.session_state[
                    "purch_cart"
                ]
            )
