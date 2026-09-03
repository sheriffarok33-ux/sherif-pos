import os
import sqlite3
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="مجموعة أبو زيد التجارية - النظام السحابي",
    layout="wide",
    initial_sidebar_state="expanded",
)

# تصميم عصري للبطاقات وتحويل أزرار القائمة الجانبية لمربعات أنيقة
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
    /* تصميم أزرار القائمة الجانبية لتكون مربعات ظريفة ومتفاعلة */
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
  
  # --- الحل الجذري لمشكلة الأعمدة الناقصة في قاعدة البيانات القديمة ---
  try:
      cursor.execute("SELECT branch_id FROM items LIMIT 1")
  except:
      cursor.execute("ALTER TABLE items ADD COLUMN branch_id INTEGER DEFAULT NULL")
  
  try:
      cursor.execute("SELECT quantity FROM items LIMIT 1")
  except:
      cursor.execute("ALTER TABLE items ADD COLUMN quantity REAL DEFAULT 0.0")

  try:
      cursor.execute("SELECT buy_price FROM items LIMIT 1")
  except:
      cursor.execute("ALTER TABLE items ADD COLUMN buy_price REAL DEFAULT 0.0")

  conn.commit()
  conn.close()


initialize_database()


def get_db_connection():
  conn = sqlite3.connect("abu_zaid_system.db", timeout=10)
  conn.row_factory = sqlite3.Row
  return conn


if "logged_in" not in st.session_state:
  st.session_state["logged_in"] = False
if "username" not in st.session_state:
  st.session_state["username"] = ""
if "role" not in st.session_state:
  st.session_state["role"] = ""
if "branch_verified" not in st.session_state:
  st.session_state["branch_verified"] = False
if "cart" not in st.session_state:
  st.session_state["cart"] = []
if "page" not in st.session_state:
  st.session_state["page"] = "🏠 الرئيسية واللوحة"


def set_page(page_name):
  st.session_state["page"] = page_name


# --- شاشة تسجيل الدخول ---
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
            st.session_state["assigned_branch_id"] = user["branch_id"]
            st.rerun()
          else:
            st.error("خطأ في اسم المستخدم أو كلمة المرور!")
  st.stop()


# --- شاشة التحقق من الفرع ---
if not st.session_state["branch_verified"]:
  st.title(f"🔥 أهلاً بك يا بطل العمل، {st.session_state['username']}! استعد ليوم متميز.")
  st.info("الرجاء اختيار الفرع التابع لك لتأكيد الدخول:")

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
        st.success("تم التحقق بنجاح، جارٍ فتح النظام...")
        st.rerun()
      else:
        st.error("❌ ( هنى روحك )! هذا ليس فرعك المخصص، حاول مجدداً.")
  else:
    st.warning("لا توجد فروع مسجلة بعد. يطلب من الأدمن إضافتها أولاً.")
    if st.session_state["role"] == "Admin" and st.button("الدخول كأدمن لتسجيل الفروع"):
        st.session_state["branch_verified"] = True
        st.rerun()
  st.stop()


# --- القائمة الجانبية (تم تحويلها لمربعات أزرار أنيقة) ---
st.sidebar.markdown(f"### 👤 المستخدم: {st.session_state['username']}")
st.sidebar.markdown(f"**الصلاحية:** `{st.session_state['role']}`")
st.sidebar.markdown("---")

menu = ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)"]

if st.session_state["role"] == "Admin":
  menu.extend([
      "🏢 إدارة الشركات والفروع",
      "👥 إدارة المستخدمين",
      "📁 استيراد وتوزيع الأصناف",
      "📊 تقارير المخازن وتحويل الكميات",
      "🥜 التحميص والخلط والتصنيع",
  ])

menu.append("🚪 تسجيل الخروج")

