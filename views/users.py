_PAGE_ERROR_UI_REVISION = 60
from views.page_guard import show_operation_error
from database import (ensure_governance_schema, approve_employee_termination, approve_account_state,
    assert_future_super_admin_coverage, business_date_today, write_audit_event)
from views.number_format import excel_literal_text
from database import hash_password
from views.number_format import decimal_display
from views.ui_feedback import ui_field, ui_form, ui_submit, notify_success, reset_page_fields
from views.ui_common import back_button
import streamlit as st
import pandas as pd
from datetime import date, datetime
import calendar
from io import BytesIO
from database import get_db_connection, ensure_hr_schema
from views.scoped_permissions import ensure_scoped_permissions, PERMISSION_GROUPS


def _lock_super_admin_change(conn):
    """Serialize last-Super_Admin checks and mutation in the same transaction."""
    import sqlite3
    raw = getattr(conn, '_conn', conn)
    if isinstance(raw, sqlite3.Connection):
        if raw.in_transaction:
            raise RuntimeError('تعذر تأمين تغيير الحساب؛ أعد المحاولة بعد إغلاق المعاملة الحالية.')
        conn.execute('BEGIN IMMEDIATE')
    else:
        conn.execute('SELECT pg_advisory_xact_lock(728919, 1)')


def _as_date(value, default=None):
    """Normalize SQLite/PostgreSQL/string HR dates to datetime.date."""
    if value is None or value == "":
        return default
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        pass
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except (ValueError, TypeError):
            continue
    return default

ROLES=["Super_Admin","Admin","Manager","Supervisor","Cashier","استعلام فقط"]

def due(salary,hire,end,y,m):
    md=calendar.monthrange(y,m)[1]; a=date(y,m,1); z=date(y,m,md)
    hire=_as_date(hire, a)
    end=_as_date(end, None)
    start=max(hire,a); finish=min(end or z,z)
    days=max(0,(finish-start).days+1) if finish>=start else 0
    return round(float(salary or 0)*days/md,2),days,md


def _ensure_local_hr_schema(conn):
    """Upgrade old local HR tables in-place; keeps all existing employee records."""
    emp_cols = {
        "user_id":"INTEGER", "full_name":"TEXT", "address":"TEXT",
        "emergency_name":"TEXT", "emergency_phone":"TEXT", "emergency_relation":"TEXT",
        "monthly_salary":"REAL DEFAULT 0", "hire_date":"TEXT", "termination_date":"TEXT",
        "employment_status":"TEXT DEFAULT 'active'", "notes":"TEXT", "updated_at":"TEXT"
    }
    tx_cols = {
        "payroll_year":"INTEGER", "payroll_month":"INTEGER", "work_days":"INTEGER",
        "month_days":"INTEGER", "base_salary":"REAL DEFAULT 0", "expense_id":"INTEGER",
        "created_by":"INTEGER"
    }
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(employees)").fetchall()}
    for col, typ in emp_cols.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE employees ADD COLUMN {col} {typ}")
    existing_tx = {r["name"] for r in conn.execute("PRAGMA table_info(employee_financial_transactions)").fetchall()}
    for col, typ in tx_cols.items():
        if col not in existing_tx:
            conn.execute(f"ALTER TABLE employee_financial_transactions ADD COLUMN {col} {typ}")
    # Map legacy fields into the current HR fields.
    final_cols = {r["name"] for r in conn.execute("PRAGMA table_info(employees)").fetchall()}
    if "employee_name" in final_cols:
        conn.execute("UPDATE employees SET full_name=employee_name WHERE (full_name IS NULL OR TRIM(full_name)='') AND employee_name IS NOT NULL")
    if "salary" in final_cols:
        conn.execute("UPDATE employees SET monthly_salary=salary WHERE COALESCE(monthly_salary,0)=0 AND COALESCE(salary,0)<>0")
    if "is_active" in final_cols:
        conn.execute("UPDATE employees SET employment_status=CASE WHEN COALESCE(is_active,1)=1 THEN 'active' ELSE 'terminated' END WHERE employment_status IS NULL OR employment_status=''")
    conn.execute("UPDATE employees SET hire_date=COALESCE(NULLIF(hire_date,''), substr(created_at,1,10), date('now')) WHERE hire_date IS NULL OR hire_date=''")
    conn.commit()

