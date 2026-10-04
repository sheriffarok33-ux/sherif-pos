import streamlit as st
import pandas as pd
import io
from datetime import datetime
from database import get_db_connection


def _excel_bytes(df, sheet_name):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return output.getvalue()


def _set_mode(mode):
    st.session_state["parties_mode"] = mode
    st.rerun()


def _current_shift_number():
    hour = datetime.now().hour
    return 1 if 6 <= hour < 16 else 2


def _table_columns(conn, table_name):
    """Return SQLite column names without changing the local database schema."""
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_voucher_schema(conn):
    """Local-first voucher archive. Safe to run repeatedly on SQLite."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_no TEXT UNIQUE NOT NULL,
            voucher_type TEXT NOT NULL,
            party_type TEXT NOT NULL,
            party_id INTEGER,
            party_name TEXT NOT NULL,
            branch_id INTEGER,
            user_id INTEGER,
            amount REAL NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_financial_vouchers_type_date "
        "ON financial_vouchers(voucher_type, created_at)"
    )
    conn.commit()


def _next_voucher_no(conn, voucher_type):
    """PAY-000001 for supplier payments, REC-000001 for customer receipts."""
    prefix = "PAY" if voucher_type == "دفع" else "REC"
    row = conn.execute(
        """
        SELECT voucher_no
        FROM financial_vouchers
        WHERE voucher_type = ?
          AND voucher_no LIKE ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (voucher_type, f"{prefix}-%")
    ).fetchone()
    last_num = 0
    if row and row["voucher_no"]:
        try:
            last_num = int(str(row["voucher_no"]).rsplit("-", 1)[-1])
        except Exception:
            last_num = 0
    return f"{prefix}-{last_num + 1:06d}"


