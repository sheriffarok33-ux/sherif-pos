import os
import re
import io
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime

st.set_page_config(
    page_title="مجموعة أبو زيد التجارية - النظام السحابي",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Tajawal', sans-serif; }
    .main { background-color: #f4f7f6; }
    div.stButton > button { border-radius: 10px; font-weight: 700; transition: all 0.3s ease; }
    [data-testid="stSidebar"] .stButton>button {
        background-color: #ffffff; color: #1e293b; border: 1px solid #e2e8f0;
        border-radius: 12px; padding: 10px 15px; text-align: right; font-weight: bold;
        transition: all 0.3s ease; margin-bottom: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.02); font-size: 16px;
    }
    [data-testid="stSidebar"] .stButton>button:hover { background-color: #2563eb; color: white; border-color: #2563eb; transform: translateX(-5px); }
    .card { padding: 20px; border-radius: 12px; color: white; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

if not os.path.exists("company_logos"): os.makedirs("company_logos")

ALL_MENUS = [
    "🏠 الرئيسية واللوحة",
    "🛒 نقطة البيع (POS)",
    "🏢 إدارة الشركات والفروع",
    "👥 إدارة المستخدمين والصلاحيات",
    "📁 استيراد وتوزيع الأصناف",
    "🏦 إدارة الخزينة والبنوك",
    "💰 تسجيل المصروفات",
    "📊 التقارير الشاملة والمخازن",
    "🥜 التحميص والخلط والتصنيع"
]

def initialize_database():
  conn = sqlite3.connect("abu_zaid_system.db", timeout=10)
  cursor = conn.cursor()

  cursor.execute("CREATE TABLE IF NOT EXISTS companies (id INTEGER PRIMARY KEY AUTOINCREMENT, company_name TEXT UNIQUE NOT NULL, company_title TEXT NOT NULL, logo_path TEXT)")
  cursor.execute("CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, branch_name TEXT NOT NULL, FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE)")
  
  cursor.execute("""
      CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL,
          phone TEXT,
          password TEXT NOT NULL,
          role TEXT NOT NULL,
          branch_id INTEGER,
          company_id INTEGER,
          is_active INTEGER DEFAULT 1,
          FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE SET NULL,
          FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL
      )
  """)
  
  cursor.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, branch_id INTEGER DEFAULT NULL, item_code TEXT, item_name TEXT NOT NULL, quantity REAL DEFAULT 0.0, buy_price REAL DEFAULT 0.0, sale_price REAL NOT NULL, FOREIGN KEY (company_id) REFERENCES companies(id), FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE)")
  cursor.execute("CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, user_id INTEGER, total_amount REAL, payment_method TEXT DEFAULT 'كاش', notes TEXT, shift_status TEXT DEFAULT 'open', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
  cursor.execute("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, branch_id INTEGER, user_id INTEGER, treasury_id INTEGER, amount REAL NOT NULL, description TEXT NOT NULL, expense_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (company_id) REFERENCES companies(id), FOREIGN KEY (branch_id) REFERENCES branches(id))")
  cursor.execute("CREATE TABLE IF NOT EXISTS treasuries (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, branch_id INTEGER, treasury_name TEXT NOT NULL, treasury_type TEXT NOT NULL, balance REAL DEFAULT 0.0)")
  cursor.execute("CREATE TABLE IF NOT EXISTS treasury_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, treasury_id INTEGER, user_id INTEGER, trans_type TEXT NOT NULL, amount REAL NOT NULL, description TEXT, trans_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
  
  cursor.execute("CREATE TABLE IF NOT EXISTS dict_expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
  cursor.execute("CREATE TABLE IF NOT EXISTS dict_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
  cursor.execute("CREATE TABLE IF NOT EXISTS dict_mixes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
  cursor.execute("CREATE TABLE IF NOT EXISTS user_branches (user_id INTEGER, branch_id INTEGER, PRIMARY KEY (user_id, branch_id))")
  
  cursor.execute("CREATE TABLE IF NOT EXISTS role_permissions (role TEXT PRIMARY KEY, allowed_menus TEXT)")
  cursor.execute("CREATE TABLE IF NOT EXISTS activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Admin', ?)", (",".join(ALL_MENUS),))
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('General_Supervisor', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),👥 إدارة المستخدمين والصلاحيات,📁 استيراد وتوزيع الأصناف,🏦 إدارة الخزينة والبنوك,💰 تسجيل المصروفات,📊 التقارير الشاملة والمخازن,🥜 التحميص والخلط والتصنيع')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Branch_Supervisor', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),💰 تسجيل المصروفات,📊 التقارير الشاملة والمخازن')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Cashier', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS)')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Viewer', ?)", (",".join(ALL_MENUS),))
  except: pass

  try: cursor.execute("INSERT OR IGNORE INTO dict_expenses (name) VALUES ('رواتب وأجور'), ('إيجار الفرع'), ('كهرباء ومياه'), ('ضيافة ونثريات'), ('صيانة ومعدات'), ('مصروفات تسويق')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO dict_transactions (name) VALUES ('إيداع مبيعات الكاشير'), ('تغذية رصيد الخزينة/الدرج'), ('سحب أرباح للإدارة'), ('تحويل نقدية بين الفروع')")
  except: pass
  
  try: cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT")
  except: pass
  try: cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
  except: pass
  try: cursor.execute("ALTER TABLE invoices ADD COLUMN payment_method TEXT DEFAULT 'كاش'")
  except: pass
  try: cursor.execute("ALTER TABLE invoices ADD COLUMN notes TEXT")
  except: pass

  admin_chk = cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin' AND is_active = 1").fetchone()[0]
  if admin_chk == 0:
      cursor.execute("INSERT OR IGNORE INTO users (username, phone, password, role, is_active) VALUES ('admin', '0910000000', 'admin', 'Admin', 1)")

  conn.commit(); conn.close()

initialize_database()

def get_db_connection():
  conn = sqlite3.connect("abu_zaid_system.db", timeout=10)
  conn.execute("PRAGMA foreign_keys = ON")
  conn.row_factory = sqlite3.Row
  return conn

def log_action(user_id, action, details):
    if not user_id: return
    conn = get_db_connection()
    conn.execute("INSERT INTO activity_logs (user_id, action, details) VALUES (?, ?, ?)", (user_id, action, details))
    conn.commit(); conn.close()

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False, sheet_name='Sheet1')
    return output.getvalue()

def get_allowed_companies(conn):
    if st.session_state["role"] == "Admin": return conn.execute("SELECT id, company_name FROM companies").fetchall()
    elif st.session_state["company_id"]: return conn.execute("SELECT id, company_name FROM companies WHERE id = ?", (st.session_state["company_id"],)).fetchall()
    return []

if "logged_in" not in st.session_state: st.session_state["logged_in"] = False
if "username" not in st.session_state: st.session_state["username"] = ""
if "role" not in st.session_state: st.session_state["role"] = ""
if "user_id" not in st.session_state: st.session_state["user_id"] = None
if "company_id" not in st.session_state: st.session_state["company_id"] = None
if "branch_verified" not in st.session_state: st.session_state["branch_verified"] = False
if "assigned_branches" not in st.session_state: st.session_state["assigned_branches"] = []
if "allowed_menus" not in st.session_state: st.session_state["allowed_menus"] = ALL_MENUS
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
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.title("🔐 بوابة الدخول")
    st.subheader("مجموعة أبو زيد التجارية (القابضة)")
    
    with st.form("login_form"):
      u_name = st.text_input("اسم المستخدم")
      u_pass = st.text_input("كلمة المرور", type="password")
      submit = st.form_submit_button("🚀 دخول للنظام (Enter)", use_container_width=True)
      if submit:
          conn = get_db_connection()
          user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (u_name, u_pass)).fetchone()
          if user:
              if user["is_active"] == 0:
                  st.error("🚫 هذا الحساب موقوف! راجع الإدارة.")
                  conn.close(); st.stop()
                  
              st.session_state["logged_in"] = True
              st.session_state["username"] = user["username"]
              st.session_state["role"] = user["role"]
              st.session_state["user_id"] = user["id"]
              st.session_state["company_id"] = user["company_id"]
              
              user_branches_db = conn.execute("SELECT branch_id FROM user_branches WHERE user_id = ?", (user["id"],)).fetchall()
              assigned = [b["branch_id"] for b in user_branches_db]
              if user["branch_id"] is not None and user["branch_id"] not in assigned: assigned.append(user["branch_id"])
              st.session_state["assigned_branches"] = assigned
              
              if user["role"] in ["Admin", "Viewer"] or user["username"].strip().lower() in ["admin", "شريف"]:
                  st.session_state["branch_verified"] = True
                  st.session_state["selected_branch_id"] = None
                  st.session_state["role"] = "Admin"
              
              if st.session_state["role"] == "Admin":
                  st.session_state["allowed_menus"] = ALL_MENUS
              else:
                  perms = conn.execute("SELECT allowed_menus FROM role_permissions WHERE role = ?", (user["role"],)).fetchone()
                  if perms and perms["allowed_menus"]: st.session_state["allowed_menus"] = perms["allowed_menus"].split(",")
                  else: st.session_state["allowed_menus"] = ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)"]
              
              log_action(user["id"], "تسجيل دخول", f"تم دخول المستخدم {user['username']}")
              conn.close(); st.rerun()
          else: 
              conn.close(); st.error("🎭 **هَنّي روحك.. اسم المستخدم أو كلمة المرور غير صحيحة!** (خطأ تسجيل دخول)")
  st.stop()

# --- التحقق من الفرع ---
if not st.session_state["branch_verified"]:
  if st.session_state["role"] in ["Admin", "Viewer"] or st.session_state["username"].strip().lower() in ["admin", "شريف"]:
      st.session_state["branch_verified"] = True
      st.session_state["selected_branch_id"] = None
      st.rerun()
      
  st.title(f"🔥 أهلاً بك، {st.session_state['username']}!")
  conn = get_db_connection()
  
  placeholders = ', '.join('?' for _ in st.session_state["assigned_branches"])
  if placeholders: branches = conn.execute(f"SELECT branches.id, branches.branch_name, companies.company_name FROM branches JOIN companies ON branches.company_id = companies.id WHERE branches.id IN ({placeholders})", st.session_state["assigned_branches"]).fetchall()
  else: branches = []
  conn.close()
  
  branch_options = {f"🏢 {b['company_name']} ➔ 📍 {b['branch_name']}": b["id"] for b in branches}
  
  if branch_options:
    with st.form("branch_form"):
        chosen_branch = st.selectbox("اختر الفرع للبدء بالعمل:", list(branch_options.keys()))
        if st.form_submit_button("تأكيد الفرع والدخول (Enter)"):
            st.session_state["branch_verified"] = True; st.session_state["selected_branch_id"] = branch_options[chosen_branch]
            log_action(st.session_state["user_id"], "اختيار فرع", f"تم فتح العمل على الفرع: {chosen_branch}")
            st.rerun()
  else:
    st.error("🎭 **هَنّي روحك.. ليس لديك أي فروع مخصصة لحسابك!** (خطأ صلاحية فرع)")
    if st.button("🔄 تسجيل الخروج"):
        st.session_state.clear()
        st.rerun()
  st.stop()

# --- القائمة الجانبية والشعار ---
conn = get_db_connection()
if st.session_state["role"] in ["Admin", "Viewer"] or st.session_state["username"].strip().lower() in ["admin", "شريف"]: 
    logo_row = conn.execute("SELECT logo_path FROM companies WHERE logo_path IS NOT NULL AND logo_path != '' LIMIT 1").fetchone()
else: 
    logo_row = conn.execute("SELECT logo_path FROM companies WHERE id = ? AND logo_path IS NOT NULL AND logo_path != ''", (st.session_state["company_id"],)).fetchone()
conn.close()

if logo_row and os.path.exists(logo_row["logo_path"]): st.sidebar.image(logo_row["logo_path"], use_container_width=True)
else: st.sidebar.markdown("<h2 style='text-align: center;'>🏢 مجموعة أبو زيد التجارية (القابضة)</h2>", unsafe_allow_html=True)

st.sidebar.markdown(f"**👤 {st.session_state['username']} | `{st.session_state['role']}`**")
st.sidebar.markdown("---")

menu_to_show = [m for m in ALL_MENUS if m in st.session_state["allowed_menus"] or st.session_state["role"] in ["Admin", "Viewer"] or st.session_state["username"].strip().lower() in ["admin", "شريف"]]
menu_to_show.append("🚪 تسجيل الخروج")

for m in menu_to_show:
    if st.sidebar.button(m, use_container_width=True):
        if m == "🚪 تسجيل الخروج":
            log_action(st.session_state["user_id"], "تسجيل خروج", "تم تسجيل الخروج من النظام")
            st.session_state.clear(); st.rerun()
        else: st.session_state["page"] = m; st.rerun()

choice = st.session_state["page"]

dashboard_cards = {
    "🛒 نقطة البيع (POS)": {"icon": "🛒", "color": "linear-gradient(135deg, #f59e0b, #ea580c)", "desc": "الكاشير والمبيعات"},
    "🏢 إدارة الشركات والفروع": {"icon": "🏢", "color": "linear-gradient(135deg, #3b82f6, #1d4ed8)", "desc": "الشركات والهيكل التنظيمي"},
    "👥 إدارة المستخدمين والصلاحيات": {"icon": "👥", "color": "linear-gradient(135deg, #8b5cf6, #6d28d9)", "desc": "الموظفين والصلاحيات والسجلات"},
    "📁 استيراد وتوزيع الأصناف": {"icon": "📁", "color": "linear-gradient(135deg, #10b981, #047857)", "desc": "استيراد المخزون من Excel"},
    "🏦 إدارة الخزينة والبنوك": {"icon": "🏦", "color": "linear-gradient(135deg, #0ea5e9, #0369a1)", "desc": "الأرصدة، البنوك، العهد"},
    "💰 تسجيل المصروفات": {"icon": "💸", "color": "linear-gradient(135deg, #ef4444, #be123c)", "desc": "سداد الإيجارات والرواتب"},
    "📊 التقارير الشاملة والمخازن": {"icon": "📊", "color": "linear-gradient(135deg, #6366f1, #4338ca)", "desc": "جرد ومراقبة الأرباح"},
    "🥜 التحميص والخلط والتصنيع": {"icon": "🥜", "color": "linear-gradient(135deg, #d946ef, #a21caf)", "desc": "حساب الفاقد وخلط المكسرات"}
}

# --- محتوى الصفحات ---
if choice == "🏠 الرئيسية واللوحة":
  st.title("🌟 مجموعة أبو زيد التجارية (القابضة) - لوحة التحكم الرئيسية")
  admin_options = [m for m in menu_to_show if m not in ["🏠 الرئيسية واللوحة", "🚪 تسجيل الخروج"]]
  cols = st.columns(3)
  for i, item in enumerate(admin_options):
      data = dashboard_cards.get(item, {"icon": "✨", "color": "linear-gradient(135deg, #64748b, #475569)", "desc": "إدارة القسم"})
      with cols[i % 3]:
          st.markdown(f'''<div style="background: {data['color']}; padding: 25px 15px; border-radius: 16px; color: white; text-align: center; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); margin-bottom: 10px; min-height: 150px;"><h1 style="margin:0; font-size: 45px;">{data['icon']}</h1><h3 style="margin: 10px 0 5px 0;">{item.split(" ", 1)[1]}</h3><p style="margin:0; font-size: 14px; opacity: 0.9;">{data['desc']}</p></div>''', unsafe_allow_html=True)
          st.button(f"دخول ➔", key=f"btn_{i}", on_click=set_page, args=(item,), use_container_width=True)
          st.markdown("<br>", unsafe_allow_html=True)

elif choice == "🏢 إدارة الشركات والفروع":
  st.header("🏢 إدارة الشركات والفروع (تحت مجموعة أبو زيد القابضة)")
  conn = get_db_connection()
  is_viewer = (st.session_state["role"] == "Viewer")
  
  if st.session_state["role"] == "Admin" and not is_viewer:
      with st.expander("➕ إضافة شركة جديدة تابعة للمجموعة", expanded=False):
          with st.form("add_comp_form", clear_on_submit=True):
              c_name = st.text_input("اسم الشركة البرمجي (مثال: محامص أبو زيد)")
              c_title = st.text_input("الاسم الرسمي للفاتورة")
              logo_file = st.file_uploader("شعار الشركة", type=["png", "jpg", "jpeg"])
              if st.form_submit_button("💾 حفظ الشركة") and c_name:
                  logo_path = ""
                  if logo_file:
                      logo_path = os.path.join("company_logos", logo_file.name)
                      with open(logo_path, "wb") as f: f.write(logo_file.getbuffer())
                  conn.execute("INSERT INTO companies (company_name, company_title, logo_path) VALUES (?, ?, ?)", (c_name.strip(), c_title.strip(), logo_path))
                  conn.commit(); log_action(st.session_state["user_id"], "إضافة شركة", f"تم إضافة شركة: {c_name}"); st.success("🎉 تم حفظ الشركة بنجاح!")
                  st.rerun()

  comps = get_allowed_companies(conn)
  comps_dict = {c["company_name"]: c["id"] for c in comps}
  
  if comps_dict and not is_viewer:
      with st.expander("➕ إضافة فرع جديد لأي شركة", expanded=False):
          with st.form("add_branch_form", clear_on_submit=True):
              sel_c = st.selectbox("اختر الشركة التابعة لها الفرع", list(comps_dict.keys()))
              b_name = st.text_input("اسم الفرع / المخزن")
              if st.form_submit_button("💾 حفظ الفرع") and b_name:
                  conn.execute("INSERT INTO branches (company_id, branch_name) VALUES (?, ?)", (comps_dict[sel_c], b_name.strip()))
                  conn.commit(); log_action(st.session_state["user_id"], "إضافة فرع", f"تم إضافة فرع {b_name} للشركة {sel_c}"); st.success("🎉 تم حفظ الفرع بنجاح!")
                  st.rerun()

  st.markdown("---")
  st.subheader("📋 الهيكل التنظيمي للمجموعة")
  for comp in comps:
      st.markdown(f"### 📁 شركة تابعة: **{comp['company_name']}**")
      branches_df = pd.read_sql("SELECT id, branch_name AS 'اسم الفرع' FROM branches WHERE company_id = ?", conn, params=(comp["id"],))
      c1, c2 = st.columns([2, 1])
      with c1:
          if not branches_df.empty:
              edited_b = st.data_editor(branches_df, disabled=is_viewer, hide_index=True, key=f"eb_{comp['id']}")
              if not is_viewer and st.button(f"💾 حفظ تعديلات فروع ({comp['company_name']})", key=f"save_b_{comp['id']}"):
                  for idx, row in edited_b.iterrows(): conn.execute("UPDATE branches SET branch_name=? WHERE id=?", (row['اسم الفرع'], row['id']))
                  conn.commit(); log_action(st.session_state["user_id"], "تعديل فروع", f"تم تعديل فروع شركة {comp['company_name']}"); st.success("🎉 تم تحديث الفروع بنجاح!")
                  st.rerun()
          else: st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;└─ ⚠️ *لا توجد فروع مسجلة لهذه الشركة.*")
      with c2:
          if not is_viewer:
              if st.session_state["role"] == "Admin" and st.button(f"🗑️ حذف الشركة ({comp['company_name']})", type="primary", key=f"del_c_{comp['id']}"):
                  conn.execute("DELETE FROM companies WHERE id=?", (comp["id"],)); conn.commit(); log_action(st.session_state["user_id"], "حذف شركة", f"تم حذف شركة {comp['company_name']}"); st.success("🗑️ تم حذف الشركة بنجاح!")
                  st.rerun()
              if not branches_df.empty:
                  del_b_id = st.selectbox("اختر فرعاً للحذف:", branches_df["id"].tolist(), format_func=lambda x: branches_df[branches_df["id"]==x]["اسم الفرع"].values[0], key=f"sel_del_{comp['id']}")
                  if st.button("🗑️ حذف الفرع المحدد", key=f"btn_del_{comp['id']}"):
                      conn.execute("DELETE FROM branches WHERE id=?", (del_b_id,)); conn.commit(); log_action(st.session_state["user_id"], "حذف فرع", f"تم حذف الفرع من شركة {comp['company_name']}"); st.success("🗑️ تم حذف الفرع بنجاح!")
                      st.rerun()
      st.markdown("<hr style='border:1px dashed #cbd5e1'>", unsafe_allow_html=True)
  conn.close()

elif choice == "👥 إدارة المستخدمين والصلاحيات":
  st.header("👥 إدارة المستخدمين والصلاحيات")
  tab1, tab2, tab3 = st.tabs(["👥 حسابات المستخدمين", "🛡️ مدير الصلاحيات (POS Manager)", "📝 سجل نشاط المستخدمين (Audit)"])
  conn = get_db_connection()
  is_viewer = (st.session_state["role"] == "Viewer")
  
  with tab1:
      all_comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
      all_comps_dict = {c["company_name"]: c["id"] for c in all_comps}

      if not is_viewer:
          with st.expander("➕ إضافة مستخدم جديد", expanded=True):
              u = st.text_input("اسم المستخدم", key="new_u_name")
              phone = st.text_input("رقم الهاتف (إجباري ومميز لكل موظف)", key="new_u_phone")
              p = st.text_input("كلمة المرور", key="new_u_pass")
              
              if st.session_state["role"] == "Admin": 
                  roles = ["Admin (مدير النظام)", "General_Supervisor (مدير شركة)", "Branch_Supervisor (مشرف فرع)", "Cashier (كاشير)", "Viewer (مُشاهد فقط)"]
              else: 
                  roles = ["Branch_Supervisor (مشرف فرع)", "Cashier (كاشير)", "Viewer (مُشاهد فقط)"]
              
              r = st.selectbox("الرتبة:", roles, key="new_u_role")
              db_role = r.split(" ")[0]
              
              assigned_c = None
              assigned_b = []
              
              # التصحيح الدقيق: إذا لم يكن أدمن، يتم عرض الشركات والفروع بوضوح تام
              if db_role != "Admin":
                  if all_comps_dict:
                      assigned_c_name = st.selectbox("🏢 اختر الشركة التابعة لها:", list(all_comps_dict.keys()), key="new_u_comp")
                      assigned_c = all_comps_dict[assigned_c_name]
                      
                      co_branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id = ?", (assigned_c,)).fetchall()
                      co_b_dict = {b["branch_name"]: b["id"] for b in co_branches}
                      
                      if db_role == "Cashier" and co_b_dict:
                          selected_b_name = st.selectbox("📍 اختر فرع العمل للكاشير:", list(co_b_dict.keys()), key="new_u_branch_cashier")
                          assigned_b = [co_b_dict[selected_b_name]]
                      elif db_role in ["Branch_Supervisor", "General_Supervisor"] and co_b_dict:
                          multi_b = st.multiselect("📍 اختر الفروع المخصصة للإشراف عليها:", list(co_b_dict.keys()), key="new_u_branches_sup")
                          assigned_b = [co_b_dict[b] for b in multi_b]
                      elif not co_b_dict:
                          st.warning("⚠️ هذه الشركة ليس لها فروع مسجلة. أنشئ لها فرعاً أولاً من إدارة الشركات والفروع.")
                  else:
                      st.warning("⚠️ لا توجد شركات مسجلة في النظام. أضف شركات وفروع أولاً.")
              else:
                  st.info("ℹ️ حساب (Admin - مدير النظام) يمتلك صلاحية كاملة على البرنامج بالكامل ولا يتقيد بشركة أو فرع محدد.")

              if st.button("💾 حفظ وإضافة المستخدم الجديد", key="btn_save_new_user"):
                if u and p and phone:
                    try:
                        cur = conn.cursor()
                        default_branch_id = assigned_b[0] if assigned_b else None
                        cur.execute("INSERT INTO users (username, phone, password, role, company_id, branch_id) VALUES (?, ?, ?, ?, ?, ?)", (u.strip(), phone.strip(), p, db_role, assigned_c, default_branch_id))
                        new_user_id = cur.lastrowid
                        if assigned_b:
                            for b_id_val in assigned_b: 
                                cur.execute("INSERT OR IGNORE INTO user_branches (user_id, branch_id) VALUES (?, ?)", (new_user_id, b_id_val))
                        conn.commit(); log_action(st.session_state["user_id"], "إضافة مستخدم", f"تم إنشاء حساب للمستخدم {u}"); st.success("🎉 تم حفظ المستخدم وربطه بالصلاحيات بنجاح!")
                        st.rerun()
                    except Exception as e: st.error(f"🎭 **هَنّي روحك.. خطأ أثناء إضافة المستخدم!**\nالسبب: {e}")
                else:
                    st.warning("⚠️ الرجاء ملء جميع الحقول الإجبارية (الاسم، الهاتف، كلمة المرور).")

      st.markdown("---")
      st.subheader("📋 قائمة المستخدمين (مع صلاحية تعديل الرتبة مباشرة)")
      if st.session_state["role"] == "Admin": users_df = pd.read_sql("SELECT id, username AS 'اسم المستخدم', phone AS 'رقم الهاتف', password AS 'كلمة المرور', role AS 'الرتبة', is_active AS 'نشط (1=نعم/0=موقوف)' FROM users", conn)
      else:
          q = "SELECT id, username AS 'اسم المستخدم', phone AS 'رقم الهاتف', password AS 'كلمة المرور', role AS 'الرتبة', is_active AS 'نشط (1=نعم/0=موقوف)' FROM users WHERE company_id = ? OR id IN (SELECT user_id FROM user_branches ub JOIN branches b ON ub.branch_id = b.id WHERE b.company_id = ?)"
          users_df = pd.read_sql(q, conn, params=(st.session_state["company_id"], st.session_state["company_id"]))
      
      if not users_df.empty:
          st.info("💡 يمكنك تعديل الاسم، رقم الهاتف، كلمة المرور، **الرتبة**، أو حالة النشاط مباشرة من الجدول ثم اضغط حفظ التعديلات.")
          edited_users = st.data_editor(users_df, hide_index=True, disabled=is_viewer or ["id"], key="u_editor")
          if not is_viewer:
              c1, c2 = st.columns([2,1])
              with c1:
                  if st.button("💾 حفظ تعديلات المستخدمين"):
                      for idx, row in edited_users.iterrows(): 
                          conn.execute("UPDATE users SET username=?, phone=?, password=?, role=?, is_active=? WHERE id=?", 
                                       (row['اسم المستخدم'], row['رقم الهاتف'], row['كلمة المرور'], row['الرتبة'], row['نشط (1=نعم/0=موقوف)'], row['id']))
                      conn.commit(); log_action(st.session_state["user_id"], "تعديل مستخدمين", "تم تعديل بيانات ورتب المستخدمين"); st.success("🎉 تم حفظ وتحديث تعديلات المستخدمين والرتب بنجاح!")
              with c2:
                  del_u_id = st.selectbox("اختر مستخدم للحذف النهائي:", users_df["id"].tolist(), format_func=lambda x: users_df[users_df["id"]==x]["اسم المستخدم"].values[0])
                  if st.button("🗑️ حذف المستخدم نهائياً", type="primary") and del_u_id != 0:
                      conn.execute("DELETE FROM users WHERE id=?", (del_u_id,)); conn.commit(); log_action(st.session_state["user_id"], "حذف مستخدم", f"تم حذف المستخدم ID:{del_u_id}"); st.success("🗑️ تم حذف المستخدم نهائياً!")
                      st.rerun()

  with tab2:
      st.subheader("🛡️ مدير صلاحيات العرض (POS Manager)")
      if st.session_state["role"] != "Admin": st.error("صلاحية تعديل أقسام النظام مخصصة للأدمن العام فقط.")
      else:
          st.info("حدد القوائم التي يُسمح لكل رتبة بمشاهدتها:")
          sel_role = st.selectbox("اختر الرتبة لضبط صلاحياتها:", ["General_Supervisor", "Branch_Supervisor", "Cashier", "Viewer"])
          curr_perms = conn.execute("SELECT allowed_menus FROM role_permissions WHERE role = ?", (sel_role,)).fetchone()
          allowed_list = curr_perms["allowed_menus"].split(",") if curr_perms and curr_perms["allowed_menus"] else []
          with st.form("perms_form"):
              st.write(f"الصلاحيات لرتبة: **{sel_role}**")
              new_perms = []
              for m in ALL_MENUS:
                  if m == "🏠 الرئيسية واللوحة": st.checkbox(m, value=True, disabled=True); new_perms.append(m)
                  else:
                      if st.checkbox(m, value=(m in allowed_list)): new_perms.append(m)
              if st.form_submit_button("💾 اعتماد الصلاحيات"):
                  conn.execute("INSERT OR REPLACE INTO role_permissions (role, allowed_menus) VALUES (?, ?)", (sel_role, ",".join(new_perms)))
                  conn.commit(); log_action(st.session_state["user_id"], "تعديل صلاحيات", f"تم تعديل صلاحيات الرتبة {sel_role}"); st.success("🎉 تم اعتماد الصلاحيات بنجاح!")
                  
  with tab3:
      st.subheader("📝 سجل نشاط المستخدمين (Audit Trail)")
      log_query = "SELECT l.id AS 'رقم', IFNULL(u.username, 'Admin/System') AS 'المستخدم', u.role AS 'الرتبة', l.action AS 'نوع الحركة', l.details AS 'التفاصيل', l.log_time AS 'وقت وتاريخ الحركة' FROM activity_logs l LEFT JOIN users u ON l.user_id = u.id"
      if st.session_state["role"] != "Admin": log_query += f" WHERE u.company_id = {st.session_state['company_id']} OR u.id IN (SELECT user_id FROM user_branches ub JOIN branches b ON ub.branch_id = b.id WHERE b.company_id = {st.session_state['company_id']})"
      log_query += " ORDER BY l.log_time DESC LIMIT 500"
      logs_df = pd.read_sql(log_query, conn)
      if not logs_df.empty:
          st.dataframe(logs_df, use_container_width=True)
          st.download_button("📥 تصدير السجل لـ Excel", data=to_excel(logs_df), file_name="audit_logs.xlsx")
      else: st.info("لا توجد نشاطات مسجلة بعد.")
  conn.close()

elif choice == "📁 استيراد وتوزيع الأصناف":
  st.header("📁 استيراد الأصناف عبر الإكسيل")
  is_viewer = (st.session_state["role"] == "Viewer")
  if is_viewer: st.warning("👀 حسابك بصلاحية مشاهدة فقط (Viewer)، لا يمكنك استيراد أو تعديل البيانات.")
  
  def safe_float(val):
      try:
          if pd.isna(val) or str(val).strip() == '': return 0.0
          s = str(val).replace(',', '.')
          s = re.sub(r'[^\d.]', '', s)
          if s.count('.') > 1: s = s.split('.')[0] + '.' + ''.join(s.split('.')[1:])
          return float(s) if s else 0.0
      except: return 0.0

  conn = get_db_connection()
  
  if st.session_state["role"] == "Admin":
      all_companies = conn.execute("SELECT id, company_name FROM companies").fetchall()
  else:
      all_companies = conn.execute("SELECT id, company_name FROM companies WHERE id = ?", (st.session_state["company_id"],)).fetchall()
  
  comps_dict = {f"🏢 {c['company_name']} (المخزن الرئيسي للشركة)": c["id"] for c in all_companies}
  
  if comps_dict and not is_viewer:
    sel_comp_label = st.selectbox("اختر المخزن الرئيسي للشركة المستهدفة لاستيراد الأصناف:", list(comps_dict.keys()))
    sel_comp_id = comps_dict[sel_comp_label]
    
    import_mode = st.radio("طريقة الاستيراد:", ["🔄 تحديث وإضافة", "🚨 مسح كامل واستيراد جديد"])
    up_file = st.file_uploader("اختر ملف الإكسيل (.xlsx)", type=["xlsx", "xls"])
    if up_file and st.button("📥 تنفيذ استيراد الأصناف"):
      df = pd.read_excel(up_file, header=None)
      cur = conn.cursor()
      added_count = 0; updated_count = 0
      if "مسح كامل" in import_mode: cur.execute("DELETE FROM items WHERE company_id = ? AND branch_id IS NULL", (sel_comp_id,)); conn.commit()
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
                if code != "": existing = cur.execute("SELECT id FROM items WHERE company_id = ? AND branch_id IS NULL AND (item_code = ? OR item_name = ?) LIMIT 1", (sel_comp_id, code, name)).fetchone()
                else: existing = cur.execute("SELECT id FROM items WHERE company_id = ? AND branch_id IS NULL AND item_name = ? LIMIT 1", (sel_comp_id, name)).fetchone()
                if existing:
                    cur.execute("UPDATE items SET quantity = quantity + ?, buy_price = ?, sale_price = ? WHERE id = ?", (qty, b_price, s_price, existing["id"]))
                    updated_count += 1
                else:
                    cur.execute("INSERT INTO items (company_id, branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, NULL, ?, ?, ?, ?, ?)", (sel_comp_id, code, name, qty, b_price, s_price))
                    added_count += 1
            else:
                cur.execute("INSERT INTO items (company_id, branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, NULL, ?, ?, ?, ?, ?)", (sel_comp_id, code, name, qty, b_price, s_price))
                added_count += 1
        except Exception: continue
      conn.commit(); log_action(st.session_state["user_id"], "استيراد أصناف", f"استيراد للمخزن الرئيسي"); st.success(f"📥 تم الاستيراد بنجاح!\n* عدد الأصناف المضافة حديثاً: **{added_count}**\n* عدد الأصناف المحدثة: **{updated_count}**")
  conn.close()

elif choice == "🏦 إدارة الخزينة والبنوك":
  st.header("🏦 إدارة الخزائن والبنوك")
  tab1, tab2, tab3 = st.tabs(["🏛️ تعريف الخزائن", "💸 إيداع وسحب", "📊 أرصدة والحركات الخزائن"])
  conn = get_db_connection()
  is_viewer = (st.session_state["role"] == "Viewer")
  
  with tab1:
      comps = get_allowed_companies(conn)
      if comps and not is_viewer:
          c_dict = {c["company_name"]: c["id"] for c in comps}
          with st.form("treasury_form", clear_on_submit=True):
              t_name = st.text_input("اسم الخزينة/البنك")
              t_type = st.selectbox("نوع الخزينة", ["كاش", "بنك", "عهدة فرع"])
              sel_c = st.selectbox("اختر الشركة", list(c_dict.keys()))
              branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id=?", (c_dict[sel_c],)).fetchall()
              b_dict = {"خزينة عامة للشركة": None}
              b_dict.update({b["branch_name"]: b["id"] for b in branches})
              t_branch = st.selectbox("الفرع", list(b_dict.keys()))
              t_bal = st.number_input("الرصيد الافتتاحي", value=0.0)
              if st.form_submit_button("حفظ الخزينة") and t_name:
                  conn.execute("INSERT INTO treasuries (company_id, branch_id, treasury_name, treasury_type, balance) VALUES (?, ?, ?, ?, ?)", (c_dict[sel_c], b_dict[t_branch], t_name.strip(), t_type, t_bal))
                  conn.commit(); log_action(st.session_state["user_id"], "إنشاء خزينة", f"خزينة {t_name}"); st.success("💰 تم حفظ الخزينة بنجاح!")
                  st.rerun()

  with tab2:
      if not is_viewer:
          if st.session_state["role"] == "Admin":
              treasuries = conn.execute("SELECT id, treasury_name, balance FROM treasuries").fetchall()
          else:
              treasuries = conn.execute("SELECT id, treasury_name, balance FROM treasuries WHERE company_id = ?", (st.session_state["company_id"],)).fetchall()
              
          if treasuries:
              t_options = {f"{t['treasury_name']} (الرصيد: {t['balance']:,.2f})": t['id'] for t in treasuries}
              sel_t = st.selectbox("اختر الخزينة", list(t_options.keys()))
              with st.form("trans_form", clear_on_submit=True):
                  trans_type = st.radio("نوع الحركة:", ["إيداع", "سحب"])
                  amount = st.number_input("المبلغ", min_value=0.1, value=100.0)
                  desc = st.text_input("البيان / السبب")
                  if st.form_submit_button("تأكيد العملية") and desc:
                      t_id = t_options[sel_t]
                      if trans_type == "إيداع": conn.execute("UPDATE treasuries SET balance = balance + ? WHERE id = ?", (amount, t_id))
                      else: conn.execute("UPDATE treasuries SET balance = balance - ? WHERE id = ?", (amount, t_id))
                      conn.execute("INSERT INTO treasury_transactions (treasury_id, user_id, trans_type, amount, description) VALUES (?, ?, ?, ?, ?)", (t_id, st.session_state["user_id"], trans_type, amount, desc))
                      conn.commit(); log_action(st.session_state["user_id"], f"{trans_type} خزينة", f"{amount} - {desc}"); st.success("✅ تم تنفيذ العملية المالية بنجاح وتحديث أرصدة الخزينة!")
                      st.rerun()

  with tab3:
      if st.session_state["role"] == "Admin":
          df_t = pd.read_sql("SELECT treasuries.id AS 'id', companies.company_name AS 'الشركة', treasuries.treasury_name AS 'الاسم', treasuries.treasury_type AS 'النوع', IFNULL(branches.branch_name, 'خزينة عامة') AS 'الفرع', treasuries.balance AS 'الرصيد' FROM treasuries LEFT JOIN companies ON treasuries.company_id = companies.id LEFT JOIN branches ON treasuries.branch_id = branches.id", conn)
      else:
          df_t = pd.read_sql("SELECT treasuries.id AS 'id', companies.company_name AS 'الشركة', treasuries.treasury_name AS 'الاسم', treasuries.treasury_type AS 'النوع', IFNULL(branches.branch_name, 'خزينة عامة') AS 'الفرع', treasuries.balance AS 'الرصيد' FROM treasuries LEFT JOIN companies ON treasuries.company_id = companies.id LEFT JOIN branches ON treasuries.branch_id = branches.id WHERE treasuries.company_id = ?", conn, params=(st.session_state["company_id"],))
          
      if not df_t.empty:
          edited_t = st.data_editor(df_t, disabled=is_viewer, hide_index=True, key="t_editor")
          if not is_viewer and st.button("💾 حفظ تعديلات الخزائن"):
              for idx, row in edited_t.iterrows(): conn.execute("UPDATE treasuries SET treasury_name=?, treasury_type=?, balance=? WHERE id=?", (row['الاسم'], row['النوع'], row['الرصيد'], row['id']))
              conn.commit(); log_action(st.session_state["user_id"], "تعديل خزائن", "تعديل أرصدة الخزائن يدوياً"); st.success("💾 تم حفظ تعديلات الخزائن بنجاح!")
              st.rerun()
          st.markdown("---")
          if st.session_state["role"] == "Admin":
              df_trans = pd.read_sql("SELECT treasury_transactions.id AS 'رقم', treasuries.treasury_name AS 'الخزينة', treasury_transactions.trans_type AS 'النوع', treasury_transactions.amount AS 'المبلغ', treasury_transactions.description AS 'البيان', users.username AS 'المستخدم', treasury_transactions.trans_date AS 'التاريخ' FROM treasury_transactions JOIN treasuries ON treasury_transactions.treasury_id = treasuries.id LEFT JOIN users ON treasury_transactions.user_id = users.id ORDER BY treasury_transactions.trans_date DESC", conn)
          else:
              df_trans = pd.read_sql("SELECT treasury_transactions.id AS 'رقم', treasuries.treasury_name AS 'الخزينة', treasury_transactions.trans_type AS 'النوع', treasury_transactions.amount AS 'المبلغ', treasury_transactions.description AS 'البيان', users.username AS 'المستخدم', treasury_transactions.trans_date AS 'التاريخ' FROM treasury_transactions JOIN treasuries ON treasury_transactions.treasury_id = treasuries.id LEFT JOIN users ON treasury_transactions.user_id = users.id WHERE treasuries.company_id = ? ORDER BY treasury_transactions.trans_date DESC", conn, params=(st.session_state["company_id"],))
          st.dataframe(df_trans, use_container_width=True)
  conn.close()

elif choice == "💰 تسجيل المصروفات":
  st.header("💰 تسجيل وإدارة المصروفات")
  is_viewer = (st.session_state["role"] == "Viewer")
  if is_viewer: st.warning("👀 حسابك بصلاحية مشاهدة فقط (Viewer).")
  
  conn = get_db_connection()
  comps = get_allowed_companies(conn)
  comps_dict = {c["company_name"]: c["id"] for c in comps}
  
  if comps_dict and not is_viewer:
      col1, col2 = st.columns(2)
      with col1: sel_comp = st.selectbox("الشركة", list(comps_dict.keys()))
      with col2:
          branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id = ?", (comps_dict[sel_comp],)).fetchall()
          b_dict = {b["branch_name"]: b["id"] for b in branches}
          sel_branch = st.selectbox("الفرع", list(b_dict.keys())) if b_dict else None
      
      treasuries = conn.execute("SELECT id, treasury_name, balance FROM treasuries WHERE company_id = ?", (comps_dict[sel_comp],)).fetchall()
      t_dict = {f"{t['treasury_name']} (رصيد: {t['balance']:,.2f})": t["id"] for t in treasuries}
      
      with st.form("expense_form", clear_on_submit=True):
          amount = st.number_input("مبلغ المصروف", min_value=0.1, value=10.0)
          exp_list = [r["name"] for r in conn.execute("SELECT name FROM dict_expenses").fetchall()]
          exp_list.append("➕ إضافة تصنيف جديد...")
          sel_desc = st.selectbox("تصنيف المصروف", exp_list)
          new_desc = st.text_input("اكتب البيان الجديد:") if sel_desc == "➕ إضافة تصنيف جديد..." else ""
          sel_t = st.selectbox("خصم من الخزينة:", list(t_dict.keys())) if t_dict else None
              
          if st.form_submit_button("💾 حفظ المصروف"):
              final_desc = new_desc.strip() if sel_desc == "➕ إضافة تصنيف جديد..." else sel_desc
              if final_desc and sel_branch and sel_t:
                  if sel_desc == "➕ إضافة تصنيف جديد...": conn.execute("INSERT OR IGNORE INTO dict_expenses (name) VALUES (?)", (final_desc,))
                  t_id = t_dict[sel_t]
                  conn.execute("INSERT INTO expenses (company_id, branch_id, user_id, treasury_id, amount, description) VALUES (?, ?, ?, ?, ?, ?)", (comps_dict[sel_comp], b_dict[sel_branch], st.session_state["user_id"], t_id, amount, final_desc))
                  conn.execute("UPDATE treasuries SET balance = balance - ? WHERE id = ?", (amount, t_id))
                  conn.execute("INSERT INTO treasury_transactions (treasury_id, user_id, trans_type, amount, description) VALUES (?, ?, 'سحب', ?, ?)", (t_id, st.session_state["user_id"], amount, f"مصروفات: {final_desc}"))
                  conn.commit(); log_action(st.session_state["user_id"], "تسجيل مصروف", f"{amount} - {final_desc}"); st.success("💸 تم حفظ المصروف وخصم المبلغ من الخزينة بنجاح!")
                  st.rerun()
  conn.close()

elif choice == "📊 التقارير الشاملة والمخازن":
  st.header("📊 التقارير الشاملة والمخازن")
  tab1, tab5, tab2, tab3, tab4 = st.tabs(["📋 المخزون", "🔄 نقل وتوزيع", "📈 المبيعات", "💸 المصروفات", "⚙️ تصفير البيانات"])
  conn = get_db_connection()
  is_viewer = (st.session_state["role"] == "Viewer")
  
  if st.session_state["role"] == "Admin":
      items_df = pd.read_sql("SELECT items.id AS id, companies.company_name AS الشركة, branches.branch_name AS الفرع, items.item_code AS الكود, items.item_name AS الصنف, items.quantity AS الكمية, items.buy_price AS 'سعر الشراء', items.sale_price AS 'سعر البيع' FROM items JOIN companies ON items.company_id = companies.id LEFT JOIN branches ON items.branch_id = branches.id", conn)
  else:
      items_df = pd.read_sql("SELECT items.id AS id, companies.company_name AS الشركة, branches.branch_name AS الفرع, items.item_code AS الكود, items.item_name AS الصنف, items.quantity AS الكمية, items.buy_price AS 'سعر الشراء', items.sale_price AS 'سعر البيع' FROM items JOIN companies ON items.company_id = companies.id LEFT JOIN branches ON items.branch_id = branches.id WHERE companies.id = ?", conn, params=(st.session_state["company_id"],))
      
  items_df['الفرع'] = items_df['الفرع'].fillna('المخزن الرئيسي للشركة (غير موزع)')
  
  with tab1:
      st.markdown("### 🔍 تصفية وعرض مخزون الشركات والفروع")
      col_f1, col_f2 = st.columns(2)
      
      all_comps = conn.execute("SELECT id, company_name FROM companies").fetchall() if st.session_state["role"] == "Admin" else conn.execute("SELECT id, company_name FROM companies WHERE id=?", (st.session_state["company_id"],)).fetchall()
      f_comps_dict = {"عرض كل الشركات": None}
      f_comps_dict.update({c["company_name"]: c["id"] for c in all_comps})
      
      with col_f1:
          f_sel_comp = st.selectbox("تصفية بالشركة:", list(f_comps_dict.keys()))
      
      with col_f2:
          f_comp_id = f_comps_dict[f_sel_comp]
          if f_comp_id:
              f_branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id=?", (f_comp_id,)).fetchall()
              f_branches_dict = {"عرض كل فروع الشركة (بما فيها المخزن الرئيسي)": "ALL", "المخزن الرئيسي للشركة (غير موزع)": "MAIN"}
              f_branches_dict.update({b["branch_name"]: b["id"] for b in f_branches})
              f_sel_branch = st.selectbox("تصفية بالفرع:", list(f_branches_dict.keys()))
          else:
              f_sel_branch = None

      filtered_df = items_df.copy()
      if f_comp_id:
          filtered_df = filtered_df[filtered_df['الشركة'] == f_sel_comp]
          if f_sel_branch and f_branches_dict[f_sel_branch] == "MAIN":
              filtered_df = filtered_df[filtered_df['الفرع'] == 'المخزن الرئيسي للشركة (غير موزع)']
          elif f_sel_branch and f_branches_dict[f_sel_branch] != "ALL":
              filtered_df = filtered_df[filtered_df['الفرع'] == f_sel_branch]
              
      if not filtered_df.empty:
          edited_items = st.data_editor(filtered_df, disabled=is_viewer, hide_index=True, key="items_editor")
          if not is_viewer and st.button("💾 حفظ تعديلات المخزون المعروض"):
              for idx, row in edited_items.iterrows(): conn.execute("UPDATE items SET item_code=?, item_name=?, quantity=?, buy_price=?, sale_price=? WHERE id=?", (row['الكود'], row['الصنف'], row['الكمية'], row['سعر الشراء'], row['سعر البيع'], row['id']))
              conn.commit(); log_action(st.session_state["user_id"], "تعديل مخزون", "تعديل بيانات الأصناف"); st.success("💾 تم حفظ تعديلات المخزون بنجاح!")
              st.rerun()
          st.download_button("📥 تصدير المخزون المعروض لـ Excel", data=to_excel(filtered_df), file_name="inventory_filtered.xlsx")
      else:
          st.warning("🎭 **هَنّي روحك.. لا توجد أصناف تطابق خيارات التصفية الحالية!** (مخزن فارغ)")

  with tab5:
      st.subheader("🔄 نقل وتحويل المخزون (بين أي شركة أو فرع بمرونة تامة)")
      if not is_viewer:
          transfer_type = st.radio("نوع العملية:", ["نقل صنف محدد (فردي)", "نقل كافة الأصناف دفعة واحدة", "🗑️ حذف أصناف من المخزن"])
          
          all_companies_list = conn.execute("SELECT id, company_name FROM companies").fetchall()
          if st.session_state["role"] != "Admin":
              all_companies_list = conn.execute("SELECT id, company_name FROM companies WHERE id=?", (st.session_state["company_id"],)).fetchall()
              
          all_c_dict = {c['company_name']: c["id"] for c in all_companies_list}
          
          if not all_companies_list:
              st.warning("⚠️ لا توجد شركات مسجلة في النظام بعد.")
          else:
              if transfer_type == "نقل صنف محدد (فردي)":
                  col_s1, col_s2 = st.columns(2)
                  with col_s1: src_comp_name = st.selectbox("من شركة المصدر:", list(all_c_dict.keys()), key="src_c")
                  src_comp_id = all_c_dict[src_comp_name]
                  with col_s2:
                      src_branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id=?", (src_comp_id,)).fetchall()
                      src_b_dict = {"المخزن الرئيسي للشركة": None}
                      src_b_dict.update({b["branch_name"]: b["id"] for b in src_branches})
                      src_branch_name = st.selectbox("من فرع المصدر:", list(src_b_dict.keys()), key="src_b")
                      src_branch_id = src_b_dict[src_branch_name]
                      
                  src_items_db = conn.execute("SELECT * FROM items WHERE company_id=? AND branch_id IS NULL", (src_comp_id,)).fetchall() if src_branch_id is None else conn.execute("SELECT * FROM items WHERE company_id=? AND branch_id=?", (src_comp_id, src_branch_id)).fetchall()
                  
                  if not src_items_db:
                      st.warning("🎭 **هَنّي روحك.. لا توجد أصناف متاحة في هذا المصدر لنقلها!** (المصدر خاوي)")
                  else:
                      src_items_opts = {f"[{i['item_code']}] {i['item_name']} | متاح: {i['quantity']}": i for i in src_items_db}
                      sel_item_label = st.selectbox("📌 اختر الصنف:", list(src_items_opts.keys()))
                      curr_item = src_items_opts[sel_item_label]
                      
                      col_d1, col_d2 = st.columns(2)
                      admin_comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
                      admin_c_dict = {c['company_name']: c["id"] for c in admin_comps}
                      with col_d1: dst_comp_name = st.selectbox("إلى شركة الوجهة:", list(admin_c_dict.keys()), key="dst_c")
                      dst_comp_id = admin_c_dict[dst_comp_name]
                      with col_d2:
                          dst_branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id=?", (dst_comp_id,)).fetchall()
                          dst_b_dict = {"المخزن الرئيسي للشركة": None}
                          dst_b_dict.update({b["branch_name"]: b["id"] for b in dst_branches})
                          dst_branch_name = st.selectbox("إلى فرع الوجهة:", list(dst_b_dict.keys()), key="dst_b")
                          dst_branch_id = dst_b_dict[dst_branch_name]
                          
                      transfer_qty = st.number_input("الكمية المراد نقلها", min_value=0.1, value=1.0)
                      if st.button("🚀 تنفيذ النقل الفردي"):
                          if transfer_qty > curr_item["quantity"]:
                              st.warning("🎭 **هَنّي روحك.. الكمية المراد نقلها أكبر من المتاح في المخزن!** (خطأ كمية غير كافية)")
                          else:
                              conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (transfer_qty, curr_item["id"]))
                              existing = conn.execute("SELECT id FROM items WHERE company_id=? AND ((branch_id IS ? AND ? IS NULL) OR branch_id = ?) AND item_code=? AND item_name=?", (dst_comp_id, dst_branch_id, dst_branch_id, dst_branch_id, curr_item["item_code"], curr_item["item_name"])).fetchone()
                              if existing: conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (transfer_qty, existing["id"]))
                              else: conn.execute("INSERT INTO items (company_id, branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?, ?)", (dst_comp_id, dst_branch_id, curr_item["item_code"], curr_item["item_name"], transfer_qty, curr_item["buy_price"], curr_item["sale_price"]))
                              conn.commit(); log_action(st.session_state["user_id"], "نقل مخزون", f"نقل {transfer_qty}")
                              st.success("🚀 تم نقل الأصناف وتحديث المخازن بنجاح وثبات!")

              elif transfer_type == "نقل كافة الأصناف دفعة واحدة":
                  col_s1, col_s2 = st.columns(2)
                  with col_s1: src_comp_name = st.selectbox("📦 من شركة المصدر:", list(all_c_dict.keys()), key="src_c_bulk")
                  src_comp_id = all_c_dict[src_comp_name]
                  with col_s2:
                      src_branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id=?", (src_comp_id,)).fetchall()
                      src_b_dict = {"المخزن الرئيسي للشركة": None}
                      src_b_dict.update({b["branch_name"]: b["id"] for b in src_branches})
                      src_branch_name = st.selectbox("من فرع المصدر:", list(src_b_dict.keys()), key="src_b_bulk")
                      src_branch_id = src_b_dict[src_branch_name]
                      
                  admin_comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
                  admin_c_dict = {c['company_name']: c["id"] for c in admin_comps}
                  
                  col_d1, col_d2 = st.columns(2)
                  with col_d1: dst_comp_name = st.selectbox("🎯 إلى شركة الوجهة:", list(admin_c_dict.keys()), key="dst_c_bulk")
                  dst_comp_id = admin_c_dict[dst_comp_name]
                  with col_d2:
                      dst_branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id=?", (dst_comp_id,)).fetchall()
                      dst_b_dict = {"المخزن الرئيسي للشركة": None}
                      dst_b_dict.update({b["branch_name"]: b["id"] for b in dst_branches})
                      dst_branch_name = st.selectbox("إلى فرع الوجهة:", list(dst_b_dict.keys()), key="dst_b_bulk")
                      dst_branch_id = dst_b_dict[dst_branch_name]

                  if st.button("🚀 تنفيذ نقل كافة الأصناف دفعة واحدة", use_container_width=True, type="primary"):
                      source_items = conn.execute("SELECT * FROM items WHERE company_id=? AND branch_id IS NULL AND quantity > 0", (src_comp_id,)).fetchall() if src_branch_id is None else conn.execute("SELECT * FROM items WHERE company_id=? AND branch_id=? AND quantity > 0", (src_comp_id, src_branch_id)).fetchall()
                      if not source_items: st.warning("🎭 **هَنّي روحك.. لا توجد أصناف بكميات متاحة في هذا المصدر لنقلها!** (مخزن فارغ)")
                      else:
                          transferred_count = 0
                          for s_item in source_items:
                              existing = conn.execute("SELECT id FROM items WHERE company_id=? AND ((branch_id IS ? AND ? IS NULL) OR branch_id = ?) AND item_code=? AND item_name=?", (dst_comp_id, dst_branch_id, dst_branch_id, dst_branch_id, s_item["item_code"], s_item["item_name"])).fetchone()
                              if existing: conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (s_item["quantity"], existing["id"]))
                              else: conn.execute("INSERT INTO items (company_id, branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?, ?)", (dst_comp_id, dst_branch_id, s_item["item_code"], s_item["item_name"], s_item["quantity"], s_item["buy_price"], s_item["sale_price"]))
                              conn.execute("UPDATE items SET quantity = 0 WHERE id = ?", (s_item["id"],))
                              transferred_count += 1
                          conn.commit(); log_action(st.session_state["user_id"], "نقل مخزون شامل", f"تم نقل {transferred_count} صنف")
                          st.success(f"🚀 تم نقل وتوزيع ({transferred_count}) صنف دفعة واحدة بنجاح وثبات!")

              elif transfer_type == "🗑️ حذف أصناف من المخزن":
                  st.markdown("---")
                  st.info("🏢 **اختر الشركة المطلوبة لتحديد وحذف الأصناف التابعة لها حصرياً:**")
                  del_comp_name = st.selectbox("الشركة المراد محو أصنافها:", list(all_c_dict.keys()), key="del_c_sel")
                  del_comp_id = all_c_dict[del_comp_name]
                  
                  del_mode = st.radio("نوع الحذف:", ["حذف صنف محدد من هذه الشركة", "حذف كافة أصناف هذه الشركة بالكامل"])
                  
                  company_items_df = items_df[items_df['الشركة'] == del_comp_name]
                  
                  if del_mode == "حذف صنف محدد من هذه الشركة" and not company_items_df.empty:
                      del_item_sel = st.selectbox("اختر الصنف للحذف النهائي:", company_items_df["id"].tolist(), format_func=lambda x: f"[{company_items_df[company_items_df['id']==x]['الكود'].values[0]}] {company_items_df[company_items_df['id']==x]['الصنف'].values[0]} | الفرع: {company_items_df[company_items_df['id']==x]['الفرع'].values[0]}")
                      if st.button("🗑️ حذف هذا الصنف نهائياً", type="primary"):
                          conn.execute("DELETE FROM items WHERE id = ?", (del_item_sel,))
                          conn.commit(); st.success(f"🗑️ تم حذف الصنف نهائياً من شركة ({del_comp_name}) بنجاح!")
                  elif del_mode == "حذف كافة أصناف هذه الشركة بالكامل":
                      if st.checkbox(f"أؤكد رغبتي في مسح جميع أصناف شركة ({del_comp_name})") and st.button("🚨 تنفيذ مسح كافة أصناف هذه الشركة", type="primary"):
                          conn.execute("DELETE FROM items WHERE company_id = ?", (del_comp_id,))
                          conn.commit(); st.success(f"🗑️ تم مسح وتصفير كافة أصناف شركة ({del_comp_name}) بنجاح وثبات!")
                  else:
                      st.info("لا توجد أصناف مسجلة لهذه الشركة حالياً.")

  with tab2:
      if st.session_state["role"] == "Admin":
          invoices_df = pd.read_sql("SELECT invoices.id AS 'id', companies.company_name AS 'الشركة', branches.branch_name AS 'الفرع', users.username AS 'الكاشير', invoices.total_amount AS 'المبلغ', invoices.payment_method AS 'طريقة الدفع', invoices.shift_status AS 'الحالة', invoices.created_at AS 'التاريخ' FROM invoices LEFT JOIN branches ON invoices.branch_id = branches.id LEFT JOIN companies ON branches.company_id = companies.id LEFT JOIN users ON invoices.user_id = users.id", conn)
      else:
          invoices_df = pd.read_sql("SELECT invoices.id AS 'id', companies.company_name AS 'الشركة', branches.branch_name AS 'الفرع', users.username AS 'الكاشير', invoices.total_amount AS 'المبلغ', invoices.payment_method AS 'طريقة الدفع', invoices.shift_status AS 'الحالة', invoices.created_at AS 'التاريخ' FROM invoices LEFT JOIN branches ON invoices.branch_id = branches.id LEFT JOIN companies ON branches.company_id = companies.id LEFT JOIN users ON invoices.user_id = users.id WHERE companies.id = ?", conn, params=(st.session_state["company_id"],))
          
      if not invoices_df.empty: st.dataframe(invoices_df, use_container_width=True)
      else: st.info("لا توجد فواتير مبيعات مسجلة حتى الآن.")
      st.download_button("📥 تصدير المبيعات لـ Excel", data=to_excel(invoices_df), file_name="sales.xlsx")

  with tab3:
      if st.session_state["role"] == "Admin":
          expenses_df = pd.read_sql("SELECT expenses.id AS 'id', companies.company_name AS 'الشركة', branches.branch_name AS 'الفرع', treasuries.treasury_name AS 'خُصمت من', users.username AS 'المستخدم', expenses.amount AS 'المبلغ', expenses.description AS 'البيان', expenses.expense_date AS 'التاريخ' FROM expenses LEFT JOIN branches ON expenses.branch_id = branches.id LEFT JOIN companies ON expenses.company_id = companies.id LEFT JOIN users ON expenses.user_id = users.id LEFT JOIN treasuries ON expenses.treasury_id = treasuries.id", conn)
      else:
          expenses_df = pd.read_sql("SELECT expenses.id AS 'id', companies.company_name AS 'الشركة', branches.branch_name AS 'الفرع', treasuries.treasury_name AS 'خُصمت من', users.username AS 'المستخدم', expenses.amount AS 'المبلغ', expenses.description AS 'البيان', expenses.expense_date AS 'التاريخ' FROM expenses LEFT JOIN branches ON expenses.branch_id = branches.id LEFT JOIN companies ON expenses.company_id = companies.id LEFT JOIN users ON expenses.user_id = users.id LEFT JOIN treasuries ON expenses.treasury_id = treasuries.id WHERE companies.id = ?", conn, params=(st.session_state["company_id"],))
          
      if not expenses_df.empty: st.dataframe(expenses_df, use_container_width=True)
      else: st.info("لا توجد مصروفات مسجلة حتى الآن.")
      st.download_button("📥 تصدير المصروفات لـ Excel", data=to_excel(expenses_df), file_name="expenses.xlsx")

  with tab4:
      st.subheader("⚙️ خيارات تصفير البيانات المالية والتشغيلية")
      all_companies_list = conn.execute("SELECT id, company_name FROM companies").fetchall()
      reset_c_dict = {c['company_name']: c["id"] for c in all_companies_list}
      
      if reset_c_dict:
          with st.form("reset_form"):
              st.info("⚠️ يمكنك تصفير فواتير ومبيعات وشفتات شركة محددة أو فرع معين بدقة تامة:")
              reset_comp_name = st.selectbox("اختر الشركة للتصفير:", list(reset_c_dict.keys()))
              reset_comp_id = reset_c_dict[reset_comp_name]
              
              reset_branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id=?", (reset_comp_id,)).fetchall()
              reset_b_dict = {"تصفير كافة فروع الشركة دفعة واحدة": "ALL"}
              reset_b_dict.update({b["branch_name"]: b["id"] for b in reset_branches})
              reset_branch_sel = st.selectbox("اختر الفرع للتصفير:", list(reset_b_dict.keys()))
              reset_branch_id = reset_b_dict[reset_branch_sel]
              
              confirm_check = st.checkbox("أؤكد رغبتي في مسح وتصفير فواتير وشفتات هذه الجهة نهائياً وإعادة تعيين العدادات")
              
              if st.form_submit_button("🚨 تنفيذ التصفير الشامل للجهة المحددة", type="primary"):
                  if confirm_check:
                      if reset_branch_id == "ALL":
                          branch_ids_list = [b["id"] for b in reset_branches]
                          if branch_ids_list:
                              placeholders_b = ','.join('?' for _ in branch_ids_list)
                              conn.execute(f"DELETE FROM invoices WHERE branch_id IN ({placeholders_b})", branch_ids_list)
                          conn.commit()
                      else:
                          conn.execute("DELETE FROM invoices WHERE branch_id = ?", (reset_branch_id,))
                          conn.commit()
                      st.success(f"⚙️ تم تصفير بيانات وفواتير الجهة ({reset_comp_name} - {reset_branch_sel}) بنجاح وإعادة تعيين الشفتات!")
                  else:
                      st.warning("🎭 **هَنّي روحك.. يرجى تحديد مربّع التأكيد لتنفيذ عملية التصفير!**")
      else:
          st.warning("لا توجد شركات مسجلة في النظام للتصفير.")
  conn.close()

