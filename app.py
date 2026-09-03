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
  cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT CHECK(role IN ('Admin', 'General_Supervisor', 'Branch_Supervisor', 'Cashier')) NOT NULL, branch_id INTEGER, company_id INTEGER, is_active INTEGER DEFAULT 1, FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE SET NULL, FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL)")
  cursor.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, branch_id INTEGER DEFAULT NULL, item_code TEXT, item_name TEXT NOT NULL, quantity REAL DEFAULT 0.0, buy_price REAL DEFAULT 0.0, sale_price REAL NOT NULL, FOREIGN KEY (company_id) REFERENCES companies(id), FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE)")
  cursor.execute("CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, user_id INTEGER, total_amount REAL, shift_status TEXT DEFAULT 'open', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
  cursor.execute("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, branch_id INTEGER, user_id INTEGER, treasury_id INTEGER, amount REAL NOT NULL, description TEXT NOT NULL, expense_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (company_id) REFERENCES companies(id), FOREIGN KEY (branch_id) REFERENCES branches(id))")
  cursor.execute("CREATE TABLE IF NOT EXISTS treasuries (id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER, branch_id INTEGER, treasury_name TEXT NOT NULL, treasury_type TEXT NOT NULL, balance REAL DEFAULT 0.0)")
  cursor.execute("CREATE TABLE IF NOT EXISTS treasury_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, treasury_id INTEGER, user_id INTEGER, trans_type TEXT NOT NULL, amount REAL NOT NULL, description TEXT, trans_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
  
  cursor.execute("CREATE TABLE IF NOT EXISTS dict_expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
  cursor.execute("CREATE TABLE IF NOT EXISTS dict_transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
  cursor.execute("CREATE TABLE IF NOT EXISTS dict_mixes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)")
  cursor.execute("CREATE TABLE IF NOT EXISTS user_branches (user_id INTEGER, branch_id INTEGER, PRIMARY KEY (user_id, branch_id))")
  
  cursor.execute("CREATE TABLE IF NOT EXISTS role_permissions (role TEXT PRIMARY KEY, allowed_menus TEXT)")
  cursor.execute("CREATE TABLE IF NOT EXISTS activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('General_Supervisor', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),👥 إدارة المستخدمين والصلاحيات,📁 استيراد وتوزيع الأصناف,🏦 إدارة الخزينة والبنوك,💰 تسجيل المصروفات,📊 التقارير الشاملة والمخازن,🥜 التحميص والخلط والتصنيع')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Branch_Supervisor', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),💰 تسجيل المصروفات,📊 التقارير الشاملة والمخازن')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Cashier', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS)')")
  except: pass

  try: cursor.execute("INSERT OR IGNORE INTO dict_expenses (name) VALUES ('رواتب وأجور'), ('إيجار الفرع'), ('كهرباء ومياه'), ('ضيافة ونثريات'), ('صيانة ومعدات'), ('مصروفات تسويق')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO dict_transactions (name) VALUES ('إيداع مبيعات الكاشير'), ('تغذية رصيد الخزينة/الدرج'), ('سحب أرباح للإدارة'), ('تحويل نقدية بين الفروع')")
  except: pass
  
  try: cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
  except: pass

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

# --- تسجيل الدخول (مع زر طوارئ ذكي لترقية أو إنشاء الأدمن العام) ---
if not st.session_state["logged_in"]:
  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.title("🔐 بوابة الدخول")
    st.subheader("مجموعة أبو زيد التجارية (القابضة)")
    
    conn_chk = get_db_connection()
    admin_check = conn_chk.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin'").fetchone()[0]
    conn_chk.close()
    
    if admin_check == 0:
        st.warning("⚠️ لا توجد حسابات بصلاحية (مدير عام - Admin). انقر الزر أدناه لإنشاء/إصلاح حساب الأدمن فوراً:")
        if st.button("🛠️ إنشاء حساب المدير العام (admin / admin)"):
            conn_ins = get_db_connection()
            try:
                # حذف أي حساب قديم باسم admin لتجنب التعارض وإعادة إنشائه بصلاحية Admin مطلقة
                conn_ins.execute("DELETE FROM users WHERE username = 'admin'")
                conn_ins.execute("INSERT INTO users (username, password, role, company_id, is_active) VALUES ('admin', 'admin', 'Admin', NULL, 1)")
                conn_ins.commit()
                st.success("تم إنشاء حساب الأدمن بصلاحيات كاملة بنجاح! قم بإدخاله بالأسفل للدخول.")
                st.rerun()
            except Exception as e:
                st.error(f"خطأ: {e}")
            finally:
                conn_ins.close()

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
              
              perms = conn.execute("SELECT allowed_menus FROM role_permissions WHERE role = ?", (user["role"],)).fetchone()
              if perms and perms["allowed_menus"]: st.session_state["allowed_menus"] = perms["allowed_menus"].split(",")
              else: st.session_state["allowed_menus"] = ALL_MENUS
              
              log_action(user["id"], "تسجيل دخول", f"تم دخول المستخدم {user['username']}")
              conn.close(); st.rerun()
          else: 
              conn.close(); st.error("خطأ في اسم المستخدم أو كلمة المرور!")
  st.stop()

# --- التحقق من الفرع ---
if not st.session_state["branch_verified"]:
  st.title(f"🔥 أهلاً بك، {st.session_state['username']}!")
  conn = get_db_connection()
  
  if st.session_state["role"] == "Admin": branches = conn.execute("SELECT branches.id, branches.branch_name, companies.company_name FROM branches JOIN companies ON branches.company_id = companies.id").fetchall()
  elif st.session_state["role"] == "General_Supervisor" and st.session_state["company_id"]: branches = conn.execute("SELECT branches.id, branches.branch_name, companies.company_name FROM branches JOIN companies ON branches.company_id = companies.id WHERE companies.id = ?", (st.session_state["company_id"],)).fetchall()
  else:
      placeholders = ', '.join('?' for _ in st.session_state["assigned_branches"])
      if placeholders: branches = conn.execute(f"SELECT branches.id, branches.branch_name, companies.company_name FROM branches JOIN companies ON branches.company_id = companies.id WHERE branches.id IN ({placeholders})", st.session_state["assigned_branches"]).fetchall()
      else: branches = []
  conn.close()
  
  branch_options = {f"{b['company_name']} ➔ {b['branch_name']}": b["id"] for b in branches}
  
  if branch_options:
    with st.form("branch_form"):
        chosen_branch = st.selectbox("الفروع المتاحة لك للعمل:", list(branch_options.keys()))
        if st.form_submit_button("تأكيد الفرع والدخول (Enter)"):
            st.session_state["branch_verified"] = True; st.session_state["selected_branch_id"] = branch_options[chosen_branch]
            log_action(st.session_state["user_id"], "اختيار فرع", f"تم فتح العمل على الفرع: {chosen_branch}")
            st.rerun()
  else:
    if st.session_state["role"] == "Admin" and st.button("الدخول كأدمن لتسجيل الفروع"): st.session_state["branch_verified"] = True; st.rerun()
    elif st.session_state["role"] == "General_Supervisor" and st.button("دخول للوحة شركتي"): st.session_state["branch_verified"] = True; st.rerun()
    elif st.session_state["role"] not in ["Admin", "General_Supervisor"]: st.error("❌ ليس لديك أي فروع مخصصة. راجع الإدارة.")
  st.stop()

# --- القائمة الجانبية والشعار ---
conn = get_db_connection()
if st.session_state["role"] == "Admin": logo_row = conn.execute("SELECT logo_path FROM companies WHERE logo_path IS NOT NULL AND logo_path != '' LIMIT 1").fetchone()
else: logo_row = conn.execute("SELECT logo_path FROM companies WHERE id = ? AND logo_path IS NOT NULL AND logo_path != ''", (st.session_state["company_id"],)).fetchone()
conn.close()

if logo_row and os.path.exists(logo_row["logo_path"]): st.sidebar.image(logo_row["logo_path"], use_container_width=True)
else: st.sidebar.markdown("<h2 style='text-align: center;'>🏢 مجموعة أبو زيد (القابضة)</h2>", unsafe_allow_html=True)

st.sidebar.markdown(f"**👤 {st.session_state['username']} | `{st.session_state['role']}`**")
st.sidebar.markdown("---")

menu_to_show = [m for m in ALL_MENUS if m in st.session_state["allowed_menus"] or st.session_state["role"] == "Admin"]
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
  st.title("🌟 لوحة التحكم الرئيسية")
  admin_options = [m for m in menu_to_show if m not in ["🏠 الرئيسية واللوحة", "🚪 تسجيل الخروج"]]
  cols = st.columns(3)
  for i, item in enumerate(admin_options):
      data = dashboard_cards.get(item, {"icon": "✨", "color": "linear-gradient(135deg, #64748b, #475569)", "desc": "إدارة القسم"})
      with cols[i % 3]:
          st.markdown(f'''<div style="background: {data['color']}; padding: 25px 15px; border-radius: 16px; color: white; text-align: center; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); margin-bottom: 10px; min-height: 150px;"><h1 style="margin:0; font-size: 45px;">{data['icon']}</h1><h3 style="margin: 10px 0 5px 0;">{item.split(" ", 1)[1]}</h3><p style="margin:0; font-size: 14px; opacity: 0.9;">{data['desc']}</p></div>''', unsafe_allow_html=True)
          st.button(f"دخول ➔", key=f"btn_{i}", on_click=set_page, args=(item,), use_container_width=True)
          st.markdown("<br>", unsafe_allow_html=True)

elif choice == "🏢 إدارة الشركات والفروع":
  st.header("🏢 إدارة الشركات والفروع")
  conn = get_db_connection()
  if st.session_state["role"] == "Admin":
      with st.expander("➕ إضافة شركة جديدة (صلاحية الأدمن)", expanded=False):
          with st.form("add_comp_form", clear_on_submit=True):
              c_name = st.text_input("اسم الشركة البرمجي")
              c_title = st.text_input("الاسم الرسمي للفاتورة")
              logo_file = st.file_uploader("شعار الشركة", type=["png", "jpg", "jpeg"])
              if st.form_submit_button("💾 حفظ الشركة (Enter)") and c_name:
                  logo_path = ""
                  if logo_file:
                      logo_path = os.path.join("company_logos", logo_file.name)
                      with open(logo_path, "wb") as f: f.write(logo_file.getbuffer())
                  conn.execute("INSERT INTO companies (company_name, company_title, logo_path) VALUES (?, ?, ?)", (c_name.strip(), c_title.strip(), logo_path))
                  conn.commit(); log_action(st.session_state["user_id"], "إضافة شركة", f"تم إضافة شركة: {c_name}"); st.success("تم الحفظ!"); st.rerun()

  comps = get_allowed_companies(conn)
  comps_dict = {c["company_name"]: c["id"] for c in comps}
  
  if comps_dict:
      with st.expander("➕ إضافة فرع جديد", expanded=False):
          with st.form("add_branch_form", clear_on_submit=True):
              sel_c = st.selectbox("اختر الشركة للفرع", list(comps_dict.keys()))
              b_name = st.text_input("اسم الفرع / المخزن")
              if st.form_submit_button("💾 حفظ الفرع (Enter)") and b_name:
                  conn.execute("INSERT INTO branches (company_id, branch_name) VALUES (?, ?)", (comps_dict[sel_c], b_name.strip()))
                  conn.commit(); log_action(st.session_state["user_id"], "إضافة فرع", f"تم إضافة فرع {b_name} للشركة {sel_c}"); st.success("تم الحفظ!"); st.rerun()

  st.markdown("---")
  st.subheader("📋 الهيكل التنظيمي للمجموعة")
  for comp in comps:
      st.markdown(f"### 📁 شركة التابعة: **{comp['company_name']}**")
      branches_df = pd.read_sql("SELECT id, branch_name AS 'اسم الفرع' FROM branches WHERE company_id = ?", conn, params=(comp["id"],))
      c1, c2 = st.columns([2, 1])
      with c1:
          if not branches_df.empty:
              st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;└─ **الفروع التابعة:**")
              edited_b = st.data_editor(branches_df, hide_index=True, key=f"eb_{comp['id']}")
              if st.button(f"💾 حفظ تعديلات فروع ({comp['company_name']})", key=f"save_b_{comp['id']}"):
                  for idx, row in edited_b.iterrows(): conn.execute("UPDATE branches SET branch_name=? WHERE id=?", (row['اسم الفرع'], row['id']))
                  conn.commit(); log_action(st.session_state["user_id"], "تعديل فروع", f"تم تعديل فروع شركة {comp['company_name']}"); st.success("تم التحديث!"); st.rerun()
          else: st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;└─ ⚠️ *لا توجد فروع مسجلة تحت هذه الشركة بعد.*")
      with c2:
          if st.session_state["role"] == "Admin" and st.button(f"🗑️ حذف شركة ({comp['company_name']})", type="primary", key=f"del_c_{comp['id']}"):
              conn.execute("DELETE FROM companies WHERE id=?", (comp["id"],)); conn.commit()
              log_action(st.session_state["user_id"], "حذف شركة", f"تم حذف شركة {comp['company_name']}"); st.rerun()
          if not branches_df.empty:
              del_b_id = st.selectbox("اختر فرعاً للحذف:", branches_df["id"].tolist(), format_func=lambda x: branches_df[branches_df["id"]==x]["اسم الفرع"].values[0], key=f"sel_del_{comp['id']}")
              if st.button("🗑️ حذف الفرع المحدد", key=f"btn_del_{comp['id']}"):
                  conn.execute("DELETE FROM branches WHERE id=?", (del_b_id,)); conn.commit()
                  log_action(st.session_state["user_id"], "حذف فرع", f"تم حذف الفرع المحدد من شركة {comp['company_name']}")
                  st.success("تم الحذف!"); st.rerun()
      st.markdown("<hr style='border:1px dashed #cbd5e1'>", unsafe_allow_html=True)
  conn.close()

elif choice == "👥 إدارة المستخدمين والصلاحيات":
  st.header("👥 إدارة المستخدمين وصلاحيات الـ POS")
  tab1, tab2, tab3 = st.tabs(["👥 حسابات المستخدمين (إنشاء/تعديل/إيقاف)", "🛡️ مدير الصلاحيات (POS Manager)", "📝 سجل نشاط المستخدمين (Audit)"])
  conn = get_db_connection()
  
  with tab1:
      comps = get_allowed_companies(conn)
      comps_dict = {c["company_name"]: c["id"] for c in comps}
      if st.session_state["role"] == "Admin": branches = conn.execute("SELECT branches.id, branches.branch_name, companies.company_name FROM branches JOIN companies ON branches.company_id = companies.id").fetchall()
      else: branches = conn.execute("SELECT branches.id, branches.branch_name, companies.company_name FROM branches JOIN companies ON branches.company_id = companies.id WHERE companies.id = ?", (st.session_state["company_id"],)).fetchall()
      b_dict = {f"{b['company_name']} ➔ {b['branch_name']}": b["id"] for b in branches}

      with st.expander("➕ إضافة مستخدم جديد", expanded=False):
        with st.form("user_form", clear_on_submit=True):
          u = st.text_input("اسم المستخدم")
          p = st.text_input("كلمة المرور")
          
          if st.session_state["role"] == "Admin": roles = ["Admin (مدير النظام)", "General_Supervisor (مدير شركة)", "Branch_Supervisor (مشرف فرع)", "Cashier (كاشير)"]
          else: roles = ["Branch_Supervisor (مشرف فرع)", "Cashier (كاشير)"]
          r = st.selectbox("الرتبة:", roles)
          
          db_role = r.split(" ")[0]
          assigned_c = None
          assigned_b = []
          
          if db_role == "General_Supervisor" and comps_dict:
              assigned_c_name = st.selectbox("الشركة التابعة له:", list(comps_dict.keys()))
              assigned_c = comps_dict[assigned_c_name]
          elif db_role in ["Branch_Supervisor", "Cashier"] and b_dict:
              assigned_b = st.multiselect("الفروع المخصصة:", list(b_dict.keys()))
          
          if st.form_submit_button("💾 حفظ المستخدم") and u and p:
            try:
                cur = conn.cursor()
                cur.execute("INSERT INTO users (username, password, role, company_id) VALUES (?, ?, ?, ?)", (u.strip(), p, db_role, assigned_c))
                new_user_id = cur.lastrowid
                if db_role in ["Branch_Supervisor", "Cashier"]:
                    for branch_str in assigned_b: cur.execute("INSERT INTO user_branches (user_id, branch_id) VALUES (?, ?)", (new_user_id, b_dict[branch_str]))
                conn.commit(); log_action(st.session_state["user_id"], "إضافة مستخدم", f"تم إنشاء حساب للمستخدم {u}"); st.success("تم!")
            except sqlite3.IntegrityError: st.error("❌ اسم المستخدم مسجل مسبقاً!")

      st.markdown("---")
      st.subheader("📋 قائمة المستخدمين (تعديل الأرقام السرية وإيقاف الحسابات)")
      if st.session_state["role"] == "Admin": users_df = pd.read_sql("SELECT id, username AS 'اسم المستخدم', password AS 'كلمة المرور', role AS 'الرتبة', is_active AS 'نشط (1=نعم/0=موقوف)' FROM users", conn)
      else:
          q = "SELECT id, username AS 'اسم المستخدم', password AS 'كلمة المرور', role AS 'الرتبة', is_active AS 'نشط (1=نعم/0=موقوف)' FROM users WHERE company_id = ? OR id IN (SELECT user_id FROM user_branches ub JOIN branches b ON ub.branch_id = b.id WHERE b.company_id = ?)"
          users_df = pd.read_sql(q, conn, params=(st.session_state["company_id"], st.session_state["company_id"]))
      
      if not users_df.empty:
          st.info("💡 يمكنك تعديل (اسم المستخدم، كلمة المرور، وحالة النشاط 1 أو 0) مباشرة بالضغط على الخانة ثم اضغط حفظ.")
          edited_users = st.data_editor(users_df, hide_index=True, disabled=["الرتبة", "id"], key="u_editor")
          c1, c2 = st.columns([2,1])
          with c1:
              if st.button("💾 حفظ تعديلات المستخدمين"):
                  for idx, row in edited_users.iterrows(): conn.execute("UPDATE users SET username=?, password=?, is_active=? WHERE id=?", (row['اسم المستخدم'], row['كلمة المرور'], row['نشط (1=نعم/0=موقوف)'], row['id']))
                  conn.commit(); log_action(st.session_state["user_id"], "تعديل مستخدمين", "تم تعديل بيانات أو أرقام سرية للمستخدمين يدوياً"); st.success("تم الحفظ!")
          with c2:
              del_u_id = st.selectbox("اختر مستخدم للحذف النهائي:", users_df["id"].tolist(), format_func=lambda x: users_df[users_df["id"]==x]["اسم المستخدم"].values[0])
              if st.button("🗑️ حذف المستخدم نهائياً", type="primary") and del_u_id != 0:
                  conn.execute("DELETE FROM users WHERE id=?", (del_u_id,)); conn.commit(); log_action(st.session_state["user_id"], "حذف مستخدم", f"تم حذف المستخدم ID:{del_u_id}"); st.success("تم الحذف!"); st.rerun()

  with tab2:
      st.subheader("🛡️ مدير صلاحيات العرض (POS Manager)")
      if st.session_state["role"] != "Admin": st.error("صلاحية تعديل أقسام النظام مخصصة للأدمن العام فقط.")
      else:
          st.info("حدد القوائم التي يُسمح لكل رتبة بمشاهدتها والدخول إليها:")
          sel_role = st.selectbox("اختر الرتبة لضبط صلاحياتها:", ["General_Supervisor", "Branch_Supervisor", "Cashier"])
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
                  conn.commit(); log_action(st.session_state["user_id"], "تعديل صلاحيات", f"تم تعديل صلاحيات الرتبة {sel_role}"); st.success("تم الحفظ بنجاح!")
                  
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
  def safe_float(val):
      try:
          if pd.isna(val) or str(val).strip() == '': return 0.0
          s = str(val).replace(',', '.')
          s = re.sub(r'[^\d.]', '', s)
          if s.count('.') > 1: s = s.split('.')[0] + '.' + ''.join(s.split('.')[1:])
          return float(s) if s else 0.0
      except: return 0.0

  conn = get_db_connection()
  comps = get_allowed_companies(conn)
  comps_dict = {c["company_name"]: c["id"] for c in comps}
  
  if comps_dict:
    sel_comp = st.selectbox("اختر الشركة (سينزل المخزون في المستودع الرئيسي لهذه الشركة)", list(comps_dict.keys()))
    import_mode = st.radio("طريقة الاستيراد:", ["🔄 تحديث وإضافة", "🚨 مسح كامل واستيراد جديد"])
    up_file = st.file_uploader("اختر ملف الإكسيل (.xlsx)", type=["xlsx", "xls"])
    if up_file and st.button("📥 تنفيذ استيراد الأصناف"):
      df = pd.read_excel(up_file, header=None)
      cur = conn.cursor()
      added_count = 0; updated_count = 0
      if "مسح كامل" in import_mode: cur.execute("DELETE FROM items WHERE company_id = ?", (comps_dict[sel_comp],)); conn.commit()
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
                if code != "": existing = cur.execute("SELECT id FROM items WHERE company_id = ? AND branch_id IS NULL AND (item_code = ? OR item_name = ?) LIMIT 1", (comps_dict[sel_comp], code, name)).fetchone()
                else: existing = cur.execute("SELECT id FROM items WHERE company_id = ? AND branch_id IS NULL AND item_name = ? LIMIT 1", (comps_dict[sel_comp], name)).fetchone()
                if existing:
                    cur.execute("UPDATE items SET quantity = quantity + ?, buy_price = ?, sale_price = ? WHERE id = ?", (qty, b_price, s_price, existing["id"]))
                    updated_count += 1
                else:
                    cur.execute("INSERT INTO items (company_id, branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, NULL, ?, ?, ?, ?, ?)", (comps_dict[sel_comp], code, name, qty, b_price, s_price))
                    added_count += 1
            else:
                cur.execute("INSERT INTO items (company_id, branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, NULL, ?, ?, ?, ?, ?)", (comps_dict[sel_comp], code, name, qty, b_price, s_price))
                added_count += 1
        except Exception: continue
      conn.commit()
      log_action(st.session_state["user_id"], "استيراد أصناف", f"تم استيراد/تحديث أصناف للشركة {sel_comp} بإجمالي {added_count+updated_count} صنف")
      st.success(f"🎉 تمت العملية بنجاح! تم إضافة ({added_count}) وتحديث ({updated_count}). يمكنك توزيعها الآن من (التقارير الشاملة ➔ توزيع ونقل المخزون).")
  conn.close()

elif choice == "🏦 إدارة الخزينة والبنوك":
  st.header("🏦 إدارة الخزائن، العهد، والحسابات البنكية")
  tab1, tab2, tab3 = st.tabs(["🏛️ تعريف الخزائن والبنوك", "💸 عمليات إيداع وسحب", "📊 أرصدة الخزائن"])
  conn = get_db_connection()
  
  with tab1:
      comps = get_allowed_companies(conn)
      if comps:
          c_dict = {c["company_name"]: c["id"] for c in comps}
          with st.form("treasury_form", clear_on_submit=True):
              t_name = st.text_input("اسم الخزينة/البنك")
              t_type = st.selectbox("نوع الخزينة", ["كاش", "بنك", "عهدة فرع"])
              sel_c = st.selectbox("اختر الشركة التابعة لها الخزينة", list(c_dict.keys()))
              
              branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id=?", (c_dict[sel_c],)).fetchall()
              b_dict = {"خزينة عامة للشركة (بدون فرع محدد)": None}
              b_dict.update({b["branch_name"]: b["id"] for b in branches})
              t_branch = st.selectbox("الفرع التابع له", list(b_dict.keys()))
              
              t_bal = st.number_input("الرصيد الافتتاحي (د.ل)", value=0.0)
              if st.form_submit_button("حفظ الخزينة (Enter)") and t_name:
                  conn.execute("INSERT INTO treasuries (company_id, branch_id, treasury_name, treasury_type, balance) VALUES (?, ?, ?, ?, ?)", (c_dict[sel_c], b_dict[t_branch], t_name.strip(), t_type, t_bal))
                  conn.commit(); log_action(st.session_state["user_id"], "إنشاء خزينة", f"تم إنشاء خزينة {t_name}"); st.success("تم الإنشاء!"); st.rerun()

  with tab2:
      if st.session_state["role"] == "Admin": treasuries = conn.execute("SELECT id, treasury_name, balance FROM treasuries").fetchall()
      else: treasuries = conn.execute("SELECT id, treasury_name, balance FROM treasuries WHERE company_id=?", (st.session_state["company_id"],)).fetchall()
      
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
              if sel_desc == "➕ إضافة بيان حركة جديد...": new_desc = st.text_input("اكتب البيان الجديد هنا:")
              
              if st.form_submit_button("تأكيد العملية (Enter)"):
                  final_desc = new_desc.strip() if sel_desc == "➕ إضافة بيان حركة جديد..." else sel_desc
                  if final_desc:
                      if sel_desc == "➕ إضافة بيان حركة جديد...": conn.execute("INSERT OR IGNORE INTO dict_transactions (name) VALUES (?)", (final_desc,))
                      t_id = t_options[sel_t]
                      if trans_type == "إيداع": conn.execute("UPDATE treasuries SET balance = balance + ? WHERE id = ?", (amount, t_id))
                      else: conn.execute("UPDATE treasuries SET balance = balance - ? WHERE id = ?", (amount, t_id))
                      conn.execute("INSERT INTO treasury_transactions (treasury_id, user_id, trans_type, amount, description) VALUES (?, ?, ?, ?, ?)", (t_id, st.session_state["user_id"], trans_type, amount, final_desc))
                      conn.commit(); log_action(st.session_state["user_id"], f"{trans_type} خزينة", f"المبلغ {amount} لسبب: {final_desc}"); st.success("تم تسجيل الحركة!"); st.rerun()
                  else: st.warning("اكتب البيان.")

  with tab3:
      if st.session_state["role"] == "Admin": df_t = pd.read_sql("SELECT treasuries.id AS 'id', companies.company_name AS 'الشركة', treasuries.treasury_name AS 'الاسم', treasuries.treasury_type AS 'النوع', IFNULL(branches.branch_name, 'خزينة عامة') AS 'الفرع', treasuries.balance AS 'الرصيد' FROM treasuries LEFT JOIN companies ON treasuries.company_id = companies.id LEFT JOIN branches ON treasuries.branch_id = branches.id", conn)
      else: df_t = pd.read_sql("SELECT treasuries.id AS 'id', companies.company_name AS 'الشركة', treasuries.treasury_name AS 'الاسم', treasuries.treasury_type AS 'النوع', IFNULL(branches.branch_name, 'خزينة عامة') AS 'الفرع', treasuries.balance AS 'الرصيد' FROM treasuries LEFT JOIN companies ON treasuries.company_id = companies.id LEFT JOIN branches ON treasuries.branch_id = branches.id WHERE treasuries.company_id = ?", conn, params=(st.session_state["company_id"],))
      
      if not df_t.empty:
          edited_t = st.data_editor(df_t, disabled=(st.session_state["role"] == "Cashier"), hide_index=True, key="t_editor")
          if st.session_state["role"] != "Cashier" and st.button("💾 حفظ تعديلات الخزائن"):
              for idx, row in edited_t.iterrows(): conn.execute("UPDATE treasuries SET treasury_name=?, treasury_type=?, balance=? WHERE id=?", (row['الاسم'], row['النوع'], row['الرصيد'], row['id']))
              conn.commit(); log_action(st.session_state["user_id"], "تعديل خزائن", "تم تعديل أرصدة أو أسماء الخزائن يدوياً"); st.success("تم التحديث!")
          st.markdown("---")
          if st.session_state["role"] == "Admin": df_trans = pd.read_sql("SELECT treasury_transactions.id AS 'رقم', treasuries.treasury_name AS 'الخزينة', treasury_transactions.trans_type AS 'النوع', treasury_transactions.amount AS 'المبلغ', treasury_transactions.description AS 'البيان', users.username AS 'المستخدم', treasury_transactions.trans_date AS 'التاريخ' FROM treasury_transactions JOIN treasuries ON treasury_transactions.treasury_id = treasuries.id LEFT JOIN users ON treasury_transactions.user_id = users.id ORDER BY treasury_transactions.trans_date DESC", conn)
          else: df_trans = pd.read_sql("SELECT treasury_transactions.id AS 'رقم', treasuries.treasury_name AS 'الخزينة', treasury_transactions.trans_type AS 'النوع', treasury_transactions.amount AS 'المبلغ', treasury_transactions.description AS 'البيان', users.username AS 'المستخدم', treasury_transactions.trans_date AS 'التاريخ' FROM treasury_transactions JOIN treasuries ON treasury_transactions.treasury_id = treasuries.id LEFT JOIN users ON treasury_transactions.user_id = users.id WHERE treasuries.company_id = ? ORDER BY treasury_transactions.trans_date DESC", conn, params=(st.session_state["company_id"],))
          st.dataframe(df_trans, use_container_width=True)
  conn.close()

elif choice == "💰 تسجيل المصروفات":
  st.header("💰 تسجيل وإدارة المصروفات")
  conn = get_db_connection()
  comps = get_allowed_companies(conn)
  comps_dict = {c["company_name"]: c["id"] for c in comps}
  
  if comps_dict:
      col1, col2 = st.columns(2)
      with col1: sel_comp = st.selectbox("الشركة الخاصة بالمصروف", list(comps_dict.keys()))
      with col2:
          branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id = ?", (comps_dict[sel_comp],)).fetchall()
          b_dict = {b["branch_name"]: b["id"] for b in branches}
          sel_branch = st.selectbox("الفرع", list(b_dict.keys())) if b_dict else None
      
      treasuries = conn.execute("SELECT id, treasury_name, balance FROM treasuries WHERE company_id = ?", (comps_dict[sel_comp],)).fetchall()
      t_dict = {f"{t['treasury_name']} (رصيد: {t['balance']:,.2f})": t["id"] for t in treasuries}
      
      with st.form("expense_form", clear_on_submit=True):
          amount = st.number_input("مبلغ المصروف (د.ل)", min_value=0.1, value=10.0)
          exp_list = [r["name"] for r in conn.execute("SELECT name FROM dict_expenses").fetchall()]
          exp_list.append("➕ إضافة تصنيف/بيان مصروف جديد...")
          sel_desc = st.selectbox("تصنيف / بيان المصروف", exp_list)
          new_desc = ""
          if sel_desc == "➕ إضافة تصنيف/بيان مصروف جديد...": new_desc = st.text_input("اكتب البيان الجديد هنا:")
          sel_t = st.selectbox("خصم القيمة من الخزينة/البنك:", list(t_dict.keys())) if t_dict else None
              
          if st.form_submit_button("💾 حفظ وخصم المصروف (Enter)"):
              final_desc = new_desc.strip() if sel_desc == "➕ إضافة تصنيف/بيان مصروف جديد..." else sel_desc
              if final_desc and sel_branch and sel_t:
                  if sel_desc == "➕ إضافة تصنيف/بيان مصروف جديد...": conn.execute("INSERT OR IGNORE INTO dict_expenses (name) VALUES (?)", (final_desc,))
                  t_id = t_dict[sel_t]
                  conn.execute("INSERT INTO expenses (company_id, branch_id, user_id, treasury_id, amount, description) VALUES (?, ?, ?, ?, ?, ?)", (comps_dict[sel_comp], b_dict[sel_branch], st.session_state["user_id"], t_id, amount, final_desc))
                  conn.execute("UPDATE treasuries SET balance = balance - ? WHERE id = ?", (amount, t_id))
                  conn.execute("INSERT INTO treasury_transactions (treasury_id, user_id, trans_type, amount, description) VALUES (?, ?, 'سحب', ?, ?)", (t_id, st.session_state["user_id"], amount, f"مصروفات: {final_desc}"))
                  conn.commit(); log_action(st.session_state["user_id"], "تسجيل مصروف", f"مبلغ {amount} لسبب: {final_desc}"); st.success("تم تسجيل المصروف!"); st.rerun()
  conn.close()

elif choice == "📊 التقارير الشاملة والمخازن":
  st.header("📊 التقارير الشاملة والمخازن")
  tab1, tab5, tab2, tab3, tab4 = st.tabs(["📋 تقارير وتعديل المخزون", "🔄 توزيع ونقل المخزون", "📈 تقارير المبيعات", "💸 تقارير المصروفات", "⚙️ تصفير البيانات"])
  conn = get_db_connection()
  
  comp_filter = ""
  params = ()
  if st.session_state["role"] != "Admin":
      comp_filter = " WHERE companies.id = ? "
      params = (st.session_state["company_id"],)
  
  items_df = pd.read_sql(f"SELECT items.id AS id, companies.company_name AS الشركة, branches.branch_name AS الفرع, items.item_code AS الكود, items.item_name AS الصنف, items.quantity AS الكمية, items.buy_price AS 'سعر الشراء', items.sale_price AS 'سعر البيع' FROM items JOIN companies ON items.company_id = companies.id LEFT JOIN branches ON items.branch_id = branches.id {comp_filter}", conn, params=params)
  items_df['الفرع'] = items_df['الفرع'].fillna('المخزن الرئيسي للشركة (غير موزع)')
  
  with tab1:
      if not items_df.empty:
          edited_items = st.data_editor(items_df, disabled=(st.session_state["role"] == "Cashier"), hide_index=True, key="items_editor")
          c1, c2 = st.columns(2)
          with c1:
              if st.session_state["role"] != "Cashier" and st.button("💾 حفظ تعديلات المخزون"):
                  for idx, row in edited_items.iterrows(): conn.execute("UPDATE items SET item_code=?, item_name=?, quantity=?, buy_price=?, sale_price=? WHERE id=?", (row['الكود'], row['الصنف'], row['الكمية'], row['سعر الشراء'], row['سعر البيع'], row['id']))
                  conn.commit(); log_action(st.session_state["user_id"], "تعديل مخزون", "تم تعديل بيانات الأصناف يدوياً"); st.success("تم الحفظ!")
          with c2: st.download_button("📥 تصدير المخزون لـ Excel", data=to_excel(items_df), file_name="inventory.xlsx")

  # --- النظام الذكي لتوزيع ونقل المخزون ---
  with tab5:
      st.subheader("🔄 توزيع ونقل المخزون (بين الشركات والفروع)")
      transfer_type = st.radio("اختر نوع النقل والتوزيع:", ["نقل صنف محدد (فردي)", "نقل كافة الأصناف دفعة واحدة (من شركة لشركة)"])
      
      if transfer_type == "نقل صنف محدد (فردي)":
          if not items_df.empty:
              item_ids = items_df["id"].tolist()
              sel_item_id = st.selectbox(
                  "📦 1. اختر الصنف المراد نقله أو توزيعه (ابحث بالكتابة):", 
                  item_ids,
                  format_func=lambda x: f"[{items_df[items_df['id'] == x]['الكود'].values[0]}] {items_df[items_df['id'] == x]['الصنف'].values[0]} | المصدر: {items_df[items_df['id'] == x]['الشركة'].values[0]} - {items_df[items_df['id'] == x]['الفرع'].values[0]} | متاح: {items_df[items_df['id'] == x]['الكمية'].values[0]}"
              )
              st.markdown("**🎯 2. إلى أين تريد نقل أو توزيع هذا الصنف؟**")
              col_dest1, col_dest2 = st.columns(2)
              if st.session_state["role"] == "Admin": t_comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
              else: t_comps = conn.execute("SELECT id, company_name FROM companies WHERE id=?", (st.session_state["company_id"],)).fetchall()
              c_dict = {c["company_name"]: c["id"] for c in t_comps}
              
              with col_dest1:
                  target_comp_name = st.selectbox("إلى شركة:", list(c_dict.keys()), key="tc1")
                  target_comp_id = c_dict[target_comp_name] if target_comp_name else None
              with col_dest2:
                  if target_comp_id:
                      target_branches = conn.execute("SELECT id, branch_name FROM branches WHERE company_id=?", (target_comp_id,)).fetchall()
                      b_dict = {"المخزن الرئيسي للشركة (بدون فرع)": None}
                      b_dict.update({b["branch_name"]: b["id"] for b in target_branches})
                      target_branch_name = st.selectbox("إلى فرع:", list(b_dict.keys()), key="tb1")
                      target_branch_id = b_dict[target_branch_name]
                  else: target_branch_id = None
              
              transfer_qty = st.number_input("الكمية المراد نقلها", min_value=0.1, value=1.0)
              if st.button("🚀 تنفيذ النقل / التوزيع", use_container_width=True):
                  curr_item = conn.execute("SELECT * FROM items WHERE id = ?", (sel_item_id,)).fetchone()
                  if curr_item and curr_item["quantity"] >= transfer_qty:
                      conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (transfer_qty, sel_item_id))
                      if target_branch_id is None: existing = conn.execute("SELECT id FROM items WHERE company_id=? AND branch_id IS NULL AND item_code=? AND item_name=?", (target_comp_id, curr_item["item_code"], curr_item["item_name"])).fetchone()
                      else: existing = conn.execute("SELECT id FROM items WHERE company_id=? AND branch_id=? AND item_code=? AND item_name=?", (target_comp_id, target_branch_id, curr_item["item_code"], curr_item["item_name"])).fetchone()
                      if existing: conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (transfer_qty, existing["id"]))
                      else: conn.execute("INSERT INTO items (company_id, branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?, ?)", (target_comp_id, target_branch_id, curr_item["item_code"], curr_item["item_name"], transfer_qty, curr_item["buy_price"], curr_item["sale_price"]))
                      conn.commit(); log_action(st.session_state["user_id"], "نقل مخزون", f"تم نقل {transfer_qty} من {curr_item['item_name']} إلى {target_comp_name} - {target_branch_name}"); st.success("تم النقل بنجاح!"); st.rerun()
                  else: st.error("الكمية المتاحة لا تكفي للتحويل!")
          else: st.info("المخزن فارغ حالياً.")
          
      else: # النقل الشامل (Bulk Transfer)
          st.markdown("**🎯 نقل كامل الأصناف دفعة واحدة (من الشركة الأم للشركات التابعة)**")
          col_src, col_dst = st.columns(2)
          if st.session_state["role"] == "Admin": t_comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
          else: t_comps = conn.execute("SELECT id, company_name FROM companies WHERE id=?", (st.session_state["company_id"],)).fetchall()
          c_dict = {c["company_name"]: c["id"] for c in t_comps}
          
          with col_src:
              source_comp_name = st.selectbox("📦 من (الشركة المصدرة / الأم):", list(c_dict.keys()), key="src_comp")
              source_comp_id = c_dict[source_comp_name] if source_comp_name else None
          with col_dst:
              target_comp_name = st.selectbox("🎯 إلى (الشركة المستهدفة / التابعة):", list(c_dict.keys()), key="dst_comp")
              target_comp_id = c_dict[target_comp_name] if target_comp_name else None
              
          st.info("سيتم أخذ كافة الأصناف المتوفرة في **المخزن الرئيسي** للشركة المصدرة، وتحويلها بالكامل إلى **المخزن الرئيسي** للشركة المستهدفة بضغطة زر واحدة.")
          
          if st.button("🚀 تنفيذ نقل كافة الأصناف دفعة واحدة", use_container_width=True, type="primary"):
              if source_comp_id == target_comp_id: st.error("لا يمكن النقل لنفس الشركة!")
              else:
                  source_items = conn.execute("SELECT * FROM items WHERE company_id = ? AND branch_id IS NULL AND quantity > 0", (source_comp_id,)).fetchall()
                  if not source_items: st.warning("لا توجد أصناف بكميات متاحة في المخزن الرئيسي لهذه الشركة.")
                  else:
                      transferred_count = 0
                      for s_item in source_items:
                          existing = conn.execute("SELECT id FROM items WHERE company_id=? AND branch_id IS NULL AND item_code=? AND item_name=?", (target_comp_id, s_item["item_code"], s_item["item_name"])).fetchone()
                          if existing: conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (s_item["quantity"], existing["id"]))
                          else: conn.execute("INSERT INTO items (company_id, branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, NULL, ?, ?, ?, ?, ?)", (target_comp_id, s_item["item_code"], s_item["item_name"], s_item["quantity"], s_item["buy_price"], s_item["sale_price"]))
                          conn.execute("UPDATE items SET quantity = 0 WHERE id = ?", (s_item["id"],))
                          transferred_count += 1
                      conn.commit(); log_action(st.session_state["user_id"], "نقل مخزون شامل", f"تم نقل {transferred_count} صنف من {source_comp_name} إلى {target_comp_name}"); st.success(f"تم نقل ({transferred_count}) صنف بنجاح إلى مخزن {target_comp_name}!"); st.rerun()

  with tab2:
      invoices_df = pd.read_sql(f"SELECT invoices.id AS 'id', companies.company_name AS 'الشركة', branches.branch_name AS 'الفرع', users.username AS 'الكاشير', invoices.total_amount AS 'المبلغ', CASE WHEN invoices.shift_status = 'open' THEN 'حالية (لم ترحل)' ELSE 'سابقة (مرحلة Z-READ)' END AS 'حالة العملية', invoices.created_at AS 'التاريخ' FROM invoices LEFT JOIN branches ON invoices.branch_id = branches.id LEFT JOIN companies ON branches.company_id = companies.id LEFT JOIN users ON invoices.user_id = users.id {comp_filter}", conn, params=params)
      if not invoices_df.empty:
          edited_inv = st.data_editor(invoices_df, disabled=(st.session_state["role"] == "Cashier"), hide_index=True, key="inv_editor")
          c1, c2 = st.columns(2)
          with c1:
              if st.session_state["role"] != "Cashier" and st.button("💾 حفظ تعديلات المبيعات"):
                  for idx, row in edited_inv.iterrows(): conn.execute("UPDATE invoices SET total_amount=? WHERE id=?", (row['المبلغ'], row['id']))
                  conn.commit(); log_action(st.session_state["user_id"], "تعديل مبيعات", "تم تعديل إجمالي فواتير مبيعات يدوياً"); st.success("تم الحفظ!")
          with c2: st.download_button("📥 تصدير المبيعات لـ Excel", data=to_excel(invoices_df), file_name="sales.xlsx")

  with tab3:
      expenses_df = pd.read_sql(f"SELECT expenses.id AS 'id', companies.company_name AS 'الشركة', branches.branch_name AS 'الفرع', treasuries.treasury_name AS 'خُصمت من', users.username AS 'المستخدم', expenses.amount AS 'المبلغ', expenses.description AS 'البيان', expenses.expense_date AS 'التاريخ' FROM expenses LEFT JOIN branches ON expenses.branch_id = branches.id LEFT JOIN companies ON branches.company_id = companies.id LEFT JOIN users ON expenses.user_id = users.id LEFT JOIN treasuries ON expenses.treasury_id = treasuries.id {comp_filter}", conn, params=params)
      if not expenses_df.empty:
          edited_exp = st.data_editor(expenses_df, disabled=(st.session_state["role"] == "Cashier"), hide_index=True, key="exp_editor")
          c1, c2 = st.columns(2)
          with c1:
              if st.session_state["role"] != "Cashier" and st.button("💾 حفظ تعديلات المصروفات"):
                  for idx, row in edited_exp.iterrows(): conn.execute("UPDATE expenses SET amount=?, description=? WHERE id=?", (row['المبلغ'], row['البيان'], row['id']))
                  conn.commit(); log_action(st.session_state["user_id"], "تعديل مصروفات", "تم تعديل سجلات مصروفات يدوياً"); st.success("تم الحفظ!")
          with c2: st.download_button("📥 تصدير المصروفات لـ Excel", data=to_excel(expenses_df), file_name="expenses.xlsx")

  with tab4:
      st.error("🚨 سيتم مسح المبيعات والمصروفات والأرصدة لتبدأ فترة مالية من الصفر.")
      if st.checkbox("أؤكد التصفير") and st.button("🚨 تصفير السنة المالية الآن"):
          if st.session_state["role"] == "Admin":
              conn.execute("DELETE FROM invoices"); conn.execute("DELETE FROM expenses"); conn.execute("DELETE FROM treasury_transactions")
              conn.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name IN ('invoices', 'expenses', 'treasury_transactions')")
          else:
              conn.execute("DELETE FROM invoices WHERE branch_id IN (SELECT id FROM branches WHERE company_id=?)", (st.session_state["company_id"],))
              conn.execute("DELETE FROM expenses WHERE company_id=?", (st.session_state["company_id"],))
          conn.commit(); log_action(st.session_state["user_id"], "تصفير شامل", "تم مسح البيانات المالية للتهيئة"); st.success("تم التصفير بنجاح!"); st.rerun()
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
              conn.commit(); log_action(st.session_state["user_id"], "تحميص", f"تم تحميص {final_roast_name}"); st.success(f"تم التحميص! السعر: {new_unit_price:.2f}")
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
            conn.commit(); log_action(st.session_state["user_id"], "خلط وتصنيع", f"تم اعتماد {final_mix_name}"); st.success(f"تم الاعتماد بسعر: {final_price:.2f}")
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
        c_act1, c_act2, c_act3 = st.columns(3)
        with c_act1:
            if st.button("🖨️ إتمام وطباعة الفاتورة", use_container_width=True):
                conn.execute("INSERT INTO invoices (branch_id, user_id, total_amount, shift_status) VALUES (?, ?, ?, 'open')", (b_id, st.session_state["user_id"], grand_total))
                for c_item in st.session_state["cart"]: conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                conn.commit(); st.session_state["cart"] = []; log_action(st.session_state["user_id"], "مبيعات POS", f"إتمام فاتورة بمبلغ {grand_total}"); st.success("تم إتمام البيع!"); st.rerun()
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
                    conn.commit(); st.session_state["return_auth"] = False; log_action(st.session_state["user_id"], "مرتجع POS", f"إرجاع صنف بخصم {refund_total}"); st.success("تم الإرجاع بنجاح."); st.rerun()

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
                        conn.commit(); log_action(st.session_state["user_id"], "إغلاق وردية", "تم تنفيذ Z-Read وإيداع المبالغ"); st.success("تم الترحيل بنجاح!"); st.rerun()
                    else: st.info("الوردية مصفرة بالفعل.")
  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
