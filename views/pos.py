import streamlit as st
import json
from datetime import datetime
from database import get_db_connection


# ============================================================
# رقم الوردية
# ============================================================

def get_current_shift_number():
    current_hour = datetime.now().hour

    if 6 <= current_hour < 16:
        return 1

    return 2


# ============================================================
# تجهيز السلة
# ============================================================

def ensure_cart():
    if "cart" not in st.session_state:
        st.session_state["cart"] = []


# ============================================================
# إضافة صنف غير موجود
# ============================================================

@st.dialog("⚠️ صنف غير مسجل - إضافة سريعة")
def add_missing_item_dialog(scanned_code, b_id):

    st.warning(
        f"الكود ({scanned_code}) غير موجود في هذا الفرع. "
        "يمكنك إضافته وبيعه فوراً."
    )

    with st.form("quick_add_missing_item_form"):

        new_item_name = st.text_input(
            "اسم الصنف:"
        )

        col_q1, col_q2 = st.columns(2)

        with col_q1:
            new_item_qty = st.number_input(
                "الكمية:",
                min_value=0.01,
                value=1.0,
                step=1.0
            )

        with col_q2:
            new_item_price = st.number_input(
                "سعر البيع (د.ل):",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f"
            )

        submitted = st.form_submit_button(
            "💾 إضافة للسلة ومتابعة البيع",
            type="primary"
        )

    if not submitted:
        return

    if (
        not new_item_name.strip()
        or new_item_price <= 0
    ):
        st.error(
            "⚠️ يرجى إدخال اسم الصنف "
            "وسعر بيع صحيح."
        )
        return

    conn = None

    try:
        conn = get_db_connection()

        existing = conn.execute(
            """
            SELECT id
            FROM items
            WHERE branch_id = ?
              AND item_code = ?
            """,
            (
                b_id,
                scanned_code
            )
        ).fetchone()

        if existing:
            new_item_id = existing["id"]

        else:
            # PostgreSQL:
            # RETURNING id بدلاً من lastrowid
            row = conn.execute(
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
                RETURNING id
                """,
                (
                    b_id,
                    scanned_code,
                    new_item_name.strip(),
                    float(new_item_qty),
                    0.0,
                    new_item_price,
                    0.0
                )
            ).fetchone()

            new_item_id = row["id"]

        conn.commit()

        ensure_cart()

        st.session_state["cart"].append(
            {
                "id": new_item_id,
                "code": scanned_code,
                "name": new_item_name.strip(),
                "price": float(new_item_price),
                "qty": float(new_item_qty),
                "total": (
                    float(new_item_price)
                    * float(new_item_qty)
                )
            }
        )

        st.success(
            "✅ تمت إضافة الصنف للسلة."
        )

        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر إضافة الصنف."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# شاشة الدفع والخصم
# ============================================================

@st.dialog("💳 إتمام الدفع وإصدار الفاتورة")
def checkout_payment_dialog(
    b_id,
    gross_total,
    branch_name_str,
    cashier_name_str,
    shift_num,
    daily_inv_num
):

    st.subheader(
        f"إجمالي الفاتورة قبل الخصم: "
        f"{gross_total:,.2f} د.ل"
    )

    cust_name = st.text_input(
        "اسم الزبون:",
        value="زبون نقدي"
    )

    cust_phone = st.text_input(
        "رقم الهاتف (اختياري):",
        value=""
    )

    # ========================================================
    # الخصم
    # ========================================================

    st.markdown("### 🎁 خصم على الفاتورة")

    discount_type = st.radio(
        "طريقة الخصم:",
        [
            "بدون خصم",
            "خصم بمبلغ",
            "خصم بنسبة %"
        ],
        horizontal=True
    )

    discount_value = 0.0
    discount_amount = 0.0

    if discount_type == "خصم بمبلغ":

        discount_value = st.number_input(
            "قيمة الخصم (د.ل):",
            min_value=0.0,
            max_value=float(gross_total),
            value=0.0,
            step=0.5,
            format="%.2f"
        )

        discount_amount = float(
            discount_value
        )

    elif discount_type == "خصم بنسبة %":

        discount_value = st.number_input(
            "نسبة الخصم (%):",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=1.0,
            format="%.2f"
        )

        discount_amount = (
            float(gross_total)
            * float(discount_value)
            / 100.0
        )

    discount_amount = min(
        discount_amount,
        float(gross_total)
    )

    final_tot = max(
        0.0,
        float(gross_total)
        - discount_amount
    )

    # ========================================================
    # عرض الحسبة
    # ========================================================

    c_total1, c_total2, c_total3 = (
        st.columns(3)
    )

    c_total1.metric(
        "الإجمالي",
        f"{gross_total:,.2f} د.ل"
    )

    c_total2.metric(
        "الخصم",
        f"{discount_amount:,.2f} د.ل"
    )

    c_total3.metric(
        "الصافي",
        f"{final_tot:,.2f} د.ل"
    )

    if (
        discount_type == "خصم بنسبة %"
        and discount_value > 0
    ):
        st.success(
            f"🎁 خصم {discount_value:,.2f}% "
            f"= {discount_amount:,.2f} د.ل"
        )

    elif (
        discount_type == "خصم بمبلغ"
        and discount_amount > 0
    ):
        st.success(
            f"🎁 تم تطبيق خصم "
            f"{discount_amount:,.2f} د.ل"
        )

    st.markdown("---")

    # ========================================================
    # الدفع
    # ========================================================

    pay_method = st.selectbox(
        "نوع الدفع:",
        [
            "كاش (نقدي)",
            "شبكة / بطاقة",
            "آجل (على الحساب)"
        ]
    )

    conn = None
    accounts = []
    selected_account_id = None

    try:
        conn = get_db_connection()

        if pay_method == "آجل (على الحساب)":

            accounts = conn.execute(
                """
                SELECT
                    id,
                    customer_name,
                    phone,
                    balance
                FROM customers
                ORDER BY customer_name
                """
            ).fetchall()

            if accounts:

                acc_opts = {
                    (
                        f"{a['customer_name']} "
                        f"({a['phone'] or '-'}) "
                        f"- المديونية: "
                        f"{float(a['balance'] or 0):,.2f} د.ل"
                    ): a["id"]

                    for a in accounts
                }

                sel_acc_str = st.selectbox(
                    "📌 اختر الزبون الآجل:",
                    list(acc_opts.keys())
                )

                selected_account_id = (
                    acc_opts[sel_acc_str]
                )

            else:
                st.error(
                    "⚠️ لا يوجد زبائن آجلون "
                    "مسجلون في النظام."
                )

        # ====================================================
        # المبلغ المدفوع
        # ====================================================

        if pay_method == "آجل (على الحساب)":

            paid_amount = 0.0

            st.info(
                f"📌 سيتم تسجيل "
                f"{final_tot:,.2f} د.ل "
                "على حساب الزبون."
            )

        else:

            paid_amount = st.number_input(
                "المبلغ المدفوع (د.ل):",
                min_value=0.0,
                value=float(final_tot),
                step=0.5,
                format="%.2f"
            )

            change_due = (
                float(paid_amount)
                - float(final_tot)
            )

            if change_due >= 0:

                st.success(
                    f"💵 الباقي للزبون: "
                    f"**{change_due:,.2f} د.ل**"
                )

            else:

                st.error(
                    f"⚠️ المبلغ غير كافٍ. "
                    f"العجز: "
                    f"**{abs(change_due):,.2f} د.ل**"
                )

        # ====================================================
        # تأكيد الفاتورة
        # ====================================================

        confirm_invoice = st.button(
            "🖨️ تأكيد وإصدار الفاتورة",
            type="primary",
            use_container_width=True
        )

        if not confirm_invoice:
            return

        if (
            pay_method == "آجل (على الحساب)"
            and not selected_account_id
        ):
            st.error(
                "⚠️ يجب اختيار الزبون الآجل."
            )
            return

        if (
            pay_method != "آجل (على الحساب)"
            and paid_amount < final_tot
        ):
            st.warning(
                "⚠️ المبلغ المدفوع أقل "
                "من إجمالي الفاتورة."
            )
            return

        # ====================================================
        # التأكد من المخزون قبل البيع
        # ====================================================

        for cart_item in st.session_state["cart"]:

            if cart_item.get("id") == 99999:
                continue

            stock_row = conn.execute(
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
                    cart_item["id"],
                    b_id
                )
            ).fetchone()

            if not stock_row:
                raise ValueError(
                    f"الصنف "
                    f"({cart_item['name']}) "
                    "غير موجود في هذا الفرع."
                )

            available_qty = float(
                stock_row["quantity"] or 0
            )

            requested_qty = float(
                cart_item["qty"]
            )

            if requested_qty > available_qty:

                raise ValueError(
                    f"الكمية غير كافية للصنف "
                    f"({cart_item['name']}). "
                    f"المتاح: "
                    f"{available_qty:,.2f}"
                )

        # ====================================================
        # بيانات الأصناف والخصم داخل notes
        # ====================================================

        invoice_details = {
            "items":
                st.session_state[
                    "cart"
                ].copy(),

            "gross_total":
                float(gross_total),

            "discount_type":
                discount_type,

            "discount_value":
                float(discount_value),

            "discount_amount":
                float(discount_amount),

            "final_total":
                float(final_tot)
        }

        invoice_json = json.dumps(
            invoice_details,
            ensure_ascii=False
        )

        # ====================================================
        # حفظ الفاتورة - PostgreSQL
        # ====================================================

        invoice_row = conn.execute(
            """
            INSERT INTO invoices
            (
                branch_id,
                user_id,
                customer_name,
                customer_phone,
                total_amount,
                payment_method,
                notes,
                shift_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                b_id,
                st.session_state.get(
                    "user_id",
                    1
                ),
                (
                    cust_name.strip()
                    if cust_name.strip()
                    else "زبون نقدي"
                ),
                cust_phone.strip(),
                final_tot,
                pay_method,
                invoice_json,
                str(shift_num)
            )
        ).fetchone()

        inv_id = invoice_row["id"]

        # ====================================================
        # خصم المخزون
        # ====================================================

        for cart_item in st.session_state["cart"]:

            if cart_item.get("id") == 99999:
                continue

            conn.execute(
                """
                UPDATE items
                SET quantity = quantity - ?
                WHERE id = ?
                  AND branch_id = ?
                """,
                (
                    cart_item["qty"],
                    cart_item["id"],
                    b_id
                )
            )

        # ====================================================
        # البيع الآجل
        # ====================================================

        if (
            selected_account_id
            and pay_method
            == "آجل (على الحساب)"
        ):

            conn.execute(
                """
                UPDATE customers
                SET
                    balance =
                        COALESCE(balance, 0) + ?,

                    total_purchases =
                        COALESCE(total_purchases, 0) + ?

                WHERE id = ?
                """,
                (
                    final_tot,
                    final_tot,
                    selected_account_id
                )
            )

        conn.commit()

        # ====================================================
        # حفظ آخر فاتورة للطباعة
        # ====================================================

        st.session_state[
            "last_invoice"
        ] = {
            "inv_id":
                inv_id,

            "daily_inv_num":
                daily_inv_num,

            "branch":
                branch_name_str,

            "cashier":
                cashier_name_str,

            "shift":
                shift_num,

            "date_time":
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),

            "customer":
                (
                    cust_name.strip()
                    if cust_name.strip()
                    else "زبون نقدي"
                ),

            "items":
                st.session_state[
                    "cart"
                ].copy(),

            "gross_total":
                float(gross_total),

            "discount_type":
                discount_type,

            "discount_value":
                float(discount_value),

            "discount_amount":
                float(discount_amount),

            "total":
                float(final_tot),

            "method":
                pay_method
        }

        st.session_state["cart"] = []

        st.success(
            "✅ تم إصدار الفاتورة بنجاح."
        )

        st.rerun()

    except ValueError as e:

        if conn:
            conn.rollback()

        st.error(
            f"⚠️ {e}"
        )

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ حدث خطأ أثناء إصدار الفاتورة."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# معالجة الباركود
# ============================================================

