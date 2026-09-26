import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
import sqlite3

# --- 1. إعدادات الصفحة الأساسية ---
st.set_page_config(
    page_title="مجموعة أبو زيد - نظام المحامص والمخازن الذكي",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_NAME = 'database.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# --- 2. تهيئة الجداول تلقائياً لضمان عدم حدوث أي خطأ ---
def create_tables():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS branches (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_name TEXT NOT NULL, branch_type TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, phone TEXT, password TEXT NOT NULL, role TEXT, branch_id INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY AUTOINCREMENT, item_code TEXT, item_name TEXT NOT NULL, branch_id INTEGER, quantity REAL DEFAULT 0.0, buy_price REAL DEFAULT 0.0, sale_price REAL DEFAULT 0.0, avg_cost REAL DEFAULT 0.0, favorite_rank INTEGER DEFAULT 0, expiry_date TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT UNIQUE NOT NULL, phone TEXT, total_purchases REAL DEFAULT 0.0, balance REAL DEFAULT 0.0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS invoices (id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER, user_id INTEGER, customer_name TEXT, customer_phone TEXT, total_amount REAL, payment_method TEXT, notes TEXT, shift_status TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
    cursor.execute("CREATE TABLE IF NOT EXISTS transfer_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, from_branch_id INTEGER, to_branch_id INTEGER, transfer_type TEXT, items_details TEXT, status TEXT, transfer_date DATETIME DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    
    # إضافة فرع رئيسي وأدمن افتراضي إن لم يكن موجوداً
    if cursor.execute("SELECT COUNT(*) FROM branches").fetchone()[0] == 0:
        cursor.execute("INSERT INTO branches (branch_name, branch_type) VALUES ('الفرع الرئيسي - مصراتة', 'مخزن')")
        conn.commit()
    if cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        cursor.execute("INSERT INTO users (username, password, role, branch_id) VALUES ('admin', 'admin123', 'Admin', 1)")
        conn.commit()
    conn.close()

create_tables()

# جلسة المستخدم الافتراضية للعرض
if "logged_in" not in st.session_state: st.session_state["logged_in"] = True
if "username" not in st.session_state: st.session_state["username"] = "المهندس شريف"
if "role" not in st.session_state: st.session_state["role"] = "Admin"
if "branch_id" not in st.session_state: st.session_state["branch_id"] = 1
if "cart" not in st.session_state: st.session_state["cart"] = []

# --- 3. نافذة إتمام الدفع ---
@st.dialog("💳 إتمام الدفع وإصدار الفاتورة")
def checkout_payment_dialog(b_id, g_tot, branch_name_str, cashier_name_str):
    st.subheader(f"إجمالي الفاتورة المطلوب: {g_tot:,.2f} د.ل")
    cust_name = st.text_input("اسم الزبون:", value="زبون نقدي")
    cust_phone = st.text_input("رقم الهاتف:", value="")
    pay_method = st.selectbox("نوع الدفع:", ["كاش (نقدي)", "شبكة / بطاقة", "آجل (على الحساب)"])
    
    paid_amount = st.number_input("المبلغ المدفوع (د.ل):", min_value=0.0, value=float(g_tot), step=0.5)
    change_due = paid_amount - g_tot
    
    if change_due >= 0: st.success(f"💵 الباقي المستحق للزبون: **{change_due:,.2f} د.ل**")
    else: st.error(f"⚠️ المبلغ غير كافٍ! العجز: **{abs(change_due):,.2f} د.ل**")
    
    if st.button("🖨️ تأكيد وإصدار الفاتورة", type="primary", use_container_width=True):
        if paid_amount >= g_tot or pay_method == "آجل (على الحساب)":
            conn = get_db_connection()
            cart_json = json.dumps(st.session_state["cart"], ensure_ascii=False)
            cursor_res = conn.execute("""
                INSERT INTO invoices (branch_id, user_id, customer_name, customer_phone, total_amount, payment_method, notes, shift_status) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (b_id, 1, cust_name, cust_phone, g_tot, pay_method, cart_json, "1"))
            inv_id = cursor_res.lastrowid

            for c_item in st.session_state["cart"]:
                if c_item.get("id") != 99999:
                    conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))

            conn.commit()
            conn.close()

            st.session_state["last_invoice"] = {
                "inv_id": inv_id, "branch": branch_name_str,
                "cashier": cashier_name_str, "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "customer": cust_name, "items": st.session_state["cart"].copy(), "total": g_tot, "method": pay_method
            }
            st.session_state["cart"] = []
            st.success("✅ تم إصدار الفاتورة بنجاح!")
            st.rerun()

# --- 4. واجهة نقطة البيع المباشرة ---
st.markdown('<h2 style="text-align: right; direction: rtl;">🛒 مجموعة أبو زيد التجارية - نقطة البيع الفورية (POS)</h2>', unsafe_allow_html=True)

conn = get_db_connection()
branches_data = conn.execute("SELECT id, branch_name FROM branches").fetchall()
b_dict = {b["branch_name"]: b["id"] for b in branches_data}
sel_pos = st.selectbox("اختر الفرع الحالي للبيع:", list(b_dict.keys()))
b_id = b_dict[sel_pos]

# إضافة أصناف تجريبية فورية إن كان المخزن فارغاً لضمان نجاح العرض
if conn.execute("SELECT COUNT(*) FROM items WHERE branch_id = ?", (b_id,)).fetchone()[0] == 0:
    conn.execute("INSERT INTO items (item_code, item_name, branch_id, quantity, buy_price, sale_price, favorite_rank) VALUES ('101', 'بندق محمص فاخر', ?, 100.0, 20.0, 30.0, 1)", (b_id,))
    conn.execute("INSERT INTO items (item_code, item_name, branch_id, quantity, buy_price, sale_price, favorite_rank) VALUES ('102', 'لوز مقشر أمريكي', ?, 150.0, 25.0, 35.0, 1)", (b_id,))
    conn.commit()

# عرض الفاتورة الأخيرة بعد الدفع
if "last_invoice" in st.session_state and st.session_state["last_invoice"]:
    inv = st.session_state["last_invoice"]
    st.success(f"✅ تم دفع الفاتورة رقم #{inv['inv_id']} بقيمة {inv['total']} د.ل بنجاح!")
    if st.button("✖️ إغلاق الفاتورة ومتابعة البيع"):
        st.session_state["last_invoice"] = None
        st.rerun()

col_grid, col_fav = st.columns([3, 1])

with col_grid:
    st.markdown("### 🧾 سلة المبيعات")
    if not st.session_state["cart"]:
        st.info("السلة فارغة. اختر أصنافاً من القائمة الجانبية أو المفضلة.")
    else:
        for index, cart_item in enumerate(st.session_state["cart"]):
            c1, c2, c3, c4, c5 = st.columns([2, 1, 1, 1, 0.5])
            c1.write(cart_item['name'])
            c2.write(f"كمية: {cart_item['qty']}")
            c3.write(f"سعر: {cart_item['price']}")
            c4.write(f"إجمالي: {cart_item['total']}")
            if c5.button("🗑️", key=f"del_{index}"):
                st.session_state["cart"].pop(index)
                st.rerun()

    g_tot = sum(item["total"] for item in st.session_state.get("cart", []))
    st.markdown(f"### 💰 الإجمالي المطلوب: {g_tot:,.2f} د.ل")
    
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if st.button("💰 دفع وإصدار الفاتورة (Checkout)", type="primary", use_container_width=True) and st.session_state["cart"]:
            checkout_payment_dialog(b_id, g_tot, sel_pos, "المهندس شريف")
    with col_b2:
        if st.button("❌ تفريغ السلة", use_container_width=True):
            st.session_state["cart"] = []
            st.rerun()

with col_fav:
    st.markdown("### ⭐ الأصناف المتاحة للبيع")
    items_list = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
    for it in items_list:
        if st.button(f"➕ {it['item_name']} ({it['sale_price']} د.ل)", key=f"add_item_{it['id']}", use_container_width=True):
            st.session_state["cart"].append({
                "id": it["id"], "code": it["item_code"], "name": it["item_name"],
                "price": float(it["sale_price"]), "qty": 1.0, "total": float(it["sale_price"])
            })
            st.rerun()

conn.close()
