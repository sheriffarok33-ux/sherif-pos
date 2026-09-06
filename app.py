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
    "💰 تسجيل المصروفات والمصروف العام",
    "📥 المشتريات والموردين",
    "🥜 التحميص والخلط والتصنيع",
    "📊 الأرباح والخسائر والتقارير",
    "👥 إدارة المستخدمين وصلاحياتهم"
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
      CREATE TABLE IF NOT EXISTS activity_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          action TEXT,
          details TEXT,
          log_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
      )
  """)

  # إنشاء المخزن الرئيسي و 4 فروع افتراضية
  default_branches = [("المخزن الرئيسي", "مخزن"), ("فرع 1", "فرع"), ("فرع 2", "فرع"), ("فرع 3", "فرع"), ("فرع 4", "فرع")]
  for b_name, b_type in default_branches:
      cursor.execute("INSERT OR IGNORE INTO branches (branch_name, branch_type) VALUES (?, ?)", (b_name, b_type))

  # حماية يوزر الأدمن الأساسي
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
              
              log_action(user["id"], "تسجيل دخول", f"تم دخول المستخدم {user['username']}")
              conn.close(); st.rerun()
          else: 
              conn.close(); st.error("🎭 **هَنّي روحك.. اسم المستخدم أو كلمة المرور غير صحيحة!**")
  st.stop()

# --- القائمة الجانبية والشعار ---
st.sidebar.markdown("<h2 style='text-align: center;'>🥜 محامص أبو زيد</h2>", unsafe_allow_html=True)
st.sidebar.markdown(f"**👤 {st.session_state['username']} | `{st.session_state['role']}`**")
st.sidebar.markdown("---")

for m in DEFAULT_MENUS:
    if st.sidebar.button(m, use_container_width=True):
        st.session_state["page"] = m; st.rerun()

if st.sidebar.button("🚪 تسجيل الخروج", use_container_width=True):
    log_action(st.session_state["user_id"], "تسجيل خروج", "تم تسجيل الخروج")
    st.session_state.clear(); st.rerun()

choice = st.session_state["page"]

dashboard_cards = {
    "🛒 نقطة البيع (POS)": {"icon": "🛒", "color": "linear-gradient(135deg, #f59e0b, #ea580c)", "desc": "شاشة الكاشير ومبيعات الميزان"},
    "📦 إدارة المخزن الرئيسي والفروع": {"icon": "📦", "color": "linear-gradient(135deg, #3b82f6, #1d4ed8)", "desc": "جرد وإضافة الفائض بالمخازن"},
    "🔄 نقل وتحويل الأصناف للفروع": {"icon": "🔄", "color": "linear-gradient(135deg, #8b5cf6, #6d28d9)", "desc": "تحويل وتوزيع الأصناف من المخزن الرئيسي"},
    "💰 تسجيل المصروفات والمصروف العام": {"icon": "💸", "color": "linear-gradient(135deg, #0ea5e9, #0369a1)", "desc": "تسجيل المصروفات وتوزيعها تلقائياً على الفروع"},
    "📥 المشتريات والموردين": {"icon": "📥", "color": "linear-gradient(135deg, #10b981, #047857)", "desc": "فواتير المشتريات للمخزن/الفروع"},
    "🥜 التحميص والخلط والتصنيع": {"icon": "🥜", "color": "linear-gradient(135deg, #d946ef, #a21caf)", "desc": "تحويل الني إلى طايب وتغيير الأسماء"}
}

# --- محتوى الصفحات ---
if choice == "🏠 الرئيسية واللوحة":
  st.title("🌟 مجموعة أبو زيد - لوحة التحكم الرئيسية")
  cols = st.columns(3)
  for i, (item, data) in enumerate(dashboard_cards.items()):
      with cols[i % 3]:
          st.markdown(f'''<div style="background: {data['color']}; padding: 25px 15px; border-radius: 16px; color: white; text-align: center; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); margin-bottom: 10px; min-height: 150px;"><h1 style="margin:0; font-size: 45px;">{data['icon']}</h1><h3 style="margin: 10px 0 5px 0;">{item.split(" ", 1)[1]}</h3><p style="margin:0; font-size: 14px; opacity: 0.9;">{data['desc']}</p></div>''', unsafe_allow_html=True)
          st.button(f"دخول ➔", key=f"btn_{i}", on_click=set_page, args=(item,), use_container_width=True)
          st.markdown("<br>", unsafe_allow_html=True)

elif choice == "💰 تسجيل المصروفات والمصروف العام":
  st.header("💰 تسجيل المصروفات وتوزيعها على الفروع")
  st.info("💡 يمكنك تسجيل مصروف خاص بفرع معين، أو تسجيل مصروف عام للمخزن ليتم **توزيعه تلقائياً بالتساوي على كافة الفروع الحالية وأي فرع جديد يُضاف مستقبلاً**.")
  
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  with st.form("expense_form", clear_on_submit=True):
      exp_type = st.radio("نوع المصروف:", ["مصروف خاص بفرع معين", "🌍 مصروف عام للمخزن (يتوزع تلقائياً على كل الفروع الحالية والجديدة)"])
      
      sel_b_name = ""
      if exp_type == "مصروف خاص بفرع معين":
          sel_b_name = st.selectbox("اختر الفرع المستهدف للمصروف:", list(b_dict.keys()))
          
      exp_amount = st.number_input("مبلغ المصروف (د.ل):", min_value=0.1, value=50.0)
      exp_desc = st.text_input("بيان أو وصف المصروف (مثال: كهرباء، نظافة، صيانة...):")
      
      if st.form_submit_button("💾 حفظ وتسجيل المصروف"):
          if exp_amount > 0 and exp_desc:
              cur_ex = conn.cursor()
              if exp_type == "مصروف خاص بفرع معين":
                  target_bid = b_dict[sel_b_name]
                  cur_ex.execute("INSERT INTO expenses (branch_id, amount, description, is_general_store) VALUES (?, ?, ?, 0)", (target_bid, exp_amount, exp_desc.strip()))
                  conn.commit()
                  st.success(f"💸 تم تسجيل المصروف لفرع ({sel_b_name}) بنجاح!")
              else:
                  # المصروف العام: يتوزع على كافة الفروع
                  cur_ex.execute("INSERT INTO expenses (branch_id, amount, description, is_general_store) VALUES (NULL, ?, ?, 1)", (exp_amount, exp_desc.strip()))
                  conn.commit()
                  st.success("🌍 تم تسجيل المصروف العام وتوزيعه تلقائياً على كافة الفروع الحالية والمستقبلية بنجاح!")
              log_action(st.session_state["user_id"], "تسجيل مصروف", f"مبلغ {exp_amount} - {exp_desc}")
              st.rerun()
          else:
              st.warning("الرجاء إدخال المبلغ ووصف المصروف.")
  
  st.markdown("---")
  st.subheader("📋 سجل المصروفات المسجلة")
  exp_df = pd.read_sql("SELECT expenses.id AS 'رقم', IFNULL(branches.branch_name, '🌍 مصروف عام (موزع)') AS 'الجهة / الفرع', expenses.amount AS 'المبلغ', expenses.description AS 'البيان', expenses.expense_date AS 'التاريخ' FROM expenses LEFT JOIN branches ON expenses.branch_id = branches.id ORDER BY expenses.id DESC", conn)
  if not exp_df.empty:
      st.dataframe(exp_df, use_container_width=True)
      st.download_button("📥 تصدير المصروفات لـ Excel", data=to_excel(exp_df), file_name="expenses_report.xlsx")
  else:
      st.info("لا توجد مصروفات مسجلة حتى الآن.")
  conn.close()

elif choice == "🔄 نقل وتحويل الأصناف للفروع":
  st.header("🔄 نقل وتحويل الأصناف من المخزن الرئيسي إلى الفروع")
  conn = get_db_connection()
  main_store = conn.execute("SELECT id FROM branches WHERE branch_type = 'مخزن' LIMIT 1").fetchone()
  
  if main_store:
      main_id = main_store["id"]
      main_items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND quantity > 0", (main_id,)).fetchall()
      other_branches = conn.execute("SELECT id, branch_name FROM branches WHERE id != ?", (main_id,)).fetchall()
      
      if main_items and other_branches:
          with st.form("transfer_form", clear_on_submit=True):
              m_opts = {f"[{i['item_code']}] {i['item_name']} (متاح بالمخزن: {i['quantity']} | السعر: {i['sale_price']} د.ل)": i for i in main_items}
              sel_m_label = st.selectbox("اختر الصنف من المخزن الرئيسي للتحويل:", list(m_opts.keys()))
              chosen_item = m_opts[sel_m_label]
              
              b_opts = {b["branch_name"]: b["id"] for b in other_branches}
              sel_target_b = st.selectbox("إلى الفرع المستهدف:", list(b_opts.keys()))
              target_b_id = b_opts[sel_target_b]
              
              trans_qty = st.number_input("الكمية المراد تحويلها:", min_value=0.01, value=1.0, step=0.1, format="%.2f")
              
              if st.form_submit_button("🚀 تنفيذ النقل والتحويل الفوري"):
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
                      log_action(st.session_state["user_id"], "تحويل مخزون", f"تحويل {trans_qty} من {chosen_item['item_name']} إلى {sel_target_b}")
                      st.success(f"🚀 تم تحويل ({trans_qty}) من ({chosen_item['item_name']}) إلى ({sel_target_b}) بنجاح!")
                      st.rerun()
                  else:
                      st.warning("⚠️ الكمية المراد تحويلها أكبر من المتاح في المخزن الرئيسي.")
      else:
          st.warning("⚠️ المخزن الرئيسي خالي من الأصناف أو لا توجد فروع أخرى للاستلام.")
  else:
      st.error("⚠️ لم يتم العثور على 'مخزن رئيسي' معرف في النظام.")
  conn.close()

elif choice == "📁 استيراد الأصناف من Excel":
  st.header("📁 استيراد وتوزيع الأصناف عبر ملف Excel")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  sel_target_branch = st.selectbox("اختر الفرع أو المخزن المستهدف لتنزيل الأصناف فيه:", list(b_dict.keys()))
  target_b_id = b_dict[sel_target_branch]
  
  up_excel = st.file_uploader("اختر ملف الإكسيل (.xlsx)", type=["xlsx", "xls"])
  if up_excel and st.button("📥 تنفيذ استيراد وتحميل الأصناف"):
      try:
          df_exc = pd.read_excel(up_excel, header=None)
          cur_ex = conn.cursor()
          count_imp = 0
          for idx, row in df_exc.iterrows():
              if row.isna().all(): continue
              name = str(row.iloc[1]).strip() if len(row)>1 and not pd.isna(row.iloc[1]) else ""
              if not name or name.lower() in ["nan", "null", "item"] or name in ["الصنف", "اسم الصنف", "صنف"]: continue
              code = str(row.iloc[0]).strip() if len(row)>0 and not pd.isna(row.iloc[0]) else "GEN-01"
              try: qty = float(row.iloc[2]) if len(row)>2 and not pd.isna(row.iloc[2]) else 0.0
              except: qty = 0.0
              try: b_pr = float(row.iloc[3]) if len(row)>3 and not pd.isna(row.iloc[3]) else 0.0
              except: b_pr = 0.0
              try: s_pr = float(row.iloc[4]) if len(row)>4 and not pd.isna(row.iloc[4]) else 10.0
              except: s_pr = 10.0
              
              cur_ex.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)", 
                             (target_b_id, code, name, qty, b_pr, s_pr))
              count_imp += 1
          conn.commit()
          st.success(f"🎉 تم استيراد وتحميل ({count_imp}) صنف بنجاح إلى مخزن/فرع ({sel_target_branch})!")
      except Exception as e:
          st.error(f"حدث خطأ أثناء قراءة الملف: {e}")
  conn.close()

elif choice == "📦 إدارة المخزن الرئيسي والفروع":
  st.header("📦 إدارة المخزن الرئيسي والفروع وإضافة الفائض")
  conn = get_db_connection()
  
  branches = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  sel_b_name = st.selectbox("اختر المخزن أو الفرع للاستعراض:", list(b_dict.keys()))
  current_b_id = b_dict[sel_b_name]
  
  tab1, tab2 = st.tabs(["📋 جرد ومتابعة الأصناف والأسعار الفورية", "➕ زر إضافة فائض فرع (رصيد صفر)"])
  
  with tab1:
      st.subheader(f"مخزون: {sel_b_name}")
      items_df = pd.read_sql("SELECT id, item_code AS 'الكود', item_name AS 'اسم الصنف', quantity AS 'الكمية (كيلو/عدد)', sale_price AS 'سعر البيع (د.ل)' FROM items WHERE branch_id = ?", conn, params=(current_b_id,))
      
      if not items_df.empty:
          edited_items = st.data_editor(items_df, hide_index=True, key="inv_editor")
          if st.button("💾 حفظ وتعميم تعديلات الأسعار والأسماء فوراً على النظام"):
              for idx, row in edited_items.iterrows():
                  conn.execute("UPDATE items SET item_name=?, quantity=?, sale_price=? WHERE id=?", (row['اسم الصنف'], row['الكمية (كيلو/عدد)'], row['سعر البيع (د.ل)'], row['id']))
                  conn.execute("UPDATE items SET item_name=?, sale_price=? WHERE item_code=?", (row['اسم الصنف'], row['سعر البيع (د.ل)'], row['الكود']))
              conn.commit()
              st.success("🎉 تم التحديث والتعميم الفوري للأسماء والأسعار على مستوى كافة الفروع بنجاح!")
              st.rerun()
          st.download_button("📥 تصدير المخزون لـ Excel", data=to_excel(items_df), file_name=f"inventory_{sel_b_name}.xlsx")
      else:
          st.info("لا توجد أصناف مسجلة في هذا الفرع بعد.")

  with tab2:
      st.subheader("➕ إضافة فائض فرع (للأصناف التي رصيدها صفر)")
      zero_items = conn.execute("SELECT DISTINCT item_code, item_name, sale_price, buy_price FROM items WHERE branch_id = ? AND quantity <= 0", (current_b_id,)).fetchall()
      
      if zero_items:
          z_options = {f"[{i['item_code']}] {i['item_name']} (السعر: {i['sale_price']} د.ل)": i for i in zero_items}
          with st.form("surplus_form", clear_on_submit=True):
              chosen_z_label = st.selectbox("اختر الصنف ذو الرصيد الصفر لإضافة فائض له:", list(z_options.keys()))
              surplus_qty = st.number_input("الكمية الفائضة المراد إضافتها:", min_value=0.01, value=1.0, step=0.1, format="%.2f")
              
              if st.form_submit_button("💾 اعتماد وإضافة الفائض للفرع"):
                  z_item = z_options[chosen_z_label]
                  existing_z = conn.execute("SELECT id FROM items WHERE branch_id = ? AND item_name = ?", (current_b_id, z_item['item_name'])).fetchone()
                  if existing_z:
                      conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (surplus_qty, existing_z['id']))
                  else:
                      conn.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)", 
                                   (current_b_id, z_item['item_code'], z_item['item_name'], surplus_qty, z_item['buy_price'], z_item['sale_price']))
                  conn.commit()
                  log_action(st.session_state["user_id"], "إضافة فائض", f"إضافة فائض {surplus_qty} للصنف {z_item['item_name']} في {sel_b_name}")
                  st.success(f"🚀 تمت إضافة الفائض للصنف ({z_item['item_name']}) بنجاح وبنفس أسعاره السابقة!")
                  st.rerun()
      else:
          st.success("✨ ممتاز! لا توجد أصناف برصيد (صفر) في هذا الفرع حالياً.")
  conn.close()

elif choice == "📥 المشتريات والموردين":
  st.header("📥 تسجيل فواتير المشتريات والموردين")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  with st.form("purchase_form", clear_on_submit=True):
      p_branch = st.selectbox("المخزن أو الفرع المشتري له:", list(b_dict.keys()))
      supplier = st.text_input("اسم المورد / الشركة الموردة")
      
      st.markdown("---")
      col1, col2, col3 = st.columns(3)
      with col1: p_item_name = st.text_input("اسم الصنف المشتري")
      with col2: p_qty = st.number_input("الكمية", min_value=0.01, value=1.0, step=0.1)
      with col3: p_buy_price = st.number_input("سعر الشراء للوحدة/كيلو", min_value=0.01, value=10.0)
      
      p_sale_price = st.number_input("سعر البيع المقترح:", min_value=0.01, value=15.0)
      
      if st.form_submit_button("💾 حفظ وتسجيل فاتورة المشتريات وإضافتها للمخزن"):
          if p_item_name and supplier:
              total_p_cost = p_qty * p_buy_price
              cur = conn.cursor()
              cur.execute("INSERT INTO purchases (branch_id, supplier_name, total_cost) VALUES (?, ?, ?)", (b_dict[p_branch], supplier.strip(), total_p_cost))
              p_id = cur.lastrowid
              cur.execute("INSERT INTO purchase_items (purchase_id, item_name, qty, buy_price, total) VALUES (?, ?, ?, ?, ?)", (p_id, p_item_name.strip(), p_qty, p_buy_price, total_p_cost))
              
              b_target_id = b_dict[p_branch]
              exist_item = cur.execute("SELECT id FROM items WHERE branch_id = ? AND item_name = ?", (b_target_id, p_item_name.strip())).fetchone()
              if exist_item:
                  cur.execute("UPDATE items SET quantity = quantity + ?, buy_price = ?, sale_price = ? WHERE id = ?", (p_qty, p_buy_price, p_sale_price, exist_item['id']))
              else:
                  cur.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, 'PUR-001', ?, ?, ?, ?)", (b_target_id, p_item_name.strip(), p_qty, p_buy_price, p_sale_price))
              
              conn.commit()
              log_action(st.session_state["user_id"], "مشتريات", f"شراء {p_qty} من {p_item_name} للمورد {supplier}")
              st.success("📦 تم تسجيل فاتورة المشتريات وتحديث المخزون الرئيسي/الفرع بنجاح!")
          else:
              st.warning("الرجاء إدخال اسم المورد واسم الصنف.")
  conn.close()

elif choice == "🥜 التحميص والخلط والتصنيع":
  st.header("🥜 قسم التحميص والخلط وتغيير المسميات")
  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  with st.form("roast_transform_form", clear_on_submit=True):
      r_branch = st.selectbox("المخزن أو الفرع الذي تتم فيه عملية التحميص:", list(b_dict.keys()))
      b_id_val = b_dict[r_branch]
      
      items_list = conn.execute("SELECT item_name, sale_price, quantity FROM items WHERE branch_id = ?", (b_id_val,)).fetchall()
      items_opts = {f"{i['item_name']} (متاح: {i['quantity']} | سعر البيع: {i['sale_price']} د.ل)": i for i in items_list} if items_list else {}
      
      if items_opts:
          raw_item_label = st.selectbox("اختر الصنف الخام الداخل (مثال: لوز ني):", list(items_opts.keys()))
          raw_item = items_opts[raw_item_label]
          
          raw_qty_used = st.number_input("الكمية المستخدمة من الخام:", min_value=0.01, value=10.0, step=0.1)
          
          st.markdown("---")
          st.write("النتيجة بعد التحميص / الخلط:")
          new_item_name = st.text_input("اسم المنتج الناتج بعد التحميص (مثال: لوز طايب مالح):")
          new_item_qty = st.number_input("الكمية الناتجة بعد التحميص:", min_value=0.01, value=8.5, step=0.1)
          new_item_price = st.number_input("سعر البيع الجديد للوحدة/كيلو:", min_value=0.01, value=25.0)
          
          if st.form_submit_button("⚙️ تنفيذ التحميص وتحديث المخزون"):
              if new_item_name and raw_qty_used <= raw_item['quantity']:
                  cur_r = conn.cursor()
                  cur_r.execute("UPDATE items SET quantity = quantity - ? WHERE branch_id = ? AND item_name = ?", (raw_qty_used, b_id_val, raw_item['item_name'].split(' (')[0]))
                  
                  exist_out = cur_r.execute("SELECT id FROM items WHERE branch_id = ? AND item_name = ?", (b_id_val, new_item_name.strip())).fetchone()
                  if exist_out:
                      cur_r.execute("UPDATE items SET quantity = quantity + ?, sale_price = ? WHERE id = ?", (new_item_qty, new_item_price, exist_out['id']))
                  else:
                      cur_r.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, 'ROAST-01', ?, ?, 0.0, ?)", (b_id_val, new_item_name.strip(), new_item_qty, new_item_price))
                  
                  conn.commit()
                  log_action(st.session_state["user_id"], "تحميص وتصنيع", f"تحويل {raw_qty_used} من {raw_item['item_name']} إلى {new_item_qty} من {new_item_name}")
                  st.success(f"🥜 تمت عملية التحميص بنجاح!")
              else:
                  st.warning("⚠️ تأكد من كتابة الاسم الجديد وأن الكمية الخام المستخدمة لا تزيد عن المتاح بالمخزن.")
      else:
          st.warning("لا توجد أصناف في هذا الفرع لإجراء عمليات تحميص عليها.")
  conn.close()

elif choice == "📊 الأرباح والخسائر والتقارير":
  st.header("📊 الأرباح والخسائر والتقارير التفصيلية لكل فرع")
  conn = get_db_connection()
  
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  # اختيار الفرع لعرض تقريره على حدة أو عرض الكل
  report_branch_options = {"🌐 إجمالي كل الفروع والمخزن (شامل)": "ALL"}
  report_branch_options.update(b_dict)
  
  sel_report_target = st.selectbox("اختر الفرع لعرض تقريره المالي بالتفصيل:", list(report_branch_options.keys()))
  target_rep_id = report_branch_options[sel_report_target]
  
  # حساب المصروف العام وتوزيعه على عدد الفروع تلقائياً
  total_branches_count = len(branches) if len(branches) > 0 else 1
  general_expenses_total = conn.execute("SELECT SUM(amount) FROM expenses WHERE is_general_store = 1").fetchone()[0] or 0.0
  share_general_expense = general_expenses_total / total_branches_count
  
  if target_rep_id == "ALL":
      total_sales = conn.execute("SELECT SUM(total_amount) FROM invoices WHERE shift_status != 'canceled'").fetchone()[0] or 0.0
      total_purchases = conn.execute("SELECT SUM(total_cost) FROM purchases").fetchone()[0] or 0.0
      total_direct_expenses = conn.execute("SELECT SUM(amount) FROM expenses WHERE is_general_store = 0").fetchone()[0] or 0.0
      total_all_expenses = total_direct_expenses + general_expenses_total
      net_profit = total_sales - (total_purchases + total_all_expenses)
      
      st.subheader("📊 ملخص النتائج المالية الشاملة لكل المجموعة")
      c1, c2, c3, c4 = st.columns(4)
      with c1: st.metric("إجمالي المبيعات", f"{total_sales:,.2f} د.ل")
      with c2: st.metric("إجمالي المشتريات", f"{total_purchases:,.2f} د.ل")
      with c3: st.metric("إجمالي المصروفات (مباشر وعام)", f"{total_all_expenses:,.2f} د.ل")
      with c4: st.metric("صافي الربح / الخسارة", f"{net_profit:,.2f} د.ل", delta=f"{net_profit:,.2f}")
      
      sales_df = pd.read_sql("SELECT invoices.id AS 'رقم الفاتورة', branches.branch_name AS 'الفرع', users.username AS 'الكاشير', invoices.total_amount AS 'الإجمالي', invoices.payment_method AS 'طريقة الدفع', invoices.created_at AS 'التاريخ' FROM invoices LEFT JOIN branches ON invoices.branch_id = branches.id LEFT JOIN users ON invoices.user_id = users.id ORDER BY invoices.id DESC", conn)
      if not sales_df.empty:
          st.markdown("---")
          st.subheader("سجل مبيعات كل الفروع")
          st.dataframe(sales_df, use_container_width=True)
          st.download_button("📥 تصدير تقرير المبيعات لـ Excel", data=to_excel(sales_df), file_name="all_branches_sales.xlsx")
  else:
      branch_sales = conn.execute("SELECT SUM(total_amount) FROM invoices WHERE branch_id = ? AND shift_status != 'canceled'", (target_rep_id,)).fetchone()[0] or 0.0
      branch_purchases = conn.execute("SELECT SUM(total_cost) FROM purchases WHERE branch_id = ?", (target_rep_id,)).fetchone()[0] or 0.0
      branch_direct_exp = conn.execute("SELECT SUM(amount) FROM expenses WHERE branch_id = ?", (target_rep_id,)).fetchone()[0] or 0.0
      branch_total_exp = branch_direct_exp + share_general_expense
      branch_net = branch_sales - (branch_purchases + branch_total_exp)
      
      st.subheader(f"📊 النتائج المالية التفصيلية لـ: {sel_report_target}")
      c1, c2, c3, c4 = st.columns(4)
      with c1: st.metric("مبيعات الفرع", f"{branch_sales:,.2f} د.ل")
      with c2: st.metric("مشتريات الفرع", f"{branch_purchases:,.2f} د.ل")
      with c3: st.metric("مصروفات الفرع (شاملة حصة العام)", f"{branch_total_exp:,.2f} د.ل")
      with c4: st.metric("صافي ربح الفرع", f"{branch_net:,.2f} د.ل", delta=f"{branch_net:,.2f}")
      
      b_sales_df = pd.read_sql("SELECT invoices.id AS 'رقم الفاتورة', users.username AS 'الكاشير', invoices.total_amount AS 'الإجمالي', invoices.payment_method AS 'طريقة الدفع', invoices.created_at AS 'التاريخ' FROM invoices LEFT JOIN users ON invoices.user_id = users.id WHERE invoices.branch_id = ? ORDER BY invoices.id DESC", conn, params=(target_rep_id,))
      if not b_sales_df.empty:
          st.markdown("---")
          st.subheader(f"فواتير ومبيعات {sel_report_target}")
          st.dataframe(b_sales_df, use_container_width=True)
          st.download_button(f"📥 تصدير مبيعات {sel_report_target} لـ Excel", data=to_excel(b_sales_df), file_name=f"sales_{sel_report_target}.xlsx")
  conn.close()

elif choice == "👥 إدارة المستخدمين وصلاحياتهم":
  st.header("👥 إدارة المستخدمين والصلاحيات (أدمن، مدير عام، مدير فرع، كاشير)")
  conn = get_db_connection()
  
  with st.expander("➕ إضافة مستخدم جديد", expanded=False):
      with st.form("new_user_form", clear_on_submit=True):
          u_name = st.text_input("اسم المستخدم")
          u_phone = st.text_input("رقم الهاتف")
          u_pass = st.text_input("كلمة المرور")
          u_role = st.selectbox("الرتبة:", ["Admin (مدير النظام)", "General_Supervisor (مدير عام)", "Branch_Supervisor (مدير فرع)", "Cashier (كاشير)"])
          
          branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
          b_dict = {b["branch_name"]: b["id"] for b in branches}
          u_branch = st.selectbox("الفرع التابع له:", list(b_dict.keys()))
          
          if st.form_submit_button("💾 حفظ المستخدم"):
              if u_name and u_pass:
                  conn.execute("INSERT INTO users (username, phone, password, role, branch_id) VALUES (?, ?, ?, ?, ?)", (u_name.strip(), u_phone.strip(), u_pass, u_role.split(" ")[0], b_dict[u_branch]))
                  conn.commit()
                  st.success("🎉 تم إضافة المستخدم بنجاح!")
                  st.rerun()

  users_df = pd.read_sql("SELECT users.id, users.username AS 'اسم المستخدم', users.phone AS 'الهاتف', users.role AS 'الرتبة', branches.branch_name AS 'الفرع' FROM users LEFT JOIN branches ON users.branch_id = branches.id", conn)
  if not users_df.empty:
      st.dataframe(users_df, use_container_width=True)
  conn.close()

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير (POS) - قراءة باركود الميزان الإلكتروني")
  conn = get_db_connection()
  
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  if st.session_state["role"] == "Admin":
      sel_pos_branch = st.selectbox("اختر الفرع للبيع:", list(b_dict.keys()))
      b_id = b_dict[sel_pos_branch]
  else:
      b_id = st.session_state.get("branch_id")
      
  if b_id:
      items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND quantity > 0", (b_id,)).fetchall()
      
      col_g, col_c = st.columns([2, 1])
      with col_g:
          st.subheader("الأصناف المتاحة للبيع (ذات رصيد)")
          st.text_input("🔍 مسح باركود الصنف أو باركود الميزان (Scale Barcode):", key="barcode_scan", on_change=process_scale_barcode)
          
          if items:
              for item in items:
                  col_i1, col_i2, col_i3 = st.columns([2, 1, 1])
                  with col_i1: st.write(f"**{item['item_name']}** (المتاح: {item['quantity']})")
                  with col_i2: st.write(f"{item['sale_price']} د.ل")
                  with col_i3:
                      with st.form(key=f"pos_qty_form_{item['id']}", clear_on_submit=True):
                          p_qty_input = st.number_input("الكمية / الوزن", min_value=0.01, value=1.0, step=0.1, format="%.2f", key=f"q_{item['id']}")
                          if st.form_submit_button("➕ إضافة"):
                              st.session_state["cart"].append({
                                  "id": item["id"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": float(p_qty_input), "total": float(item["sale_price"]) * float(p_qty_input)
                              })
                              st.success("تمت الإضافة!")
                              st.rerun()
          else:
              st.info("لا توجد أصناف برصيد متاح في هذا الفرع حالياً.")

      with col_c:
          st.subheader("سلة المبيعات")
          if st.session_state["cart"]:
              df_c = pd.DataFrame(st.session_state["cart"])
              st.dataframe(df_c[["name", "price", "qty", "total"]], use_container_width=True)
              g_tot = sum([x["total"] for x in st.session_state["cart"]])
              st.metric("الإجمالي", f"{g_tot:,.2f} د.ل")
              
              if st.button("🖨️ إتمام البيع وطباعة الفاتورة", type="primary", use_container_width=True):
                  cur_in = conn.cursor()
                  cur_in.execute("INSERT INTO invoices (branch_id, user_id, total_amount) VALUES (?, ?, ?)", (b_id, st.session_state["user_id"], g_tot))
                  inv_id = cur_in.lastrowid
                  for c_item in st.session_state["cart"]:
                      conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                  conn.commit()
                  st.session_state["cart"] = []
                  st.success(f"🎉 تم إتمام الفاتورة رقم #{inv_id} بنجاح!")
                  st.rerun()
              if st.button("🗑️ تفريغ السلة", use_container_width=True):
                  st.session_state["cart"] = []
                  st.rerun()
          else:
              st.info("السلة فارغة.")
  conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
