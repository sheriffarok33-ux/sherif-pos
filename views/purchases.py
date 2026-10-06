from views.ui_common import back_button
from views.ui_common import item_alerts
import streamlit as st
import html
from datetime import datetime, date
from database import get_db_connection
from offline_store import get_device_id
from views.documents import ensure_document_schema, register_document


def _ensure_purchase_document_schema(conn):
    try:
        conn.execute("ALTER TABLE purchases ADD COLUMN document_number TEXT")
    except Exception:
        pass
    ensure_document_schema(conn)

def _next_purchase_document_number(conn, branch_id):
    """رقم نظام ثابت وآمن نسبياً بين الأجهزة: فرع + بصمة جهاز + تسلسل محلي."""
    _ensure_purchase_document_schema(conn)
    device_tag = get_device_id().replace("-", "")[:4].upper()
    prefix = f"PUR-{int(branch_id):02d}-{device_tag}-"
    rows = conn.execute(
        "SELECT document_number FROM purchases WHERE document_number LIKE ?",
        (prefix + "%",)
    ).fetchall()
    seq = 0
    for r in rows:
        try:
            seq = max(seq, int(str(r["document_number"]).rsplit("-", 1)[-1]))
        except Exception:
            pass
    return f"{prefix}{seq + 1:06d}"


# ============================================================
# دفعات الصلاحية
# ============================================================

