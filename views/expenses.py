from views.test_branch_policy import expense_allocation_branches
_PAGE_ERROR_UI_REVISION = 61
from views.page_guard import show_operation_error
from views.number_format import excel_literal_text
from views.dashboard import _validated_role
from views.number_format import decimal_display
from views.ui_feedback import ui_field, ui_form, ui_submit, notify_success, reset_page_fields
from views.ui_common import back_button
import streamlit as st
import pandas as pd
import io
from datetime import datetime
from database import get_db_connection


# ============================================================
# تحويل DataFrame إلى Excel
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
            sheet_name="Financial_Report"
        )
        excel_literal_text(writer)

    return output.getvalue()


# ============================================================
# جلب الفروع
# ============================================================

def get_branches():

    conn = None

    try:
        conn = get_db_connection()

        return conn.execute(
            """
            SELECT
                id,
                branch_name,
                branch_type
            FROM branches
            ORDER BY id ASC
            """
        ).fetchall()

    finally:
        if conn:
            conn.close()


# ============================================================
# تسجيل مصروف خاص بفرع
# ============================================================

def add_branch_expense(
    branch_id,
    amount,
    description,
    target_month,
    expense_date,
    expense_type,
    advance_end_date
):

    _validated_role()
    conn = None

    try:
        conn = get_db_connection()

        if amount <= 0:
            raise ValueError(
                "قيمة المصروف يجب أن تكون أكبر من صفر."
            )

        if not description.strip():
            raise ValueError(
                "يجب إدخال وصف للمصروف."
            )

        desc_final = description.strip()

        if (
            "إيجار" in expense_type
            and advance_end_date.strip()
        ):
            desc_final = (
                f"[إيجار مقدم يغطي حتى "
                f"{advance_end_date.strip()}] "
                f"{desc_final}"
            )

        final_description = (
            f"[{target_month}] "
            f"{desc_final}"
        )

        conn.execute(
            """
            INSERT INTO expenses
            (
                branch_id,
                amount,
                description,
                is_general_store,
                expense_date
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                branch_id,
                amount,
                final_description,
                0,
                expense_date.strftime(
                    "%Y-%m-%d"
                )
            )
        )

        expense_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        st.session_state["finance_last_undo"] = {
            "table": "expenses", "ids": [expense_id],
            "label": "مصروف فرع", "amount": float(amount),
        }
        st.session_state["finance_success_info"] = {
            "message": "✅ تم تسجيل المصروف على الفرع المحدد بنجاح.",
            "summary": [
                ("المبلغ", f"{decimal_display(float(amount), 2)} د.ل"),
                ("البيان", description.strip()),
                ("تاريخ التسجيل", expense_date.strftime("%Y-%m-%d")),
            ],
        }
        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تسجيل المصروف."
        )

        show_operation_error(e, announce=False, context='views/expenses.py:158')

    finally:

        if conn:
            conn.close()


# ============================================================
# توزيع مصروف عام على الفروع التشغيلية
# ============================================================

def add_general_expense(
    operational_branches,
    amount,
    description,
    target_month,
    expense_date
):

    _validated_role()
    conn = None

    try:
        operational_branches = expense_allocation_branches(operational_branches, st.session_state.get('branch_id'))
        conn = get_db_connection()

        if amount <= 0:
            raise ValueError(
                "قيمة المصروف يجب أن تكون أكبر من صفر."
            )

        if not description.strip():
            raise ValueError(
                "يجب إدخال وصف للمصروف."
            )

        if not operational_branches:
            raise ValueError(
                "لا توجد فروع تشغيلية "
                "لتوزيع المصروف عليها."
            )

        op_count = len(
            operational_branches
        )

        share_per_branch = (
            float(amount) / op_count
        )

        inserted_ids = []
        for branch in operational_branches:

            branch_desc = (
                f"[{target_month}] "
                f"[مصروف عام صادر من المخزن الرئيسي "
                f"- إجمالي البند: "
                f"{decimal_display(amount, 2)} د.ل] "
                f"{description.strip()}"
            )

            conn.execute(
                """
                INSERT INTO expenses
                (
                    branch_id,
                    amount,
                    description,
                    is_general_store,
                    expense_date
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    branch["id"],
                    share_per_branch,
                    branch_desc,
                    1,
                    expense_date.strftime(
                        "%Y-%m-%d"
                    )
                )
            )
            inserted_ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        conn.commit()

        st.session_state["finance_last_undo"] = {
            "table": "expenses", "ids": inserted_ids,
            "label": "مصروف عام موزع على الفروع", "amount": float(amount),
        }
        st.session_state["finance_success_info"] = {
            "message": "✅ تم تسجيل المصروف العام وتوزيعه على الفروع التشغيلية بنجاح.",
            "summary": [
                ("إجمالي المصروف", f"{decimal_display(float(amount), 2)} د.ل"),
                ("عدد الفروع", str(op_count)),
                ("نصيب كل فرع", f"{decimal_display(share_per_branch, 2)} د.ل"),
                ("البيان", description.strip()),
            ],
        }
        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تسجيل وتوزيع المصروف."
        )

        show_operation_error(e, announce=False, context='views/expenses.py:269')

    finally:

        if conn:
            conn.close()


