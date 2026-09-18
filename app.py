import os
import io
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(
    page_title="مجموعة أبو زيد التجارية",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not os.path.exists("item_images"): os.makedirs("item_images")

DEFAULT_MENUS = [
    "🛒 نقطة البيع (POS)",
    "💼 إدارة الخزينة",
    "🔄 تزويد الفروع والأرشيف",
    "🏠 الرئيسية واللوحة",
    "📦 إدارة المخزن",
    "➕ الفائض والتوالف والمرتجعات",
    "🏢 إدارة الفروع",
    "📁 استيراد Excel",
    "💰 المصروفات",
    "📥 المشتريات والموردين",
    "📊 التقارير والأرباح",
    "👥 إدارة المستخدمين"
]

def initialize_database():
  try:
      conn = sqlite3.connect("abu_zaid_new_system.db", timeout=10)
      conn.execute("PRAGMA foreign_keys = ON")
      cursor = conn.cursor()

      cursor.execute("CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_name TEXT UNIQUE NOT NULL, branch_type TEXT DEFAULT 'فرع')")
      cursor.execute("""
          CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL,
              phone TEXT,
              password TEXT NOT NULL,
              role TEXT NOT NULL,
              branch_id INTEGER,
              allowed_branches TEXT DEFAULT 'ALL',
              custom_permissions TEXT DEFAULT '',
              is_active INTEGER DEFAULT 1,
              FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE SET NULL
          )
      """)
      cursor.execute("""
          CREATE TABLE IF NOT EXISTS items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              branch_id INTEGER,
              item_code TEXT,
              item_name TEXT NOT NULL,
              quantity REAL DEFAULT 0.0,
              buy_price REAL DEFAULT 0.0,
              sale_price REAL NOT NULL,
              avg_cost REAL DEFAULT 0.0,
              favorite_rank INTEGER DEFAULT 0,
              FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
          )
      """)
      cursor.execute("CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_name TEXT NOT NULL, phone TEXT, balance REAL DEFAULT 0.0)")
      cursor.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL, phone TEXT UNIQUE NOT NULL, total_purchases REAL DEFAULT 0.0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
      
      cursor.execute("""
          CREATE TABLE IF NOT EXISTS purchases (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              branch_id INTEGER,
              supplier_id INTEGER,
              supplier_name TEXT,
              invoice_number TEXT,
              total_cost REAL,
              payment_type TEXT DEFAULT 'كاش',
              items_details TEXT,
              invoice_date TEXT,
              FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
          )
      """)
      
      cursor.execute("""
          CREATE TABLE IF NOT EXISTS transfer_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              from_branch_id INTEGER,
              to_branch_id INTEGER,
              transfer_type TEXT,
              items_details TEXT,
              status TEXT DEFAULT 'معلقة',
              transfer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
          )
      """)
      cursor.execute("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, amount REAL NOT NULL, description TEXT NOT NULL, expense_date TEXT)")
      cursor.execute("""
          CREATE TABLE IF NOT EXISTS invoices (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              branch_id INTEGER,
              user_id INTEGER,
              customer_name TEXT DEFAULT 'زبون نقدي',
              customer_phone TEXT DEFAULT '',
              total_amount REAL,
              payment_method TEXT DEFAULT 'كاش',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
          )
      """)
      cursor.execute("""
          CREATE TABLE IF NOT EXISTS treasury_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              trans_type TEXT,
              amount REAL,
              description TEXT,
              trans_date TEXT
          )
      """)

      branch_count = cursor.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
      if branch_count == 0:
          default_branches = [("المخزن الرئيسي", "مخزن"), ("فرع الجزيرة", "فرع"), ("فرع 2", "فرع")]
          for b_name, b_type in default_branches:
              cursor.execute("INSERT OR IGNORE INTO branches (branch_name, branch_type) VALUES (?, ?)", (b_name, b_type))

      admin_chk = cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin' AND is_active = 1").fetchone()[0]
      if admin_chk == 0:
          cursor.execute("INSERT OR IGNORE INTO users (username, phone, password, role, allowed_branches, is_active) VALUES ('admin', '0910000000', 'admin', 'Admin', 'ALL', 1)")

      conn.commit()
      conn.close()
  except Exception as e:
      st.error(f"خطأ في قاعدة البيانات: {e}")

initialize_database()

def get_db_connection():
  conn = sqlite3.connect("abu_zaid_new_system.db", timeout=10)
  conn.execute("PRAGMA foreign_keys = ON")
  conn.row_factory = sqlite3.Row
  return conn

def verify_admin_password(pass_input):
    role = st.session_state.get("role", "")
    if role in ["Admin", "General_Supervisor"]:
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE id = ? AND password = ?", (st.session_state["user_id"], pass_input)).fetchone()
        conn.close()
        return user is not None
    return False

def check_user_permission(menu_name):
    role = st.session_state.get("role", "")
    if role in ["Admin", "General_Supervisor", "Viewer"]: return True
    if role == "Cashier" and menu_name in ["🛒 نقطة البيع (POS)", "🔄 تزويد الفروع والأرشيف", "💼 إدارة الخزينة"]: return True
    return True

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "username" not in st.session_state: st.session_state["username"] = ""
if "role" not in st.session_state: st.session_state["role"] = ""
if "user_id" not in st.session_state: st.session_state["user_id"] = None
if "branch_id" not in st.session_state: st.session_state["branch_id"] = None
if "cart" not in st.session_state: st.session_state["cart"] = []
if "page" not in st.session_state: st.session_state["page"] = "🛒 نقطة البيع (POS)"
if "unified_barcode" not in st.session_state: st.session_state["unified_barcode"] = ""
if "success_alert_msg" not in st.session_state: st.session_state["success_alert_msg"] = ""

def set_page(page_name): 
    st.session_state["page"] = page_name
    st.rerun()

if st.session_state.get("success_alert_msg", ""):
    st.success(st.session_state["success_alert_msg"])
    st.session_state["success_alert_msg"] = ""

# --- بوابة الدخول ---
if not st.session_state["logged_in"]:
  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.title("تسجيل الدخول")
    st.subheader("مجموعة أبو زيد التجارية")
    with st.form("login_form"):
      u_name = st.text_input("اسم المستخدم")
      u_pass = st.text_input("كلمة المرور", type="password")
      if st.form_submit_button("دخول", use_container_width=True):
          conn = get_db_connection()
          user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (u_name, u_pass)).fetchone()
          if user:
              st.session_state["logged_in"] = True
              st.session_state["username"] = user["username"]
              st.session_state["role"] = user["role"]
              st.session_state["user_id"] = user["id"]
              st.session_state["branch_id"] = user["branch_id"]
              conn.close(); st.rerun()
          else: 
              conn.close(); st.error("اسم المستخدم أو كلمة المرور غير صحيحة!")
  st.stop()

