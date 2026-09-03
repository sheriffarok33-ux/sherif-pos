import os
import re
import io
import sqlite3
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="مجموعة أبو زيد التجارية - النظام السحابي",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    .main { background-color: #f8fafc; }
    .card {
        padding: 20px;
        border-radius: 12px;
        color: white;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 10px;
    }
    [data-testid="stSidebar"] .stButton>button {
        background-color: #ffffff;
        color: #1e293b;
        border: 1px solid #cbd5e1;
        border-radius: 8px;
        padding: 12px;
        text-align: center;
        font-weight: bold;
        transition: all 0.3s ease;
        margin-bottom: 5px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    [data-testid="stSidebar"] .stButton>button:hover {
        background-color: #3b82f6;
        color: white;
        border-color: #2563eb;
    }
    </style>
""", unsafe_allow_html=True)

if not os.path.exists("company_logos"): os.makedirs("company_logos")

def initialize_database():
  conn = sqlite3.connect("abu_zaid_system.db", timeout=10)
  cursor = conn.cursor()
  cursor.execute("CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT UNIQUE NOT NULL, company_title TEXT NOT NULL, logo_path TEXT)")
  cursor.execute("CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, branch_name TEXT NOT NULL, FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE)")
  cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT CHECK(role IN ('Admin', 'General_Supervisor', 'Branch_Supervisor', 'Cashier')) NOT NULL, branch_id INTEGER, FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE SET NULL)")
  cursor.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, branch_id INTEGER DEFAULT NULL, item_code TEXT, item_name TEXT NOT NULL, quantity REAL DEFAULT 0.0, buy_price REAL DEFAULT 0.0, sale_price REAL NOT NULL, FOREIGN KEY (company_id) REFERENCES companies(id), FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE)")
  cursor.execute("CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, user_id INTEGER, total_amount REAL, shift_status TEXT DEFAULT 'open', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
  cursor.execute("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, branch_id INTEGER, user_id INTEGER, treasury_id INTEGER, amount REAL NOT NULL, description TEXT NOT NULL, expense_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (company_id) REFERENCES companies(id), FOREIGN KEY (branch_id) REFERENCES branches(id))")
  cursor.execute("CREATE TABLE IF NOT EXISTS treasuries (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, treasury_name TEXT NOT NULL, treasury_type TEXT NOT NULL, balance REAL DEFAULT 0.0)")
  cursor.execute("CREATE TABLE IF NOT EXISTS treasury_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, treasury_id INTEGER, user_id INTEGER, trans_type TEXT NOT NULL, amount REAL NOT NULL, description TEXT, trans_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
  
  cursor.execute("CREATE TABLE IF NOT EXISTS dict_expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
  cursor.execute("CREATE TABLE IF NOT EXISTS dict_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
  cursor.execute("CREATE TABLE IF NOT EXISTS dict_mixes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")

  try: cursor.execute("INSERT OR IGNORE INTO dict_expenses (name) VALUES ('رواتب وأجور'), ('إيجار الفرع'), ('كهرباء ومياه'), ('ضيافة ونثريات'), ('صيانة ومعدات'), ('مصروفات تسويق')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO dict_transactions (name) VALUES ('إيداع مبيعات الكاشير'), ('تغذية رصيد الخزينة/الدرج'), ('سحب أرباح للإدارة'), ('تحويل نقدية بين الفروع')")
  except: pass
  
  try: cursor.execute("SELECT branch_id FROM items LIMIT 1")
  except: cursor.execute("ALTER TABLE items ADD COLUMN branch_id INTEGER DEFAULT NULL")
  try: cursor.execute("SELECT quantity FROM items LIMIT 1")
  except: cursor.execute("ALTER TABLE items ADD COLUMN quantity REAL DEFAULT 0.0")
  try: cursor.execute("SELECT buy_price FROM items LIMIT 1")
  except: cursor.execute("ALTER TABLE items ADD COLUMN buy_price REAL DEFAULT 0.0")
  try: cursor.execute("SELECT treasury_id FROM expenses LIMIT 1")
  except: cursor.execute("ALTER TABLE expenses ADD COLUMN treasury_id INTEGER DEFAULT NULL")

  conn.commit(); conn.close()

initialize_database()

def get_db_connection():
  conn = sqlite3.connect("abu_zaid_system.db", timeout=10)
  conn.row_factory = sqlite3.Row
  return conn

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "username" not in st.session_state: st.session_state["username"] = ""
if "role" not in st.session_state: st.session_state["role"] = ""
if "user_id" not in st.session_state: st.session_state["user_id"] = None
if "branch_verified" not in st.session_state: st.session_state["branch_verified"] = False
if "cart" not in st.session_state: st.session_state["cart"] = []
if "held_carts" not in st.session_state: st.session_state["held_carts"] = []
if "return_auth" not in st.session_state: st.session_state["return_auth"] = False
if "page" not in st.session_state: st.session_state["page"] = "🏠 الرئيسية واللوحة"
if "barcode_scan" not in st.session_state: st.session_state["barcode_scan"] = ""

def set_page(page_name): st.session_state["page"] = page_name

def process_barcode():
    code = st.session_state.barcode_scan.strip()
    if code:
        b_id = st.session_state.get("selected_branch_id")
        conn = get_db_connection()
        item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
        conn.close()
        if item:
            st.session_state["cart"].append({
                "id": item["id"], "code": item["item_code"], "name": item["item_name"],
                "price": item["sale_price"], "qty": 1, "total": item["sale_price"] * 1
            })
    st.session_state.barcode_scan = ""

# --- تسجيل الدخول ---
if not st.session_state["logged_in"]:
  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.title("🔐 تسجيل الدخول")
    st.subheader("مجموعة أبو زيد التجارية")
    with st.form("login_form"):
      u_name = st.text_input("اسم المستخدم")
      u_pass = st.text_input("كلمة المرور", type="password")
      submit = st.form_submit_button("🚀 دخول للنظام (Enter)", use_container_width=True)
      if submit:
        if u_name == "admin" and u_pass == "admin":
          st.session_state["logged_in"] = True; st.session_state["username"] = "admin"; st.session_state["role"] = "Admin"; st.session_state["user_id"] = 0; st.session_state["branch_verified"] = True; st.rerun()
        else:
          conn = get_db_connection()
          user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (u_name, u_pass)).fetchone()
          conn.close()
          if user:
            st.session_state["logged_in"] = True; st.session_state["username"] = user["username"]; st.session_state["role"] = user["role"]; st.session_state["user_id"] = user["id"]; st.session_state["assigned_branch_id"] = user["branch_id"]; st.rerun()
          else: st.error("خطأ في اسم المستخدم أو كلمة المرور!")
  st.stop()

# --- التحقق من الفرع ---
if not st.session_state["branch_verified"]:
  st.title(f"🔥 أهلاً بك يا بطل العمل، {st.session_state['username']}!")
  conn = get_db_connection(); branches = conn.execute("SELECT id, branch_name FROM branches").fetchall(); conn.close()
  branch_options = {b["branch_name"]: b["id"] for b in branches}
  if branch_options:
    with st.form("branch_form"):
        chosen_branch = st.selectbox("اختر فرعك المخصص", list(branch_options.keys()))
        if st.form_submit_button("تأكيد الفرع والدخول (Enter)"):
            chosen_id = branch_options[chosen_branch]
            if st.session_state["role"] == "Admin" or st.session_state.get("assigned_branch_id") == chosen_id:
                st.session_state["branch_verified"] = True; st.session_state["selected_branch_id"] = chosen_id; st.rerun()
            else: st.error("❌ هذا ليس فرعك المخصص.")
  else:
    if st.session_state["role"] == "Admin" and st.button("الدخول كأدمن لتسجيل الفروع"):
        st.session_state["branch_verified"] = True; st.rerun()
  st.stop()

# --- القائمة الجانبية ---
st.sidebar.markdown(f"### 👤 {st.session_state['username']} | `{st.session_state['role']}`")
st.sidebar.markdown("---")
menu = ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)"]
if st.session_state["role"] == "Admin":
  menu.extend(["🏢 إدارة الشركات والفروع", "👥 إدارة المستخدمين", "📁 استيراد وتوزيع الأصناف", "🏦 إدارة الخزينة والبنوك", "💰 تسجيل المصروفات", "📊 التقارير الشاملة والمخازن", "🥜 التحميص والخلط والتصنيع"])
menu.append("🚪 تسجيل الخروج")
st.sidebar.markdown("### 📂 القائمة الرئيسية")
for m in menu:
    if st.sidebar.button(m, use_container_width=True):
        if m == "🚪 تسجيل الخروج": st.session_state.clear(); st.rerun()
        else: st.session_state["page"] = m; st.rerun()

choice = st.session_state["page"]

# --- محتوى الصفحات ---
if choice == "🏠 الرئيسية واللوحة":
  st.title("🏢 مجموعة أبو زيد التجارية - لوحة التحكم السحابية")
  conn = get_db_connection()
  c_count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
  b_count = conn.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
  i_count = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
  t_bal = conn.execute("SELECT SUM(balance) FROM treasuries").fetchone()[0]
  t_bal = t_bal if t_bal else 0.0
  conn.close()

  c1, c2, c3, c4 = st.columns(4)
  with c1: st.markdown(f"""<div class="card" style="background-color: #2563eb;"><h3>🏢 {c_count} شركات</h3><p>{b_count} فروع</p></div>""", unsafe_allow_html=True)
  with c2: st.markdown(f"""<div class="card" style="background-color: #059669;"><h3>📊 {i_count} أصناف</h3><p>في المخازن</p></div>""", unsafe_allow_html=True)
  with c3: st.markdown(f"""<div class="card" style="background-color: #0284c7;"><h3>🏦 الأرصدة</h3><p>{t_bal:,.2f} د.ل</p></div>""", unsafe_allow_html=True)
  with c4: 
    st.markdown("""<div class="card" style="background-color: #ea580c;"><h3>🛒 الكاشير</h3><p>نقطة البيع</p></div>""", unsafe_allow_html=True)
    st.button("💳 فتح الكاشير", on_click=set_page, args=("🛒 نقطة البيع (POS)",), use_container_width=True)

elif choice == "🏢 إدارة الشركات والفروع":
  st.header("🏢 إدارة الشركات والفروع")
  col1, col2 = st.columns(2)
  with col1:
    with st.form("add_comp_form", clear_on_submit=True):
        st.subheader("إضافة شركة جديدة")
        c_name = st.text_input("اسم الشركة البرمجي")
        c_title = st.text_input("الاسم الرسمي للفاتورة")
        if st.form_submit_button("💾 حفظ الشركة (Enter)") and c_name:
            conn = get_db_connection()
            conn.execute("INSERT INTO companies (company_name, company_title) VALUES (?, ?)", (c_name.strip(), c_title.strip()))
            conn.commit(); conn.close(); st.success("تم الحفظ!")
  with col2:
    conn = get_db_connection()
    comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
    comps_dict = {c["company_name"]: c["id"] for c in comps}
    if comps_dict:
      with st.form("add_branch_form", clear_on_submit=True):
          st.subheader("إضافة فرع جديد")
          sel_c = st.selectbox("اختر الشركة للفرع", list(comps_dict.keys()))
          b_name = st.text_input("اسم الفرع / المخزن")
          if st.form_submit_button("💾 حفظ الفرع (Enter)") and b_name:
              conn.execute("INSERT INTO branches (company_id, branch_name) VALUES (?, ?)", (comps_dict[sel_c], b_name.strip()))
              conn.commit(); st.success("تم الحفظ!")
    conn.close()

elif choice == "👥 إدارة المستخدمين":
  st.header("👥 إدارة المستخدمين والصلاحيات")
  with st.form("user_form", clear_on_submit=True):
    u = st.text_input("اسم المستخدم")
    p = st.text_input("كلمة المرور", type="password")
    r = st.selectbox("الصلاحية", ["Cashier", "Branch_Supervisor", "General_Supervisor", "Admin"])
    conn = get_db_connection(); branches = conn.execute("SELECT id, branch_name FROM branches").fetchall(); conn.close()
    b_dict = {b["branch_name"]: b["id"] for b in branches}
    assigned_b = st.selectbox("الفرع المخصص", list(b_dict.keys())) if b_dict else None
    if st.form_submit_button("حفظ المستخدم (Enter)") and u and p:
      b_id = b_dict[assigned_b] if assigned_b else None
      conn = get_db_connection()
      conn.execute("INSERT INTO users (username, password, role, branch_id) VALUES (?, ?, ?, ?)", (u.strip(), p, r, b_id))
      conn.commit(); conn.close(); st.success("تم إضافة المستخدم!")

elif choice == "📁 استيراد وتوزيع الأصناف":
  st.header("📁 استيراد الأصناف عبر الإكسيل")
  def safe_float(val):
      try:
          if pd.isna(val) or str(val).strip() == '': return 0.0
          s = str(val).replace(',', '.')
          s = re.sub(r'[^\d.]', '', s)
          if s.count('.') > 1:
              parts = s.split('.')
              s = parts[0] + '.' + ''.join(parts[1:])
          return float(s) if s else 0.0
      except: return 0.0

  conn = get_db_connection()
  comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
  conn.close()
  comps_dict = {c["company_name"]: c["id"] for c in comps}
  
  if comps_dict:
    sel_comp = st.selectbox("اختر الشركة لتطبيق الاستيراد عليها", list(comps_dict.keys()))
    import_mode = st.radio("طريقة الاستيراد:", ["🔄 تحديث وإضافة", "🚨 مسح كامل واستيراد جديد"])
    up_file = st.file_uploader("اختر ملف الإكسيل (.xlsx)", type=["xlsx", "xls"])
    if up_file and st.button("📥 تنفيذ استيراد الأصناف"):
      df = pd.read_excel(up_file, header=None)
      conn = get_db_connection(); cur = conn.cursor()
      added_count = 0; updated_count = 0
      if "مسح كامل" in import_mode:
          cur.execute("DELETE FROM items WHERE company_id = ?", (comps_dict[sel_comp],))
          conn.commit()
      for idx, row in df.iterrows():
        try:
            if row.isna().all(): continue
            name = str(row.iloc[1]).strip() if len(row)>1 and not pd.isna(row.iloc[1]) else ""
            if not name or name.lower() in ["nan", "null", "item"] or name in ["الصنف", "اسم الصنف", "صنف"]: continue
            code = str(row.iloc[0]).strip() if len(row)>0 and not pd.isna(row.iloc[0]) else ""
            if code.lower() in ["nan", "null", "الكود", "كود", "code"]: code = ""
            qty = safe_float(row.iloc[2] if len(row)>2 else 0.0)
            b_price = safe_float(row.iloc[3] if len(row)>3 else 0.0)
            s_price = safe_float(row.iloc[4] if len(row)>4 else 0.0)
            
            if "تحديث وإضافة" in import_mode:
                if code != "": existing = cur.execute("SELECT id FROM items WHERE company_id = ? AND (item_code = ? OR item_name = ?) LIMIT 1", (comps_dict[sel_comp], code, name)).fetchone()
                else: existing = cur.execute("SELECT id FROM items WHERE company_id = ? AND item_name = ? LIMIT 1", (comps_dict[sel_comp], name)).fetchone()
                if existing:
                    cur.execute("UPDATE items SET quantity = quantity + ?, buy_price = ?, sale_price = ? WHERE id = ?", (qty, b_price, s_price, existing["id"]))
                    updated_count += 1
                else:
                    cur.execute("INSERT INTO items (company_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)", (comps_dict[sel_comp], code, name, qty, b_price, s_price))
                    added_count += 1
            else:
                cur.execute("INSERT INTO items (company_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)", (comps_dict[sel_comp], code, name, qty, b_price, s_price))
                added_count += 1
        except Exception: continue
      conn.commit(); conn.close()
      st.success(f"🎉 تمت العملية بنجاح! تم إضافة ({added_count}) وتحديث ({updated_count}).")

elif choice == "🏦 إدارة الخزينة والبنوك":
  st.header("🏦 إدارة الخزائن، العهد، والحسابات البنكية")
  tab1, tab2, tab3 = st.tabs(["🏛️ تعريف الخزائن والبنوك", "💸 عمليات (إيداع وسحب) ذكية", "📊 أرصدة وحركات الخزائن"])
  conn = get_db_connection()
  
  with tab1:
      branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict = {"خزينة عامة للشركة (بدون فرع محدد)": None}
      b_dict.update({b["branch_name"]: b["id"] for b in branches})
      with st.form("treasury_form", clear_on_submit=True):
          t_name = st.text_input("اسم الخزينة/البنك")
          t_type = st.selectbox("نوع الخزينة", ["كاش", "بنك", "عهدة فرع"])
          t_branch = st.selectbox("الفرع التابع له", list(b_dict.keys()))
          t_bal = st.number_input("الرصيد الافتتاحي (د.ل)", value=0.0)
          if st.form_submit_button("حفظ الخزينة (Enter)") and t_name:
              conn.execute("INSERT INTO treasuries (branch_id, treasury_name, treasury_type, balance) VALUES (?, ?, ?, ?)", (b_dict[t_branch], t_name.strip(), t_type, t_bal))
              conn.commit(); st.success("تم إنشاء الحساب بنجاح!")

  with tab2:
      treasuries = conn.execute("SELECT id, treasury_name, balance FROM treasuries").fetchall()
      if treasuries:
          t_options = {f"{t['treasury_name']} (الرصيد: {t['balance']:,.2f})": t['id'] for t in treasuries}
          sel_t = st.selectbox("اختر الخزينة / الحساب", list(t_options.keys()))
          with st.form("trans_form", clear_on_submit=True):
              trans_type = st.radio("نوع الحركة:", ["إيداع", "سحب"])
              amount = st.number_input("المبلغ (د.ل)", min_value=0.1, value=100.0)
              
              trans_list = [r["name"] for r in conn.execute("SELECT name FROM dict_transactions").fetchall()]
              trans_list.append("➕ إضافة بيان حركة جديد...")
              sel_desc = st.selectbox("البيان / تفاصيل الحركة", trans_list)
              new_desc = ""
              if sel_desc == "➕ إضافة بيان حركة جديد...":
                  new_desc = st.text_input("اكتب البيان الجديد هنا:")
              
              if st.form_submit_button("تأكيد العملية (Enter)"):
                  final_desc = new_desc.strip() if sel_desc == "➕ إضافة بيان حركة جديد..." else sel_desc
                  if final_desc:
                      if sel_desc == "➕ إضافة بيان حركة جديد...": conn.execute("INSERT OR IGNORE INTO dict_transactions (name) VALUES (?)", (final_desc,))
                      t_id = t_options[sel_t]
                      if trans_type == "إيداع": conn.execute("UPDATE treasuries SET balance = balance + ? WHERE id = ?", (amount, t_id))
                      else: conn.execute("UPDATE treasuries SET balance = balance - ? WHERE id = ?", (amount, t_id))
                      conn.execute("INSERT INTO treasury_transactions (treasury_id, user_id, trans_type, amount, description) VALUES (?, ?, ?, ?, ?)", (t_id, st.session_state["user_id"], trans_type, amount, final_desc))
                      conn.commit(); st.success("تم تسجيل الحركة بنجاح!"); st.rerun()
                  else: st.warning("الرجاء تحديد أو كتابة البيان.")

  with tab3:
      df_t = pd.read_sql("SELECT treasuries.id AS 'id', treasuries.treasury_name AS 'الاسم', treasuries.treasury_type AS 'النوع', IFNULL(branches.branch_name, 'خزينة عامة') AS 'الفرع', treasuries.balance AS 'الرصيد' FROM treasuries LEFT JOIN branches ON treasuries.branch_id = branches.id", conn)
      if not df_t.empty:
          st.info("💡 يمكنك التعديل المباشر على أرصدة وأسماء الخزائن بالضغط عليها (للأدمن فقط).")
          edited_t = st.data_editor(df_t, disabled=(st.session_state["role"] == "Cashier"), hide_index=True, key="t_editor")
          if st.session_state["role"] != "Cashier" and st.button("💾 حفظ تعديلات الخزائن"):
              for idx, row in edited_t.iterrows():
                  conn.execute("UPDATE treasuries SET treasury_name=?, treasury_type=?, balance=? WHERE id=?", (row['الاسم'], row['النوع'], row['الرصيد'], row['id']))
              conn.commit(); st.success("تم التحديث!")
          
          st.markdown("---")
          st.subheader("سجل الحركات المالية (كشف حساب)")
          df_trans = pd.read_sql("SELECT treasury_transactions.id AS 'رقم', treasuries.treasury_name AS 'الخزينة', treasury_transactions.trans_type AS 'النوع', treasury_transactions.amount AS 'المبلغ', treasury_transactions.description AS 'البيان', users.username AS 'المستخدم', treasury_transactions.trans_date AS 'التاريخ' FROM treasury_transactions JOIN treasuries ON treasury_transactions.treasury_id = treasuries.id LEFT JOIN users ON treasury_transactions.user_id = users.id ORDER BY treasury_transactions.trans_date DESC", conn)
          st.dataframe(df_trans, use_container_width=True)
  conn.close()

elif choice == "💰 تسجيل المصروفات":
  st.header("💰 تسجيل وإدارة المصروفات بذكاء")
  conn = get_db_connection()
  comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
  comps_dict = {c["company_name"]: c["id"] for c in comps}
  
  if comps_dict:
      col1, col2 = st.columns(2)
      with col1: sel_comp = st.selectbox("الشركة الخاصة بالمصروف", list(comps_dict.keys()))
      with col2:
          branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id = ?", (comps_dict[sel_comp],)).fetchall()
          b_dict = {b["branch_name"]: b["id"] for b in branches}
          if b_dict: sel_branch = st.selectbox("الفرع", list(b_dict.keys()))
          else: sel_branch = None
      
      treasuries = conn.execute("SELECT id, treasury_name, balance FROM treasuries").fetchall()
      t_dict = {f"{t['treasury_name']} (رصيد: {t['balance']:,.2f})": t["id"] for t in treasuries}
      
      with st.form("expense_form", clear_on_submit=True):
          amount = st.number_input("مبلغ المصروف (د.ل)", min_value=0.1, value=10.0)
          exp_list = [r["name"] for r in conn.execute("SELECT name FROM dict_expenses").fetchall()]
          exp_list.append("➕ إضافة تصنيف/بيان مصروف جديد...")
          sel_desc = st.selectbox("تصنيف / بيان المصروف", exp_list)
          new_desc = ""
          if sel_desc == "➕ إضافة تصنيف/بيان مصروف جديد...":
              new_desc = st.text_input("اكتب البيان الجديد هنا:")

          sel_t = st.selectbox("خصم القيمة من الخزينة/البنك:", list(t_dict.keys())) if t_dict else None
              
          if st.form_submit_button("💾 حفظ وخصم المصروف (Enter)"):
              final_desc = new_desc.strip() if sel_desc == "➕ إضافة تصنيف/بيان مصروف جديد..." else sel_desc
              if final_desc and sel_branch and sel_t:
                  if sel_desc == "➕ إضافة تصنيف/بيان مصروف جديد...": conn.execute("INSERT OR IGNORE INTO dict_expenses (name) VALUES (?)", (final_desc,))
                  t_id = t_dict[sel_t]
                  conn.execute("INSERT INTO expenses (company_id, branch_id, user_id, treasury_id, amount, description) VALUES (?, ?, ?, ?, ?, ?)", (comps_dict[sel_comp], b_dict[sel_branch], st.session_state["user_id"], t_id, amount, final_desc))
                  conn.execute("UPDATE treasuries SET balance = balance - ? WHERE id = ?", (amount, t_id))
                  conn.execute("INSERT INTO treasury_transactions (treasury_id, user_id, trans_type, amount, description) VALUES (?, ?, 'سحب', ?, ?)", (t_id, st.session_state["user_id"], amount, f"مصروفات: {final_desc}"))
                  conn.commit(); st.success("تم تسجيل المصروف!"); st.rerun()
              else: st.warning("أكمل البيانات المطلوبة.")
  conn.close()

elif choice == "📊 التقارير الشاملة والمخازن":
  st.header("📊 التقارير الشاملة والمخازن (قابلة للتعديل المباشر)")
  tab1, tab2, tab3, tab4 = st.tabs(["📋 تقارير المخزون", "📈 تقارير المبيعات", "💸 تقارير المصروفات", "⚙️ تصفير البيانات للتهيئة"])
  conn = get_db_connection()
  
  with tab1:
      items_df = pd.read_sql("SELECT items.id AS id, companies.company_name AS الشركة, branches.branch_name AS الفرع, items.item_code AS الكود, items.item_name AS الصنف, items.quantity AS الكمية, items.buy_price AS 'سعر الشراء', items.sale_price AS 'سعر البيع' FROM items JOIN companies ON items.company_id = companies.id LEFT JOIN branches ON items.branch_id = branches.id", conn)
      if not items_df.empty:
          st.info("💡 يمكنك الضغط مرتين على أي خانة (الصنف، الكمية، السعر) لتعديلها مباشرة كالإكسيل.")
          # عرض الجدول التفاعلي
          edited_items = st.data_editor(items_df, disabled=(st.session_state["role"] == "Cashier"), hide_index=True, key="items_editor")
          
          c1, c2 = st.columns(2)
          with c1:
              if st.session_state["role"] != "Cashier" and st.button("💾 حفظ تعديلات المخزون"):
                  for idx, row in edited_items.iterrows():
                      conn.execute("UPDATE items SET item_code=?, item_name=?, quantity=?, buy_price=?, sale_price=? WHERE id=?", 
                                   (row['الكود'], row['الصنف'], row['الكمية'], row['سعر الشراء'], row['سعر البيع'], row['id']))
                  conn.commit(); st.success("تم حفظ التعديلات بنجاح!")
          with c2: st.download_button("📥 تصدير المخزون إلى Excel", data=to_excel(items_df), file_name="inventory.xlsx")

  with tab2:
      invoices_df = pd.read_sql("SELECT invoices.id AS 'id', companies.company_name AS 'الشركة', branches.branch_name AS 'الفرع', users.username AS 'الكاشير', invoices.total_amount AS 'المبلغ', CASE WHEN invoices.shift_status = 'open' THEN 'حالية (لم ترحل)' ELSE 'سابقة (مرحلة Z-READ)' END AS 'حالة العملية', invoices.created_at AS 'التاريخ' FROM invoices LEFT JOIN branches ON invoices.branch_id = branches.id LEFT JOIN companies ON branches.company_id = companies.id LEFT JOIN users ON invoices.user_id = users.id", conn)
      if not invoices_df.empty:
          edited_inv = st.data_editor(invoices_df, disabled=(st.session_state["role"] == "Cashier"), hide_index=True, key="inv_editor")
          c1, c2 = st.columns(2)
          with c1:
              if st.session_state["role"] != "Cashier" and st.button("💾 حفظ تعديلات المبيعات"):
                  for idx, row in edited_inv.iterrows(): conn.execute("UPDATE invoices SET total_amount=? WHERE id=?", (row['المبلغ'], row['id']))
                  conn.commit(); st.success("تم الحفظ!")
          with c2: st.download_button("📥 تصدير المبيعات إلى Excel", data=to_excel(invoices_df), file_name="sales.xlsx")

  with tab3:
      expenses_df = pd.read_sql("SELECT expenses.id AS 'id', companies.company_name AS 'الشركة', branches.branch_name AS 'الفرع', treasuries.treasury_name AS 'خُصمت من', users.username AS 'المستخدم', expenses.amount AS 'المبلغ', expenses.description AS 'البيان', expenses.expense_date AS 'التاريخ' FROM expenses LEFT JOIN branches ON expenses.branch_id = branches.id LEFT JOIN companies ON expenses.company_id = companies.id LEFT JOIN users ON expenses.user_id = users.id LEFT JOIN treasuries ON expenses.treasury_id = treasuries.id", conn)
      if not expenses_df.empty:
          edited_exp = st.data_editor(expenses_df, disabled=(st.session_state["role"] == "Cashier"), hide_index=True, key="exp_editor")
          c1, c2 = st.columns(2)
          with c1:
              if st.session_state["role"] != "Cashier" and st.button("💾 حفظ تعديلات المصروفات"):
                  for idx, row in edited_exp.iterrows(): conn.execute("UPDATE expenses SET amount=?, description=? WHERE id=?", (row['المبلغ'], row['البيان'], row['id']))
                  conn.commit(); st.success("تم الحفظ!")
          with c2: st.download_button("📥 تصدير المصروفات إلى Excel", data=to_excel(expenses_df), file_name="expenses.xlsx")

  with tab4:
      st.error("هذا الإجراء سيقوم بحذف المبيعات، المصروفات، حركات الخزينة لبدء فترة جديدة.")
      if st.checkbox("أؤكد التصفير") and st.button("🚨 تنفيذ التصفير الشامل الآن"):
          conn.execute("DELETE FROM invoices"); conn.execute("DELETE FROM expenses"); conn.execute("DELETE FROM treasury_transactions")
          conn.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name IN ('invoices', 'expenses', 'treasury_transactions')")
          conn.commit(); st.success("تم التصفير!"); st.rerun()
  conn.close()

elif choice == "🥜 التحميص والخلط والتصنيع":
  st.header("🥜 إدارة عمليات التحميص والخلط بذكاء")
  tab1, tab2 = st.tabs(["🔥 قسم التحميص وحساب الفاقد", "🥜 خلائط المكسرات المشكلة"])
  
  with tab1:
    conn = get_db_connection()
    branches = conn.execute("SELECT branches.id, branches.branch_name, companies.company_name FROM branches JOIN companies ON branches.company_id = companies.id").fetchall()
    branch_dict = {f"{b['company_name']} ➔ {b['branch_name']}": b["id"] for b in branches}
    
    if branch_dict:
      with st.form("roast_form", clear_on_submit=True):
          sel_b_roast = st.selectbox("اختر الفرع", list(branch_dict.keys()))
          b_id = branch_dict[sel_b_roast]
          items = conn.execute("SELECT item_name, sale_price FROM items WHERE branch_id = ?", (b_id,)).fetchall()
          
          items_dict = {f"{i['item_name']} ({i['sale_price']} د.ل)": i for i in items} if items else {}
          sel_item = st.selectbox("اختر الصنف الخام", list(items_dict.keys())) if items_dict else None
          in_qty = st.number_input("الوزن الخام (كيلو)", min_value=0.1, value=10.0)
          out_qty = st.number_input("الوزن الناتج (كيلو)", min_value=0.1, value=8.5)
          
          existing_items = list(set([i['item_name'] for i in items])) if items else []
          existing_items.append("➕ إضافة صنف جديد تماماً للقائمة...")
          sel_new_roast = st.selectbox("اسم الصنف الناتج بعد التحميص:", existing_items)
          new_roast = ""
          if sel_new_roast == "➕ إضافة صنف جديد تماماً للقائمة...":
              new_roast = st.text_input("اكتب اسم الصنف المحمص الجديد:")
              
          if st.form_submit_button("⚙️ تنفيذ التحميص وإضافة المخزون (Enter)"):
            final_roast_name = new_roast.strip() if sel_new_roast == "➕ إضافة صنف جديد تماماً للقائمة..." else sel_new_roast
            if final_roast_name and sel_item:
              old_price = items_dict[sel_item]["sale_price"]
              new_unit_price = (in_qty * old_price) / out_qty
              conn.execute("INSERT INTO items (branch_id, item_name, sale_price, quantity) VALUES (?, ?, ?, ?)", (b_id, final_roast_name, round(new_unit_price, 2), out_qty))
              conn.commit(); st.success(f"تم التحميص! السعر الجديد: {new_unit_price:.2f}")

  with tab2:
    with st.form("mix_form", clear_on_submit=True):
        mix_list = [r["name"] for r in conn.execute("SELECT name FROM dict_mixes").fetchall()]
        mix_list.append("➕ إضافة صنف مكسرات مشكلة جديد...")
        sel_mix = st.selectbox("اسم الصنف المُشكل", mix_list)
        new_mix = ""
        if sel_mix == "➕ إضافة صنف مكسرات مشكلة جديد...": new_mix = st.text_input("اكتب الاسم الجديد هنا:")
            
        total_cost = st.number_input("إجمالي التكلفة (د.ل)", min_value=0.1, value=50.0)
        profit_margin = st.number_input("نسبة هامش الربح (%)", min_value=0.0, value=20.0)
        
        if st.form_submit_button("✨ اعتماد وإنتاج الخليط (Enter)"):
          final_mix_name = new_mix.strip() if sel_mix == "➕ إضافة صنف مكسرات مشكلة جديد..." else sel_mix
          if final_mix_name:
            if sel_mix == "➕ إضافة صنف مكسرات مشكلة جديد...": conn.execute("INSERT OR IGNORE INTO dict_mixes (name) VALUES (?)", (final_mix_name,))
            final_price = total_cost * (1 + (profit_margin / 100))
            b_id = list(branch_dict.values())[0] if branch_dict else None
            conn.execute("INSERT INTO items (branch_id, item_name, sale_price) VALUES (?, ?, ?)", (b_id, final_mix_name, round(final_price, 2)))
            conn.commit(); st.success(f"تم اعتماد '{final_mix_name}' بسعر: {final_price:.2f}")
    conn.close()

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير المتقدمة (POS)")
  tab1, tab2, tab3 = st.tabs(["🛒 شاشة البيع", "📦 المرتجعات", "📊 الوردية (X/Z-READ)"])
  b_id = st.session_state.get("selected_branch_id")
  conn = get_db_connection()
  if st.session_state["role"] == "Admin": branch_items = conn.execute("SELECT * FROM items").fetchall()
  else: branch_items = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
      
  with tab1:
    st.text_input("🔍 مسح الباركود (Scanner):", key="barcode_scan", on_change=process_barcode)
    with st.form("pos_form", clear_on_submit=True):
        col_search, col_qty, col_btn = st.columns([3, 1, 1])
        with col_search:
            items_options = {f"[{i['item_code']}] {i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items} if branch_items else {}
            chosen_item = st.selectbox("أو ابحث عن الصنف يدوياً:", [""] + list(items_options.keys()))
        with col_qty: qty = st.number_input("الكمية", min_value=1, value=1)
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("➕ إضافة (Enter)", use_container_width=True) and chosen_item:
                item_data = items_options[chosen_item]
                st.session_state["cart"].append({"id": item_data["id"], "code": item_data["item_code"], "name": item_data["item_name"], "price": item_data["sale_price"], "qty": qty, "total": item_data["sale_price"] * qty})
                st.rerun()

    st.markdown("---")
    if st.session_state["cart"]:
        df_cart = pd.DataFrame(st.session_state["cart"])
        # هنا أيضاً يمكن للكاشير أن يرى السلة كجدول قراءة، وللمشرف التعديل (مثل حذف صنف من السلة)
        st.data_editor(df_cart[["code", "name", "price", "qty", "total"]], disabled=True, use_container_width=True)
        grand_total = sum([x["total"] for x in st.session_state["cart"]])
        st.metric("الإجمالي النهائي للفاتورة", f"{grand_total:.2f} د.ل")
        c_act1, c_act2, c_act3 = st.columns(3)
        with c_act1:
            if st.button("🖨️ إتمام وطباعة الفاتورة", use_container_width=True):
                conn.execute("INSERT INTO invoices (branch_id, user_id, total_amount, shift_status) VALUES (?, ?, ?, 'open')", (b_id, st.session_state["user_id"], grand_total))
                for c_item in st.session_state["cart"]: conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                conn.commit(); st.session_state["cart"] = []; st.success("تم إتمام البيع!"); st.rerun()
        with c_act2:
            if st.button("⏸️ تعليق الفاتورة", use_container_width=True): st.session_state["held_carts"].append(st.session_state["cart"]); st.session_state["cart"] = []; st.rerun()
        with c_act3:
            if st.button("🗑️ تفريغ الفاتورة", use_container_width=True): st.session_state["cart"] = []; st.rerun()
    if st.session_state["held_carts"] and st.button("▶️ استرجاع فاتورة معلقة"):
        if not st.session_state["cart"]: st.session_state["cart"] = st.session_state["held_carts"].pop(); st.rerun()

  with tab2:
    if not st.session_state["return_auth"]:
        with st.form("auth_form", clear_on_submit=True):
            auth_pass = st.text_input("الرقم السري للمشرف لفتح المرتجعات:", type="password")
            if st.form_submit_button("فتح شاشة المرتجعات (Enter)"):
                if conn.execute("SELECT role FROM users WHERE password = ? AND role IN ('Admin', 'General_Supervisor', 'Branch_Supervisor')", (auth_pass,)).fetchone():
                    st.session_state["return_auth"] = True; st.rerun()
                else: st.error("الرقم السري غير صحيح.")
    else:
        st.success("✅ صلاحية المرتجع مفتوحة.")
        if branch_items:
            with st.form("return_form", clear_on_submit=True):
                items_options_ret = {f"[{i['item_code']}] {i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items}
                ret_item = st.selectbox("اختر الصنف المرتجع:", list(items_options_ret.keys()))
                ret_qty = st.number_input("الكمية المرتجعة", min_value=1, value=1)
                if st.form_submit_button("إتمام المرتجع (Enter)"):
                    item_data_ret = items_options_ret[ret_item]
                    refund_total = item_data_ret['sale_price'] * ret_qty
                    conn.execute("INSERT INTO invoices (branch_id, user_id, total_amount, shift_status) VALUES (?, ?, ?, 'open')", (b_id, st.session_state["user_id"], -refund_total))
                    conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (ret_qty, item_data_ret['id']))
                    conn.commit(); st.session_state["return_auth"] = False; st.success("تم إرجاع الصنف بنجاح."); st.rerun()

  with tab3:
    open_sales = conn.execute("SELECT SUM(total_amount) as total FROM invoices WHERE branch_id = ? AND shift_status = 'open'", (b_id,)).fetchone()
    shift_total = open_sales["total"] if open_sales["total"] else 0.0
    col_x, col_z = st.columns(2)
    with col_x: st.markdown(f"""<div class="card" style="background-color: #0284c7;"><h3>X-READ (مبيعات الوردية)</h3><h2>{shift_total:.2f} د.ل</h2></div>""", unsafe_allow_html=True)
    with col_z:
        st.markdown(f"""<div class="card" style="background-color: #be123c;"><h3>Z-READ (تصفير الوردية وإيداع)</h3></div>""", unsafe_allow_html=True)
        treasuries_branch = conn.execute("SELECT id, treasury_name FROM treasuries WHERE branch_id = ? OR branch_id IS NULL", (b_id,)).fetchall()
        t_dict_z = {t["treasury_name"]: t["id"] for t in treasuries_branch}
        if t_dict_z:
            with st.form("zread_form", clear_on_submit=True):
                sel_t_z = st.selectbox("إيداع النقدية في:", list(t_dict_z.keys()))
                if st.form_submit_button("🛑 تنفيذ Z-READ (Enter)"):
                    if shift_total > 0:
                        t_id_z = t_dict_z[sel_t_z]
                        conn.execute("UPDATE invoices SET shift_status = 'closed' WHERE branch_id = ? AND shift_status = 'open'", (b_id,))
                        conn.execute("UPDATE treasuries SET balance = balance + ? WHERE id = ?", (shift_total, t_id_z))
                        conn.execute("INSERT INTO treasury_transactions (treasury_id, user_id, trans_type, amount, description) VALUES (?, ?, 'إيداع', ?, 'إغلاق وردية Z-READ')", (t_id_z, st.session_state["user_id"], shift_total))
                        conn.commit(); st.success("تم الترحيل بنجاح!"); st.rerun()
                    else: st.info("الوردية مصفرة بالفعل.")
  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