def employees(conn,active=False):
    w="WHERE e.employment_status='active'" if active else ""
    return conn.execute(f"""SELECT e.*,b.branch_name,u.username,u.role
        FROM employees e JOIN branches b ON b.id=e.branch_id
        LEFT JOIN users u ON u.id=e.user_id {w} ORDER BY e.id DESC""").fetchall()

def pick(rows,key):
    d={f"#{r['id']} - {r['full_name']} - {r['branch_name']}":r for r in rows}
    return d[ui_field(st.selectbox, "users:83", "اختر الموظف:",list(d),key=key)] if d else None

def financial(conn,e,kind,amount,notes="",y=None,m=None,wd=None,md=None):
    amount=float(amount)
    if amount<=0: raise ValueError("المبلغ يجب أن يكون أكبر من صفر.")
    exp_id=None
    label={"salary":"راتب موظف","advance":"سلفة موظف","advance_repayment":"تسوية سلفة"}[kind]
    if kind == "salary":
        r=conn.execute("""INSERT INTO expenses(branch_id,amount,description,is_general_store,expense_date)
            VALUES(?,?,?,0,CURRENT_DATE) RETURNING id""",
            (e["branch_id"],amount,f"{label} - {e['full_name']} - {notes}".strip(" -"))).fetchone()
        exp_id=r["id"]
    conn.execute("""INSERT INTO employee_financial_transactions
        (employee_id,branch_id,transaction_type,amount,payroll_year,payroll_month,
         work_days,month_days,base_salary,notes,expense_id,created_by)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (e["id"],e["branch_id"],kind,amount,y,m,wd,md,float(e["monthly_salary"] or 0),
         notes,exp_id,st.session_state.get("user_id")))

def _xlsx_bytes(df, sheet_name="Data"):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
        excel_literal_text(writer)
    return out.getvalue()

def show_page():
    back_button(key="back_users")

    try:
        ensure_hr_schema()
    except Exception as e:
        st.error("❌ تعذر تجهيز جداول الموارد البشرية في قاعدة البيانات.")
        show_operation_error(e, announce=False, context='views/users.py:135')
        return

    st.header("👥 إدارة الموظفين والمستخدمين — HR مصغرة")
    st.info("الراتب يُسجّل كمصروف على فرع الموظف؛ السلفة مديونية على الموظف وليست مصروفًا. ربط حركات الخزينة الرئيسية ما زال قيد الاستكمال.")
    role=st.session_state.get("role","")
    if role not in ("Super_Admin","Admin","Manager","General_Supervisor"):
        st.warning("🔒 هذه الشاشة متاحة للإدارة فقط."); return
    if "hr_view" not in st.session_state: st.session_state.hr_view="list"
    nav=[("list","👥 الموظفون"),("add","➕ إضافة موظف"),("edit","✏️ تعديل/إنهاء"),
         ("salary","💵 الرواتب"),("advance","💳 السلف"),("settle","🔁 تسوية سلفة"),
         ("history","📋 السجل"),("accounts","🔐 حسابات الدخول")]
    cs=st.columns(4)
    for i,(k,l) in enumerate(nav):
        if cs[i%4].button(l,key="hr_"+k,use_container_width=True,
                          type="primary" if st.session_state.hr_view==k else "secondary"):
            st.session_state.hr_view=k; st.rerun()
    st.markdown("---")
    conn=None
    try:
        conn=get_db_connection()
        ensure_governance_schema(conn); conn.commit()
        _ensure_local_hr_schema(conn)
        bs=conn.execute("SELECT id,branch_name FROM branches ORDER BY id").fetchall()
        bm={b["branch_name"]:b["id"] for b in bs}; v=st.session_state.hr_view

        if v=="list":
            rs=employees(conn)
            if not rs: st.info("لا توجد ملفات موظفين."); return
            df=pd.DataFrame([{"رقم":r["id"],"الاسم":r["full_name"],"الهاتف":r["phone"] or "",
              "العنوان":r["address"] or "","الفرع":r["branch_name"],
              "الراتب":float(r["monthly_salary"] or 0),"التعيين":r["hire_date"],
              "إنهاء العمل":r["termination_date"] or "",
              "الحالة":"على رأس العمل" if r["employment_status"]=="active" else "منتهي",
              "حساب الدخول":r["username"] or "بدون حساب"} for r in rs])
            st.dataframe(df,use_container_width=True,hide_index=True)
            st.download_button("📥 تصدير Excel", _xlsx_bytes(df, "Employees"),
                               "employees.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

        elif v=="add":
            us=conn.execute("""SELECT id,username FROM users WHERE id NOT IN
                (SELECT user_id FROM employees WHERE user_id IS NOT NULL) ORDER BY username""").fetchall()
            um={"بدون حساب دخول":None}; um.update({x["username"]:x["id"] for x in us})
            with ui_form("add_emp"):
                c1,c2=st.columns(2)
                name=ui_field(c1.text_input, "users:159", "اسم الموظف الكامل *"); phone=ui_field(c1.text_input, "users:159", "الهاتف")
                addr=ui_field(c1.text_input, "users:160", "العنوان"); sal=ui_field(c1.number_input, "users:160", "الراتب الشهري",min_value=0.,step=50.)
                hd=ui_field(c1.date_input, "users:161", "تاريخ التعيين",date.today())
                en=ui_field(c2.text_input, "users:162", "اسم شخص مقرب"); ep=ui_field(c2.text_input, "users:162", "هاتف الشخص المقرب")
                er=ui_field(c2.text_input, "users:163", "صلة القرابة"); bn=ui_field(c2.selectbox, "users:163", "الفرع *",list(bm))
                un=ui_field(c2.selectbox, "users:164", "ربط بحساب دخول (اختياري)",list(um))
                notes=ui_field(st.text_area, "users:165", "ملاحظات"); ok=ui_submit("💾 حفظ",type="primary")
            if ok:
                if not name.strip(): st.warning("أدخل اسم الموظف."); return
                dup = conn.execute("""SELECT id FROM employees
                    WHERE LOWER(TRIM(full_name))=LOWER(TRIM(?))
                       OR (? <> '' AND phone IS NOT NULL AND TRIM(phone)=TRIM(?))
                    LIMIT 1""", (name.strip(), phone.strip(), phone.strip())).fetchone()
                if dup:
                    st.error("❌ يوجد موظف مسجل بنفس الاسم أو رقم الهاتف. افتح تعديل/إنهاء لتحديث بياناته بدلاً من إنشاء ملف مكرر.")
                    return
                conn.execute("""INSERT INTO employees(user_id,full_name,phone,address,emergency_name,
                    emergency_phone,emergency_relation,branch_id,monthly_salary,hire_date,notes)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(um[un],name.strip(),phone,addr,en,ep,er,bm[bn],sal,hd,notes))
                conn.commit(); notify_success("✅ تم إنشاء ملف الموظف."); st.rerun()

        elif v=="edit":
            e=pick(employees(conn),"edit_emp")
            if not e: st.info("لا توجد ملفات."); return
            names=list(bm); bi=names.index(e["branch_name"])
            with ui_form("edit_emp_form"):
                c1,c2=st.columns(2)
                name=ui_field(c1.text_input, "users:186", "الاسم",e["full_name"]); phone=ui_field(c1.text_input, "users:186", "الهاتف",e["phone"] or "")
                addr=ui_field(c1.text_input, "users:187", "العنوان",e["address"] or "")
                sal=ui_field(c1.number_input, "users:188", "الراتب",min_value=0.,value=float(e["monthly_salary"] or 0),step=50.)
                bn=ui_field(c1.selectbox, "users:189", "الفرع",names,index=bi)
                en=ui_field(c2.text_input, "users:190", "اسم شخص مقرب",e["emergency_name"] or "")
                ep=ui_field(c2.text_input, "users:191", "هاتف الشخص المقرب",e["emergency_phone"] or "")
                er=ui_field(c2.text_input, "users:192", "صلة القرابة",e["emergency_relation"] or "")
                hd=ui_field(c2.date_input, "users:193", "تاريخ التعيين",_as_date(e["hire_date"], date.today()))
                ended=ui_field(c2.checkbox, "users:194", "إنهاء خدمة",value=bool(e["termination_date"]) or e["employment_status"]!="active")
                ed=ui_field(c2.date_input, "users:195", "تاريخ إنهاء العمل",_as_date(e["termination_date"], date.today()))
                notes=ui_field(st.text_area, "users:196", "ملاحظات",e["notes"] or "")
                termination_confirmation = ui_field(st.text_input,"users:termination_confirmation","تأكيد كلمة المرور لاعتماد قرار إنهاء الخدمة",type="password") if role == "Super_Admin" else None
                ok=ui_submit("💾 حفظ",type="primary")
            if ok:
                if ended and ed<hd: st.error("تاريخ الإنهاء يسبق التعيين."); return
                approve_employee_termination(conn, e, ended, ed, st.session_state.get("user_id"), termination_confirmation)
                conn.execute("""UPDATE employees SET full_name=?,phone=?,address=?,emergency_name=?,
                    emergency_phone=?,emergency_relation=?,branch_id=?,monthly_salary=?,hire_date=?,
                    termination_date=?,employment_status=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (name,phone,addr,en,ep,er,bm[bn],sal,hd,ed if ended else None,
                     "terminated" if ended and ed <= business_date_today() else "active",notes,e["id"]))
                if e["user_id"]: conn.execute("UPDATE users SET branch_id=? WHERE id=?",(bm[bn],e["user_id"]))
                conn.commit(); notify_success("✅ تم التحديث."); st.rerun()

        elif v=="salary":
            e=pick(employees(conn),"salary_emp")
            if not e: st.info("لا توجد ملفات."); return
            now=date.today(); c1,c2=st.columns(2)
            y=int(ui_field(c1.number_input, "users:211", "السنة",2020,2100,now.year)); m=ui_field(c2.selectbox, "users:211", "الشهر",range(1,13),index=now.month-1)
            total,wd,md=due(e["monthly_salary"],e["hire_date"],e["termination_date"],y,m)
            paid=float(conn.execute("""SELECT COALESCE(SUM(amount),0) FROM employee_financial_transactions
                WHERE employee_id=? AND transaction_type='salary' AND payroll_year=? AND payroll_month=?""",
                (e["id"],y,m)).fetchone()[0] or 0)
            rem=max(0.,total-paid)
            st.info(f"الراتب: {decimal_display(float(e['monthly_salary'] or 0), 2)} | أيام العمل: {wd}/{md} | الاستحقاق: {decimal_display(total, 2)} | المصروف: {decimal_display(paid, 2)} | المتبقي: {decimal_display(rem, 2)} د.ل")
            with ui_form("pay_salary"):
                amt=ui_field(st.number_input, "users:219", "المبلغ",min_value=0.,value=float(rem),step=50.)
                notes=ui_field(st.text_input, "users:220", "ملاحظات"); ok=ui_submit("💵 اعتماد الصرف",type="primary")
            if ok:
                if amt<=0 or amt>rem+.001: st.error("راجع مبلغ الاستحقاق."); return
                financial(conn,e,"salary",amt,notes,y,m,wd,md); conn.commit()
                notify_success(f"✅ تم الصرف وتحميله على فرع {e['branch_name']}."); st.rerun()

        elif v in ("advance","settle"):
            e=pick(employees(conn,True) if v=="advance" else employees(conn),v+"_emp")
            if not e: st.info("لا يوجد موظفون."); return
            bal=float(conn.execute("""SELECT COALESCE(SUM(CASE WHEN transaction_type='advance' THEN amount
                WHEN transaction_type='advance_repayment' THEN -amount ELSE 0 END),0)
                FROM employee_financial_transactions WHERE employee_id=?""",(e["id"],)).fetchone()[0] or 0)
            st.info(f"رصيد السلف: {decimal_display(bal, 2)} د.ل")
            with ui_form(v+"_form"):
                maxv=float(max(0,bal)) if v=="settle" else None
                if v=="settle": amt=ui_field(st.number_input, "users:235", "قيمة التسوية",min_value=0.,max_value=maxv,value=0.,step=50.)
                else: amt=ui_field(st.number_input, "users:236", "قيمة السلفة",min_value=0.,step=50.)
                notes=ui_field(st.text_input, "users:237", "ملاحظات"); ok=ui_submit("✅ اعتماد",type="primary")
            if ok:
                financial(conn,e,"advance" if v=="advance" else "advance_repayment",amt,notes)
                conn.commit(); notify_success("✅ تم تسجيل الحركة."); st.rerun()

        elif v=="history":
            rs=conn.execute("""SELECT t.*,e.full_name,b.branch_name FROM employee_financial_transactions t
                JOIN employees e ON e.id=t.employee_id JOIN branches b ON b.id=t.branch_id
                ORDER BY t.id DESC LIMIT 1000""").fetchall()
            labels={"salary":"راتب","advance":"سلفة","advance_repayment":"تسوية سلفة"}
            df=pd.DataFrame([{"رقم":r["id"],"الموظف":r["full_name"],"الفرع":r["branch_name"],
              "النوع":labels.get(r["transaction_type"],r["transaction_type"]),"المبلغ":float(r["amount"]),
              "الشهر":f"{r['payroll_month']:02d}/{r['payroll_year']}" if r["payroll_month"] else "",
              "أيام العمل":f"{r['work_days']}/{r['month_days']}" if r["work_days"] is not None else "",
              "ملاحظات":r["notes"] or "","التاريخ":r["created_at"]} for r in rs])
            st.dataframe(df,use_container_width=True,hide_index=True)
            if not df.empty: st.download_button("📥 تصدير Excel", _xlsx_bytes(df, "HR History"),
                                                "hr_history.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

        else:
            st.subheader("🔐 حسابات الدخول والصلاحيات")
            allbm={"🌐 كافة الفروع":None}; allbm.update(bm)
            from sherif_local_identity import MODE_KEY, password_hash
            local_mode = bool(conn.execute('SELECT 1 FROM local_meta WHERE key=? AND value=?',(MODE_KEY,'1')).fetchone())
            with ui_form("new_user"):
                c1,c2=st.columns(2); un=ui_field(c1.text_input, "users:260", "اسم المستخدم"); pw=ui_field(c2.text_input, "users:260", "الرقم السري (4 أرقام)" if local_mode else "كلمة المرور",type="password",max_chars=4 if local_mode else None)
                ph=ui_field(c1.text_input, "users:261", "الهاتف"); roles=ROLES if role=="Super_Admin" else ["Manager","Supervisor","Cashier","استعلام فقط"]
                rr=ui_field(c2.selectbox, "users:262", "الصلاحية",roles); bn=ui_field(st.selectbox, "users:262", "الفرع",list(allbm))
                ok=ui_submit("➕ إنشاء حساب",type="primary")
            if ok:
                if not un.strip() or not pw: st.warning("الاسم وكلمة المرور مطلوبان."); return
                if conn.execute("SELECT id FROM users WHERE LOWER(TRIM(username))=LOWER(TRIM(?)) LIMIT 1", (un.strip(),)).fetchone():
                    st.error("❌ اسم المستخدم مستخدم بالفعل."); return
                if local_mode:
                    try: encoded = password_hash(pw)
                    except ValueError as exc: st.error(str(exc)); return
                else: encoded = hash_password(pw)
                cur=conn.execute("INSERT INTO users(username,phone,password,role,branch_id) VALUES(?,?,?,?,?)", (un.strip(),ph,encoded,rr,allbm[bn]))
                if local_mode: conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)", ('sherif_pin_user:'+str(cur.lastrowid),'1'))
                conn.commit(); notify_success("✅ تم إنشاء الحساب."); st.rerun()
            rs=conn.execute("""SELECT u.id,u.username,u.phone,u.role,COALESCE(b.branch_name,'كافة الفروع') branch_name
                FROM users u LEFT JOIN branches b ON b.id=u.branch_id ORDER BY u.id""").fetchall()
            st.dataframe(pd.DataFrame([{"رقم":r["id"],"المستخدم":r["username"],"الهاتف":r["phone"] or "",
              "الصلاحية":r["role"],"الفرع":r["branch_name"]} for r in rs]),use_container_width=True,hide_index=True)
            if rs and role in ("Super_Admin", "Admin"):
                st.markdown("### صلاحيات إضافية حسب المستخدم والفرع")
                st.caption("تُضاف إلى صلاحيات الجروب ولا تغيّرها. يمكن إلغاؤها لكل فرع على حدة.")
                ensure_scoped_permissions(conn)
                editable = [r for r in rs if role == "Super_Admin" or r["role"] not in ("Super_Admin", "Admin")]
                if editable and bs:
                    users_map = {f"{r['username']} (#{r['id']})": r["id"] for r in editable}
                    branch_map = {b["branch_name"]: b["id"] for b in bs}
                    perm_map = {label: key for group in PERMISSION_GROUPS.values() for label, key in group.items()}
                    picked_user = st.selectbox("المستخدم", list(users_map), key="scoped_user")
                    picked_branch = st.selectbox("الفرع المحدد", list(branch_map), key="scoped_branch")
                    uid, bid = users_map[picked_user], branch_map[picked_branch]
                    existing = {r["permission_key"] for r in conn.execute(
                        "SELECT permission_key FROM user_branch_permissions WHERE user_id=? AND branch_id=?",
                        (uid, bid)).fetchall()}
                    with st.form("scoped_perm_form"):
                        selected_permissions = {}
                        for group_label, group_permissions in PERMISSION_GROUPS.items():
                            with st.expander(group_label, expanded=group_label == "الورديات ونقطة البيع"):
                                for label, key in group_permissions.items():
                                    selected_permissions[key] = st.checkbox(
                                        label, value=key in existing, key=f"perm_{uid}_{bid}_{key}"
                                    )
                        save_permissions = st.form_submit_button("حفظ صلاحيات هذا الفرع", type="primary")
                    if save_permissions:
                        for key, enabled in selected_permissions.items():
                            if enabled:
                                conn.execute("""INSERT INTO user_branch_permissions(user_id,branch_id,permission_key,granted_by)
                                    VALUES(?,?,?,?) ON CONFLICT(user_id,branch_id,permission_key) DO NOTHING""",
                                    (uid, bid, key, st.session_state.get("user_id")))
                            else:
                                conn.execute("DELETE FROM user_branch_permissions WHERE user_id=? AND branch_id=? AND permission_key=?",
                                             (uid, bid, key))
                        conn.commit()
                        notify_success("تم حفظ الصلاحيات الإضافية لهذا الفرع.")
                        st.rerun()
            if rs:
                st.markdown("---")
                labels={f"#{r['id']} - {r['username']} - {r['role']}":r for r in rs}
                selected=labels[ui_field(st.selectbox, "users:277", "اختر حساباً للتعديل أو الحذف", list(labels), key="hr_account_pick")]
                can_edit_selected = role == "Super_Admin" or (role == "Admin" and selected["role"] != "Super_Admin") or (role in ("Manager", "General_Supervisor") and selected["role"] not in ("Super_Admin", "Admin"))
                if can_edit_selected:
                    editable_roles = ROLES if role == "Super_Admin" else (["Admin","Manager","Supervisor","Cashier","استعلام فقط"] if role == "Admin" else ["Manager","Supervisor","Cashier","استعلام فقط"])
                    with ui_form("edit_user_account"):
                        c1,c2=st.columns(2)
                        eu=ui_field(c1.text_input, "users:285", "اسم المستخدم", selected["username"])
                        eph=ui_field(c1.text_input, "users:286", "الهاتف", selected["phone"] or "")
                        epw=ui_field(c2.text_input, "users:287", "رقم سري جديد (4 أرقام؛ اتركه فارغًا للإبقاء على الحالي)" if local_mode else "كلمة مرور جديدة (اتركها فارغة للإبقاء على الحالية)", type="password", max_chars=4 if local_mode else None)
                        erole=ui_field(c2.selectbox, "users:288", "الصلاحية", editable_roles, index=editable_roles.index(selected["role"]) if selected["role"] in editable_roles else 0)
                        branch_names=list(allbm)
                        current_branch=selected["branch_name"] if selected["branch_name"] in allbm else "🌐 كافة الفروع"
                        ebn=ui_field(st.selectbox, "users:291", "الفرع", branch_names, index=branch_names.index(current_branch))
                        save=ui_submit("💾 حفظ تعديل الحساب", type="primary")
                    if save:
                        if not eu.strip():
                            st.error("❌ اسم المستخدم مطلوب."); return
                        if role in ("Manager", "General_Supervisor") and (selected["role"] in ("Super_Admin", "Admin") or erole in ("Super_Admin", "Admin")):
                            st.error("⛔ المدير لا يستطيع تعديل حسابات الأدمن أو السوبر أدمن."); return
                        duplicate=conn.execute("SELECT id FROM users WHERE LOWER(TRIM(username))=LOWER(TRIM(?)) AND id<>? LIMIT 1", (eu.strip(), selected["id"])).fetchone()
                        if duplicate: st.error("❌ اسم المستخدم مستخدم بالفعل."); return
                        if selected["role"] == "Super_Admin" and erole != "Super_Admin":
                            _lock_super_admin_change(conn)
                            assert_future_super_admin_coverage(conn, excluding_user_id=selected["id"])
                            supers=conn.execute("SELECT COUNT(*) FROM users WHERE role='Super_Admin' AND is_active=1").fetchone()[0]
                            if supers <= 1: st.error("❌ لا يمكن إزالة صلاحية آخر Super Admin نشط."); return
                        if epw:
                            if local_mode:
                                try: encoded = password_hash(epw)
                                except ValueError as exc: st.error(str(exc)); return
                            else: encoded = hash_password(epw)
                            conn.execute("UPDATE users SET username=?,phone=?,password=?,role=?,branch_id=? WHERE id=?", (eu.strip(),eph,encoded,erole,allbm[ebn],selected["id"]))
                            if local_mode: conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)", ('sherif_pin_user:'+str(selected['id']),'1'))
                        else:
                            conn.execute("UPDATE users SET username=?,phone=?,role=?,branch_id=? WHERE id=?", (eu.strip(),eph,erole,allbm[ebn],selected["id"]))
                        conn.commit(); notify_success("✅ تم تعديل الحساب."); st.rerun()

                    confirm=ui_field(st.checkbox, "users:307", "أؤكد حذف الحساب المحدد", key="confirm_delete_user")
                    if st.button("🗑️ حذف حساب الدخول", type="secondary", use_container_width=True, disabled=not confirm):
                        if role in ("Manager", "General_Supervisor") and selected["role"] in ("Super_Admin", "Admin"):
                            st.error("⛔ الحساب الإداري محمي."); return
                        if selected["id"] == st.session_state.get("user_id"):
                            st.error("❌ لا يمكنك حذف حسابك أثناء تسجيل الدخول."); return
                        if selected["role"] == "Super_Admin":
                            if role != "Super_Admin":
                                st.error("❌ لا يمكن إلا لـ Super Admin حذف حساب من نفس الفئة."); return
                            _lock_super_admin_change(conn)
                            assert_future_super_admin_coverage(conn, excluding_user_id=selected["id"])
                            supers=conn.execute("SELECT COUNT(*) FROM users WHERE role='Super_Admin' AND is_active=1").fetchone()[0]
                            if supers <= 1: st.error("❌ لا يمكن حذف آخر Super Admin نشط."); return
                        conn.execute("DELETE FROM users WHERE id=?", (selected["id"],))
                        conn.commit(); notify_success("✅ تم حذف حساب الدخول. ملف الموظف -إن كان مرتبطاً- سيبقى محفوظاً بدون حساب دخول."); st.rerun()
                    if role == "Super_Admin":
                        confirmation = ui_field(st.text_input, "users:account_lifecycle_password", "تأكيد كلمة المرور لحالة الحساب", type="password", key=f"account_state_password_{selected['id']}")
                        deactivate = st.button("تعطيل الحساب", key=f"account_disable_{selected['id']}")
                        reactivate = st.button("إعادة تفعيل الحساب", key=f"account_enable_{selected['id']}")
                        if deactivate or reactivate:
                            try:
                                approve_account_state(conn, selected["id"], bool(reactivate), st.session_state.get("user_id"), confirmation)
                                conn.commit(); notify_success("تم تحديث حالة دخول الحساب."); st.rerun()
                            except PermissionError:
                                conn.rollback()
                                write_audit_event(conn,"account_state_denied",st.session_state.get("user_id"),st.session_state.get("branch_id"),"users",selected["id"],outcome="denied")
                                conn.commit()
                                st.error("تعذر اعتماد الإجراء؛ تحقق من كلمة المرور والصلاحية.")
    except Exception as ex:
        if conn: conn.rollback()
        st.error("❌ حدث خطأ في HR."); show_operation_error(ex, announce=False, context='views/users.py:399')
    finally:
        if conn: conn.close()