st.sidebar.title("مجموعة أبو زيد")
st.sidebar.write(f"المستخدم: {st.session_state['username']} ({st.session_state['role']})")
st.sidebar.markdown("---")

for m in DEFAULT_MENUS:
    if st.sidebar.button(m, use_container_width=True, key=f"btn_{m}"):
        set_page(m)

if st.sidebar.button("تسجيل الخروج", use_container_width=True):
    st.session_state.clear(); st.rerun()

choice = st.session_state["page"]

if choice == "🛒 نقطة البيع (POS)":
    st.title("نقطة البيع (POS)")
    conn = get_db_connection()
    b_id = st.session_state.get("branch_id") or 1
    
    items = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("إضافة أصناف للسلة")
        if items:
            item_opts = {f"{i['item_name']} (السعر: {i['sale_price']} د.ل - المتاح: {i['quantity']})": i for i in items}
            sel_item_label = st.selectbox("اختر الصنف:", list(item_opts.keys()))
            chosen = item_opts[sel_item_label]
            q = st.number_input("الكمية:", min_value=0.1, value=1.0, step=0.1)
            if st.button("إضافة للسلة"):
                st.session_state["cart"].append({
                    "id": chosen["id"], "name": chosen["item_name"],
                    "price": float(chosen["sale_price"]), "qty": float(q),
                    "total": float(chosen["sale_price"]) * float(q)
                })
                st.success("تمت الإضافة!")
                st.rerun()
        else:
            st.info("لا توجد أصناف في هذا الفرع حالياً.")
            
    with col2:
        st.subheader("سلة المبيعات الحالية")
        if st.session_state["cart"]:
            tot = 0
            for idx, c in enumerate(st.session_state["cart"]):
                st.write(f"- {c['name']} | الكمية: {c['qty']} | الإجمالي: {c['total']} د.ل")
                tot += c['total']
            st.markdown(f"**الإجمالي النهائي: {tot:,.2f} د.ل**")
            
            if st.button("إتمام البيع", type="primary"):
                cur = conn.cursor()
                cur.execute("INSERT INTO invoices (branch_id, user_id, total_amount) VALUES (?, ?, ?)", (b_id, st.session_state["user_id"], tot))
                for c in st.session_state["cart"]:
                    conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c['qty'], c['id']))
                conn.commit()
                st.session_state["cart"] = []
                st.session_state["success_alert_msg"] = "تمت عملية البيع بنجاح!"
                conn.close()
                st.rerun()
                
            if st.button("تفريغ السلة"):
                st.session_state["cart"] = []
                st.rerun()
        else:
            st.info("السلة فارغة.")
    conn.close()

