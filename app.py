import os
import re
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
  
  try: cursor.execute("SELECT branch_id FROM items LIMIT 1")
  except: cursor.execute("ALTER TABLE items ADD COLUMN branch_id INTEGER DEFAULT NULL")
  try: cursor.execute("SELECT quantity FROM items LIMIT 1")
  except: cursor.execute("ALTER TABLE items ADD COLUMN quantity REAL DEFAULT 0.0")
  try: cursor.execute("SELECT buy_price FROM items LIMIT 1")
  except: cursor.execute("ALTER TABLE items ADD COLUMN buy_price REAL DEFAULT 0.0")

  conn.commit()
  conn.close()

initialize_database()

def get_db_connection():
  conn = sqlite3.connect("abu_zaid_system.db", timeout=10)
  conn.row_factory = sqlite3.Row
  return conn

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
  st.title(f"🔥 أهلاً بك يا بطل العمل، {st.session_state['username']}! استعد ليوم متميز.")
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
        st.error("❌ ( هنى روحك )! هذا ليس فرعك المخصص، حاول مجدداً.")
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
  menu.extend(["🏢 إدارة الشركات والفروع", "👥 إدارة المستخدمين", "📁 استيراد وتوزيع الأصناف", "📊 تقارير المخازن وتحويل الكميات", "🥜 التحميص والخلط والتصنيع"])
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
  conn.close()

  c1, c2, c3 = st.columns(3)
  with c1:
    st.markdown(f"""<div class="card" style="background-color: #2563eb;"><h3>🏢 {c_count} شركات</h3><p>{b_count} فروع مسجلة</p></div>""", unsafe_allow_html=True)
    if st.session_state["role"] == "Admin": st.button("⚙️ إدارة الشركات", on_click=set_page, args=("🏢 إدارة الشركات والفروع",), use_container_width=True)
  with c2:
    st.markdown(f"""<div class="card" style="background-color: #059669;"><h3>📊 {i_count} أصناف</h3><p>متاحة في المخازن</p></div>""", unsafe_allow_html=True)
    if st.session_state["role"] == "Admin": st.button("📦 إدارة المخازن", on_click=set_page, args=("📊 تقارير المخازن وتحويل الكميات",), use_container_width=True)
  with c3:
    st.markdown("""<div class="card" style="background-color: #ea580c;"><h3>🛒 الكاشير</h3><p>المبيعات والورديات</p></div>""", unsafe_allow_html=True)
    st.button("💳 فتح شاشة البيع", on_click=set_page, args=("🛒 نقطة البيع (POS)",), use_container_width=True)

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
          if s.count('.') > 1: # معالجة النقاط المتعددة بالخطأ
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
    
    import_mode = st.radio("طريقة الاستيراد:", [
        "🔄 تحديث وإضافة (يمنع التكرار، يضيف الكميات الجديدة ويحدث السعر)",
        "🚨 مسح كامل واستيراد جديد (يحذف كافة الأصناف للشركة ويبدأ من الصفر)"
    ])
    
    up_file = st.file_uploader("اختر ملف الإكسيل (.xlsx)", type=["xlsx", "xls"])
    if up_file and st.button("📥 تنفيذ استيراد الأصناف"):
      df = pd.read_excel(up_file, header=None)
      conn = get_db_connection(); cur = conn.cursor()
      added_count = 0
      updated_count = 0
      
      if "مسح كامل" in import_mode:
          cur.execute("DELETE FROM items WHERE company_id = ?", (comps_dict[sel_comp],))
          conn.commit()
          st.warning("تم مسح المخزون القديم لهذه الشركة.")

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
                # اصلاح المشكلة الكبرى: لا تستخدم الكود في البحث إلا إذا كان غير فارغ
                if code != "":
                    existing = cur.execute("SELECT id FROM items WHERE company_id = ? AND (item_code = ? OR item_name = ?) LIMIT 1", 
                                           (comps_dict[sel_comp], code, name)).fetchone()
                else:
                    existing = cur.execute("SELECT id FROM items WHERE company_id = ? AND item_name = ? LIMIT 1", 
                                           (comps_dict[sel_comp], name)).fetchone()

                if existing:
                    cur.execute("UPDATE items SET quantity = quantity + ?, buy_price = ?, sale_price = ? WHERE id = ?", 
                                (qty, b_price, s_price, existing["id"]))
                    updated_count += 1
                else:
                    cur.execute("INSERT INTO items (company_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)", 
                                (comps_dict[sel_comp], code, name, qty, b_price, s_price))
                    added_count += 1
            else:
                cur.execute("INSERT INTO items (company_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)", 
                            (comps_dict[sel_comp], code, name, qty, b_price, s_price))
                added_count += 1
                
        except Exception as e:
            continue
            
      conn.commit(); conn.close()
      st.success(f"🎉 تمت العملية بنجاح! تم إضافة ({added_count}) صنف جديد، وتحديث ({updated_count}) صنف موجود.")
  else:
    st.warning("أضف شركة أولاً.")

