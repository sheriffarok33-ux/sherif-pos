import os
import sqlite3
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="مجموعة أبو زيد التجارية - النظام السحابي المتكامل",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    .main { background-color: #f8fafc; }
    .card {
        padding: 20px;
        border-radius: 12px;
        color: white;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

if not os.path.exists("company_logos"):
  os.makedirs("company_logos")


def initialize_database():
  conn = sqlite3.connect("abu_zaid_system.db", timeout=10)
  cursor = conn.cursor()

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT UNIQUE NOT NULL,
            company_title TEXT NOT NULL,
            logo_path TEXT
        )
    """)

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS branches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            branch_name TEXT NOT NULL,
            FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
        )
    """)

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT CHECK(role IN ('Admin', 'General_Supervisor', 'Branch_Supervisor', 'Cashier')) NOT NULL,
            branch_id INTEGER,
            FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE SET NULL
        )
    """)

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER,
            branch_id INTEGER DEFAULT NULL,
            item_code TEXT,
            item_name TEXT NOT NULL,
            quantity REAL DEFAULT 0.0,
            buy_price REAL DEFAULT 0.0,
            sale_price REAL NOT NULL,
            FOREIGN KEY (company_id) REFERENCES companies(id),
            FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
        )
    """)

  conn.commit()
  conn.close()


initialize_database()


def get_db_connection():
  conn = sqlite3.connect("abu_zaid_system.db", timeout=10)
  conn.row_factory = sqlite3.Row
  return conn


if "logged_in" not in st.session_state:
  st.session_state["logged_in"] = False
if "username" not in st.session_state:
  st.session_state["username"] = ""
if "role" not in st.session_state:
  st.session_state["role"] = ""
if "branch_verified" not in st.session_state:
  st.session_state["branch_verified"] = False
if "cart" not in st.session_state:
  st.session_state["cart"] = []

# --- شاشة تسجيل الدخول ---
if not st.session_state["logged_in"]:
  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.title("🔐 تسجيل الدخول")
    st.subheader("مجموعة أبو زيد التجارية")
    with st.form("login_form"):
      u_name = st.text_input("اسم المستخدم")
      u_pass = st.text_input("كلمة المرور", type="password")
      submit = st.form_submit_button(
          "🚀 دخول للنظام", use_container_width=True
      )

      if submit:
        if u_name == "admin" and u_pass == "admin":
          st.session_state["logged_in"] = True
          st.session_state["username"] = "admin"
          st.session_state["role"] = "Admin"
          st.session_state["branch_verified"] = True
          st.rerun()
        else:
          conn = get_db_connection()
          user = conn.execute(
              "SELECT * FROM users WHERE username = ? AND password = ?",
              (u_name, u_pass),
          ).fetchone()
          conn.close()
          if user:
            st.session_state["logged_in"] = True
            st.session_state["username"] = user["username"]
            st.session_state["role"] = user["role"]
            st.session_state["assigned_branch_id"] = user["branch_id"]
            st.rerun()
          else:
            st.error("خطأ في اسم المستخدم أو كلمة المرور!")
  st.stop()

# --- شاشة التحقق من الفرع برسالة ترحيبية أو "هنى روحك" ---
if not st.session_state["branch_verified"]:
  st.title(
      f"🔥 أهلاً بك يا بطل العمل، {st.session_state['username']}! استعد ليوم عمل"
      " متميز ومشوق."
  )
  st.info("الرجاء اختيار الفرع التابع لك لتأكيد الدخول:")

  conn = get_db_connection()
  branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
  conn.close()

  branch_options = {b["branch_name"]: b["id"] for b in branches}
  if branch_options:
    chosen_branch = st.selectbox("اختر فرعك المخصص", list(branch_options.keys()))
    if st.button("تأكيد الفرع والدخول"):
      chosen_id = branch_options[chosen_branch]
      if (
          st.session_state["role"] == "Admin"
          or st.session_state.get("assigned_branch_id") == chosen_id
      ):
        st.session_state["branch_verified"] = True
        st.session_state["selected_branch_id"] = chosen_id
        st.success("تم التحقق بنجاح، جارٍ فتح النظام...")
        st.rerun()
      else:
        st.error("❌ ( هنى روحك )! هذا ليس فرعك المخصص، حاول مجدداً.")
  else:
    st.warning("لا توجد فروع مسجلة بعد. يطلب من الأدمن إضافتها أولاً.")
    if st.session_state["role"] == "Admin":
      if st.button("الدخول كأدمن لتسجيل الفروع"):
        st.session_state["branch_verified"] = True
        st.rerun()
  st.stop()

