from views.ui_common import back_button
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
    cols = _table_columns(conn, "financial_vouchers")
    if "treasury_id" not in cols:
        conn.execute("ALTER TABLE financial_vouchers ADD COLUMN treasury_id INTEGER")
    if "treasury_name" not in cols:
        conn.execute("ALTER TABLE financial_vouchers ADD COLUMN treasury_name TEXT")
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
                  branch_id, user_id, amount, notes, treasury_id=None, treasury_name=None):
    # Retry protects against a rare duplicate number if two users save together.
    for _ in range(5):
        voucher_no = _next_voucher_no(conn, voucher_type)
        try:
            conn.execute(
                """
                INSERT INTO financial_vouchers
                (voucher_no, voucher_type, party_type, party_id, party_name,
                 branch_id, user_id, amount, notes, treasury_id, treasury_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    voucher_no, voucher_type, party_type, party_id, party_name,
                    branch_id, user_id, float(amount), notes, treasury_id, treasury_name
                )
            )
            return voucher_no
        except Exception as exc:
            if "UNIQUE" not in str(exc).upper():
                raise
    raise RuntimeError("تعذر إنشاء رقم إيصال مسلسل جديد.")


@st.dialog("✅ تمت العملية بنجاح")
def _parties_success_dialog():
    st.success(st.session_state.get("parties_success_message", "تمت العملية بنجاح."))
    if st.session_state.get("last_voucher_html"):
        st.download_button("🖨️ طباعة / حفظ السند", st.session_state["last_voucher_html"].encode("utf-8"), file_name=f"{st.session_state.get('last_voucher_no','voucher')}.html", mime="text/html", use_container_width=True)
    if st.button("موافق", type="primary", use_container_width=True, key="parties_success_ok"):
        st.session_state.pop("parties_success_pending", None)
        st.session_state.pop("parties_success_message", None)
        st.rerun()


def _parties_done(message):
    st.session_state["parties_success_message"] = message
    st.session_state["parties_success_pending"] = True
    st.rerun()



def _ensure_treasury_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS treasuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            treasury_name TEXT NOT NULL UNIQUE,
            treasury_type TEXT NOT NULL DEFAULT 'branch',
            branch_id INTEGER,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS treasury_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            treasury_id INTEGER NOT NULL,
            movement_type TEXT NOT NULL,
            amount REAL NOT NULL,
            voucher_no TEXT,
            description TEXT,
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    exists = conn.execute("SELECT id FROM treasuries WHERE treasury_name='خزينة الشركة' LIMIT 1").fetchone()
    if not exists:
        conn.execute("INSERT INTO treasuries(treasury_name,treasury_type,branch_id) VALUES('خزينة الشركة','company',NULL)")
    branches=conn.execute("SELECT id, branch_name FROM branches ORDER BY branch_name").fetchall()
    for b in branches:
        treasury_name = f"خزينة فرع {b['branch_name']}"
        exists = conn.execute("SELECT id FROM treasuries WHERE treasury_name=? LIMIT 1", (treasury_name,)).fetchone()
        if not exists:
            conn.execute("INSERT INTO treasuries(treasury_name,treasury_type,branch_id) VALUES(?, 'branch', ?)", (treasury_name, b["id"]))
    conn.commit()

def _voucher_html(voucher_no, voucher_type, party_type, party_name, amount, notes, treasury_name, created_at=None):
    title = "سند دفع" if voucher_type == "دفع" else "سند قبض"
    dt = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"""<!doctype html><html dir="rtl"><head><meta charset="utf-8"><title>{title} {voucher_no}</title>
<style>body{{font-family:Arial;direction:rtl;margin:35px}}.box{{border:2px solid #222;padding:25px}}h1{{text-align:center}}table{{width:100%;border-collapse:collapse}}td{{padding:10px;border-bottom:1px solid #aaa}}.sig{{margin-top:55px;display:flex;justify-content:space-between}}</style></head>
<body><div class="box"><h1>{title}</h1><table>
<tr><td><b>رقم السند</b></td><td>{voucher_no}</td><td><b>التاريخ والوقت</b></td><td>{dt}</td></tr>
<tr><td><b>الخزينة</b></td><td>{treasury_name}</td><td><b>الجهة</b></td><td>{party_type}</td></tr>
<tr><td><b>الاسم</b></td><td>{party_name}</td><td><b>المبلغ</b></td><td>{float(amount):,.2f} د.ل</td></tr>
<tr><td><b>البيان</b></td><td colspan="3">{notes or '-'}</td></tr>
</table><div class="sig"><span>توقيع المستلم: __________</span><span>المحاسب: __________</span><span>الاعتماد: __________</span></div></div>
<script>window.onload=function(){{window.print();}}</script></body></html>"""

def _treasury_options(conn):
    _ensure_treasury_schema(conn)
    rows=conn.execute("SELECT id,treasury_name,treasury_type,branch_id FROM treasuries WHERE is_active=1 ORDER BY CASE WHEN treasury_type='company' THEN 0 ELSE 1 END, treasury_name").fetchall()
    return {r["treasury_name"]: r for r in rows}


def show_page():
    back_button(key="back_parties")

    if st.session_state.get("parties_success_pending"):
        _parties_success_dialog()

    st.header("👥 الموردون والعملاء والحسابات")
    st.info("الإضافة، التعديل، الحذف، السداد والتحصيل والتصدير من شاشة واحدة.")

    if "parties_mode" not in st.session_state:
        st.session_state["parties_mode"] = "suppliers"

    if not st.session_state.get("parties_entry_lock"):
        party_modes = {
            "🚛 الموردون": "suppliers",
            "🤝 العملاء": "customers",
            "➕ إضافة جهة": "add",
        }
        current_label = next((k for k,v in party_modes.items() if v == st.session_state["parties_mode"]), list(party_modes)[0])
        selected_label = st.selectbox("اختر العملية:", list(party_modes), index=list(party_modes).index(current_label), key="parties_action_dropdown")
        selected_mode = party_modes[selected_label]
        if selected_mode != st.session_state["parties_mode"]:
            st.session_state["parties_mode"] = selected_mode
            st.rerun()
    
    conn = get_db_connection()
    try:
        _ensure_voucher_schema(conn)
        _ensure_treasury_schema(conn)
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
                        _parties_done("تم الحفظ بنجاح.")
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
                        _parties_done("تم حفظ تعديلات الموردين بنجاح.")
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
                                _parties_done("تم حذف المورد بنجاح.")
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
                        _parties_done("تم حفظ تعديلات العملاء بنجاح.")
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
            rows = conn.execute("SELECT id, supplier_name, balance FROM suppliers ORDER BY supplier_name").fetchall()
            if not rows:
                st.info("لا يوجد موردون.")
            else:
                opts={f"{r['supplier_name']} | الرصيد: {float(r['balance'] or 0):,.2f}":r for r in rows}
                supplier=opts[st.selectbox("اختر المورد:",list(opts))]
                treasuries=_treasury_options(conn)
                treasury=treasuries[st.selectbox("🏦 الخزينة التي سيتم الدفع منها:",list(treasuries),key="pay_treasury")]
                amount=st.number_input("المبلغ المدفوع (د.ل):",min_value=0.0,step=10.0,key="supplier_pay_amount")
                notes=st.text_input("البيان:",value="دفعة من حساب مورد",key="supplier_pay_notes")
                if st.button("✅ تسجيل سند الدفع",type="primary",use_container_width=True):
                    if amount<=0: st.warning("أدخل مبلغًا أكبر من صفر.")
                    else:
                        user_id=st.session_state.get("user_id")
                        branch_id=treasury["branch_id"]
                        conn.execute("UPDATE suppliers SET balance=balance-? WHERE id=?",(amount,supplier["id"]))
                        if branch_id:
                            conn.execute("""INSERT INTO supplier_payments(supplier_id,branch_id,user_id,amount,shift_number,notes) VALUES(?,?,?,?,?,?)""",(supplier["id"],branch_id,user_id,float(amount),_current_shift_number(),notes))
                        voucher_no=_save_voucher(conn,"دفع","مورد",supplier["id"],supplier["supplier_name"],branch_id,user_id,amount,notes,treasury["id"],treasury["treasury_name"])
                        conn.execute("""INSERT INTO treasury_movements(treasury_id,movement_type,amount,voucher_no,description,user_id) VALUES(?,?,?,?,?,?)""",(treasury["id"],"دفع",-float(amount),voucher_no,notes,user_id))
                        conn.commit()
                        html=_voucher_html(voucher_no,"دفع","مورد",supplier["supplier_name"],amount,notes,treasury["treasury_name"])
                        st.session_state["last_voucher_html"]=html
                        st.session_state["last_voucher_no"]=voucher_no
                        _parties_done(f"تم تسجيل سند الدفع {voucher_no} من {treasury['treasury_name']}.")

        elif mode == "customer_collection":
            rows=conn.execute("SELECT id,customer_name,phone,balance FROM customers ORDER BY customer_name").fetchall()
            if not rows: st.info("لا يوجد عملاء.")
            else:
                opts={f"{r['customer_name']} ({r['phone'] or '-'}) | الرصيد: {float(r['balance'] or 0):,.2f}":r for r in rows}
                customer=opts[st.selectbox("اختر العميل:",list(opts))]
                treasuries=_treasury_options(conn)
                treasury=treasuries[st.selectbox("🏦 الخزينة التي سيتم القبض فيها:",list(treasuries),key="rec_treasury")]
                amount=st.number_input("المبلغ المحصل (د.ل):",min_value=0.0,step=10.0,key="customer_rec_amount")
                notes=st.text_input("البيان:",value="تحصيل من حساب عميل",key="customer_rec_notes")
                if st.button("✅ تسجيل سند القبض",type="primary",use_container_width=True):
                    if amount<=0: st.warning("أدخل مبلغًا أكبر من صفر.")
                    else:
                        user_id=st.session_state.get("user_id"); branch_id=treasury["branch_id"]
                        conn.execute("UPDATE customers SET balance=balance-? WHERE id=?",(amount,customer["id"]))
                        voucher_no=_save_voucher(conn,"قبض","عميل",customer["id"],customer["customer_name"],branch_id,user_id,amount,notes,treasury["id"],treasury["treasury_name"])
                        conn.execute("""INSERT INTO treasury_movements(treasury_id,movement_type,amount,voucher_no,description,user_id) VALUES(?,?,?,?,?,?)""",(treasury["id"],"قبض",float(amount),voucher_no,notes,user_id))
                        conn.commit()
                        html=_voucher_html(voucher_no,"قبض","عميل",customer["customer_name"],amount,notes,treasury["treasury_name"])
                        st.session_state["last_voucher_html"]=html
                        st.session_state["last_voucher_no"]=voucher_no
                        _parties_done(f"تم تسجيل سند القبض {voucher_no} في {treasury['treasury_name']}.")

        elif mode == "treasuries":
            st.subheader("🏦 خزينة الشركة وخزائن الفروع")
            treasuries=_treasury_options(conn)
            # balances
            data=[]
            for name,t in treasuries.items():
                bal=conn.execute("SELECT COALESCE(SUM(amount),0) AS balance FROM treasury_movements WHERE treasury_id=?",(t["id"],)).fetchone()["balance"]
                data.append({"الخزينة":name,"الرصيد الحالي":float(bal or 0)})
            st.dataframe(pd.DataFrame(data),hide_index=True,use_container_width=True)
            st.markdown("#### 🔁 تحويل بين الخزائن")
            names=list(treasuries)
            c1,c2,c3=st.columns(3)
            src_name=c1.selectbox("من خزينة:",names,key="treasury_from")
            dst_names=[n for n in names if n!=src_name]
            dst_name=c2.selectbox("إلى خزينة:",dst_names,key="treasury_to")
            transfer_amount=c3.number_input("المبلغ:",min_value=0.0,step=10.0,key="treasury_transfer_amount")
            transfer_notes=st.text_input("البيان:",value="تحويل بين الخزائن",key="treasury_transfer_notes")
            if st.button("🔁 تنفيذ التحويل بين الخزائن",type="primary",use_container_width=True):
                if transfer_amount<=0: st.warning("أدخل مبلغًا أكبر من صفر.")
                else:
                    src=treasuries[src_name]; dst=treasuries[dst_name]; user_id=st.session_state.get("user_id")
                    ref=f"TR-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    conn.execute("INSERT INTO treasury_movements(treasury_id,movement_type,amount,voucher_no,description,user_id) VALUES(?,?,?,?,?,?)",(src["id"],"تحويل صادر",-float(transfer_amount),ref,transfer_notes,user_id))
                    conn.execute("INSERT INTO treasury_movements(treasury_id,movement_type,amount,voucher_no,description,user_id) VALUES(?,?,?,?,?,?)",(dst["id"],"تحويل وارد",float(transfer_amount),ref,transfer_notes,user_id))
                    conn.commit()
                    _parties_done(f"تم تحويل {float(transfer_amount):,.2f} د.ل من {src_name} إلى {dst_name}. رقم الحركة: {ref}")
            st.markdown("#### 📒 آخر حركات الخزائن")
            mov=conn.execute("""SELECT tm.created_at,t.treasury_name,tm.movement_type,tm.amount,tm.voucher_no,tm.description FROM treasury_movements tm JOIN treasuries t ON t.id=tm.treasury_id ORDER BY datetime(tm.created_at) DESC,tm.id DESC LIMIT 200""").fetchall()
            if mov:
                st.dataframe(pd.DataFrame([{"التاريخ":r["created_at"],"الخزينة":r["treasury_name"],"الحركة":r["movement_type"],"المبلغ":float(r["amount"] or 0),"المرجع":r["voucher_no"] or "","البيان":r["description"] or ""} for r in mov]),hide_index=True,use_container_width=True)
            else: st.info("لا توجد حركات خزينة حتى الآن.")

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
                           amount, notes, created_at, COALESCE(treasury_name,'-') AS treasury_name
                    FROM financial_vouchers
                    ORDER BY datetime(created_at) DESC, id DESC
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT voucher_no, voucher_type, party_type, party_name,
                           amount, notes, created_at, COALESCE(treasury_name,'-') AS treasury_name
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
                    "الخزينة": r["treasury_name"],
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