def process_barcode_scan():

    ensure_cart()

    code = st.session_state.get(
        "barcode_scan_input",
        ""
    ).strip()

    qty_to_add = float(
        st.session_state.get(
            "barcode_qty_input",
            1.0
        )
    )

    if not code:
        return

    b_id = st.session_state.get(
        "branch_id"
    )

    if not b_id:
        st.error(
            "⚠️ لم يتم تحديد الفرع."
        )
        return

    conn = None

    try:

        conn = get_db_connection()

        item = None

        # ====================================================
        # باركود الوزن
        # ====================================================

        if (
            code.startswith("20")
            and len(code) >= 12
        ):

            item_code = code[2:7]

            try:
                weight_value = (
                    float(code[7:12])
                    / 1000.0
                )

            except ValueError:
                weight_value = qty_to_add

            item = conn.execute(
                """
                SELECT *
                FROM items
                WHERE item_code = ?
                  AND branch_id = ?
                """,
                (
                    item_code,
                    b_id
                )
            ).fetchone()

            if item:
                qty_to_add = weight_value

        # ====================================================
        # باركود عادي
        # ====================================================

        if not item:

            item = conn.execute(
                """
                SELECT *
                FROM items
                WHERE item_code = ?
                  AND branch_id = ?
                """,
                (
                    code,
                    b_id
                )
            ).fetchone()

        if item:

            unit_price = float(
                item["sale_price"] or 0
            )

            # لو نفس الصنف موجود بالسلة
            # نزود كميته بدل سطر جديد
            existing_cart_item = None

            for cart_item in st.session_state["cart"]:

                if (
                    cart_item.get("id")
                    == item["id"]
                ):
                    existing_cart_item = (
                        cart_item
                    )
                    break

            if existing_cart_item:

                existing_cart_item["qty"] += (
                    float(qty_to_add)
                )

                existing_cart_item["total"] = (
                    existing_cart_item["qty"]
                    * existing_cart_item["price"]
                )

            else:

                st.session_state["cart"].append(
                    {
                        "id":
                            item["id"],

                        "code":
                            item["item_code"],

                        "name":
                            item["item_name"],

                        "price":
                            unit_price,

                        "qty":
                            float(qty_to_add),

                        "total":
                            (
                                unit_price
                                * float(qty_to_add)
                            )
                    }
                )

            st.session_state[
                "barcode_qty_input"
            ] = 1.0

        else:

            conn.close()
            conn = None

            add_missing_item_dialog(
                code,
                b_id
            )

            return

    except Exception as e:

        st.error(
            "❌ حدث خطأ أثناء قراءة الباركود."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()

        st.session_state[
            "barcode_scan_input"
        ] = ""


# ============================================================
# قراءة notes القديمة والجديدة
# ============================================================

def parse_invoice_notes(notes, total_amount):

    default_result = {
        "items": [],
        "gross_total": float(
            total_amount or 0
        ),
        "discount_type": "بدون خصم",
        "discount_value": 0.0,
        "discount_amount": 0.0,
        "final_total": float(
            total_amount or 0
        )
    }

    if not notes:
        return default_result

    try:

        data = json.loads(notes)

        # النظام الجديد
        if isinstance(data, dict):

            result = default_result.copy()

            result.update(data)

            return result

        # الفواتير القديمة
        if isinstance(data, list):

            default_result[
                "items"
            ] = data

            return default_result

    except Exception:
        pass

    return default_result


# ============================================================
# أدوات تقارير الخصم والطباعة المباشرة
# ============================================================

def summarize_invoice_rows(rows):
    gross_total = 0.0
    discount_total = 0.0
    net_total = 0.0
    discounted_count = 0

    for row in rows:
        net = float(row["total_amount"] or 0)
        details = parse_invoice_notes(row["notes"], net)
        gross = float(details.get("gross_total", net) or net)
        discount = float(details.get("discount_amount", 0) or 0)
        gross_total += gross
        discount_total += discount
        net_total += net
        if discount > 0:
            discounted_count += 1

    return {
        "gross_total": gross_total,
        "discount_total": discount_total,
        "net_total": net_total,
        "discounted_count": discounted_count,
        "invoice_count": len(rows)
    }


def make_printable_html(body_html, title="طباعة"):
    return f"""
    <!doctype html>
    <html dir="rtl">
    <head>
        <meta charset="utf-8">
        <title>{title}</title>
        <style>
            @page {{ size: 80mm auto; margin: 3mm; }}
            body {{
                font-family: Arial, sans-serif;
                direction: rtl;
                text-align: center;
                width: 72mm;
                margin: 0 auto;
                color: #000;
                background: #fff;
                font-size: 12px;
            }}
            table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
            th, td {{
                padding: 3px 1px;
                border-bottom: 1px dashed #999;
                text-align: right;
            }}
            .left {{ text-align: left; }}
            .no-print {{ margin: 10px 0; }}
            @media print {{ .no-print {{ display: none !important; }} }}
        </style>
    </head>
    <body>
        {body_html}
        <div class="no-print">
            <button onclick="window.print()" style="
                width:100%; padding:10px; font-size:16px;
                font-weight:bold; cursor:pointer;
            ">🖨️ طباعة الآن</button>
        </div>
    </body>
    </html>
    """


def build_invoice_print_html(inv):
    items_html = "".join(
        [
            (
                "<tr>"
                f"<td>{i.get('name', '-')}</td>"
                f"<td>{float(i.get('qty', 0) or 0):g}</td>"
                f"<td>{float(i.get('price', 0) or 0):.2f}</td>"
                f"<td>{float(i.get('total', 0) or 0):.2f}</td>"
                "</tr>"
            )
            for i in inv.get("items", [])
        ]
    )

    discount_amount = float(inv.get("discount_amount", 0) or 0)
    gross_total = float(inv.get("gross_total", inv.get("total", 0)) or 0)
    total = float(inv.get("total", 0) or 0)

    discount_html = ""
    if discount_amount > 0:
        discount_html = f"""
        <p class="left">الإجمالي قبل الخصم: <b>{gross_total:,.2f} د.ل</b></p>
        <p class="left">الخصم: <b>{discount_amount:,.2f} د.ل</b></p>
        """

    body = f"""
        <h2>مجموعة أبو زيد التجارية</h2>
        <p>فرع: {inv.get('branch', '-')}</p>
        <hr>
        <p style="text-align:right;">
            <b>رقم فاتورة اليوم:</b> #{inv.get('daily_inv_num', '-')}<br>
            <b>رقم الفاتورة:</b> #{inv.get('inv_id', '-')}<br>
            <b>التاريخ:</b> {inv.get('date_time', '-')}<br>
            <b>الكاشير:</b> {inv.get('cashier', '-')}<br>
            <b>الوردية:</b> {inv.get('shift', '-')}<br>
            <b>الزبون:</b> {inv.get('customer', 'زبون نقدي')}<br>
            <b>طريقة الدفع:</b> {inv.get('method', '-')}
        </p>
        <hr>
        <table>
            <tr><th>الصنف</th><th>الكمية</th><th>السعر</th><th>المجموع</th></tr>
            {items_html}
        </table>
        <hr>
        {discount_html}
        <h3 class="left">الصافي: {total:,.2f} د.ل</h3>
        <p>شكراً لتسوقكم معنا 🥜</p>
    """
    return make_printable_html(body, f"Invoice {inv.get('inv_id', '')}")


def build_shift_report_html(report_title, branch_name, username, shift_num, summary):
    body = f"""
        <h2>مجموعة أبو زيد التجارية</h2>
        <p>فرع: {branch_name}</p>
        <hr>
        <h3>{report_title}</h3>
        <p style="text-align:right;">
            <b>التاريخ:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>
            <b>الكاشير:</b> {username}<br>
            <b>الوردية:</b> {shift_num}
        </p>
        <hr>
        <p class="left">عدد الفواتير: <b>{summary["invoice_count"]}</b></p>
        <p class="left">إجمالي قبل الخصم: <b>{summary["gross_total"]:,.2f} د.ل</b></p>
        <p class="left">إجمالي الخصومات: <b>{summary["discount_total"]:,.2f} د.ل</b></p>
        <p class="left">عدد فواتير الخصم: <b>{summary["discounted_count"]}</b></p>
        <h3 class="left">صافي المبيعات: {summary["net_total"]:,.2f} د.ل</h3>
    """
    return make_printable_html(body, report_title)


# ============================================================
# الصفحة الرئيسية
# ============================================================

def show_page():

    ensure_cart()

    st.markdown(
        """
        <style>

        .top-panel {
            background-color: #e2e8f0;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #cbd5e1;
            margin-bottom: 12px;
            direction: rtl;
            text-align: right;
        }

        .totals-panel {
            background-color: #0f172a;
            color: #ffffff !important;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
            font-size: 19px;
            border: 2px solid #334155;
            margin-top: 8px;
            direction: rtl;
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
        🛒 نقطة البيع (POS)
        </h2>
        """,
        unsafe_allow_html=True
    )

    role = st.session_state.get(
        "role",
        ""
    )

    username = st.session_state.get(
        "username",
        ""
    )

    user_branch_id = st.session_state.get(
        "branch_id"
    )

    current_shift_num = (
        get_current_shift_number()
    )

    conn = None

    try:

        conn = get_db_connection()

        # ====================================================
        # تحديد الفرع
        # ====================================================

        if role in [
            "Admin",
            "General_Supervisor"
        ]:

            branches_data = conn.execute(
                """
                SELECT
                    id,
                    branch_name,
                    branch_type
                FROM branches
                ORDER BY id ASC
                """
            ).fetchall()

            if not branches_data:
                st.warning(
                    "لا توجد فروع مسجلة."
                )
                return

            b_dict = {
                b["branch_name"]: b["id"]
                for b in branches_data
            }

            default_index = 0

            for idx, branch in enumerate(
                branches_data
            ):

                if (
                    branch["branch_type"]
                    == "مخزن"
                ):
                    default_index = idx
                    break

            sel_pos = st.selectbox(
                "اختر الفرع الحالي للبيع:",
                list(b_dict.keys()),
                index=default_index
            )

            b_id = b_dict[sel_pos]

            branch_name_display = (
                sel_pos
            )

        else:

            b_id = user_branch_id

            if not b_id:

                st.error(
                    "⚠️ المستخدم الحالي "
                    "غير مرتبط بفرع."
                )
                return

            b_row = conn.execute(
                """
                SELECT branch_name
                FROM branches
                WHERE id = ?
                """,
                (b_id,)
            ).fetchone()

            branch_name_display = (
                b_row["branch_name"]
                if b_row
                else "الفرع الحالي"
            )

        st.session_state[
            "branch_id"
        ] = b_id

        # ====================================================
        # إشعارات التزويد
        # ====================================================

        pending_logs = conn.execute(
            """
            SELECT *
            FROM transfer_logs
            WHERE to_branch_id = ?
              AND status NOT LIKE
                  'مكتملة ومستلمة%'
            ORDER BY id DESC
            """,
            (b_id,)
        ).fetchall()

        if pending_logs:

            st.success(
                f"📦 توجد بضاعة واردة إلى "
                f"({branch_name_display}) "
                "تحتاج تأكيد الاستلام."
            )

            for pt in pending_logs:

                with st.container(
                    border=True
                ):

                    st.write(
                        f"رقم الحركة: "
                        f"#{pt['id']}"
                    )

                    st.write(
                        f"التاريخ: "
                        f"{pt['transfer_date']}"
                    )

                    st.write(
                        pt["items_details"]
                    )

            if st.button(
                "✅ تأكيد استلام البضاعة",
                type="primary",
                use_container_width=True
            ):

                try:

                    for pt in pending_logs:

                        conn.execute(
                            """
                            UPDATE transfer_logs
                            SET status = ?
                            WHERE id = ?
                            """,
                            (
                                (
                                    "مكتملة ومستلمة "
                                    "بواسطة الكاشير: "
                                    f"{username}"
                                ),
                                pt["id"]
                            )
                        )

                    conn.commit()

                    st.success(
                        "✅ تم تأكيد الاستلام."
                    )

                    st.rerun()

                except Exception:

                    conn.rollback()
                    raise

            st.stop()

        # ====================================================
        # رقم فاتورة اليوم
        # ====================================================

        today_date = (
            datetime.now().date()
        )

        branch_inv_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM invoices
            WHERE branch_id = ?
              AND DATE(created_at) = ?
            """,
            (
                b_id,
                today_date
            )
        ).fetchone()[0]

        daily_inv_num = (
            int(branch_inv_count or 0)
            + 1
        )

        # ====================================================
        # تقارير الوردية والإغلاق
        # ====================================================

        if role in [
            "Admin",
            "General_Supervisor",
            "Branch_Supervisor"
        ]:

            st.markdown("---")

            st.markdown(
                "### 📊 تقارير الإغلاق المالي "
                "وتسليم الورديات"
            )

            c_x, c_z = st.columns(2)

            with c_x:

                shift_invoice_rows = conn.execute(
                    """
                    SELECT total_amount, notes
                    FROM invoices
                    WHERE branch_id = ?
                      AND DATE(created_at) = ?
                      AND shift_status = ?
                    ORDER BY id ASC
                    """,
                    (b_id, today_date, str(current_shift_num))
                ).fetchall()

                x_summary = summarize_invoice_rows(shift_invoice_rows)

                st.metric(
                    f"صافي مبيعات الوردية رقم {current_shift_num}",
                    f"{x_summary['net_total']:,.2f} د.ل"
                )

                st.caption(
                    f"قبل الخصم: {x_summary['gross_total']:,.2f} د.ل | "
                    f"الخصومات: {x_summary['discount_total']:,.2f} د.ل | "
                    f"فواتير عليها خصم: {x_summary['discounted_count']}"
                )

                x_html = build_shift_report_html(
                    "تقرير X - تسليم الوردية",
                    branch_name_display,
                    username,
                    current_shift_num,
                    x_summary
                )

                st.components.v1.html(x_html, height=180, scrolling=True)

            with c_z:

                z_invoice_rows = conn.execute(
                    """
                    SELECT total_amount, notes
                    FROM invoices
                    WHERE branch_id = ?
                      AND DATE(created_at) = ?
                      AND shift_status != 'Z_Closed'
                    ORDER BY id ASC
                    """,
                    (b_id, today_date)
                ).fetchall()

                z_summary = summarize_invoice_rows(z_invoice_rows)

                st.metric(
                    "صافي مبيعات اليوم غير المغلقة",
                    f"{z_summary['net_total']:,.2f} د.ل"
                )

                st.caption(
                    f"قبل الخصم: {z_summary['gross_total']:,.2f} د.ل | "
                    f"الخصومات: {z_summary['discount_total']:,.2f} د.ل | "
                    f"فواتير عليها خصم: {z_summary['discounted_count']}"
                )

                z_html = build_shift_report_html(
                    "تقرير Z - الإغلاق المالي",
                    branch_name_display,
                    username,
                    current_shift_num,
                    z_summary
                )

                st.components.v1.html(z_html, height=180, scrolling=True)

                if st.button(
                    "⚙️ تنفيذ الإغلاق المالي لليوم",
                    type="primary",
                    use_container_width=True
                ):
                    try:
                        st.session_state["last_z_report_html"] = z_html

                        conn.execute(
                            """
                            UPDATE invoices
                            SET shift_status = 'Z_Closed'
                            WHERE branch_id = ?
                              AND DATE(created_at) = ?
                              AND shift_status != 'Z_Closed'
                            """,
                            (b_id, today_date)
                        )

                        conn.commit()
                        st.success("✅ تم إغلاق مبيعات اليوم.")
                        st.rerun()

                    except Exception:
                        conn.rollback()
                        raise

                if st.session_state.get("last_z_report_html"):
                    st.markdown("#### 🧾 آخر تقرير Z تم إغلاقه")
                    st.components.v1.html(
                        st.session_state["last_z_report_html"],
                        height=180,
                        scrolling=True
                    )

            st.markdown("---")

        # ====================================================
        # آخر فاتورة - عرض وطباعة مباشرة
        # ====================================================

        if st.session_state.get("last_invoice"):

            inv = st.session_state["last_invoice"]
            html_file_content = build_invoice_print_html(inv)

            st.success("✅ تمت عملية الدفع بنجاح.")
            st.info(
                "🖨️ اضغط «طباعة الآن» داخل الفاتورة لفتح نافذة "
                "الطباعة مباشرة من المتصفح."
            )

            st.components.v1.html(
                html_file_content,
                height=620,
                scrolling=True
            )

            c_inv1, c_inv2 = st.columns(2)

            with c_inv1:
                st.download_button(
                    "📥 تحميل الفاتورة (HTML)",
                    data=html_file_content.encode("utf-8"),
                    file_name=f"Invoice_{inv['inv_id']}.html",
                    mime="text/html",
                    use_container_width=True
                )

            with c_inv2:
                if st.button(
                    "✖️ إخفاء الفاتورة ومتابعة البيع",
                    type="primary",
                    use_container_width=True
                ):
                    st.session_state["last_invoice"] = None
                    st.rerun()

        # ====================================================
        # اختيار الشاشة
        # ====================================================

        if (
            "pos_active_view"
            not in st.session_state
        ):

            st.session_state[
                "pos_active_view"
            ] = "الكاشير السريع"

        st.markdown("---")

        t_col1, t_col2, t_col3 = (
            st.columns(3)
        )

        if t_col1.button(
            "🛒 الكاشير السريع والباركود",
            use_container_width=True
        ):
            st.session_state[
                "pos_active_view"
            ] = "الكاشير السريع"

        if t_col2.button(
            "🔍 البحث اليدوي والصنف الحر",
            use_container_width=True
        ):
            st.session_state[
                "pos_active_view"
            ] = "البحث اليدوي"

        if t_col3.button(
            "📋 الأرشيف وإعادة الطباعة",
            use_container_width=True
        ):
            st.session_state[
                "pos_active_view"
            ] = "الأرشيف"

        st.markdown("---")

        # ====================================================
        # الكاشير السريع
        # ====================================================

        if (
            st.session_state[
                "pos_active_view"
            ]
            == "الكاشير السريع"
        ):

            col_qty, col_bar, col_info = (
                st.columns(
                    [1, 2, 2]
                )
            )

            with col_qty:

                st.number_input(
                    "الكمية (كجم/وحدة):",
                    min_value=0.01,
                    value=1.0,
                    step=0.5,
                    key="barcode_qty_input"
                )

            with col_bar:

                st.text_input(
                    "🔍 مسح الباركود "
                    "الفوري (Enter):",
                    key="barcode_scan_input",
                    on_change=(
                        process_barcode_scan
                    )
                )

            with col_info:

                st.info(
                    f"فاتورة اليوم: "
                    f"#{daily_inv_num}\n\n"
                    f"الوردية: "
                    f"{current_shift_num}\n\n"
                    f"الفرع: "
                    f"{branch_name_display}\n\n"
                    f"الكاشير: "
                    f"{username}"
                )

            st.markdown(
                "### 🧾 محتويات "
                "سلة المبيعات"
            )

            cart_items_list = (
                st.session_state[
                    "cart"
                ]
            )

            total_cart_qty = sum(
                float(item["qty"])
                for item
                in cart_items_list
            )

            total_cart_val = sum(
                float(item["total"])
                for item
                in cart_items_list
            )

            stat_c1, stat_c2 = (
                st.columns(2)
            )

            stat_c1.metric(
                "📦 إجمالي الكمية",
                f"{total_cart_qty:,.2f}"
            )

            stat_c2.metric(
                "💰 إجمالي الفاتورة",
                f"{total_cart_val:,.2f} د.ل"
            )

            st.markdown("---")

            if not cart_items_list:

                st.info(
                    "السلة فارغة حالياً."
                )

            else:

                for index, cart_item in enumerate(
                    cart_items_list
                ):

                    (
                        c_col1,
                        c_col2,
                        c_col3,
                        c_col4,
                        c_col5
                    ) = st.columns(
                        [2, 1, 1, 1, 0.6]
                    )

                    c_col1.write(
                        f"🏷️ "
                        f"{cart_item['name']}"
                    )

                    c_col2.write(
                        f"كمية: "
                        f"{cart_item['qty']}"
                    )

                    c_col3.write(
                        f"سعر: "
                        f"{cart_item['price']:.2f}"
                    )

                    c_col4.write(
                        f"إجمالي: "
                        f"{cart_item['total']:.2f}"
                    )

                    if c_col5.button(
                        "🗑️",
                        key=(
                            f"del_cart_"
                            f"{index}"
                        )
                    ):

                        st.session_state[
                            "cart"
                        ].pop(index)

                        st.rerun()

            g_tot = total_cart_val

            st.markdown(
                f"""
                <div class="totals-panel">
                    إجمالي السلة:
                    <b>
                    {g_tot:,.2f} د.ل
                    </b>
                    <br>
                    الخصم يتم تحديده
                    عند الضغط على الدفع
                </div>
                """,
                unsafe_allow_html=True
            )

            st.write("")

            c_btn1, c_btn2 = (
                st.columns([2, 1])
            )

            with c_btn1:

                if st.button(
                    "💰 دفع واعتماد الفاتورة",
                    use_container_width=True,
                    type="primary"
                ):

                    if st.session_state[
                        "cart"
                    ]:

                        checkout_payment_dialog(
                            b_id,
                            g_tot,
                            branch_name_display,
                            username,
                            current_shift_num,
                            daily_inv_num
                        )

                    else:

                        st.warning(
                            "السلة فارغة."
                        )

            with c_btn2:

                if st.button(
                    "❌ تفريغ السلة بالكامل",
                    use_container_width=True
                ):

                    st.session_state[
                        "cart"
                    ] = []

                    st.rerun()

        # ====================================================
        # البحث اليدوي
        # ====================================================

        elif (
            st.session_state[
                "pos_active_view"
            ]
            == "البحث اليدوي"
        ):

            st.markdown(
                "### ⚡ البحث اليدوي "
                "عن الأصناف"
            )

            all_items_db = conn.execute(
                """
                SELECT *
                FROM items
                WHERE branch_id = ?
                ORDER BY item_name ASC
                """,
                (b_id,)
            ).fetchall()

            if all_items_db:

                item_names_dict = {
                    (
                        f"{it['item_name']} "
                        f"(الكود: "
                        f"{it['item_code']} "
                        f"- السعر: "
                        f"{float(it['sale_price'] or 0):,.2f} "
                        f"د.ل "
                        f"- المتاح: "
                        f"{float(it['quantity'] or 0):,.2f})"
                    ): it

                    for it in all_items_db
                }

                selected_manual_item_str = (
                    st.selectbox(
                        "اختر الصنف يدوياً:",
                        list(
                            item_names_dict.keys()
                        )
                    )
                )

                selected_item_obj = (
                    item_names_dict[
                        selected_manual_item_str
                    ]
                )

                manual_qty = st.number_input(
                    "الكمية المطلوبة:",
                    min_value=0.01,
                    value=1.0,
                    step=0.1
                )

                if st.button(
                    "➕ إضافة إلى "
                    "سلة المبيعات",
                    type="primary"
                ):

                    sale_price = float(
                        selected_item_obj[
                            "sale_price"
                        ] or 0
                    )

                    st.session_state[
                        "cart"
                    ].append(
                        {
                            "id":
                                selected_item_obj[
                                    "id"
                                ],

                            "name":
                                selected_item_obj[
                                    "item_name"
                                ],

                            "code":
                                selected_item_obj[
                                    "item_code"
                                ],

                            "price":
                                sale_price,

                            "qty":
                                float(
                                    manual_qty
                                ),

                            "total":
                                (
                                    sale_price
                                    * float(
                                        manual_qty
                                    )
                                )
                        }
                    )

                    st.success(
                        "✅ تمت إضافة "
                        "الصنف للسلة."
                    )

                    st.rerun()

            else:

                st.info(
                    "لا توجد أصناف "
                    "في هذا الفرع."
                )

            st.markdown("---")

            st.markdown(
                "### 🛒 بيع صنف حر "
                "(بدون كود)"
            )

            col_f1, col_f2, col_f3 = (
                st.columns(3)
            )

            free_name = col_f1.text_input(
                "اسم الصنف:",
                value="صنف عام / خدمة"
            )

            free_price = (
                col_f2.number_input(
                    "السعر (د.ل):",
                    min_value=0.0,
                    step=1.0,
                    format="%.2f"
                )
            )

            free_qty = (
                col_f3.number_input(
                    "الكمية:",
                    min_value=0.01,
                    value=1.0,
                    step=1.0
                )
            )

            if st.button(
                "➕ إضافة الصنف الحر "
                "للفاتورة"
            ):

                if free_price > 0:

                    st.session_state[
                        "cart"
                    ].append(
                        {
                            "id": 99999,
                            "name":
                                free_name.strip()
                                or "صنف عام / خدمة",
                            "code": "FREE",
                            "price":
                                float(
                                    free_price
                                ),
                            "qty":
                                float(
                                    free_qty
                                ),
                            "total":
                                (
                                    float(
                                        free_price
                                    )
                                    * float(
                                        free_qty
                                    )
                                )
                        }
                    )

                    st.success(
                        "✅ تمت إضافة "
                        "الصنف الحر."
                    )

                    st.rerun()

                else:

                    st.warning(
                        "يرجى إدخال "
                        "سعر صحيح."
                    )

        # ====================================================
        # الأرشيف
        # ====================================================

        elif (
            st.session_state[
                "pos_active_view"
            ]
            == "الأرشيف"
        ):

            st.markdown(
                "### 📋 أرشيف مبيعات الفرع "
                "وإعادة الطباعة"
            )

            recent_invs = conn.execute(
                """
                SELECT
                    id,
                    customer_name,
                    total_amount,
                    created_at
                FROM invoices
                WHERE branch_id = ?
                ORDER BY id DESC
                LIMIT 100
                """,
                (b_id,)
            ).fetchall()

            if recent_invs:

                inv_dict = {
                    (
                        f"فاتورة #{r['id']} "
                        f"| {r['customer_name']} "
                        f"| "
                        f"{float(r['total_amount'] or 0):,.2f} "
                        f"د.ل "
                        f"| {r['created_at']}"
                    ): r["id"]

                    for r in recent_invs
                }

                sel_inv_str = st.selectbox(
                    "اختر الفاتورة:",
                    [
                        "-- اختر الفاتورة --"
                    ]
                    + list(
                        inv_dict.keys()
                    )
                )

                if (
                    sel_inv_str
                    != "-- اختر الفاتورة --"
                ):

                    target_inv_id = (
                        inv_dict[
                            sel_inv_str
                        ]
                    )

                    inv_data = conn.execute(
                        """
                        SELECT *
                        FROM invoices
                        WHERE id = ?
                        """,
                        (target_inv_id,)
                    ).fetchone()

                    if inv_data:

                        details = (
                            parse_invoice_notes(
                                inv_data[
                                    "notes"
                                ],
                                inv_data[
                                    "total_amount"
                                ]
                            )
                        )

                        saved_items = details[
                            "items"
                        ]

                        items_html = "".join(
                            [
                                (
                                    "<tr>"
                                    f"<td>{i.get('name', '-')}</td>"
                                    f"<td>{i.get('qty', '-')}</td>"
                                    f"<td>{i.get('price', '-')}</td>"
                                    f"<td>{i.get('total', '-')}</td>"
                                    "</tr>"
                                )
                                for i in saved_items
                            ]
                        )

                        discount_html = ""

                        if float(
                            details.get(
                                "discount_amount",
                                0
                            )
                            or 0
                        ) > 0:

                            discount_html = f"""
                            <p>
                                الإجمالي قبل الخصم:
                                {
                                    float(
                                        details.get(
                                            "gross_total",
                                            inv_data[
                                                "total_amount"
                                            ]
                                        )
                                    )
                                    :,.2f
                                }
                                د.ل
                            </p>

                            <p>
                                الخصم:
                                {
                                    float(
                                        details.get(
                                            "discount_amount",
                                            0
                                        )
                                    )
                                    :,.2f
                                }
                                د.ل
                            </p>
                            """

                        html_reprint_content = f"""
                        <html dir="rtl">

                        <head>
                            <meta charset="utf-8">
                        </head>

                        <body style="
                            font-family:Arial;
                            text-align:center;
                            max-width:350px;
                            margin:auto;
                            padding:20px;
                            border:1px solid #000;
                        ">

                            <h2>
                                مجموعة أبو زيد التجارية
                            </h2>

                            <p>
                                فرع:
                                {branch_name_display}
                            </p>

                            <hr>

                            <p style="
                                text-align:right;
                            ">
                                <b>
                                رقم الفاتورة:
                                </b>
                                #{inv_data['id']}
                                <br>

                                <b>
                                التاريخ:
                                </b>
                                {
                                    inv_data[
                                        'created_at'
                                    ]
                                }
                                <br>

                                <b>
                                طريقة الدفع:
                                </b>
                                {
                                    inv_data[
                                        'payment_method'
                                    ]
                                }
                            </p>

                            <hr>

                            <table style="
                                width:100%;
                                text-align:right;
                            ">

                                <tr>
                                    <th>الصنف</th>
                                    <th>الكمية</th>
                                    <th>السعر</th>
                                    <th>المجموع</th>
                                </tr>

                                {items_html}

                            </table>

                            <hr>

                            {discount_html}

                            <h3>
                                الصافي:
                                {
                                    float(
                                        inv_data[
                                            'total_amount'
                                        ]
                                    )
                                    :,.2f
                                }
                                د.ل
                            </h3>

                        </body>
                        </html>
                        """

                        archive_print_inv = {
                            "inv_id": inv_data["id"],
                            "daily_inv_num": "-",
                            "branch": branch_name_display,
                            "cashier": "-",
                            "shift": inv_data["shift_status"],
                            "date_time": inv_data["created_at"],
                            "customer": inv_data["customer_name"],
                            "items": saved_items,
                            "gross_total": float(
                                details.get(
                                    "gross_total",
                                    inv_data["total_amount"]
                                ) or 0
                            ),
                            "discount_amount": float(
                                details.get("discount_amount", 0) or 0
                            ),
                            "total": float(inv_data["total_amount"] or 0),
                            "method": inv_data["payment_method"]
                        }

                        html_reprint_content = build_invoice_print_html(
                            archive_print_inv
                        )

                        st.info(
                            "🖨️ اضغط «طباعة الآن» داخل الفاتورة "
                            "لإعادة طباعتها."
                        )

                        st.components.v1.html(
                            html_reprint_content,
                            height=620,
                            scrolling=True
                        )

                        st.download_button(
                            "📥 تحميل الفاتورة "
                            "المسترجعة",
                            data=(
                                html_reprint_content
                                .encode(
                                    "utf-8"
                                )
                            ),
                            file_name=(
                                f"Invoice_Reprint_"
                                f"{target_inv_id}.html"
                            ),
                            mime="text/html",
                            use_container_width=True
                        )

            else:

                st.info(
                    "📭 لا توجد فواتير "
                    "مبيعات سابقة."
                )

            st.markdown("---")

            # =================================================
            # أرشيف التزويد
            # =================================================

            st.markdown(
                "### 📦 أرشيف التزويد "
                "الوارد للفرع"
            )

            branch_transfers = conn.execute(
                """
                SELECT
                    id,
                    items_details,
                    status,
                    transfer_date
                FROM transfer_logs
                WHERE to_branch_id = ?
                ORDER BY id DESC
                LIMIT 100
                """,
                (b_id,)
            ).fetchall()

            if branch_transfers:

                transfer_data = [
                    {
                        "رقم التزويد":
                            r["id"],
                        "التاريخ":
                            r["transfer_date"],
                        "الحالة":
                            r["status"],
                        "التفاصيل":
                            r["items_details"]
                    }
                    for r in branch_transfers
                ]

                st.dataframe(
                    transfer_data,
                    use_container_width=True,
                    hide_index=True
                )

            else:

                st.info(
                    "لا توجد حركات تزويد "
                    "مسجلة لهذا الفرع."
                )

    except Exception as e:

        st.error(
            "❌ حدث خطأ داخل شاشة "
            "نقطة البيع."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()