# --- القائمة الجانبية العصرية ---
st.sidebar.markdown(f"### 👤 المستخدم: {st.session_state['username']}")
st.sidebar.markdown(f"**الصلاحية:** `{st.session_state['role']}`")
st.sidebar.markdown("---")

menu = ["🏠 الرئيسية واللوحة", "🛒 نقطة البيع (POS)"]

if st.session_state["role"] == "Admin":
  menu.extend([
      "🏢 إدارة الشركات والفروع",
      "👥 إدارة المستخدمين",
      "📁 استيراد وتوزيع الأصناف",
      "📊 تقارير المخازن وتحويل الكميات",
      "🥜 التحميص والخلط والتصنيع",
  ])

menu.append("🚪 تسجيل الخروج")
choice = st.sidebar.selectbox("📂 القائمة الرئيسية", menu)

if choice == "🚪 تسجيل الخروج":
  st.session_state["logged_in"] = False
  st.session_state["branch_verified"] = False
  st.rerun()

elif choice == "🏠 الرئيسية واللوحة":
  st.title("🏢 مجموعة أبو زيد التجارية - لوحة التحكم السحابية")
  c1, c2, c3 = st.columns(3)
  with c1:
    st.markdown(
        """<div class="card" style="background-color: #2563eb;"><h3>🏢 الشركات"
        " والفروع</h3><p>إدارة كاملة وعرض البيانات</p></div>""",
        unsafe_allow_html=True,
    )
  with c2:
    st.markdown(
        """<div class="card" style="background-color: #059669;"><h3>📊"
        " المخازن</h3><p>تتبع الأصناف والأسعار</p></div>""",
        unsafe_allow_html=True,
    )
  with c3:
    st.markdown(
        """<div class="card" style="background-color: #ea580c;"><h3>🥜 التحميص"
        " والخلط</h3><p>حساب الفاقد والمكسرات</p></div>""",
        unsafe_allow_html=True,
    )

elif choice == "🏢 إدارة الشركات والفروع":
  st.header("🏢 إدارة الشركات والفروع")
  col1, col2 = st.columns(2)
  with col1:
    st.subheader("إضافة شركة جديدة")
    c_name = st.text_input("اسم الشركة البرمجي")
    c_title = st.text_input("الاسم الرسمي للفاتورة")
    if st.button("💾 حفظ الشركة"):
      if c_name and c_title:
        conn = get_db_connection()
        try:
          conn.execute(
              "INSERT INTO companies (company_name, company_title) VALUES"
              " (?, ?)",
              (c_name, c_title),
          )
          conn.commit()
          st.success("تم حفظ الشركة بنجاح!")
        except Exception as e:
          st.error(f"خطأ: {e}")
        finally:
          conn.close()

  with col2:
    st.subheader("إضافة فرع جديد")
    conn = get_db_connection()
    comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
    conn.close()
    comps_dict = {c["company_name"]: c["id"] for c in comps}
    if comps_dict:
      sel_c = st.selectbox("اختر الشركة للفرع", list(comps_dict.keys()))
      b_name = st.text_input("اسم الفرع / المخزن")
      if st.button("💾 حفظ الفرع"):
        if b_name:
          conn = get_db_connection()
          conn.execute(
              "INSERT INTO branches (company_id, branch_name) VALUES (?, ?)",
              (comps_dict[sel_c], b_name),
          )
          conn.commit()
          conn.close()
          st.success("تم حفظ الفرع بنجاح!")

  st.markdown("---")
  st.subheader("📋 الشركات والفروع المسجلة")
  conn = get_db_connection()
  df_comps = pd.read_sql("SELECT * FROM companies", conn)
  df_branches = pd.read_sql(
      """
        SELECT branches.id, companies.company_name AS الشركة, branches.branch_name AS الفرع
        FROM branches JOIN companies ON branches.company_id = companies.id
    """,
      conn,
  )
  conn.close()

  if not df_comps.empty:
    st.dataframe(df_comps, use_container_width=True)
    del_c_id = st.selectbox(
        "معرف الشركة للحذف", df_comps["id"].tolist(), key="del_c"
    )
    if st.button("🗑️ حذف الشركة"):
      conn = get_db_connection()
      conn.execute("DELETE FROM companies WHERE id = ?", (del_c_id,))
      conn.commit()
      conn.close()
      st.success("تم الحذف!")
      st.rerun()

  if not df_branches.empty:
    st.dataframe(df_branches, use_container_width=True)
    del_b_id = st.selectbox(
        "معرف الفرع للحذف", df_branches["id"].tolist(), key="del_b"
    )
    if st.button("🗑️ حذف الفرع"):
      conn = get_db_connection()
      conn.execute("DELETE FROM branches WHERE id = ?", (del_b_id,))
      conn.commit()
      conn.close()
      st.success("تم الحذف!")
      st.rerun()

