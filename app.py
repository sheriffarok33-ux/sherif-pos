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

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;700&display=swap');
    html, body, [class*="css"], p, span, div, label, h1, h2, h3, h4, h5, h6 { 
        font-family: 'Tajawal', sans-serif !important; 
        color: #000000 !important; 
    }
    .main { background-color: #f8fafc; }
    h1 { font-size: 24px !important; color: #0f172a !important; font-weight: 700 !important; margin-bottom: 10px; }
    h2 { font-size: 20px !important; color: #1e293b !important; font-weight: 700 !important; margin-bottom: 8px; }
    h3 { font-size: 16px !important; color: #334155 !important; font-weight: 700 !important; margin-bottom: 6px; }
    
    div.stButton > button { 
        border-radius: 6px; font-weight: 700 !important; height: 40px; 
        background: #0284c7; color: white !important; border: none; font-size: 15px !important;
    }
    div.stButton > button:hover { background: #0369a1; }
    
    [data-testid="stSidebar"] { background-color: #0f172a; }
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] span, [data-testid="stSidebar"] p { color: #ffffff !important; font-size: 15px !important; }
    [data-testid="stSidebar"] .stButton>button {
        background-color: #1e293b; color: #ffffff !important; border: 1px solid #334155;
        border-radius: 6px; padding: 8px 10px; text-align: right; font-weight: 700 !important;
        margin-bottom: 4px; font-size: 15px !important; height: auto;
    }
    [data-testid="stSidebar"] .stButton>button:hover { background-color: #0284c7; }
    
    .thermal-receipt {
        background: #ffffff; padding: 15px; border-radius: 8px; border: 1px dashed #cbd5e1;
        max-width: 380px; margin: auto; font-family: 'Tajawal', monospace !important;
    }
    </style>
""", unsafe_allow_html=True)

if not os.path.exists("item_images"): os.makedirs("item_images")
if not os.path.exists("saved_receipts"): os.makedirs("saved_receipts")

DEFAULT_MENUS = [
    "🛒 نقطة البيع (POS)",
    "🏠 الرئيسية واللوحة",
    "⭐ لوحة المفضلة (1-20)",
    "📦 إدارة المخزن والفروع",
    "➕ الفائض والتوالف والمرتجعات وتعديل السعر",
    "🔄 تزويد الفروع والأرشيف",
    "🏢 إدارة الفروع",
    "📁 استيراد Excel",
    "💰 المصروفات",
    "📥 المشتريات والموردين",
    "📊 التقارير الشاملة والأرباح",
    "⚙️ الجرد والتصفير السنوي",
    "🥜 التحميص والخلط",
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
              expiry_date TEXT DEFAULT '',
              no_expiry INTEGER DEFAULT 0,
              favorite_rank INTEGER DEFAULT 0,
              FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
          )
      """)
      cursor.execute("CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, supplier_name TEXT UNIQUE NOT NULL, phone TEXT, balance REAL DEFAULT 0.0)")
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
      cursor.execute("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, amount REAL NOT NULL, description TEXT NOT NULL, is_general_store INTEGER DEFAULT 0, expense_date TEXT, rent_months INTEGER DEFAULT 1, rent_paid_until TEXT DEFAULT '')")
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
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
          )
      """)
      cursor.execute("CREATE TABLE IF NOT EXISTS negative_sales_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, user_id INTEGER, item_name TEXT, sale_qty REAL, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
      cursor.execute("CREATE TABLE IF NOT EXISTS role_permissions (role TEXT PRIMARY KEY, allowed_menus TEXT)")
      cursor.execute("CREATE TABLE IF NOT EXISTS custom_labels (original_name TEXT PRIMARY KEY, custom_name TEXT NOT NULL)")
      cursor.execute("CREATE TABLE IF NOT EXISTS activity_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, details TEXT, log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")

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
    if role == "Cashier" and menu_name in ["🛒 نقطة البيع (POS)", "⭐ لوحة المفضلة (1-20)", "🔄 تزويد الفروع والأرشيف"]: return True
    user_id = st.session_state.get("user_id")
    if not user_id: return False
    conn = get_db_connection()
    user_row = conn.execute("SELECT custom_permissions FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if user_row and user_row["custom_permissions"]:
        if menu_name in user_row["custom_permissions"].split(","): return True
    allowed = st.session_state.get("allowed_menus", [])
    return menu_name in allowed

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
if "show_welcome_dialog" not in st.session_state: st.session_state["show_welcome_dialog"] = False
if "missing_barcode_alert" not in st.session_state: st.session_state["missing_barcode_alert"] = ""
if "success_alert_msg" not in st.session_state: st.session_state["success_alert_msg"] = ""
if "last_invoice_data" not in st.session_state: st.session_state["last_invoice_data"] = None

def set_page(page_name): 
    st.session_state["page"] = page_name
    st.rerun()

@st.dialog("🔔 تنبيه")
def success_action_dialog():
    msg = st.session_state.get("success_alert_msg", "تمت العملية بنجاح!")
    st.success(f"**{msg}**")
    if st.button("موافق", use_container_width=True, type="primary"):
        st.session_state["success_alert_msg"] = ""
        st.rerun()

@st.dialog("⚠️ تنبيه")
def missing_barcode_dialog():
    code_text = st.session_state.get("missing_barcode_alert", "")
    st.error(f"❌ عذراً، الباركود ({code_text}) غير مسجل!")
    st.info("☕ هنى روحك وبلغ المدير عن الصنف الغير موجود يا صاحبي!")
    if st.button("موافق", use_container_width=True, type="primary"):
        st.session_state["missing_barcode_alert"] = ""
        st.rerun()

@st.dialog("🌟 ترحيب")
def welcome_user_dialog():
    st.success("أهلاً بك في عائلة أبو زيد التجارية! نتمنى لك يوماً مباركاً ☕")
    if st.button("موافق", use_container_width=True, type="primary"):
        st.session_state["show_welcome_dialog"] = False
        st.rerun()

@st.dialog("🔒 تأكيد")
def admin_confirm_dialog(action_type, target_id, target_name=""):
    st.warning(f"تأكيد تنفيذ ({action_type})؟")
    admin_pass = st.text_input("الرقم السري:", type="password", key="diag_pass_input")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("تأكيد", use_container_width=True, type="primary"):
            if verify_admin_password(admin_pass):
                conn = get_db_connection()
                if action_type == "حذف فرع": conn.execute("DELETE FROM branches WHERE id = ?", (target_id,))
                elif action_type == "حذف صنف": conn.execute("DELETE FROM items WHERE id = ?", (target_id,))
                elif action_type == "حذف مصروف": conn.execute("DELETE FROM expenses WHERE id = ?", (target_id,))
                elif action_type == "حذف مشتريات": conn.execute("DELETE FROM purchases WHERE id = ?", (target_id,))
                elif action_type == "حذف فاتورة": conn.execute("DELETE FROM invoices WHERE id = ?", (target_id,))
                elif action_type == "حذف مورد": conn.execute("DELETE FROM suppliers WHERE id = ?", (target_id,))
                elif action_type == "حذف مستخدم":
                    target_user = conn.execute("SELECT role, username FROM users WHERE id = ?", (target_id,)).fetchone()
                    if target_user and (target_user["role"] == "Admin" or target_user["username"].strip().lower() == "admin"):
                        st.error("لا يمكن حذف حساب الأدمن الأساسي!")
                    else:
                        conn.execute("DELETE FROM users WHERE id = ?", (target_id,))
                conn.commit()
                conn.close()
                st.session_state["success_alert_msg"] = f"تمت عملية ({action_type}) بنجاح!"
                st.rerun()
            else:
                st.error("الرقم السري غير صحيح!")
    with col2:
        if st.button("إلغاء", use_container_width=True):
            st.rerun()

@st.dialog("🖨️ طباعة الفاتورة")
def thermal_receipt_dialog(inv_data):
    st.markdown(f"""
    <div class="thermal-receipt">
        <h3 style="text-align: center; margin:0; color:#0f172a;">مجموعة محامص أبو زيد التجارية</h3>
        <p style="text-align: center; margin:5px 0;">فرع: {inv_data['branch_name']}</p>
        <hr style="border: 1px dashed #000;">
        <p style="margin:2px 0;"><b>رقم الفاتورة:</b> #{inv_data['invoice_id']}</p>
        <p style="margin:2px 0;"><b>التاريخ:</b> {inv_data['date']}</p>
        <p style="margin:2px 0;"><b>الزبون:</b> {inv_data['customer']}</p>
        <hr style="border: 1px dashed #000;">
        <table style="width:100%; font-size:14px;">
            <tr>
                <th style="text-align:right;">الصنف</th>
                <th style="text-align:center;">كمية</th>
                <th style="text-align:left;">السعر</th>
            </tr>
    """, unsafe_allow_html=True)
    
    receipt_text_lines = [
        "مجموعة محامص أبو زيد التجارية",
        f"فرع: {inv_data['branch_name']}",
        f"رقم الفاتورة: #{inv_data['invoice_id']}",
        f"التاريخ: {inv_data['date']}",
        f"الزبون: {inv_data['customer']}",
        "-" * 30
    ]
    
    for itm in inv_data['items']:
        st.markdown(f"""
            <tr>
                <td style="text-align:right;">{itm['name']}</td>
                <td style="text-align:center;">{itm['qty']}</td>
                <td style="text-align:left;">{itm['total']:,.2f}</td>
            </tr>
        """, unsafe_allow_html=True)
        receipt_text_lines.append(f"{itm['name']} | {itm['qty']} كجم | {itm['total']:,.2f} د.ل")
        
    st.markdown(f"""
        </table>
        <hr style="border: 1px dashed #000;">
        <p style="margin:2px 0;"><b>الإجمالي:</b> {inv_data['total']:,.2f} د.ل</p>
        <p style="margin:2px 0;"><b>الدفع:</b> {inv_data['pay_method']}</p>
        <p style="margin:2px 0;"><b>المدفوع:</b> {inv_data['paid']:,.2f} د.ل</p>
        <p style="margin:2px 0;"><b>الباقي:</b> {inv_data['change']:,.2f} د.ل</p>
        <hr style="border: 1px dashed #000;">
        <p style="text-align: center; margin: 10px 0 0 0;"><b>شكراً لزيارتكم ☕</b></p>
    </div>
    """, unsafe_allow_html=True)
    
    receipt_text_lines.extend([
        "-" * 30,
        f"الإجمالي: {inv_data['total']:,.2f} د.ل",
        f"طريقة الدفع: {inv_data['pay_method']}",
        "شكراً لزيارتكم مجموعة أبو زيد التجارية"
    ])
    full_receipt_text = "\n".join(receipt_text_lines)
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("طباعة", use_container_width=True, type="primary"):
            st.success("تم إرسال الفاتورة للطابعة!")
            st.session_state["last_invoice_data"] = None
            st.rerun()
    with col2:
        st.download_button(
            label="حفظ (للواتساب)",
            data=full_receipt_text,
            file_name=f"receipt_{inv_data['invoice_id']}.txt",
            mime="text/plain",
            use_container_width=True
        )

@st.dialog("💳 إتمام الدفع")
def checkout_payment_dialog(b_id, g_tot):
    st.subheader(f"الإجمالي المطلوب: {g_tot:,.2f} د.ل")
    cust_name = st.text_input("اسم الزبون:", value="زبون نقدي")
    cust_phone = st.text_input("رقم الهاتف:", value="")
    
    conn = get_db_connection()
    applied_discount = 0.0
    if cust_phone.strip():
        cust_db = conn.execute("SELECT * FROM customers WHERE phone = ?", (cust_phone.strip(),)).fetchone()
        if cust_db and float(cust_db["total_purchases"]) >= 1000.0:
            st.success("خصم الولاء: 50.00 د.ل")
            if st.checkbox("تطبيق خصم الولاء (50 دينار)"):
                applied_discount = 50.0
                
    final_tot = max(0.0, g_tot - applied_discount)
    pay_method = st.selectbox("نوع الدفع:", ["كاش", "شبكة", "تحويل بنكي", "آجل"])
    paid_amount = st.number_input("المبلغ المدفوع (د.ل):", min_value=0.0, value=float(final_tot), step=0.5, format="%.2f")
    
    change_due = paid_amount - final_tot
    if change_due >= 0:
        st.success(f"الباقي: {change_due:,.2f} د.ل")
    else:
        st.error(f"المبلغ غير كافٍ! العجز: {abs(change_due):,.2f} د.ل")
    
    if st.button("تأكيد الفاتورة", type="primary", use_container_width=True):
        if paid_amount >= final_tot or pay_method == "آجل":
            target_inv_branch = b_id if b_id != "ALL" else conn.execute("SELECT id FROM branches LIMIT 1").fetchone()["id"]
            branch_row = conn.execute("SELECT branch_name FROM branches WHERE id = ?", (target_inv_branch,)).fetchone()
            b_name_str = branch_row["branch_name"] if branch_row else "الفرع"
            
            can_proceed = True
            for c_item in st.session_state["cart"]:
                if c_item["id"] != 99999 and c_item["id"] != 88888:
                    db_it = conn.execute("SELECT quantity FROM items WHERE id = ?", (c_item["id"],)).fetchone()
                    if db_it and float(db_it["quantity"]) < c_item["qty"]:
                        can_proceed = False
                        st.warning(f"الصنف ({c_item['name']}) غير متوفر بالكمية المطلوبة!")

            if can_proceed:
                cur_in = conn.cursor()
                cur_in.execute("INSERT INTO invoices (branch_id, user_id, customer_name, customer_phone, total_amount, payment_method) VALUES (?, ?, ?, ?, ?, ?)", 
                               (target_inv_branch, st.session_state["user_id"], cust_name.strip() if cust_name else "زبون نقدي", cust_phone.strip(), final_tot, pay_method))
                inv_id = cur_in.lastrowid
                
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
                
                st.session_state["last_invoice_data"] = {
                    "invoice_id": inv_id,
                    "branch_name": b_name_str,
                    "date": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "customer": cust_name.strip() if cust_name else "زبون نقدي",
                    "items": st.session_state["cart"],
                    "total": final_tot,
                    "pay_method": pay_method,
                    "paid": paid_amount,
                    "change": max(0.0, change_due)
                }
                
                st.session_state["cart"] = []
                st.session_state["success_alert_msg"] = "تم إصدار الفاتورة بنجاح!"
                conn.close()
                st.rerun()
            else:
                conn.close()
        else:
            st.warning("المبلغ المدفوع أقل من الإجمالي.")
    conn.close()

def process_unified_barcode():
    code = st.session_state.unified_barcode.strip()
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
            else:
                # تفعيل البيع المانيوال (إضافة مؤقتة للسلة حتى لو الصنف غير مسجل)
                st.session_state["cart"].append({
                    "id": 99999, "code": code, "name": f"صنف يدوي ({code})",
                    "price": 0.0, "qty": 1.0, "total": 0.0
                })
        conn.close()
    st.session_state.unified_barcode = ""

# --- بوابة الدخول ---
if not st.session_state["logged_in"]:
  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    st.title("🔐 تسجيل الدخول")
    st.subheader("مجموعة أبو زيد التجارية")
    
    with st.form("login_form"):
      u_name = st.text_input("اسم المستخدم")
      u_pass = st.text_input("كلمة المرور", type="password")
      submit = st.form_submit_button("دخول", use_container_width=True)
      if submit:
          conn = get_db_connection()
          user = conn.execute("SELECT * FROM users WHERE username = ? AND password = ?", (u_name, u_pass)).fetchone()
          if user:
              if user["is_active"] == 0:
                  st.error("هذا الحساب موقوف!")
                  conn.close(); st.stop()
              st.session_state["logged_in"] = True
              st.session_state["username"] = user["username"]
              st.session_state["role"] = user["role"]
              st.session_state["user_id"] = user["id"]
              st.session_state["branch_id"] = user["branch_id"]
              st.session_state["show_welcome_dialog"] = True
              # إذا كان المستخدم كاشير، نجعل صفحته الافتراضية نقطة البيع مباشرة
              if user["role"] == "Cashier":
                  st.session_state["page"] = "🛒 نقطة البيع (POS)"
              conn.close(); st.rerun()
          else: 
              conn.close(); st.error("اسم المستخدم أو كلمة المرور غير صحيحة!")
  st.stop()

if st.session_state.get("show_welcome_dialog", False): welcome_user_dialog()
if st.session_state.get("missing_barcode_alert", ""): missing_barcode_dialog()
if st.session_state.get("success_alert_msg", ""): success_action_dialog()
if st.session_state.get("last_invoice_data") is not None: thermal_receipt_dialog(st.session_state["last_invoice_data"])

st.sidebar.markdown("<h2 style='text-align: center; color: white;'>🥜 مجموعة أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p style='text-align: center; color: white;'><b>{st.session_state['username']} | {st.session_state['role']}</b></p>", unsafe_allow_html=True)
st.sidebar.markdown("---")

menu_to_show = [m for m in DEFAULT_MENUS if check_user_permission(m)]
for m in menu_to_show:
    if st.sidebar.button(m, use_container_width=True, key=f"btn_menu_{m}", on_click=set_page, args=(m,)): pass

if st.sidebar.button("تسجيل الخروج", use_container_width=True):
    st.session_state.clear(); st.rerun()

choice = st.session_state["page"]

dashboard_cards = {
    "🛒 نقطة البيع (POS)": {"icon": "🛒", "color": "linear-gradient(135deg, #f59e0b, #ea580c)", "desc": "شاشة الكاشير"},
    "⭐ لوحة المفضلة (1-20)": {"icon": "⭐", "color": "linear-gradient(135deg, #e11d48, #be123c)", "desc": "الأصناف المفضلة"},
    "📦 إدارة المخزن والفروع": {"icon": "📦", "color": "linear-gradient(135deg, #3b82f6, #1d4ed8)", "desc": "إدارة الأصناف والأسعار"},
    "➕ الفائض والتوالف والمرتجعات وتعديل السعر": {"icon": "➕", "color": "linear-gradient(135deg, #10b981, #047857)", "desc": "التوالف والمرتجعات"},
    "🔄 تزويد الفروع والأرشيف": {"icon": "🔄", "color": "linear-gradient(135deg, #8b5cf6, #6d28d9)", "desc": "تزويد الفروع"},
    "🥜 التحميص والخلط": {"icon": "🥜", "color": "linear-gradient(135deg, #d946ef, #a21caf)", "desc": "التحميص والخلط"}
}

if choice == "🏠 الرئيسية واللوحة":
  st.title("لوحة التحكم الرئيسية")
  cols = st.columns(3)
  for i, (item, data) in enumerate(dashboard_cards.items()):
      if check_user_permission(item):
          with cols[i % 3]:
              st.markdown(f'''<div style="background: {data['color']}; padding: 15px 10px; border-radius: 8px; color: white; text-align: center; margin-bottom: 8px; min-height: 110px;"><h1 style="margin:0; font-size: 30px; color: white !important;">{data['icon']}</h1><h3 style="margin: 6px 0 2px 0; color: white !important; font-size: 15px;">{item}</h3><p style="margin:0; font-size: 12px; opacity: 0.9; color: white !important;">{data['desc']}</p></div>''', unsafe_allow_html=True)
              if st.button("دخول", key=f"btn_card_{i}", on_click=set_page, args=(item,)): pass
              st.markdown("<br>", unsafe_allow_html=True)

elif choice == "⭐ لوحة المفضلة (1-20)":
  st.header("الأصناف المفضلة (1 إلى 20)")
  conn = get_db_connection()
  b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
  sel_b = st.selectbox("الفرع:", list(b_dict.keys()))
  items_fav = pd.read_sql("SELECT id, item_code AS 'كود', item_name AS 'اسم الصنف', favorite_rank AS 'الرقم المفضل' FROM items WHERE branch_id = ?", conn, params=(b_dict[sel_b],))
  if not items_fav.empty:
      edited_fav = st.data_editor(items_fav, hide_index=True)
      if st.button("حفظ الترتيب"):
          for idx, row in edited_fav.iterrows():
              conn.execute("UPDATE items SET favorite_rank = ? WHERE id = ?", (row['الرقم المفضل'], row['id']))
          conn.commit()
          st.session_state["success_alert_msg"] = "تم حفظ الترتيب بنجاح!"
          st.rerun()
  conn.close()

elif choice == "⚙️ الجرد والتصفير السنوي":
  st.header("التصفير والجرد السنوي")
  conn = get_db_connection()
  b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
  with st.form("annual_inventory_form"):
      target_scope = st.selectbox("النطاق:", ["كل الفروع"] + list(b_dict.keys()))
      opt_sales = st.checkbox("تصفير المبيعات والفواتير")
      opt_stock = st.checkbox("تصفير المخزون")
      admin_pass_inv = st.text_input("الرقم السري:", type="password")
      if st.form_submit_button("تنفيذ التصفير", type="primary"):
          if verify_admin_password(admin_pass_inv):
              cur_inv = conn.cursor()
              scope_id = "ALL" if target_scope == "كل الفروع" else b_dict.get(target_scope, "ALL")
              if opt_sales:
                  if scope_id == "ALL": cur_inv.execute("DELETE FROM invoices")
                  else: cur_inv.execute("DELETE FROM invoices WHERE branch_id = ?", (scope_id,))
              if opt_stock:
                  if scope_id == "ALL": cur_inv.execute("UPDATE items SET quantity = 0")
                  else: cur_inv.execute("UPDATE items SET quantity = 0 WHERE branch_id = ?", (scope_id,))
              conn.commit()
              st.session_state["success_alert_msg"] = "تم التصفير بنجاح!"
              st.rerun()
          else: st.error("الرقم السري غير صحيح!")
  conn.close()

elif choice == "📁 استيراد Excel":
  st.header("استيراد الأصناف عبر Excel")
  conn = get_db_connection()
  b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
  with st.form("excel_import_seq_form"):
      sel_target_branch = st.selectbox("الفرع المستهدف:", ["تعميم لكافة الفروع"] + list(b_dict.keys()))
      up_excel = st.file_uploader("ملف Excel", type=["xlsx", "xls"])
      if st.form_submit_button("تنفيذ الاستيراد"):
          if up_excel:
              try:
                  df_exc = pd.read_excel(up_excel, usecols=[0, 1, 2, 3, 4, 5])
                  cur_ex = conn.cursor()
                  count_imp = 0
                  target_ids = list(b_dict.values()) if sel_target_branch == "تعميم لكافة الفروع" else [b_dict[sel_target_branch]]
                  for idx, row in df_exc.iterrows():
                      if row.isna().all(): continue
                      code, name = str(row.iloc[0]).strip(), str(row.iloc[1]).strip()
                      if code.lower() in ["nan", "code", "كود"] or name.lower() in ["nan", "name", "اسم"]: continue
                      qty, b_pr, s_pr = float(row.iloc[2]) if pd.notna(row.iloc[2]) else 0.0, float(row.iloc[3]) if pd.notna(row.iloc[3]) else 0.0, float(row.iloc[4]) if pd.notna(row.iloc[4]) else 0.0
                      for tid in target_ids:
                          exist_item = cur_ex.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (tid, code)).fetchone()
                          if exist_item:
                              cur_ex.execute("UPDATE items SET quantity = ?, buy_price = ?, sale_price = ?, avg_cost = ? WHERE id = ?", (qty, b_pr, s_pr, b_pr, exist_item['id']))
                          else:
                              cur_ex.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)", (tid, code, name, qty, b_pr, s_pr, b_pr))
                      count_imp += 1
                  conn.commit()
                  st.session_state["success_alert_msg"] = f"تم استيراد ({count_imp}) صنف بنجاح!"
                  st.rerun()
              except Exception as e: st.error(f"خطأ: {e}")
  conn.close()

elif choice == "🏢 إدارة الفروع":
  st.header("إدارة الفروع والمخازن")
  conn = get_db_connection()
  with st.expander("إضافة فرع أو مخزن جديد"):
      with st.form("new_branch_form", clear_on_submit=True):
          nb_name = st.text_input("اسم الفرع:")
          nb_type = st.selectbox("النوع:", ["فرع", "مخزن"])
          if st.form_submit_button("حفظ") and nb_name:
              try:
                  conn.execute("INSERT INTO branches (branch_name, branch_type) VALUES (?, ?)", (nb_name.strip(), nb_type))
                  conn.commit()
                  st.session_state["success_alert_msg"] = "تم إضافة الفرع بنجاح!"
                  st.rerun()
              except: st.error("الاسم موجود مسبقاً.")
  
  for b in conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall():
      with st.form(f"branch_edit_{b['id']}"):
          col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
          with col1: new_bn = st.text_input("الاسم:", value=b["branch_name"], key=f"bn_{b['id']}")
          with col2: new_bt = st.selectbox("النوع:", ["فرع", "مخزن"], index=0 if b["branch_type"]=="فرع" else 1, key=f"bt_{b['id']}")
          with col3:
              st.markdown("<br>", unsafe_allow_html=True)
              save_btn = st.form_submit_button("حفظ التعديل")
          with col4:
              st.markdown("<br>", unsafe_allow_html=True)
              del_btn = st.form_submit_button("حذف الفرع")
          if save_btn:
              conn.execute("UPDATE branches SET branch_name=?, branch_type=? WHERE id=?", (new_bn.strip(), new_bt, b['id']))
              conn.commit()
              st.session_state["success_alert_msg"] = "تم التحديث بنجاح!"
              st.rerun()
          if del_btn: admin_confirm_dialog("حذف فرع", b['id'])
  conn.close()

elif choice == "📦 إدارة المخزن والفروع":
  st.header("إدارة المخزن والفروع")
  conn = get_db_connection()
  b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
  sel_b = st.selectbox("اختر الفرع:", list(b_dict.keys()))
  cur_b_id = b_dict[sel_b]
  
  with st.expander("إضافة صنف جديد يدويًا"):
      with st.form("manual_add_item", clear_on_submit=True):
          m_code = st.text_input("كود الصنف / الباركود:")
          m_name = st.text_input("اسم الصنف:")
          m_qty = st.number_input("الكمية:", min_value=0.0, value=0.0, step=0.1)
          m_buy = st.number_input("سعر الشراء:", min_value=0.0, value=0.0, step=0.5)
          m_sale = st.number_input("سعر البيع:", min_value=0.0, value=0.0, step=0.5)
          m_avg = st.number_input("متوسط التكلفة:", min_value=0.0, value=0.0, step=0.5)
          if st.form_submit_button("حفظ الصنف الجديد") and m_code and m_name:
              try:
                  conn.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)",
                               (cur_b_id, m_code.strip(), m_name.strip(), m_qty, m_buy, m_sale, m_avg if m_avg > 0 else m_buy))
                  conn.commit()
                  st.session_state["success_alert_msg"] = "تم إضافة الصنف بنجاح!"
                  st.rerun()
              except: st.error("الكود أو الباركود موجود مسبقاً.")

  items_df = pd.read_sql("SELECT id, item_code AS 'الكود', item_name AS 'اسم الصنف', quantity AS 'الكمية (كجم)', sale_price AS 'سعر البيع', buy_price AS 'سعر الشراء', avg_cost AS 'التكلفة' FROM items WHERE branch_id = ?", conn, params=(cur_b_id,))
  if not items_df.empty:
      edited_items = st.data_editor(items_df, hide_index=True, key="inv_editor_indep")
      if st.button("حفظ التعديلات وتعميم الأسعار"):
          cur_up = conn.cursor()
          for idx, row in edited_items.iterrows():
              cur_up.execute("UPDATE items SET item_code=?, item_name=?, quantity=?, buy_price=?, sale_price=?, avg_cost=? WHERE id=?", 
                           (row['الكود'], row['اسم الصنف'], row['الكمية (كجم)'], row['سعر الشراء'], row['سعر البيع'], row['التكلفة'], row['id']))
              cur_up.execute("UPDATE items SET item_name=?, sale_price=? WHERE item_code=?", (row['اسم الصنف'], row['سعر البيع'], row['الكود']))
          conn.commit()
          st.session_state["success_alert_msg"] = "تم الحفظ وتعميم الأسعار بنجاح!"
          st.rerun()
      st.download_button("تصدير لـ Excel", data=to_excel(items_df), file_name="inventory.xlsx")
  conn.close()

elif choice == "💰 المصروفات":
  st.header("إدارة المصروفات والإيجارات")
  conn = get_db_connection()
  b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches WHERE branch_type='فرع'").fetchall()}
  all_branches_cnt = conn.execute("SELECT COUNT(*) FROM branches WHERE branch_type='فرع'").fetchone()[0]
  
  with st.form("expense_form", clear_on_submit=True):
      exp_type = st.radio("نوع المصروف:", ["خاص بفرع معين", "مصروف عام للمخزن (يُقسَم بالتساوي على الفروع - المخزن صفر)"])
      sel_b = st.selectbox("الفرع:", list(b_dict.keys())) if exp_type == "خاص بفرع معين" else ""
      amount = st.number_input("المبلغ الإجمالي (د.ل):", min_value=0.0, value=0.0, step=0.5)
      desc = st.text_input("البيان:")
      is_rent = st.checkbox("هل المصروف إيجار مدفوع مقدماً؟")
      rent_months = st.number_input("عدد شهور الإيجار المدفوعة:", min_value=1, value=1, step=1) if is_rent else 1
      
      if st.form_submit_button("حفظ المصروف"):
          if amount > 0 and desc:
              cur_ex = conn.cursor()
              today_date = datetime.now().date()
              paid_until = (today_date + timedelta(days=30*rent_months)).strftime('%Y-%m-%d') if is_rent else ""
              
              if exp_type == "خاص بفرع معين":
                  cur_ex.execute("INSERT INTO expenses (branch_id, amount, description, is_general_store, expense_date, rent_months, rent_paid_until) VALUES (?, ?, ?, 0, ?, ?, ?)", 
                                 (b_dict[sel_b], amount, desc, today_date.strftime('%Y-%m-%d'), rent_months, paid_until))
              else:
                  share = amount / all_branches_cnt if all_branches_cnt > 0 else amount
                  cur_ex.execute("INSERT INTO expenses (branch_id, amount, description, is_general_store, expense_date, rent_months, rent_paid_until) VALUES (NULL, ?, ?, 1, ?, ?, ?)", 
                                 (amount, f"[مخزن عام - حصة الفرع: {share:,.2f}] {desc}", today_date.strftime('%Y-%m-%d'), rent_months, paid_until))
              conn.commit()
              st.session_state["success_alert_msg"] = "تم حفظ المصروف بنجاح!"
              st.rerun()

  exp_df = pd.read_sql("SELECT expenses.id AS 'مسلسل', IFNULL(branches.branch_name, 'عام (موزع)') AS 'الفرع', expenses.amount AS 'المبلغ', expenses.description AS 'البيان', expenses.expense_date AS 'التاريخ', expenses.rent_paid_until AS 'مدفوع حتى' FROM expenses LEFT JOIN branches ON expenses.branch_id = branches.id ORDER BY expenses.id DESC", conn)
  if not exp_df.empty:
      st.dataframe(exp_df, use_container_width=True)
      st.download_button("تصدير المصروفات لـ Excel", data=to_excel(exp_df), file_name="expenses.xlsx")
      del_e = st.selectbox("مسلسل المصروف للحذف:", exp_df["مسلسل"].tolist())
      if st.button("حذف المصروف", type="primary"): admin_confirm_dialog("حذف مصروف", del_e)
  conn.close()

elif choice == "➕ الفائض والتوالف والمرتجعات وتعديل السعر":
  st.header("الفائض، التوالف، والمرتجعات")
  conn = get_db_connection()
  b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
  sel_b = st.selectbox("الفرع:", list(b_dict.keys()))
  cur_id = b_dict[sel_b]
  
  op_type = st.radio("العملية:", ["إضافة فائض", "توالف أو تلفيات أو مرتجعات", "تعديل سعر وتعميمه"])
  items_list = conn.execute("SELECT id, item_code, item_name, quantity, sale_price FROM items WHERE branch_id = ?", (cur_id,)).fetchall()
  if items_list:
      i_opts = {f"[{i['item_code']}] {i['item_name']} (متاح: {i['quantity']})": i for i in items_list}
      with st.form("surplus_return_form", clear_on_submit=True):
          chosen = st.selectbox("الصنف:", list(i_opts.keys()))
          it = i_opts[chosen]
          
          if op_type == "تعديل سعر وتعميمه":
              new_sale_p = st.number_input("سعر البيع الجديد:", min_value=0.0, value=float(it['sale_price']), step=0.5)
              if st.form_submit_button("حفظ وتعميم السعر"):
                  cur_up = conn.cursor()
                  cur_up.execute("UPDATE items SET sale_price = ? WHERE item_code = ?", (new_sale_p, it['item_code']))
                  conn.commit()
                  st.session_state["success_alert_msg"] = "تم تعميم السعر بنجاح!"
                  st.rerun()
          else:
              qty = st.number_input("الكمية (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
              if st.form_submit_button("تنفيذ"):
                  if qty > 0:
                      mult = 1 if op_type.startswith("إضافة") else -1
                      conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (qty * mult, it['id']))
                      conn.commit()
                      st.session_state["success_alert_msg"] = "تمت العملية بنجاح!"
                      st.rerun()
  conn.close()

elif choice == "🔄 تزويد الفروع والأرشيف":
  st.header("تزويد الفروع والأرشيف")
  conn = get_db_connection()
  main_store = conn.execute("SELECT id FROM branches WHERE branch_type = 'مخزن' LIMIT 1").fetchone()
  
  tab_tr1, tab_tr2, tab_tr3 = st.tabs(["تزويد فرع", "الطلبات المعلقة", "أرشيف الفواتير"])
  
  with tab_tr1:
      if main_store:
          main_id = main_store["id"]
          b_opts = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches WHERE id != ?", (main_id,)).fetchall()}
          sel_t = st.selectbox("الفرع المستهدف:", list(b_opts.keys()))
          target_id = b_opts[sel_t]
          
          if "transfer_cart" not in st.session_state: st.session_state["transfer_cart"] = []
          m_items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND quantity > 0", (main_id,)).fetchall()
          m_opts = {f"[{i['item_code']}] {i['item_name']} (متاح: {i['quantity']})": i for i in m_items} if m_items else {}
          
          with st.form("add_tr_form", clear_on_submit=True):
              if m_opts:
                  sel_m = st.selectbox("الصنف:", list(m_opts.keys()))
                  t_qty = st.number_input("الكمية:", min_value=0.0, value=0.0, step=0.1, format="%.2f")
                  if st.form_submit_button("إضافة للسلة"):
                      if t_qty > 0:
                          obj = m_opts[sel_m]
                          st.session_state["transfer_cart"].append({"id": obj['id'], "code": obj['item_code'], "name": obj['item_name'], "qty": t_qty, "buy": obj['buy_price'], "sale": obj['sale_price'], "avg": obj['avg_cost'], "exp": obj['expiry_date'], "no_exp": obj['no_expiry']})
                          st.rerun()
          if st.session_state["transfer_cart"]:
              st.dataframe(pd.DataFrame(st.session_state["transfer_cart"]).rename(columns={"code": "الكود", "name": "الصنف", "qty": "الكمية"}), use_container_width=True)
              if st.button("إرسال بضاعة للفرع", type="primary"):
                  cur_tr = conn.cursor()
                  details = []
                  for t in st.session_state["transfer_cart"]:
                      cur_tr.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (t['qty'], t['id']))
                      details.append(f"{t['name']} ({t['qty']} كجم)")
                  cur_tr.execute("INSERT INTO transfer_logs (from_branch_id, to_branch_id, transfer_type, items_details, status) VALUES (?, ?, 'تزويد بضاعة', ?, 'معلقة')", (main_id, target_id, " - ".join(details)))
                  conn.commit()
                  st.session_state["transfer_cart"] = []
                  st.session_state["success_alert_msg"] = "تم إرسال بضاعة التزويد بنجاح!"
                  st.rerun()

  with tab_tr2:
      st.subheader("الفواتير المعلقة للفرع")
      user_branch_id = st.session_state.get("branch_id")
      user_role = st.session_state.get("role", "")
      
      pending_logs = conn.execute("SELECT * FROM transfer_logs WHERE status = 'معلقة'" + ("" if user_role in ["Admin", "General_Supervisor"] else " AND to_branch_id = ?"), (() if user_role in ["Admin", "General_Supervisor"] else (user_branch_id,))).fetchall()
      
      if pending_logs:
          for plog in pending_logs:
              from_b = conn.execute("SELECT branch_name FROM branches WHERE id = ?", (plog["from_branch_id"],)).fetchone()["branch_name"]
              to_b = conn.execute("SELECT branch_name FROM branches WHERE id = ?", (plog["to_branch_id"],)).fetchone()["branch_name"]
              
              st.markdown(f"""
              <div style="background:#e0f2fe; padding:10px; border-radius:6px; margin-bottom:6px;">
                  <b>فاتورة رقم #{plog['id']} من ({from_b}) إلى ({to_b})</b><br>
                  التفاصيل: {plog['items_details']}
              </div>
              """, unsafe_allow_html=True)
              
              if st.button(f"استلام واعتماد الفاتورة #{plog['id']}", key=f"accept_trans_{plog['id']}"):
                  cur_acc = conn.cursor()
                  cur_acc.execute("UPDATE transfer_logs SET status = 'مكتملة' WHERE id = ?", (plog['id'],))
                  conn.commit()
                  st.session_state["success_alert_msg"] = f"تم استلام الفاتورة #{plog['id']} بنجاح!"
                  st.rerun()
      else:
          st.info("لا توجد فواتير معلقة.")

  with tab_tr3:
      if user_role in ["Admin", "General_Supervisor"]:
          logs_df = pd.read_sql("SELECT transfer_logs.id AS 'رقم', b1.branch_name AS 'من', b2.branch_name AS 'إلى', transfer_logs.items_details AS 'التفاصيل', transfer_logs.status AS 'الحالة', transfer_logs.transfer_date AS 'التاريخ' FROM transfer_logs LEFT JOIN branches b1 ON transfer_logs.from_branch_id=b1.id LEFT JOIN branches b2 ON transfer_logs.to_branch_id=b2.id ORDER BY transfer_logs.id DESC", conn)
      else:
          logs_df = pd.read_sql("SELECT transfer_logs.id AS 'رقم', b1.branch_name AS 'من', b2.branch_name AS 'إلى', transfer_logs.items_details AS 'التفاصيل', transfer_logs.status AS 'الحالة', transfer_logs.transfer_date AS 'التاريخ' FROM transfer_logs LEFT JOIN branches b1 ON transfer_logs.from_branch_id=b1.id LEFT JOIN branches b2 ON transfer_logs.to_branch_id=b2.id WHERE transfer_logs.to_branch_id = ? ORDER BY transfer_logs.id DESC", conn, params=(user_branch_id,))
      
      if not logs_df.empty:
          st.dataframe(logs_df, use_container_width=True)
          st.download_button("تصدير الأرشيف لـ Excel", data=to_excel(logs_df), file_name="transfer_logs.xlsx")
  conn.close()

elif choice == "📥 المشتريات والموردين":
  st.header("المشتريات وديون الموردين")
  conn = get_db_connection()
  tab_p1, tab_p2, tab_p3 = st.tabs(["فاتورة مشتريات", "الموردين والديون", "سجل المشتريات"])
  
  with tab_p1:
      b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
      s_dict = {s["supplier_name"]: s["id"] for s in conn.execute("SELECT id, supplier_name FROM suppliers").fetchall()}
      pb = st.selectbox("الفرع:", list(b_dict.keys()))
      ps = st.selectbox("المورد:", list(s_dict.keys()) if s_dict else ["لا توجد موردين"])
      inv_num = st.text_input("رقم الفاتورة:")
      ptype = st.radio("نوع الشراء:", ["كاش", "آجل"])
      
      if "purch_cart" not in st.session_state: st.session_state["purch_cart"] = []
      db_items = conn.execute("SELECT id, item_code, item_name, buy_price FROM items WHERE branch_id = ?", (b_dict[pb],)).fetchall()
      i_opts = {f"[{i['item_code']}] {i['item_name']}": i for i in db_items} if db_items else {}
      
      with st.form("add_p_f", clear_on_submit=True):
          if i_opts:
              c_ik = st.selectbox("الصنف:", list(i_opts.keys()))
              p_q = st.number_input("الكمية (كجم):", min_value=0.0, value=0.0, step=0.1)
              p_pr = st.number_input("سعر الشراء:", min_value=0.0, value=0.0, step=0.5)
              if st.form_submit_button("إضافة للسلة"):
                  if p_q > 0 and p_pr > 0:
                      it = i_opts[c_ik]
                      st.session_state["purch_cart"].append({"id": it['id'], "code": it['item_code'], "name": it['item_name'], "qty": p_q, "price": p_pr, "total": p_q * p_pr})
                      st.rerun()
      if st.session_state["purch_cart"]:
          st.dataframe(pd.DataFrame(st.session_state["purch_cart"]).rename(columns={"code": "الكود", "name": "الصنف", "qty": "الكمية", "price": "السعر", "total": "الإجمالي"}), use_container_width=True)
          g_tot = sum([x["total"] for x in st.session_state["purch_cart"]])
          st.markdown(f"**الإجمالي: {g_tot:,.2f} د.ل**")
          
          if st.button("حفظ فاتورة المشتريات", type="primary"):
              if ps != "لا توجد موردين" and inv_num.strip():
                  sup_id = s_dict[ps]
                  cur_p = conn.cursor()
                  det = []
                  for pi in st.session_state["purch_cart"]:
                      old_r = cur_p.execute("SELECT quantity, avg_cost, buy_price FROM items WHERE id = ?", (pi['id'],)).fetchone()
                      old_q = old_r["quantity"]
                      old_avg = old_r["avg_cost"] if old_r["avg_cost"] > 0 else old_r["buy_price"]
                      new_tot_q = old_q + pi['qty']
                      new_avg_cost = (((old_q * old_avg) + (pi['qty'] * pi['price'])) / new_tot_q) if new_tot_q > 0 else pi['price']
                      cur_p.execute("UPDATE items SET quantity = quantity + ?, buy_price = ?, avg_cost = ? WHERE id = ?", (pi['qty'], pi['price'], new_avg_cost, pi['id']))
                      det.append(f"{pi['name']} ({pi['qty']} كجم)")
                  cur_p.execute("INSERT INTO purchases (branch_id, supplier_id, supplier_name, invoice_number, total_cost, payment_type, items_details, invoice_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (b_dict[pb], sup_id, ps, inv_num.strip(), g_tot, ptype, " - ".join(det), datetime.now().strftime('%Y-%m-%d')))
                  if ptype == "آجل": 
                      cur_p.execute("UPDATE suppliers SET balance = balance + ? WHERE id = ?", (g_tot, sup_id))
                  conn.commit()
                  st.session_state["purch_cart"] = []
                  st.session_state["success_alert_msg"] = "تم حفظ المشتريات وتحديث الديون بنجاح!"
                  st.rerun()

  with tab_p2:
      with st.form("new_sup", clear_on_submit=True):
          sname, sphone = st.text_input("اسم المورد:"), st.text_input("الهاتف:")
          if st.form_submit_button("حفظ مورد") and sname:
              try:
                  conn.execute("INSERT INTO suppliers (supplier_name, phone) VALUES (?, ?)", (sname.strip(), sphone.strip()))
                  conn.commit()
                  st.session_state["success_alert_msg"] = "تم حفظ المورد!"
                  st.rerun()
              except: st.error("المورد موجود مسبقاً.")
      
      supp_df = pd.read_sql("SELECT id, supplier_name AS 'المورد', phone AS 'الهاتف', balance AS 'الديون والمستحقات (د.ل)' FROM suppliers", conn)
      if not supp_df.empty: 
          st.dataframe(supp_df, use_container_width=True)
          st.download_button("تصدير الديون لـ Excel", data=to_excel(supp_df), file_name="suppliers_debts.xlsx")
          total_debts = supp_df['الديون والمستحقات (د.ل)'].sum()
          st.metric("إجمالي الديون للموردين", f"{total_debts:,.2f} د.ل")
          
          del_s = st.selectbox("المورد للحذف:", supp_df["id"].tolist(), format_func=lambda x: f"رقم: {x} - {supp_df[supp_df['id']==x]['المورد'].values[0]}")
          if st.button("حذف المورد", type="primary"): admin_confirm_dialog("حذف مورد", del_s)

  with tab_p3:
      p_df = pd.read_sql("SELECT purchases.id AS 'مسلسل', purchases.invoice_number AS 'الفاتورة', branches.branch_name AS 'الفرع', purchases.supplier_name AS 'المورد', purchases.total_cost AS 'الإجمالي', purchases.invoice_date AS 'التاريخ' FROM purchases LEFT JOIN branches ON purchases.branch_id=branches.id ORDER BY purchases.id DESC", conn)
      if not p_df.empty:
          st.dataframe(p_df, use_container_width=True)
          st.download_button("تصدير المشتريات لـ Excel", data=to_excel(p_df), file_name="purchases.xlsx")
          del_pr = st.selectbox("فاتورة المشتريات للحذف:", p_df["مسلسل"].tolist(), format_func=lambda x: f"مسلسل: {x}")
          if st.button("حذف الفاتورة", type="primary"): admin_confirm_dialog("حذف مشتريات", del_pr)
  conn.close()

elif choice == "🥜 التحميص والخلط":
    st.header("التحميص وخلط المكسرات")
    conn = get_db_connection()
    main_store_row = conn.execute("SELECT id FROM branches WHERE branch_type='مخزن' LIMIT 1").fetchone()
    main_s_id = main_store_row["id"] if main_store_row else 1
    
    store_items = conn.execute("SELECT item_code, item_name, quantity, buy_price, sale_price, avg_cost FROM items WHERE branch_id = ? AND quantity > 0", (main_s_id,)).fetchall()
    all_store_items = conn.execute("SELECT item_code, item_name, buy_price, sale_price, avg_cost FROM items WHERE branch_id = ?", (main_s_id,)).fetchall()
    
    mix_tab, roast_tab = st.tabs(["خلط المكسرات", "التحميص"])
    
    with mix_tab:
        if store_items:
            item_choices = {f"[{i['item_code']}] {i['item_name']} (متاح: {i['quantity']})": i for i in store_items}
            if "mix_list" not in st.session_state: st.session_state["mix_list"] = []
            with st.form("mix_f", clear_on_submit=True):
                sel_c = st.selectbox("اختر الخام:", list(item_choices.keys()))
                mqty = st.number_input("الوزن (كجم):", min_value=0.0, value=0.0, step=0.1)
                if st.form_submit_button("إضافة للخلطة"):
                    if mqty > 0:
                        it = item_choices[sel_c]
                        st.session_state["mix_list"].append({"code": it['item_code'], "name": it['item_name'], "qty": mqty, "cost": it['avg_cost'] or it['buy_price']})
                        st.rerun()
            if st.session_state["mix_list"]:
                st.dataframe(pd.DataFrame(st.session_state["mix_list"]).rename(columns={"code": "الكود", "name": "الصنف", "qty": "الكمية", "cost": "التكلفة"}), use_container_width=True)
                with st.form("fin_mix"):
                    all_prod_opts = {f"[{i['item_code']}] {i['item_name']}": i for i in all_store_items}
                    res_sel = st.selectbox("الصنف الناتج بعد الخلط:", list(all_prod_opts.keys()))
                    final_weight = st.number_input("الوزن النهائي (كجم):", min_value=0.0, value=0.0, step=0.1)
                    if st.form_submit_button("اعتماد الخلطة"):
                        if res_sel and final_weight > 0:
                            cur_mx = conn.cursor()
                            tot_cost = sum([x['qty'] * x['cost'] for x in st.session_state["mix_list"]])
                            res_obj = all_prod_opts[res_sel]
                            new_avg = tot_cost / final_weight if final_weight > 0 else 0
                            for m in st.session_state["mix_list"]:
                                cur_mx.execute("UPDATE items SET quantity = quantity - ? WHERE branch_id = ? AND item_code = ?", (m['qty'], main_s_id, m['code']))
                            cur_mx.execute("UPDATE items SET quantity = quantity + ?, avg_cost = ? WHERE branch_id = ? AND item_code = ?", (final_weight, new_avg, main_s_id, res_obj['item_code']))
                            conn.commit()
                            st.session_state["mix_list"] = []
                            st.session_state["success_alert_msg"] = "تمت عملية الخلط بنجاح!"
                            st.rerun()
                            
    with roast_tab:
        if store_items:
            roast_choices = {f"[{i['item_code']}] {i['item_name']}": i for i in store_items}
            with st.form("roast_f", clear_on_submit=True):
                sel_r = st.selectbox("صنف التحميص:", list(roast_choices.keys()))
                raw_w = st.number_input("الوزن قبل التحميص (كجم):", min_value=0.0, value=0.0, step=0.1)
                all_out_opts = {f"[{i['item_code']}] {i['item_name']}": i for i in all_store_items}
                sel_out = st.selectbox("الصنف بعد التحميص:", list(all_out_opts.keys()))
                roasted_w = st.number_input("الوزن بعد التحميص (كجم):", min_value=0.0, value=0.0, step=0.1)
                r_price = st.number_input("سعر البيع الناتج:", min_value=0.0, value=0.0, step=0.5)
                
                if st.form_submit_button("اعتماد التحميص"):
                    if raw_w > 0 and roasted_w > 0:
                        r_in_obj = roast_choices[sel_r]
                        r_out_obj = all_out_opts[sel_out]
                        cur_r = conn.cursor()
                        cur_r.execute("UPDATE items SET quantity = quantity - ? WHERE branch_id = ? AND item_code = ?", (raw_w, main_s_id, r_in_obj['item_code']))
                        cur_r.execute("UPDATE items SET quantity = quantity + ?, sale_price = ?, avg_cost = ? WHERE branch_id = ? AND item_code = ?", 
                                      (roasted_w, r_price, r_in_obj['avg_cost'] or r_in_obj['buy_price'], main_s_id, r_out_obj['item_code']))
                        conn.commit()
                        st.session_state["success_alert_msg"] = "تم التحميص بنجاح!"
                        st.rerun()
    conn.close()

elif choice == "📊 التقارير الشاملة والأرباح":
  st.header("التقارير الشاملة والأرباح والمصروفات")
  conn = get_db_connection()
  b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
  
  rep_type = st.selectbox("اختر نوع التقرير:", ["مؤشرات الأرباح العامة", "تقرير المبيعات", "تقرير المشتريات والذمم", "تقرير المصروفات والإيجارات الشهرية"])
  
  if rep_type == "مؤشرات الأرباح العامة":
      sel_rep = st.selectbox("الفرع:", ["إجمالي الكل"] + list(b_dict.keys()))
      t_id = "ALL" if sel_rep == "إجمالي الكل" else b_dict[sel_rep]
      
      sales = conn.execute("SELECT SUM(total_amount) FROM invoices" + ("" if t_id=="ALL" else " WHERE branch_id = ?"), (() if t_id=="ALL" else (t_id,))).fetchone()[0] or 0.0
      purch = conn.execute("SELECT SUM(total_cost) FROM purchases" + ("" if t_id=="ALL" else " WHERE branch_id = ?"), (() if t_id=="ALL" else (t_id,))).fetchone()[0] or 0.0
      exps = conn.execute("SELECT SUM(amount) FROM expenses" + ("" if t_id=="ALL" else " WHERE branch_id = ?"), (() if t_id=="ALL" else (t_id,))).fetchone()[0] or 0.0
      net = sales - (purch + exps)
      
      c1, c2, c3, c4 = st.columns(4)
      with c1: st.metric("المبيعات", f"{sales:,.2f} د.ل")
      with c2: st.metric("المشتريات", f"{purch:,.2f} د.ل")
      with c3: st.metric("المصروفات", f"{exps:,.2f} د.ل")
      with c4: st.metric("صافي الربح", f"{net:,.2f} د.ل")

  elif rep_type == "تقرير المبيعات":
      sel_rep = st.selectbox("الفرع:", ["إجمالي الكل"] + list(b_dict.keys()))
      t_id = "ALL" if sel_rep == "إجمالي الكل" else b_dict[sel_rep]
      query = "SELECT invoices.id AS 'رقم', branches.branch_name AS 'الفرع', invoices.customer_name AS 'الزبون', invoices.total_amount AS 'الإجمالي', invoices.payment_method AS 'الدفع', invoices.created_at AS 'التاريخ' FROM invoices LEFT JOIN branches ON invoices.branch_id = branches.id" + ("" if t_id=="ALL" else " WHERE invoices.branch_id = ?")
      df_sales = pd.read_sql(query, conn, params=(() if t_id=="ALL" else (t_id,)))
      st.dataframe(df_sales, use_container_width=True)
      if not df_sales.empty:
          st.download_button("تصدير المبيعات لـ Excel", data=to_excel(df_sales), file_name="sales_report.xlsx")

  elif rep_type == "تقرير المشتريات والذمم":
      d_start = st.date_input("من تاريخ:", datetime.now() - timedelta(days=30))
      d_end = st.date_input("إلى تاريخ:", datetime.now())
      sel_sup = st.selectbox("المورد:", ["كل الموردين"] + [s['supplier_name'] for s in conn.execute("SELECT supplier_name FROM suppliers").fetchall()])
      
      q_p = "SELECT purchases.id AS 'مسلسل', purchases.invoice_number AS 'الفاتورة', branches.branch_name AS 'الفرع', purchases.supplier_name AS 'المورد', purchases.total_cost AS 'الإجمالي', purchases.payment_type AS 'نوع الدفع', purchases.invoice_date AS 'التاريخ' FROM purchases LEFT JOIN branches ON purchases.branch_id=branches.id WHERE purchases.invoice_date BETWEEN ? AND ?"
      params = [d_start.strftime('%Y-%m-%d'), d_end.strftime('%Y-%m-%d')]
      if sel_sup != "كل الموردين":
          q_p += " AND purchases.supplier_name = ?"
          params.append(sel_sup)
          
      df_p = pd.read_sql(q_p, conn, params=tuple(params))
      st.dataframe(df_p, use_container_width=True)
      if not df_p.empty:
          st.download_button("تصدير المشتريات لـ Excel", data=to_excel(df_p), file_name="purchases_filtered.xlsx")

  elif rep_type == "تقرير المصروفات والإيجارات الشهرية":
      st.markdown("### المصروفات ومتابعة الإيجارات")
      df_exp = pd.read_sql("SELECT expenses.id AS 'مسلسل', IFNULL(branches.branch_name, 'عام (موزع)') AS 'الفرع', expenses.amount AS 'المبلغ', expenses.description AS 'البيان', expenses.expense_date AS 'التاريخ', expenses.rent_paid_until AS 'مدفوع حتى تاريخ' FROM expenses LEFT JOIN branches ON expenses.branch_id = branches.id", conn)
      if not df_exp.empty:
          st.dataframe(df_exp, use_container_width=True)
          st.download_button("تصدير المصروفات لـ Excel", data=to_excel(df_exp), file_name="expenses_report.xlsx")
  conn.close()

elif choice == "👥 إدارة المستخدمين":
    st.header("إدارة المستخدمين والصلاحيات")
    conn = get_db_connection()
    current_user_role = st.session_state.get("role", "")
    
    branches_list = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    b_opts_dict = {b["branch_name"]: b["id"] for b in branches_list}
    
    with st.form("new_u", clear_on_submit=True):
        uname = st.text_input("اسم المستخدم:")
        uphone = st.text_input("الهاتف:")
        upass = st.text_input("كلمة المرور:", type="password")
        
        if current_user_role == "Admin":
            available_roles = ["Admin", "General_Supervisor", "Branch_Supervisor", "Cashier", "Viewer"]
        else:
            available_roles = ["General_Supervisor", "Branch_Supervisor", "Cashier", "Viewer"]
            
        urole = st.selectbox("الرتبة:", available_roles)
        
        if urole in ["Admin", "General_Supervisor"]:
            st.info("الأدمن والمدير العام لهما صلاحية على كافة الفروع تلقائياً.")
            assigned_b_id = None
        else:
            sel_user_branch = st.selectbox("الفرع المخصص:", list(b_opts_dict.keys()))
            assigned_b_id = b_opts_dict[sel_user_branch]
        
        if st.form_submit_button("حفظ المستخدم الجديد") and uname and upass:
            if urole == "Admin" and current_user_role != "Admin":
                st.error("لا يمكن إضافة أدمن إلا بواسطة أدمن آخر!")
            elif current_user_role == "General_Supervisor" and urole == "Admin":
                st.error("المدير العام ليس له صلاحية إضافة أدمن!")
            else:
                try:
                    conn.execute("INSERT INTO users (username, phone, password, role, branch_id, allowed_branches) VALUES (?, ?, ?, ?, ?, ?)", 
                                 (uname.strip(), uphone.strip(), upass, urole, assigned_b_id, "ALL" if urole in ["Admin", "General_Supervisor"] else str(assigned_b_id)))
                    conn.commit()
                    st.session_state["success_alert_msg"] = "تم حفظ المستخدم بنجاح!"
                    st.rerun()
                except Exception as e: st.error(f"خطأ: {e}")
    
    udf = pd.read_sql("SELECT users.id AS 'المسلسل', users.username AS 'المستخدم', users.role AS 'الرتبة', branches.branch_name AS 'الفرع' FROM users LEFT JOIN branches ON users.branch_id = branches.id", conn)
    if not udf.empty:
        st.dataframe(udf, use_container_width=True)
        del_u = st.selectbox("المستخدم للحذف:", udf["المسلسل"].tolist(), format_func=lambda x: f"مسلسل: {x} - الاسم: {udf[udf['المسلسل']==x]['المستخدم'].values[0]}")
        
        selected_row_user = conn.execute("SELECT username, role FROM users WHERE id = ?", (del_u,)).fetchone()
        is_admin_target = selected_row_user and (selected_row_user["role"] == "Admin" or selected_row_user["username"].strip().lower() == "admin")
        
        can_delete = True
        if is_admin_target and current_user_role != "Admin":
            can_delete = False
        if current_user_role == "General_Supervisor" and is_admin_target:
            can_delete = False
            
        if st.button("حذف المستخدم المختار", type="primary", disabled=not can_delete): 
            admin_confirm_dialog("حذف مستخدم", del_u)
    conn.close()

elif choice == "🛒 نقطة البيع (POS)":
  st.header("نقطة البيع (POS)")
  conn = get_db_connection()
  
  user_role = st.session_state.get("role", "")
  user_branch_id = st.session_state.get("branch_id")
  
  if user_role in ["Cashier", "Branch_Supervisor"] and user_branch_id:
      b_row = conn.execute("SELECT branch_name FROM branches WHERE id = ?", (user_branch_id,)).fetchone()
      branch_name_str = b_row["branch_name"] if b_row else "فرعي"
      st.info(f"الفرع: {branch_name_str}")
      b_id = user_branch_id
      pos_items = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
  else:
      b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
      sel_pos = st.selectbox("الفرع:", ["كل الفروع"] + list(b_dict.keys()))
      b_id = "ALL" if sel_pos == "كل الفروع" else b_dict[sel_pos]
      pos_items = conn.execute("SELECT * FROM items" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ?", (() if b_id=="ALL" else (b_id,))).fetchall()
  
  st.text_input("مسح الباركود أو إدخال كود الصنف:", key="unified_barcode", on_change=process_unified_barcode, placeholder="امسح الباركود أو اكتب الكود هنا واضغط Enter...")

  col_g, col_c = st.columns([2, 1])
  with col_g:
      st.markdown("### أصناف البيع المتاحة")
      if pos_items:
          for item in pos_items:
              c1, c2, c3 = st.columns([2, 1, 1])
              with c1: st.markdown(f"<div style='background:#f1f5f9; padding:6px; border-radius:4px;'><b>{item['item_name']}</b><br><small>المتاح: {item['quantity']} كجم</small></div>", unsafe_allow_html=True)
              with c2: st.markdown(f"<div style='padding:6px; text-align:center;'><b>{item['sale_price']} د.ل</b></div>", unsafe_allow_html=True)
              with c3:
                  with st.form(key=f"pos_q_{item['id']}", clear_on_submit=True):
                      q_in = st.number_input("كمية", min_value=0.0, value=0.0, step=0.1, format="%.2f", key=f"q_{item['id']}")
                      if st.form_submit_button("إضافة"):
                          if q_in > 0:
                              st.session_state["cart"].append({"id": item["id"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": float(q_in), "total": float(item["sale_price"]) * float(q_in)})
                              st.rerun()
      else:
          st.info("لا توجد أصناف مسجلة حالياً. يمكنك استخدام حقل الباركود بالاعلى لإضافة أصناف يدوية مباشرة للسلة وطباعة فاتورتها.")
          
  with col_c:
      st.markdown("### سلة المبيعات")
      if st.session_state["cart"]:
          for index, cart_item in enumerate(st.session_state["cart"]):
              col_item_desc, col_item_del = st.columns([3, 1])
              with col_item_desc:
                  st.markdown(f"**{cart_item['name']}**<br>`{cart_item['qty']} كجم` × `{cart_item['price']}` = **{cart_item['total']:,.2f} د.ل**", unsafe_allow_html=True)
              with col_item_del:
                  if st.button("❌", key=f"del_cart_item_{index}"):
                      st.session_state["cart"].pop(index)
                      st.rerun()
              st.markdown("---")
              
          g_tot = sum([x["total"] for x in st.session_state["cart"]])
          st.metric("الإجمالي", f"{g_tot:,.2f} د.ل")
          if st.button("إتمام وطباعة الفاتورة", type="primary", use_container_width=True): checkout_payment_dialog(b_id, g_tot)
          if st.button("تفريغ السلة", use_container_width=True): st.session_state["cart"] = []; st.rerun()
      else:
          st.info("السلة فارغة.")
  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