# ============================================================
# تسجيل إيراد
# ============================================================

def add_revenue(
    branch_id,
    revenue_source,
    amount,
    notes,
    revenue_date
):

    _validated_role()
    conn = None

    try:
        conn = get_db_connection()

        if amount <= 0:
            raise ValueError(
                "قيمة الإيراد يجب أن تكون أكبر من صفر."
            )

        if not revenue_source.strip():
            raise ValueError(
                "يجب إدخال مصدر الإيراد."
            )

        description = revenue_source.strip()

        if notes.strip():
            description = (
                f"{description} - {notes.strip()}"
            )

        conn.execute(
            """
            INSERT INTO revenues
            (
                branch_id,
                revenue_source,
                amount,
                notes,
                description,
                revenue_date
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                branch_id,
                revenue_source.strip(),
                amount,
                notes.strip(),
                description,
                revenue_date.strftime("%Y-%m-%d")
            )
        )

        revenue_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        st.session_state["finance_last_undo"] = {
            "table": "revenues", "ids": [revenue_id],
            "label": "إيراد", "amount": float(amount),
        }
        st.session_state["finance_success_info"] = {
            "message": "✅ تم تسجيل الإيراد في الفرع / المخزن المحدد بنجاح.",
            "summary": [
                ("المبلغ", f"{decimal_display(float(amount), 2)} د.ل"),
                ("المصدر", revenue_source.strip()),
                ("تاريخ الإيراد", revenue_date.strftime("%Y-%m-%d")),
            ],
        }
        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تسجيل الإيراد."
        )

        show_operation_error(e, announce=False, context='views/expenses.py:361')

    finally:

        if conn:
            conn.close()


# ============================================================
# تحميل المصروفات
# ============================================================

def load_expenses(branch_id=None):

    conn = None

    try:
        conn = get_db_connection()

        if branch_id is None:

            rows = conn.execute(
                """
                SELECT
                    expenses.id,
                    branches.branch_name,
                    expenses.amount,
                    expenses.description,
                    expenses.expense_date
                FROM expenses

                JOIN branches
                    ON expenses.branch_id =
                       branches.id

                ORDER BY expenses.id DESC
                """
            ).fetchall()

        else:

            rows = conn.execute(
                """
                SELECT
                    expenses.id,
                    branches.branch_name,
                    expenses.amount,
                    expenses.description,
                    expenses.expense_date
                FROM expenses

                JOIN branches
                    ON expenses.branch_id =
                       branches.id

                WHERE expenses.branch_id = ?

                ORDER BY expenses.id DESC
                """,
                (branch_id,)
            ).fetchall()

        data = []

        for row in rows:

            data.append(
                {
                    "مسلسل":
                        row["id"],

                    "الفرع":
                        row["branch_name"],

                    "المبلغ (د.ل)":
                        float(
                            row["amount"] or 0
                        ),

                    "البيان":
                        row["description"],

                    "تاريخ التسجيل":
                        row["expense_date"]
                }
            )

        return pd.DataFrame(data)

    finally:

        if conn:
            conn.close()


# ============================================================
# حذف مصروف
# ============================================================

def delete_expense(
    expense_id,
    password
):

    _validated_role()
    conn = None

    try:
        conn = get_db_connection()

        role = _validated_role()

        user_id = st.session_state.get(
            "user_id"
        )

        if role not in [
            "Super_Admin", "Admin",
            "General_Supervisor"
        ]:

            raise PermissionError(
                "ليس لديك صلاحية حذف المصروفات."
            )

        if not user_id:

            raise PermissionError(
                "تعذر تحديد المستخدم الحالي."
            )

        from branch_auth import verify_local_user_password
        user_chk = verify_local_user_password(user_id, password)

        if not user_chk:

            raise PermissionError(
                "كلمة المرور غير صحيحة."
            )

        expense = conn.execute(
            """
            SELECT id
            FROM expenses
            WHERE id = ?
            FOR UPDATE
            """,
            (expense_id,)
        ).fetchone()

        if not expense:

            raise ValueError(
                "المصروف غير موجود "
                "أو تم حذفه مسبقاً."
            )

        linked = conn.execute("""SELECT 1 FROM commitment_accruals WHERE expense_id=?
            UNION ALL SELECT 1 FROM commitment_documents WHERE expense_id=?
            UNION ALL SELECT 1 FROM employee_financial_transactions WHERE expense_id=?
            LIMIT 1""", (expense_id, expense_id, expense_id)).fetchone()
        if linked:
            raise ValueError('المصروف مرتبط بقيد محاسبي؛ لا يمكن حذفه مباشرة. يلزم إجراء إلغاء محاسبي متكامل.')

        conn.execute(
            """
            DELETE FROM expenses
            WHERE id = ?
            """,
            (expense_id,)
        )

        conn.commit()

        notify_success(
            "✅ تم حذف المصروف بنجاح."
        )

        st.rerun()

    except PermissionError as e:

        if conn:
            conn.rollback()

        st.error(
            f"🚫 {e}"
        )

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر حذف المصروف."
        )

        show_operation_error(e, announce=False, context='views/expenses.py:559')

    finally:

        if conn:
            conn.close()



# ============================================================
# مراجعة / نجاح / تراجع آمن
# ============================================================

@st.dialog("⚠️ مراجعة العملية قبل التنفيذ")
def _finance_confirm_dialog():
    _validated_role()
    pending = st.session_state.get("finance_pending_action")
    if not pending:
        st.info("لا توجد عملية معلقة للمراجعة.")
        return

    st.warning("راجع البيانات التالية جيدًا. لن يتم تغيير أي رصيد قبل الضغط على «تأكيد التنفيذ».")
    for label, value in pending.get("summary", []):
        st.write(f"**{label}:** {value}")

    c1, c2 = st.columns(2)
    if c1.button("✅ تأكيد التنفيذ", type="primary", use_container_width=True, key="finance_confirm_yes"):
        action = pending.get("action")
        data = pending.get("data", {})
        st.session_state.pop("finance_pending_action", None)
        if action == "branch_expense":
            add_branch_expense(**data)
        elif action == "general_expense":
            add_general_expense(**data)
        elif action == "revenue":
            add_revenue(**data)

    if c2.button("❌ إلغاء", use_container_width=True, key="finance_confirm_no"):
        st.session_state.pop("finance_pending_action", None)
        st.rerun()


@st.dialog("✅ تمت العملية بنجاح", dismissible=False)
def _finance_success_dialog():
    _validated_role()
    info = st.session_state.get("finance_success_info")
    if not info:
        return
    st.success(info.get("message", "تمت العملية بنجاح."))
    for label, value in info.get("summary", []):
        st.write(f"**{label}:** {value}")
    if st.button("موافق", type="primary", use_container_width=True, key="finance_success_ok"):
        reset_page_fields()
        st.session_state.pop("finance_success_info", None)
        st.rerun()


@st.dialog("↩️ تأكيد التراجع عن آخر إدخال")
def _finance_undo_dialog():
    _validated_role()
    undo = st.session_state.get("finance_last_undo")
    if not undo:
        st.info("لا توجد عملية حديثة قابلة للتراجع.")
        return

    st.warning("سيتم عكس آخر إدخال فقط. هل تريد المتابعة؟")
    st.write(f"**العملية:** {undo.get('label', '')}")
    st.write(f"**القيمة:** {decimal_display(undo.get('amount', 0), 2)} د.ل")
    c1, c2 = st.columns(2)
    if c1.button("✅ نعم، تراجع", type="primary", use_container_width=True, key="finance_undo_yes"):
        conn = get_db_connection()
        try:
            table = undo["table"]
            ids = [int(x) for x in undo.get("ids", [])]
            if table not in ("expenses", "revenues") or not ids:
                raise ValueError("بيانات التراجع غير صالحة.")
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", ids)
            conn.commit()
            st.session_state.pop("finance_last_undo", None)
            st.session_state.pop("finance_undo_open", None)
            st.session_state["finance_success_info"] = {
                "message": "↩️ تم التراجع عن آخر إدخال بنجاح.",
                "summary": [("العملية", undo.get("label", ""))]
            }
            st.rerun()
        except Exception as e:
            conn.rollback()
            show_operation_error(e, announce=True, context='views/expenses.py:647')
        finally:
            conn.close()
    if c2.button("❌ إلغاء", use_container_width=True, key="finance_undo_no"):
        st.session_state.pop("finance_undo_open", None)
        st.rerun()


# ============================================================
# الصفحة الرئيسية
# ============================================================


def _ensure_settlement_schema(conn):
    _validated_role()
    conn.execute("""CREATE TABLE IF NOT EXISTS shift_closures(
        id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER NOT NULL, shift_date TEXT NOT NULL, shift_number INTEGER NOT NULL,
        gross_sales REAL DEFAULT 0, net_sales REAL DEFAULT 0, cash_amount REAL DEFAULT 0, card_amount REAL DEFAULT 0,
        transfer_amount REAL DEFAULT 0, credit_amount REAL DEFAULT 0, other_amount REAL DEFAULT 0, status TEXT DEFAULT 'closed',
        closed_by INTEGER, closed_at TEXT DEFAULT CURRENT_TIMESTAMP, notes TEXT, UNIQUE(branch_id, shift_date, shift_number))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS shift_settlement_adjustments(
        id INTEGER PRIMARY KEY AUTOINCREMENT, closure_id INTEGER, branch_id INTEGER NOT NULL, shift_date TEXT NOT NULL, shift_number INTEGER,
        cash_amount REAL DEFAULT 0, card_amount REAL DEFAULT 0, transfer_amount REAL DEFAULT 0, credit_amount REAL DEFAULT 0,
        other_amount REAL DEFAULT 0, reason TEXT, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS treasuries(id INTEGER PRIMARY KEY AUTOINCREMENT,treasury_name TEXT NOT NULL UNIQUE,treasury_type TEXT NOT NULL DEFAULT 'branch',branch_id INTEGER,is_active INTEGER NOT NULL DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS treasury_movements(id INTEGER PRIMARY KEY AUTOINCREMENT,treasury_id INTEGER NOT NULL,movement_type TEXT NOT NULL,amount REAL NOT NULL,voucher_no TEXT,description TEXT,user_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    cols={r['name'] for r in conn.execute('PRAGMA table_info(treasury_movements)').fetchall()}
    for col,typ in [('branch_id','INTEGER'),('payment_method','TEXT'),('movement_date','TEXT'),('source_type','TEXT'),('source_ref','TEXT')]:
        if col not in cols: conn.execute(f'ALTER TABLE treasury_movements ADD COLUMN {col} {typ}')
    conn.commit()

def _main_treasury(conn):
    row=conn.execute("SELECT id FROM treasuries WHERE treasury_type='company' ORDER BY id LIMIT 1").fetchone()
    if row:
        conn.execute("UPDATE treasuries SET treasury_name='الخزينة الرئيسية', branch_id=NULL, is_active=1 WHERE id=?",(row['id'],))
        conn.execute("UPDATE treasuries SET is_active=0 WHERE treasury_type='branch'")
        return row['id']
    cur=conn.execute("INSERT INTO treasuries(treasury_name,treasury_type,branch_id,is_active) VALUES('الخزينة الرئيسية','company',NULL,1)")
    conn.execute("UPDATE treasuries SET is_active=0 WHERE treasury_type='branch'")
    return cur.lastrowid

def _show_shift_settlement(branches):
    _validated_role()
    role=_validated_role()
    if role not in ("Super_Admin", 'Admin','Manager','General_Supervisor'):
        st.warning('🔒 تسوية الورديات والأيام السابقة متاحة للمدير أو الأدمن فقط.')
        return
    conn=get_db_connection()
    try:
        _ensure_settlement_schema(conn)
        st.subheader('🧮 مراجعة وتسوية ترحيل الورديات')
        closures=conn.execute("""SELECT sc.*,b.branch_name FROM shift_closures sc JOIN branches b ON b.id=sc.branch_id ORDER BY sc.shift_date DESC,sc.id DESC LIMIT 180""").fetchall()
        if closures:
            labels={f"{r['shift_date']} | {r['branch_name']} | وردية {r['shift_number']} | {decimal_display(float(r['net_sales'] or 0), 2)}":r for r in closures}
            row=labels[ui_field(st.selectbox, "expenses:692", 'اختر وردية مغلقة:',list(labels),key='settlement_closure')]
            st.caption('التعديل هنا يصحح توزيع طرق التحصيل ولا يغيّر فواتير البيع الأصلية. الآجل لا يدخل الخزينة.')
            c1,c2,c3=st.columns(3)
            cash=ui_field(c1.number_input, "expenses:695", 'كاش',min_value=0.0,value=float(row['cash_amount'] or 0),step=1.0,key='set_cash')
            card=ui_field(c2.number_input, "expenses:696", 'بطاقة',min_value=0.0,value=float(row['card_amount'] or 0),step=1.0,key='set_card')
            transfer=ui_field(c3.number_input, "expenses:697", 'تحويل',min_value=0.0,value=float(row['transfer_amount'] or 0),step=1.0,key='set_transfer')
            c4,c5=st.columns(2)
            credit=ui_field(c4.number_input, "expenses:699", 'آجل',min_value=0.0,value=float(row['credit_amount'] or 0),step=1.0,key='set_credit')
            other=ui_field(c5.number_input, "expenses:700", 'دفع آخر',min_value=0.0,value=float(row['other_amount'] or 0),step=1.0,key='set_other')
            reason=ui_field(st.text_input, "expenses:701", 'سبب التسوية:',key='set_reason')
            total=float(cash+card+transfer+credit+other)
            st.metric('إجمالي التوزيع',f'{decimal_display(total, 2)} د.ل',delta=f'{decimal_display(total-float(row["net_sales"] or 0), 2)} عن صافي المبيعات')
            if st.button('✅ حفظ تسوية الوردية',type='primary',use_container_width=True,key='save_shift_settlement'):
                if not reason.strip(): st.warning('اكتب سبب التسوية.')
                elif abs(total-float(row['net_sales'] or 0))>0.01: st.error('إجمالي طرق الدفع يجب أن يساوي صافي مبيعات الوردية.')
                else:
                    tid=_main_treasury(conn); ref=str(row['id']); uid=st.session_state.get('user_id')
                    conn.execute("UPDATE treasury_movements SET amount=0, description=COALESCE(description,'') || ' [تم استبدالها بتسوية]' WHERE source_type='shift_close' AND source_ref=?",(ref,))
                    for method,amount in [('كاش',cash),('بطاقة',card),('تحويل',transfer),('أخرى',other)]:
                        if amount>0: conn.execute("""INSERT INTO treasury_movements(treasury_id,movement_type,amount,voucher_no,description,user_id,branch_id,payment_method,movement_date,source_type,source_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(tid,'تسوية وردية',float(amount),f'ADJ-{ref}',reason,uid,row['branch_id'],method,row['shift_date'],'shift_adjustment',ref))
                    conn.execute("UPDATE shift_closures SET cash_amount=?,card_amount=?,transfer_amount=?,credit_amount=?,other_amount=?,notes=? WHERE id=?",(cash,card,transfer,credit,other,reason,row['id']))
                    conn.execute("INSERT INTO shift_settlement_adjustments(closure_id,branch_id,shift_date,shift_number,cash_amount,card_amount,transfer_amount,credit_amount,other_amount,reason,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(row['id'],row['branch_id'],row['shift_date'],row['shift_number'],cash,card,transfer,credit,other,reason,uid))
                    conn.commit(); notify_success('تم حفظ التسوية وتحديث الترحيل إلى الخزينة الرئيسية مع الاحتفاظ باسم الفرع وسجل التعديل.'); st.rerun()
        else: st.info('لا توجد ورديات مغلقة مسجلة بالنظام الجديد حتى الآن.')
        st.markdown('---'); st.subheader('➕ إضافة حركة مالية ليوم سابق')
        bmap={b['branch_name']:b['id'] for b in branches}; bc1,bc2=st.columns(2)
        bn=ui_field(bc1.selectbox, "expenses:718", 'الفرع:',list(bmap),key='hist_branch'); d=ui_field(bc2.date_input, "expenses:718", 'التاريخ:',key='hist_date')
        hc1,hc2=st.columns(2); method=ui_field(hc1.selectbox, "expenses:719", 'نوع دخول المال:',['كاش','بطاقة','تحويل','أخرى'],key='hist_method'); amount=ui_field(hc2.number_input, "expenses:719", 'المبلغ:',min_value=0.0,step=1.0,key='hist_amount')
        source=ui_field(st.selectbox, "expenses:720", 'مصدر الحركة:',['مبيعات سابقة','إيراد آخر','تحصيل دين'],key='hist_source'); note=ui_field(st.text_input, "expenses:720", 'البيان / السبب:',key='hist_note')
        if st.button('💾 إضافة الحركة السابقة',type='primary',use_container_width=True,key='save_hist_money'):
            if amount<=0 or not note.strip(): st.warning('أدخل مبلغاً وبياناً واضحاً.')
            else:
                bid=bmap[bn]; tid=_main_treasury(conn); uid=st.session_state.get('user_id'); ref=f'MAN-{bid}-{d}-{datetime.now().strftime("%H%M%S")}'
                conn.execute("""INSERT INTO treasury_movements(treasury_id,movement_type,amount,voucher_no,description,user_id,branch_id,payment_method,movement_date,source_type,source_ref) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(tid,'إضافة يوم سابق',float(amount),ref,f'{source}: {note}',uid,bid,method,str(d),'manual_historical',ref))
                if source=='إيراد آخر': conn.execute("INSERT INTO revenues(branch_id,revenue_source,amount,notes,description,revenue_date) VALUES(?,?,?,?,?,?)",(bid,'إيراد يوم سابق',float(amount),note,note,str(d)))
                conn.commit(); notify_success('تمت إضافة الحركة السابقة إلى الخزينة الرئيسية مع تسجيل الفرع المصدر.'); st.rerun()
    finally: conn.close()

def show_page():
    _validated_role()
    back_button(key="back_expenses")


    if st.session_state.get("finance_success_info"):
        _finance_success_dialog()
        st.stop()
    if st.session_state.get("finance_pending_action"):
        _finance_confirm_dialog()
        st.stop()
    if st.session_state.get("finance_undo_open"):
        _finance_undo_dialog()
        st.stop()

    st.header(
        "💰 إدارة وتوزيع المصروفات "
        "والإيرادات الذكية"
    )

    st.info(
        "💡 توزيع مصروفات المخزن الرئيسي "
        "حصرياً على الفروع التشغيلية بالتساوي، "
        "مع إمكانية تسجيل المصروفات الخاصة "
        "والإيرادات ومراجعة الأرشيف."
    )

    # ========================================================
    # تحميل الفروع
    # ========================================================

    try:
        branches = get_branches()

    except Exception as e:

        st.error(
            "❌ تعذر تحميل الفروع."
        )

        show_operation_error(e, announce=False, context='views/expenses.py:779')

        return

    if not branches:

        st.warning(
            "⚠️ يرجى إضافة فروع أولاً "
            "قبل تسجيل المصروفات أو الإيرادات."
        )

        return

    branch_dict = {
        b["branch_name"]: b["id"]
        for b in branches
    }

    operational_branches = [
        b
        for b in branches
        if b["branch_type"] != "مخزن"
    ]

    # ========================================================
    # اختيار القسم
    # ========================================================

    if "finance_screen_mode" not in st.session_state:
        st.session_state["finance_screen_mode"] = "expense"

    if not st.session_state.get("finance_entry_lock"):
        finance_modes = {"💸 مصروف جديد":"expense", "💵 إيراد آخر":"revenue", "🧮 تسوية الورديات":"settlement", "📋 الأرشيف والتقارير":"archive"}
        current_label = next((k for k,v in finance_modes.items() if v == st.session_state["finance_screen_mode"]), list(finance_modes)[0])
        selected_label = ui_field(st.selectbox, "expenses:803", "اختر العملية:", list(finance_modes), index=list(finance_modes).index(current_label), key="finance_action_dropdown")
        selected_value = finance_modes[selected_label]
        if selected_value != st.session_state["finance_screen_mode"]:
            st.session_state["finance_screen_mode"] = selected_value
            st.rerun()
    
    selected_mode = (
        '➕ تسجيل مصروف جديد' if st.session_state["finance_screen_mode"] == "expense"
        else '💵 تسجيل إيراد جديد' if st.session_state["finance_screen_mode"] == "revenue"
        else '🧮 تسوية وإغلاق الورديات' if st.session_state["finance_screen_mode"] == "settlement"
        else '📋 أرشيف المصروفات وتقارير الفروع (تصدير Excel)'
    )

    st.markdown("---")

    if st.session_state.get("finance_last_undo"):
        if st.button("↩️ تراجع عن آخر إدخال", use_container_width=True, key="finance_open_undo"):
            st.session_state["finance_undo_open"] = True
            st.rerun()

    # ========================================================
    # 1 - تسجيل مصروف
    # ========================================================

    if selected_mode.startswith("➕"):

        st.subheader(
            "✍️ إدخال مصروف جديد "
            "وتوزيع الحصص"
        )

        # أزرار اختيار نوع المصروف يجب أن تكون خارج st.form.
        # Streamlit لا يسمح بـ st.button العادي داخل form.
        if "expense_scope_mode" not in st.session_state:
            st.session_state["expense_scope_mode"] = "branch"

        sc1, sc2 = st.columns(2)
        if sc1.button(
            "🏢 مصروف فرع",
            use_container_width=True,
            key="expense_scope_branch"
        ):
            st.session_state["expense_scope_mode"] = "branch"
            st.rerun()

        if sc2.button(
            "🌐 مصروف عام",
            use_container_width=True,
            key="expense_scope_general"
        ):
            st.session_state["expense_scope_mode"] = "general"
            st.rerun()

        exp_scope = (
            '📍 خاص بفرع أو مخزن معين'
            if st.session_state["expense_scope_mode"] == "branch"
            else '🌍 مصروف عام للمخزن الرئيسي '
        )

        with ui_form(
            "expense_advanced_form",
            clear_on_submit=False
        ):
            sel_branch_name = None

            if "خاص بفرع" in exp_scope:

                sel_branch_name = ui_field(st.selectbox, "expenses:870", 
                    "اختر الفرع أو المخزن المستفيد:",
                    list(branch_dict.keys())
                )

            col_a, col_b = st.columns(2)

            with col_a:

                amount = ui_field(st.number_input, "expenses:879", 
                    "المبلغ الإجمالي (د.ل):",
                    min_value=0.0,
                    value=0.0,
                    step=0.5,
                    format="%.2f"
                )

                expense_type = ui_field(st.selectbox, "expenses:887", 
                    "نوع المصروف:",
                    [
                        "تشغيلي عادي",
                        "إيجار / مصروف مقدم "
                        "(لفترة محددة)"
                    ]
                )

            with col_b:

                current_year_month = (
                    datetime.now().strftime(
                        "%Y-%m"
                    )
                )

                target_month = ui_field(st.text_input, "expenses:904", 
                    "شهر الاستحقاق المحاسبي "
                    "(YYYY-MM):",
                    value=current_year_month
                )

                expense_date = ui_field(st.date_input, "expenses:910", 
                    "تاريخ التسجيل الفعلي:",
                    value=datetime.now()
                )

            description = ui_field(st.text_input, "expenses:915", 
                "البيان أو وصف المصروف "
                "(مثلاً: صيانة سيارة المخزن، "
                "فاتورة كهرباء...):"
            )

            advance_end_date = ""

            if "إيجار" in expense_type:

                st.markdown("---")

                st.warning(
                    "📌 إدارة الإيجارات "
                    "والمصروفات المقدمة:"
                )

                advance_end_date = ui_field(st.text_input, "expenses:932", 
                    "تاريخ انتهاء فترة التغطية "
                    "المقدمة "
                    "(مثال: 2027-06-30):",
                    value=""
                )

            submitted_exp = (
                ui_submit(
                    "💾 حفظ وترحيل وتوزيع المصروف",
                    type="primary",
                    use_container_width=True
                )
            )

        if submitted_exp:

            if (
                amount <= 0
                or not description.strip()
            ):

                st.error(
                    "⚠️ يجب إدخال مبلغ صحيح "
                    "ووصف واضح للمصروف."
                )

            elif "خاص بفرع" in exp_scope:

                branch_id = branch_dict[
                    sel_branch_name
                ]

                st.session_state["finance_pending_action"] = {
                    "action": "branch_expense",
                    "data": {
                        "branch_id": branch_id, "amount": amount,
                        "description": description, "target_month": target_month,
                        "expense_date": expense_date, "expense_type": expense_type,
                        "advance_end_date": advance_end_date,
                    },
                    "summary": [
                        ("الفرع", sel_branch_name),
                        ("المبلغ", f"{decimal_display(float(amount), 2)} د.ل"),
                        ("نوع المصروف", expense_type),
                        ("البيان", description.strip()),
                        ("شهر الاستحقاق", target_month),
                        ("تاريخ التسجيل", expense_date.strftime("%Y-%m-%d")),
                    ],
                }
                st.rerun()

            else:

                st.session_state["finance_pending_action"] = {
                    "action": "general_expense",
                    "data": {
                        "operational_branches": operational_branches,
                        "amount": amount, "description": description,
                        "target_month": target_month, "expense_date": expense_date,
                    },
                    "summary": [
                        ("النطاق", "مصروف عام موزع على الفروع التشغيلية"),
                        ("إجمالي المبلغ", f"{decimal_display(float(amount), 2)} د.ل"),
                        ("عدد الفروع", str(len(operational_branches))),
                        ("البيان", description.strip()),
                        ("شهر الاستحقاق", target_month),
                    ],
                }
                st.rerun()

    # ========================================================
    # 2 - تسجيل إيراد
    # ========================================================

    elif selected_mode.startswith("💵"):

        st.subheader(
            "💵 تسجيل إيراد جديد "
            "(خارجي أو خدمي)"
        )

        with ui_form(
            "revenue_form_new",
            clear_on_submit=False
        ):

            rev_branch = ui_field(st.selectbox, "expenses:1019", 
                "الفرع أو المخزن "
                "المستفيد من الإيراد:",
                list(branch_dict.keys())
            )

            rev_source = ui_field(st.text_input, "expenses:1025", 
                "مصدر الإيراد "
                "(مثال: بيع خردة، "
                "إيراد خدمات، "
                "أرباح رأسمالية...):"
            )

            rev_amount = ui_field(st.number_input, "expenses:1032", 
                "مبلغ الإيراد (د.ل):",
                min_value=0.0,
                step=0.5,
                format="%.2f"
            )

            rev_date = ui_field(st.date_input, "expenses:1039", 
                "تاريخ الإيراد:",
                value=datetime.now(),
                key="revenue_date"
            )

            rev_notes = ui_field(st.text_area, "expenses:1045", 
                "ملاحظات إضافية:"
            )

            submit_rev = (
                ui_submit(
                    "💾 حفظ وتسجيل الإيراد",
                    type="primary",
                    use_container_width=True
                )
            )

        if submit_rev:

            if (
                rev_amount <= 0
                or not rev_source.strip()
            ):

                st.warning(
                    "⚠️ يرجى إدخال مصدر "
                    "الإيراد ومبلغ صحيح."
                )

            else:

                b_id = branch_dict[
                    rev_branch
                ]

                st.session_state["finance_pending_action"] = {
                    "action": "revenue",
                    "data": {
                        "branch_id": b_id, "revenue_source": rev_source,
                        "amount": rev_amount, "notes": rev_notes,
                        "revenue_date": rev_date,
                    },
                    "summary": [
                        ("الفرع / المخزن", rev_branch),
                        ("المبلغ", f"{decimal_display(float(rev_amount), 2)} د.ل"),
                        ("مصدر الإيراد", rev_source.strip()),
                        ("التاريخ", rev_date.strftime("%Y-%m-%d")),
                        ("ملاحظات", rev_notes.strip() or "-"),
                    ],
                }
                st.rerun()

    # ========================================================
    # 3 - تسوية الورديات والحركات السابقة
    # ========================================================

    elif selected_mode.startswith("🧮"):
        _show_shift_settlement(branches)

    # ========================================================
    # 4 - الأرشيف والتقارير
    # ========================================================

    elif selected_mode.startswith("📋"):

        st.subheader(
            "📋 تقارير ومتابعة "
            "مصروفات الفروع"
        )

        report_filter = ui_field(st.selectbox, "expenses:1110", 
            "عرض مصروفات حسب الفرع:",
            [
                "🌐 عرض كل المصروفات "
                "(الإجمالي العام)"
            ]
            + list(branch_dict.keys())
        )

        try:

            if report_filter.startswith(
                "🌐"
            ):

                exp_df = load_expenses()

            else:

                selected_b_id = (
                    branch_dict[
                        report_filter
                    ]
                )

                exp_df = load_expenses(
                    selected_b_id
                )

        except Exception as e:

            st.error(
                "❌ تعذر تحميل تقرير "
                "المصروفات."
            )

            show_operation_error(e, announce=False, context='views/expenses.py:1156')

            exp_df = pd.DataFrame()

        if not exp_df.empty:

            total_filtered_amount = float(
                exp_df[
                    "المبلغ (د.ل)"
                ].sum()
            )

            st.metric(
                label=(
                    "إجمالي المصروفات للجهة "
                    f"({report_filter})"
                ),
                value=(
                    f"{decimal_display(total_filtered_amount, 2)} "
                    "د.ل"
                )
            )

            st.dataframe(
                exp_df,
                use_container_width=True,
                hide_index=True
            )

            # ------------------------------------------------
            # Excel
            # ------------------------------------------------

            excel_data = to_excel(
                exp_df
            )

            if report_filter.startswith(
                "🌐"
            ):

                file_suffix = (
                    "all_branches"
                )

            else:

                file_suffix = (
                    report_filter
                    .replace("/", "-")
                    .replace("\\", "-")
                )

            st.download_button(
                label=(
                    "📥 تصدير جدول مصروفات "
                    f"({report_filter}) إلى Excel"
                ),
                data=excel_data,
                file_name=(
                    f"expenses_{file_suffix}_"
                    f"{datetime.now().strftime('%Y%m%d')}"
                    ".xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"
                ),
                use_container_width=True
            )

            # ------------------------------------------------
            # حذف مصروف
            # ------------------------------------------------

            st.markdown("---")

            st.markdown(
                "### 🗑️ حذف مصروف خاطئ "
                "(يتطلب كلمة مرور)"
            )

            del_id = ui_field(st.selectbox, "expenses:1228", 
                "اختر مسلسل المصروف "
                "المراد حذفه:",
                exp_df["مسلسل"].tolist()
            )

            admin_pass_del = ui_field(st.text_input, "expenses:1234", 
                "🔒 أدخل كلمة المرور "
                "لتأكيد الحذف:",
                type="password",
                key="exp_del_pass"
            )

            if st.button(
                "🗑️ حذف المصروف المختار",
                type="primary"
            ):

                delete_expense(
                    del_id,
                    admin_pass_del
                )

        else:

            st.info(
                f"لا توجد مصروفات مسجلة "
                f"للجهة المحددة "
                f"({report_filter})."
            )
