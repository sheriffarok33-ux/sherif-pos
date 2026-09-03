import os
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
  # جدول الفواتير لضبط الشفتات X-READ و Z-READ
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

# --- إعداد متغيرات الجلسة الأساسية ---
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

# وظيفة قراءة الباركود فوراً
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
    st.session_state.barcode_scan = "" # تفريغ الخانة للصنف التالي

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
    st.warning("لا توجد فروع مسجلة بعد.")
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
    if st.button("💾 حفظ الشركة"):
      if c_name and c_title:
        conn = get_db_connection()
        conn.execute("INSERT INTO companies (company_name, company_title) VALUES (?, ?)", (c_name, c_title))
        conn.commit(); conn.close()
        st.success("تم الحفظ!"); st.rerun()

  with col2:
    st.subheader("إضافة فرع جديد")
    conn = get_db_connection()
    comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
    comps_dict = {c["company_name"]: c["id"] for c in comps}
    if comps_dict:
      sel_c = st.selectbox("اختر الشركة للفرع", list(comps_dict.keys()))
      b_name = st.text_input("اسم الفرع / المخزن")
      if st.button("💾 حفظ الفرع"):
        if b_name:
          conn.execute("INSERT INTO branches (company_id, branch_name) VALUES (?, ?)", (comps_dict[sel_c], b_name))
          conn.commit(); conn.close()
          st.success("تم الحفظ!"); st.rerun()
    else: conn.close()

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
      conn.commit(); conn.close()
      st.success("تم إضافة المستخدم!")

elif choice == "📁 استيراد وتوزيع الأصناف":
  st.header("📁 استيراد الأصناف عبر الإكسيل")
  conn = get_db_connection()
  comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
  conn.close()
  comps_dict = {c["company_name"]: c["id"] for c in comps}
  if comps_dict:
    sel_comp = st.selectbox("اختر الشركة للاستيراد إليها", list(comps_dict.keys()))
    up_file = st.file_uploader("اختر ملف الإكسيل (.xlsx)", type=["xlsx", "xls"])
    if up_file and st.button("📥 تنفيذ استيراد الأصناف"):
      df = pd.read_excel(up_file, header=None)
      conn = get_db_connection(); cur = conn.cursor()
      for idx, row in df.iterrows():
        if row.isna().all(): continue
        name = str(row.iloc[1]).strip() if len(row)>1 and not pd.isna(row.iloc[1]) else ""
        if not name or name == "nan" or "صنف" in name or name.lower() == "item": continue
        code = str(row.iloc[0]).strip() if len(row)>0 and not pd.isna(row.iloc[0]) else ""
        qty = float(str(row.iloc[2]).replace(',','.')) if len(row)>2 and not pd.isna(row.iloc[2]) else 0.0
        b_price = float(str(row.iloc[3]).replace(',','.')) if len(row)>3 and not pd.isna(row.iloc[3]) else 0.0
        s_price = float(str(row.iloc[4]).replace(',','.')) if len(row)>4 and not pd.isna(row.iloc[4]) else 0.0
        cur.execute("INSERT INTO items (company_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)", (comps_dict[sel_comp], code, name, qty, b_price, s_price))
      conn.commit(); conn.close()
      st.success(f"🎉 تم استيراد الأصناف بنجاح!")

elif choice == "📊 تقارير المخازن وتحويل الكميات":
  st.header("📊 تقارير المخازن وتحويل الكميات")
  st.info("القسم قيد التطوير والمراجعة...")

