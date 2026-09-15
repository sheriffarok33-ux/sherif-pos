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

# --- تنسيق الخطوط والألوان (نص أسود عريض وواضح جداً لراحة العين) ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700;900&display=swap');
    html, body, [class*="css"], p, span, div, label, h1, h2, h3, h4, h5, h6, table { 
        font-family: 'Tajawal', sans-serif !important; 
        color: #000000 !important; 
        font-weight: 700 !important;
    }
    .main { background-color: #f8fafc; }
    
    div.stButton > button { 
        border-radius: 8px; 
        font-weight: 900 !important; 
        transition: all 0.3s ease; 
        height: 45px; 
        background: linear-gradient(135deg, #0284c7, #0369a1);
        color: white !important;
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
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] span, [data-testid="stSidebar"] p {
        color: #ffffff !important;
    }
    [data-testid="stSidebar"] .stButton>button {
        background-color: #1e293b; color: #ffffff !important; border: 1px solid #334155;
        border-radius: 10px; padding: 10px 15px; text-align: right; font-weight: 900 !important;
        transition: all 0.3s ease; margin-bottom: 5px; font-size: 15px; height: auto;
    }
    [data-testid="stSidebar"] .stButton>button:hover { 
        background-color: #0284c7; color: white !important; border-color: #0284c7; transform: translateX(-5px); 
    }
    </style>
""", unsafe_allow_html=True)

if not os.path.exists("item_images"): os.makedirs("item_images")

DEFAULT_MENUS = [
    "🏠 الرئيسية واللوحة",
    "🛒 نقطة البيع (POS)",
    "⭐ لوحة المفضلة (1-20)",
    "📦 إدارة المخزن والفروع",
    "➕ الفائض والتوالف والمرتجعات",
    "🔄 تزويد الفروع والأرشيف",
    "🏢 إدارة الفروع",
    "📁 استيراد Excel",
    "💰 المصروفات",
    "📥 المشتريات والموردين",
    "⚙️ الجرد والتصفير السنوي",
    "🥜 التحميص والخلط والمكسرات",
    "📊 التقارير والأرباح",
    "👥 إدارة المستخدمين",
    "⚙️ تخصيص الأزرار"
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
      CREATE TABLE IF NOT EXISTS customers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          customer_name TEXT NOT NULL,
          phone TEXT UNIQUE NOT NULL,
          total_purchases REAL DEFAULT 0.0,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
          customer_name TEXT DEFAULT 'زبون نقدي',
          customer_phone TEXT DEFAULT '',
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
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Branch_Supervisor', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),⭐ لوحة المفضلة (1-20),📦 إدارة المخزن والفروع,📥 المشتريات والموردين,📊 التقارير والأرباح')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Cashier', '🏠 الرئيسية واللوحة,🛒 نقطة البيع (POS),⭐ لوحة المفضلة (1-20)')")
  except: pass
  try: cursor.execute("INSERT OR IGNORE INTO role_permissions (role, allowed_menus) VALUES ('Viewer', ?)", (",".join(DEFAULT_MENUS),))
  except: pass

  branch_count = cursor.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
  if branch_count == 0:
      default_branches = [("المخزن الرئيسي", "مخزن"), ("فرع الجزيرة", "فرع"), ("فرع 2", "فرع"), ("فرع 3", "فرع"), ("فرع 4", "فرع")]
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
    st.success("**أهلاً بك يا عائلة أبو زيد التجارية! نتمنى لك يوماً مباركاً ☕✨**")
    if st.button("OK (موافق)", use_container_width=True, type="primary"):
        st.session_state["show_welcome_dialog"] = False
        st.rerun()

@st.dialog("🖨️ إعادة طباعة وعرض آخر فاتورة")
def reprint_last_invoice_dialog():
    conn = get_db_connection()
    last_inv = conn.execute("SELECT invoices.*, branches.branch_name FROM invoices LEFT JOIN branches ON invoices.branch_id = branches.id ORDER BY invoices.id DESC LIMIT 1").fetchone()
    if last_inv:
        st.markdown(f"""
            <div style="background: white; padding: 20px; border-radius: 10px; border: 2px solid #0284c7; color: black; max-width: 400px; margin: auto; font-family: 'Tajawal', sans-serif;">
                <h3 style="text-align: center; color: #0284c7; margin:0;">🥜 مجموعة أبو زيد التجارية</h3>
                <p style="text-align: center; margin:5px 0;">فرع: <b>{last_inv['branch_name']}</b> | فاتورة رقم: <b>#{last_inv['id']}</b></p>
                <p style="text-align: center; margin:0; font-size: 14px;">الزبون: <b>{last_inv['customer_name']}</b> ({last_inv['customer_phone']})</p>
                <p style="text-align: center; margin:0 0 15px 0; font-size: 13px; color: #64748b;">التاريخ: {last_inv['created_at']}</p>
                <hr style="border: 0; border-top: 1px dashed #cbd5e1;">
                <h4 style="text-align: right; color: #1e293b;">إجمالي المبلغ: <span style="color: #0284c7;">{last_inv['total_amount']:,.2f} د.ل</span></h4>
                <p>طريقة الدفع: {last_inv['payment_method']}</p>
            </div>
        """, unsafe_allow_html=True)
        
        inv_txt_data = f"مجموعة أبو زيد التجارية\nفرع: {last_inv['branch_name']}\nرقم الفاتورة: #{last_inv['id']}\nالزبون: {last_inv['customer_name']}\nالهاتف: {last_inv['customer_phone']}\nالإجمالي: {last_inv['total_amount']:,.2f} د.ل\nطريقة الدفع: {last_inv['payment_method']}\nالتاريخ: {last_inv['created_at']}\nشكراً لتعاملكم معنا ☕✨"
        st.download_button("📥 تنزيل الفاتورة (ملف نصي للحفظ أو الإرسال اليدوي)", data=inv_txt_data, file_name=f"invoice_{last_inv['id']}.txt", mime="text/plain", use_container_width=True)
    else:
        st.info("لا توجد فواتير سابقة لإعادة طباعتها.")
    conn.close()
    if st.button("إغلاق"):
        st.rerun()

@st.dialog("⚡ إضافة صنف سريع / خدمة سريعة (F10)")
def fast_service_dialog():
    st.subheader("إضافة صنف أو خدمة سريعة للسلة الحالية")
    with st.form("fast_serv_form", clear_on_submit=True):
        f_name = st.text_input("اسم الخدمة / الصنف السريع:")
        f_price = st.number_input("السعر (د.ل):", min_value=0.0, value=0.0, step=0.5, format="%.2f")
        f_qty = st.number_input("الكمية:", min_value=0.0, value=1.0, step=0.1, format="%.2f")
        if st.form_submit_button("➕ اعتماد وإضافة للسلة"):
            if f_name and f_price > 0 and f_qty > 0:
                st.session_state["cart"].append({
                    "id": 88888, "name": f"سريع: {f_name.strip()}", "price": f_price, "qty": f_qty, "total": f_price * f_qty
                })
                st.success("✅ تمت إضافة الصنف السريع للسلة بنجاح!")
                st.rerun()

@st.dialog("🔒 تأكيد كلمة السر")
def admin_confirm_dialog(action_type, target_id, target_name=""):
    st.warning(f"⚠️ تأكيد أمني: تنفيذ عملية ({action_type}). يرجى إدخال كلمة السر:")
    admin_pass = st.text_input("كلمة السر:", type="password", key="diag_pass_input")
    
    if st.button("✅ تأكيد التنفيذ", use_container_width=True, type="primary"):
        if verify_admin_password(admin_pass):
            conn = get_db_connection()
            if action_type == "حذف فرع": conn.execute("DELETE FROM branches WHERE id = ?", (target_id,))
            elif action_type == "حذف صنف": conn.execute("DELETE FROM items WHERE id = ?", (target_id,))
            elif action_type == "محو كافة الأصناف": conn.execute("DELETE FROM items WHERE branch_id = ?" if target_id != "ALL" else "DELETE FROM items", (target_id,) if target_id != "ALL" else ())
            elif action_type == "حذف مصروف": conn.execute("DELETE FROM expenses WHERE id = ?", (target_id,))
            elif action_type == "حذف مشتريات": conn.execute("DELETE FROM purchases WHERE id = ?", (target_id,))
            elif action_type == "حذف فاتورة": conn.execute("DELETE FROM invoices WHERE id = ?", (target_id,))
            elif action_type == "حذف مستخدم":
                target_user = conn.execute("SELECT role FROM users WHERE id = ?", (target_id,)).fetchone()
                if target_user and target_user["role"] == "Admin" and st.session_state["role"] == "General_Supervisor":
                    st.error("❌ عذراً، لا تملك صلاحية حذف حساب الأدمن الأساسي!")
                else:
                    conn.execute("DELETE FROM users WHERE id = ?", (target_id,))
            
            conn.commit()
            conn.close()
            st.success("🗑️ تمت العملية بنجاح!")
            st.rerun()
        else:
            st.error("❌ كلمة السر غير صحيحة!")

@st.dialog("💳 شاشة إتمام الدفع")
def checkout_payment_dialog(b_id, g_tot):
    st.subheader(f"إجمالي الفاتورة المطلوب: {g_tot:,.2f} د.ل")
    cust_name = st.text_input("اسم الزبون:", value="زبون نقدي")
    cust_phone = st.text_input("رقم هاتف الزبون:", value="")
    
    conn = get_db_connection()
    applied_discount = 0.0
    if cust_phone.strip():
        cust_db = conn.execute("SELECT * FROM customers WHERE phone = ?", (cust_phone.strip(),)).fetchone()
        if cust_db and float(cust_db["total_purchases"]) >= 1000.0:
            st.success("🎁 يستحق الزبون خصم الولاء: **50.00 د.ل**")
            if st.checkbox("تطبيق خصم الولاء (50 دينار)"):
                applied_discount = 50.0
                
    final_tot = max(0.0, g_tot - applied_discount)
    pay_method = st.selectbox("نوع الدفع:", ["كاش (نقدي)", "شبكة / بطاقة", "آجل"])
    paid_amount = st.number_input("المبلغ المدفوع (د.ل):", min_value=0.0, value=float(final_tot), step=0.5, format="%.2f")
    
    change_due = paid_amount - final_tot
    if change_due >= 0:
        st.success(f"💵 الباقي المستحق: **{change_due:,.2f} د.ل**")
    else:
        st.error(f"⚠️ المبلغ غير كافٍ! العجز: **{abs(change_due):,.2f} د.ل**")
    
    if st.button("🖨️ تأكيد وإصدار الفاتورة", type="primary", use_container_width=True):
        if paid_amount >= final_tot or pay_method == "آجل":
            target_inv_branch = b_id if b_id != "ALL" else conn.execute("SELECT id FROM branches LIMIT 1").fetchone()["id"]
            
            can_proceed = True
            for c_item in st.session_state["cart"]:
                if c_item["id"] != 99999 and c_item["id"] != 88888:
                    db_it = conn.execute("SELECT quantity FROM items WHERE id = ?", (c_item["id"],)).fetchone()
                    if db_it and float(db_it["quantity"]) < c_item["qty"]:
                        can_proceed = False
                        st.warning(f"⚠️ الصنف ({c_item['name']}) غير متوفر بالكمية المطلوبة!")

            if can_proceed:
                cur_in = conn.cursor()
                cur_in.execute("INSERT INTO invoices (branch_id, user_id, customer_name, customer_phone, total_amount, payment_method) VALUES (?, ?, ?, ?, ?, ?)", 
                               (target_inv_branch, st.session_state["user_id"], cust_name.strip() if cust_name else "زبون نقدي", cust_phone.strip(), final_tot, pay_method))
                
                for c_item in st.session_state["cart"]:
                    if c_item["id"] != 99999 and c_item["id"] != 88888:
                        conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                
                if cust_phone.strip() and cust_name.strip() != "زبون نقدي":
                    existing_cust = cur_in.execute("SELECT id, total_purchases FROM customers WHERE phone = ?", (cust_phone.strip(),)).fetchone()
                    if existing_cust:
                        cur_in.execute("UPDATE customers SET total_purchases = total_purchases + ?, customer_name = ? WHERE id = ?", 
                                       (final_tot, cust_name.strip(), existing_cust['id']))
                    else:
                        cur_in.execute("INSERT INTO customers (customer_name, phone, total_purchases) VALUES (?, ?, ?)", 
                                       (cust_name.strip(), cust_phone.strip(), final_tot))
                        
                conn.commit()
                conn.close()
                st.session_state["cart"] = []
                st.success("🎉 تم إصدار الفاتورة بنجاح!")
                st.rerun()
            else:
                conn.close()
        else:
            st.warning("⚠️ المبلغ المدفوع أقل من الإجمالي.")
    conn.close()

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
              
              if user["role"] in ["Admin", "General_Supervisor", "Viewer"]:
                  st.session_state["allowed_menus"] = DEFAULT_MENUS
              else:
                  perms = conn.execute("SELECT allowed_menus FROM role_permissions WHERE role = ?", (user["role"],)).fetchone()
                  if perms and perms["allowed_menus"]: st.session_state["allowed_menus"] = perms["allowed_menus"].split(",")
                  else: st.session_state["allowed_menus"] = ["🏠 الرئيسية واللوحة"]
              
              log_action(user["id"], "تسجيل دخول", f"تم دخول المستخدم {user['username']}")
              conn.close(); st.rerun()
          else: 
              conn.close(); st.error("🎭 **اسم المستخدم أو كلمة المرور غير صحيحة!**")
  st.stop()

if st.session_state.get("show_welcome_dialog", False):
    welcome_user_dialog()

# --- القائمة الجانبية ---
st.sidebar.markdown("<h2 style='text-align: center; color: white;'>🥜 مجموعة أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; color: white;'><b>{st.session_state['username']} | {st.session_state['role']}</b></p>", unsafe_allow_html=True)
st.sidebar.markdown("---")

current_allowed = DEFAULT_MENUS if st.session_state["role"] in ["Admin", "General_Supervisor", "Viewer"] else st.session_state.get("allowed_menus", DEFAULT_MENUS)
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
    "🛒 نقطة البيع (POS)": {"icon": "🛒", "color": "linear-gradient(135deg, #f59e0b, #ea580c)", "desc": "شاشة الكاشير"},
    "⭐ لوحة المفضلة (1-20)": {"icon": "⭐", "color": "linear-gradient(135deg, #e11d48, #be123c)", "desc": "الأصناف المفضلة للكاشير"},
    "📦 إدارة المخزن والفروع": {"icon": "📦", "color": "linear-gradient(135deg, #3b82f6, #1d4ed8)", "desc": "جرد وإدارة وتعديل أسعار الفروع"},
    "➕ الفائض والتوالف والمرتجعات": {"icon": "➕", "color": "linear-gradient(135deg, #10b981, #047857)", "desc": "إضافة فائض وتوالف المخزن الرئيسي"},
    "🔄 تزويد الفروع والأرشيف": {"icon": "🔄", "color": "linear-gradient(135deg, #8b5cf6, #6d28d9)", "desc": "تزويد الفروع من المخزن الرئيسي"},
    "📊 التقارير والأرباح": {"icon": "📊", "color": "linear-gradient(135deg, #6366f1, #4338ca)", "desc": "الأرباح، حركة الأصناف، والفواتير"}
}

# --- محتوى الصفحات ---
if choice == "🏠 الرئيسية واللوحة":
  st.title("🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية")
  cols = st.columns(3)
  for i, (item, data) in enumerate(dashboard_cards.items()):
      if check_user_permission(item):
          with cols[i % 3]:
              c_title = get_label(item)
              st.markdown(f'''<div style="background: {data['color']}; padding: 25px 15px; border-radius: 16px; color: white; text-align: center; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); margin-bottom: 10px; min-height: 150px;"><h1 style="margin:0; font-size: 45px; color: white !important;">{data['icon']}</h1><h3 style="margin: 10px 0 5px 0; color: white !important;">{c_title}</h3><p style="margin:0; font-size: 14px; opacity: 0.9; color: white !important;">{data['desc']}</p></div>''', unsafe_allow_html=True)
              if st.button(f"دخول ➔", key=f"btn_card_{i}", on_click=set_page, args=(item,)):
                  pass
              st.markdown("<br>", unsafe_allow_html=True)

elif choice == "⭐ لوحة المفضلة (1-20)":
  st.header("⭐ لوحة الأصناف المفضلة (من 1 إلى 20)")
  if st.session_state["role"] not in ["Admin", "General_Supervisor", "Viewer"]:
      st.error("🔒 مخصصة للإدارة فقط.")
  else:
      conn = get_db_connection()
      branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict = {b["branch_name"]: b["id"] for b in branches}
      sel_b_name = st.selectbox("اختر الفرع:", list(b_dict.keys()))
      cur_b_id = b_dict[sel_b_name]
      
      items_fav = pd.read_sql("SELECT id, item_code AS 'الكود', item_name AS 'اسم الصنف', favorite_rank AS 'الرقم المفضل (1 إلى 20)' FROM items WHERE branch_id = ?", conn, params=(cur_b_id,))
      if not items_fav.empty:
          edited_fav = st.data_editor(items_fav, hide_index=True, key="fav_editor")
          if st.button("💾 حفظ الترتيب"):
              for idx, row in edited_fav.iterrows():
                  conn.execute("UPDATE items SET favorite_rank = ? WHERE id = ?", (row['الرقم المفضل (1 إلى 20)'], row['id']))
              conn.commit()
              st.success("🎉 تم الحفظ بنجاح!")
      conn.close()

elif choice == "⚙️ تخصيص الأزرار":
  st.header("⚙️ تخصيص مسميات القوائم والأزرار")
  if st.session_state["role"] != "Admin":
      st.error("مخصص للأدمن فقط.")
  else:
      conn = get_db_connection()
      with st.form("custom_label_form"):
          orig_sel = st.selectbox("اختر القائمة للتعديل:", DEFAULT_MENUS)
          current_val = get_label(orig_sel)
          new_custom_name = st.text_input("الاسم الجديد:", value=current_val)
          if st.form_submit_button("💾 حفظ التعديل"):
              conn.execute("INSERT OR REPLACE INTO custom_labels (original_name, custom_name) VALUES (?, ?)", (orig_sel, new_custom_name.strip()))
              conn.commit()
              st.success("🎉 تم الحفظ!")
      conn.close()

elif choice == "⚙️ الجرد والتصفير السنوي":
  st.header("⚙️ الجرد والعمليات السنوية والتصفير الشامل")
  if st.session_state["role"] not in ["Admin", "General_Supervisor", "Viewer"]:
      st.error("مخصص للإدارة العليا فقط.")
  else:
      conn = get_db_connection()
      branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict = {b["branch_name"]: b["id"] for b in branches}
      
      with st.form("annual_inventory_form"):
          target_scope = st.selectbox("النطاق:", ["🌐 كل الفروع والمخازن"] + list(b_dict.keys()))
          opt_sales = st.checkbox("تصفير المبيعات والفواتير")
          opt_purch = st.checkbox("تصفير حركات المشتريات")
          opt_stock = st.checkbox("تصفير المخزون إلى الصفر")
          admin_pass_inv = st.text_input("🔒 كلمة السر للتأكيد:", type="password")
          
          if st.form_submit_button("🚨 تنفيذ التصفير", type="primary"):
              if verify_admin_password(admin_pass_inv):
                  cur_inv = conn.cursor()
                  scope_id = "ALL" if target_scope == "🌐 كل الفروع والمخازن" else b_dict.get(target_scope, "ALL")
                  if opt_sales:
                      if scope_id == "ALL": cur_inv.execute("DELETE FROM invoices")
                      else: cur_inv.execute("DELETE FROM invoices WHERE branch_id = ?", (scope_id,))
                  if opt_stock:
                      if scope_id == "ALL": cur_inv.execute("UPDATE items SET quantity = 0")
                      else: cur_inv.execute("UPDATE items SET quantity = 0 WHERE branch_id = ?", (scope_id,))
                  conn.commit()
                  st.success("🎉 تمت عملية التصفير بنجاح!")
              else:
                  st.error("❌ كلمة السر غير صحيحة!")
      conn.close()

elif choice == "📁 استيراد Excel":
  st.header("📁 استيراد وتحديث الأصناف عبر Excel")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  with st.form("excel_import_seq_form"):
      sel_target_branch = st.selectbox("الفرع المستهدف:", ["🌐 تعميم لكافة الفروع"] + list(b_dict.keys()))
      up_excel = st.file_uploader("اختر ملف الإكسيل (.xlsx)", type=["xlsx", "xls"])
      
      if st.form_submit_button("📥 تنفيذ الاستيراد"):
          if up_excel:
              try:
                  df_exc = pd.read_excel(up_excel, usecols=[0, 1, 2, 3, 4, 5])
                  cur_ex = conn.cursor()
                  count_imp = 0
                  target_ids = list(b_dict.values()) if sel_target_branch == "🌐 تعميم لكافة الفروع" else [b_dict[sel_target_branch]]
                  
                  for idx, row in df_exc.iterrows():
                      if row.isna().all(): continue
                      code_val, name_val = row.iloc[0], row.iloc[1]
                      if pd.isna(code_val) or pd.isna(name_val): continue
                      code = str(code_val).strip()
                      name = str(name_val).strip()
                      if code.lower() in ["nan", "code", "كود"] or name.lower() in ["nan", "name", "اسم"]: continue
                      
                      try: qty = float(row.iloc[2]) if pd.notna(row.iloc[2]) else 0.0
                      except: qty = 0.0
                      try: b_pr = float(row.iloc[3]) if pd.notna(row.iloc[3]) else 0.0
                      except: b_pr = 0.0
                      try: s_pr = float(row.iloc[4]) if pd.notna(row.iloc[4]) else 0.0
                      except: s_pr = 0.0
                      
                      for tid in target_ids:
                          exist_item = cur_ex.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (tid, code)).fetchone()
                          if exist_item:
                              cur_ex.execute("UPDATE items SET quantity = ?, buy_price = ?, sale_price = ? WHERE id = ?", (qty, b_pr, s_pr, exist_item['id']))
                          else:
                              cur_ex.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)", 
                                             (tid, code, name, qty, b_pr, s_pr, b_pr))
                      count_imp += 1
                  conn.commit()
                  st.success(f"🎉 تم استيراد ({count_imp}) صنف بنجاح!")
              except Exception as e:
                  st.error(f"خطأ في الملف: {e}")
  conn.close()

elif choice == "🏢 إدارة الفروع":
  st.header("🏢 إدارة وتعديل وحذف الفروع")
  conn = get_db_connection()
  with st.expander("➕ إضافة فرع أو مخزن جديد"):
      with st.form("new_branch_form", clear_on_submit=True):
          nb_name = st.text_input("اسم الفرع أو المخزن:")
          nb_type = st.selectbox("النوع:", ["فرع", "مخزن"])
          if st.form_submit_button("💾 حفظ") and nb_name:
              try:
                  conn.execute("INSERT INTO branches (branch_name, branch_type) VALUES (?, ?)", (nb_name.strip(), nb_type))
                  conn.commit()
                  st.success("🎉 تم إضافة الفرع بنجاح!")
                  st.rerun()
              except:
                  st.error("⚠️ الاسم موجود مسبقاً.")
  
  branches_list = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
  for b in branches_list:
      with st.form(f"branch_edit_{b['id']}"):
          col1, col2, col3 = st.columns([2, 1, 1])
          with col1: new_bn = st.text_input("الاسم:", value=b["branch_name"])
          with col2: new_bt = st.selectbox("النوع:", ["فرع", "مخزن"], index=0 if b["branch_type"]=="فرع" else 1)
          with col3:
              st.markdown("<br>", unsafe_allow_html=True)
              if st.form_submit_button("💾 حفظ"):
                  conn.execute("UPDATE branches SET branch_name=?, branch_type=? WHERE id=?", (new_bn.strip(), new_bt, b['id']))
                  conn.commit()
                  st.success("🎉 تم التحديث!")
                  st.rerun()
  conn.close()

elif choice == "📦 إدارة المخزن والفروع":
  st.header("📦 إدارة المخزن والفروع (إضافة أصناف يدوياً وتعديل الأسعار بدون تعميم)")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  sel_b_name = st.selectbox("اختر الفرع أو المخزن الرئيسي:", list(b_dict.keys()))
  current_b_id = b_dict[sel_b_name]
  
  with st.expander("➕ إضافة صنف جديد يدوياً لهذا الفرع"):
      with st.form("manual_add_item", clear_on_submit=True):
          m_code = st.text_input("كود الصنف:")
          m_name = st.text_input("اسم الصنف:")
          m_qty = st.number_input("الكمية المبدئية (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
          m_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=0.0, step=0.5, format="%.2f")
          m_sale = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=0.0, step=0.5, format="%.2f")
          if st.form_submit_button("💾 حفظ الصنف الجديد") and m_code and m_name:
              try:
                  conn.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)",
                               (current_b_id, m_code.strip(), m_name.strip(), m_qty, m_buy, m_sale, m_buy))
                  conn.commit()
                  st.success("🎉 تم إضافة الصنف يدوياً بنجاح!")
                  st.rerun()
              except:
                  st.error("⚠️ خطأ أو كود الصنف موجود مسبقاً في هذا الفرع.")

  items_df = pd.read_sql("SELECT id, item_code AS 'الكود', item_name AS 'اسم الصنف', quantity AS 'الكمية', sale_price AS 'سعر البيع', buy_price AS 'سعر الشراء' FROM items WHERE branch_id = ?", conn, params=(current_b_id,))
  if not items_df.empty:
      edited_items = st.data_editor(items_df, hide_index=True, key="inv_editor_indep")
      if st.button("💾 حفظ تعديلات هذا الفرع فقط (بدون تعميم)"):
          for idx, row in edited_items.iterrows():
              conn.execute("UPDATE items SET item_code=?, item_name=?, quantity=?, buy_price=?, sale_price=? WHERE id=?", 
                           (row['الكود'], row['اسم الصنف'], row['الكمية'], row['سعر الشراء'], row['سعر البيع'], row['id']))
          conn.commit()
          st.success("🎉 تم حفظ التعديلات للفرع بشكل مستقل تماماً!")
          st.rerun()
      st.download_button("📥 تصدير لـ Excel", data=to_excel(items_df), file_name="branch_inventory.xlsx")
  else:
      st.info("لا توجد أصناف في هذا الفرع حالياً.")
  conn.close()

elif choice == "💰 المصروفات":
  st.header("💰 تسجيل المصروفات وإدارة حذفها مع إجمالي المبالغ")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  with st.form("expense_form", clear_on_submit=True):
      exp_type = st.radio("نوع المصروف:", ["خاص بفرع معين", "🌍 مصروف المخزن الرئيسي (يُسجل كإجمالي بالمخزن ويُقسَم نصيب كل فرع بدقة وتلقائية)"])
      sel_b_name = st.selectbox("اختر الفرع:", list(b_dict.keys())) if exp_type == "خاص بفرع معين" else ""
      exp_amount = st.number_input("المبلغ الإجمالي (د.ل):", min_value=0.0, value=0.0, step=0.5)
      exp_desc = st.text_input("البيان (مثال: صيانة المخزن، فاتورة نقل عامة..):")
      exp_date_in = st.date_input("تاريخ المصروف الفعلي:", value=datetime.now())
      
      if st.form_submit_button("💾 حفظ المصروف وإثباته بالسجلات"):
          if exp_amount > 0 and exp_desc:
              cur_ex = conn.cursor()
              date_str = exp_date_in.strftime('%Y-%m-%d')
              if exp_type == "خاص بفرع معين":
                  cur_ex.execute("INSERT INTO expenses (branch_id, amount, description, is_general_store, expense_date) VALUES (?, ?, ?, 0, ?)", (b_dict[sel_b_name], exp_amount, exp_desc.strip(), date_str))
              else:
                  total_branches_count = len(branches)
                  # حساب نصيب كل فرع من القسمة العادلة
                  share_per_branch = exp_amount / total_branches_count if total_branches_count > 0 else exp_amount
                  cur_ex.execute("INSERT INTO expenses (branch_id, amount, description, is_general_store, expense_date) VALUES (NULL, ?, ?, 1, ?)", (exp_amount, f"[مصروف مخزن رئيسي إجمالي - نصيب الفروع: {share_per_branch:,.2f} لكل فرع] {exp_desc.strip()}", date_str))
              conn.commit()
              st.success("💸 تم حفظ المصروف وتقسيم الحصص بالتساوي على الفروع بنجاح تام!")
              st.rerun()
  
  exp_df = pd.read_sql("SELECT expenses.id AS 'رقم', IFNULL(branches.branch_name, '🌍 مصروف مخزن رئيسي (إجمالي وتوزيع عادل)') AS 'الجهة / الفرع', expenses.amount AS 'المبلغ', expenses.description AS 'البيان', expenses.expense_date AS 'التاريخ' FROM expenses LEFT JOIN branches ON expenses.branch_id = branches.id ORDER BY expenses.id DESC", conn)
  if not exp_df.empty:
      total_exp = exp_df["المبلغ"].sum()
      st.dataframe(exp_df, use_container_width=True)
      st.markdown(f"### 📌 إجمالي المصروفات المسجلة: <span style='color: #0284c7;'>{total_exp:,.2f} د.ل</span>", unsafe_allow_html=True)
      
      st.download_button("📥 تصدير المصروفات لـ Excel", data=to_excel(exp_df), file_name="expenses.xlsx")
      
      st.markdown("---")
      del_exp_id = st.selectbox("اختر رقم المصروف للحذف (إذا أردت مسحه):", exp_df["رقم"].tolist())
      if st.button("🗑️ حذف المصروف المختار نهائياً", type="primary"):
          admin_confirm_dialog("حذف مصروف", del_exp_id)
  conn.close()

elif choice == "➕ الفائض والتوالف والمرتجعات":
  st.header("➕ الفائض والتوالف (إدارة مرتجعات الفروع وتوالفها العائدة للمخزن الرئيسي)")
  conn = get_db_connection()
  
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  sel_b_name = st.selectbox("اختر الفرع أو المخزن الرئيسي:", list(b_dict.keys()))
  current_b_id = b_dict[sel_b_name]
  
  operation_type = st.radio("نوع العملية:", ["➕ إضافة فائض صنف", "♻️ تسجيل توالف أو مرتجع راجع للمخزن الرئيسي"])
  items_list = conn.execute("SELECT id, item_code, item_name, sale_price FROM items WHERE branch_id = ?", (current_b_id,)).fetchall()
  
  if items_list:
      i_opts = {f"[{i['item_code']}] {i['item_name']}": i for i in items_list}
      with st.form("surplus_return_form", clear_on_submit=True):
          chosen_lbl = st.selectbox("اختر الصنف:", list(i_opts.keys()))
          qty_val = st.number_input("الكمية (كجم بالكسور):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
          
          if st.form_submit_button("💾 تنفيذ واعتماد العملية"):
              if qty_val > 0:
                  sel_item = i_opts[chosen_lbl]
                  conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (qty_val, sel_item['id']))
                  conn.commit()
                  st.success("🚀 تمت عملية الفائض أو تسجيل التوالف والمرتجع بنجاح!")
                  st.rerun()
  else:
      st.info("لا توجد أصناف مسجلة.")
  conn.close()

elif choice == "🔄 تزويد الفروع والأرشيف":
  st.header("🔄 تزويد الفروع من المخزن الرئيسي (بفواتير تزويد مسجلة وموثقة للرجوع إليها)")
  conn = get_db_connection()
  
  tab_tr1, tab_tr2 = st.tabs(["🚀 تزويد بضاعة للفرع", "📋 سجل فواتير التزويد السابقة"])
  with tab_tr1:
      main_store = conn.execute("SELECT id, branch_name FROM branches WHERE branch_type = 'مخزن' LIMIT 1").fetchone()
      if main_store:
          main_id = main_store["id"]
          other_branches = conn.execute("SELECT id, branch_name FROM branches WHERE id != ?", (main_id,)).fetchall()
          b_opts = {b["branch_name"]: b["id"] for b in other_branches}
          sel_target_b = st.selectbox("اختر الفرع المستهدف لتزويده:", list(b_opts.keys()))
          target_b_id = b_opts[sel_target_b]
          
          if "transfer_cart" not in st.session_state: st.session_state["transfer_cart"] = []
          
          main_items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND quantity > 0", (main_id,)).fetchall()
          m_opts = {f"[{i['item_code']}] {i['item_name']} (متاح بالمخزن: {i['quantity']} كجم)": i for i in main_items} if main_items else {}
          
          with st.form("add_transfer_item_form", clear_on_submit=True):
              if m_opts:
                  chosen_m_label = st.selectbox("اختر الصنف من المخزن الرئيسي:", list(m_opts.keys()))
                  t_qty = st.number_input("الكمية المراد إرسالها (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
                  if st.form_submit_button("➕ إضافة الصنف إلى سلة التزويد"):
                      if t_qty > 0:
                          it_obj = m_opts[chosen_m_label]
                          st.session_state["transfer_cart"].append({
                              "id": it_obj['id'], "code": it_obj['item_code'], "name": it_obj['item_name'], "qty": t_qty,
                              "buy_price": it_obj['buy_price'], "sale_price": it_obj['sale_price'], "avg_cost": it_obj['avg_cost'],
                              "expiry": it_obj['expiry_date'], "no_expiry": it_obj['no_expiry']
                          })
                          st.success("✅ تمت الإضافة للسلة!")
                          st.rerun()
              else:
                  st.warning("المخزن الرئيسي فارغ.")
                  
          if st.session_state["transfer_cart"]:
              st.dataframe(pd.DataFrame(st.session_state["transfer_cart"])[["code", "name", "qty"]], use_container_width=True)
              if st.button("🚀 حفظ وإنهاء وإرسال فاتورة التزويد للفرع", type="primary"):
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
                  
                  cur_tr.execute("INSERT INTO transfer_logs (from_branch_id, to_branch_id, transfer_type, items_details, status) VALUES (?, ?, 'تزويد بضاعة', ?, 'مكتملة')",
                                (main_id, target_b_id, " - ".join(details_list)))
                  conn.commit()
                  st.session_state["transfer_cart"] = []
                  st.success("🎉 تم تزويد الفرع بنجاح وإصدار الفاتورة وتوثيقها!")
                  st.rerun()
              if st.button("🗑️ تفريغ السلة"):
                  st.session_state["transfer_cart"] = []
                  st.rerun()
  with tab_tr2:
      st.subheader("📋 أرشيف فواتير التزويد لكل فرع (لمعرفة ما تم تزويده ومتى)")
      logs_df = pd.read_sql("SELECT transfer_logs.id AS 'رقم الفاتورة', b1.branch_name AS 'من', b2.branch_name AS 'إلى الفرع', transfer_logs.items_details AS 'الأصناف والكميات المزودة', transfer_logs.transfer_date AS 'التاريخ والوقت' FROM transfer_logs LEFT JOIN branches b1 ON transfer_logs.from_branch_id=b1.id LEFT JOIN branches b2 ON transfer_logs.to_branch_id=b2.id ORDER BY transfer_logs.id DESC", conn)
      if not logs_df.empty:
          st.dataframe(logs_df, use_container_width=True)
          st.download_button("📥 تصدير سجل تزويد الفروع لـ Excel", data=to_excel(logs_df), file_name="branch_supplies.xlsx")
      else:
          st.info("لا توجد فواتير تزويد سجلت بعد.")
  conn.close()

elif choice == "📥 المشتريات والموردين":
  st.header("📥 المشتريات والموردين (متوسط التكلفة الحقيقي وتقرير الدائن والمدين لكل تاجر)")
  conn = get_db_connection()
  tab_p1, tab_p2, tab_p3 = st.tabs(["➕ فاتورة مشتريات (تفريغ تلقائي)", "👥 الموردين وحسابات الدائن والمدين", "📋 سجل المشتريات"])
  
  with tab_p1:
      branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict = {b["branch_name"]: b["id"] for b in branches}
      suppliers = conn.execute("SELECT id, supplier_name FROM suppliers").fetchall()
      s_dict = {s["supplier_name"]: s["id"] for s in suppliers} if suppliers else {}
      
      p_branch_name = st.selectbox("الفرع المستلم:", list(b_dict.keys()), key="pb")
      p_supp_name = st.selectbox("المورد / التاجر:", list(s_dict.keys()) if s_dict else ["لا توجد موردين"], key="ps")
      inv_num_in = st.text_input("رقم فاتورة المورد:")
      p_type = st.radio("نوع الشراء:", ["كاش", "آجل"], key="pt")
      p_date = st.date_input("التاريخ:", value=datetime.now())
      
      if "purch_cart" not in st.session_state: st.session_state["purch_cart"] = []
      all_db_items = conn.execute("SELECT id, item_code, item_name, buy_price FROM items WHERE branch_id = ?", (b_dict[p_branch_name],)).fetchall()
      item_opts = {f"[{i['item_code']}] {i['item_name']}": i for i in all_db_items} if all_db_items else {}
      
      with st.form("add_p_item", clear_on_submit=True):
          if item_opts:
              chosen_ik = st.selectbox("الصنف:", list(item_opts.keys()))
              p_qty = st.number_input("الكمية (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
              p_price = st.number_input("سعر شراء الكيلو (د.ل):", min_value=0.0, value=0.0, step=0.5, format="%.2f")
              if st.form_submit_button("➕ إضافة للسلة"):
                  if p_qty > 0:
                      it_obj = item_opts[chosen_ik]
                      st.session_state["purch_cart"].append({"id": it_obj['id'], "code": it_obj['item_code'], "name": it_obj['item_name'], "qty": p_qty, "price": p_price, "total": p_qty * p_price})
                      st.success("✅ تمت الإضافة!")
                      st.rerun()
      if st.session_state["purch_cart"]:
          df_pc = pd.DataFrame(st.session_state["purch_cart"])[["code", "name", "qty", "price", "total"]]
          p_g_tot = sum([x["total"] for x in st.session_state["purch_cart"]])
          st.dataframe(df_pc, use_container_width=True)
          st.markdown(f"### 📌 إجمالي سلة المشتريات: <span style='color: #0284c7;'>{p_g_tot:,.2f} د.ل</span>", unsafe_allow_html=True)
          
          if st.button("💾 حفظ الفاتورة (تفريغ تلقائي للسلة)", type="primary"):
              if p_supp_name != "لا توجد موردين" and inv_num_in.strip():
                  supp_id = s_dict[p_supp_name]
                  cur_p = conn.cursor()
                  details_list = []
                  for p_item in st.session_state["purch_cart"]:
                      old_qty = cur_p.execute("SELECT quantity FROM items WHERE id = ?", (p_item['id'],)).fetchone()["quantity"]
                      old_avg = cur_p.execute("SELECT avg_cost FROM items WHERE id = ?", (p_item['id'],)).fetchone()["avg_cost"] or cur_p.execute("SELECT buy_price FROM items WHERE id = ?", (p_item['id'],)).fetchone()["buy_price"]
                      new_total_qty = old_qty + p_item['qty']
                      new_avg_cost = ((old_qty * old_avg) + (p_item['qty'] * p_item['price'])) / new_total_qty if new_total_qty > 0 else p_item['price']
                      
                      cur_p.execute("UPDATE items SET quantity = quantity + ?, buy_price = ?, avg_cost = ? WHERE id = ?", (p_item['qty'], p_item['price'], new_avg_cost, p_item['id']))
                      details_list.append(f"{p_item['name']} ({p_item['qty']} كجم بسعر {p_item['price']})")
                  
                  cur_p.execute("INSERT INTO purchases (branch_id, supplier_id, supplier_name, invoice_number, total_cost, payment_type, items_details, invoice_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (b_dict[p_branch_name], supp_id, p_supp_name, inv_num_in.strip(), p_g_tot, p_type, " - ".join(details_list), p_date.strftime('%Y-%m-%d')))
                  if p_type == "آجل":
                      cur_p.execute("UPDATE suppliers SET balance = balance + ? WHERE id = ?", (p_g_tot, supp_id))
                  conn.commit()
                  st.session_state["purch_cart"] = []
                  st.success("🎉 تم الحفظ وتفريغ السلة تلقائياً بنجاح!")
                  st.rerun()
              else:
                  st.warning("⚠️ اختر المورد واكتب رقم الفاتورة.")
  with tab_p2:
      st.subheader("👥 تقرير الدائن والمدين وإدارة الحذف")
      with st.form("new_sup", clear_on_submit=True):
          sname = st.text_input("اسم المورد الجديد:")
          sphone = st.text_input("الهاتف:")
          if st.form_submit_button("💾 حفظ المورد") and sname:
              try:
                  conn.execute("INSERT INTO suppliers (supplier_name, phone) VALUES (?, ?)", (sname.strip(), sphone.strip()))
                  conn.commit()
                  st.success("🎉 تم الحفظ!")
                  st.rerun()
              except: st.error("⚠️ موجود مسبقاً.")
      supp_df = pd.read_sql("SELECT id, supplier_name AS 'اسم التاجر / المورد', phone AS 'الهاتف', balance AS 'المستحقات (دائن / مدين) د.ل' FROM suppliers", conn)
      if not supp_df.empty: 
          tot_debts = supp_df["المستحقات (دائن / مدين) د.ل"].sum()
          st.dataframe(supp_df, use_container_width=True)
          st.markdown(f"### 📌 إجمالي الديون والمستحقات للموردين: <span style='color: #0284c7;'>{tot_debts:,.2f} د.ل</span>", unsafe_allow_html=True)
          st.download_button("📥 تصدير تقرير الديون لـ Excel", data=to_excel(supp_df), file_name="suppliers_debts.xlsx")
          
          del_sup_id = st.selectbox("اختر رقم المورد للحذف:", supp_df["id"].tolist())
          if st.button("🗑️ حذف المورد المختار", type="primary"):
              admin_confirm_dialog("حذف مورد", del_sup_id)
  with tab_p3:
      p_df = pd.read_sql("SELECT purchases.id AS 'مسلسل', purchases.invoice_number AS 'رقم الفاتورة', branches.branch_name AS 'الفرع', purchases.supplier_name AS 'المورد', purchases.total_cost AS 'الإجمالي', purchases.invoice_date AS 'التاريخ' FROM purchases LEFT JOIN branches ON purchases.branch_id=branches.id ORDER BY purchases.id DESC", conn)
      if not p_df.empty: 
          tot_purch = p_df["الإجمالي"].sum()
          st.dataframe(p_df, use_container_width=True)
          st.markdown(f"### 📌 إجمالي المشتريات المسجلة: <span style='color: #0284c7;'>{tot_purch:,.2f} د.ل</span>", unsafe_allow_html=True)
          
          del_p_id = st.selectbox("اختر رقم مسلسل الفاتورة للحذف:", p_df["مسلسل"].tolist())
          if st.button("🗑️ حذف فاتورة المشتريات المحددة", type="primary"):
              admin_confirm_dialog("حذف مشتريات", del_p_id)
  conn.close()

elif choice == "🥜 التحميص والخلط والمكسرات":
  st.header("🥜 التحميص والخلط (الفرق بين خلط المكسرات وتحميصها ومتوسط التكلفة)")
  conn = get_db_connection()
  
  main_store_row = conn.execute("SELECT id FROM branches WHERE branch_type='مخزن' LIMIT 1").fetchone()
  main_s_id = main_store_row["id"] if main_store_row else 1
  store_items = conn.execute("SELECT item_code, item_name, quantity, buy_price, avg_cost FROM items WHERE branch_id = ? AND quantity > 0", (main_s_id,)).fetchall()
  
  mix_tab, roast_tab = st.tabs(["🥜 خلط المكسرات (دمج خامات وإنتاج صنف مكسرات مشكلة بمتوسط التكلفة)", "🔥 التحميص (فقد وزني: استلام وزن وعودة وزن أقل بسعر متكود)"])
  
  with mix_tab:
      st.info("💡 الخلط: دمج عدة خامات (لوز، فستق..) بسعر تكلفتها، وخصمها من المخزن، وإضافة الوزن والمجموع إلى صنف 'مكسرات مشكلة' الموجود مسبقاً بنفس كوده مع حساب متوسط التكلفة الجديد.")
      if store_items:
          item_choices = {f"[{i['item_code']}] {i['item_name']} (متاح: {i['quantity']} كجم)": i for i in store_items}
          if "mix_list" not in st.session_state: st.session_state["mix_list"] = []
          
          with st.form("mix_f", clear_on_submit=True):
              sel_c = st.selectbox("اختر الخام للخلط:", list(item_choices.keys()))
              mqty = st.number_input("الوزن المستخدم من الخامات (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
              if st.form_submit_button("➕ إضافة الخام للخلطة"):
                  if mqty > 0:
                      it_obj = item_choices[sel_c]
                      st.session_state["mix_list"].append({"code": it_obj['item_code'], "name": it_obj['item_name'], "qty": mqty, "cost": it_obj['avg_cost'] or it_obj['buy_price']})
                      st.success("✅ تمت الإضافة لقائمة الخلط!")
                      st.rerun()
          if st.session_state["mix_list"]:
              st.dataframe(pd.DataFrame(st.session_state["mix_list"])[["code", "name", "qty"]], use_container_width=True)
              with st.form("fin_mix"):
                  res_name = st.selectbox("اختر الصنف الناتج النهائي بعد الخلط (مثل: مكسرات مشكلة مسجلة):", [i['item_name'] for i in store_items])
                  if st.form_submit_button("⚙️ اعتماد الخلطة وخصم الخامات وتحديث صنف المكسرات المشكلة"):
                      cur_mx = conn.cursor()
                      total_cost = sum([x['qty'] * x['cost'] for x in st.session_state["mix_list"]])
                      total_weight = sum([x['qty'] for x in st.session_state["mix_list"]])
                      new_avg = total_cost / total_weight if total_weight > 0 else 0
                      
                      for m in st.session_state["mix_list"]:
                          cur_mx.execute("UPDATE items SET quantity = quantity - ? WHERE branch_id = ? AND item_code = ?", (m['qty'], main_s_id, m['code']))
                      cur_mx.execute("UPDATE items SET quantity = quantity + ?, avg_cost = ? WHERE branch_id = ? AND item_name = ?", (total_weight, new_avg, main_s_id, res_name))
                      conn.commit()
                      st.session_state["mix_list"] = []
                      st.success("🎉 تمت عملية الخلط وحساب متوسط التكلفة وتحديث الأصناف بنجاح تام!")
                      st.rerun()
  with roast_tab:
      st.info("🔥 التحميص: عملية يفقد فيها الصنف وزناً (مثال: استلام 10 كجم تعود بعد التحميص 9 كجم). يتم خصم الخام بالكامل وإضافة الوزن المحمص الفعلي للصنف المتكود.")
      if store_items:
          with st.form("roast_f", clear_on_submit=True):
              sel_r = st.selectbox("اختر الصنف المراد تحميصه:", list(item_choices.keys()))
              raw_w = st.number_input("الوزن الخام قبل التحميص (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
              roasted_w = st.number_input("الوزن الفعلي بعد التحميص (يقل الوزن):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
              r_price = st.number_input("سعر بيع المحمص (د.ل):", min_value=0.0, value=0.0, step=0.5, format="%.2f")
              if st.form_submit_button("🔥 اعتماد التحميص وخصم الخام وإضافة الوزن المحمص الجديد"):
                  if raw_w > 0 and roasted_w > 0:
                      r_obj = item_choices[sel_r]
                      cur_r = conn.cursor()
                      cur_r.execute("UPDATE items SET quantity = quantity - ? WHERE branch_id = ? AND item_code = ?", (raw_w, main_s_id, r_obj['item_code']))
                      cur_r.execute("UPDATE items SET quantity = quantity + ?, sale_price = ? WHERE branch_id = ? AND item_code = ?", (roasted_w, r_price, main_s_id, r_obj['item_code']))
                      conn.commit()
                      st.success("🎉 تمت عملية التحميص وتحديث الأرصدة بنجاح!")
                      st.rerun()
  conn.close()

elif choice == "📊 التقارير والأرباح":
  st.header("📊 مركز التقارير، الأرباح، وفواتير المبيعات مع إجمالي التوتال")
  conn = get_db_connection()
  
  tab_r1, tab_r2, tab_r3, tab_r4 = st.tabs(["📊 الأرباح والخسائر", "📦 حركة صنف", "📈 مبيعات الفترات", "🖨️ طباعة وتنزيل الفواتير"])
  with tab_r1:
      branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
      b_dict = {b["branch_name"]: b["id"] for b in branches}
      sel_rep = st.selectbox("الفرع:", ["🌐 إجمالي الكل"] + list(b_dict.keys()))
      t_id = "ALL" if sel_rep == "🌐 إجمالي الكل" else b_dict[sel_rep]
      
      sales = conn.execute("SELECT SUM(total_amount) FROM invoices" + ("" if t_id=="ALL" else " WHERE branch_id = ?"), (() if t_id=="ALL" else (t_id,))).fetchone()[0] or 0.0
      purch = conn.execute("SELECT SUM(total_cost) FROM purchases" + ("" if t_id=="ALL" else " WHERE branch_id = ?"), (() if t_id=="ALL" else (t_id,))).fetchone()[0] or 0.0
      exps = conn.execute("SELECT SUM(amount) FROM expenses" + ("" if t_id=="ALL" else " WHERE branch_id = ?"), (() if t_id=="ALL" else (t_id,))).fetchone()[0] or 0.0
      net = sales - (purch + exps)
      
      c1, c2, c3, c4 = st.columns(4)
      with c1: st.metric("إجمالي المبيعات", f"{sales:,.2f}")
      with c2: st.metric("إجمالي المشتريات", f"{purch:,.2f}")
      with c3: st.metric("إجمالي المصروفات", f"{exps:,.2f}")
      with c4: st.metric("صافي الربح", f"{net:,.2f}")
  with tab_r2:
      all_items = conn.execute("SELECT DISTINCT item_code, item_name FROM items").fetchall()
      if all_items:
          it_dict = {f"[{i['item_code']}] {i['item_name']}": i['item_code'] for i in all_items}
          sel_it = st.selectbox("الصنف:", list(it_dict.keys()))
          if st.button("عرض الأرصدة بالفروع"):
              res = conn.execute("SELECT branches.branch_name, items.quantity, items.sale_price FROM items LEFT JOIN branches ON items.branch_id=branches.id WHERE items.item_code = ?", (it_dict[sel_it],)).fetchall()
              tot_qty = sum([r['quantity'] for r in res])
              for r in res: st.write(f"- الفرع: **{r['branch_name']}** | الرصيد المتاح: **{r['quantity']} كجم** | السعر: {r['sale_price']} د.ل")
              st.markdown(f"### 📌 إجمالي الكمية المتاحة في كافة الفروع: <span style='color: #0284c7;'>{tot_qty:,.2f} كجم</span>", unsafe_allow_html=True)
  with tab_r3:
      df_p = pd.read_sql("SELECT invoices.id AS 'الفاتورة', branches.branch_name AS 'الفرع', invoices.customer_name AS 'الزبون', invoices.total_amount AS 'المبلغ', invoices.created_at AS 'الوقت' FROM invoices LEFT JOIN branches ON invoices.branch_id=branches.id ORDER BY invoices.id DESC", conn)
      if not df_p.empty:
          tot_sales_period = df_p["المبلغ"].sum()
          st.dataframe(df_p, use_container_width=True)
          st.markdown(f"### 📌 إجمالي المبيعات بالفترة: <span style='color: #0284c7;'>{tot_sales_period:,.2f} د.ل</span>", unsafe_allow_html=True)
          st.download_button("📥 تصدير لـ Excel", data=to_excel(df_p), file_name="sales.xlsx")
  with tab_r4:
      all_invs = conn.execute("SELECT invoices.id, branches.branch_name, invoices.customer_name, invoices.total_amount, invoices.created_at FROM invoices LEFT JOIN branches ON invoices.branch_id=branches.id ORDER BY invoices.id DESC LIMIT 50").fetchall()
      if all_invs:
          inv_opts = {f"فاتورة #{inv['id']} - {inv['branch_name']} - {inv['customer_name']} - {inv['total_amount']} د.ل": inv['id'] for inv in all_invs}
          chosen_id = inv_opts[st.selectbox("اختر الفاتورة لتنزيلها أو طباعتها:", list(inv_opts.keys()))]
          inv_data = conn.execute("SELECT invoices.*, branches.branch_name FROM invoices LEFT JOIN branches ON invoices.branch_id=branches.id WHERE invoices.id = ?", (chosen_id,)).fetchone()
          if inv_data:
              st.markdown(f"""
                  <div style="background: white; padding: 20px; border: 2px solid #0284c7; border-radius: 10px; max-width: 400px; margin: auto;">
                      <h3 style="text-align: center; color: #0284c7; margin:0;">🥜 مجموعة أبو زيد التجارية</h3>
                      <p style="text-align: center;">فرع: <b>{inv_data['branch_name']}</b> | فاتورة #{inv_data['id']}</p>
                      <p>الزبون: <b>{inv_data['customer_name']}</b> ({inv_data['customer_phone']})</p>
                      <h4 style="text-align: right; color: #000;">الإجمالي: {inv_data['total_amount']:,.2f} د.ل</h4>
                  </div>
              """, unsafe_allow_html=True)
              txt = f"مجموعة أبو زيد التجارية\nفرع: {inv_data['branch_name']}\nرقم الفاتورة: #{inv_data['id']}\nالزبون: {inv_data['customer_name']}\nالإجمالي: {inv_data['total_amount']:,.2f} د.ل\nالتاريخ: {inv_data['created_at']}"
              st.download_button("📥 تنزيل الفاتورة ملف نصي", data=txt, file_name=f"invoice_{inv_data['id']}.txt", mime="text/plain", use_container_width=True)
  conn.close()

elif choice == "👥 إدارة المستخدمين":
  st.header("👥 إدارة المستخدمين والصلاحيات (وحماية الأدمن)")
  conn = get_db_connection()
  with st.form("new_u", clear_on_submit=True):
      uname = st.text_input("اسم المستخدم:")
      uphone = st.text_input("الهاتف:")
      upass = st.text_input("كلمة المرور:")
      urole = st.selectbox("الرتبة:", ["Admin", "General_Supervisor", "Branch_Supervisor", "Cashier", "Viewer"])
      if st.form_submit_button("💾 حفظ") and uname and upass:
          try:
              conn.execute("INSERT INTO users (username, phone, password, role) VALUES (?, ?, ?, ?)", (uname.strip(), uphone.strip(), upass, urole))
              conn.commit()
              st.success("🎉 تم الحفظ!")
              st.rerun()
          except: st.error("⚠️ المستخدم موجود مسبقاً.")
  
  udf = pd.read_sql("SELECT id, username AS 'المستخدم', role AS 'الرتبة' FROM users", conn)
  if not udf.empty: 
      st.dataframe(udf, use_container_width=True)
      st.markdown("---")
      del_u_id = st.selectbox("اختر المستخدم للحذف:", udf["id"].tolist(), format_func=lambda x: f"رقم: {x} - {udf[udf['id']==x]['المستخدم'].values[0]} ({udf[udf['id']==x]['الرتبة'].values[0]})")
      if st.button("🗑️ حذف المستخدم المختار", type="primary"):
          admin_confirm_dialog("حذف مستخدم", del_u_id)
  conn.close()

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير (POS)")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  sel_pos_branch = st.selectbox("الفرع:", ["🌐 إجمالي كل الفروع"] + list(b_dict.keys()))
  b_id = "ALL" if sel_pos_branch == "🌐 إجمالي كل الفروع" else b_dict[sel_pos_branch]
  
  if b_id:
      if b_id == "ALL":
          fav_items = conn.execute("SELECT * FROM items WHERE favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC").fetchall()
      else:
          fav_items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC", (b_id,)).fetchall()
      
      st.markdown("""
          <div style="background: #1e293b; color: white; padding: 10px; border-radius: 8px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; font-size: 14px;">
              <div><b>⌨️ اختصارات:</b></div>
              <div><b>[F1]</b> إتمام البيع</div>
              <div><b>[F2]</b> إعادة طباعة</div>
              <div><b>[F3]</b> تفريغ السلة</div>
              <div><b>[F10]</b> صنف سريع</div>
          </div>
      """, unsafe_allow_html=True)

      hk1, hk2, hk3, hk4 = st.columns(4)
      with hk1:
          if st.button("F1: إتمام البيع", use_container_width=True):
              if st.session_state["cart"]: checkout_payment_dialog(b_id, sum([x["total"] for x in st.session_state["cart"]]))
              else: st.warning("السلة فارغة!")
      with hk2:
          if st.button("F2: إعادة طباعة", use_container_width=True): reprint_last_invoice_dialog()
      with hk3:
          if st.button("F3: تفريغ السلة", use_container_width=True):
              st.session_state["cart"] = []
              st.rerun()
      with hk4:
          if st.button("F10: صنف سريع", use_container_width=True): fast_service_dialog()

      st.markdown("---")
      st.text_input("🔍 باركود الميزان أو الصنف:", key="barcode_scan", on_change=process_scale_barcode)
      
      col_g, col_c = st.columns([2, 1])
      with col_g:
          st.subheader("الأصناف المفضلة للكاشير")
          if fav_items:
              for item in fav_items:
                  c1, c2, c3 = st.columns([2, 1, 1])
                  with c1: st.write(f"<b>{item['item_name']}</b> (المتاح: {item['quantity']} كجم)", unsafe_allow_html=True)
                  with c2: st.write(f"{item['sale_price']} د.ل")
                  with c3:
                      with st.form(key=f"pos_q_{item['id']}", clear_on_submit=True):
                          q_in = st.number_input("كمية", min_value=0.0, value=0.0, step=0.1, format="%.2f", key=f"q_{item['id']}")
                          if st.form_submit_button("➕ إضافة"):
                              if q_in > 0:
                                  st.session_state["cart"].append({"id": item["id"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": float(q_in), "total": float(item["sale_price"]) * float(q_in)})
                                  st.rerun()
          else:
              st.info("لا توجد أصناف مفضلة (1-20).")
      with col_c:
          st.subheader("سلة المبيعات")
          if st.session_state["cart"]:
              df_c = pd.DataFrame(st.session_state["cart"])
              st.dataframe(df_c[["name", "price", "qty", "total"]], use_container_width=True)
              g_tot = sum([x["total"] for x in st.session_state["cart"]])
              st.metric("الإجمالي", f"{g_tot:,.2f} د.ل")
              if st.button("🖨️ إتمام وطباعة الفاتورة", type="primary", use_container_width=True):
                  checkout_payment_dialog(b_id, g_tot)
              if st.button("🗑️ تفريغ السلة", use_container_width=True):
                  st.session_state["cart"] = []
                  st.rerun()
          else:
              st.info("السلة فارغة.")
  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
