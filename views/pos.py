import streamlit as st
import pandas as pd
from datetime import datetime
from database import get_db_connection

# --- دالة شاشة إتمام الدفع وإصدار الفاتورة ---
@st.dialog("💳 إتمام الدفع وإصدار الفاتورة")
def checkout_payment_dialog(b_id, g_tot):
    st.subheader(f"إجمالي الفاتورة المطلوب: {g_tot:,.2f} د.ل")
    cust_name = st.text_input("اسم الزبون:", value="زبون نقدي")
    cust_phone = st.text_input("رقم الهاتف (اختياري):", value="")
    
    conn = get_db_connection()
    applied_discount = 0.0
    if cust_phone.strip():
        cust_db = conn.execute("SELECT * FROM customers WHERE phone = ?", (cust_phone.strip(),)).fetchone()
        if cust_db and float(cust_db["total_purchases"]) >= 1000.0:
            st.success("🎁 يستحق الزبون خصم الولاء: **50.00 د.ل**")
            if st.checkbox("تطبيق خصم الولاء (50 دينار)"):
                applied_discount = 50.0
                
    final_tot = max(0.0, g_tot - applied_discount)
    
    # 🌟 إضافة طرق الدفع الجديدة المطلوبة
    pay_method = st.selectbox("نوع الدفع:", [
        "كاش (نقدي)", 
        "شبكة / بطاقة", 
        "آجل", 
        "خصم من رصيد مدين (لمورد أو زبون جملة)"
    ])
    
    paid_amount = st.number_input("المبلغ المدفوع (د.ل):", min_value=0.0, value=float(final_tot), step=0.5, format="%.2f")
    
    change_due = paid_amount - final_tot
    if change_due >= 0:
        st.success(f"💵 الباقي المستحق للزبون: **{change_due:,.2f} د.ل**")
    else:
        st.error(f"⚠️ المبلغ غير كافٍ! العجز: **{abs(change_due):,.2f} د.ل**")
    
    if st.button("🖨️ تأكيد وإصدار الفاتورة", type="primary", use_container_width=True):
        if paid_amount >= final_tot or pay_method in ["آجل", "خصم من رصيد مدين (لمورد أو زبون جملة)"]:
            target_inv_branch = b_id if b_id != "ALL" else conn.execute("SELECT id FROM branches LIMIT 1").fetchone()["id"]
            
            cur_in = conn.cursor()
            cursor_res = cur_in.execute("""
                INSERT INTO invoices (branch_id, user_id, customer_name, customer_phone, total_amount, payment_method) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (target_inv_branch, st.session_state.get("user_id", 1), cust_name.strip() if cust_name else "زبون نقدي", cust_phone.strip(), final_tot, pay_method))
            
            inv_id = cursor_res.lastrowid

            for c_item in st.session_state["cart"]:
                conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))

            conn.commit()
            
            branch_info = conn.execute("SELECT branch_name FROM branches WHERE id = ?", (target_inv_branch,)).fetchone()
            branch_name_str = branch_info["branch_name"] if branch_info else "الفرع الرئيسي"
            
            user_info = conn.execute("SELECT username FROM users WHERE id = ?", (st.session_state.get("user_id", 1),)).fetchone()
            cashier_name_str = user_info["username"] if user_info else "كاشير عام"
            
            conn.close()

            st.session_state["last_invoice"] = {
                "inv_id": inv_id,
                "branch": branch_name_str,
                "cashier": cashier_name_str,
                "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "customer": cust_name,
                "items": st.session_state["cart"].copy(),
                "total": final_tot,
                "method": pay_method
            }
            st.session_state["cart"] = []
            st.success("✅ تم إصدار الفاتورة بنجاح!")
            st.rerun()
        else:
            st.warning("⚠️ المبلغ المدفوع أقل من إجمالي الفاتورة.")
    conn.close()

# --- معالجة الباركود (العادي والميزان) بالكمية المفتوحة ---
def process_barcode_scan():
    code = st.session_state.barcode_scan_input.strip()
    qty_to_add = st.session_state.get("barcode_qty_input", 1.0)
    
    if code:
        b_id = st.session_state.get("branch_id", "ALL")
        conn = get_db_connection()
        item = None
        
        # معالجة باركود الميزان (يبدأ بـ 20 وطوله 13 رقم غالباً)
        if code.startswith("20") and len(code) >= 12:
            item_code = code[2:7] # كود الصنف في الميزان
            weight_value = float(code[7:12]) / 1000.0 # استخراج الوزن بالكيلوجرام
            
            if b_id == "ALL": item = conn.execute("SELECT * FROM items WHERE item_code = ? LIMIT 1", (item_code,)).fetchone()
            else: item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (item_code, b_id)).fetchone()
            
            if item:
                qty_to_add = weight_value # إجبار الكمية لتكون هي وزن الميزان المستخرج
                
        # إذا لم يكن باركود ميزان، نبحث عنه كباركود عادي
        if not item:
            if b_id == "ALL": item = conn.execute("SELECT * FROM items WHERE item_code = ? LIMIT 1", (code,)).fetchone()
            else: item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
            
        if item:
            unit_price = float(item["sale_price"])
            total_price = unit_price * qty_to_add
            st.session_state["cart"].append({
                "id": item["id"], "code": item["item_code"], "name": item["item_name"], 
                "price": unit_price, "qty": float(qty_to_add), "total": total_price
            })
        else:
            st.toast(f"❌ الباركود غير مسجل: {code}")
            
        conn.close()
    st.session_state.barcode_scan_input = "" # تفريغ حقل الباركود للاستعداد للصنف التالي

# --- واجهة شاشة نقطة البيع الأساسية ---
def show_page():
    # 🎨 1. إصلاح CSS (توضيح الألوان وإصلاح تداخل النصوص)
    st.markdown("""
        <style>
        .top-panel {
            background-color: #e2e8f0;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #cbd5e1;
            margin-bottom: 15px;
        }
        /* إصلاح مشكلة اللون الغامق */
        .totals-panel {
            background-color: #0f172a;
            color: #ffffff !important; 
            padding: 15px;
            border-radius: 8px;
            text-align: left;
            font-size: 22px;
            border: 2px solid #334155;
            margin-top: 10px;
        }
        .totals-panel span { color: #22c55e !important; font-weight: bold; } /* لون الصافي أخضر فاتح */
        
        .pos-btn > button { height: 60px; font-size: 18px !important; font-weight: bold; }
        .btn-green > button { background-color: #16a34a !important; color: white !important; }
        .btn-red > button { background-color: #dc2626 !important; color: white !important; }
        </style>
    """, unsafe_allow_html=True)

    st.header("🛒 نقطة البيع (POS) - شاشة الكاشير العصرية")
    
    conn = get_db_connection()
    role = st.session_state.get("role", "")
    username = st.session_state.get("username", "")
    user_branch_id = st.session_state.get("branch_id")

    # 🔒 حماية الفروع
    if role in ["Admin", "General_Supervisor"]:
        b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
        sel_pos = st.selectbox("اختر الفرع الحالي (صلاحية إدارة):", ["🌐 إجمالي كل الفروع"] + list(b_dict.keys()))
        b_id = "ALL" if sel_pos == "🌐 إجمالي كل الفروع" else b_dict[sel_pos]
        branch_name_display = sel_pos
    else:
        b_id = user_branch_id
        b_row = conn.execute("SELECT branch_name FROM branches WHERE id=?", (b_id,)).fetchone()
        branch_name_display = b_row["branch_name"] if b_row else "الفرع الحالي"
        
    st.session_state["branch_id"] = b_id

    # 🌟 عرض الفاتورة وإمكانية تحميلها كـ HTML أو إخفائها
    if "last_invoice" in st.session_state and st.session_state["last_invoice"]:
        inv = st.session_state["last_invoice"]
        
        # تجهيز كود HTML للفاتورة للتحميل
        items_html = "".join([f"<tr><td>{i['name']}</td><td>{i['qty']}</td><td>{i['price']}</td><td>{i['total']}</td></tr>" for i in inv["items"]])
        html_file_content = f"""
        <html dir="rtl">
        <head><meta charset="utf-8"><title>فاتورة #{inv['inv_id']}</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; max-width: 350px; margin: auto; padding: 20px; border: 1px solid #000;">
            <h2 style="margin-bottom: 5px;">مجموعة أبو زيد التجارية</h2>
            <p style="margin-top: 0;">فرع: {inv['branch']}</p>
            <hr>
            <p style="text-align: right;"><b>رقم الفاتورة:</b> #{inv['inv_id']}<br>
            <b>التاريخ:</b> {inv['date_time']}<br>
            <b>الكاشير:</b> {inv['cashier']}<br>
            <b>الزبون:</b> {inv['customer']} <br>
            <b>طريقة الدفع:</b> {inv['method']}</p>
            <hr>
            <table style="width: 100%; text-align: right; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #000;"><th>الصنف</th><th>الكمية</th><th>السعر</th><th>المجموع</th></tr>
                {items_html}
            </table>
            <hr>
            <h3 style="text-align: left;">الإجمالي: {inv['total']:,.2f} د.ل</h3>
            <p style="font-size: 12px; margin-top: 20px;">شكراً لتسوقكم معنا 🥜</p>
        </body>
        </html>
        """

        # تم حل مشكلة تداخل النصوص في الـ expander
        with st.expander("🧾 تم حفظ الفاتورة بنجاح - تفاصيل الروشتة الحالية", expanded=True):
            st.components.v1.html(html_file_content, height=400, scrolling=True)
            
            c_inv1, c_inv2 = st.columns(2)
            with c_inv1:
                st.download_button(
                    label="📥 تحميل الفاتورة (HTML)",
                    data=html_file_content.encode('utf-8'),
                    file_name=f"Invoice_{inv['inv_id']}.html",
                    mime="text/html",
                    use_container_width=True
                )
            with c_inv2:
                # زر لإخفاء الفاتورة والعودة للعمل النظيف
                if st.button("✖️ إخفاء الفاتورة ومتابعة البيع", type="primary", use_container_width=True):
                    st.session_state["last_invoice"] = None
                    st.rerun()
                    
        st.markdown("---")

    pos_tab1, pos_tab2, pos_tab3 = st.tabs(["🛒 كاشير البيع السريع (Desktop UI)", "🔍 البحث اليدوي", "📋 أرشيف وتقارير الوردية"])

    # ==========================================
    # التبويب الأول: شاشة الكاشير
    # ==========================================
    with pos_tab1:
        st.markdown('<div class="top-panel">', unsafe_allow_html=True)
        col_qty, col_bar, col_info = st.columns([1, 2, 2])
        
        with col_qty:
            # 🌟 الكمية المفتوحة قبل ضرب الباركود
            st.number_input("الكمية المطلوبة (كجم/وحدة):", min_value=0.01, value=1.00, step=0.5, key="barcode_qty_input")
            
        with col_bar:
            st.text_input("🔍 مسح الباركود الفوري (اضغط Enter):", key="barcode_scan_input", on_change=process_barcode_scan)
            
        with col_info:
            next_inv = conn.execute("SELECT MAX(id) FROM invoices").fetchone()[0] or 0
            inv_num = next_inv + 1
            st.markdown(f"""
                <div style="font-size: 15px; text-align: left; line-height: 1.6;">
                    <b>رقم الفاتورة:</b> <span style="color:red; font-size: 18px;">#{inv_num}</span><br>
                    <b>الفرع:</b> {branch_name_display} | <b>الكاشير:</b> {username}
                </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        col_grid, col_fav = st.columns([3, 1])
        
        with col_grid:
            st.markdown("### 🧾 بيانات الفاتورة الحالية")
            if not st.session_state["cart"]:
                df_cart = pd.DataFrame(columns=["مسلسل", "الكود", "اسم الصنف", "الكمية", "السعر", "الإجمالي"])
                st.dataframe(df_cart, use_container_width=True, height=250)
            else:
                cart_data = []
                for idx, item in enumerate(st.session_state["cart"]):
                    cart_data.append({
                        "مسلسل": idx + 1,
                        "الكود": item["code"],
                        "اسم الصنف": item["name"],
                        "الكمية": item["qty"],
                        "السعر": item["price"],
                        "الإجمالي": item["total"]
                    })
                df_cart = pd.DataFrame(cart_data)
                st.dataframe(df_cart, use_container_width=True, height=250, hide_index=True)

            g_tot = sum(item["total"] for item in st.session_state.get("cart", []))
            
            # 🌟 تم إصلاح الألوان ليكون النص أبيض مقروء على الخلفية الكحلية
            st.markdown(f"""
                <div class="totals-panel">
                    إجمالي الفاتورة: <span style="color:white !important;">{g_tot:,.2f} د.ل</span> &nbsp; | &nbsp;
                    <span style="color:#22c55e !important; font-size:26px;">الصافي المطلوب: {g_tot:,.2f} د.ل</span>
                </div>
            """, unsafe_allow_html=True)
            
            st.write("")
            c_btn1, c_btn3 = st.columns([2, 1])
            with c_btn1:
                st.markdown('<div class="pos-btn btn-green">', unsafe_allow_html=True)
                if st.button("💰 دفع وطباعة (F12)", use_container_width=True) and st.session_state["cart"]:
                    checkout_payment_dialog(b_id, g_tot)
                st.markdown('</div>', unsafe_allow_html=True)
            with c_btn3:
                st.markdown('<div class="pos-btn btn-red">', unsafe_allow_html=True)
                if st.button("❌ تفريغ الفاتورة", use_container_width=True):
                    st.session_state["cart"] = []
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

        with col_fav:
            st.markdown("### ⭐ الأصناف السريعة")
            fav_items = conn.execute("SELECT * FROM items WHERE favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ? AND favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC", (() if b_id=="ALL" else (b_id,))).fetchall()
            st.markdown("<div style='background-color:#f1f5f9; padding:10px; border-radius:5px; height:400px; overflow-y:auto; border:1px solid #cbd5e1;'>", unsafe_allow_html=True)
            
            if fav_items:
                for item in fav_items:
                    # إضافة الصنف المفضل بناءً على الكمية المفتوحة المحددة بالأعلى
                    if st.button(f"{item['item_name']}\n{item['sale_price']} د.ل", key=f"fav_{item['id']}", use_container_width=True):
                        qty = st.session_state.get("barcode_qty_input", 1.0)
                        st.session_state["cart"].append({
                            "id": item["id"], "code": item["item_code"], "name": item["item_name"], 
                            "price": float(item["sale_price"]), "qty": float(qty), "total": float(item["sale_price"]) * float(qty)
                        })
                        st.rerun()
            else:
                st.info("لا توجد أصناف مفضلة.")
            st.markdown("</div>", unsafe_allow_html=True)

    # ==========================================
    # التبويب الثاني والثالث ...
    # ==========================================
    with pos_tab2:
        st.subheader("⚡ البحث اليدوي عن الأصناف")
        all_items_db = conn.execute("SELECT * FROM items" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ?", (() if b_id=="ALL" else (b_id,))).fetchall()
        if all_items_db:
            item_names_dict = {it["item_name"] + f" (الكود: {it['item_code']} - السعر: {it['sale_price']} د.ل)": it for it in all_items_db}
            selected_manual_item_str = st.selectbox("اختر الصنف يدوياً:", list(item_names_dict.keys()))
            selected_item_obj = item_names_dict[selected_manual_item_str]
            manual_qty = st.number_input("الكمية المطلوبة يدوياً:", min_value=0.01, value=1.0, step=0.1)
            
            if st.button("➕ إضافة إلى سلة المبيعات", type="primary"):
                st.session_state["cart"].append({
                    "id": selected_item_obj["id"], "name": selected_item_obj["item_name"], "code": selected_item_obj["item_code"],
                    "price": float(selected_item_obj["sale_price"]), "qty": float(manual_qty), "total": float(selected_item_obj["sale_price"]) * float(manual_qty)
                })
                st.success(f"تمت إضافة ({selected_item_obj['item_name']}) بنجاح!")
                st.rerun()

    with pos_tab3:
        st.subheader("📋 أرشيف وتقارير الوردية")
        col_xz1, col_xz2 = st.columns(2)
        with col_xz1:
            if st.button("📊 تقرير X-Report (مبيعات الشفت الحالي)", use_container_width=True):
                shift_sales = conn.execute("SELECT SUM(total_amount) AS total, COUNT(*) as cnt FROM invoices WHERE DATE(created_at) = DATE('now')").fetchone()
                st.info(f"📊 **تقرير X-Report:** إجمالي المبيعات = **{shift_sales['total'] or 0:,.2f} د.ل** عبر **{shift_sales['cnt']}** فاتورة.")
        with col_xz2:
            if st.button("🔄 تقرير Z-Report (إغلاق الوردية)", type="primary", use_container_width=True):
                st.success("✅ تم إغلاق الوردية بنجاح.")

    conn.close()
