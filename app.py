import os
import re
import io
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(
    page_title="مجموعة أبو زيد - نظام المحامص والمخازن الذكي",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- تنسيق الألوان والخطوط العصرية والاحترافية ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Tajawal', sans-serif; color: #1e293b; }
    .main { background-color: #f1f5f9; }
    
    div.stButton > button { 
        border-radius: 8px; 
        font-weight: 700; 
        transition: all 0.3s ease; 
        height: 45px; 
        background: linear-gradient(135deg, #0284c7, #0369a1);
        color: white;
        border: none;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    div.stButton > button:hover {
        background: linear-gradient(135deg, #0369a1, #075985);
        transform: translateY(-2px);
    }
    
    [data-testid="stSidebar"] {
        background-color: #0f172a;
    }
    [data-testid="stSidebar"] .stButton>button {
        background-color: #1e293b; color: #f8fafc; border: 1px solid #334155;
        border-radius: 10px; padding: 10px 15px; text-align: right; font-weight: bold;
        transition: all 0.3s ease; margin-bottom: 5px; font-size: 15px; height: auto;
    }
    [data-testid="stSidebar"] .stButton>button:hover { 
        background-color: #0284c7; color: white; border-color: #0284c7; transform: translateX(-5px); 
    }
    .card { padding: 15px; border-radius: 12px; color: white; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 10px; }
    .pos-item-card { background: white; padding: 12px; border-radius: 10px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; margin-bottom: 8px; }
    </style>
""", unsafe_allow_html=True)

if not os.path.exists("item_images"): os.makedirs("item_images")

DEFAULT_MENUS = [
    "🏠 الرئيسية واللوحة",
    "🛒 نقطة البيع (POS)",
    "⭐ لوحة الأصناف المفضلة (1-20)",
    "📦 إدارة المخزن والفروع وتعديل الأسعار",
    "➕ إضافة فائض أو مرتجع وتوالف",
    "🔄 نقل وتحويل وتزويد الفروع (سلة متعددة الأصناف)",
    "🏢 إدارة وتغيير أسماء الفروع والحذف",
    "📁 استيراد وتحديث الأصناف من Excel",
    "💰 تسجيل المصروفات والمصروف العام",
    "📥 المشتريات والموردين (فواتير متعددة الأصناف)",
    "⚙️ إدارة الجرد والعمليات السنوية والتصفير",
    "🥜 التحميص والخلط والمكسرات المشكلة (متعدد الأصناف)",
    "📊 مركز التقارير والإدارة الشاملة (مع التصدير وحركة الفروع)",
    "👥 إدارة المستخدمين وصلاحياتهم الفردية",
    "⚙️ تخصيص وتعديل مسميات الأزرار"
]

def initialize_database():
  conn = sqlite3.connect("abu_zaid_new_system.db", timeout=10)
  conn.execute("PRAGMA foreign_keys = ON")
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
          allowed_branches TEXT DEFAULT 'ALL',
          custom_permissions TEXT DEFAULT '',
          is_active INTEGER DEFAULT 1,
          FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE SET NULL
      )
  """)

  try: cursor.execute("ALTER TABLE users ADD COLUMN allowed_branches TEXT DEFAULT 'ALL'")
  except: pass
  try: cursor.execute("ALTER TABLE users ADD COLUMN custom_permissions TEXT DEFAULT ''")
  except: pass

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
          expiry_date TEXT DEFAULT '',
          no_expiry INTEGER DEFAULT 0,
          favorite_rank INTEGER DEFAULT 0,
          FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
      )
  """)

  try: cursor.execute("ALTER TABLE items ADD COLUMN avg_cost REAL DEFAULT 0.0")
  except: pass
  try: cursor.execute("ALTER TABLE items ADD COLUMN expiry_date TEXT DEFAULT ''")
  except: pass
  try: cursor.execute("ALTER TABLE items ADD COLUMN no_expiry INTEGER DEFAULT 0")
  except: pass
  try: cursor.execute("ALTER TABLE items ADD COLUMN favorite_rank INTEGER DEFAULT 0")
  except: pass

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS suppliers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          supplier_name TEXT UNIQUE NOT NULL,
          phone TEXT,
          balance REAL DEFAULT 0.0
      )
  """)

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
  
  try: cursor.execute("ALTER TABLE purchases ADD COLUMN invoice_number TEXT")
  except: pass

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS transfer_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          from_branch_id INTEGER,
          to_branch_id INTEGER,
          transfer_type TEXT,
          items_details TEXT,
          status TEXT DEFAULT 'مكتملة',
          transfer_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (from_branch_id) REFERENCES branches(id) ON DELETE CASCADE,
          FOREIGN KEY (to_branch_id) REFERENCES branches(id) ON DELETE CASCADE
      )
  """)

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS expenses (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          branch_id INTEGER,
          amount REAL NOT NULL,
          description TEXT NOT NULL,
          is_general_store INTEGER DEFAULT 0,
          expense_date TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
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
          FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
      )
  """)

  cursor.execute("""
      CREATE TABLE IF NOT EXISTS negative_sales_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          branch_id INTEGER,
          user_id INTEGER,
          item_name TEXT,
          sale_qty REAL,
          log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
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
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Branch_Supervisor', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),⭐ لوحة الأصناف المفضلة (1-20),📦 إدارة المخزن والفروع وتعديل الأسعار,📥 المشتريات والموردين (فواتير متعددة الأصناف),📊 مركز التقارير والإدارة الشاملة (مع التصدير وحركة الفروع)')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Cashier', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),⭐ لوحة الأصناف المفضلة (1-20)')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Viewer', '🏠 الرئيسية واللوحة,📊 مركز التقارير والإدارة الشاملة (مع التصدير وحركة الفروع)')")
  except: pass

  branch_count = cursor.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
  if branch_count == 0:
      default_branches = [("المخزن الرئيسي", "مخزن"), ("فرع 1", "فرع"), ("فرع 2", "فرع"), ("فرع 3", "فرع"), ("فرع 4", "فرع")]
      for b_name, b_type in default_branches:
          cursor.execute("INSERT OR IGNORE INTO branches (branch_name, branch_type) VALUES (?, ?)", (b_name, b_type))

  admin_chk = cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin' AND is_active = 1").fetchone()[0]
  if admin_chk == 0:
      cursor.execute("INSERT OR IGNORE INTO users (username, phone, password, role, allowed_branches, is_active) VALUES ('admin', '0910000000', 'admin', 'Admin', 'ALL', 1)")

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

def check_user_permission(menu_name):
    role = st.session_state.get("role", "")
    if role == "Admin": return True
    user_id = st.session_state.get("user_id")
    if not user_id: return False
    conn = get_db_connection()
    user_row = conn.execute("SELECT custom_permissions FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if user_row and user_row["custom_permissions"]:
        custom_perms = user_row["custom_permissions"].split(",")
        if menu_name in custom_perms: return True
    
    allowed = st.session_state.get("allowed_menus", [])
    return menu_name in allowed

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
if "allowed_branches" not in st.session_state: st.session_state["allowed_branches"] = "ALL"
if "cart" not in st.session_state: st.session_state["cart"] = []
if "purch_cart" not in st.session_state: st.session_state["purch_cart"] = []
if "transfer_cart" not in st.session_state: st.session_state["transfer_cart"] = []
if "page" not in st.session_state: st.session_state["page"] = "🏠 الرئيسية واللوحة"
if "barcode_scan" not in st.session_state: st.session_state["barcode_scan"] = ""
if "show_welcome_dialog" not in st.session_state: st.session_state["show_welcome_dialog"] = False
if "welcome_branch_name" not in st.session_state: st.session_state["welcome_branch_name"] = ""

def set_page(page_name): st.session_state["page"] = page_name

@st.dialog("🌟 ترحيب النظام")
def welcome_user_dialog():
    st.success(f"**أهلاً بك يا {st.session_state['username']} في فروعك المصرح لك بها! نتمنى لك يوم سعيد مبارك ☕✨**")
    if st.button("OK (موافق ودخول للنظام)", use_container_width=True, type="primary"):
        st.session_state["show_welcome_dialog"] = False
        st.rerun()

@st.dialog("🔔 تنبيه وإخطار النظام")
def alert_ok_dialog(message):
    st.write(message)
    if st.button("OK (موافق)", use_container_width=True, type="primary"):
        st.rerun()

@st.dialog("🔒 تأكيد كلمة سر الأدمن المطلوبة")
def admin_confirm_dialog(action_type, target_id, target_name=""):
    st.warning(f"⚠️ تحذير أمني: أنت على وشك تنفيذ عملية ({action_type}). يرجى إدخال كلمة سر الأدمن للمتابعة:")
    admin_pass = st.text_input("كلمة سر الأدمن:", type="password", key="diag_pass_input")
    
    if st.button("✅ تأكيد التنفيذ وتبرير العملية", use_container_width=True, type="primary"):
        if verify_admin_password(admin_pass):
            conn = get_db_connection()
            if action_type == "حذف فرع":
                conn.execute("DELETE FROM branches WHERE id = ?", (target_id,))
            elif action_type == "حذف صنف":
                conn.execute("DELETE FROM items WHERE id = ?", (target_id,))
            elif action_type == "محو كافة الأصناف":
                conn.execute("DELETE FROM items WHERE branch_id = ?" if target_id != "ALL" else "DELETE FROM items", (target_id,) if target_id != "ALL" else ())
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
            log_action(st.session_state["user_id"], f"تنفيذ آمن ({action_type})", f"تم تنفيذ العملية بنجاح")
            st.success(f"🗑️ تمت عملية ({action_type}) بنجاح!")
            if st.button("OK (موافق)"):
                st.rerun()
        else:
            st.error("❌ كلمة سر الأدمن غير صحيحة!")

@st.dialog("💳 شاشة إتمام الدفع (الخزينة)")
def checkout_payment_dialog(b_id, g_tot):
    st.subheader(f"إجمالي الفاتورة المطلوب: {g_tot:,.2f} د.ل")
    pay_method = st.selectbox("نوع الدفع:", ["كاش (نقدي)", "شبكة / بطاقة", "آجل"])
    paid_amount = st.number_input("المبلغ المدفوع من الزبون (د.ل):", min_value=0.0, value=0.0, step=0.5, format="%.2f")
    
    change_due = paid_amount - g_tot
    if change_due >= 0:
        st.success(f"💵 الباقي المستحق للزبون: **{change_due:,.2f} د.ل**")
    else:
        st.error(f"⚠️ المبلغ المدفوع غير كافٍ! العجز: **{abs(change_due):,.2f} د.ل**")
    
    if st.button("🖨️ تأكيد الإصدار وطباعة الفاتورة النهائية", type="primary", use_container_width=True):
        if paid_amount >= g_tot or pay_method == "آجل":
            conn = get_db_connection()
            target_inv_branch = b_id if b_id != "ALL" else conn.execute("SELECT id FROM branches LIMIT 1").fetchone()["id"]
            
            can_proceed = True
            for c_item in st.session_state["cart"]:
                if c_item["id"] != 99999:
                    db_it = conn.execute("SELECT quantity FROM items WHERE id = ?", (c_item["id"],)).fetchone()
                    if db_it and float(db_it["quantity"]) < c_item["qty"]:
                        can_proceed = False
                        st.warning(f"⚠️ الصنف ({c_item['name']}) الكمية المتوفرة لا تكفي!")

            if can_proceed:
                cur_in = conn.cursor()
                cur_in.execute("INSERT INTO invoices (branch_id, user_id, total_amount, payment_method) VALUES (?, ?, ?, ?)", (target_inv_branch, st.session_state["user_id"], g_tot, pay_method))
                inv_id = cur_in.lastrowid
                for c_item in st.session_state["cart"]:
                    if c_item["id"] != 99999:
                        conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                conn.commit()
                conn.close()
                st.session_state["cart"] = []
                st.success(f"🎉 تم إصدار الفاتورة رقم #{inv_id} بنجاح!")
                if st.button("OK (موافق)"):
                    st.rerun()
            else:
                conn.close()
        else:
            st.warning("⚠️ المبلغ المدفوع أقل من إجمالي الفاتورة.")

def process_scale_barcode():
    code = st.session_state.barcode_scan.strip()
    if code:
        b_id = st.session_state.get("branch_id")
        conn = get_db_connection()
        item = None
        if code.startswith("20") and len(code) >= 12:
            item_code = code[2:7]
            scale_value = float(code[7:]) / 100.0
            if b_id == "ALL":
                item = conn.execute("SELECT * FROM items WHERE item_code = ? LIMIT 1", (item_code,)).fetchone()
            else:
                item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (item_code, b_id)).fetchone()
            if item:
                unit_price = float(item["sale_price"])
                calculated_qty = scale_value / unit_price if unit_price > 0 else 1.0
                if float(item["quantity"]) <= 0:
                    conn.execute("INSERT INTO negative_sales_logs (branch_id, user_id, item_name, sale_qty) VALUES (?, ?, ?, ?)", 
                                 (item["branch_id"], st.session_state["user_id"], item["item_name"], calculated_qty))
                    conn.commit()
                st.session_state["cart"].append({
                    "id": item["id"], "code": item["item_code"], "name": item["item_name"],
                    "price": unit_price, "qty": float(calculated_qty), "total": float(scale_value)
                })
        if not item:
            if b_id == "ALL":
                item = conn.execute("SELECT * FROM items WHERE item_code = ? LIMIT 1", (code,)).fetchone()
            else:
                item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
            if item:
                if float(item["quantity"]) <= 0:
                    conn.execute("INSERT INTO negative_sales_logs (branch_id, user_id, item_name, sale_qty) VALUES (?, ?, ?, ?)", 
                                 (item["branch_id"], st.session_state["user_id"], item["item_name"], 1.0))
                    conn.commit()
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
              st.session_state["allowed_branches"] = user["allowed_branches"] if user["allowed_branches"] else "ALL"
              
              st.session_state["welcome_branch_name"] = "متعدد الفروع / كافة الفروع"
              st.session_state["show_welcome_dialog"] = True
              
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

if st.session_state.get("show_welcome_dialog", False):
    welcome_user_dialog()

# --- القائمة الجانبية والصلاحيات ---
st.sidebar.markdown("<h2 style='text-align: center;'>🥜 محامص أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"**👤 {st.session_state['username']} | `{st.session_state['role']}`**")
st.sidebar.markdown("---")

current_allowed = DEFAULT_MENUS if st.session_state["role"] == "Admin" else st.session_state.get("allowed_menus", DEFAULT_MENUS)
menu_to_show = [m for m in DEFAULT_MENUS if check_user_permission(m)]

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
    "⭐ لوحة الأصناف المفضلة (1-20)": {"icon": "⭐", "color": "linear-gradient(135deg, #e11d48, #be123c)", "desc": "تعديل واختيار الأصناف المفضلة للكاشير"},
    "📦 إدارة المخزن والفروع وتعديل الأسعار": {"icon": "📦", "color": "linear-gradient(135deg, #3b82f6, #1d4ed8)", "desc": "جرد وإدارة وتعديل أسعار الفروع"},
    "➕ إضافة فائض أو مرتجع وتوالف": {"icon": "➕", "color": "linear-gradient(135deg, #10b981, #047857)", "desc": "إضافة فائض أو مرتجع وتوالف للأصناف"},
    "🔄 نقل وتحويل وتزويد الفروع (مع الأرشفة)": {"icon": "🔄", "color": "linear-gradient(135deg, #8b5cf6, #6d28d9)", "desc": "تزويد الفروع والتحويلات بسلة أصناف متعددة"},
    "📊 مركز التقارير والإدارة الشاملة (مع التصدير وحركة الفروع)": {"icon": "📊", "color": "linear-gradient(135deg, #6366f1, #4338ca)", "desc": "المركّز الموحد للتقارير والأرباح والتصدير لـ Excel"}
}

# --- محتوى الصفحات ---
if choice == "🏠 الرئيسية واللوحة":
  st.title("🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية")
  cols = st.columns(3)
  for i, (item, data) in enumerate(dashboard_cards.items()):
      if check_user_permission(item):
          with cols[i % 3]:
              c_title = get_label(item)
              st.markdown(f'''<div style="background: {data['color']}; padding: 25px 15px; border-radius: 16px; color: white; text-align: center; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); margin-bottom: 10px; min-height: 150px;"><h1 style="margin:0; font-size: 45px;">{data['icon']}</h1><h3 style="margin: 10px 0 5px 0;">{c_title.split(" ", 1)[-1] if " " in c_title else c_title}</h3><p style="margin:0; font-size: 14px; opacity: 0.9;">{data['desc']}</p></div>''', unsafe_allow_html=True)
              if st.button(f"دخول ➔", key=f"btn_card_{i}", on_click=set_page, args=(item,)):
                  pass
              st.markdown("<br>", unsafe_allow_html=True)

elif choice == "⭐ لوحة الأصناف المفضلة (1-20)":
  st.header("⭐ إعداد وتعديل لوحة الأصناف المفضلة (من 1 إلى 20 أمام الكاشير)")
  if st.session_state["role"] not in ["Admin", "General_Supervisor"]:
      st.error("🔒 هذه الشاشة مخصصة للأدمن والمدير العام فقط لتحديد أصناف الكاشير المفضلة.")
  else:
      conn = get_db_connection()
      branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict = {b["branch_name"]: b["id"] for b in branches}
      sel_b_name = st.selectbox("اختر الفرع لتعديل أزراره المفضلة:", list(b_dict.keys()))
      cur_b_id = b_dict[sel_b_name]
      
      items_fav = pd.read_sql("SELECT id, item_code AS 'الكود', item_name AS 'اسم الصنف', favorite_rank AS 'الرقم المفضل (1 إلى 20 أو 0 للاستبعاد)' FROM items WHERE branch_id = ?", conn, params=(cur_b_id,))
      if not items_fav.empty:
          st.info("💡 حدد رقم الصنف المفضل من 1 إلى 20 ليظهر للكاشير في شاشة المبيعات، وضع 0 للأصناف التي لا تظهر.")
          edited_fav = st.data_editor(items_fav, hide_index=True, key="fav_editor")
          if st.button("💾 حفظ أرقام الترتيب المفضل"):
              for idx, row in edited_fav.iterrows():
                  conn.execute("UPDATE items SET favorite_rank = ? WHERE id = ?", (row['الرقم المفضل (1 إلى 20 أو 0 للاستبعاد)'], row['id']))
              conn.commit()
              st.success("🎉 تم تحديث لوحة الأصناف المفضلة بنجاح للكاشير!")
      conn.close()

elif choice == "⚙️ تخصيص وتعديل مسميات الأزرار":
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
      conn.close()

elif choice == "⚙️ إدارة الجرد والعمليات السنوية والتصفير":
  st.header("⚙️ إدارة الجرد والعمليات السنوية والتصفير الشامل للمدير والأدمن")
  if st.session_state["role"] not in ["Admin", "General_Supervisor"]:
      st.error("صلاحية إدارة الجرد السنوي والتصفير مخصصة للإدارة العليا والأدمن فقط.")
  else:
      conn = get_db_connection()
      branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict = {b["branch_name"]: b["id"] for b in branches}
      
      with st.form("annual_inventory_form"):
          target_scope = st.selectbox("تحديد النطاق:", ["🌐 كل الفروع والمخازن (الكل)", "🏢 فرع أو مخزن معروض محدد"] + list(b_dict.keys()))
          
          st.markdown("---")
          opt_sales = st.checkbox("تصفير المبيعات والفواتير (إعادة تعيين أرقام الفواتير إلى INV-0001)")
          opt_purch = st.checkbox("تصفير حركات وسجلات المشتريات (مع الاحتفاظ بقاعدة أسماء وبيانات المورد الأساسية)")
          opt_stock = st.checkbox("تصفير كميات مخزون الأصناف بالكامل إلى الصفر")
          opt_prices = st.checkbox("إعادة ضبط أسعار البيع والشراء الحركية إلى الصفر")
          
          admin_pass_inv = st.text_input("🔒 كلمة سر الأدمن لتأكيد عملية التصفير السنوي:", type="password")
          
          if st.form_submit_button("🚨 تنفيذ عمليات التصفير الحركي للجرد", type="primary"):
              if verify_admin_password(admin_pass_inv):
                  cur_inv = conn.cursor()
                  scope_id = "ALL" if target_scope == "🌐 كل الفروع والمخازن (الكل)" else (b_dict.get(target_scope, "ALL") if target_scope != "🏢 فرع أو مخزن معروض محدد" else "ALL")
                  
                  if opt_sales:
                      if scope_id == "ALL": cur_inv.execute("DELETE FROM invoices")
                      else: cur_inv.execute("DELETE FROM invoices WHERE branch_id = ?", (scope_id,))
                  if opt_purch:
                      if scope_id == "ALL": cur_inv.execute("DELETE FROM purchases")
                      else: cur_inv.execute("DELETE FROM purchases WHERE branch_id = ?", (scope_id,))
                  if opt_stock:
                      if scope_id == "ALL": cur_inv.execute("UPDATE items SET quantity = 0")
                      else: cur_inv.execute("UPDATE items SET quantity = 0 WHERE branch_id = ?", (scope_id,))
                  if opt_prices:
                      if scope_id == "ALL": cur_inv.execute("UPDATE items SET sale_price = 0, buy_price = 0")
                      else: cur_inv.execute("UPDATE items SET sale_price = 0, buy_price = 0 WHERE branch_id = ?", (scope_id,))
                  
                  conn.commit()
                  st.success("🎉 تمت عملية الجرد والتصفير الحركي السنوي بنجاح تامة!")
              else:
                  st.error("❌ كلمة سر الأدمن غير صحيحة!")
      conn.close()

elif choice == "📁 استيراد وتحديث الأصناف من Excel":
  st.header("📁 استيراد وتحديث الأصناف عبر ملف Excel")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  with st.form("excel_import_seq_form"):
      sel_target_branch = st.selectbox("اختر الفرع أو المخزن المستهدف (أو تعميم للكل):", ["🌐 تعميم على كافة الفروع والمخازن دفعة واحدة"] + list(b_dict.keys()))
      no_expiry_flag = st.checkbox("منتج لا تنتهي صلاحيته مستمرة أو متحركة (بدون تاريخ انتهاء)")
      expiry_date_in = st.text_input("تاريخ الصلاحية الافتراضي (YYYY-MM-DD):", value="")
      up_excel = st.file_uploader("اختر ملف الإكسيل (.xlsx)", type=["xlsx", "xls"])
      
      if st.form_submit_button("📥 تنفيذ استيراد وتحديث الأصناف"):
          if up_excel:
              try:
                  df_exc = pd.read_excel(up_excel, usecols=[0, 1, 2, 3, 4, 5])
                  cur_ex = conn.cursor()
                  count_imp = 0
                  target_ids = list(b_dict.values()) if sel_target_branch == "🌐 تعميم على كافة الفروع والمخازن دفعة واحدة" else [b_dict[sel_target_branch]]
                  
                  for idx, row in df_exc.iterrows():
                      if row.isna().all(): continue
                      code_val, name_val = row.iloc[0], row.iloc[1]
                      if pd.isna(code_val) or pd.isna(name_val): continue
                      code = str(code_val).strip()
                      name = str(name_val).strip()
                      if code.lower() in ["nan", "null", "item", "كود الصنف", "كود"] or name.lower() in ["nan", "null", "item", "اسم الصنف"]: continue
                      if not code or code.lower() == 'nan': continue
                      
                      try: qty = float(row.iloc[2]) if pd.notna(row.iloc[2]) else 0.0
                      except: qty = 0.0
                      try: b_pr = float(row.iloc[3]) if pd.notna(row.iloc[3]) else 0.0
                      except: b_pr = 0.0
                      try: s_pr = float(row.iloc[4]) if pd.notna(row.iloc[4]) else 0.0
                      except: s_pr = 0.0
                      
                      row_exp_date = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else expiry_date_in
                      if row_exp_date.lower() == 'nan' or row_exp_date == '0': row_exp_date = ''

                      for tid in target_ids:
                          exist_item = cur_ex.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (tid, code)).fetchone()
                          if exist_item:
                              cur_ex.execute("UPDATE items SET quantity = ?, buy_price = ?, sale_price = ?, expiry_date = ?, no_expiry = ? WHERE id = ?",
                                             (qty, b_pr, s_pr, row_exp_date, 1 if no_expiry_flag else 0, exist_item['id']))
                          else:
                              cur_ex.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)", 
                                             (tid, code, name, qty, b_pr, s_pr, b_pr, row_exp_date, 1 if no_expiry_flag else 0))
                      count_imp += 1
                  conn.commit()
                  st.success(f"🎉 تمت عملية استيراد وتحديث ({count_imp}) صنف بنجاح تام وبدون أي أخطاء!")
              except Exception as e:
                  st.error(f"حدث خطأ أثناء قراءة الملف: {e}")
  conn.close()

elif choice == "🏢 إدارة وتغيير أسماء الفروع والحذف":
  st.header("🏢 إدارة، إضافة، تعديل وحذف الفروع والمخزن الرئيسي")
  conn = get_db_connection()
  
  with st.expander("➕ إضافة فرع أو مخزن جديد قابل للزيادة", expanded=False):
      with st.form("new_branch_form", clear_on_submit=True):
          nb_name = st.text_input("اسم الفرع أو المخزن الجديد (مثال: فرع 5 / فرع السوق)")
          nb_type = st.selectbox("النوع:", ["فرع", "مخزن"])
          if st.form_submit_button("💾 حفظ الفرع الجديد") and nb_name:
              try:
                  conn.execute("INSERT INTO branches (branch_name, branch_type) VALUES (?, ?)", (nb_name.strip(), nb_type))
                  conn.commit()
                  st.success(f"🎉 تم إضافة الفرع ({nb_name}) بنجاح!")
                  st.rerun()
              except sqlite3.IntegrityError:
                  st.error("⚠️ خطأ: اسم الفرع موجود مسبقاً، يرجى اختيار اسم فريد.")

  st.markdown("---")
  st.subheader("📋 تعديل أو حذف الفروع الحالية")
  branches_list = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
  
  if branches_list:
      for b in branches_list:
          with st.form(f"branch_edit_form_{b['id']}"):
              col_be1, col_be2, col_be3 = st.columns([2, 1, 1])
              with col_be1:
                  new_b_name = st.text_input("اسم الفرع:", value=b["branch_name"], key=f"b_name_{b['id']}")
              with col_be2:
                  type_idx = 0 if b["branch_type"]=="فرع" else 1
                  new_b_type = st.selectbox("النوع:", ["فرع", "مخزن"], index=type_idx, key=f"b_type_{b['id']}")
              with col_be3:
                  st.markdown("<br>", unsafe_allow_html=True)
                  up_btn = st.form_submit_button("💾 حفظ التعديل")
              
              if up_btn:
                  try:
                      conn.execute("UPDATE branches SET branch_name=?, branch_type=? WHERE id=?", (new_b_name.strip(), new_b_type, b['id']))
                      conn.commit()
                      st.success(f"🎉 تم تحديث الفرع ({new_b_name}) بنجاح!")
                      st.rerun()
                  except sqlite3.IntegrityError:
                      st.error("⚠️ خطأ: اسم الفرع موجود مسبقاً!")

      if st.session_state["role"] == "Admin":
          st.markdown("---")
          with st.form("del_branch_form_clean"):
              del_b_id = st.selectbox("اختر فرع للحذف النهائي:", [br["id"] for br in branches_list], format_func=lambda x: [br["branch_name"] for br in branches_list if br["id"]==x][0])
              admin_pass_db = st.text_input("🔒 كلمة سر الأدمن لتأكيد الحذف:", type="password")
              if st.form_submit_button("🗑️ حذف الفرع المختار", type="primary"):
                  if verify_admin_password(admin_pass_db):
                      conn.execute("DELETE FROM branches WHERE id = ?", (del_b_id,))
                      conn.commit()
                      st.success("🗑️ تم حذف الفرع بنجاح!")
                      st.rerun()
                  else:
                      st.error("⚠️ كلمة سر الأدمن غير صحيحة!")
  conn.close()

elif choice == "💰 تسجيل المصروفات والمصروف العام":
  st.header("💰 تسجيل المصروفات وتوزيعها على الفروع (مع تحديد التاريخ المخصص والتصدير)")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  with st.form("expense_form", clear_on_submit=True):
      exp_type = st.radio("نوع المصروف:", ["مصروف خاص بفرع معين", "🌍 مصروف عام للمخزن (يتوزع تلقائياً على كل الفروع لتاريخه)"])
      sel_b_name = ""
      if exp_type == "مصروف خاص بفرع معين":
          sel_b_name = st.selectbox("اختر الفرع المستهدف للمصروف:", list(b_dict.keys()))
          
      exp_amount = st.number_input("مبلغ المصروف (د.ل):", min_value=0.0, value=0.0, step=0.5, format="%.2f")
      exp_desc = st.text_input("بيان أو وصف المصروف:")
      exp_date_in = st.date_input("تاريخ المصروف:", value=datetime.now())
      
      if st.form_submit_button("💾 حفظ وتسجيل المصروف"):
          if exp_amount > 0 and exp_desc:
              cur_ex = conn.cursor()
              date_str = exp_date_in.strftime('%Y-%m-%d')
              if exp_type == "مصروف خاص بفرع معين":
                  target_bid = b_dict[sel_b_name]
                  cur_ex.execute("INSERT INTO expenses (branch_id, amount, description, is_general_store, expense_date) VALUES (?, ?, ?, 0, ?)", (target_bid, exp_amount, exp_desc.strip(), date_str))
              else:
                  cur_ex.execute("INSERT INTO expenses (branch_id, amount, description, is_general_store, expense_date) VALUES (NULL, ?, ?, 1, ?)", (exp_amount, exp_desc.strip(), date_str))
              conn.commit()
              log_action(st.session_state["user_id"], "تسجيل مصروف", f"مبلغ {exp_amount} بتاريخ {date_str} - {exp_desc}")
              st.success("💸 تم تسجيل المصروف بنجاح!")
  
  exp_df = pd.read_sql("SELECT expenses.id AS 'رقم', IFNULL(branches.branch_name, '🌍 مصروف عام (موزع)') AS 'الجهة / الفرع', expenses.amount AS 'المبلغ', expenses.description AS 'البيان', expenses.expense_date AS 'تاريخ المصروف' FROM expenses LEFT JOIN branches ON expenses.branch_id = branches.id ORDER BY expenses.id DESC", conn)
  if not exp_df.empty:
      st.dataframe(exp_df, use_container_width=True)
      st.download_button("📥 تصدير المصروفات لـ Excel", data=to_excel(exp_df), file_name="expenses_report.xlsx")
      if st.session_state["role"] == "Admin":
          del_exp_id = st.selectbox("اختر رقم المصروف للحذف:", exp_df["رقم"].tolist())
          if st.button("🗑️ حذف المصروف المختار", type="primary"):
              admin_confirm_dialog("حذف مصروف", del_exp_id)
  conn.close()

elif choice == "➕ إضافة فائض أو مرتجع وتوالف":
  st.header("➕ إضافة فائض أو مرتجع وتوالف (بقاء الصنف بكوده وسعره وصلاحيته)")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  sel_b_name = st.selectbox("اختر الفرع أو المخزن:", list(b_dict.keys()))
  current_b_id = b_dict[sel_b_name]
  
  operation_type = st.radio("نوع العملية:", ["➕ إضافة فائض صنف", "♻️ تسجيل مرتجع / توالف (رجوع الصنف بكوده وسعره وصلاحيته)"])
  items_list = conn.execute("SELECT id, item_code, item_name, sale_price, buy_price, expiry_date, no_expiry FROM items WHERE branch_id = ?", (current_b_id,)).fetchall()
  
  if items_list:
      i_opts = {f"[{i['item_code']}] {i['item_name']} (السعر: {i['sale_price']} د.ل)": i for i in items_list}
      with st.form("surplus_return_form", clear_on_submit=True):
          chosen_lbl = st.selectbox("اختر الصنف:", list(i_opts.keys()))
          qty_val = st.number_input("الكمية (بالكسور / كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
          
          btn_label = "💾 اعتماد وإضافة الفائض" if operation_type.startswith("➕") else "♻️ اعتماد وتسجيل المرتجع / التالف"
          if st.form_submit_button(btn_label):
              sel_item = i_opts[chosen_lbl]
              conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (qty_val, sel_item['id']))
              conn.commit()
              st.success(f"🚀 تمت العملية بنجاح للصنف ({sel_item['item_name']})!")
              st.rerun()
  else:
      st.info("لا توجد أصناف مسجلة في هذا الفرع حالياً.")
  conn.close()

elif choice == "🔄 نقل وتحويل وتزويد الفروع (مع الأرشفة)":
  st.header("🔄 نقل وتحويل وتزويد الفروع (سلة أصناف متعددة مع حفظ الأرشيف والاسترجاع)")
  conn = get_db_connection()
  
  main_store = conn.execute("SELECT id, branch_name FROM branches WHERE branch_type = 'مخزن' LIMIT 1").fetchone()
  if main_store:
      main_id = main_store["id"]
      other_branches = conn.execute("SELECT id, branch_name FROM branches WHERE id != ?", (main_id,)).fetchall()
      
      if other_branches:
          b_opts = {b["branch_name"]: b["id"] for b in other_branches}
          sel_target_b = st.selectbox("اختر الفرع المستهدف لتزويده بالبضاعة:", list(b_opts.keys()))
          target_b_id = b_opts[sel_target_b]
          
          if "transfer_cart" not in st.session_state: st.session_state["transfer_cart"] = []
          
          main_items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND quantity > 0", (main_id,)).fetchall()
          m_opts = {f"[{i['item_code']}] {i['item_name']} (متاح بالمخزن: {i['quantity']} كجم)": i for i in main_items} if main_items else {}
          
          with st.form("add_transfer_item_form", clear_on_submit=True):
              if m_opts:
                  chosen_m_label = st.selectbox("اختر الصنف من المخزن:", list(m_opts.keys()))
                  t_qty = st.number_input("الكمية المراد إرسالها (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
                  if st.form_submit_button("➕ إضافة الصنف إلى سلة التزويد"):
                      if t_qty > 0:
                          it_obj = m_opts[chosen_m_label]
                          if t_qty <= it_obj['quantity']:
                              st.session_state["transfer_cart"].append({
                                  "id": it_obj['id'], "code": it_obj['item_code'], "name": it_obj['item_name'],
                                  "qty": t_qty, "buy_price": it_obj['buy_price'], "sale_price": it_obj['sale_price'],
                                  "avg_cost": it_obj['avg_cost'], "expiry": it_obj['expiry_date'], "no_expiry": it_obj['no_expiry']
                              })
                              st.success(f"✅ تمت إضافة ({it_obj['item_name']}) بكمية ({t_qty} كجم) للسلة.")
                              st.rerun()
                          else:
                              st.warning("⚠️ الكمية المطلوبة تتجاوز المتاح بالمخزن.")
              else:
                  st.warning("⚠️ لا توجد أصناف متاحة بالمخزن الرئيسي.")
                  
          if st.session_state["transfer_cart"]:
              st.write("<b>أصناف سلة تزويد الفرع الحالية:</b>", unsafe_allow_html=True)
              t_df = pd.DataFrame(st.session_state["transfer_cart"])
              st.dataframe(t_df[["code", "name", "qty"]], use_container_width=True)
              
              if st.button("🚀 حفظ وإنهاء وإرسال بضاعة التزويد للفرع", type="primary"):
                  cur_tr = conn.cursor()
                  details_list = []
                  for t_item in st.session_state["transfer_cart"]:
                      cur_tr.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (t_item['qty'], t_item['id']))
                      dest_e = cur_tr.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (target_b_id, t_item['code'])).fetchone()
                      if dest_e:
                          cur_tr.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (t_item['qty'], dest_e["id"]))
                      else:
                          cur_tr.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
                                       (target_b_id, t_item['code'], t_item['name'], t_item['qty'], t_item['buy_price'], t_item['sale_price'], t_item['avg_cost'], t_item['expiry'], t_item['no_expiry']))
                      details_list.append(f"{t_item['name']} ({t_item['qty']} كجم)")
                  
                  full_details = " - ".join(details_list)
                  cur_tr.execute("INSERT INTO transfer_logs (from_branch_id, to_branch_id, transfer_type, items_details, status) VALUES (?, ?, 'تزويد بضاعة', ?, 'مكتملة')",
                                (main_id, target_b_id, full_details))
                  conn.commit()
                  st.session_state["transfer_cart"] = []
                  st.success(f"🎉 تم تزويد فرع ({sel_target_b}) بكافة أصناف الفاتورة بنجاح!")
                  st.rerun()
                  
              if st.button("🗑️ تفريغ السلة"):
                  st.session_state["transfer_cart"] = []
                  st.rerun()
  conn.close()

elif choice == "📥 المشتريات والموردين (فواتير متعددة الأصناف)":
  st.header("📥 تسجيل فواتير المشتريات (برقم فاتورة يدوي، أصناف متعددة، وحسابات الموردين)")
  conn = get_db_connection()
  
  tab_p1, tab_p2, tab_p3 = st.tabs(["➕ تسجيل فاتورة مشتريات متعددة الأصناف", "👥 إدارة الموردين وديونهم (مع التصدير)", "📋 سجل فواتير المشتريات"])
  
  with tab_p1:
      branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict = {b["branch_name"]: b["id"] for b in branches}
      suppliers = conn.execute("SELECT id, supplier_name FROM suppliers").fetchall()
      s_dict = {s["supplier_name"]: s["id"] for s in suppliers} if suppliers else {}
      
      p_branch_name = st.selectbox("الفرع أو المخزن المستلم للبضاعة:", list(b_dict.keys()), key="p_b_sel")
      p_supp_name = st.selectbox("اختر المورد:", list(s_dict.keys()) if s_dict else ["لا توجد موردين مسجلين"], key="p_s_sel")
      inv_num_in = st.text_input("رقم فاتورة المورد (يدوي):", value="", key="p_inv_num")
      p_type = st.radio("طريقة الشراء:", ["كاش (نقدي)", "آجل (على حساب المورد)"], key="p_pay_type")
      p_date = st.date_input("تاريخ الفاتورة:", value=datetime.now(), key="p_date_in")
      
      st.markdown("---")
      if "purch_cart" not in st.session_state: st.session_state["purch_cart"] = []
      
      all_db_items = conn.execute("SELECT id, item_code, item_name, buy_price FROM items WHERE branch_id = ?", (b_dict[p_branch_name],)).fetchall()
      item_opts = {f"[{i['item_code']}] {i['item_name']}": i for i in all_db_items} if all_db_items else {}
      
      with st.form("add_purch_item_form", clear_on_submit=True):
          if item_opts:
              chosen_item_key = st.selectbox("اختر صنف للإضافة بالفاتورة:", list(item_opts.keys()))
              purch_qty = st.number_input("الكمية المشتراة (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
              purch_price = st.number_input("سعر شراء الكيلو من المورد (د.ل):", min_value=0.0, value=0.0, step=0.5, format="%.2f")
              
              if st.form_submit_button("➕ إضافة الصنف إلى سلة فاتورة المشتريات"):
                  if purch_qty > 0:
                      chosen_it = item_opts[chosen_item_key]
                      st.session_state["purch_cart"].append({
                          "id": chosen_it['id'], "code": chosen_it['item_code'], "name": chosen_it['item_name'],
                          "qty": purch_qty, "price": purch_price, "total": purch_qty * purch_price
                      })
                      st.success(f"✅ تمت إضافة ({chosen_it['item_name']}) للفاتورة.")
                      st.rerun()
          else:
              st.warning("⚠️ يرجى تحميل الأصناف في هذا الفرع أولاً.")
              
      if st.session_state["purch_cart"]:
          st.write("<b>أصناف فاتورة المشتريات الحالية:</b>", unsafe_allow_html=True)
          p_cart_df = pd.DataFrame(st.session_state["purch_cart"])
          st.dataframe(p_cart_df[["code", "name", "qty", "price", "total"]], use_container_width=True)
          p_g_tot = sum([x["total"] for x in st.session_state["purch_cart"]])
          st.metric("إجمالي الفاتورة", f"{p_g_tot:,.2f} د.ل")
          
          if st.button("💾 حفظ وإنهاء فاتورة المشتريات واعتمادها", type="primary"):
              if p_supp_name != "لا توجد موردين مسجلين" and inv_num_in.strip():
                  supp_id = s_dict[p_supp_name]
                  cur_p = conn.cursor()
                  details_list = []
                  
                  for p_item in st.session_state["purch_cart"]:
                      old_qty = cur_p.execute("SELECT quantity FROM items WHERE id = ?", (p_item['id'],)).fetchone()["quantity"]
                      old_avg = cur_p.execute("SELECT avg_cost FROM items WHERE id = ?", (p_item['id'],)).fetchone()["avg_cost"] or cur_p.execute("SELECT buy_price FROM items WHERE id = ?", (p_item['id'],)).fetchone()["buy_price"]
                      
                      new_total_qty = old_qty + p_item['qty']
                      new_avg_cost = ((old_qty * old_avg) + (p_item['qty'] * p_item['price'])) / new_total_qty if new_total_qty > 0 else p_item['price']
                      
                      cur_p.execute("UPDATE items SET quantity = quantity + ?, buy_price = ?, avg_cost = ? WHERE id = ?", 
                                    (p_item['qty'], p_item['price'], new_avg_cost, p_item['id']))
                      details_list.append(f"{p_item['name']} ({p_item['qty']} كجم بسعر {p_item['price']})")
                  
                  full_details = " - ".join(details_list)
                  cur_p.execute("INSERT INTO purchases (branch_id, supplier_id, supplier_name, invoice_number, total_cost, payment_type, items_details, invoice_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (b_dict[p_branch_name], supp_id, p_supp_name, inv_num_in.strip(), p_g_tot, p_type, full_details, p_date.strftime('%Y-%m-%d')))
                  
                  if p_type.startswith("آجل"):
                      cur_p.execute("UPDATE suppliers SET balance = balance + ? WHERE id = ?", (p_g_tot, supp_id))
                  
                  conn.commit()
                  st.session_state["purch_cart"] = []
                  st.success(f"🎉 تم حفظ فاتورة المشتريات رقم (#{inv_num_in}) بنجاح تام!")
                  st.rerun()
              else:
                  st.warning("⚠️ يرجى اختيار المورد وكتابة رقم الفاتورة.")
                  
          if st.button("🗑️ تفريغ سلة الفاتورة"):
              st.session_state["purch_cart"] = []
              st.rerun()
  
  with tab_p2:
      st.subheader("👥 إضافة مورد جديد ومتابعة الديون والمستحقات المالية (مع التصدير)")
      with st.form("new_supplier_form", clear_on_submit=True):
          s_name = st.text_input("اسم المورد التجاري:")
          s_phone = st.text_input("رقم الهاتف:")
          if st.form_submit_button("💾 حفظ المورد الجديد") and s_name:
              try:
                  conn.execute("INSERT INTO suppliers (supplier_name, phone) VALUES (?, ?)", (s_name.strip(), s_phone.strip()))
                  conn.commit()
                  st.success(f"🎉 تم إضافة المورد ({s_name}) بنجاح!")
                  st.rerun()
              except:
                  st.error("⚠️ المورد موجود مسبقاً.")
                  
      supp_df = pd.read_sql("SELECT id, supplier_name AS 'اسم المورد', phone AS 'الهاتف', balance AS 'إجمالي الديون والمستحقات (د.ل)' FROM suppliers", conn)
      if not supp_df.empty:
          st.dataframe(supp_df, use_container_width=True)
          st.download_button("📥 تصدير تقرير ديون الموردين لـ Excel", data=to_excel(supp_df), file_name="suppliers_debts.xlsx")
      else:
          st.info("لا توجد موردين مسجلين بعد.")
          
  with tab_p3:
      try:
          p_df = pd.read_sql("SELECT purchases.id AS 'مسلسل', purchases.invoice_number AS 'رقم الفاتورة', branches.branch_name AS 'الفرع', purchases.supplier_name AS 'المورد', purchases.total_cost AS 'إجمالي التكلفة', purchases.payment_type AS 'طريقة الدفع', purchases.items_details AS 'التفاصيل', purchases.invoice_date AS 'التاريخ' FROM purchases LEFT JOIN branches ON purchases.branch_id = branches.id ORDER BY purchases.id DESC", conn)
          if not p_df.empty:
              st.dataframe(p_df, use_container_width=True)
              st.download_button("📥 تصدير سجل فواتير المشتريات لـ Excel", data=to_excel(p_df), file_name="purchases_invoices.xlsx")
      except:
          st.info("لا توجد فواتير مشتريات مسجلة حتى الآن.")
  conn.close()

elif choice == "🥜 التحميص والخلط والمكسرات المشكلة (متعدد الأصناف)":
  st.header("🥜 التحميص والخلط وتكوين المكسرات المشكلة (إضافة عدة أصناف خامات بالكسور)")
  conn = get_db_connection()
  
  main_store_row = conn.execute("SELECT id FROM branches WHERE branch_type='مخزن' LIMIT 1").fetchone()
  main_s_id = main_store_row["id"] if main_store_row else 1
  store_items = conn.execute("SELECT item_code, item_name, quantity, buy_price, avg_cost FROM items WHERE branch_id = ? AND quantity > 0", (main_s_id,)).fetchall()
  
  if store_items:
      item_choices = {f"[{i['item_code']}] {i['item_name']} (متاح: {i['quantity']} كجم)": i for i in store_items}
      
      st.subheader("📋 تحديد أصناف الخلطة المتعددة:")
      if "mix_items_list" not in st.session_state: st.session_state["mix_items_list"] = []
      
      with st.form("add_mix_component_form", clear_on_submit=True):
          sel_comp = st.selectbox("اختر صنفاً خاماً للخلطة:", list(item_choices.keys()))
          comp_qty = st.number_input("الوزن / الكمية المستخدمة (كجم بالكسور):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
          if st.form_submit_button("➕ إضافة هذا الصنف للخلطة"):
              if comp_qty > 0:
                  it_obj = item_choices[sel_comp]
                  st.session_state["mix_items_list"].append({
                      "code": it_obj['item_code'], "name": it_obj['item_name'], 
                      "qty": comp_qty, "cost": it_obj['avg_cost'] or it_obj['buy_price']
                  })
                  st.success(f"✅ تمت إضافة ({it_obj['item_name']}) بكمية ({comp_qty} كجم) للخلطة.")
                  st.rerun()
                  
      if st.session_state["mix_items_list"]:
          st.write("<b>الأصناف المضافة للخلطة الحالية:</b>", unsafe_allow_html=True)
          mix_df = pd.DataFrame(st.session_state["mix_items_list"])
          st.dataframe(mix_df, use_container_width=True)
          
          with st.form("finalize_mix_form"):
              st.markdown("---")
              res_name = st.text_input("اسم المنتج الناتج النهائي (مثال: مكسرات مشكلة فاخرة):")
              res_code = st.text_input("كود المنتج الناتج:")
              res_total_qty = st.number_input("الوزن الإجمالي المنتج النهائي (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
              res_sale_price = st.number_input("سعر بيع الكيلو للمنتج الناتج (د.ل):", min_value=0.0, value=0.0, step=0.5, format="%.2f")
              
              if st.form_submit_button("⚙️ اعتماد الخلطة وخصم الخامات وإنتاج الصنف النهائي"):
                  if res_name and res_code and res_total_qty > 0:
                      cur_mx = conn.cursor()
                      total_mix_cost = sum([x['qty'] * x['cost'] for x in st.session_state["mix_items_list"]])
                      final_cost_per_kg = total_mix_cost / res_total_qty if res_total_qty > 0 else 0
                      
                      for m_item in st.session_state["mix_items_list"]:
                          cur_mx.execute("UPDATE items SET quantity = quantity - ? WHERE branch_id = ? AND item_code = ?", 
                                         (m_item['qty'], main_s_id, m_item['code']))
                          
                      cur_mx.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)",
                                     (main_s_id, res_code, res_name, res_total_qty, final_cost_per_kg, res_sale_price, final_cost_per_kg))
                      conn.commit()
                      st.session_state["mix_items_list"] = []
                      st.success(f"🎉 تم تكوين المنتج ({res_name}) بوزن ({res_total_qty} كجم) وتكلفة ({final_cost_per_kg:,.2f} د.ل) بنجاح تام!")
                      st.rerun()
                      
          if st.button("🗑️ تفريغ وتصفير قائمة خامات الخلطة"):
              st.session_state["mix_items_list"] = []
              st.rerun()
  else:
      st.info("لا توجد خامات متوفرة بالمخزن الرئيسي.")
  conn.close()

elif choice == "📊 مركز التقارير والإدارة الشاملة (مع التصدير وحركة الفروع)":
  st.header("📊 مركز التقارير والإدارة الشاملة (متابعة الأرباح، حركة الفروع، التصدير لـ Excel والحذف)")
  conn = get_db_connection()
  
  tab_c1, tab_c2, tab_c3, tab_c4 = st.tabs(["📊 الأرباح والخسائر والتقارير", "📦 تقرير حركة صنف (مع قائمة الفروع)", "📈 مبيعات الفروع بالفترة", "🗑️ إدارة وحذف الفواتير والمصروفات"])
  
  with tab_c1:
      branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict = {b["branch_name"]: b["id"] for b in branches}
      rep_opts = {"🌐 إجمالي الكل": "ALL"}
      rep_opts.update(b_dict)
      sel_rep = st.selectbox("اختر الفرع لعرض تقرير أرباحه:", list(rep_opts.keys()), key="rep_branch_sel")
      t_id = rep_opts[sel_rep]
      
      if t_id == "ALL":
          sales = conn.execute("SELECT SUM(total_amount) FROM invoices").fetchone()[0] or 0.0
          purch = conn.execute("SELECT SUM(total_cost) FROM purchases").fetchone()[0] or 0.0
          exps = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0.0
          net = sales - (purch + exps)
          
          c1, c2, c3, c4 = st.columns(4)
          with c1: st.metric("إجمالي المبيعات", f"{sales:,.2f}")
          with c2: st.metric("إجمالي المشتريات", f"{purch:,.2f}")
          with c3: st.metric("إجمالي المصروفات", f"{exps:,.2f}")
          with c4: st.metric("صافي الربح العام", f"{net:,.2f}")
      else:
          sales = conn.execute("SELECT SUM(total_amount) FROM invoices WHERE branch_id = ?", (t_id,)).fetchone()[0] or 0.0
          purch = conn.execute("SELECT SUM(total_cost) FROM purchases WHERE branch_id = ?", (t_id,)).fetchone()[0] or 0.0
          exps = conn.execute("SELECT SUM(amount) FROM expenses WHERE branch_id = ? OR is_general_store = 1", (t_id,)).fetchone()[0] or 0.0
          net = sales - (purch + exps)
          
          c1, c2, c3, c4 = st.columns(4)
          with c1: st.metric("مبيعات الفرع", f"{sales:,.2f}")
          with c2: st.metric("مشتريات الفرع", f"{purch:,.2f}")
          with c3: st.metric("مصروفات الفرع", f"{exps:,.2f}")
          with c4: st.metric("صافي أرباح الفرع", f"{net:,.2f}")

  with tab_c2:
      st.subheader("📦 تقرير حركة صنف في فرع معين أو كافة الفروع")
      branches_rep = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict_rep = {b["branch_name"]: b["id"] for b in branches_rep}
      sel_branch_mov = st.selectbox("اختر الفرع المراد الاستعلام عن حركته:", ["🌐 كافة الفروع"] + list(b_dict_rep.keys()))
      
      all_items_code = conn.execute("SELECT DISTINCT item_code, item_name FROM items").fetchall()
      if all_items_code:
          it_dict = {f"[{i['item_code']}] {i['item_name']}": i['item_code'] for i in all_items_code}
          sel_item_c = st.selectbox("اختر الصنف:", list(it_dict.keys()))
          
          d_from = st.date_input("من تاريخ:", value=datetime.now() - timedelta(days=30))
          d_to = st.date_input("إلى تاريخ:", value=datetime.now())
          
          if st.button("📊 عرض تقرير حركة الصنف بالفرع"):
              code_to_search = it_dict[sel_item_c]
              if sel_branch_mov == "🌐 كافة الفروع":
                  item_branches = conn.execute("SELECT branches.branch_name, items.quantity, items.sale_price, items.buy_price FROM items LEFT JOIN branches ON items.branch_id = branches.id WHERE items.item_code = ?", (code_to_search,)).fetchall()
              else:
                  b_id_target = b_dict_rep[sel_branch_mov]
                  item_branches = conn.execute("SELECT branches.branch_name, items.quantity, items.sale_price, items.buy_price FROM items LEFT JOIN branches ON items.branch_id = branches.id WHERE items.item_code = ? AND items.branch_id = ?", (code_to_search, b_id_target)).fetchall()
              
              st.write(f"**نتائج الاستعلام عن صنف ({sel_item_c}):**")
              for ib in item_branches:
                  st.write(f"- الفرع: **{ib['branch_name']}** | الكمية المتاحة: **{ib['quantity']} كجم** | سعر البيع: **{ib['sale_price']} د.ل**")
  
  with tab_c3:
      st.subheader("📈 تقرير مبيعات الفروع بحسب الفترة الزمنية (مع التصدير لـ Excel)")
      d_f2 = st.date_input("من تاريخ المبيعات:", value=datetime.now() - timedelta(days=7), key="df2")
      d_t2 = st.date_input("إلى تاريخ المبيعات:", value=datetime.now(), key="dt2")
      
      if st.button("📊 عرض تقرير المبيعات بالفترة"):
          sales_period_df = pd.read_sql("""
              SELECT invoices.id AS 'رقم الفاتورة', branches.branch_name AS 'الفرع', users.username AS 'الكاشير', invoices.total_amount AS 'المبلغ', invoices.created_at AS 'التاريخ والوقت' 
              FROM invoices 
              LEFT JOIN branches ON invoices.branch_id = branches.id 
              LEFT JOIN users ON invoices.user_id = users.id 
              WHERE date(invoices.created_at) BETWEEN ? AND ?
              ORDER BY invoices.id DESC
          """, conn, params=(d_f2.strftime('%Y-%m-%d'), d_t2.strftime('%Y-%m-%d')))
          
          if not sales_period_df.empty:
              st.dataframe(sales_period_df, use_container_width=True)
              st.download_button("📥 تصدير تقرير المبيعات للفترة لـ Excel", data=to_excel(sales_period_df), file_name="sales_period.xlsx")
          else:
              st.info("لا توجد مبيعات مسجلة في هذه الفترة.")

  with tab_c4:
      st.subheader("🗑️ مركز التحكم المركزي: حذف الفواتير والمصروفات وحركات المشتريات")
      sub_del_choice = st.selectbox("اختر نوع السجل للتحكم به وحذفه:", ["الفواتير", "المصروفات", "فواتير المشتريات"])
      
      if sub_del_choice == "الفواتير":
          inv_df = pd.read_sql("SELECT id, total_amount, created_at FROM invoices ORDER BY id DESC LIMIT 50", conn)
          if not inv_df.empty:
              inv_id_del = st.selectbox("اختر رقم الفاتورة للحذف:", inv_df['id'].tolist())
              if st.button("🗑️ حذف الفاتورة المحددة", type="primary"):
                  admin_confirm_dialog("حذف فاتورة", inv_id_del)
          else:
              st.info("لا توجد فواتير.")
      elif sub_del_choice == "المصروفات":
          exp_df_del = pd.read_sql("SELECT id, amount, description, expense_date FROM expenses ORDER BY id DESC LIMIT 50", conn)
          if not exp_df_del.empty:
              exp_id_del = st.selectbox("اختر رقم المصروف للحذف:", exp_df_del['id'].tolist())
              if st.button("🗑️ حذف المصروف المحدد", type="primary"):
                  admin_confirm_dialog("حذف مصروف", exp_id_del)
          else:
              st.info("لا توجد مصروفات.")
      else:
          purch_df_del = pd.read_sql("SELECT id, invoice_number, supplier_name, total_cost, invoice_date FROM purchases ORDER BY id DESC LIMIT 50", conn)
          if not purch_df_del.empty:
              purch_id_del = st.selectbox("اختر رقم مسلسل فاتورة المشتريات للحذف:", purch_df_del['id'].tolist(), format_func=lambda x: f"مسلسل: {x} (فاتورة رقم: {purch_df_del[purch_df_del['id']==x]['invoice_number'].values[0]})")
              if st.button("🗑️ حذف فاتورة المشتريات المحددة", type="primary"):
                  admin_confirm_dialog("حذف مشتريات", purch_id_del)
          else:
              st.info("لا توجد فواتير مشتريات.")
  conn.close()

elif choice == "👥 إدارة المستخدمين وصلاحياتهم الفردية":
  st.header("👥 إدارة المستخدمين وصلاحياتهم الفردية (إعطاء صلاحيات فرعية للموظفين)")
  conn = get_db_connection()
  
  tab_u1, tab_u2 = st.tabs(["👥 حسابات المستخدمين", "🛡️ إعطاء صلاحيات فردية للموظف"])
  with tab_u1:
      with st.expander("➕ إضافة مستخدم جديد", expanded=False):
          with st.form("new_user_form", clear_on_submit=True):
              u_name = st.text_input("اسم المستخدم")
              u_phone = st.text_input("الهاتف")
              u_pass = st.text_input("كلمة المرور")
              u_role = st.selectbox("الرتبة:", ["Admin (مدير النظام)", "General_Supervisor (مدير عام)", "Branch_Supervisor (مشرف فرع)", "Cashier (كاشير)", "Viewer (مشاهد فقط)"])
              
              branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
              b_dict = {b["branch_name"]: b["id"] for b in branches}
              
              allowed_b_selection = "ALL"
              if u_role.startswith("Cashier") or u_role.startswith("Branch_Supervisor"):
                  st.write("حدد الفروع المصرح بها لهذا المستخدم (أو اختر الكل):")
                  selected_branches_names = []
                  for b_name in b_dict.keys():
                      if st.checkbox(b_name, key=f"user_b_{b_name}"):
                          selected_branches_names.append(str(b_dict[b_name]))
                  if selected_branches_names:
                      allowed_b_selection = ",".join(selected_branches_names)
              
              if st.form_submit_button("💾 حفظ"):
                  if u_name and u_pass:
                      primary_bid = int(allowed_b_selection.split(",")[0]) if allowed_b_selection != "ALL" else None
                      conn.execute("INSERT INTO users (username, phone, password, role, branch_id, allowed_branches) VALUES (?, ?, ?, ?, ?, ?)", 
                                   (u_name.strip(), u_phone.strip(), u_pass, u_role.split(" ")[0], primary_bid, allowed_b_selection))
                      conn.commit()
                      st.success("🎉 تم إضافة المستخدم بنجاح!")
                      
      users_df = pd.read_sql("SELECT users.id, users.username AS 'اسم المستخدم', users.phone AS 'الهاتف', users.role AS 'الرتبة', users.allowed_branches AS 'الفروع المسموحة' FROM users", conn)
      if not users_df.empty:
          st.dataframe(users_df, use_container_width=True)
          st.download_button("📥 تصدير قائمة المستخدمين لـ Excel", data=to_excel(users_df), file_name="users_report.xlsx")
          if st.session_state["role"] == "Admin":
              del_user_id = st.selectbox("اختر مستخدم للحذف النهائي:", users_df["id"].tolist(), format_func=lambda x: users_df[users_df["id"]==x]["اسم المستخدم"].values[0])
              if st.button("🗑️ حذف المستخدم (نافذة تأكيد للأدمن)", type="primary"):
                  admin_confirm_dialog("حذف مستخدم", del_user_id)

  with tab_u2:
      st.subheader("🛡️ إعطاء صلاحية معينة لموظف معين (صلاحيات فردية استثنائية)")
      all_users = conn.execute("SELECT id, username, role FROM users WHERE role != 'Admin'").fetchall()
      if all_users:
          u_opts = {f"{u['username']} (الرتبة الأصلية: {u['role']})": u["id"] for u in all_users}
          sel_u_label = st.selectbox("اختر الموظف لتعديل صلاحياته الفردية:", list(u_opts.keys()))
          target_u_id = u_opts[sel_u_label]
          
          current_u_row = conn.execute("SELECT custom_permissions FROM users WHERE id = ?", (target_u_id,)).fetchone()
          curr_custom_list = current_u_row["custom_permissions"].split(",") if current_u_row and current_u_row["custom_permissions"] else []
          
          with st.form("custom_user_perm_form"):
              st.write("حدد الميزات والصلاحيات الإضافية التي تريد إعطاءها لهذا الموظف:")
              selected_extra_perms = []
              for m in DEFAULT_MENUS:
                  if st.checkbox(m, value=(m in curr_custom_list), key=f"extra_p_{m}2"):
                      selected_extra_perms.append(m)
              
              if st.form_submit_button("💾 حفظ واعتماد الصلاحيات الفردية للموظف"):
                  perm_str = ",".join(selected_extra_perms)
                  conn.execute("UPDATE users SET custom_permissions = ? WHERE id = ?", (perm_str, target_u_id))
                  conn.commit()
                  st.success("🎉 تم منح وصلاحيات الموظف الفردية بنجاح!")
  conn.close()

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير (POS)")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  user_allowed_b = st.session_state.get("allowed_branches", "ALL")
  
  if st.session_state["role"] == "Admin" or user_allowed_b == "ALL":
      sel_pos_branch = st.selectbox("اختر الفرع:", ["🌐 إجمالي كل الفروع (شامل)"] + list(b_dict.keys()))
      if sel_pos_branch == "🌐 إجمالي كل الفروع (شامل)":
          b_id = "ALL"
      else:
          b_id = b_dict[sel_pos_branch]
  else:
      allowed_ids = [int(x) for x in user_allowed_b.split(",") if x.strip().isdigit()]
      allowed_b_dict = {b["branch_name"]: b["id"] for b in branches if b["id"] in allowed_ids}
      if len(allowed_b_dict) > 1:
          sel_pos_branch = st.selectbox("اختر الفرع المصرح لك به:", list(allowed_b_dict.keys()))
          b_id = allowed_b_dict[sel_pos_branch]
      elif len(allowed_b_dict) == 1:
          b_id = list(allowed_b_dict.values())[0]
          st.info(f"🏢 الفرع الحالي: **{list(allowed_b_dict.keys())[0]}**")
      else:
          b_id = None
          st.warning("⚠️ ليس لديك أي فروع مصرح لك بالعمل عليها حالياً.")
      
  if b_id:
      if b_id == "ALL":
          fav_items = conn.execute("SELECT * FROM items WHERE favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC").fetchall()
      else:
          fav_items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC", (b_id,)).fetchall()
          
      st.markdown("""
          <div style="background: #1e293b; color: white; padding: 10px; border-radius: 8px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; font-size: 14px;">
              <div><b>⌨️ أزرار الاختصارات السريعة:</b></div>
              <div><b>[F1]</b> إتمام البيع</div>
              <div><b>[F2]</b> إعادة طباعة</div>
              <div><b>[F3]</b> تفريغ السلة</div>
              <div><b>[F8]</b> خصم / تعديل</div>
              <div><b>[F10]</b> صنف سريع / خدمة</div>
          </div>
      """, unsafe_allow_html=True)

      hk_col1, hk_col2, hk_col3, hk_col4, hk_col5 = st.columns(5)
      with hk_col1:
          if st.button("F1: إتمام البيع الفوري", use_container_width=True):
              if st.session_state["cart"]:
                  g_tot = sum([x["total"] for x in st.session_state["cart"]])
                  checkout_payment_dialog(b_id, g_tot)
              else:
                  st.warning("السلة فارغة!")
      with hk_col2:
          if st.button("F2: إعادة طباعة آخر فاتورة", use_container_width=True):
              last_inv = conn.execute("SELECT id, total_amount, created_at FROM invoices ORDER BY id DESC LIMIT 1").fetchone()
              if last_inv:
                  st.info(f"🖨️ جاري إعادة طباعة الفاتورة رقم #{last_inv['id']} بمبلغ {last_inv['total_amount']} د.ل")
              else:
                  st.warning("لا توجد فواتير سابقة لإعادة طباعتها.")
      with hk_col3:
          if st.button("F3: تفريغ السلة", use_container_width=True):
              st.session_state["cart"] = []
              st.success("🗑️ تم تفريغ سلة المبيعات بالكامل!")
              st.rerun()
      with hk_col4:
          if st.button("F8: تطبيق خصم", use_container_width=True):
              st.info("💡 خاصية الخصم جاهزة للتطبيق على إجمالي الفاتورة.")
      with hk_col5:
          if st.button("F10: إضافة خدمة سريعة", use_container_width=True):
              st.session_state["cart"].append({
                  "id": 99999, "name": "خدمة عامة / توصيل", "price": 0.0, "qty": 1.0, "total": 0.0
              })
              st.success("✅ تمت إضافة خدمة سريعة للسلة!")
              st.rerun()

      st.markdown("---")
      col_g, col_c = st.columns([2, 1])
      with col_g:
          st.subheader("⭐ لوحة الأصناف المفضلة (أول 20 صنفاً أمام الكاشير)")
          st.text_input("🔍 مسح باركود الميزان أو الصنف:", key="barcode_scan", on_change=process_scale_barcode)
          
          if fav_items:
              for item in fav_items:
                  col_i1, col_i2, col_i3 = st.columns([2, 1, 1])
                  with col_i1: 
                      qty_status = f"(متاح: {item['quantity']} كجم)" if float(item['quantity']) > 0 else "⚠️ (رصيد صفر)"
                      st.write(f"**#{item['favorite_rank']} - {item['item_name']}** {qty_status}")
                  with col_i2: st.write(f"{item['sale_price']} د.ل")
                  with col_i3:
                      with st.form(key=f"pos_qty_{item['id']}", clear_on_submit=True):
                          q_in = st.number_input("الكمية (كجم)", min_value=0.0, value=0.0, step=0.1, format="%.2f", key=f"q_{item['id']}")
                          if st.form_submit_button("➕ إضافة"):
                              if q_in > 0:
                                  if float(item['quantity']) <= 0:
                                      cur_neg = conn.cursor()
                                      cur_neg.execute("INSERT INTO negative_sales_logs (branch_id, user_id, item_name, sale_qty) VALUES (?, ?, ?, ?)", 
                                                      (item['branch_id'], st.session_state["user_id"], item['item_name'], float(q_in)))
                                      conn.commit()
                                  st.session_state["cart"].append({
                                      "id": item["id"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": float(q_in), "total": float(item["sale_price"]) * float(q_in)
                                  })
                                  st.rerun()
          else:
              st.info("لا توجد أصناف محددة في لوحة المفضلة (من 1 إلى 20) لهذا الفرع حالياً.")

      with col_c:
          st.subheader("سلة المبيعات")
          if st.session_state["cart"]:
              df_c = pd.DataFrame(st.session_state["cart"])
              st.dataframe(df_c[["name", "price", "qty", "total"]], use_container_width=True)
              g_tot = sum([x["total"] for x in st.session_state["cart"]])
              st.metric("الإجمالي", f"{g_tot:,.2f} د.ل")
              
              if st.button("🖨️ إتمام وطباعة الفاتورة", type="primary", use_container_width=True):
                  g_tot = sum([x["total"] for x in st.session_state["cart"]])
                  checkout_payment_dialog(b_id, g_tot)
              if st.button("🗑️ تفريغ السلة", use_container_width=True):
                  st.session_state["cart"] = []
                  st.rerun()
          else:
              st.info("السلة فارغة.")
  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