elif choice == "💼 إدارة الخزينة":
    st.title("إدارة الخزينة")
    conn = get_db_connection()
    sales = conn.execute("SELECT SUM(total_amount) FROM invoices").fetchone()[0] or 0.0
    exps = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0.0
    st.metric("إجمالي المبيعات", f"{sales:,.2f} د.ل")
    st.metric("إجمالي المصروفات", f"{exps:,.2f} د.ل")
    st.metric("صافي الخزينة", f"{(sales - exps):,.2f} د.ل")
    conn.close()

elif choice == "📦 إدارة المخزن":
    st.title("إدارة المخزن والأصناف")
    conn = get_db_connection()
    b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
    sel_b = st.selectbox("الفرع:", list(b_dict.keys()))
    
    with st.form("add_item"):
        c = st.text_input("كود الصنف:")
        n = st.text_input("اسم الصنف:")
        qty = st.number_input("الكمية:", min_value=0.0)
        p = st.number_input("سعر البيع:", min_value=0.0)
        if st.form_submit_button("حفظ صنف جديد") and c and n:
            try:
                conn.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, sale_price) VALUES (?, ?, ?, ?, ?)", (b_dict[sel_b], c, n, qty, p))
                conn.commit()
                st.success("تم الحفظ!")
                st.rerun()
            except: st.error("الكود موجود مسبقاً.")
            
    df = pd.read_sql("SELECT item_code AS 'الكود', item_name AS 'الاسم', quantity AS 'الكمية', sale_price AS 'السعر' FROM items WHERE branch_id = ?", conn, params=(b_dict[sel_b],))
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    conn.close()

elif choice == "💰 المصروفات":
    st.title("المصروفات")
    conn = get_db_connection()
    with st.form("exp"):
        amt = st.number_input("المبلغ:", min_value=0.0)
        desc = st.text_input("البيان:")
        if st.form_submit_button("حفظ المصروف") and amt > 0 and desc:
            conn.execute("INSERT INTO expenses (amount, description, expense_date) VALUES (?, ?, ?)", (amt, desc, datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
            st.success("تم حفظ المصروف!")
            st.rerun()
    df_exp = pd.read_sql("SELECT amount AS 'المبلغ', description AS 'البيان', expense_date AS 'التاريخ' FROM expenses", conn)
    if not df_exp.empty:
        st.dataframe(df_exp, use_container_width=True)
    conn.close()

else:
    st.title(choice)
    st.info("هذه الشاشة جاهزة للتشغيل وسيتم تخصيصها حسب طلبك.")
