import os
import sqlite3
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="مجموعة أبو زيد التجارية - النظام السحابي", layout="wide"
)

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
            role TEXT CHECK(role IN ('Admin', 'General_Supervisor', 'Branch_Supervisor', 'Cashier')) NOT NULL
        )
    """)

  cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_branches (
            user_id INTEGER,
            branch_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, branch_id)
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


# تهيئة الجلسة لمنع الشاشة البيضاء
if "logged_in" not in st.session_state:
  st.session_state["logged_in"] = False
if "username" not in st.session_state:
  st.session_state["username"] = ""
if "role" not in st.session_state:
  st.session_state["role"] = ""
if "user_id" not in st.session_state:
  st.session_state["user_id"] = None

# --- شاشة تسجيل الدخول ---
if not st.session_state["logged_in"]:
  st.title("🔐 تسجيل الدخول - مجموعة أبو زيد التجارية")

  with st.form("login_form"):
    u_name = st.text_input("اسم المستخدم")
    u_pass = st.text_input("كلمة المرور", type="password")
    submit = st.form_submit_button("دخول")

    if submit:
      if u_name == "admin" and u_pass == "admin":
        st.session_state["logged_in"] = True
        st.session_state["username"] = "admin"
        st.session_state["role"] = "Admin"
        st.session_state["user_id"] = None
        st.rerun()
      else:
        try:
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
            st.rerun()
          else:
            st.error("اسم المستخدم أو كلمة المرور غير صحيحة!")
        except Exception as e:
          st.error(f"خطأ في الاتصال بقاعدة البيانات: {e}")

  st.stop()  # إيقاف التنفيذ هنا حتى يتم تسجيل الدخول بنجاح

# --- لوحة التحكم بعد تسجيل الدخول ---
st.sidebar.title(
    f"مرحباً: {st.session_state['username']} ({st.session_state['role']})"
)
menu = ["الرئيسية"]

if st.session_state["role"] == "Admin":
  menu.extend([
      "إضافة شركات وفروع",
      "إدارة المستخدمين",
      "استيراد وتوزيع الأصناف",
      "تقارير المخازن",
  ])

menu.append("تسجيل الخروج")
choice = st.sidebar.radio("القائمة الرئيسية", menu)

if choice == "تسجيل الخروج":
  st.session_state["logged_in"] = False
  st.session_state["username"] = ""
  st.session_state["role"] = ""
  st.session_state["user_id"] = None
  st.rerun()

elif choice == "الرئيسية":
  st.title("🏢 مجموعة أبو زيد التجارية - النظام السحابي")
  st.success("تم تسجيل الدخول بنجاح والنظام يعمل بكفاءة تامة.")

elif choice == "إضافة شركات وفروع":
  st.header("🏢 إدارة الشركات والفروع")
  c_name = st.text_input("اسم الشركة البرمجي")
  c_title = st.text_input("الاسم الرسمي للفاتورة")
  if st.button("حفظ الشركة"):
    if c_name and c_title:
      conn = get_db_connection()
      conn.execute(
          "INSERT INTO companies (company_name, company_title) VALUES (?, ?)",
          (c_name, c_title),
      )
      conn.commit()
      conn.close()
      st.success("تم حفظ الشركة بنجاح!")
    else:
      st.warning("أدخل البيانات كاملة.")

elif choice == "إدارة المستخدمين":
  st.header("👥 إدارة المستخدمين والصلاحيات")
  with st.form("user_form"):
    new_user = st.text_input("اسم المستخدم الجديد")
    new_pass = st.text_input("كلمة المرور", type="password")
    new_role = st.selectbox(
        "الصلاحية", ["Cashier", "Branch_Supervisor", "Admin"]
    )
    if st.form_submit_button("حفظ المستخدم"):
      if new_user and new_pass:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (new_user, new_pass, new_role),
        )
        conn.commit()
        conn.close()
        st.success("تم إضافة المستخدم بنجاح!")
      else:
        st.warning("أدخل بيانات المستخدم كاملة.")

elif choice == "استيراد وتوزيع الأصناف":
  st.header("📁 استيراد الأصناف عبر الإكسيل")
  uploaded_file = st.file_uploader("اختر ملف إكسيل", type=["xlsx", "xls"])
  if uploaded_file:
    df = pd.read_excel(uploaded_file)
    st.dataframe(df)

elif choice == "تقارير المخازن":
  st.header("📊 تقارير المخازن")
  conn = get_db_connection()
  df = pd.read_sql("SELECT * FROM items", conn)
  conn.close()
  st.dataframe(df, use_container_width=True)

# التوقيع الرسمي
st.sidebar.markdown("---")
st.sidebar.text("ENG: SHERIF M. FAROK")