elif choice == "🥜 التحميص والخلط والتصنيع":
  st.header("🥜 إدارة عمليات التحميص والخلط")
  st.info("القسم قيد التطوير والمراجعة...")

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير المتقدمة (POS)")
  
  tab1, tab2, tab3 = st.tabs(["🛒 شاشة البيع", "📦 المرتجعات", "📊 الوردية (X/Z-READ)"])
  b_id = st.session_state.get("selected_branch_id")
  conn = get_db_connection()
  branch_items = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
  
  with tab1:
    st.subheader("إضافة الأصناف للفاتورة")
    # 1. البحث عبر الباركود
    st.text_input("🔍 مسح الباركود (Scanner):", key="barcode_scan", on_change=process_barcode, help="ضع المؤشر هنا واستخدم مسدس الباركود")
    
    col_search, col_qty, col_btn = st.columns([3, 1, 1])
    with col_search:
        # 2. البحث اليدوي بالاسم لتتضح أسماء الأصناف
        items_options = {f"[{i['item_code']}] {i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items} if branch_items else {}
        chosen_item = st.selectbox("أو ابحث عن الصنف يدوياً:", [""] + list(items_options.keys()))
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
    # عرض سلة المشتريات
    st.subheader("🛒 الفاتورة الحالية")
    if st.session_state["cart"]:
        df_cart = pd.DataFrame(st.session_state["cart"])
        st.dataframe(df_cart[["code", "name", "price", "qty", "total"]], use_container_width=True)
        grand_total = sum([x["total"] for x in st.session_state["cart"]])
        st.metric("الإجمالي النهائي للفاتورة", f"{grand_total:.2f} د.ل")
        
        c_act1, c_act2, c_act3 = st.columns(3)
        with c_act1:
            # زر إتمام الفاتورة
            if st.button("🖨️ إتمام وطباعة الفاتورة", use_container_width=True):
                # تسجيل الفاتورة في الوردية
                conn.execute("INSERT INTO invoices (branch_id, user_id, total_amount, shift_status) VALUES (?, ?, ?, 'open')", 
                             (b_id, st.session_state["user_id"], grand_total))
                conn.commit()
                st.session_state["cart"] = []
                st.success("تم إتمام البيع بنجاح وتسجيله في الوردية!")
                st.rerun()
        with c_act2:
            # زر تعليق الفاتورة لخدمة زبون آخر
            if st.button("⏸️ تعليق الفاتورة (Hold)", use_container_width=True):
                st.session_state["held_carts"].append(st.session_state["cart"])
                st.session_state["cart"] = []
                st.info("تم تعليق الفاتورة. يمكنك الآن خدمة زبون آخر.")
                st.rerun()
        with c_act3:
            if st.button("🗑️ تفريغ الفاتورة", use_container_width=True):
                st.session_state["cart"] = []
                st.rerun()
    else:
        st.info("الفاتورة فارغة حالياً. استخدم الباركود أو البحث لإضافة أصناف.")

    # استرجاع الفواتير المعلقة
    if st.session_state["held_carts"]:
        st.markdown("---")
        st.warning(f"⚠️ يوجد لديك ({len(st.session_state['held_carts'])}) فواتير معلقة (في الانتظار).")
        if st.button("▶️ استرجاع فاتورة معلقة"):
            if not st.session_state["cart"]:
                st.session_state["cart"] = st.session_state["held_carts"].pop()
                st.rerun()
            else:
                st.error("الرجاء إتمام أو تعليق الفاتورة الحالية أولاً قبل استرجاع فاتورة أخرى.")

  with tab2:
    st.subheader("📦 إدارة المرتجعات")
    if not st.session_state["return_auth"]:
        st.warning("المرتجعات تتطلب صلاحية. الرجاء من المشرف إدخال الرقم السري الخاص به:")
        auth_pass = st.text_input("الرقم السري للمشرف:", type="password")
        if st.button("فتح شاشة المرتجعات"):
            supervisor = conn.execute("SELECT role FROM users WHERE password = ? AND role IN ('Admin', 'General_Supervisor', 'Branch_Supervisor')", (auth_pass,)).fetchone()
            if supervisor:
                st.session_state["return_auth"] = True
                st.success("تمت الموافقة! يمكنك الآن إجراء مرتجع.")
                st.rerun()
            else:
                st.error("الرقم السري غير صحيح أو لا تملك صلاحية الإرجاع.")
    else:
        st.success("✅ صلاحية المرتجع مفتوحة حالياً للمشرف.")
        if branch_items:
            items_options_ret = {f"{i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items}
            ret_item = st.selectbox("اختر الصنف المراد إرجاعه:", list(items_options_ret.keys()))
            ret_qty = st.number_input("الكمية المرتجعة", min_value=1, value=1)
            
            if st.button("إتمام المرتجع (خصم من الصندوق)"):
                item_data_ret = items_options_ret[ret_item]
                refund_total = item_data_ret['sale_price'] * ret_qty
                # إدخال فاتورة بالسالب لخصمها من الشفت X-READ
                conn.execute("INSERT INTO invoices (branch_id, user_id, total_amount, shift_status) VALUES (?, ?, ?, 'open')", 
                             (b_id, st.session_state["user_id"], -refund_total))
                conn.commit()
                st.session_state["return_auth"] = False # إغلاق الصلاحية بعد العملية للأمان
                st.success(f"تم إرجاع {ret_qty} من {item_data_ret['item_name']} وخصم {refund_total} د.ل من الصندوق بنجاح.")
                st.rerun()

  with tab3:
    st.subheader("📊 قراءة وإنهاء الوردية (الشفت)")
    
    # حساب مبيعات الوردية الحالية المفتوحة
    open_sales = conn.execute("SELECT SUM(total_amount) as total FROM invoices WHERE branch_id = ? AND shift_status = 'open'", (b_id,)).fetchone()
    shift_total = open_sales["total"] if open_sales["total"] else 0.0
    
    col_x, col_z = st.columns(2)
    with col_x:
        st.markdown(f"""<div class="card" style="background-color: #0284c7;">
        <h3>X-READ (قراءة الوردية الحالية)</h3>
        <h2>{shift_total:.2f} د.ل</h2>
        <p>إجمالي المبالغ الموجودة في الصندوق حالياً</p>
        </div>""", unsafe_allow_html=True)
        if st.button("🖨️ طباعة ملخص X-READ", use_container_width=True):
            st.success("تم أمر الطباعة (قراءة فقط بدون تصفير).")
            
    with col_z:
        st.markdown(f"""<div class="card" style="background-color: #be123c;">
        <h3>Z-READ (تصفير الوردية)</h3>
        <h2>إنهاء العمل</h2>
        <p>إغلاق الوردية وتصفير المبالغ للمناوبة القادمة</p>
        </div>""", unsafe_allow_html=True)
        st.warning("هل أنت متأكد من إنهاء الوردية؟ هذا الإجراء سيقوم بتصفير درج النقدية وبدء وردية مالية جديدة.")
        if st.button("🛑 تنفيذ Z-READ (إغلاق الوردية)", use_container_width=True):
            if shift_total == 0:
                st.info("الوردية الحالية مصفرة بالفعل ولا توجد مبيعات لإغلاقها.")
            else:
                conn.execute("UPDATE invoices SET shift_status = 'closed' WHERE branch_id = ? AND shift_status = 'open'", (b_id,))
                conn.commit()
                st.success("تم إغلاق الوردية بنجاح وتصفير المبالغ! (Z-READ تم).")
                st.rerun()

  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