def _save_voucher(conn, voucher_type, party_type, party_id, party_name,
                  branch_id, user_id, amount, notes):
    # Retry protects against a rare duplicate number if two users save together.
    for _ in range(5):
        voucher_no = _next_voucher_no(conn, voucher_type)
        try:
            conn.execute(
                """
                INSERT INTO financial_vouchers
                (voucher_no, voucher_type, party_type, party_id, party_name,
                 branch_id, user_id, amount, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    voucher_no, voucher_type, party_type, party_id, party_name,
                    branch_id, user_id, float(amount), notes
                )
            )
            return voucher_no
        except Exception as exc:
            if "UNIQUE" not in str(exc).upper():
                raise
    raise RuntimeError("تعذر إنشاء رقم إيصال مسلسل جديد.")


def show_page():
    st.header("👥 الموردون والعملاء والحسابات")
    st.info("الإضافة، التعديل، الحذف، السداد والتحصيل والتصدير من شاشة واحدة.")

    if st.session_state.get("last_party_voucher"):
        st.success(st.session_state.pop("last_party_voucher"))

    if "parties_mode" not in st.session_state:
        st.session_state["parties_mode"] = "suppliers"

    r1 = st.columns(6)
    if r1[0].button("🚛 الموردون", use_container_width=True):
        _set_mode("suppliers")
    if r1[1].button("🤝 العملاء", use_container_width=True):
        _set_mode("customers")
    if r1[2].button("➕ إضافة جهة", use_container_width=True):
        _set_mode("add")
    if r1[3].button("💳 دفع لمورد", use_container_width=True):
        _set_mode("supplier_payment")
    if r1[4].button("💵 تحصيل عميل", use_container_width=True):
        _set_mode("customer_collection")
    if r1[5].button("🧾 أرشيف الإيصالات", use_container_width=True):
        _set_mode("vouchers")

    conn = get_db_connection()
    try:
        _ensure_voucher_schema(conn)
        mode = st.session_state["parties_mode"]

        if mode == "add":
            if "party_add_type" not in st.session_state:
                st.session_state["party_add_type"] = "supplier"

            t1, t2 = st.columns(2)
            if t1.button("🚛 مورد جديد", use_container_width=True):
                st.session_state["party_add_type"] = "supplier"
                st.rerun()
            if t2.button("🤝 عميل آجل جديد", use_container_width=True):
                st.session_state["party_add_type"] = "customer"
                st.rerun()

            kind = st.session_state["party_add_type"]
            with st.form("party_add_form", clear_on_submit=True):
                c1, c2 = st.columns(2)
                name = c1.text_input("الاسم:")
                phone = c2.text_input("رقم الهاتف:")
                submit = st.form_submit_button("💾 حفظ", type="primary", use_container_width=True)

            if submit:
                if not name.strip():
                    st.warning("أدخل الاسم.")
                else:
                    try:
                        if kind == "supplier":
                            conn.execute(
                                "INSERT INTO suppliers (supplier_name, phone, balance) VALUES (?, ?, 0.0)",
                                (name.strip(), phone.strip())
                            )
                        else:
                            conn.execute(
                                "INSERT INTO customers (customer_name, phone, total_purchases, balance) VALUES (?, ?, 0.0, 0.0)",
                                (name.strip(), phone.strip())
                            )
                        conn.commit()
                        st.success("✅ تم الحفظ.")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error("تعذر الحفظ؛ قد يكون الاسم أو الهاتف مسجلاً.")
                        st.code(str(e))

        elif mode == "suppliers":
            rows = conn.execute(
                "SELECT id, supplier_name, phone, balance FROM suppliers ORDER BY supplier_name"
            ).fetchall()
            if not rows:
                st.info("لا يوجد موردون.")
            else:
                df = pd.DataFrame([{
                    "id": r["id"], "اسم المورد": r["supplier_name"],
                    "الهاتف": r["phone"] or "", "الرصيد": float(r["balance"] or 0)
                } for r in rows])
                edited = st.data_editor(
                    df, hide_index=True, use_container_width=True, num_rows="fixed",
                    disabled=["id", "الرصيد"],
                    key="suppliers_editor"
                )
                c1, c2 = st.columns(2)
                if c1.button("💾 حفظ تعديلات الموردين", type="primary", use_container_width=True):
                    try:
                        for _, r in edited.iterrows():
                            conn.execute(
                                "UPDATE suppliers SET supplier_name=?, phone=? WHERE id=?",
                                (str(r["اسم المورد"]).strip(), str(r["الهاتف"]).strip(), int(r["id"]))
                            )
                        conn.commit()
                        st.success("✅ تم حفظ التعديلات.")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error(str(e))
                c2.download_button(
                    "📥 تصدير الموردين Excel",
                    _excel_bytes(df.drop(columns=["id"]), "Suppliers"),
                    "suppliers.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

                labels = {f"{r['supplier_name']} | {r['phone'] or '-'}": r for r in rows}
                sel = labels[st.selectbox("اختر موردًا للحذف:", list(labels), key="delete_supplier_select")]
                if st.button("🗑️ حذف المورد المختار", use_container_width=True):
                    if abs(float(sel["balance"] or 0)) > 1e-9:
                        st.error("لا يمكن حذف مورد له رصيد غير مسفّر. صفّر الحساب أولاً.")
                    else:
                        try:
                            used = conn.execute(
                                "SELECT 1 FROM purchases WHERE supplier_id=? LIMIT 1", (sel["id"],)
                            ).fetchone()
                            if used:
                                st.error("لا يمكن حذف المورد لأنه مرتبط بفواتير مشتريات محفوظة.")
                            else:
                                conn.execute("DELETE FROM suppliers WHERE id=?", (sel["id"],))
                                conn.commit()
                                st.success("✅ تم حذف المورد.")
                                st.rerun()
                        except Exception as e:
                            conn.rollback()
                            st.error(str(e))

        elif mode == "customers":
            customer_columns = _table_columns(conn, "customers")
            total_expr = "total_purchases" if "total_purchases" in customer_columns else "0.0 AS total_purchases"
            balance_expr = "balance" if "balance" in customer_columns else "0.0 AS balance"
            created_expr = "created_at" if "created_at" in customer_columns else "NULL AS created_at"
            rows = conn.execute(
                f"SELECT id, customer_name, phone, {total_expr}, {balance_expr}, {created_expr} "
                "FROM customers ORDER BY customer_name"
            ).fetchall()
            if not rows:
                st.info("لا يوجد عملاء.")
            else:
                df = pd.DataFrame([{
                    "id": r["id"], "اسم العميل": r["customer_name"],
                    "الهاتف": r["phone"] or "",
                    "إجمالي المشتريات": float(r["total_purchases"] or 0),
                    "الرصيد": float(r["balance"] or 0),
                    "تاريخ التسجيل": r["created_at"]
                } for r in rows])
                edited = st.data_editor(
                    df, hide_index=True, use_container_width=True, num_rows="fixed",
                    disabled=["id", "إجمالي المشتريات", "الرصيد", "تاريخ التسجيل"],
                    key="customers_editor"
                )
                c1, c2 = st.columns(2)
                if c1.button("💾 حفظ تعديلات العملاء", type="primary", use_container_width=True):
                    try:
                        for _, r in edited.iterrows():
                            conn.execute(
                                "UPDATE customers SET customer_name=?, phone=? WHERE id=?",
                                (str(r["اسم العميل"]).strip(), str(r["الهاتف"]).strip(), int(r["id"]))
                            )
                        conn.commit()
                        st.success("✅ تم حفظ التعديلات.")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error(str(e))
                c2.download_button(
                    "📥 تصدير العملاء Excel",
                    _excel_bytes(df.drop(columns=["id"]), "Customers"),
                    "customers.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

        elif mode == "supplier_payment":
            rows = conn.execute(
                "SELECT id, supplier_name, balance FROM suppliers ORDER BY supplier_name"
            ).fetchall()
            if not rows:
                st.info("لا يوجد موردون.")
            else:
                opts = {f"{r['supplier_name']} | الرصيد: {float(r['balance'] or 0):,.2f}": r for r in rows}
                label = st.selectbox("اختر المورد:", list(opts))
                supplier = opts[label]
                amount = st.number_input("المبلغ المدفوع (د.ل):", min_value=0.0, step=10.0)
                if st.button("✅ تسجيل الدفعة", type="primary", use_container_width=True):
                    if amount <= 0:
                        st.warning("أدخل مبلغًا أكبر من صفر.")
                    else:
                        branch_id = st.session_state.get("branch_id")
                        user_id = st.session_state.get("user_id")
                        if not branch_id:
                            st.error("⚠️ المستخدم غير مرتبط بفرع؛ لا يمكن تسجيل الدفعة.")
                            return

                        conn.execute(
                            "UPDATE suppliers SET balance = balance - ? WHERE id = ?",
                            (amount, supplier["id"])
                        )
                        conn.execute(
                            """
                            INSERT INTO supplier_payments
                            (supplier_id, branch_id, user_id, amount, shift_number, notes)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                supplier["id"],
                                branch_id,
                                user_id,
                                float(amount),
                                _current_shift_number(),
                                "دفعة من حساب مورد"
                            )
                        )
                        voucher_no = _save_voucher(
                            conn, "دفع", "مورد", supplier["id"],
                            supplier["supplier_name"], branch_id, user_id,
                            amount, "دفعة من حساب مورد"
                        )
                        conn.commit()
                        st.session_state["last_party_voucher"] = (
                            f"✅ تم تسجيل الدفعة وتحديث رصيد المورد. "
                            f"رقم إيصال الدفع: {voucher_no}"
                        )
                        st.rerun()

        elif mode == "customer_collection":
            rows = conn.execute(
                "SELECT id, customer_name, phone, balance FROM customers ORDER BY customer_name"
            ).fetchall()
            if not rows:
                st.info("لا يوجد عملاء.")
            else:
                opts = {
                    f"{r['customer_name']} ({r['phone'] or '-'}) | الرصيد: {float(r['balance'] or 0):,.2f}": r
                    for r in rows
                }
                label = st.selectbox("اختر العميل:", list(opts))
                customer = opts[label]
                amount = st.number_input("المبلغ المحصل (د.ل):", min_value=0.0, step=10.0)
                if st.button("✅ تسجيل التحصيل", type="primary", use_container_width=True):
                    if amount <= 0:
                        st.warning("أدخل مبلغًا أكبر من صفر.")
                    else:
                        branch_id = st.session_state.get("branch_id")
                        user_id = st.session_state.get("user_id")
                        if not branch_id:
                            st.error("⚠️ المستخدم غير مرتبط بفرع؛ لا يمكن تسجيل التحصيل.")
                            return
                        conn.execute(
                            "UPDATE customers SET balance = balance - ? WHERE id = ?",
                            (amount, customer["id"])
                        )
                        voucher_no = _save_voucher(
                            conn, "قبض", "عميل", customer["id"],
                            customer["customer_name"], branch_id, user_id,
                            amount, "تحصيل من حساب عميل"
                        )
                        conn.commit()
                        st.session_state["last_party_voucher"] = (
                            f"✅ تم تسجيل التحصيل وتحديث رصيد العميل. "
                            f"رقم إيصال القبض: {voucher_no}"
                        )
                        st.rerun()
        elif mode == "vouchers":
            st.subheader("🧾 أرشيف إيصالات الدفع والقبض")
            voucher_filter = st.selectbox(
                "نوع الإيصال:",
                ["الكل", "دفع", "قبض"],
                key="voucher_archive_type"
            )
            if voucher_filter == "الكل":
                rows = conn.execute(
                    """
                    SELECT voucher_no, voucher_type, party_type, party_name,
                           amount, notes, created_at
                    FROM financial_vouchers
                    ORDER BY datetime(created_at) DESC, id DESC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT voucher_no, voucher_type, party_type, party_name,
                           amount, notes, created_at
                    FROM financial_vouchers
                    WHERE voucher_type = ?
                    ORDER BY datetime(created_at) DESC, id DESC
                    """,
                    (voucher_filter,)
                ).fetchall()

            if not rows:
                st.info("لا توجد إيصالات مسجلة حتى الآن.")
            else:
                df = pd.DataFrame([{
                    "رقم الإيصال": r["voucher_no"],
                    "النوع": "إيصال دفع" if r["voucher_type"] == "دفع" else "إيصال قبض",
                    "الجهة": r["party_type"],
                    "الاسم": r["party_name"],
                    "المبلغ": float(r["amount"] or 0),
                    "البيان": r["notes"] or "",
                    "التاريخ والوقت": r["created_at"],
                } for r in rows])
                st.dataframe(df, hide_index=True, use_container_width=True)
                st.download_button(
                    "📥 تصدير الإيصالات Excel",
                    _excel_bytes(df, "Vouchers"),
                    "financial_vouchers.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )

    finally:
        conn.close()
