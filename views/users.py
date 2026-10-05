from views.ui_common import back_button
import streamlit as st
import pandas as pd
from datetime import date
import calendar
from io import BytesIO
from database import get_db_connection, ensure_hr_schema

ROLES=["Admin","General_Supervisor","Branch_Supervisor","Cashier","Viewer"]

def due(salary,hire,end,y,m):
    md=calendar.monthrange(y,m)[1]; a=date(y,m,1); z=date(y,m,md)
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
    return d[st.selectbox("اختر الموظف:",list(d),key=key)] if d else None

def financial(conn,e,kind,amount,notes="",y=None,m=None,wd=None,md=None):
    amount=float(amount)
    if amount<=0: raise ValueError("المبلغ يجب أن يكون أكبر من صفر.")
    exp_id=None
    label={"salary":"راتب موظف","advance":"سلفة موظف","advance_repayment":"تسوية سلفة"}[kind]
    if kind in ("salary","advance"):
        r=conn.execute("""INSERT INTO expenses(branch_id,amount,description,is_general_store,expense_date)
            VALUES(?,?,?,0,CURRENT_DATE::text) RETURNING id""",
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
    return out.getvalue()

def show_page():
    back_button(key="back_users")

    try:
        ensure_hr_schema()
    except Exception as e:
        st.error("❌ تعذر تجهيز جداول الموارد البشرية في قاعدة البيانات.")
        st.code(str(e))
        return

    st.header("👥 إدارة الموظفين والمستخدمين — HR مصغرة")
    st.info("الراتب والسلفة يُحمّلان تلقائياً على مصروفات الفرع المسجل عليه الموظف.")
    role=st.session_state.get("role","")
    if role not in ("Admin","General_Supervisor"):
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
            with st.form("add_emp"):
                c1,c2=st.columns(2)
                name=c1.text_input("اسم الموظف الكامل *"); phone=c1.text_input("الهاتف")
                addr=c1.text_input("العنوان"); sal=c1.number_input("الراتب الشهري",min_value=0.,step=50.)
                hd=c1.date_input("تاريخ التعيين",date.today())
                en=c2.text_input("اسم شخص مقرب"); ep=c2.text_input("هاتف الشخص المقرب")
                er=c2.text_input("صلة القرابة"); bn=c2.selectbox("الفرع *",list(bm))
                un=c2.selectbox("ربط بحساب دخول (اختياري)",list(um))
                notes=st.text_area("ملاحظات"); ok=st.form_submit_button("💾 حفظ",type="primary")
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
                conn.commit(); st.success("✅ تم إنشاء ملف الموظف."); st.rerun()

        elif v=="edit":
            e=pick(employees(conn),"edit_emp")
            if not e: st.info("لا توجد ملفات."); return
            names=list(bm); bi=names.index(e["branch_name"])
            with st.form("edit_emp_form"):
                c1,c2=st.columns(2)
                name=c1.text_input("الاسم",e["full_name"]); phone=c1.text_input("الهاتف",e["phone"] or "")
                addr=c1.text_input("العنوان",e["address"] or "")
                sal=c1.number_input("الراتب",min_value=0.,value=float(e["monthly_salary"] or 0),step=50.)
                bn=c1.selectbox("الفرع",names,index=bi)
                en=c2.text_input("اسم شخص مقرب",e["emergency_name"] or "")
                ep=c2.text_input("هاتف الشخص المقرب",e["emergency_phone"] or "")
                er=c2.text_input("صلة القرابة",e["emergency_relation"] or "")
                hd=c2.date_input("تاريخ التعيين",e["hire_date"])
                ended=c2.checkbox("إنهاء خدمة",value=e["employment_status"]!="active")
                ed=c2.date_input("تاريخ إنهاء العمل",e["termination_date"] or date.today(),disabled=not ended)
                notes=st.text_area("ملاحظات",e["notes"] or ""); ok=st.form_submit_button("💾 حفظ",type="primary")
            if ok:
                if ended and ed<hd: st.error("تاريخ الإنهاء يسبق التعيين."); return
                conn.execute("""UPDATE employees SET full_name=?,phone=?,address=?,emergency_name=?,
                    emergency_phone=?,emergency_relation=?,branch_id=?,monthly_salary=?,hire_date=?,
                    termination_date=?,employment_status=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (name,phone,addr,en,ep,er,bm[bn],sal,hd,ed if ended else None,
                     "terminated" if ended else "active",notes,e["id"]))
                if e["user_id"]: conn.execute("UPDATE users SET branch_id=? WHERE id=?",(bm[bn],e["user_id"]))
                conn.commit(); st.success("✅ تم التحديث."); st.rerun()

        elif v=="salary":
            e=pick(employees(conn),"salary_emp")
            if not e: st.info("لا توجد ملفات."); return
            now=date.today(); c1,c2=st.columns(2)
            y=int(c1.number_input("السنة",2020,2100,now.year)); m=c2.selectbox("الشهر",range(1,13),index=now.month-1)
            total,wd,md=due(e["monthly_salary"],e["hire_date"],e["termination_date"],y,m)
            paid=float(conn.execute("""SELECT COALESCE(SUM(amount),0) FROM employee_financial_transactions
                WHERE employee_id=? AND transaction_type='salary' AND payroll_year=? AND payroll_month=?""",
                (e["id"],y,m)).fetchone()[0] or 0)
            rem=max(0.,total-paid)
            st.info(f"الراتب: {float(e['monthly_salary'] or 0):,.2f} | أيام العمل: {wd}/{md} | الاستحقاق: {total:,.2f} | المصروف: {paid:,.2f} | المتبقي: {rem:,.2f} د.ل")
            with st.form("pay_salary"):
                amt=st.number_input("المبلغ",min_value=0.,value=float(rem),step=50.)
                notes=st.text_input("ملاحظات"); ok=st.form_submit_button("💵 اعتماد الصرف",type="primary")
            if ok:
                if amt<=0 or amt>rem+.001: st.error("راجع مبلغ الاستحقاق."); return
                financial(conn,e,"salary",amt,notes,y,m,wd,md); conn.commit()
                st.success(f"✅ تم الصرف وتحميله على فرع {e['branch_name']}."); st.rerun()

        elif v in ("advance","settle"):
            e=pick(employees(conn,True) if v=="advance" else employees(conn),v+"_emp")
            if not e: st.info("لا يوجد موظفون."); return
            bal=float(conn.execute("""SELECT COALESCE(SUM(CASE WHEN transaction_type='advance' THEN amount
                WHEN transaction_type='advance_repayment' THEN -amount ELSE 0 END),0)
                FROM employee_financial_transactions WHERE employee_id=?""",(e["id"],)).fetchone()[0] or 0)
            st.info(f"رصيد السلف: {bal:,.2f} د.ل")
            with st.form(v+"_form"):
                maxv=float(max(0,bal)) if v=="settle" else None
                if v=="settle": amt=st.number_input("قيمة التسوية",min_value=0.,max_value=maxv,value=0.,step=50.)
                else: amt=st.number_input("قيمة السلفة",min_value=0.,step=50.)
                notes=st.text_input("ملاحظات"); ok=st.form_submit_button("✅ اعتماد",type="primary")
            if ok:
                financial(conn,e,"advance" if v=="advance" else "advance_repayment",amt,notes)
                conn.commit(); st.success("✅ تم تسجيل الحركة."); st.rerun()

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
            with st.form("new_user"):
                c1,c2=st.columns(2); un=c1.text_input("اسم المستخدم"); pw=c2.text_input("كلمة المرور",type="password")
                ph=c1.text_input("الهاتف"); roles=ROLES if role=="Admin" else ROLES[1:]
                rr=c2.selectbox("الصلاحية",roles); bn=st.selectbox("الفرع",list(allbm))
                ok=st.form_submit_button("➕ إنشاء حساب",type="primary")
            if ok:
                if not un.strip() or not pw: st.warning("الاسم وكلمة المرور مطلوبان."); return
                if conn.execute("SELECT id FROM users WHERE LOWER(TRIM(username))=LOWER(TRIM(?)) LIMIT 1", (un.strip(),)).fetchone():
                    st.error("❌ اسم المستخدم مستخدم بالفعل."); return
                conn.execute("INSERT INTO users(username,phone,password,role,branch_id) VALUES(?,?,?,?,?)",
                             (un.strip(),ph,pw,rr,allbm[bn])); conn.commit(); st.success("✅ تم إنشاء الحساب."); st.rerun()
            rs=conn.execute("""SELECT u.id,u.username,u.phone,u.role,COALESCE(b.branch_name,'كافة الفروع') branch_name
                FROM users u LEFT JOIN branches b ON b.id=u.branch_id ORDER BY u.id""").fetchall()
            st.dataframe(pd.DataFrame([{"رقم":r["id"],"المستخدم":r["username"],"الهاتف":r["phone"] or "",
              "الصلاحية":r["role"],"الفرع":r["branch_name"]} for r in rs]),use_container_width=True,hide_index=True)
            if rs:
                st.markdown("---")
                labels={f"#{r['id']} - {r['username']} - {r['role']}":r for r in rs}
                selected=labels[st.selectbox("اختر حساباً للتعديل أو الحذف", list(labels), key="hr_account_pick")]
                if role == "Admin":
                    with st.form("edit_user_account"):
                        c1,c2=st.columns(2)
                        eu=c1.text_input("اسم المستخدم", selected["username"])
                        eph=c1.text_input("الهاتف", selected["phone"] or "")
                        epw=c2.text_input("كلمة مرور جديدة (اتركها فارغة للإبقاء على الحالية)", type="password")
                        erole=c2.selectbox("الصلاحية", ROLES, index=ROLES.index(selected["role"]) if selected["role"] in ROLES else 0)
                        branch_names=list(allbm)
                        current_branch=selected["branch_name"] if selected["branch_name"] in allbm else "🌐 كافة الفروع"
                        ebn=st.selectbox("الفرع", branch_names, index=branch_names.index(current_branch))
                        save=st.form_submit_button("💾 حفظ تعديل الحساب", type="primary")
                    if save:
                        duplicate=conn.execute("SELECT id FROM users WHERE LOWER(TRIM(username))=LOWER(TRIM(?)) AND id<>? LIMIT 1", (eu.strip(), selected["id"])).fetchone()
                        if duplicate: st.error("❌ اسم المستخدم مستخدم بالفعل."); return
                        if selected["id"] == st.session_state.get("user_id") and erole != "Admin" and selected["role"] == "Admin":
                            admins=conn.execute("SELECT COUNT(*) FROM users WHERE role='Admin' AND is_active=1").fetchone()[0]
                            if admins <= 1: st.error("❌ لا يمكن إزالة صلاحية آخر Admin نشط."); return
                        if epw:
                            conn.execute("UPDATE users SET username=?,phone=?,password=?,role=?,branch_id=? WHERE id=?", (eu.strip(),eph,epw,erole,allbm[ebn],selected["id"]))
                        else:
                            conn.execute("UPDATE users SET username=?,phone=?,role=?,branch_id=? WHERE id=?", (eu.strip(),eph,erole,allbm[ebn],selected["id"]))
                        conn.commit(); st.success("✅ تم تعديل الحساب."); st.rerun()

                    confirm=st.checkbox("أؤكد حذف الحساب المحدد", key="confirm_delete_user")
                    if st.button("🗑️ حذف حساب الدخول", type="secondary", use_container_width=True, disabled=not confirm):
                        if selected["id"] == st.session_state.get("user_id"):
                            st.error("❌ لا يمكنك حذف حسابك أثناء تسجيل الدخول."); return
                        if selected["role"] == "Admin":
                            admins=conn.execute("SELECT COUNT(*) FROM users WHERE role='Admin' AND is_active=1").fetchone()[0]
                            if admins <= 1: st.error("❌ لا يمكن حذف آخر Admin نشط."); return
                        conn.execute("DELETE FROM users WHERE id=?", (selected["id"],))
                        conn.commit(); st.success("✅ تم حذف حساب الدخول. ملف الموظف -إن كان مرتبطاً- سيبقى محفوظاً بدون حساب دخول."); st.rerun()
    except Exception as ex:
        if conn: conn.rollback()
        st.error("❌ حدث خطأ في HR."); st.code(str(ex))
    finally:
        if conn: conn.close()
