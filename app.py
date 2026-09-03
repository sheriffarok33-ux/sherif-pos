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

if not os.path.exists("company_logos"):
  os.makedirs("company_logos")

def initialize_database():
  conn = sqlite3.connect("abu_zaid_system.db", timeout=10)
  cursor = conn.cursor()

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT UNIQUE NOT NULL,
            company_title TEXT NOT NULL,
            logo_path TEXT
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            branch_name TEXT NOT NULL,
            FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT CHECK(role IN ('Admin', 'General_Supervisor', 'Branch_Supervisor', 'Cashier')) NOT NULL,
            branch_id INTEGER,
            FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE SET NULL
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            branch_id INTEGER DEFAULT NULL,
            item_code TEXT,
            item_name TEXT NOT NULL,
            quantity REAL DEFAULT 0.0,
            buy_price REAL DEFAULT 0.0,
            sale_price REAL NOT NULL,
            FOREIGN KEY (company_id) REFERENCES companies(id),
            FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER,
            user_id INTEGER,
            total_amount REAL,
            shift_status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            branch_id INTEGER,
            user_id INTEGER,
            treasury_id INTEGER,
            amount REAL NOT NULL,
            description TEXT NOT NULL,
            expense_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
            FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
        )
    """)
  # جداول الخزينة الجديدة
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS treasuries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            branch_id INTEGER, -- إذا كان NULL يعني خزينة عامة
            treasury_name TEXT NOT NULL,
            treasury_type TEXT NOT NULL, -- كاش، بنك، عهدة فرع
            balance REAL DEFAULT 0.0
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS treasury_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            treasury_id INTEGER,
            user_id INTEGER,
            trans_type TEXT NOT NULL, -- إيداع، سحب
            amount REAL NOT NULL,
            description TEXT,
            trans_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
  
  # التحديثات التلقائية للأعمدة في حال كان الجدول قديماً
  try: cursor.execute("SELECT branch_id FROM items LIMIT 1")
  except: cursor.execute("ALTER TABLE items ADD COLUMN branch_id INTEGER DEFAULT NULL")
  try: cursor.execute("SELECT quantity FROM items LIMIT 1")
  except: cursor.execute("ALTER TABLE items ADD COLUMN quantity REAL DEFAULT 0.0")
  try: cursor.execute("SELECT buy_price FROM items LIMIT 1")
  except: cursor.execute("ALTER TABLE items ADD COLUMN buy_price REAL DEFAULT 0.0")
  try: cursor.execute("SELECT treasury_id FROM expenses LIMIT 1")
  except: cursor.execute("ALTER TABLE expenses ADD COLUMN treasury_id INTEGER DEFAULT NULL")

  conn.commit()
  conn.close()

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

def set_page(page_name):
  st.session_state["page"] = page_name

def process_barcode():
    code = st.session_state.barcode_scan.strip()
    if code:
        b_id = st.session_state.get("selected_branch_id")
        conn = get_db_connection()
        item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
        conn.close()
        if item:
            st.session_state["cart"].append({
                "id": item["id"],
                "code": item["item_code"],
                "name": item["item_name"],
                "price": item["sale_price"],
                "qty": 1,
                "total": item["sale_price"] * 1
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
      submit = st.form_submit_button("🚀 دخول للنظام", use_container_width=True)

      if submit:
        if u_name == "admin" and u_pass == "admin":
          st.session_state["logged_in"] = True
          st.session_state["username"] = "admin"
          st.session_state["role"] = "Admin"
          st.session_state["user_id"] = 0
          st.session_state["branch_verified"] = True
          st.rerun()
        else:
          conn = get_db_connection()
          user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (u_name, u_pass)).fetchone()
          conn.close()
          if user:
            st.session_state["logged_in"] = True
            st.session_state["username"] = user["username"]
            st.session_state["role"] = user["role"]
            st.session_state["user_id"] = user["id"]
            st.session_state["assigned_branch_id"] = user["branch_id"]
            st.rerun()
          else:
            st.error("خطأ في اسم المستخدم أو كلمة المرور!")
  st.stop()

# --- التحقق من الفرع ---
if not st.session_state["branch_verified"]:
  st.title(f"🔥 أهلاً بك يا بطل العمل، {st.session_state['username']}!")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  conn.close()

  branch_options = {b["branch_name"]: b["id"] for b in branches}
  if branch_options:
    chosen_branch = st.selectbox("اختر فرعك المخصص", list(branch_options.keys()))
    if st.button("تأكيد الفرع والدخول"):
      chosen_id = branch_options[chosen_branch]
      if st.session_state["role"] == "Admin" or st.session_state.get("assigned_branch_id") == chosen_id:
        st.session_state["branch_verified"] = True
        st.session_state["selected_branch_id"] = chosen_id
        st.rerun()
      else:
        st.error("❌ ( هنى روحك )! هذا ليس فرعك المخصص.")
  else:
    if st.session_state["role"] == "Admin" and st.button("الدخول كأدمن لتسجيل الفروع"):
        st.session_state["branch_verified"] = True
        st.rerun()
  st.stop()

# --- القائمة الجانبية ---
st.sidebar.markdown(f"### 👤 {st.session_state['username']} | `{st.session_state['role']}`")
st.sidebar.markdown("---")
menu = ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)"]
if st.session_state["role"] == "Admin":
  menu.extend([
      "🏢 إدارة الشركات والفروع", 
      "👥 إدارة المستخدمين", 
      "📁 استيراد وتوزيع الأصناف", 
      "🏦 إدارة الخزينة والبنوك", 
      "💰 تسجيل المصروفات", 
      "📊 التقارير الشاملة والمخازن", 
      "🥜 التحميص والخلط والتصنيع"
  ])
menu.append("🚪 تسجيل الخروج")

st.sidebar.markdown("### 📂 القائمة الرئيسية")
for m in menu:
    if st.sidebar.button(m, use_container_width=True):
        if m == "🚪 تسجيل الخروج":
            st.session_state.clear()
            st.rerun()
        else:
            st.session_state["page"] = m
            st.rerun()

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
    st.subheader("إضافة شركة جديدة")
    c_name = st.text_input("اسم الشركة البرمجي")
    c_title = st.text_input("الاسم الرسمي للفاتورة")
    if st.button("💾 حفظ الشركة") and c_name:
        conn = get_db_connection()
        conn.execute("INSERT INTO companies (company_name, company_title) VALUES (?, ?)", (c_name, c_title))
        conn.commit(); conn.close(); st.success("تم الحفظ!"); st.rerun()
  with col2:
    st.subheader("إضافة فرع جديد")
    conn = get_db_connection()
    comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
    comps_dict = {c["company_name"]: c["id"] for c in comps}
    if comps_dict:
      sel_c = st.selectbox("اختر الشركة للفرع", list(comps_dict.keys()))
      b_name = st.text_input("اسم الفرع / المخزن")
      if st.button("💾 حفظ الفرع") and b_name:
          conn.execute("INSERT INTO branches (company_id, branch_name) VALUES (?, ?)", (comps_dict[sel_c], b_name))
          conn.commit(); conn.close(); st.success("تم الحفظ!"); st.rerun()

elif choice == "👥 إدارة المستخدمين":
  st.header("👥 إدارة المستخدمين والصلاحيات")
  with st.form("user_form"):
    u = st.text_input("اسم المستخدم")
    p = st.text_input("كلمة المرور", type="password")
    r = st.selectbox("الصلاحية", ["Cashier", "Branch_Supervisor", "General_Supervisor", "Admin"])
    conn = get_db_connection()
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    conn.close()
    b_dict = {b["branch_name"]: b["id"] for b in branches}
    assigned_b = st.selectbox("الفرع المخصص", list(b_dict.keys()))
    if st.form_submit_button("حفظ المستخدم") and u and p:
      b_id = b_dict[assigned_b] if assigned_b else None
      conn = get_db_connection()
      conn.execute("INSERT INTO users (username, password, role, branch_id) VALUES (?, ?, ?, ?)", (u, p, r, b_id))
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
      except:
          return 0.0

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
                if code != "":
                    existing = cur.execute("SELECT id FROM items WHERE company_id = ? AND (item_code = ? OR item_name = ?) LIMIT 1", (comps_dict[sel_comp], code, name)).fetchone()
                else:
                    existing = cur.execute("SELECT id FROM items WHERE company_id = ? AND item_name = ? LIMIT 1", (comps_dict[sel_comp], name)).fetchone()
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
  tab1, tab2, tab3 = st.tabs(["🏛️ تعريف الخزائن والبنوك", "💸 عمليات (إيداع وسحب)", "📊 أرصدة وحركات الخزائن"])
  
  conn = get_db_connection()
  
  with tab1:
      st.subheader("إنشاء خزينة / بنك / عهدة جديدة")
      branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict = {"خزينة عامة للشركة (بدون فرع محدد)": None}
      b_dict.update({b["branch_name"]: b["id"] for b in branches})
      
      with st.form("treasury_form"):
          t_name = st.text_input("اسم الخزينة/البنك (مثال: خزينة الإدارة، بنك الجمهورية، عهدة فرع طرابلس)")
          t_type = st.selectbox("نوع الخزينة", ["كاش", "بنك", "عهدة فرع"])
          t_branch = st.selectbox("الفرع التابع له", list(b_dict.keys()))
          t_bal = st.number_input("الرصيد الافتتاحي (د.ل)", value=0.0)
          
          if st.form_submit_button("حفظ الخزينة"):
              if t_name:
                  conn.execute("INSERT INTO treasuries (branch_id, treasury_name, treasury_type, balance) VALUES (?, ?, ?, ?)", 
                               (b_dict[t_branch], t_name, t_type, t_bal))
                  conn.commit()
                  st.success("تم إنشاء الحساب بنجاح!"); st.rerun()

  with tab2:
      st.subheader("إيداع أو سحب نقدي (خارج نطاق البيع والمصروفات)")
      treasuries = conn.execute("SELECT id, treasury_name, balance FROM treasuries").fetchall()
      if treasuries:
          t_options = {f"{t['treasury_name']} (الرصيد: {t['balance']:,.2f})": t['id'] for t in treasuries}
          sel_t = st.selectbox("اختر الخزينة / الحساب", list(t_options.keys()))
          trans_type = st.radio("نوع الحركة:", ["إيداع", "سحب"])
          amount = st.number_input("المبلغ (د.ل)", min_value=0.1, value=100.0)
          desc = st.text_input("البيان (تفاصيل الحركة)")
          
          if st.button("تأكيد العملية"):
              if desc:
                  t_id = t_options[sel_t]
                  if trans_type == "إيداع":
                      conn.execute("UPDATE treasuries SET balance = balance + ? WHERE id = ?", (amount, t_id))
                  else:
                      conn.execute("UPDATE treasuries SET balance = balance - ? WHERE id = ?", (amount, t_id))
                  
                  conn.execute("INSERT INTO treasury_transactions (treasury_id, user_id, trans_type, amount, description) VALUES (?, ?, ?, ?, ?)", 
                               (t_id, st.session_state["user_id"], trans_type, amount, desc))
                  conn.commit(); st.success("تم تسجيل الحركة المالية بنجاح!"); st.rerun()
              else:
                  st.warning("الرجاء إدخال البيان.")
      else:
          st.info("لا توجد خزائن معرفة بعد.")

  with tab3:
      st.subheader("أرصدة الخزائن الحالية")
      df_t = pd.read_sql("""
          SELECT treasuries.id AS 'المعرف', treasuries.treasury_name AS 'الاسم', treasuries.treasury_type AS 'النوع',
                 IFNULL(branches.branch_name, 'خزينة عامة') AS 'الفرع', treasuries.balance AS 'الرصيد'
          FROM treasuries LEFT JOIN branches ON treasuries.branch_id = branches.id
      """, conn)
      if not df_t.empty:
          st.dataframe(df_t, use_container_width=True)
          st.markdown("---")
          st.subheader("سجل الحركات المالية (كشف حساب)")
          df_trans = pd.read_sql("""
              SELECT treasury_transactions.id AS 'رقم الحركة', treasuries.treasury_name AS 'الخزينة',
                     treasury_transactions.trans_type AS 'النوع', treasury_transactions.amount AS 'المبلغ',
                     treasury_transactions.description AS 'البيان', users.username AS 'المستخدم', treasury_transactions.trans_date AS 'التاريخ'
              FROM treasury_transactions
              JOIN treasuries ON treasury_transactions.treasury_id = treasuries.id
              LEFT JOIN users ON treasury_transactions.user_id = users.id
              ORDER BY treasury_transactions.trans_date DESC
          """, conn)
          st.dataframe(df_trans, use_container_width=True)
  conn.close()

elif choice == "💰 تسجيل المصروفات":
  st.header("💰 تسجيل وإدارة المصروفات")
  conn = get_db_connection()
  comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
  comps_dict = {c["company_name"]: c["id"] for c in comps}
  
  if comps_dict:
      col1, col2 = st.columns(2)
      with col1:
          sel_comp = st.selectbox("الشركة الخاصة بالمصروف", list(comps_dict.keys()))
      with col2:
          branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id = ?", (comps_dict[sel_comp],)).fetchall()
          b_dict = {b["branch_name"]: b["id"] for b in branches}
          if b_dict:
              sel_branch = st.selectbox("الفرع", list(b_dict.keys()))
          else:
              sel_branch = None
              st.warning("لا يوجد فروع لهذه الشركة.")
      
      st.markdown("---")
      treasuries = conn.execute("SELECT id, treasury_name, balance FROM treasuries").fetchall()
      t_dict = {f"{t['treasury_name']} (رصيد: {t['balance']:,.2f})": t["id"] for t in treasuries}
      
      with st.form("expense_form"):
          amount = st.number_input("مبلغ المصروف (د.ل)", min_value=0.1, value=10.0)
          desc = st.text_input("بيان المصروف (السبب/التفاصيل)")
          
          if t_dict:
              sel_t = st.selectbox("خصم القيمة من الخزينة/البنك:", list(t_dict.keys()))
          else:
              sel_t = None
              st.error("الرجاء إضافة خزينة أو عهدة أولاً من شاشة إدارة الخزائن.")
              
          if st.form_submit_button("💾 حفظ وخصم المصروف"):
              if desc and sel_branch and sel_t:
                  t_id = t_dict[sel_t]
                  conn.execute("INSERT INTO expenses (company_id, branch_id, user_id, treasury_id, amount, description) VALUES (?, ?, ?, ?, ?, ?)", 
                               (comps_dict[sel_comp], b_dict[sel_branch], st.session_state["user_id"], t_id, amount, desc))
                  # خصم المبلغ من الخزينة وتسجيل الحركة
                  conn.execute("UPDATE treasuries SET balance = balance - ? WHERE id = ?", (amount, t_id))
                  conn.execute("INSERT INTO treasury_transactions (treasury_id, user_id, trans_type, amount, description) VALUES (?, ?, 'سحب', ?, ?)", 
                               (t_id, st.session_state["user_id"], amount, f"مصروفات: {desc}"))
                  conn.commit()
                  st.success("تم تسجيل المصروف وخصمه من الخزينة بنجاح!")
  else:
      st.info("قم بإضافة شركات أولاً.")
  conn.close()

elif choice == "📊 التقارير الشاملة والمخازن":
  st.header("📊 التقارير الشاملة (المبيعات، المخازن، والمصروفات)")
  tab1, tab2, tab3, tab4 = st.tabs(["📋 تقارير المخزون", "📈 تقارير المبيعات", "💸 تقارير المصروفات", "⚙️ تصفير السنة المالية"])
  conn = get_db_connection()
  
  with tab1:
      st.subheader("تقرير المخزن العام والفروع")
      items_df = pd.read_sql("SELECT items.id, companies.company_name AS الشركة, branches.branch_name AS الفرع, items.item_code AS الكود, items.item_name AS الصنف, items.quantity AS الكمية, items.buy_price AS 'سعر الشراء', items.sale_price AS 'سعر البيع' FROM items JOIN companies ON items.company_id = companies.id LEFT JOIN branches ON items.branch_id = branches.id", conn)
      if not items_df.empty:
          st.dataframe(items_df, use_container_width=True)
          st.download_button("📥 تصدير المخزون إلى Excel", data=to_excel(items_df), file_name="inventory.xlsx")
          
  with tab2:
      st.subheader("تقارير المبيعات (حالية وسابقة)")
      invoices_df = pd.read_sql("""
          SELECT invoices.id AS 'رقم الفاتورة/العملية', companies.company_name AS 'الشركة', branches.branch_name AS 'الفرع',
                 users.username AS 'الكاشير', invoices.total_amount AS 'المبلغ', 
                 CASE WHEN invoices.shift_status = 'open' THEN 'حالية (لم ترحل)' ELSE 'سابقة (مرحلة Z-READ)' END AS 'حالة العملية',
                 invoices.created_at AS 'التاريخ'
          FROM invoices
          LEFT JOIN branches ON invoices.branch_id = branches.id LEFT JOIN companies ON branches.company_id = companies.id LEFT JOIN users ON invoices.user_id = users.id
      """, conn)
      if not invoices_df.empty:
          st.dataframe(invoices_df, use_container_width=True)
          st.download_button("📥 تصدير المبيعات إلى Excel", data=to_excel(invoices_df), file_name="sales.xlsx")

  with tab3:
      st.subheader("تقارير المصروفات")
      expenses_df = pd.read_sql("""
          SELECT expenses.id AS 'رقم السند', companies.company_name AS 'الشركة', branches.branch_name AS 'الفرع',
                 treasuries.treasury_name AS 'خُصمت من', users.username AS 'المستخدم', expenses.amount AS 'المبلغ', 
                 expenses.description AS 'البيان', expenses.expense_date AS 'التاريخ'
          FROM expenses
          LEFT JOIN branches ON expenses.branch_id = branches.id LEFT JOIN companies ON expenses.company_id = companies.id LEFT JOIN users ON expenses.user_id = users.id LEFT JOIN treasuries ON expenses.treasury_id = treasuries.id
      """, conn)
      if not expenses_df.empty:
          st.dataframe(expenses_df, use_container_width=True)
          st.download_button("📥 تصدير المصروفات إلى Excel", data=to_excel(expenses_df), file_name="expenses.xlsx")

  with tab4:
      st.subheader("🚨 تهيئة نقطة بيع جديدة / تصفير السنة المالية")
      st.error("تنبيه: هذا الإجراء سيقوم بحذف جميع المبيعات، المصروفات، حركات الخزينة، وتصفير العدادات لتبدأ من 1. (المخزون والشركات والأرصدة ستبقى).")
      confirm_reset = st.checkbox("أؤكد أنني أريد تصفير البيانات المالية نهائياً لتهيئة الفرع/السنة.")
      if confirm_reset and st.button("🚨 تنفيذ التصفير الشامل الآن"):
          conn.execute("DELETE FROM invoices"); conn.execute("DELETE FROM expenses"); conn.execute("DELETE FROM treasury_transactions")
          conn.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name IN ('invoices', 'expenses', 'treasury_transactions')")
          conn.commit(); st.success("تم تصفير المبيعات والمصروفات وبدء دورة مالية جديدة بنجاح!"); st.rerun()
  conn.close()

elif choice == "🥜 التحميص والخلط والتصنيع":
  st.header("🥜 إدارة عمليات التحميص والخلط")
  st.info("نظام التحميص والخلط جاهز للعمل كما صممناه مسبقاً.")

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير المتقدمة (POS)")
  tab1, tab2, tab3 = st.tabs(["🛒 شاشة البيع", "📦 المرتجعات", "📊 الوردية (X/Z-READ)"])
  b_id = st.session_state.get("selected_branch_id")
  conn = get_db_connection()
  
  if st.session_state["role"] == "Admin": branch_items = conn.execute("SELECT * FROM items").fetchall()
  else: branch_items = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
      
  with tab1:
    st.text_input("🔍 مسح الباركود (Scanner):", key="barcode_scan", on_change=process_barcode)
    col_search, col_qty, col_btn = st.columns([3, 1, 1])
    with col_search:
        items_options = {f"[{i['item_code']}] {i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items} if branch_items else {}
        chosen_item = st.selectbox("أو ابحث عن الصنف يدوياً بالكتابة:", [""] + list(items_options.keys()))
    with col_qty: qty = st.number_input("الكمية", min_value=1, value=1)
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("➕ إضافة", use_container_width=True) and chosen_item:
            item_data = items_options[chosen_item]
            st.session_state["cart"].append({
                "id": item_data["id"], "code": item_data["item_code"], "name": item_data["item_name"],
                "price": item_data["sale_price"], "qty": qty, "total": item_data["sale_price"] * qty,
            }); st.rerun()

    st.markdown("---")
    st.subheader("🛒 الفاتورة الحالية")
    if st.session_state["cart"]:
        df_cart = pd.DataFrame(st.session_state["cart"])
        st.dataframe(df_cart[["code", "name", "price", "qty", "total"]], use_container_width=True)
        grand_total = sum([x["total"] for x in st.session_state["cart"]])
        st.metric("الإجمالي النهائي للفاتورة", f"{grand_total:.2f} د.ل")
        
        c_act1, c_act2, c_act3 = st.columns(3)
        with c_act1:
            if st.button("🖨️ إتمام وطباعة الفاتورة", use_container_width=True):
                conn.execute("INSERT INTO invoices (branch_id, user_id, total_amount, shift_status) VALUES (?, ?, ?, 'open')", (b_id, st.session_state["user_id"], grand_total))
                for c_item in st.session_state["cart"]:
                    conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                conn.commit()
                st.session_state["cart"] = []; st.success("تم إتمام البيع وتسجيله في الوردية!"); st.rerun()
        with c_act2:
            if st.button("⏸️ تعليق الفاتورة", use_container_width=True):
                st.session_state["held_carts"].append(st.session_state["cart"])
                st.session_state["cart"] = []; st.info("تم تعليق الفاتورة."); st.rerun()
        with c_act3:
            if st.button("🗑️ تفريغ الفاتورة", use_container_width=True):
                st.session_state["cart"] = []; st.rerun()
    if st.session_state["held_carts"]:
        if st.button("▶️ استرجاع فاتورة معلقة"):
            if not st.session_state["cart"]: st.session_state["cart"] = st.session_state["held_carts"].pop(); st.rerun()
            else: st.error("أتمم الفاتورة الحالية أولاً.")

  with tab2:
    st.subheader("📦 إدارة المرتجعات")
    if not st.session_state["return_auth"]:
        auth_pass = st.text_input("الرقم السري للمشرف لفتح المرتجعات:", type="password")
        if st.button("فتح شاشة المرتجعات"):
            if conn.execute("SELECT role FROM users WHERE password = ? AND role IN ('Admin', 'General_Supervisor', 'Branch_Supervisor')", (auth_pass,)).fetchone():
                st.session_state["return_auth"] = True; st.rerun()
            else: st.error("الرقم السري غير صحيح.")
    else:
        st.success("✅ صلاحية المرتجع مفتوحة.")
        if branch_items:
            items_options_ret = {f"[{i['item_code']}] {i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items}
            ret_item = st.selectbox("اختر الصنف المرتجع:", list(items_options_ret.keys()))
            ret_qty = st.number_input("الكمية المرتجعة", min_value=1, value=1)
            if st.button("إتمام المرتجع (خصم من الصندوق)"):
                item_data_ret = items_options_ret[ret_item]
                refund_total = item_data_ret['sale_price'] * ret_qty
                conn.execute("INSERT INTO invoices (branch_id, user_id, total_amount, shift_status) VALUES (?, ?, ?, 'open')", (b_id, st.session_state["user_id"], -refund_total))
                conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (ret_qty, item_data_ret['id']))
                conn.commit(); st.session_state["return_auth"] = False; st.success("تم إرجاع الصنف بنجاح."); st.rerun()

  with tab3:
    st.subheader("📊 قراءة وإنهاء الوردية (الشفت)")
    open_sales = conn.execute("SELECT SUM(total_amount) as total FROM invoices WHERE branch_id = ? AND shift_status = 'open'", (b_id,)).fetchone()
    shift_total = open_sales["total"] if open_sales["total"] else 0.0
    
    col_x, col_z = st.columns(2)
    with col_x: st.markdown(f"""<div class="card" style="background-color: #0284c7;"><h3>X-READ (مبيعات الوردية)</h3><h2>{shift_total:.2f} د.ل</h2></div>""", unsafe_allow_html=True)
    with col_z:
        st.markdown(f"""<div class="card" style="background-color: #be123c;"><h3>Z-READ (تصفير الوردية)</h3><h2>إنهاء العمل وإيداع بالخزينة</h2></div>""", unsafe_allow_html=True)
        treasuries_branch = conn.execute("SELECT id, treasury_name FROM treasuries WHERE branch_id = ? OR branch_id IS NULL", (b_id,)).fetchall()
        t_dict_z = {t["treasury_name"]: t["id"] for t in treasuries_branch}
        if t_dict_z:
            sel_t_z = st.selectbox("إيداع النقدية في:", list(t_dict_z.keys()))
            if st.button("🛑 تنفيذ Z-READ", use_container_width=True):
                if shift_total == 0: st.info("الوردية مصفرة بالفعل.")
                else:
                    t_id_z = t_dict_z[sel_t_z]
                    conn.execute("UPDATE invoices SET shift_status = 'closed' WHERE branch_id = ? AND shift_status = 'open'", (b_id,))
                    conn.execute("UPDATE treasuries SET balance = balance + ? WHERE id = ?", (shift_total, t_id_z))
                    conn.execute("INSERT INTO treasury_transactions (treasury_id, user_id, trans_type, amount, description) VALUES (?, ?, 'إيداع', ?, 'إغلاق وردية Z-READ')", (t_id_z, st.session_state["user_id"], shift_total))
                    conn.commit(); st.success("تم إغلاق الوردية وإيداع المبلغ في الخزينة!"); st.rerun()
        else:
            st.warning("أضف خزينة لهذا الفرع أولاً لتتمكن من إيداع مبيعات الوردية بها.")

  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
