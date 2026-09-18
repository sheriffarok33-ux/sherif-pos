import os
import io
import sqlite3
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta

st.set_page_config(
    page_title="مجموعة أبو زيد التجارية - النظام المالي والمخزني",
    layout="wide",
    initial_sidebar_state="expanded",
)

if not os.path.exists("item_images"): os.makedirs("item_images")

# القوائم الجانبية مطابقة لنظامهم الفعلي الموضح في الصور
DEFAULT_MENUS = [
    "🛒 نقطة بيع",
    "📦 أصناف",
    "📄 فواتير",
    "💵 الإيصالات (مقبوضات ومدفوعات)",
    "👥 عملاء وموردين",
    "💰 المصروفات",
    "💼 الخزينة",
    "📊 التقارير",
    "⚙️ الجرد"
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
              category TEXT DEFAULT 'مكسرات',
              quantity REAL DEFAULT 0.0,
              buy_price REAL DEFAULT 0.0,
              sale_price REAL NOT NULL,
              wholesale_price REAL DEFAULT 0.0,
              avg_cost REAL DEFAULT 0.0,
              FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
          )
      """)
      # جدول العملاء والموردين (يدعم زبون، مورد، أو زبون/مورد في نفس الوقت)
      cursor.execute("""
          CREATE TABLE IF NOT EXISTS customers_suppliers (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              phone TEXT UNIQUE NOT NULL,
              account_type TEXT DEFAULT 'زبون', 
              balance REAL DEFAULT 0.0,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
              invoice_type C-TEXT DEFAULT 'مبيعات',
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
          )
      """)
      cursor.execute("""
          CREATE TABLE IF NOT EXISTS receipts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              receipt_type TEXT, 
              party_name TEXT,
              amount REAL,
              payment_mode TEXT,
              notes TEXT,
              receipt_date TEXT
          )
      """)
      cursor.execute("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, expense_type TEXT, amount REAL, description TEXT, expense_date TEXT)")
      cursor.execute("CREATE TABLE IF NOT EXISTS treasury_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, trans_type TEXT, amount REAL, description TEXT, trans_date TEXT)")

      branch_count = cursor.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
      if branch_count == 0:
          default_branches = [("المخزن الرئيسي", "مخزن"), ("فرع الجزيرة", "فرع"), ("فرع 2", "فرع")]
          for b_name, b_type in default_branches:
              cursor.execute("INSERT OR IGNORE INTO branches (branch_name, branch_type) VALUES (?, ?)", (b_name, b_type))

      admin_chk = cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'Admin' AND is_active = 1").fetchone()[0]
      if admin_chk == 0:
          cursor.execute("INSERT OR IGNORE INTO users (username, phone, password, role, is_active) VALUES ('ابوزيد', '0910000000', 'admin', 'Admin', 1)")

      conn.commit()
      conn.close()
  except Exception as e:
      st.error(f"خطأ في تهيئة قاعدة البيانات: {e}")

initialize_database()

def get_db_connection():
  conn = sqlite3.connect("abu_zaid_new_system.db", timeout=10)
  conn.execute("PRAGMA foreign_keys = ON")
  conn.row_factory = sqlite3.Row
  return conn

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
if "page" not in st.session_state: st.session_state["page"] = "🛒 نقطة بيع"
if "success_alert_msg" not in st.session_state: st.session_state["success_alert_msg"] = ""

def set_page(page_name): 
    st.session_state["page"] = page_name
    st.rerun()

if st.session_state.get("success_alert_msg", ""):
    st.success(st.session_state["success_alert_msg"])
    st.session_state["success_alert_msg"] = ""

# --- شاشة تسجيل الدخول ---
if not st.session_state["logged_in"]:
  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.title("🔐 تسجيل الدخول")
    st.subheader("مجموعة أبو زيد التجارية")
    with st.form("login_form"):
      u_name = st.text_input("اسم المستخدم")
      u_pass = st.text_input("كلمة المرور", type="password")
      if st.form_submit_button("دخول للنظام", use_container_width=True):
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

# --- القائمة الجانبية (مطابقة للصور) ---
st.sidebar.title("🥜 مجموعة أبو زيد")
st.sidebar.write(f"المستخدم الحالي: {st.session_state['username']}")
st.sidebar.markdown("---")

for m in DEFAULT_MENUS:
    if st.sidebar.button(m, use_container_width=True, key=f"btn_{m}"):
        set_page(m)

if st.sidebar.button("خروج", use_container_width=True):
    st.session_state.clear(); st.rerun()

choice = st.session_state["page"]

# ================= 1. نقطة البيع (POS) =================
if choice == "🛒 نقطة بيع":
    st.title("🛒 نقطة البيع (شاشة الكاشير)")
    conn = get_db_connection()
    b_id = st.session_state.get("branch_id") or 1
    
    items = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
    customers = conn.execute("SELECT name FROM customers_suppliers WHERE account_type IN ('زبون', 'زبون/مورد')").fetchall()
    cust_list = ["زبون نقدي"] + [c["name"] for c in customers]
    
    col_top1, col_top2 = st.columns(2)
    with col_top1:
        sel_cust = st.selectbox("المستلم / العميل:", cust_list)
    with col_top2:
        price_type = st.radio("نوع السعر:", ["سعر البيع قطاعي", "سعر الجملة"], horizontal=True)
    
    col1, col2 = st.columns([2, 1])
    with col1:
        st.subheader("إضافة أصناف للفاتورة")
        if items:
            item_opts = {f"[{i['item_code']}] {i['item_name']} (المتاح: {i['quantity']} كجم)": i for i in items}
            sel_item_label = st.selectbox("اختر أو ابحث عن الصنف:", list(item_opts.keys()))
            chosen = item_opts[sel_item_label]
            
            unit_price = chosen['sale_price'] if price_type == "سعر البيع قطاعي" else (chosen['wholesale_price'] if chosen['wholesale_price'] > 0 else chosen['sale_price'])
            
            q = st.number_input("الكمية (كجم):", min_value=0.1, value=1.0, step=0.1)
            if st.button("إضافة الصنف للسلة", type="primary", use_container_width=True):
                st.session_state["cart"].append({
                    "id": chosen["id"], "name": chosen["item_name"],
                    "price": float(unit_price), "qty": float(q),
                    "total": float(unit_price) * float(q)
                })
                st.success("تمت الإضافة للسلة!")
                st.rerun()
        else:
            st.warning("لا توجد أصناف مضافة في هذا الفرع.")
            
    with col2:
        st.subheader("سلة المبيعات الحالية")
        if st.session_state["cart"]:
            tot = 0
            for idx, c in enumerate(st.session_state["cart"]):
                st.write(f"- **{c['name']}** | {c['qty']} كجم × {c['price']} = **{c['total']:,.2f} د.ل**")
                tot += c['total']
            st.markdown(f"### الإجمالي: {tot:,.2f} د.ل")
            
            pay_m = st.selectbox("طريقة الدفع:", ["كاش", "آجل", "مقاصة من حساب المورد"])
            
            if st.button("طباعة الفاتورة F9", type="primary", use_container_width=True):
                cur = conn.cursor()
                cur.execute("INSERT INTO invoices (branch_id, user_id, customer_name, total_amount, payment_method) VALUES (?, ?, ?, ?, ?)", 
                            (b_id, st.session_state["user_id"], sel_cust, tot, pay_m))
                
                # إذا كانت مقاصة من حساب المورد وكان الزبون مسجلاً كمورد
                if pay_m == "مقاصة من حساب المورد":
                    conn.execute("UPDATE customers_suppliers SET balance = balance - ? WHERE name = ?", (tot, sel_cust))
                
                for c in st.session_state["cart"]:
                    conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c['qty'], c['id']))
                
                conn.commit()
                st.session_state["cart"] = []
                st.session_state["success_alert_msg"] = "تم إصدار الفاتورة بنجاح!"
                conn.close()
                st.rerun()
                
            if st.button("تفريغ السلة"):
                st.session_state["cart"] = []
                st.rerun()
        else:
            st.info("السلة فارغة.")
    conn.close()

# ================= 2. إدارة الأصناف =================
elif choice == "📦 أصناف":
    st.title("📦 إدارة الأصناف والمجموعات")
    conn = get_db_connection()
    b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
    sel_b = st.selectbox("الفرع أو المخزن:", list(b_dict.keys()))
    
    with st.expander("➕ إضافة صنف جديد"):
        with st.form("add_item_form"):
            c_code = st.text_input("رقم الصنف (الباركود):")
            c_name = st.text_input("اسم الصنف:")
            c_cat = st.selectbox("المجموعة:", ["مكسرات", "مشربات وعصائر", "ساهينسا", "قهوة عربية", "شيكولاتة وشيبسي", "بقوليات", "بهارات وتوابل", "حلويات"])
            c_qty = st.number_input("الرصيد الافتتاحي (كجم):", min_value=0.0)
            c_buy = st.number_input("التكلفة / سعر الشراء:", min_value=0.0)
            c_sale = st.number_input("سعر البيع (قطاعي):", min_value=0.0)
            c_whole = st.number_input("سعر البيع (جملة):", min_value=0.0)
            
            if st.form_submit_button("حفظ الصنف الجديد") and c_code and c_name:
                try:
                    conn.execute("INSERT INTO items (branch_id, item_code, item_name, category, quantity, buy_price, sale_price, wholesale_price) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                 (b_dict[sel_b], c_code, c_name, c_cat, c_qty, c_buy, c_sale, c_whole))
                    conn.commit()
                    st.success("تم حفظ الصنف بنجاح!")
                    st.rerun()
                except: st.error("رقم الصنف أو الباركود موجود مسبقاً.")
                
    df_items = pd.read_sql("SELECT item_code AS 'الرقم', item_name AS 'اسم الصنف', category AS 'المجموعة', quantity AS 'الرصيد', buy_price AS 'التكلفة', sale_price AS 'بيع قطاعي', wholesale_price AS 'بيع جملة' FROM items WHERE branch_id = ?", conn, params=(b_dict[sel_b],))
    if not df_items.empty:
        st.dataframe(df_items, use_container_width=True)
    conn.close()

# ================= 3. أرشيف الفواتير =================
elif choice == "📄 فواتير":
    st.title("📄 أرشيف الفواتير السابقة")
    conn = get_db_connection()
    df_inv = pd.read_sql("SELECT id AS 'رقم الفاتورة', customer_name AS 'العميل', total_amount AS 'الإجمالي', payment_method AS 'طريقة الدفع', created_at AS 'التاريخ والوقت' FROM invoices ORDER BY id DESC", conn)
    if not df_inv.empty:
        st.dataframe(df_inv, use_container_width=True)
    else:
        st.info("لا توجد فواتير مسجلة.")
    conn.close()

# ================= 4. الإيصالات (مقبوضات ومدفوعات) =================
elif choice == "💵 الإيصالات (مقبوضات ومدفوعات)":
    st.title("💵 إدارة الإيصالات (سندات القبض والصرف)")
    conn = get_db_connection()
    
    with st.form("receipt_form", clear_on_submit=True):
        r_type = st.selectbox("نوع الإيصال:", ["مقبوضات (سند قبض من عميل)", "مدفوعات (سند دفع لمورد)"])
        r_party = st.text_input("اسم العميل / المورد:")
        r_amount = st.number_input("القيمة (د.ل):", min_value=0.0)
        r_mode = st.selectbox("طريقة الدفع:", ["نقدي", "سك (شيك)", "تحويل مصرفي"])
        r_notes = st.text_input("ملاحظات / البيان:")
        
        if st.form_submit_button("حفظ وطباعة الإيصال"):
            if r_amount > 0 and r_party:
                conn.execute("INSERT INTO receipts (receipt_type, party_name, amount, payment_mode, notes, receipt_date) VALUES (?, ?, ?, ?, ?, ?)",
                             (r_type, r_party, r_amount, r_mode, r_notes, datetime.now().strftime('%Y-%m-%d')))
                
                # تحديث رصيد العميل أو المورد تلقائياً
                if "مقبوضات" in r_type:
                    conn.execute("UPDATE customers_suppliers SET balance = balance - ? WHERE name = ?", (r_amount, r_party))
                else:
                    conn.execute("UPDATE customers_suppliers SET balance = balance - ? WHERE name = ?", (r_amount, r_party))
                    
                conn.commit()
                st.success("تم حفظ وتسجيل الإيصال بنجاح!")
                st.rerun()
                
    df_rec = pd.read_sql("SELECT id AS 'رقم الإيصال', receipt_type AS 'النوع', party_name AS 'الطرف', amount AS 'القيمة', payment_mode AS 'الطريقة', notes AS 'الملاحظات', receipt_date AS 'التاريخ' FROM receipts ORDER BY id DESC", conn)
    if not df_rec.empty:
        st.dataframe(df_rec, use_container_width=True)
    conn.close()

# ================= 5. عملاء وموردين (يدعم زبون ومورد في نفس الوقت) =================
elif choice == "👥 عملاء وموردين":
    st.title("👥 حسابات العملاء والموردين (كشف الديون)")
    conn = get_db_connection()
    
    with st.expander("➕ إضافة عميل أو مورد جديد (أو مشترك زبون/مورد)"):
        with st.form("add_cs_form", clear_on_submit=True):
            cs_name = st.text_input("اسم العميل أو المورد:")
            cs_phone = st.text_input("رقم الهاتف:")
            cs_type = st.selectbox("صفة الحساب:", ["زبون", "مورد", "زبون/مورد (مشترك)"])
            cs_balance = st.number_input("الرصيد الافتتاحي (له/عليه):", value=0.0)
            
            if st.form_submit_button("حفظ الحساب") and cs_name and cs_phone:
                try:
                    conn.execute("INSERT INTO customers_suppliers (name, phone, account_type, balance) VALUES (?, ?, ?, ?)",
                                 (cs_name, cs_phone, cs_type, cs_balance))
                    conn.commit()
                    st.success("تم حفظ الحساب بنجاح!")
                    st.rerun()
                except: st.error("رقم الهاتف مسجل مسبقاً.")
                
    df_cs = pd.read_sql("SELECT id AS 'رقم', name AS 'الاسم', phone AS 'الهاتف', account_type AS 'التصنيف', balance AS 'الرصيد الحالي (د.ل)' FROM customers_suppliers", conn)
    if not df_cs.empty:
        st.dataframe(df_cs, use_container_width=True)
        total_d = df_cs['الرصيد الحالي (د.ل)'].sum()
        st.metric("إجمالي الأرصدة والديون", f"{total_d:,.2f} د.ل")
    conn.close()

# ================= 6. المصروفات والإيجارات =================
elif choice == "💰 المصروفات":
    st.title("💰 إدارة المصروفات (الإيجارات وغيرها)")
    conn = get_db_connection()
    
    with st.form("exp_form", clear_on_submit=True):
        e_type = st.selectbox("نوع المصروف:", ["الإيجار", "صيانة", "كهرباء ومياه", "نثريات وطوارئ"])
        e_amount = st.number_input("المبلغ (د.ل):", min_value=0.0)
        e_desc = st.text_input("البيان / المستلم (مثل: اسم صاحب الشقة للإيجار):")
        
        if st.form_submit_button("حفظ المصروف"):
            if e_amount > 0 and e_desc:
                conn.execute("INSERT INTO expenses (expense_type, amount, description, expense_date) VALUES (?, ?, ?, ?)",
                             (e_type, e_amount, e_desc, datetime.now().strftime('%Y-%m-%d')))
                conn.commit()
                st.success("تم حفظ المصروف بنجاح!")
                st.rerun()
                
    df_exp = pd.read_sql("SELECT id AS 'مسلسل', expense_type AS 'نوع المصروف', amount AS 'المبلغ', description AS 'البيان', expense_date AS 'التاريخ' FROM expenses ORDER BY id DESC", conn)
    if not df_exp.empty:
        st.dataframe(df_exp, use_container_width=True)
    conn.close()

# ================= 7. الخزينة =================
elif choice == "💼 الخزينة":
    st.title("💼 حركة الخزينة والنقدية")
    conn = get_db_connection()
    
    sales_cash = conn.execute("SELECT SUM(total_amount) FROM invoices WHERE payment_method = 'كاش'").fetchone()[0] or 0.0
    receipts_in = conn.execute("SELECT SUM(amount) FROM receipts WHERE receipt_type LIKE '%مقبوضات%'").fetchone()[0] or 0.0
    receipts_out = conn.execute("SELECT SUM(amount) FROM receipts WHERE receipt_type LIKE '%مدفوعات%'").fetchone()[0] or 0.0
    expenses_tot = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0.0
    
    net_treasury = (sales_cash + receipts_in) - (receipts_out + expenses_tot)
    
    col1, col2, col3 = st.columns(3)
    with col1: st.metric("إيرادات المبيعات النقدية والمقبوضات", f"{(sales_cash + receipts_in):,.2f} د.ل")
    with col2: st.metric("المصروفات والمدفوعات الخارجة", f"{(receipts_out + expenses_tot):,.2f} د.ل")
    with col3: st.metric("💰 صافي الخزينة الحالية", f"{net_treasury:,.2f} د.ل")
    
    conn.close()

# ================= 8. التقارير =================
elif choice == "📊 التقارير":
    st.title("📊 التقارير العامة والأرباح")
    conn = get_db_connection()
    sales = conn.execute("SELECT SUM(total_amount) FROM invoices").fetchone()[0] or 0.0
    exps = conn.execute("SELECT SUM(amount) FROM expenses").fetchone()[0] or 0.0
    st.metric("إجمالي المبيعات", f"{sales:,.2f} د.ل")
    st.metric("إجمالي المصروفات", f"{exps:,.2f} د.ل")
    st.metric("صافي الربح", f"{(sales - exps):,.2f} د.ل")
    conn.close()

# ================= 9. الجرد =================
elif choice == "⚙️ الجرد":
    st.title("⚙️ جرد المخزن")
    conn = get_db_connection()
    df_inv = pd.read_sql("SELECT item_code AS 'الكود', item_name AS 'اسم الصنف', quantity AS 'الرصيد الفعلي (كجم)' FROM items", conn)
    if not df_inv.empty:
        st.dataframe(df_inv, use_container_width=True)
        st.download_button("تصدير جرد المخزن لـ Excel", data=to_excel(df_inv), file_name="inventory_stock.xlsx")
    conn.close()

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
