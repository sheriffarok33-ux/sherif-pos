import streamlit as st
import pandas as pd
from database import get_db_connection

# --- شاشة الدفع المنبثقة ---
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
                db_it = conn.execute("SELECT quantity FROM items WHERE id = ?", (c_item["id"],)).fetchone()
                if db_it and float(db_it["quantity"]) < c_item["qty"]:
                    can_proceed = False
                    st.warning(f"⚠️ الصنف ({c_item['name']}) غير متوفر بالكمية المطلوبة!")

            if can_proceed:
                cur_in = conn.cursor()
                cur_in.execute("INSERT INTO invoices (branch_id, user_id, customer_name, customer_phone, total_amount, payment_method) VALUES (?, ?, ?, ?, ?, ?)", 
                               (target_inv_branch, st.session_state["user_id"], cust_name.strip() if cust_name else "زبون نقدي", cust_phone.strip(), final_tot, pay_method))
                
                for c_item in st.session_state["cart"]:
                    conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                
                if cust_phone.strip() and cust_name.strip() != "زبون نقدي":
                    existing_cust = cur_in.execute("SELECT id, total_purchases FROM customers WHERE phone = ?", (cust_phone.strip(),)).fetchone()
                    if existing_cust:
                        cur_in.execute("UPDATE customers SET total_purchases = total_purchases + ?, customer_name = ? WHERE id = ?", (final_tot, cust_name.strip(), existing_cust['id']))
                    else:
                        cur_in.execute("INSERT INTO customers (customer_name, phone, total_purchases) VALUES (?, ?, ?)", (cust_name.strip(), cust_phone.strip(), final_tot))
                        
                conn.commit()
                conn.close()
                st.session_state["cart"] = []
                st.session_state["success_alert_msg"] = "تم إصدار الفاتورة بنجاح!"
                st.rerun()
            else:
                conn.close()
        else:
            st.warning("⚠️ المبلغ المدفوع أقل من الإجمالي.")
    conn.close()

# --- معالجة الباركود ---
def process_scale_barcode():
    code = st.session_state.barcode_scan.strip()
    if code:
        b_id = st.session_state.get("branch_id")
        conn = get_db_connection()
        item = None
        if code.startswith("20") and len(code) >= 12:
            item_code = code[2:7]
            scale_value = float(code[7:]) / 100.0
            if b_id == "ALL": item = conn.execute("SELECT * FROM items WHERE item_code = ? LIMIT 1", (item_code,)).fetchone()
            else: item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (item_code, b_id)).fetchone()
            
            if item:
                unit_price = float(item["sale_price"])
                calculated_qty = scale_value / unit_price if unit_price > 0 else 1.0
                st.session_state["cart"].append({"id": item["id"], "code": item["item_code"], "name": item["item_name"], "price": unit_price, "qty": float(calculated_qty), "total": float(scale_value)})
        if not item:
            if b_id == "ALL": item = conn.execute("SELECT * FROM items WHERE item_code = ? LIMIT 1", (code,)).fetchone()
            else: item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
            
            if item:
                st.session_state["cart"].append({"id": item["id"], "code": item["item_code"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": 1.0, "total": float(item["sale_price"]) * 1.0})
            else:
                st.toast(f"❌ الباركود غير مسجل: {code}")
        conn.close()
    st.session_state.barcode_scan = ""

def process_pos_manual_barcode():
    code = st.session_state.pos_manual_barcode.strip()
    if code:
        b_id = st.session_state.get("branch_id")
        conn = get_db_connection()
        if b_id == "ALL": item = conn.execute("SELECT * FROM items WHERE item_code = ? LIMIT 1", (code,)).fetchone()
        else: item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
        
        if item:
            st.session_state["cart"].append({"id": item["id"], "code": item["item_code"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": 1.0, "total": float(item["sale_price"]) * 1.0})
        else:
            st.toast(f"❌ الباركود غير مسجل: {code}")
        conn.close()
    st.session_state.pos_manual_barcode = ""


# --- الواجهة الأساسية للشاشة ---
def show_page():
    st.header("🛒 نقطة البيع (POS) - شاشة الكاشير العصرية")
    
    conn = get_db_connection()
    b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
    sel_pos = st.selectbox("الفرع:", ["🌐 إجمالي كل الفروع"] + list(b_dict.keys()))
    b_id = "ALL" if sel_pos == "🌐 إجمالي كل الفروع" else b_dict[sel_pos]
    
    fav_items = conn.execute("SELECT * FROM items WHERE favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ? AND favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC", (() if b_id=="ALL" else (b_id,))).fetchall()
    
    st.text_input("🔍 مسح باركود الميزان أو الباركود العادي:", key="barcode_scan", on_change=process_scale_barcode)
    st.text_input("⚡ إدخال باركود الصنف بالماسح الضوئي الفعلي مباشرة:", key="pos_manual_barcode", on_change=process_pos_manual_barcode)

    col_g, col_c = st.columns([2, 1])
    
    # قائمة الأصناف المفضلة
    with col_g:
        st.subheader("⭐ الأصناف المفضلة للكاشير")
        if fav_items:
            for item in fav_items:
                c1, c2, c3 = st.columns([2, 1, 1])
                with c1: st.write(f"<b>{item['item_name']}</b> (المتاح: {item['quantity']} كجم)", unsafe_allow_html=True)
                with c2: st.write(f"{item['sale_price']} د.ل")
                with c3:
                    with st.form(key=f"pos_q_{item['id']}", clear_on_submit=True):
                        q_in = st.number_input("كمية", min_value=0.0, value=0.0, step=0.1, format="%.2f")
                        if st.form_submit_button("➕ إضافة") and q_in > 0:
                            st.session_state["cart"].append({"id": item["id"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": float(q_in), "total": float(item["sale_price"]) * float(q_in)})
                            st.rerun()
                            
    # سلة المبيعات
    with col_c:
        st.subheader("🛒 سلة المبيعات الحالية")
        if st.session_state["cart"]:
            for index, cart_item in enumerate(st.session_state["cart"]):
                col_item_desc, col_item_del = st.columns([3, 1])
                with col_item_desc:
                    st.markdown(f"**{cart_item['name']}**<br>`{cart_item['qty']} كجم` × `{cart_item['price']}` = **{cart_item['total']:,.2f} د.ل**", unsafe_allow_html=True)
                with col_item_del:
                    if st.button("❌", key=f"del_cart_item_{index}", help="حذف"):
                        st.session_state["cart"].pop(index)
                        st.rerun()
                st.markdown("---")
                
            g_tot = sum([x["total"] for x in st.session_state["cart"]])
            st.metric("الإجمالي النهائي", f"{g_tot:,.2f} د.ل")
            if st.button("🖨️ إتمام وطباعة الفاتورة", type="primary", use_container_width=True): 
                checkout_payment_dialog(b_id, g_tot)
            if st.button("🗑️ تفريغ السلة بالكامل", use_container_width=True): 
                st.session_state["cart"] = []
                st.rerun()
        else:
            st.info("السلة فارغة حالياً. قم بمسح الباركود أو اختيار صنف.")
    conn.close()