elif choice == "👥 إدارة المستخدمين":
  st.header("👥 إدارة المستخدمين والصلاحيات")
  with st.form("user_form"):
    u = st.text_input("اسم المستخدم")
    p = st.text_input("كلمة المرور", type="password")
    r = st.selectbox(
        "الصلاحية", ["Cashier", "Branch_Supervisor", "General_Supervisor", "Admin"]
    )
    conn = get_db_connection()
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    conn.close()
    b_dict = {b["branch_name"]: b["id"] for b in branches}
    assigned_b = st.selectbox("الفرع المخصص", list(b_dict.keys()))

    if st.form_submit_button("حفظ المستخدم"):
      if u and p:
        b_id = b_dict[assigned_b] if assigned_b else None
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO users (username, password, role, branch_id) VALUES"
            " (?, ?, ?, ?)",
            (u, p, r, b_id),
        )
        conn.commit()
        conn.close()
        st.success("تم إضافة المستخدم!")

elif choice == "📁 استيراد وتوزيع الأصناف":
  st.header("📁 استيراد الأصناف عبر الإكسيل")
  st.info(
      "📌 **فورمات ملف الإكسيل المطلوب (بدون عناوين أو مع تخطي السطر"
      " الأول):**\n"
      "العمود 1: `الكود` | العمود 2: `الصنف` | العمود 3: `الكمية` | العمود 4:"
      " `سعر الشراء` | العمود 5: `سعر البيع`"
  )

  demo_df = pd.DataFrame({
      "الكود": ["A001", "A002"],
      "الصنف": ["لوز خام", "بندق منقى"],
      "الكمية": [100, 50],
      "سعر الشراء": [15.0, 25.0],
      "سعر البيع": [20.0, 35.0],
  })
  st.write("مثال توضيحي لشكل الفورمات المقبول:")
  st.dataframe(demo_df, use_container_width=True)

  conn = get_db_connection()
  comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
  conn.close()
  comps_dict = {c["company_name"]: c["id"] for c in comps}

  if comps_dict:
    sel_comp = st.selectbox(
        "اختر الشركة لتأكيد استيراد الأصناف إليها", list(comps_dict.keys())
    )
    up_file = st.file_uploader(
        "اختر ملف الإكسيل (.xlsx)", type=["xlsx", "xls"]
    )
    if up_file and st.button("📥 تنفيذ استيراد الأصناف"):
      try:
        # قراءة الملف بدون اعتبار السطر الأول كـ Header لمنع أخطاء التسمية
        df = pd.read_excel(up_file, header=None)
        conn = get_db_connection()
        cur = conn.cursor()
        success_count = 0

        for idx, row in df.iterrows():
          # تخطي السطر الأول إذا كان يحتوي على عناوين نصية
          if idx == 0 and any(
              str(val).strip() in ["الكود", "الصنف", "الكمية", "code", "item"]
              for val in row.values
          ):
            continue

          try:
            code = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
            name = str(row.iloc[1]) if pd.notna(row.iloc[1]) else ""
            qty = float(row.iloc[2]) if pd.notna(row.iloc[2]) else 0.0
            b_price = float(row.iloc[3]) if pd.notna(row.iloc[3]) else 0.0
            s_price = float(row.iloc[4]) if pd.notna(row.iloc[4]) else 0.0

            if name and name != "nan":
              cur.execute(
                  """INSERT INTO items (company_id, item_code, item_name,"
                  " quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)""",
                  (comps_dict[sel_comp], code, name, qty, b_price, s_price),
              )
              success_count += 1
          except Exception:
            continue  # تخطي أي سطر تالف أو غير مطابق لتجنب توقف البرنامج

        conn.commit()
        conn.close()
        st.success(
            f"تم استيراد وتوزيع عدد ({success_count}) صنف بنجاح للشركة المحددة!"
        )
      except Exception as e:
        st.error(f"حدث خطأ أثناء قراءة الملف: {e}")
  else:
    st.warning("أضف شركة أولاً ليتم توجيه الأصناف إليها.")