st.sidebar.markdown("### 📂 القائمة الرئيسية")
for m in menu:
    if st.sidebar.button(m, use_container_width=True):
        if m == "🚪 تسجيل الخروج":
            st.session_state["logged_in"] = False
            st.session_state["branch_verified"] = False
            st.session_state["page"] = "🏠 الرئيسية واللوحة"
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

  # البطاقات الخارجية مربوطة الآن بالقائمة عن طريق الأزرار
  c1, c2, c3 = st.columns(3)
  with c1:
    st.markdown(f"""<div class="card" style="background-color: #2563eb;"><h3>🏢 {c_count} شركات</h3><p>{b_count} فروع مسجلة</p></div>""", unsafe_allow_html=True)
    if st.session_state["role"] == "Admin":
        st.button("⚙️ الانتقال لإدارة الشركات", on_click=set_page, args=("🏢 إدارة الشركات والفروع",), use_container_width=True, key="btn1")
  with c2:
    st.markdown(f"""<div class="card" style="background-color: #059669;"><h3>📊 {i_count} أصناف</h3><p>متاحة في المخازن</p></div>""", unsafe_allow_html=True)
    if st.session_state["role"] == "Admin":
        st.button("📦 الانتقال للمخازن", on_click=set_page, args=("📊 تقارير المخازن وتحويل الكميات",), use_container_width=True, key="btn2")
  with c3:
    st.markdown("""<div class="card" style="background-color: #ea580c;"><h3>🥜 التحميص والتصنيع</h3><p>يعمل بكفاءة</p></div>""", unsafe_allow_html=True)
    if st.session_state["role"] == "Admin":
        st.button("🔥 الانتقال لقسم التحميص", on_click=set_page, args=("🥜 التحميص والخلط والتصنيع",), use_container_width=True, key="btn3")

elif choice == "🏢 إدارة الشركات والفروع":
  st.header("🏢 إدارة الشركات والفروع")
  col1, col2 = st.columns(2)
  with col1:
    st.subheader("إضافة شركة جديدة")
    c_name = st.text_input("اسم الشركة البرمجي")
    c_title = st.text_input("الاسم الرسمي للفاتورة")
    if st.button("💾 حفظ الشركة"):
      if c_name and c_title:
        conn = get_db_connection()
        conn.execute("INSERT INTO companies (company_name, company_title) VALUES (?, ?)", (c_name, c_title))
        conn.commit()
        conn.close()
        st.success("تم حفظ الشركة بنجاح!")
        st.rerun()

  with col2:
    st.subheader("إضافة فرع جديد")
    conn = get_db_connection()
    comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
    conn.close()
    comps_dict = {c["company_name"]: c["id"] for c in comps}
    if comps_dict:
      sel_c = st.selectbox("اختر الشركة للفرع", list(comps_dict.keys()))
      b_name = st.text_input("اسم الفرع / المخزن")
      if st.button("💾 حفظ الفرع"):
        if b_name:
          conn = get_db_connection()
          conn.execute("INSERT INTO branches (company_id, branch_name) VALUES (?, ?)", (comps_dict[sel_c], b_name))
          conn.commit()
          conn.close()
          st.success("تم حفظ الفرع بنجاح!")
          st.rerun()

  st.markdown("---")
  st.subheader("📋 الشركات والفروع المسجلة")
  conn = get_db_connection()
  df_comps = pd.read_sql("SELECT * FROM companies", conn)
  df_branches = pd.read_sql("SELECT branches.id, companies.company_name AS الشركة, branches.branch_name AS الفرع FROM branches JOIN companies ON branches.company_id = companies.id", conn)
  conn.close()

  if not df_comps.empty:
    st.dataframe(df_comps, use_container_width=True)
    del_c_id = st.selectbox("معرف الشركة للحذف", df_comps["id"].tolist(), key="del_c")
    if st.button("🗑️ حذف الشركة"):
      conn = get_db_connection()
      conn.execute("DELETE FROM companies WHERE id = ?", (del_c_id,))
      conn.commit()
      conn.close()
      st.success("تم الحذف!")
      st.rerun()

  if not df_branches.empty:
    st.dataframe(df_branches, use_container_width=True)
    del_b_id = st.selectbox("معرف الفرع للحذف", df_branches["id"].tolist(), key="del_b")
    if st.button("🗑️ حذف الفرع"):
      conn = get_db_connection()
      conn.execute("DELETE FROM branches WHERE id = ?", (del_b_id,))
      conn.commit()
      conn.close()
      st.success("تم الحذف!")
      st.rerun()

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

    if st.form_submit_button("حفظ المستخدم"):
      if u and p:
        b_id = b_dict[assigned_b] if assigned_b else None
        conn = get_db_connection()
        conn.execute("INSERT INTO users (username, password, role, branch_id) VALUES (?, ?, ?, ?)", (u, p, r, b_id))
        conn.commit()
        conn.close()
        st.success("تم إضافة المستخدم!")