def ensure_inventory_batches_table(conn):
    """
    نفس جدول الدفعات المستخدم في المخزون وPOS.
    يتم إنشاؤه فقط إذا لم يكن موجوداً.
    """
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
    document_number,
    payment_type,
    purchase_cart
):

    conn = None

    try:

        invoice_number = (invoice_number or "").strip()
        document_number = (document_number or "").strip()
        if not document_number:
            raise ValueError("تعذر إنشاء رقم مستند المشتريات.")

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
        ensure_inventory_batches_table(conn)

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

        duplicate_invoice = None
        if invoice_number:
            duplicate_invoice = conn.execute(
                """SELECT id FROM purchases
                   WHERE supplier_id=? AND invoice_number=? LIMIT 1""",
                (supplier_id, invoice_number)
            ).fetchone()
        if duplicate_invoice:
            raise ValueError(f"فاتورة المورد رقم ({invoice_number}) مسجلة مسبقاً لهذا المورد.")

        duplicate_document = conn.execute(
            "SELECT id FROM purchases WHERE document_number=? LIMIT 1",
            (document_number,)
        ).fetchone()
        if duplicate_document:
            raise ValueError(f"رقم المستند ({document_number}) مستخدم مسبقاً.")

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

            expiry_date = purchase_item.get("expiry_date")

            if expiry_date:
                if hasattr(expiry_date, "isoformat"):
                    expiry_date_value = expiry_date
                else:
                    expiry_date_value = datetime.strptime(
                        str(expiry_date),
                        "%Y-%m-%d"
                    ).date()

                if expiry_date_value < date.today():
                    raise ValueError(
                        f"تاريخ انتهاء الصنف "
                        f"({purchase_item['name']}) "
                        "منتهي بالفعل."
                    )

                conn.execute(
                    """
                    INSERT INTO inventory_batches
                    (
                        item_id,
                        branch_id,
                        quantity,
                        remaining_quantity,
                        received_date,
                        expiry_date,
                        unit_cost,
                        source_type
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item_id,
                        branch_id,
                        purchased_qty,
                        purchased_qty,
                        datetime.now().date(),
                        expiry_date_value,
                        purchase_price,
                        "purchase"
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
                    + (
                        f" - انتهاء: {expiry_date_value}"
                        if expiry_date
                        else " - بدون تاريخ انتهاء"
                    )
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
                document_number,
                total_cost,
                payment_type,
                items_details,
                invoice_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                branch_id,
                supplier_id,
                supplier_name,
                invoice_number,
                document_number,
                grand_total,
                payment_type,
                "\n".join(details),
                datetime.now().date()
            )
        )

        purchase_row = conn.execute("SELECT id FROM purchases WHERE document_number=? LIMIT 1", (document_number,)).fetchone()
        purchase_id = purchase_row["id"]
        conn.execute("DELETE FROM purchase_items WHERE purchase_id=?", (purchase_id,))
        for purchase_item in purchase_cart:
            conn.execute("""INSERT INTO purchase_items
                (purchase_id,item_id,item_code,item_name,quantity,unit,unit_price,line_total,expiry_date)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (purchase_id, purchase_item.get("id"), purchase_item.get("code"), purchase_item.get("name"),
                 float(purchase_item.get("qty") or 0), purchase_item.get("unit") or "",
                 float(purchase_item.get("price") or 0), float(purchase_item.get("total") or 0),
                 purchase_item.get("expiry_date")))
        register_document(conn, document_number, "فاتورة مشتريات", "purchases", purchase_id,
                          invoice_number or None, branch_id, supplier_name, grand_total,
                          datetime.now().date().isoformat(), st.session_state.get("user_id"))

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

        # بعد نجاح الحفظ لا نمسح الفاتورة فوراً.
        # تظهر نافذة تأكيد، والتنظيف يتم عند ضغط "موافق".
        st.session_state["purchase_success_pending"] = True
        st.session_state["purchase_success_message"] = (
            f"تم ترحيل فاتورة المشتريات {document_number} بنجاح. "
            f"إجمالي الفاتورة: {grand_total:,.2f} د.ل"
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
# أرشيف وتقارير المشتريات
# ============================================================

def show_purchase_reports(branches, suppliers_data):
    st.markdown("### 📊 أرشيف وتقارير المشتريات")

    branch_map = {"كل الفروع": None}
    branch_map.update({b["branch_name"]: b["id"] for b in branches})
    supplier_map = {"كل الموردين": None}
    supplier_map.update({s["supplier_name"]: s["id"] for s in suppliers_data})

    today = date.today()
    month_start = today.replace(day=1)

    f1, f2 = st.columns(2)
    selected_supplier = f1.selectbox("المورد", list(supplier_map), key="purchase_report_supplier")
    selected_branch = f2.selectbox("الفرع / المخزن", list(branch_map), key="purchase_report_branch")

    d1, d2 = st.columns(2)
    date_from = d1.date_input("من تاريخ", value=month_start, key="purchase_report_from")
    date_to = d2.date_input("إلى تاريخ", value=today, key="purchase_report_to")

    if date_from > date_to:
        st.error("تاريخ البداية يجب أن يكون قبل أو مساوياً لتاريخ النهاية.")
        return

    where = ["date(p.invoice_date) BETWEEN date(?) AND date(?)"]
    params = [date_from.isoformat(), date_to.isoformat()]

    supplier_id = supplier_map[selected_supplier]
    if supplier_id is not None:
        where.append("p.supplier_id = ?")
        params.append(supplier_id)

    branch_id = branch_map[selected_branch]
    if branch_id is not None:
        where.append("p.branch_id = ?")
        params.append(branch_id)

    conn = None
    try:
        conn = get_db_connection()
        rows = conn.execute(
            f"""
            SELECT p.id, p.invoice_number, COALESCE(p.document_number, '') AS document_number, p.invoice_date, p.supplier_name,
                   COALESCE(br.branch_name, '') AS branch_name,
                   p.payment_type, COALESCE(p.total_cost, 0) AS total_cost,
                   COALESCE(p.items_details, '') AS items_details
            FROM purchases p
            LEFT JOIN branches br ON br.id = p.branch_id
            WHERE {' AND '.join(where)}
            ORDER BY date(p.invoice_date) DESC, p.id DESC
            """,
            tuple(params)
        ).fetchall()
    except Exception as e:
        st.error("❌ تعذر تحميل تقرير المشتريات.")
        st.code(str(e))
        return
    finally:
        if conn:
            conn.close()

    total_value = sum(float(r["total_cost"] or 0) for r in rows)
    m1, m2, m3 = st.columns(3)
    m1.metric("عدد الفواتير", len(rows))
    m2.metric("إجمالي المشتريات", f"{total_value:,.2f} د.ل")
    m3.metric("المورد", selected_supplier)

    if not rows:
        st.info("لا توجد فواتير مشتريات مطابقة للفترة والفلتر المحدد.")
        return

    table_rows = [{
        "رقم المستند": r["document_number"] or f"PUR-OLD-{r['id']}",
        "رقم فاتورة المورد": r["invoice_number"] or "-",
        "التاريخ": r["invoice_date"],
        "المورد": r["supplier_name"],
        "الفرع / المخزن": r["branch_name"],
        "طريقة الدفع": r["payment_type"],
        "الإجمالي": float(r["total_cost"] or 0),
    } for r in rows]

    st.dataframe(
        table_rows, use_container_width=True, hide_index=True,
        column_config={"الإجمالي": st.column_config.NumberColumn("الإجمالي", format="%.2f د.ل")}
    )

    def _purchase_items_lines(value):
        text = str(value or "").strip()
        if not text:
            return []
        # يدعم الفواتير القديمة المخزنة بعلامة | والجديدة المخزنة كسطور منفصلة
        text = text.replace(" | ", "\n")
        return [line.strip() for line in text.splitlines() if line.strip()]

    st.markdown("#### 🔎 تفاصيل الفواتير")
    for r in rows:
        with st.expander(
            f"فاتورة {r['document_number'] or ('PUR-OLD-' + str(r['id']))} — {r['supplier_name']} — "
            f"{float(r['total_cost'] or 0):,.2f} د.ل"
        ):
            st.write(f"**التاريخ:** {r['invoice_date']}")
            st.write(f"**الفرع / المخزن:** {r['branch_name'] or '-'}")
            st.write(f"**طريقة الدفع:** {r['payment_type'] or '-'}")
            st.markdown("**تفاصيل الأصناف:**")
            _detail_conn = get_db_connection()
            try:
                ensure_document_schema(_detail_conn)
                _item_rows = _detail_conn.execute("SELECT item_code,item_name,quantity,unit,unit_price,line_total,expiry_date FROM purchase_items WHERE purchase_id=? ORDER BY id", (r["id"],)).fetchall()
            finally:
                _detail_conn.close()
            if _item_rows:
                st.dataframe([{
                    "كود الصنف": x["item_code"] or "", "الصنف": x["item_name"],
                    "الكمية": float(x["quantity"] or 0), "الوحدة": x["unit"] or "",
                    "سعر الشراء": float(x["unit_price"] or 0), "الإجمالي": float(x["line_total"] or 0),
                    "الصلاحية": x["expiry_date"] or "—"} for x in _item_rows], use_container_width=True, hide_index=True)
                _lines = []
            else:
                _lines = _purchase_items_lines(r['items_details'])
            if _lines:
                _items_html = "".join(
                    f"<div style='direction:rtl;text-align:right;padding:7px 10px;border-bottom:1px solid #e5e7eb'>"
                    f"{html.escape(line)}</div>" for line in _lines
                )
                st.markdown(
                    f"<div dir='rtl' style='text-align:right;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden'>{_items_html}</div>",
                    unsafe_allow_html=True,
                )
            else:
                st.write("-")
            if _item_rows:
                _print_items_html = "".join(
                    f"<tr><td>{html.escape(str(x['item_code'] or ''))}</td><td>{html.escape(str(x['item_name']))}</td><td>{float(x['quantity'] or 0):,.3f}</td><td>{html.escape(str(x['unit'] or ''))}</td><td>{float(x['unit_price'] or 0):,.2f}</td><td>{float(x['line_total'] or 0):,.2f}</td><td>{html.escape(str(x['expiry_date'] or '-'))}</td></tr>"
                    for x in _item_rows)
                _print_items_head = "<tr><th>الكود</th><th>الصنف</th><th>الكمية</th><th>الوحدة</th><th>سعر الشراء</th><th>الإجمالي</th><th>الصلاحية</th></tr>"
            else:
                _print_items_html = "".join(f"<tr><td>{html.escape(line)}</td></tr>" for line in _lines) or "<tr><td>-</td></tr>"
                _print_items_head = "<tr><th>تفاصيل الصنف</th></tr>"
            invoice_html = f"""
            <html dir='rtl'><head><meta charset='utf-8'><style>
            body{{font-family:Arial;padding:24px;direction:rtl;text-align:right}} table{{width:100%;border-collapse:collapse;direction:rtl}}
            td{{border:1px solid #999;padding:8px}} .no-print{{margin-top:18px}}
            @media print{{.no-print{{display:none}}}}
            </style></head><body>
            <h2 style='text-align:center'>فاتورة مشتريات</h2>
            <table>
            <tr><td><b>رقم مستند النظام</b></td><td>{html.escape(str(r['document_number'] or ('PUR-OLD-' + str(r['id']))))}</td></tr>
            <tr><td><b>رقم فاتورة المورد</b></td><td>{html.escape(str(r['invoice_number'] or '-'))}</td></tr>
            <tr><td><b>التاريخ</b></td><td>{html.escape(str(r['invoice_date'] or '-'))}</td></tr>
            <tr><td><b>المورد</b></td><td>{html.escape(str(r['supplier_name'] or '-'))}</td></tr>
            <tr><td><b>الفرع / المخزن</b></td><td>{html.escape(str(r['branch_name'] or '-'))}</td></tr>
            <tr><td><b>طريقة الدفع</b></td><td>{html.escape(str(r['payment_type'] or '-'))}</td></tr>
            <tr><td><b>الإجمالي</b></td><td>{float(r['total_cost'] or 0):,.2f} د.ل</td></tr>
            </table>
            <h3 style='text-align:right'>الأصناف</h3>
            <table style='direction:rtl;text-align:right'><thead>{_print_items_head}</thead><tbody>{_print_items_html}</tbody></table>
            <div class='no-print'><button onclick='window.print()'>🖨️ طباعة</button></div>
            </body></html>"""
            pc1, pc2 = st.columns(2)
            preview_key = f"purchase_preview_{r['id']}"
            if pc1.button("👁️ معاينة", key=f"preview_purchase_{r['id']}", use_container_width=True):
                st.session_state[preview_key] = not st.session_state.get(preview_key, False)
            if pc2.button("🖨️ طباعة", key=f"print_purchase_{r['id']}", use_container_width=True):
                st.session_state[preview_key] = True
            if st.session_state.get(preview_key):
                st.components.v1.html(invoice_html, height=520, scrolling=True)


# ============================================================
# الصفحة
# ============================================================

@st.dialog("✅ تمت العملية بنجاح")
def _purchase_success_dialog():
    st.success(
        st.session_state.get(
            "purchase_success_message",
            "تم ترحيل فاتورة المشتريات بنجاح."
        )
    )
    st.info("تم حفظ الفاتورة وتحديث المخزون. اضغط موافق لبدء فاتورة جديدة.")
    if st.button(
        "موافق",
        type="primary",
        use_container_width=True,
        key="purchase_success_ok"
    ):
        # تنظيف بيانات الفاتورة لا يتم إلا بعد تأكيد المستخدم.
        st.session_state["purch_cart"] = []
        for key in [
            "purch_cart_branch_id",
            "purch_cart_supplier_id",
            "purchase_expiry_date",
        ]:
            st.session_state.pop(key, None)
        st.session_state.pop("purchase_success_pending", None)
        st.session_state.pop("purchase_success_message", None)
        for _k in list(st.session_state.keys()):
            if str(_k).startswith("purchase_document_number_"):
                st.session_state.pop(_k, None)
        st.rerun()



@st.dialog("⚠️ مراجعة العملية قبل التنفيذ")
def _purchase_confirm_confirm_dialog():
    pending = st.session_state.get("purchase_confirm_pending_action")
    if not pending:
        return
    st.warning("راجع البيانات جيدًا. لن يتم تنفيذ أي تغيير قبل التأكيد.")
    for label, value in pending.get("summary", []):
        st.write(f"**{label}:** {value}")
    c1, c2 = st.columns(2)
    if c1.button("✅ تأكيد التنفيذ", type="primary", use_container_width=True, key="purchase_confirm_confirm_yes"):
        callback = pending.get("callback")
        args = pending.get("args", [])
        kwargs = pending.get("kwargs", {})
        st.session_state.pop("purchase_confirm_pending_action", None)
        callback(*args, **kwargs)
    if c2.button("❌ إلغاء", use_container_width=True, key="purchase_confirm_confirm_no"):
        st.session_state.pop("purchase_confirm_pending_action", None)
        st.rerun()


def show_page():
    back_button(key="back_purchases")
    item_alerts(st.session_state.get("branch_id"), key="alerts_purchases")

    if st.session_state.get("purchase_confirm_pending_action"):
        _purchase_confirm_confirm_dialog()
        st.stop()

    if st.session_state.get("purchase_success_pending"):
        _purchase_success_dialog()


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

    if not st.session_state.get("purchases_entry_lock"):
        st.markdown(
            "### ⚙️ الإدارة السريعة "
            "لجهات التعامل"
        )
    
        if "purchase_quick_mode" not in st.session_state:
            st.session_state["purchase_quick_mode"] = "invoice"
    
        purchase_modes = {"🛒 فاتورة مشتريات":"invoice", "📊 الأرشيف والتقارير":"reports"}
        current_label = next((k for k,v in purchase_modes.items() if v == st.session_state["purchase_quick_mode"]), list(purchase_modes)[0])
        selected_label = st.selectbox("اختر العملية:", list(purchase_modes), index=list(purchase_modes).index(current_label), key="purchase_action_dropdown")
        selected_value = purchase_modes[selected_label]
        if selected_value != st.session_state["purchase_quick_mode"]:
            st.session_state["purchase_quick_mode"] = selected_value
            st.rerun()
    
    quick_mode = st.session_state["purchase_quick_mode"]

    if quick_mode == "reports":
        show_purchase_reports(branches, suppliers_data)
        return

    # ========================================================
    # مورد جديد
    # ========================================================
    if quick_mode == "supplier":
        st.markdown("#### ➕ إضافة مورد جديد")
        with st.form(
            "quick_sup_form_clean",
            clear_on_submit=True
        ):
            qc1, qc2 = st.columns(2)
            q_sname = qc1.text_input("اسم المورد / الشركة:")
            q_sphone = qc2.text_input("رقم الهاتف:")
            submit_supplier = st.form_submit_button(
                "💾 حفظ المورد الجديد",
                type="primary",
                use_container_width=True
            )

        if submit_supplier:
            add_supplier(q_sname, q_sphone)

        st.info("بعد الحفظ اضغط «🛒 فاتورة توريد» للعودة إلى الفاتورة.")
        return

    # ========================================================
    # زبون آجل جديد
    # ========================================================
    if quick_mode == "customer":
        st.markdown("#### ➕ إضافة زبون آجل جديد")
        with st.form(
            "quick_cust_form_clean",
            clear_on_submit=True
        ):
            qcc1, qcc2 = st.columns(2)
            q_cname = qcc1.text_input("اسم الزبون الآجل:")
            q_cphone = qcc2.text_input("رقم الهاتف:")
            submit_customer = st.form_submit_button(
                "💾 حفظ واعتماد الزبون الآجل",
                type="primary",
                use_container_width=True
            )

        if submit_customer:
            add_customer(q_cname, q_cphone)

        st.info("بعد الحفظ اضغط «🛒 فاتورة توريد» للعودة إلى الفاتورة.")
        return

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
        "🧾 رقم فاتورة المورد (اختياري):"
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

    # رقم مستند النظام ينشأ تلقائياً ويظل ثابتاً طوال الفاتورة المفتوحة.
    doc_key = f"purchase_document_number_{selected_branch_id}"
    if not st.session_state.get(doc_key):
        _doc_conn = get_db_connection()
        try:
            st.session_state[doc_key] = _next_purchase_document_number(_doc_conn, selected_branch_id)
        finally:
            _doc_conn.close()
    document_number = st.session_state[doc_key]
    st.text_input("🔒 رقم مستند النظام", value=document_number, disabled=True, key=f"purchase_doc_display_{selected_branch_id}")

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

            col_i1, col_i2, col_i3, col_i4 = (
                st.columns([2, 1, 1, 1.25])
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

            has_expiry = col_i4.checkbox(
                "له تاريخ انتهاء",
                value=False
            )

            purchase_expiry_date = None

            if has_expiry:
                purchase_expiry_date = st.date_input(
                    "📅 تاريخ انتهاء هذه الدفعة:",
                    value=date.today(),
                    min_value=date.today(),
                    key="purchase_expiry_date"
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
                        cart_item["id"] == selected_item["id"]
                        and cart_item.get("expiry_date")
                        == (
                            purchase_expiry_date.isoformat()
                            if purchase_expiry_date
                            else None
                        )
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

                            "expiry_date":
                                (
                                    purchase_expiry_date.isoformat()
                                    if purchase_expiry_date
                                    else None
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

        cart_rows = []
        for index, purchase_item in enumerate(st.session_state["purch_cart"], start=1):
            cart_rows.append({
                "#": index,
                "كود الصنف": purchase_item["code"],
                "الصنف": purchase_item["name"],
                "الكمية": float(purchase_item["qty"]),
                "سعر الشراء": float(purchase_item["price"]),
                "الإجمالي": float(purchase_item["total"]),
                "الصلاحية": purchase_item.get("expiry_date") or "—",
            })
        st.dataframe(
            cart_rows, use_container_width=True, hide_index=True,
            column_config={
                "الكمية": st.column_config.NumberColumn("الكمية", format="%.3f"),
                "سعر الشراء": st.column_config.NumberColumn("سعر الشراء", format="%.2f د.ل"),
                "الإجمالي": st.column_config.NumberColumn("الإجمالي", format="%.2f د.ل"),
            }
        )
        d1, d2 = st.columns([3, 1])
        delete_index = d1.selectbox(
            "حذف سطر من الفاتورة",
            list(range(len(st.session_state["purch_cart"]))),
            format_func=lambda i: f"{i+1} - {st.session_state['purch_cart'][i]['name']}",
            key="purchase_delete_line"
        )
        if d2.button("🗑️ حذف السطر", use_container_width=True):
            st.session_state["purch_cart"].pop(delete_index)
            if not st.session_state["purch_cart"]:
                st.session_state.pop("purch_cart_branch_id", None)
                st.session_state.pop("purch_cart_supplier_id", None)
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

            st.session_state["purchase_confirm_pending_action"] = {
                "callback": post_purchase_invoice,
                "kwargs": {
                    "branch_id": selected_branch_id,
                    "supplier_id": selected_supplier_id,
                    "supplier_name": ps,
                    "invoice_number": inv_num,
                    "document_number": document_number,
                    "payment_type": payment_type,
                    "purchase_cart": list(st.session_state["purch_cart"]),
                },
                "summary": [
                    ("العملية", "اعتماد فاتورة مشتريات"),
                    ("رقم مستند النظام", document_number),
                    ("رقم فاتورة المورد", inv_num or "-"),
                    ("المورد", ps),
                    ("طريقة الدفع", payment_type),
                    ("عدد الأصناف", str(len(st.session_state["purch_cart"]))),
                    ("إجمالي الفاتورة", f"{float(grand_total):,.2f} د.ل"),
                ],
            }
            st.rerun()
