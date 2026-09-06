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

ALL_MENUS = [
    "🏠 الرئيسية واللوحة",
    "🛒 نقطة البيع (POS)",
    "📦 إدارة المخزن الرئيسي والفروع",
    "🏢 تعديل وإدارة أسماء الفروع",
    "📁 استيراد الأصناف من Excel",
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
      CREATE TABLE IF NOT EXISTS purchase_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          purchase_id INTEGER,
          item_name TEXT,
          qty REAL,
          buy_price REAL,
          total REAL,
          FOREIGN KEY (purchase_id) REFERENCES purchases(id) ON DELETE CASCADE
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

  # إنشاء المخزن الرئيسي و 4 فروع افتراضية لو لم تكن موجودة
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

def process_barcode():
    code = st.session_state.barcode_scan.strip()
    if code:
        b_id = st.session_state.get("branch_id")
        conn = get_db_connection()
        item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
        conn.close()
        if item:
            st.session_state["cart"].append({
                "id": item["id"], "code": item["item_code"], "name": item["item_name"],
                "price": float(item["sale_price"]), "qty": 1.0, "total": float(item["sale_price"]) * 1.0
            })
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

for m in ALL_MENUS:
    if st.sidebar.button(m, use_container_width=True):
        st.session_state["page"] = m; st.rerun()

if st.sidebar.button("🚪 تسجيل الخروج", use_container_width=True):
    log_action(st.session_state["user_id"], "تسجيل خروج", "تم تسجيل الخروج")
    st.session_state.clear(); st.rerun()

choice = st.session_state["page"]

dashboard_cards = {
    "🛒 نقطة البيع (POS)": {"icon": "🛒", "color": "linear-gradient(135deg, #f59e0b, #ea580c)", "desc": "شاشة الكاشير والمبيعات"},
    "📦 إدارة المخزن الرئيسي والفروع": {"icon": "📦", "color": "linear-gradient(135deg, #3b82f6, #1d4ed8)", "desc": "جرد وإضافة الفائض بالمخازن"},
    "🏢 تعديل وإدارة أسماء الفروع": {"icon": "🏢", "color": "linear-gradient(135deg, #0ea5e9, #0369a1)", "desc": "إضافة وتعديل أسماء المخزن والفروع"},
    "📁 استيراد الأصناف من Excel": {"icon": "📁", "color": "linear-gradient(135deg, #10b981, #047857)", "desc": "تحميل واستيراد الأصناف بالإكسيل"},
    "📥 المشتريات والموردين": {"icon": "📥", "color": "linear-gradient(135deg, #6366f1, #4338ca)", "desc": "فواتير المشتريات للمخزن/الفروع"},
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

elif choice == "🏢 تعديل وإدارة أسماء الفروع":
  st.header("🏢 إدارة وتغيير أسماء الفروع والمخزن الرئيسي")
  conn = get_db_connection()
  
  with st.expander("➕ إضافة فرع جديد قابل للزيادة", expanded=False):
      with st.form("new_branch_form", clear_on_submit=True):
          nb_name = st.text_input("اسم الفرع الجديد (مثال: فرع 5 / فرع السوق)")
          nb_type = st.selectbox("النوع:", ["فرع", "مخزن"])
          if st.form_submit_button("💾 حفظ الفرع الجديد") and nb_name:
              conn.execute("INSERT INTO branches (branch_name, branch_type) VALUES (?, ?)", (nb_name.strip(), nb_type))
              conn.commit()
              st.success(f"🎉 تم إضافة الفرع ({nb_name}) بنجاح!")
              st.rerun()

  st.markdown("---")
  st.subheader("📋 تعديل أو إعادة تسمية الفروع الحالية")
  branches_df = pd.read_sql("SELECT id, branch_name AS 'اسم الفرع', branch_type AS 'النوع' FROM branches", conn)
  if not branches_df.empty:
      edited_branches = st.data_editor(branches_df, hide_index=True, key="branches_editor")
      if st.button("💾 حفظ التعديلات على أسماء الفروع"):
          for idx, row in edited_branches.iterrows():
              conn.execute("UPDATE branches SET branch_name=?, branch_type=? WHERE id=?", (row['اسم الفرع'], row['النوع'], row['id']))
          conn.commit()
          st.success("🎉 تم تحديث أسماء الفروع بنجاح وتعميمها في النظام!")
          st.rerun()
  conn.close()

elif choice == "📁 استيراد الأصناف من Excel":
  st.header("📁 استيراد وتوزيع الأصناف عبر ملف Excel")
  st.info("💡 قم برفع ملف إكسيل (.xlsx) يحتوي على أعمدة: (الكود، اسم الصنف، الكمية، سعر الشراء، سعر البيع) ليتم إضافتها مباشرة للمخزن أو الفرع المختار.")
  
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
          if st.button("💾 حفظ تعديلات الأسعار (تعميم فوري للفروع) أو الكميات"):
              for idx, row in edited_items.iterrows():
                  conn.execute("UPDATE items SET quantity=?, sale_price=? WHERE id=?", (row['الكمية (كيلو/عدد)'], row['سعر البيع (د.ل)'], row['id']))
                  conn.execute("UPDATE items SET sale_price=? WHERE item_name=?", (row['سعر البيع (د.ل)'], row['اسم الصنف']))
              conn.commit()
              st.success("🎉 تم التحديث والتعميم الفوري للأسعار على مستوى الفروع بنجاح!")
              st.rerun()
          st.download_button("📥 تصدير المخزون لـ Excel", data=to_excel(items_df), file_name=f"inventory_{sel_b_name}.xlsx")
      else:
          st.info("لا توجد أصناف مسجلة في هذا الفرع بعد.")

  with tab2:
      st.subheader("➕ إضافة فائض فرع (للأصناف التي رصيدها صفر)")
      st.info("💡 هذه الخاصية تعرض فقط الأصناف التي رصيدها (صفر) في هذا الفرع ليقوم المسؤول بإضافة فائض منها بنفس أسعارها السابقة.")
      
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
      
      if st.form_submit_button("💾 حفظ وتسجيل فاتورة المشتريات وإضافتها للمخزون"):
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
  st.info("💡 مخصص لتحويل المواد الخام (مثل: لوز ني) بكميات وأسعار معينة، وبعد التسوية أو الخلط تخرج بمسمى آخر وسعر آخر (مثل: لوز طايب) وتضاف للمخزن بمرة واحدة.")
  
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
          
          if st.form_submit_button("⚙️ تنفيذ التحميص وتحديث المخزون (خصم الخام وإضافة الناتج)"):
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
                  st.success(f"🥜 تمت عملية التحميص بنجاح! تم خصم الخام وإضافة المنتج الجديد ({new_item_name}) بكميته وسعره الجديد.")
              else:
                  st.warning("⚠️ تأكد من كتابة الاسم الجديد وأن الكمية الخام المستخدمة لا تزيد عن المتاح بالمخزن.")
      else:
          st.warning("لا توجد أصناف في هذا الفرع لإجراء عمليات تحميص عليها.")
  conn.close()

elif choice == "📊 الأرباح والخسائر والتقارير":
  st.header("📊 تقارير الأرباح والخسائر والمبيعات")
  conn = get_db_connection()
  
  tab1, tab2 = st.tabs(["💰 حساب الأرباح والخسائر", "📈 تقارير المبيعات الشاملة"])
  with tab1:
      st.subheader("تقرير الأرباح والخسائر المالي")
      total_sales = conn.execute("SELECT SUM(total_amount) FROM invoices WHERE shift_status != 'canceled'").fetchone()[0] or 0.0
      total_purchases = conn.execute("SELECT SUM(total_cost) FROM purchases").fetchone()[0] or 0.0
      
      net_profit = total_sales - total_purchases
      
      col1, col2, col3 = st.columns(3)
      with col1: st.metric("إجمالي المبيعات", f"{total_sales:,.2f} د.ل")
      with col2: st.metric("إجمالي المشتريات", f"{total_purchases:,.2f} د.ل")
      with col3: st.metric("صافي الربح / الخسارة", f"{net_profit:,.2f} د.ل", delta=f"{net_profit:,.2f}")

  with tab2:
      st.subheader("سجل الفواتير والمبيعات")
      sales_df = pd.read_sql("SELECT invoices.id AS 'رقم الفاتورة', branches.branch_name AS 'الفرع', users.username AS 'الكاشير', invoices.total_amount AS 'الإجمالي', invoices.payment_method AS 'طريقة الدفع', invoices.created_at AS 'التاريخ' FROM invoices LEFT JOIN branches ON invoices.branch_id = branches.id LEFT JOIN users ON invoices.user_id = users.id ORDER BY invoices.id DESC", conn)
      if not sales_df.empty:
          st.dataframe(sales_df, use_container_width=True)
          st.download_button("📥 تصدير المبيعات لـ Excel", data=to_excel(sales_df), file_name="sales_report.xlsx")
      else:
          st.info("لا توجد مبيعات مسجلة حتى الآن.")
  conn.close()

elif choice == "👥 إدارة المستخدمين وصلاحياتهم":
  st.header("👥 إدارة المستخدمين والصلاحيات")
  conn = get_db_connection()
  
  with st.expander("➕ إضافة مستخدم جديد (كاشير أو مشرف)", expanded=False):
      with st.form("new_user_form", clear_on_submit=True):
          u_name = st.text_input("اسم المستخدم")
          u_phone = st.text_input("رقم الهاتف")
          u_pass = st.text_input("كلمة المرور")
          u_role = st.selectbox("الرتبة:", ["Admin (مدير النظام)", "Branch_Supervisor (مشرف فرع)", "Cashier (كاشير)"])
          
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
  st.header("🛒 شاشة الكاشير (POS)")
  conn = get_db_connection()
  
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  b_dict = {b["branch_name"]: b["id"] for b in branches}
  
  if st.session_state["role"] == "Admin":
      sel_pos_branch = st.selectbox("اختر الفرع للبيع:", list(b_dict.keys()))
      b_id = b_dict[sel_pos_branch]
  else:
      b_id = st.session_state.get("branch_id")
      
  if b_id:
      items = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
      
      col_g, col_c = st.columns([2, 1])
      with col_g:
          st.subheader("الأصناف المتاحة للبيع")
          st.text_input("🔍 مسح باركود صنف:", key="barcode_scan", on_change=process_barcode)
          
          if items:
              for item in items:
                  col_i1, col_i2, col_i3 = st.columns([2, 1, 1])
                  with col_i1: st.write(f"**{item['item_name']}** (متاح: {item['quantity']})")
                  with col_i2: st.write(f"{item['sale_price']} د.ل")
                  with col_i3:
                      if st.button(f"➕ إضافة", key=f"p_{item['id']}"):
                          st.session_state["cart"].append({
                              "id": item["id"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": 1.0, "total": float(item["sale_price"])
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