elif choice == "📁 استيراد وتوزيع الأصناف":
  st.header("📁 استيراد الأصناف عبر الإكسيل")
  
  def safe_float(val):
      try:
          if pd.isna(val): return 0.0
          return float(str(val).replace(',', '.').strip())
      except:
          return 0.0

  conn = get_db_connection()
  comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
  conn.close()
  comps_dict = {c["company_name"]: c["id"] for c in comps}

  if comps_dict:
    sel_comp = st.selectbox("اختر الشركة للاستيراد إليها", list(comps_dict.keys()))
    up_file = st.file_uploader("اختر ملف الإكسيل (.xlsx)", type=["xlsx", "xls"])
    if up_file and st.button("📥 تنفيذ استيراد الأصناف"):
      try:
        df = pd.read_excel(up_file, header=None)
        conn = get_db_connection()
        cur = conn.cursor()
        success_count = 0

        for idx, row in df.iterrows():
          if row.isna().all(): continue
          name = str(row.iloc[1]).strip() if len(row) > 1 and not pd.isna(row.iloc[1]) else ""
          if not name or name == "nan" or "صنف" in name or "الصنف" in name or "اسم" in name or name.lower() == "item":
            continue

          code = str(row.iloc[0]).strip() if len(row) > 0 and not pd.isna(row.iloc[0]) else ""
          qty = safe_float(row.iloc[2] if len(row) > 2 else 0.0)
          b_price = safe_float(row.iloc[3] if len(row) > 3 else 0.0)
          s_price = safe_float(row.iloc[4] if len(row) > 4 else 0.0)

          cur.execute(
              "INSERT INTO items (company_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)",
              (comps_dict[sel_comp], code, name, qty, b_price, s_price),
          )
          success_count += 1

        conn.commit()
        conn.close()
        st.success(f"🎉 تم استيراد ({success_count}) صنف بنجاح!")
      except Exception as e:
        st.error(f"حدث خطأ أثناء قراءة الملف: {e}")
  else:
    st.warning("أضف شركة أولاً ليتم توجيه الأصناف إليها.")

elif choice == "📊 تقارير المخازن وتحويل الكميات":
  st.header("📊 تقارير المخازن وتحويل الكميات للفروع")
  conn = get_db_connection()
  items_df = pd.read_sql("SELECT items.id, companies.company_name AS الشركة, branches.branch_name AS الفرع, items.item_code AS الكود, items.item_name AS الصنف, items.quantity AS الكمية, items.sale_price AS السعر FROM items JOIN companies ON items.company_id = companies.id LEFT JOIN branches ON items.branch_id = branches.id", conn)
  branches_list = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  conn.close()

  if not items_df.empty:
    st.dataframe(items_df, use_container_width=True)
    st.markdown("---")
    st.subheader("🔄 تحويل كمية من صنف لفرع آخر")
    item_ids = items_df["id"].tolist()
    sel_item_id = st.selectbox(
        "اختر الصنف المراد تحويل جزء من كميته",
        item_ids,
        format_func=lambda x: f"{items_df[items_df['id'] == x]['الصنف'].values[0]} (متاح: {items_df[items_df['id'] == x]['الكمية'].values[0]})"
    )

    b_dict = {b["branch_name"]: b["id"] for b in branches_list}
    if b_dict:
      target_branch = st.selectbox("الفرع المحول إليه", list(b_dict.keys()))
      transfer_qty = st.number_input("الكمية المراد تحويلها", min_value=0.1, value=1.0)
      if st.button("🚀 تنفيذ التحويل للفرع"):
        conn = get_db_connection()
        curr_item = conn.execute("SELECT * FROM items WHERE id = ?", (sel_item_id,)).fetchone()
        if curr_item and curr_item["quantity"] >= transfer_qty:
          conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (transfer_qty, sel_item_id))
          conn.execute("INSERT INTO items (company_id, branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?, ?)", (curr_item["company_id"], b_dict[target_branch], curr_item["item_code"], curr_item["item_name"], transfer_qty, curr_item["buy_price"], curr_item["sale_price"]))
          conn.commit()
          conn.close()
          st.success("تم تحويل الكمية بنجاح!")
          st.rerun()
        else:
          conn.close()
          st.error("الكمية لا تكفي!")

