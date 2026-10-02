import streamlit as st
import pandas as pd
import io
from datetime import datetime
from database import get_db_connection, ensure_pos_extensions_schema
ء

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


def show_page():
    try:
        ensure_pos_extensions_schema()
    except Exception as e:
        st.error("❌ تعذر تجهيز سجل دفعات الموردين.")
        st.code(str(e))
        return

    st.header("👥 الموردون والعملاء والحسابات")
    st.info("الإضافة، التعديل، الحذف، السداد والتحصيل والتصدير من شاشة واحدة.")

    if "parties_mode" not in st.session_state:
        st.session_state["parties_mode"] = "suppliers"

    r1 = st.columns(5)
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

    conn = get_db_connection()
    try:
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
            rows = conn.execute(
                "SELECT id, customer_name, phone, total_purchases, balance, created_at "
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
                        conn.commit()
                        st.success("✅ تم تسجيل الدفعة وتحديث رصيد المورد.")
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
                        conn.execute(
                            "UPDATE customers SET balance = balance - ? WHERE id = ?",
                            (amount, customer["id"])
                        )
                        conn.commit()
                        st.success("✅ تم تسجيل التحصيل وتحديث رصيد العميل.")
                        st.rerun()
    finally:
        conn.close()