elif choice == "🥜 التحميص والخلط والتصنيع":
  st.header("🥜 التحميص والخلط")
  tab1, tab2 = st.tabs(["🔥 قسم التحميص", "🥜 المكسرات المشكلة"])
  with tab1:
    conn = get_db_connection()
    if st.session_state["role"] == "Admin": branches = conn.execute("SELECT branches.id, branches.branch_name, companies.company_name FROM branches JOIN companies ON branches.company_id = companies.id").fetchall()
    else: branches = conn.execute("SELECT branches.id, branches.branch_name, companies.company_name FROM branches JOIN companies ON branches.company_id = companies.id WHERE companies.id=?", (st.session_state["company_id"],)).fetchall()
    branch_dict = {f"{b['company_name']} ➔ {b['branch_name']}": b["id"] for b in branches}
    if branch_dict:
      with st.form("roast_form", clear_on_submit=True):
          sel_b_roast = st.selectbox("اختر الفرع", list(branch_dict.keys()))
          b_id = branch_dict[sel_b_roast]
          items = conn.execute("SELECT item_name, sale_price FROM items WHERE branch_id = ?", (b_id,)).fetchall()
          items_dict = {f"{i['item_name']} ({i['sale_price']} د.ل)": i for i in items} if items else {}
          sel_item = st.selectbox("الصنف الخام", list(items_dict.keys())) if items_dict else None
          in_qty = st.number_input("الوزن الخام (كيلو)", min_value=0.1, value=10.0)
          out_qty = st.number_input("الوزن الناتج (كيلو)", min_value=0.1, value=8.5)
          
          existing_items = list(set([i['item_name'] for i in items])) if items else []
          existing_items.append("➕ إضافة صنف جديد تماماً للقائمة...")
          sel_new_roast = st.selectbox("الصنف المحمص الناتج:", existing_items)
          new_roast = ""
          if sel_new_roast == "➕ إضافة صنف جديد تماماً للقائمة...": new_roast = st.text_input("اسم الصنف المحمص:")
              
          if st.form_submit_button("⚙️ تنفيذ التحميص (Enter)"):
            final_roast_name = new_roast.strip() if sel_new_roast == "➕ إضافة صنف جديد تماماً للقائمة..." else sel_new_roast
            if final_roast_name and sel_item:
              old_price = items_dict[sel_item]["sale_price"]
              new_unit_price = (in_qty * old_price) / out_qty
              conn.execute("INSERT INTO items (company_id, branch_id, item_name, sale_price, quantity) VALUES ((SELECT company_id FROM branches WHERE id=?), ?, ?, ?, ?)", (b_id, b_id, final_roast_name, round(new_unit_price, 2), out_qty))
              conn.commit(); log_action(st.session_state["user_id"], "تحميص", f"تم تحميص {final_roast_name}"); st.success(f"🥜 تم تنفيذ عملية التحميص بنجاح! السعر الناتج: {new_unit_price:.2f} د.ل")
    conn.close()
  with tab2:
    with st.form("mix_form", clear_on_submit=True):
        conn = get_db_connection()
        mix_list = [r["name"] for r in conn.execute("SELECT name FROM dict_mixes").fetchall()]
        mix_list.append("➕ إضافة صنف مكسرات مشكلة جديد...")
        sel_mix = st.selectbox("اسم الصنف المُشكل", mix_list)
        new_mix = ""
        if sel_mix == "➕ إضافة صنف مكسرات مشكلة جديد...": new_mix = st.text_input("اكتب الاسم الجديد:")
        total_cost = st.number_input("إجمالي التكلفة (د.ل)", min_value=0.1, value=50.0)
        profit_margin = st.number_input("نسبة الربح (%)", min_value=0.0, value=20.0)
        
        if st.form_submit_button("✨ اعتماد وإنتاج (Enter)"):
          final_mix_name = new_mix.strip() if sel_mix == "➕ إضافة صنف مكسرات مشكلة جديد..." else sel_mix
          if final_mix_name:
            if sel_mix == "➕ إضافة صنف مكسرات مشكلة جديد...": conn.execute("INSERT OR IGNORE INTO dict_mixes (name) VALUES (?)", (final_mix_name,))
            final_price = total_cost * (1 + (profit_margin / 100))
            b_id = list(branch_dict.values())[0] if branch_dict else None
            conn.execute("INSERT INTO items (company_id, branch_id, item_name, sale_price) VALUES ((SELECT company_id FROM branches WHERE id=?), ?, ?, ?)", (b_id, b_id, final_mix_name, round(final_price, 2)))
            conn.commit(); log_action(st.session_state["user_id"], "خلط وتصنيع", f"تم اعتماد {final_mix_name}"); st.success(f"✨ تم اعتماد وإنتاج صنف المكسرات بنجاح بسعر: {final_price:.2f} د.ل")
    conn.close()

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير (POS)")
  tab1, tab2, tab3 = st.tabs(["🛒 شاشة البيع", "📦 المرتجعات", "📊 الوردية (X/Z-READ)"])
  b_id = st.session_state.get("selected_branch_id")
  conn = get_db_connection()
  
  branch_items = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
      
  with tab1:
    st.text_input("🔍 مسح الباركود (Scanner):", key="barcode_scan", on_change=process_barcode)
    with st.form("pos_form", clear_on_submit=True):
        col_search, col_qty, col_btn = st.columns([3, 1, 1])
        with col_search:
            items_options = {f"[{i['item_code']}] {i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items} if branch_items else {}
            chosen_item = st.selectbox("ابحث عن الصنف يدوياً:", [""] + list(items_options.keys()))
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
        st.data_editor(df_cart[["code", "name", "price", "qty", "total"]], disabled=True, use_container_width=True)
        grand_total = sum([x["total"] for x in st.session_state["cart"]])
        st.metric("الإجمالي النهائي", f"{grand_total:.2f} د.ل")
        
        with st.form("checkout_form"):
            pay_method = st.selectbox("طريقة الدفع:", ["كاش (نقدي)", "بطاقة (شبكة)", "تحويل بنكي"])
            cash_paid = st.number_input("المبلغ المستلم من العميل (د.ل):", min_value=0.0, value=grand_total)
            
            change_due = cash_paid - grand_total if pay_method == "كاش (نقدي)" else 0.0
            if pay_method == "كاش (نقدي)":
                st.info(f"💵 المتبقي (الباقي للعميل): **{change_due:,.2f} د.ل**")
                if change_due < 0:
                    st.error("⚠️ المبلغ المستلم أقل من الإجمالي المطلوب!")
            
            c_act1, c_act2, c_act3 = st.columns(3)
            with c_act1:
                checkout_submit = st.form_submit_button("🖨️ إتمام وطباعة الفاتورة", use_container_width=True)
            with c_act2:
                hold_submit = st.form_submit_button("⏸️ تعليق الفاتورة", use_container_width=True)
            with c_act3:
                clear_submit = st.form_submit_button("🗑️ تفريغ الفاتورة", use_container_width=True)
                
            if checkout_submit:
                if pay_method == "كاش (نقدي)" and change_due < 0:
                    st.error("🎭 **هَنّي روحك.. المبلغ المدفوع غير كافٍ لإتمام الفاتورة!** (خطأ نقص نقدية)")
                else:
                    conn.execute("INSERT INTO invoices (branch_id, user_id, total_amount, payment_method, shift_status) VALUES (?, ?, ?, ?, 'open')", (b_id, st.session_state["user_id"], grand_total, pay_method))
                    for c_item in st.session_state["cart"]:
                        if c_item["id"] != 999999:
                            conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                    conn.commit()
                    st.session_state["cart"] = []
                    log_action(st.session_state["user_id"], "مبيعات POS", f"إتمام فاتورة بمبلغ {grand_total} عبر {pay_method}")
                    st.success(f"🎉 تم إتمام البيع بنجاح عبر ({pay_method})!")
                    st.rerun()
            if hold_submit:
                st.session_state["held_carts"].append(st.session_state["cart"])
                st.session_state["cart"] = []
                st.success("⏸️ تم تعليق الفاتورة بنجاح.")
                st.rerun()
            if clear_submit:
                st.session_state["cart"] = []
                st.rerun()

    if st.session_state["held_carts"] and st.button("▶️ استرجاع فاتورة معلقة"):
        if not st.session_state["cart"]: 
            st.session_state["cart"] = st.session_state["held_carts"].pop()
            st.rerun()

  with tab2:
    if not st.session_state["return_auth"]:
        with st.form("auth_form", clear_on_submit=True):
            auth_pass = st.text_input("الرقم السري للمشرف لفتح المرتجعات:", type="password")
            if st.form_submit_button("فتح شاشة المرتجعات (Enter)"):
                if conn.execute("SELECT role FROM users WHERE password = ? AND role IN ('Admin', 'General_Supervisor', 'Branch_Supervisor')", (auth_pass,)).fetchone():
                    st.session_state["return_auth"] = True; st.rerun()
                else: st.error("🎭 **هَنّي روحك.. الرقم السري للمشرف غير صحيح!** (خطأ مصادقة)")
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
                    conn.execute("INSERT INTO invoices (branch_id, user_id, total_amount, payment_method, shift_status) VALUES (?, ?, ?, 'مرتجع', 'open')", (b_id, st.session_state["user_id"], -refund_total, 'كاش'))
                    conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (ret_qty, item_data_ret['id']))
                    conn.commit(); st.session_state["return_auth"] = False; log_action(st.session_state["user_id"], "مرتجع POS", f"إرجاع صنف بخصم {refund_total}"); st.success("📦 تم إرجاع الصنف وتعديل المخزون بنجاح.")
                    st.rerun()

  with tab3:
    open_sales = conn.execute("SELECT SUM(total_amount) as total FROM invoices WHERE branch_id = ? AND shift_status = 'open'", (b_id,)).fetchone()
    shift_total = open_sales["total"] if open_sales["total"] else 0.0
    col_x, col_z = st.columns(2)
    with col_x: st.markdown(f"""<div class="card" style="background-color: #0284c7;"><h3>X-READ (مبيعات الوردية)</h3><h2>{shift_total:.2f} د.ل</h2></div>""", unsafe_allow_html=True)
    with col_z:
        st.markdown(f"""<div class="card" style="background-color: #be123c;"><h3>Z-READ (تصفير الوردية وإيداع)</h3></div>""", unsafe_allow_html=True)
        treasuries_branch = conn.execute("SELECT id, treasury_name FROM treasuries WHERE branch_id = ? OR (branch_id IS NULL AND company_id = (SELECT company_id FROM branches WHERE id=?))", (b_id, b_id)).fetchall()
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
                        conn.commit(); log_action(st.session_state["user_id"], "إغلاق وردية", "تم تنفيذ Z-Read وإيداع المبالغ"); st.success("📊 تم إغلاق الوردية وترحيل المبالغ للخزينة بنجاح!")
                        st.rerun()
                    else: st.info("🎭 **هَنّي روحك.. الوردية مصفرة بالفعل ولا توجد مبيعات لإغلاقها!** (تنبيه وردية فارغة)")
  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