elif choice == "🥜 التحميص والخلط والتصنيع":
  st.header("🥜 إدارة عمليات التحميص، الفاقد، وخلط المكسرات")
  tab1, tab2 = st.tabs(["🔥 قسم التحميص وحساب الفاقد", "🥜 خلائط المكسرات المشكلة"])

  with tab1:
    st.subheader("تسجيل عملية تحميص")
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

        if st.button("⚙️ تنفيذ التحميص وتحديث التكلفة"):
          if new_roast_name and sel_item:
            old_price = items_dict[sel_item]["sale_price"]
            new_unit_price = (in_qty * old_price) / out_qty
            conn = get_db_connection()
            conn.execute("INSERT INTO items (branch_id, item_name, sale_price) VALUES (?, ?, ?)", (b_id, new_roast_name, round(new_unit_price, 2)))
            conn.commit()
            conn.close()
            st.success(f"تم التحميص بنجاح! سعر الكيلو الجديد: {new_unit_price:.2f} د.ل")
      else:
        st.info("لا توجد أصناف في هذا الفرع.")
    else:
      st.warning("يجب إضافة فروع أولاً.")

  with tab2:
    st.subheader("تكوين المكسرات المشكلة (Mix Nuts)")
    mix_name = st.text_input("اسم صنف المكسرات الجديد")
    total_cost = st.number_input("إجمالي التكلفة (د.ل)", min_value=0.1, value=50.0)
    profit_margin = st.number_input("نسبة هامش الربح (%)", min_value=0.0, value=20.0)

    if st.button("✨ اعتماد الخليط كصنف جديد للبيع"):
      if mix_name:
        final_price = total_cost * (1 + (profit_margin / 100))
        conn = get_db_connection()
        b_id = list(branch_dict.values())[0] if branch_dict else None
        conn.execute("INSERT INTO items (branch_id, item_name, sale_price) VALUES (?, ?, ?)", (b_id, mix_name, round(final_price, 2)))
        conn.commit()
        conn.close()
        st.success(f"تم اعتماد '{mix_name}' بسعر بيع: {final_price:.2f} د.ل بنجاح!")

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير ونقطة البيع")
  conn = get_db_connection()
  
  if st.session_state["role"] == "Admin":
      branch_items = conn.execute("SELECT item_name, sale_price FROM items").fetchall()
  else:
      branch_items = conn.execute("SELECT item_name, sale_price FROM items WHERE branch_id = ?", (st.session_state["selected_branch_id"],)).fetchall()
      
  conn.close()

  if branch_items:
    items_options = {f"{i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items}
    col1, col2 = st.columns([2, 1])
    with col1:
      chosen_item = st.selectbox("الأصناف المتاحة للبيع", list(items_options.keys()))
      qty = st.number_input("الكمية", min_value=1, value=1)
      if st.button("➕ إضافة للسلة"):
        item_data = items_options[chosen_item]
        st.session_state["cart"].append({
            "name": item_data["item_name"],
            "price": item_data["sale_price"],
            "qty": qty,
            "total": item_data["sale_price"] * qty,
        })
        st.success("تمت الإضافة للسلة")

    with col2:
      st.subheader("🛒 سلة الفاتورة الحالية")
      if st.session_state["cart"]:
        df_cart = pd.DataFrame(st.session_state["cart"])
        st.dataframe(df_cart[["name", "price", "qty", "total"]])
        grand_total = sum([x["total"] for x in st.session_state["cart"]])
        st.metric("الإجمالي النهائي", f"{grand_total:.2f} د.ل")
        if st.button("🖨️ إتمام البيع"):
          st.success("تم إتمام الفاتورة بنجاح!")
          st.session_state["cart"] = []
          st.rerun()
      else:
        st.info("السلة فارغة")
  else:
    st.info("لا توجد أصناف متاحة للبيع في هذا الفرع.")

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
