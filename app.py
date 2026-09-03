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
if "user_id" not in st.session_state:
  st.session_state["user_id"] = None
if "selected_branch_id" not in st.session_state:
  st.session_state["selected_branch_id"] = None
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
            st.session_state["user_id"] = user["id"]
            st.session_state["assigned_branch_id"] = user["branch_id"]
            st.rerun()
          else:
            st.error("خطأ في اسم المستخدم أو كلمة المرور!")
  st.stop()

# --- شاشة التحقق من الفرع برسالة ترحيبية أو "هنى روحك" ---
if not st.session_state["branch_verified"]:
  st.title(
      f"🔥 أهلاً بك يا قهوجي/بطل العمل، {st.session_state['username']}! استعد"
      " ليوم عمل متميز ومشوق."
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
      # إذا كان الأدمين مستثنى أو الفرع مطابق لتعيين المستخدم
      if (
          st.session_state["role"] == "Admin"
          .get("assigned_branch_id")
          == chosen_id
          or st.session_state.get("assigned_branch_id") is None
          or st.session_state["role"] == "Admin"
      ):
        st.session_state["branch_verified"] = True
        st.session_state["selected_branch_id"] = chosen_id
        st.success("تم التحقق بنجاح، جارٍ فتح النظام...")
        st.rerun()
      else:
        st.error("❌ ( هنى روحك )! هذا ليس فرعك المخصص، حاول مجدداً.")
  else:
    st.warning(
        "لا توجد فروع مسجلة بعد. يطلب من الأدمن إضافتها أولاً من لوحة التحكم."
    )
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
      "📊 تقارير المخازن الشاملة",
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
  st.markdown(
      "أهلاً بك في النظام السحابي لإدارة الفروع والمخامص والمبيعات."
  )

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
  st.header("🏢 إدارة الشركات والفروع (صلاحيات الأدمين)")

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
      sel_c = st.selectbox("اختر الشركة التابع لها الفرع", list(comps_dict.keys()))
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
    else:
      st.info("أضف شركة أولاً ليظهر خيار إتاحة الفروع.")

  st.markdown("---")
  st.subheader("📋 شاشة عرض الشركات والفروع المسجلة (تعديل وحذف)")
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

  st.write("### الشركات المتاحة:")
  if not df_comps.empty:
    st.dataframe(df_comps, use_container_width=True)
    del_c_id = st.selectbox(
        "اختر رقم معرف الشركة للحذف", df_comps["id"].tolist(), key="del_c"
    )
    if st.button("🗑️ حذف الشركة المحددة"):
      conn = get_db_connection()
      conn.execute("DELETE FROM companies WHERE id = ?", (del_c_id,))
      conn.commit()
      conn.close()
      st.success("تم الحذف بنجاح!")
      st.rerun()
  else:
    st.info("لا توجد شركات مسجلة.")

  st.write("### الفروع المتاحة:")
  if not df_branches.empty:
    st.dataframe(df_branches, use_container_width=True)
    del_b_id = st.selectbox(
        "اختر رقم معرف الفرع للحذف", df_branches["id"].tolist(), key="del_b"
    )
    if st.button("🗑️ حذف الفرع المحدد"):
      conn = get_db_connection()
      conn.execute("DELETE FROM branches WHERE id = ?", (del_b_id,))
      conn.commit()
      conn.close()
      st.success("تم حذف الفرع بنجاح!")
      st.rerun()
  else:
    st.info("لا توجد فروع مسجلة.")

elif choice == "👥 إدارة المستخدمين":
  st.header("👥 إدارة المستخدمين والصلاحيات والربط بالفروع")
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
    assigned_b = st.selectbox("الفرع المخصص للمستخدم", list(b_dict.keys()))

    if st.form_submit_button("حفظ المستخدم الجديد"):
      if u and p:
        b_id = b_dict[assigned_b] if assigned_b else None
        conn = get_db_connection()
        try:
          conn.execute(
              "INSERT INTO users (username, password, role, branch_id) VALUES"
              " (?, ?, ?, ?)",
              (u, p, r, b_id),
          )
          conn.commit()
          st.success("تم إضافة المستخدم بنجاح!")
        except Exception as e:
          st.error(f"خطأ: {e}")
        finally:
          conn.close()

  st.markdown("---")
  st.subheader("📋 قائمة المستخدمين المسجلين (إدارة وتعديل)")
  conn = get_db_connection()
  df_users = pd.read_sql(
      """
        SELECT users.id, users.username AS المستخدم, users.role AS الصلاحية, branches.branch_name AS الفرع المخصص
        FROM users LEFT JOIN branches ON users.branch_id = branches.id
    """,
      conn,
  )
  conn.close()
  if not df_users.empty:
    st.dataframe(df_users, use_container_width=True)
    del_u_id = st.selectbox(
        "اختر رقم معرف المستخدم للحذف", df_users["id"].tolist()
    )
    if st.button("🗑️ حذف المستخدم المحدد"):
      conn = get_db_connection()
      conn.execute("DELETE FROM users WHERE id = ?", (del_u_id,))
      conn.commit()
      conn.close()
      st.success("تم الحذف بنجاح!")
      st.rerun()

elif choice == "📁 استيراد وتوزيع الأصناف":
  st.header("📁 استيراد الأصناف عبر الإكسيل")
  conn = get_db_connection()
  comps = conn.execute("SELECT id, company_name FROM companies").fetchall()
  conn.close()
  comps_dict = {c["company_name"]: c["id"] for c in comps}
  if comps_dict:
    sel_comp = st.selectbox("اختر الشركة لتوزيع الأصناف عليها", list(comps_dict.keys()))
    up_file = st.file_uploader("ملف الإكسيل", type=["xlsx", "xls"])
    if up_file and st.button("📥 بدء استيراد وتوزيع الأصناف"):
      df = pd.read_excel(up_file)
      conn = get_db_connection()
      cur = conn.cursor()
      for _, row in df.iterrows():
        code = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
        name = str(row.iloc[1]) if pd.notna(row.iloc[1]) else ""
        price = float(row.iloc[2]) if pd.notna(row.iloc[2]) else 0.0
        if name:
          cur.execute(
              "INSERT INTO items (company_id, item_code, item_name, sale_price)"
              " VALUES (?, ?, ?, ?)",
              (comps_dict[sel_comp], code, name, price),
          )
      conn.commit()
      conn.close()
      st.success("تم استيراد الأصناف بنجاح!")
  else:
    st.warning("أضف شركة أولاً قبل استيراد الأصناف.")

elif choice == "📊 تقارير المخازن الشاملة":
  st.header("📊 تقارير المخازن والأصناف")
  conn = get_db_connection()
  df = pd.read_sql(
      """
        SELECT items.id AS المعرف, companies.company_name AS الشركة, branches.branch_name AS الفرع, 
               items.item_code AS الكود, items.item_name AS الصنف, items.sale_price AS السعر
        FROM items 
        JOIN companies ON items.company_id = companies.id 
        LEFT JOIN branches ON items.branch_id = branches.id
    """,
      conn,
  )
  conn.close()
  if not df.empty:
    st.dataframe(df, use_container_width=True)
    del_item_id = st.selectbox(
        "اختر رقم معرف الصنف للحذف أو التعديل", df["المعرف"].tolist()
    )
    if st.button("🗑️ حذف الصنف المحدد"):
      conn = get_db_connection()
      conn.execute("DELETE FROM items WHERE id = ?", (del_item_id,))
      conn.commit()
      conn.close()
      st.success("تم حذف الصنف بنجاح!")
      st.rerun()
  else:
    st.info("لا توجد أصناف مسجلة في المخزن.")

elif choice == "🥜 التحميص والخلط والتصنيع":
  st.header("🥜 إدارة عمليات التحميص، الفاقد، وخلط المكسرات")
  tab1, tab2 = st.tabs(
      ["🔥 قسم التحميص وحساب الفاقد", "🥜 خلائط المكسرات المشكلة"]
  )

  with tab1:
    st.subheader("تسجيل عملية تحميص")
    conn = get_db_connection()
    branches = conn.execute("""
            SELECT branches.id, branches.branch_name, companies.company_name 
            FROM branches JOIN companies ON branches.company_id = companies.id
        """).fetchall()
    conn.close()
    branch_dict = {
        f"{b['company_name']} ➔ {b['branch_name']}": b["id"] for b in branches
    }
    if branch_dict:
      sel_b_roast = st.selectbox("اختر الفرع", list(branch_dict.keys()))
      b_id = branch_dict[sel_b_roast]
      conn = get_db_connection()
      items = conn.execute(
          "SELECT item_name, sale_price FROM items", ()
      ).fetchall()
      conn.close()
      if items:
        items_dict = {
            f"{i['item_name']} ({i['sale_price']} د.ل)": i for i in items
        }
        sel_item = st.selectbox("اختر الصنف الخام", list(items_dict.keys()))
        in_qty = st.number_input("الوزن الخام المرسل (كيلو)", value=10.0)
        out_qty = st.number_input("الوزن الناتج بعد التحميص (كيلو)", value=8.5)
        new_roast_name = st.text_input("اسم الصنف الجديد بعد التحميص")

        if st.button("⚙️ تنفيذ التحميص وتحديث التكلفة"):
          if new_roast_name and sel_item:
            old_price = items_dict[sel_item]["sale_price"]
            new_unit_price = (in_qty * old_price) / out_qty
            conn = get_db_connection()
            conn.execute(
                "INSERT INTO items (branch_id, item_name, sale_price) VALUES"
                " (?, ?, ?)",
                (b_id, new_roast_name, round(new_unit_price, 2)),
            )
            conn.commit()
            conn.close()
            st.success(
                f"تم التحميص بنجاح! سعر الكيلو الجديد: {new_unit_price:.2f} د.ل"
            )
      else:
        st.info("لا توجد أصناف مسجلة للاختيار منها.")
    else:
      st.warning("أضف فروعاً أولاً لتتمكن من إجراء التحميص.")

  with tab2:
    st.subheader("تكوين المكسرات المشكلة (Mix Nuts)")
    mix_name = st.text_input("اسم صنف المكسرات الجديد")
    total_cost = st.number_input("إجمالي التكلفة (د.ل)", value=50.0)
    profit_margin = st.number_input("نسبة هامش الربح (%)", value=20.0)

    if st.button("✨ اعتماد الخليط كصنف جديد للبيع"):
      if mix_name:
        final_price = total_cost * (1 + (profit_margin / 100))
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO items (item_name, sale_price) VALUES (?, ?)",
            (mix_name, round(final_price, 2)),
        )
        conn.commit()
        conn.close()
        st.success(
            f"تم اعتماد '{mix_name}' بسعر بيع: {final_price:.2f} د.ل بنجاح!"
        )

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
    st.info("لا توجد أصناف متاحة للبيع حالياً.")

st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
