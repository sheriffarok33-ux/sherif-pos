import os
import re
import io
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime

st.set_page_config(
    page_title="مجموعة أبو زيد - نظام المحامص والمخازن",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Tajawal', sans-serif; }
    .main { background-color: #f4f7f6; }
    div.stButton > button { border-radius: 10px; font-weight: 700; transition: all 0.3s ease; height: 45px; }
    [data-testid="stSidebar"] .stButton>button {
        background-color: #ffffff; color: #1e293b; border: 1px solid #e2e8f0;
        border-radius: 12px; padding: 10px 15px; text-align: right; font-weight: bold;
        transition: all 0.3s ease; margin-bottom: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.02); font-size: 16px; height: auto;
    }
    [data-testid="stSidebar"] .stButton>button:hover { background-color: #2563eb; color: white; border-color: #2563eb; transform: translateX(-5px); }
    .card { padding: 15px; border-radius: 12px; color: white; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 10px; }
    .pos-item-card { background: white; padding: 12px; border-radius: 10px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; margin-bottom: 8px; }
    </style>
""", unsafe_allow_html=True)

if not os.path.exists("item_images"): os.makedirs("item_images")

DEFAULT_MENUS = [
    "🏠 الرئيسية واللوحة",
    "🛒 نقطة البيع (POS)",
    "📦 إدارة المخزن الرئيسي والفروع",
    "🔄 نقل وتحويل الأصناف للفروع",
    "🏢 إدارة وتغيير أسماء الفروع والحذف",
    "💰 تسجيل المصروفات والمصروف العام",
    "📥 المشتريات والموردين",
    "🥜 التحميص والخلط والتصنيع",
    "📊 الأرباح والخسائر والتقارير",
    "👥 إدارة المستخدمين وصلاحياتهم",
    "⚙️ تخصيص وتعديل مسميات الأزرار والقوائم"
]

def initialize_database():
  conn = sqlite3.connect("abu_zaid_new_system.db", timeout=10)
  conn.row_factory = sqlite3.Row
  cursor = conn.cursor()

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS branches (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          branch_name TEXT UNIQUE NOT NULL,
          branch_type TEXT DEFAULT 'فرع'
      )
  """)

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL,
          phone TEXT,
          password TEXT NOT NULL,
          role TEXT NOT NULL,
          branch_id INTEGER,
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
          FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
      )
  """)

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS purchases (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          branch_id INTEGER,
          supplier_name TEXT,
          total_cost REAL,
          invoice_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (branch_id) REFERENCES branches(id)
      )
  """)

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS expenses (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          branch_id INTEGER,
          amount REAL NOT NULL,
          description TEXT NOT NULL,
          is_general_store INTEGER DEFAULT 0,
          expense_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (branch_id) REFERENCES branches(id)
      )
  """)

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS invoices (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          branch_id INTEGER,
          user_id INTEGER,
          total_amount REAL,
          payment_method TEXT DEFAULT 'كاش',
          notes TEXT,
          shift_status TEXT DEFAULT 'open',
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (branch_id) REFERENCES branches(id)
      )
  """)

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS role_permissions (
          role TEXT PRIMARY KEY,
          allowed_menus TEXT
      )
  """)

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS custom_labels (
          original_name TEXT PRIMARY KEY,
          custom_name TEXT NOT NULL
      )
  """)

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS activity_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          action TEXT,
          details TEXT,
          log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
  """)

  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Admin', ?)", (",".join(DEFAULT_MENUS),))
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('General_Supervisor', ?)", (",".join(DEFAULT_MENUS),))
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Branch_Supervisor', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),📦 إدارة المخزن الرئيسي والفروع,📥 المشتريات والموردين')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Cashier', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS)')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Viewer', '🏠 الرئيسية واللوحة,📊 الأرباح والخسائر والتقارير')")
  except: pass

  default_branches = [("المخزن الرئيسي", "مخزن"), ("فرع 1", "فرع"), ("فرع 2", "فرع"), ("فرع 3", "فرع"), ("فرع 4", "فرع")]
  for b_name, b_type in default_branches:
      cursor.execute("INSERT OR IGNORE INTO branches (branch_name, branch_type) VALUES (?, ?)", (b_name, b_type))

  admin_chk = cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin' AND is_active = 1").fetchone()[0]
  if admin_chk == 0:
      cursor.execute("INSERT OR IGNORE INTO users (username, phone, password, role, is_active) VALUES ('admin', '0910000000', 'admin', 'Admin', 1)")

  conn.commit()
  conn.close()

initialize_database()

def get_db_connection():
  conn = sqlite3.connect("abu_zaid_new_system.db", timeout=10)
  conn.execute("PRAGMA foreign_keys = ON")
  conn.row_factory = sqlite3.Row
  return conn

def get_label(orig_name):
    conn = get_db_connection()
    row = conn.execute("SELECT custom_name FROM custom_labels WHERE original_name = ?", (orig_name,)).fetchone()
    conn.close()
    return row["custom_name"] if row else orig_name

def verify_admin_password(pass_input):
    if st.session_state["role"] == "Admin":
        conn = get_db_connection()
        admin_user = conn.execute("SELECT * FROM users WHERE id = ? AND password = ?", (st.session_state["user_id"], pass_input)).fetchone()
        conn.close()
        return admin_user is not None
    return False

def log_action(user_id, action, details):
    if not user_id: return
    conn = get_db_connection()
    conn.execute("INSERT INTO activity_logs (user_id, action, details) VALUES (?, ?, ?)", (user_id, action, details))
    conn.commit(); conn.close()

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
if "page" not in st.session_state: st.session_state["page"] = "🏠 الرئيسية واللوحة"
if "barcode_scan" not in st.session_state: st.session_state["barcode_scan"] = ""

def set_page(page_name): st.session_state["page"] = page_name

@st.dialog("🔒 تأكيد كلمة سر الأدمن المطلوبة")
def admin_confirm_dialog(action_type, target_id, target_name=""):
    st.warning(f"⚠️ تحذير أمني: أنت على وشك تنفيذ عملية ({action_type}). يرجى إدخال كلمة سر الأدمن للمتابعة:")
    admin_pass = st.text_input("كلمة سر الأدمن:", type="password", key="diag_pass_input")
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        if st.button("✅ تأكيد التنفيذ", use_container_width=True):
            if verify_admin_password(admin_pass):
                conn = get_db_connection()
                if action_type == "حذف فرع":
                    conn.execute("DELETE FROM branches WHERE id = ?", (target_id,))
                elif action_type == "حذف صنف":
                    conn.execute("DELETE FROM items WHERE id = ?", (target_id,))
                elif action_type == "حذف مصروف":
                    conn.execute("DELETE FROM expenses WHERE id = ?", (target_id,))
                elif action_type == "حذف مشتريات":
                    conn.execute("DELETE FROM purchases WHERE id = ?", (target_id,))
                elif action_type == "حذف فاتورة":
                    conn.execute("DELETE FROM invoices WHERE id = ?", (target_id,))
                elif action_type == "حذف مستخدم":
                    conn.execute("DELETE FROM users WHERE id = ?", (target_id,))
                
                conn.commit()
                conn.close()
                log_action(st.session_state["user_id"], f"حذف آمن ({action_type})", f"تم حذف العناصر ذات الرقم {target_id}")
                st.success(f"🗑️ تمت عملية ({action_type}) بنجاح وإغلاق النافذة!")
                st.rerunn = st.rerun()
            else:
                st.error("❌ كلمة سر الأدمن غير صحيحة!")
    with col_d2:
        if st.button("❌ إلغاء", use_container_width=True):
            st.rerun()

def process_scale_barcode():
    code = st.session_state.barcode_scan.strip()
    if code:
        b_id = st.session_state.get("branch_id")
        conn = get_db_connection()
        item = None
        if code.startswith("20") and len(code) >= 12:
            item_code = code[2:7]
            scale_value = float(code[7:]) / 100.0
            item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (item_code, b_id)).fetchone()
            if item:
                unit_price = float(item["sale_price"])
                calculated_qty = scale_value / unit_price if unit_price > 0 else 1.0
                st.session_state["cart"].append({
                    "id": item["id"], "code": item["item_code"], "name": item["item_name"],
                    "price": unit_price, "qty": float(calculated_qty), "total": float(scale_value)
                })
        if not item:
            item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
            if item:
                st.session_state["cart"].append({
                    "id": item["id"], "code": item["item_code"], "name": item["item_name"],
                    "price": float(item["sale_price"]), "qty": 1.0, "total": float(item["sale_price"]) * 1.0
                })
        conn.close()
    st.session_state.barcode_scan = ""

# --- بوابة الدخول ---
if not st.session_state["logged_in"]:
  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.markdown("<br><br><br>", unsafe_allow_html=True)
    st.title("🔐 بوابة دخول نظام المحامص")
    st.subheader("مجموعة أبو زيد التجارية")
    
    with st.form("login_form"):
      u_name = st.text_input("اسم المستخدم")
      u_pass = st.text_input("كلمة المرور", type="password")
      submit = st.form_submit_button("🚀 دخول للنظام", use_container_width=True)
      if submit:
          conn = get_db_connection()
          user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (u_name, u_pass)).fetchone()
          if user:
              if user["is_active"] == 0:
                  st.error("🚫 هذا الحساب موقوف!")
                  conn.close(); st.stop()
                  
              st.session_state["logged_in"] = True
              st.session_state["username"] = user["username"]
              st.session_state["role"] = user["role"]
              st.session_state["user_id"] = user["id"]
              st.session_state["branch_id"] = user["branch_id"]
              
              if user["role"] == "Admin":
                  st.session_state["allowed_menus"] = DEFAULT_MENUS
              else:
                  perms = conn.execute("SELECT allowed_menus FROM role_permissions WHERE role = ?", (user["role"],)).fetchone()
                  if perms and perms["allowed_menus"]: st.session_state["allowed_menus"] = perms["allowed_menus"].split(",")
                  else: st.session_state["allowed_menus"] = ["🏠 الرئيسية واللوحة"]
              
              log_action(user["id"], "تسجيل دخول", f"تم دخول المستخدم {user['username']}")
              conn.close(); st.rerun()
          else: 
              conn.close(); st.error("🎭 **هَنّي روحك.. اسم المستخدم أو كلمة المرور غير صحيحة!**")
  st.stop()

# --- القائمة الجانبية والصلاحيات ---
st.sidebar.markdown("<h2 style='text-align: center;'>🥜 محامص أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"**👤 {st.session_state['username']} | `{st.session_state['role']}`**")
st.sidebar.markdown("---")

current_allowed = DEFAULT_MENUS if st.session_state["role"] == "Admin" else st.session_state.get("allowed_menus", DEFAULT_MENUS)
menu_to_show = [m for m in DEFAULT_MENUS if m in current_allowed]

for m in menu_to_show:
    disp_name = get_label(m)
    if st.sidebar.button(disp_name, use_container_width=True, key=f"btn_menu_{m}"):
        st.session_state["page"] = m; st.rerun()

if st.sidebar.button("🚪 تسجيل الخروج", use_container_width=True, key="btn_logout_sidebar"):
    log_action(st.session_state["user_id"], "تسجيل خروج", "تم تسجيل الخروج")
    st.session_state.clear(); st.rerun()

choice = st.session_state["page"]

dashboard_cards = {
    "🛒 نقطة البيع (POS)": {"icon": "🛒", "color": "linear-gradient(135deg, #f59e0b, #ea580c)", "desc": "شاشة الكاشير ومبيعات الميزان"},
    "📦 إدارة المخزن الرئيسي والفروع": {"icon": "📦", "color": "linear-gradient(135deg, #3b82f6, #1d4ed8)", "desc": "جرد وإضافة الفائض بالمخازن"},
    "🔄 نقل وتحويل الأصناف للفروع": {"icon": "🔄", "color": "linear-gradient(135deg, #8b5cf6, #6d28d9)", "desc": "تحويل وتوزيع الأصناف من المخزن الرئيسي"},
    "🏢 إدارة وتغيير أسماء الفروع والحذف": {"icon": "🏢", "color": "linear-gradient(135deg, #0ea5e9, #0369a1)", "desc": "إضافة وتعديل وحذف المخزن والفروع"},
    "💰 تسجيل المصروفات والمصروف العام": {"icon": "💸", "color": "linear-gradient(135deg, #10b981, #047857)", "desc": "تسجيل المصروفات وتوزيعها تلقائياً"},
    "📥 المشتريات والموردين": {"icon": "📥", "color": "linear-gradient(135deg, #6366f1, #4338ca)", "desc": "فواتير المشتريات للمخزن/الفروع"}
}

# --- محتوى الصفحات ---
if choice == "🏠 الرئيسية واللوحة":
  st.title("🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية")
  cols = st.columns(3)
  for i, (item, data) in enumerate(dashboard_cards.items()):
      with cols[i % 3]:
          c_title = get_label(item)
          st.markdown(f'''<div style="background: {data['color']}; padding: 25px 15px; border-radius: 16px; color: white; text-align: center; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); margin-bottom: 10px; min-height: 150px;"><h1 style="margin:0; font-size: 45px;">{data['icon']}</h1><h3 style="margin: 10px 0 5px 0;">{c_title.split(" ", 1)[-1] if " " in c_title else c_title}</h3><p style="margin:0; font-size: 14px; opacity: 0.9;">{data['desc']}</p></div>''', unsafe_allow_html=True)
          if st.button(f"دخول ➔", key=f"btn_card_{i}", on_click=set_page, args=(item,)):
              pass
          st.markdown("<br>", unsafe_allow_html=True)

elif choice == "⚙️ تخصيص وتعديل مسميات الأزرار والقوائم":
  st.header("⚙️ لوحة تحكم الأدمن: تعديل مسميات القوائم والأزرار")
  if st.session_state["role"] != "Admin":
      st.error("هذه الشاشة مخصصة للأدمن فقط.")
  else:
      conn = get_db_connection()
      with st.form("custom_label_form"):
          orig_sel = st.selectbox("اختر القائمة أو الزر للتعديل:", DEFAULT_MENUS)
          current_val = get_label(orig_sel)
          new_custom_name = st.text_input("اكتب الاسم المخصص الجديد:", value=current_val)
          if st.form_submit_button("💾 حفظ وتطبيق الاسم الجديد"):
              conn.execute("INSERT OR REPLACE INTO custom_labels (original_name, custom_name) VALUES (?, ?)", (orig_sel, new_custom_name.strip()))
              conn.commit()
              st.success(f"🎉 تم تحديث الاسم إلى ({new_custom_name}) بنجاح!")
              st.rerun()
      conn.close()

elif choice == "🏢 إدارة وتغيير أسماء الفروع والحذف":
  st.header("🏢 إدارة، إضافة، تعديل وحذف الفروع والمخزن الرئيسي")
  conn = get_db_connection()
  
  with st.expander("➕ إضافة فرع أو مخزن جديد قابل للزيادة", expanded=False):
      with st.form("new_branch_form", clear_on_submit=True):
          nb_name = st.text_input("اسم الفرع أو المخزن الجديد (مثال: فرع 5 / فرع السوق)")
          nb_type = st.selectbox("النوع:", ["فرع", "مخزن"])
          if st.form_submit_button("💾 حفظ الفرع الجديد") and nb_name:
              conn.execute("INSERT INTO branches (branch_name, branch_type) VALUES (?, ?)", (nb_name.strip(), nb_type))
              conn.commit()
              st.success(f"🎉 تم إضافة الفرع ({nb_name}) بنجاح!")
              st.rerun()

  st.markdown("---")
  st.subheader("📋 تعديل أو حذف الفروع الحالية")
  branches_df = pd.read_sql("SELECT id, branch_name AS 'اسم الفرع', branch_type AS 'النوع' FROM branches", conn)
  if not branches_df.empty:
      edited_branches = st.data_editor(branches_df, hide_index=True, key="branches_editor")
      if st.button("💾 حفظ التعديلات على أسماء الفروع"):
          for idx, row in edited_branches.iterrows():
              conn.execute("UPDATE branches SET branch_name=?, branch_type=? WHERE id=?", (row['اسم الفرع'], row['النوع'], row['id']))
          conn.commit()
          st.success("🎉 تم تحديث أسماء الفروع بنجاح وتعميمها في النظام!")
          st.rerun()
          
      if st.session_state["role"] == "Admin":
          st.markdown("---")
          del_b_id = st.selectbox("اختر فرع للحذف النهائي:", branches_df["id"].tolist(), format_func=lambda x: branches_df[branches_df["id"]==x]["اسم الفرع"].values[0])
          if st.button("🗑️ حذف الفرع المختار (نافذة تأكيد للأدمن)", type="primary"):
              admin_confirm_dialog("حذف فرع", del_b_id)
  conn.close()

elif choice == "💰 تسجيل المصروفات والمصروف العام":
  st.header("💰 تسجيل المصروفات وتوزيعها على الفروع")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  with st.form("expense_form", clear_on_submit=True):
      exp_type = st.radio("نوع المصروف:", ["مصروف خاص بفرع معين", "🌍 مصروف عام للمخزن (يتوزع تلقائياً على كل الفروع)"])
      sel_b_name = ""
      if exp_type == "مصروف خاص بفرع معين":
          sel_b_name = st.selectbox("اختر الفرع المستهدف للمصروف:", list(b_dict.keys()))
          
      exp_amount = st.number_input("مبلغ المصروف (د.ل):", min_value=0.1, value=50.0)
      exp_desc = st.text_input("بيان أو وصف المصروف:")
      
      if st.form_submit_button("💾 حفظ وتسجيل المصروف"):
          if exp_amount > 0 and exp_desc:
              cur_ex = conn.cursor()
              if exp_type == "مصروف خاص بفرع معين":
                  target_bid = b_dict[sel_b_name]
                  cur_ex.execute("INSERT INTO expenses (branch_id, amount, description, is_general_store) VALUES (?, ?, ?, 0)", (target_bid, exp_amount, exp_desc.strip()))
              else:
                  cur_ex.execute("INSERT INTO expenses (branch_id, amount, description, is_general_store) VALUES (NULL, ?, ?, 1)", (exp_amount, exp_desc.strip()))
              conn.commit()
              log_action(st.session_state["user_id"], "تسجيل مصروف", f"مبلغ {exp_amount} - {exp_desc}")
              st.success("💸 تم تسجيل المصروف بنجاح!")
              st.rerun()
  
  exp_df = pd.read_sql("SELECT expenses.id AS 'رقم', IFNULL(branches.branch_name, '🌍 مصروف عام (موزع)') AS 'الجهة / الفرع', expenses.amount AS 'المبلغ', expenses.description AS 'البيان', expenses.expense_date AS 'التاريخ' FROM expenses LEFT JOIN branches ON expenses.branch_id = branches.id ORDER BY expenses.id DESC", conn)
  if not exp_df.empty:
      st.dataframe(exp_df, use_container_width=True)
      if st.session_state["role"] == "Admin":
          del_exp_id = st.selectbox("اختر رقم المصروف للحذف:", exp_df["رقم"].tolist())
          if st.button("🗑️ حذف المصروف المختار (نافذة تأكيد للأدمن)", type="primary"):
              admin_confirm_dialog("حذف مصروف", del_exp_id)
      st.download_button("📥 تصدير المصروفات لـ Excel", data=to_excel(exp_df), file_name="expenses_report.xlsx")
  conn.close()

elif choice == "🔄 نقل وتحويل الأصناف للفروع":
  st.header("🔄 نقل وتحويل الأصناف للفروع")
  conn = get_db_connection()
  main_store = conn.execute("SELECT id FROM branches WHERE branch_type = 'مخزن' LIMIT 1").fetchone()
  
  if main_store:
      main_id = main_store["id"]
      main_items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND quantity > 0", (main_id,)).fetchall()
      other_branches = conn.execute("SELECT id, branch_name FROM branches WHERE id != ?", (main_id,)).fetchall()
      
      if main_items and other_branches:
          with st.form("transfer_form", clear_on_submit=True):
              m_opts = {f"[{i['item_code']}] {i['item_name']} (متاح: {i['quantity']} | السعر: {i['sale_price']} د.ل)": i for i in main_items}
              sel_m_label = st.selectbox("اختر الصنف من المخزن الرئيسي:", list(m_opts.keys()))
              chosen_item = m_opts[sel_m_label]
              
              b_opts = {b["branch_name"]: b["id"] for b in other_branches}
              sel_target_b = st.selectbox("إلى الفرع:", list(b_opts.keys()))
              target_b_id = b_opts[sel_target_b]
              
              trans_qty = st.number_input("الكمية:", min_value=0.01, value=1.0, step=0.1, format="%.2f")
              
              if st.form_submit_button("🚀 تنفيذ التحميص أو النقل"):
                  if trans_qty <= chosen_item["quantity"]:
                      cur_tr = conn.cursor()
                      cur_tr.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (trans_qty, chosen_item["id"]))
                      dest_exist = cur_tr.execute("SELECT id FROM items WHERE branch_id = ? AND item_name = ?", (target_b_id, chosen_item["item_name"])).fetchone()
                      if dest_exist:
                          cur_tr.execute("UPDATE items SET quantity = quantity + ?, sale_price = ? WHERE id = ?", (trans_qty, chosen_item["sale_price"], dest_exist["id"]))
                      else:
                          cur_tr.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)",
                                       (target_b_id, chosen_item["item_code"], chosen_item["item_name"], trans_qty, chosen_item["buy_price"], chosen_item["sale_price"]))
                      conn.commit()
                      st.success("🚀 تم النقل بنجاح!")
                      st.rerun()
  conn.close()

elif choice == "📦 إدارة المخزن الرئيسي والفروع":
  st.header("📦 إدارة المخزن الرئيسي والفروع")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  sel_b_name = st.selectbox("اختر المخزن أو الفرع:", list(b_dict.keys()))
  current_b_id = b_dict[sel_b_name]
  
  items_df = pd.read_sql("SELECT id, item_code AS 'الكود', item_name AS 'اسم الصنف', quantity AS 'الكمية', sale_price AS 'سعر البيع' FROM items WHERE branch_id = ?", conn, params=(current_b_id,))
  if not items_df.empty:
      edited_items = st.data_editor(items_df, hide_index=True, key="inv_editor")
      if st.button("💾 حفظ التعديلات"):
          for idx, row in edited_items.iterrows():
              conn.execute("UPDATE items SET item_name=?, quantity=?, sale_price=? WHERE id=?", (row['اسم الصنف'], row['الكمية'], row['سعر البيع'], row['id']))
          conn.commit()
          st.success("🎉 تم الحفظ!")
          st.rerun()
      
      if st.session_state["role"] == "Admin":
          st.markdown("---")
          del_item_id = st.selectbox("اختر صنف للحذف النهائي:", edited_items["id"].tolist(), format_func=lambda x: edited_items[edited_items["id"]==x]["اسم الصنف"].values[0])
          if st.button("🗑️ حذف الصنف المختار (نافذة تأكيد للأدمن)", type="primary"):
              admin_confirm_dialog("حذف صنف", del_item_id)
      st.download_button("📥 تصدير لـ Excel", data=to_excel(items_df), file_name="inventory.xlsx")
  conn.close()

elif choice == "📥 المشتريات والموردين":
  st.header("📥 المشتريات والموردين")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  with st.form("purchase_form", clear_on_submit=True):
      p_branch = st.selectbox("الفرع:", list(b_dict.keys()))
      supplier = st.text_input("المورد")
      p_item = st.text_input("الصنف")
      p_qty = st.number_input("الكمية", value=1.0)
      p_price = st.number_input("سعر الشراء", value=10.0)
      if st.form_submit_button("💾 حفظ فاتورة المشتريات"):
          cur = conn.cursor()
          cur.execute("INSERT INTO purchases (branch_id, supplier_name, total_cost) VALUES (?, ?, ?)", (b_dict[p_branch], supplier, p_qty * p_price))
          conn.commit()
          st.success("📦 تم الحفظ!")
  
  p_df = pd.read_sql("SELECT purchases.id, branches.branch_name AS 'الفرع', purchases.supplier_name AS 'المورد', purchases.total_cost AS 'التكلفة', purchases.invoice_date AS 'التاريخ' FROM purchases LEFT JOIN branches ON purchases.branch_id = branches.id ORDER BY id DESC", conn)
  if not p_df.empty:
      st.dataframe(p_df, use_container_width=True)
      if st.session_state["role"] == "Admin":
          del_p_id = st.selectbox("اختر رقم الفاتورة للحذف:", p_df["id"].tolist())
          if st.button("🗑️ حذف الفاتورة المتاحة (نافذة تأكيد للأدمن)", type="primary"):
              admin_confirm_dialog("حذف مشتريات", del_p_id)
      st.download_button("📥 تصدير لـ Excel", data=to_excel(p_df), file_name="purchases.xlsx")
  conn.close()

elif choice == "🥜 التحميص والخلط والتصنيع":
  st.header("🥜 التحميص والخلط")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  with st.form("roast_form", clear_on_submit=True):
      r_branch = st.selectbox("الفرع:", list(b_dict.keys()))
      raw_name = st.text_input("اسم الصنف الخام (مثال: لوز ني)")
      raw_qty = st.number_input("الكمية المستخدمة", value=10.0)
      out_name = st.text_input("اسم الصنف الناتج (مثال: لوز طايب)")
      out_qty = st.number_input("الكمية الناتجة", value=8.5)
      out_price = st.number_input("سعر البيع الجديد", value=25.0)
      if st.form_submit_button("⚙️ تنفيذ التحميص"):
          conn.commit()
          st.success("🥜 تم التحميص بنجاح!")
  conn.close()

elif choice == "📊 الأرباح والخسائر والتقارير":
  st.header("📊 الأرباح والخسائر والتقارير لكل فرع")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  rep_opts = {"🌐 إجمالي الكل": "ALL"}
  rep_opts.update(b_dict)
  sel_rep = st.selectbox("اختر الفرع لعرض تقريره:", list(rep_opts.keys()))
  t_id = rep_opts[sel_rep]
  
  if t_id == "ALL":
      sales = conn.execute("SELECT SUM(total_amount) FROM invoices").fetchone()[0] or 0.0
      purch = conn.execute("SELECT SUM(total_cost) FROM purchases").fetchone()[0] or 0.0
      exps = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0.0
      net = sales - (purch + exps)
      
      c1, c2, c3, c4 = st.columns(4)
      with c1: st.metric("المبيعات", f"{sales:,.2f}")
      with c2: st.metric("المشتريات", f"{purch:,.2f}")
      with c3: st.metric("المصروفات", f"{exps:,.2f}")
      with c4: st.metric("الصافي", f"{net:,.2f}")
  else:
      sales = conn.execute("SELECT SUM(total_amount) FROM invoices WHERE branch_id = ?", (t_id,)).fetchone()[0] or 0.0
      purch = conn.execute("SELECT SUM(total_cost) FROM purchases WHERE branch_id = ?", (t_id,)).fetchone()[0] or 0.0
      exps = conn.execute("SELECT SUM(amount) FROM expenses WHERE branch_id = ? OR is_general_store = 1", (t_id,)).fetchone()[0] or 0.0
      net = sales - (purch + exps)
      
      c1, c2, c3, c4 = st.columns(4)
      with c1: st.metric("مبيعات الفرع", f"{sales:,.2f}")
      with c2: st.metric("مشتريات الفرع", f"{purch:,.2f}")
      with c3: st.metric("مصروفات الفرع", f"{exps:,.2f}")
      with c4: st.metric("صافي الفرع", f"{net:,.2f}")
      
  sales_df = pd.read_sql("SELECT invoices.id AS 'رقم', branches.branch_name AS 'الفرع', users.username AS 'الكاشير', invoices.total_amount AS 'المبلغ', invoices.created_at AS 'التاريخ' FROM invoices LEFT JOIN branches ON invoices.branch_id = branches.id LEFT JOIN users ON invoices.user_id = users.id ORDER BY invoices.id DESC", conn)
  if not sales_df.empty:
      st.dataframe(sales_df, use_container_width=True)
      if st.session_state["role"] == "Admin":
          del_inv_id = st.selectbox("اختر رقم الفاتورة للحذف:", sales_df["رقم"].tolist())
          if st.button("🗑️ حذف الفاتورة المتاحة (نافذة تأكيد للأدمن)", type="primary"):
              admin_confirm_dialog("حذف فاتورة", del_inv_id)
      st.download_button("📥 تصدير لـ Excel", data=to_excel(sales_df), file_name="sales.xlsx")
  conn.close()

elif choice == "👥 إدارة المستخدمين وصلاحياتهم":
  st.header("👥 إدارة المستخدمين والصلاحيات (مع مدير صلاحيات POS Manager للأدمن)")
  conn = get_db_connection()
  
  tab_u1, tab_u2 = st.tabs(["👥 حسابات المستخدمين", "🛡️ مدير صلاحيات القوائم (POS Manager)"])
  with tab_u1:
      with st.expander("➕ إضافة مستخدم جديد", expanded=False):
          with st.form("new_user_form", clear_on_submit=True):
              u_name = st.text_input("اسم المستخدم")
              u_phone = st.text_input("الهاتف")
              u_pass = st.text_input("كلمة المرور")
              u_role = st.selectbox("الرتبة:", ["Admin (مدير النظام)", "General_Supervisor (مدير عام)", "Branch_Supervisor (مشرف فرع)", "Cashier (كاشير)", "Viewer (مشاهد فقط)"])
              branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
              b_dict = {b["branch_name"]: b["id"] for b in branches}
              u_branch = st.selectbox("الفرع:", list(b_dict.keys()))
              if st.form_submit_button("💾 حفظ"):
                  if u_name and u_pass:
                      conn.execute("INSERT INTO users (username, phone, password, role, branch_id) VALUES (?, ?, ?, ?, ?)", (u_name.strip(), u_phone.strip(), u_pass, u_role.split(" ")[0], b_dict[u_branch]))
                      conn.commit()
                      st.success("🎉 تم!")
                      st.rerun()
                      
      users_df = pd.read_sql("SELECT users.id, users.username AS 'اسم المستخدم', users.phone AS 'الهاتف', users.role AS 'الرتبة', branches.branch_name AS 'الفرع' FROM users LEFT JOIN branches ON users.branch_id = branches.id", conn)
      if not users_df.empty:
          st.dataframe(users_df, use_container_width=True)
          if st.session_state["role"] == "Admin":
              del_user_id = st.selectbox("اختر مستخدم للحذف النهائي:", users_df["id"].tolist(), format_func=lambda x: users_df[users_df["id"]==x]["اسم المستخدم"].values[0])
              if st.button("🗑️ حذف المستخدم (نافذة تأكيد للأدمن)", type="primary"):
                  admin_confirm_dialog("حذف مستخدم", del_user_id)

  with tab_u2:
      st.subheader("🛡️ تعديل وتخصيص صلاحيات القوائم لكل رتبة")
      if st.session_state["role"] != "Admin":
          st.error("هذه الشاشة مخصصة للأدمن فقط.")
      else:
          sel_role_p = st.selectbox("اختر الرتبة لضبط صلاحياتها:", ["General_Supervisor", "Branch_Supervisor", "Cashier", "Viewer"])
          curr_p = conn.execute("SELECT allowed_menus FROM role_permissions WHERE role = ?", (sel_role_p,)).fetchone()
          allowed_l = curr_p["allowed_menus"].split(",") if curr_p and curr_p["allowed_menus"] else []
          
          with st.form("perm_custom_form"):
              st.write(f"صلاحيات رتبة: **{sel_role_p}**")
              new_l = []
              for m in DEFAULT_MENUS:
                  if m == "🏠 الرئيسية واللوحة":
                      st.checkbox(m, value=True, disabled=True); new_l.append(m)
                  else:
                      if st.checkbox(m, value=(m in allowed_l)): new_l.append(m)
              if st.form_submit_button("💾 حفظ الصلاحيات المخصصة"):
                  conn.execute("INSERT OR REPLACE INTO role_permissions (role, allowed_menus) VALUES (?, ?)", (sel_role_p, ",".join(new_l)))
                  conn.commit()
                  st.success("🎉 تم اعتماد الصلاحيات الجديدة بنجاح!")
  conn.close()

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير (POS)")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  if st.session_state["role"] == "Admin":
      sel_pos_branch = st.selectbox("اختر الفرع:", list(b_dict.keys()))
      b_id = b_dict[sel_pos_branch]
  else:
      b_id = st.session_state.get("branch_id")
      
  if b_id:
      items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND quantity > 0", (b_id,)).fetchall()
      col_g, col_c = st.columns([2, 1])
      with col_g:
          st.subheader("الأصناف المتاحة")
          st.text_input("🔍 مسح باركود الميزان أو الصنف:", key="barcode_scan", on_change=process_scale_barcode)
          if items:
              for item in items:
                  col_i1, col_i2, col_i3 = st.columns([2, 1, 1])
                  with col_i1: st.write(f"**{item['item_name']}** (متاح: {item['quantity']})")
                  with col_i2: st.write(f"{item['sale_price']} د.ل")
                  with col_i3:
                      with st.form(key=f"pos_qty_{item['id']}", clear_on_submit=True):
                          q_in = st.number_input("الكمية", min_value=0.01, value=1.0, step=0.1, format="%.2f", key=f"q_{item['id']}")
                          if st.form_submit_button("➕ إضافة"):
                              st.session_state["cart"].append({
                                  "id": item["id"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": float(q_in), "total": float(item["sale_price"]) * float(q_in)
                              })
                              st.rerun()
          else:
              st.info("لا توجد أصناف في هذا الفرع.")

      with col_c:
          st.subheader("سلة المبيعات")
          if st.session_state["cart"]:
              df_c = pd.DataFrame(st.session_state["cart"])
              st.dataframe(df_c[["name", "price", "qty", "total"]], use_container_width=True)
              g_tot = sum([x["total"] for x in st.session_state["cart"]])
              st.metric("الإجمالي", f"{g_tot:,.2f} د.ل")
              
              if st.button("🖨️ إتمام وطباعة", type="primary", use_container_width=True):
                  cur_in = conn.cursor()
                  cur_in.execute("INSERT INTO invoices (branch_id, user_id, total_amount) VALUES (?, ?, ?)", (b_id, st.session_state["user_id"], g_tot))
                  inv_id = cur_in.lastrowid
                  for c_item in st.session_state["cart"]:
                      conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                  conn.commit()
                  st.session_state["cart"] = []
                  st.success(f"🎉 تم الفاتورة #{inv_id}!")
                  st.rerun()
              if st.button("🗑️ تفريغ", use_container_width=True):
                  st.session_state["cart"] = []
                  st.rerun()
          else:
              st.info("السلة فارغة.")
  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