elif choice == "📊 تقارير المخازن وتحويل الكميات":
  st.header("📊 إدارة المخازن (تقارير، تحويل، تعديل وحذف)")
  
  tab1, tab2, tab3 = st.tabs(["📋 عرض المخزون", "🔄 تحويل بين الفروع", "✏️ تعديل أو حذف صنف"])
  
  conn = get_db_connection()
  items_df = pd.read_sql("SELECT items.id, companies.company_name AS الشركة, branches.branch_name AS الفرع, items.item_code AS الكود, items.item_name AS الصنف, items.quantity AS الكمية, items.buy_price AS 'سعر الشراء', items.sale_price AS 'سعر البيع' FROM items JOIN companies ON items.company_id = companies.id LEFT JOIN branches ON items.branch_id = branches.id", conn)
  branches_list = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  conn.close()

  with tab1:
      if not items_df.empty:
        search_q = st.text_input("🔍 بحث عن صنف (بالاسم أو الكود):")
        if search_q:
            mask = items_df['الصنف'].astype(str).str.contains(search_q, case=False, na=False) | items_df['الكود'].astype(str).str.contains(search_q, case=False, na=False)
            display_df = items_df[mask]
        else:
            display_df = items_df
        st.dataframe(display_df, use_container_width=True)
        st.info(f"إجمالي عدد الأصناف المعروضة: {len(display_df)} صنف.")
      else:
        st.info("المخزن فارغ حالياً.")
        
  with tab2:
      if not items_df.empty:
        st.subheader("🔄 تحويل كمية لفرع آخر")
        item_ids = items_df["id"].tolist()
        sel_item_id = st.selectbox("اختر الصنف المراد تحويله (ابحث بالكتابة):", item_ids,
            format_func=lambda x: f"[{items_df[items_df['id'] == x]['الكود'].values[0]}] {items_df[items_df['id'] == x]['الصنف'].values[0]} (متاح: {items_df[items_df['id'] == x]['الكمية'].values[0]})"
        )
        b_dict = {b["branch_name"]: b["id"] for b in branches_list}
        if b_dict:
            target_branch = st.selectbox("الفرع المحول إليه", list(b_dict.keys()))
            transfer_qty = st.number_input("الكمية المحولة", min_value=0.1, value=1.0)
            if st.button("🚀 تنفيذ التحويل للفرع"):
                conn = get_db_connection()
                curr_item = conn.execute("SELECT * FROM items WHERE id = ?", (sel_item_id,)).fetchone()
                if curr_item and curr_item["quantity"] >= transfer_qty:
                    conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (transfer_qty, sel_item_id))
                    conn.execute("INSERT INTO items (company_id, branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                (curr_item["company_id"], b_dict[target_branch], curr_item["item_code"], curr_item["item_name"], transfer_qty, curr_item["buy_price"], curr_item["sale_price"]))
                    conn.commit(); conn.close()
                    st.success("تم تحويل الكمية بنجاح!"); st.rerun()
                else:
                    conn.close(); st.error("الكمية لا تكفي!")

  with tab3:
      if not items_df.empty:
        st.subheader("✏️ تعديل صنف أو حذفه")
        edit_item_id = st.selectbox("اختر الصنف للتعديل أو الحذف:", items_df["id"].tolist(),
            format_func=lambda x: f"[{items_df[items_df['id'] == x]['الكود'].values[0]}] {items_df[items_df['id'] == x]['الصنف'].values[0]}", key="edit_item")
        
        selected_row = items_df[items_df['id'] == edit_item_id].iloc[0]
        
        with st.form("edit_item_form"):
            new_code = st.text_input("كود الصنف", value=selected_row['الكود'])
            new_name = st.text_input("اسم الصنف", value=selected_row['الصنف'])
            new_qty = st.number_input("الكمية الحالية", value=float(selected_row['الكمية']))
            new_bprice = st.number_input("سعر الشراء", value=float(selected_row['سعر الشراء']))
            new_sprice = st.number_input("سعر البيع", value=float(selected_row['سعر البيع']))
            
            c_save, c_del = st.columns(2)
            with c_save:
                if st.form_submit_button("💾 حفظ التعديلات"):
                    conn = get_db_connection()
                    conn.execute("UPDATE items SET item_code=?, item_name=?, quantity=?, buy_price=?, sale_price=? WHERE id=?", 
                                 (new_code, new_name, new_qty, new_bprice, new_sprice, edit_item_id))
                    conn.commit(); conn.close()
                    st.success("تم تعديل الصنف بنجاح!"); st.rerun()
            with c_del:
                if st.form_submit_button("🗑️ حذف الصنف نهائياً"):
                    conn = get_db_connection()
                    conn.execute("DELETE FROM items WHERE id=?", (edit_item_id,))
                    conn.commit(); conn.close()
                    st.success("تم الحذف بنجاح!"); st.rerun()
                    
        st.markdown("---")
        if st.button("🚨 تصفير المخزن بالكامل وحذف كافة الأصناف (خطر)"):
            conn = get_db_connection()
            conn.execute("DELETE FROM items")
            conn.commit(); conn.close()
            st.warning("تم تصفير المخزن بالكامل!"); st.rerun()

elif choice == "🥜 التحميص والخلط والتصنيع":
  st.header("🥜 إدارة عمليات التحميص والخلط")
  tab1, tab2 = st.tabs(["🔥 قسم التحميص وحساب الفاقد", "🥜 خلائط المكسرات المشكلة"])
  with tab1:
    conn = get_db_connection()
    branches = conn.execute("SELECT branches.id, branches.branch_name, companies.company_name FROM branches JOIN companies ON branches.company_id = companies.id").fetchall()
    conn.close()
    branch_dict = {f"{b['company_name']} ➔ {b['branch_name']}": b["id"] for b in branches}
    
    if branch_dict:
      sel_b_roast = st.selectbox("اختر الفرع", list(branch_dict.keys()))
      b_id = branch_dict[sel_b_roast]
      conn = get_db_connection()
      items = conn.execute("SELECT item_name, sale_price FROM items WHERE branch_id = ?", (b_id,)).fetchall()
      conn.close()
      
      if items:
        items_dict = {f"{i['item_name']} ({i['sale_price']} د.ل)": i for i in items}
        sel_item = st.selectbox("اختر الصنف الخام", list(items_dict.keys()))
        in_qty = st.number_input("الوزن الخام المرسل (كيلو)", min_value=0.1, value=10.0)
        out_qty = st.number_input("الوزن الناتج بعد التحميص (كيلو)", min_value=0.1, value=8.5)
        new_roast_name = st.text_input("اسم الصنف الجديد بعد التحميص")
        if st.button("⚙️ تنفيذ التحميص"):
          if new_roast_name and sel_item:
            old_price = items_dict[sel_item]["sale_price"]
            new_unit_price = (in_qty * old_price) / out_qty
            conn = get_db_connection()
            conn.execute("INSERT INTO items (branch_id, item_name, sale_price) VALUES (?, ?, ?)", (b_id, new_roast_name, round(new_unit_price, 2)))
            conn.commit(); conn.close()
            st.success(f"تم التحميص بنجاح! سعر الكيلو الجديد: {new_unit_price:.2f} د.ل")

  with tab2:
    mix_name = st.text_input("اسم صنف المكسرات الجديد")
    total_cost = st.number_input("إجمالي التكلفة (د.ل)", min_value=0.1, value=50.0)
    profit_margin = st.number_input("نسبة هامش الربح (%)", min_value=0.0, value=20.0)
    if st.button("✨ اعتماد الخليط"):
      if mix_name:
        final_price = total_cost * (1 + (profit_margin / 100))
        conn = get_db_connection()
        b_id = list(branch_dict.values())[0] if branch_dict else None
        conn.execute("INSERT INTO items (branch_id, item_name, sale_price) VALUES (?, ?, ?)", (b_id, mix_name, round(final_price, 2)))
        conn.commit(); conn.close()
        st.success(f"تم اعتماد '{mix_name}' بسعر بيع: {final_price:.2f} د.ل بنجاح!")

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير المتقدمة (POS)")
  tab1, tab2, tab3 = st.tabs(["🛒 شاشة البيع", "📦 المرتجعات", "📊 الوردية (X/Z-READ)"])
  b_id = st.session_state.get("selected_branch_id")
  conn = get_db_connection()
  
  if st.session_state["role"] == "Admin":
      branch_items = conn.execute("SELECT * FROM items").fetchall()
  else:
      branch_items = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
      
  with tab1:
    st.subheader("إضافة الأصناف للفاتورة")
    st.text_input("🔍 مسح الباركود (Scanner):", key="barcode_scan", on_change=process_barcode)
    
    col_search, col_qty, col_btn = st.columns([3, 1, 1])
    with col_search:
        items_options = {f"[{i['item_code']}] {i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items} if branch_items else {}
        chosen_item = st.selectbox("أو ابحث عن الصنف يدوياً بالكتابة:", [""] + list(items_options.keys()))
    with col_qty:
        qty = st.number_input("الكمية", min_value=1, value=1)
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("➕ إضافة", use_container_width=True) and chosen_item:
            item_data = items_options[chosen_item]
            st.session_state["cart"].append({
                "id": item_data["id"],
                "code": item_data["item_code"],
                "name": item_data["item_name"],
                "price": item_data["sale_price"],
                "qty": qty,
                "total": item_data["sale_price"] * qty,
            })
            st.rerun()

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
                st.session_state["cart"] = []
                st.success("تم إتمام البيع وتسجيله في الوردية وخصم الكمية!"); st.rerun()
        with c_act2:
            if st.button("⏸️ تعليق الفاتورة (Hold)", use_container_width=True):
                st.session_state["held_carts"].append(st.session_state["cart"])
                st.session_state["cart"] = []
                st.info("تم تعليق الفاتورة."); st.rerun()
        with c_act3:
            if st.button("🗑️ تفريغ الفاتورة", use_container_width=True):
                st.session_state["cart"] = []; st.rerun()
    else:
        st.info("الفاتورة فارغة حالياً.")

    if st.session_state["held_carts"]:
        st.markdown("---")
        st.warning(f"⚠️ يوجد ({len(st.session_state['held_carts'])}) فواتير معلقة.")
        if st.button("▶️ استرجاع فاتورة معلقة"):
            if not st.session_state["cart"]:
                st.session_state["cart"] = st.session_state["held_carts"].pop()
                st.rerun()
            else:
                st.error("أتمم الفاتورة الحالية أولاً.")

  with tab2:
    st.subheader("📦 إدارة المرتجعات")
    if not st.session_state["return_auth"]:
        st.warning("الرجاء إدخال الرقم السري للمشرف لفتح المرتجعات:")
        auth_pass = st.text_input("الرقم السري للمشرف:", type="password")
        if st.button("فتح شاشة المرتجعات"):
            supervisor = conn.execute("SELECT role FROM users WHERE password = ? AND role IN ('Admin', 'General_Supervisor', 'Branch_Supervisor')", (auth_pass,)).fetchone()
            if supervisor:
                st.session_state["return_auth"] = True
                st.success("تمت الموافقة!"); st.rerun()
            else:
                st.error("الرقم السري غير صحيح.")
    else:
        st.success("✅ صلاحية المرتجع مفتوحة.")
        if branch_items:
            items_options_ret = {f"[{i['item_code']}] {i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items}
            ret_item = st.selectbox("اختر الصنف المراد إرجاعه:", list(items_options_ret.keys()))
            ret_qty = st.number_input("الكمية المرتجعة", min_value=1, value=1)
            
            if st.button("إتمام المرتجع (خصم من الصندوق وإرجاع للمخزن)"):
                item_data_ret = items_options_ret[ret_item]
                refund_total = item_data_ret['sale_price'] * ret_qty
                conn.execute("INSERT INTO invoices (branch_id, user_id, total_amount, shift_status) VALUES (?, ?, ?, 'open')", (b_id, st.session_state["user_id"], -refund_total))
                conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (ret_qty, item_data_ret['id']))
                conn.commit()
                st.session_state["return_auth"] = False
                st.success(f"تم إرجاع الصنف وخصم {refund_total} د.ل من الصندوق بنجاح."); st.rerun()

  with tab3:
    st.subheader("📊 قراءة وإنهاء الوردية (الشفت)")
    open_sales = conn.execute("SELECT SUM(total_amount) as total FROM invoices WHERE branch_id = ? AND shift_status = 'open'", (b_id,)).fetchone()
    shift_total = open_sales["total"] if open_sales["total"] else 0.0
    
    col_x, col_z = st.columns(2)
    with col_x:
        st.markdown(f"""<div class="card" style="background-color: #0284c7;"><h3>X-READ (مبيعات الوردية)</h3><h2>{shift_total:.2f} د.ل</h2><p>إجمالي المبالغ في الصندوق حالياً</p></div>""", unsafe_allow_html=True)
    with col_z:
        st.markdown(f"""<div class="card" style="background-color: #be123c;"><h3>Z-READ (تصفير الوردية)</h3><h2>إنهاء العمل</h2><p>إغلاق الوردية وتصفير المبالغ</p></div>""", unsafe_allow_html=True)
        if st.button("🛑 تنفيذ Z-READ (إغلاق الوردية)", use_container_width=True):
            if shift_total == 0:
                st.info("الوردية الحالية مصفرة بالفعل.")
            else:
                conn.execute("UPDATE invoices SET shift_status = 'closed' WHERE branch_id = ? AND shift_status = 'open'", (b_id,))
                conn.commit()
                st.success("تم إغلاق الوردية بنجاح وتصفير المبالغ! (Z-READ تم)."); st.rerun()

  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