elif choice == "📊 تقارير المخازن وتحويل الكميات":
  st.header("📊 تقارير المخازن وتحويل الكميات للفروع")

  conn = get_db_connection()
  items_df = pd.read_sql(
      """
        SELECT items.id, companies.company_name AS الشركة, branches.branch_name AS الفرع, 
               items.item_code AS الكود, items.item_name AS الصنف, items.quantity AS الكمية, items.sale_price AS السعر
        FROM items 
        JOIN companies ON items.company_id = companies.id 
        LEFT JOIN branches ON items.branch_id = branches.id
    """,
      conn,
  )
  branches_list = conn.execute(
      "SELECT id, branch_name FROM branches"
  ).fetchall()
  conn.close()

  if not items_df.empty:
    st.dataframe(items_df, use_container_width=True)

    st.markdown("---")
    st.subheader("🔄 تحويل كمية من صنف لفرع آخر")
    item_ids = items_df["id"].tolist()
    sel_item_id = st.selectbox(
        "اختر الصنف المراد تحويل جزء من كميته",
        item_ids,
        format_func=lambda x: (
            f"{items_df[items_df['id'] == x]['الصنف'].values[0]} (الكمية"
            f" المتوفرة: {items_df[items_df['id'] == x]['الكمية'].values[0]})"
        ),
    )

    b_dict = {b["branch_name"]: b["id"] for b in branches_list}
    if b_dict:
      target_branch = st.selectbox("الفرع المحول إليه", list(b_dict.keys()))
      transfer_qty = st.number_input(
          "الكمية المراد تحويلها", min_value=0.1, value=1.0
      )

      if st.button("🚀 تنفيذ التحويل للفرع"):
        conn = get_db_connection()
        curr_item = conn.execute(
            "SELECT quantity, item_code, item_name, company_id, buy_price,"
            " sale_price FROM items WHERE id = ?",
            (sel_item_id,),
        ).fetchone()
        if curr_item and curr_item["quantity"] >= transfer_qty:
          conn.execute(
              "UPDATE items SET quantity = quantity - ? WHERE id = ?",
              (transfer_qty, sel_item_id),
          )
          conn.execute(
              """INSERT INTO items (company_id, branch_id, item_code, item_name,"
              " quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (
                  curr_item["company_id"],
                  b_dict[target_branch],
                  curr_item["item_code"],
                  curr_item["item_name"],
                  transfer_qty,
                  curr_item["buy_price"],
                  curr_item["sale_price"],
              ),
          )
          conn.commit()
          conn.close()
          st.success("تم تحويل الكمية بنجاح إلى الفرع المستهدف!")
          st.rerun()
        else:
          conn.close()
          st.error("الكمية المتوفرة لا تكفي لإتمام التحويل!")
    else:
      st.warning("لا توجد فروع متاحة للتحويل إليها.")
  else:
    st.info("لا توجد أصناف في المخزن.")

elif choice == "🥜 التحميص والخلط والتصنيع":
  st.header("🥜 إدارة عمليات التحميص والخلط")

elif choice == "🛒 نقطة البيع (POS)":
  st.header("🛒 شاشة الكاشير ونقطة البيع")
  conn = get_db_connection()
  branch_items = conn.execute(
      "SELECT item_name, sale_price FROM items", ()
  ).fetchall()
  conn.close()

  if branch_items:
    items_options = {
        f"{i['item_name']} - {i['sale_price']} د.ل": i for i in branch_items
    }
    col1, col2 = st.columns([2, 1])
    with col1:
      chosen_item = st.selectbox("الأصناف المتاحة للبيع", list(items_options.keys()))
      qty = st.number_input("الكمية", min_value=1, value=1)
      if st.button("➕ إضافة للسلة"):
        item_data = items_options[chosen_item]
        st.session_state["cart"].append({
            "name": item_data["item_name"],
            "price": item_data["sale_price"],
            "qty": qty,
            "total": item_data["sale_price"] * qty,
        })
        st.success("تمت الإضافة للسلة")

    with col2:
      st.subheader("🛒 سلة الفاتورة الحالية")
      if st.session_state["cart"]:
        df_cart = pd.DataFrame(st.session_state["cart"])
        st.dataframe(df_cart[["name", "price", "qty", "total"]])
        grand_total = sum([x["total"] for x in st.session_state["cart"]])
        st.metric("الإجمالي النهائي", f"{grand_total:.2f} د.ل")
        if st.button("🖨️ إتمام البيع"):
          st.success("تم إتمام الفاتورة بنجاح!")
          st.session_state["cart"] = []
          st.rerun()
      else:
        st.info("السلة فارغة")
  else:
    st.info("لا توجد أصناف متاحة للبيع.")

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
