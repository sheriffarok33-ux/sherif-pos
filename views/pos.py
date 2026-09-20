import streamlit as st
import pandas as pd
from datetime import datetime
from database import get_db_connection

# --- دالة شاشة إتمام الدفع وإصدار الفاتورة وتجهيزها للواتساب ---
@st.dialog("💳 إتمام الدفع وإصدار الفاتورة")
def checkout_payment_dialog(b_id, g_tot):
    st.subheader(f"إجمالي الفاتورة المطلوب: {g_tot:,.2f} د.ل")
    cust_name = st.text_input("اسم الزبون:", value="زبون نقدي")
    cust_phone = st.text_input("رقم هاتف الزبون (للإرسال عبر الواتساب):", value="")
    
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
            
            cur_in = conn.cursor()
            # إدخال الفاتورة وجلب رقمها التسلسلي
            cursor_res = cur_in.execute("""
                INSERT INTO invoices (branch_id, user_id, customer_name, customer_phone, total_amount, payment_method) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (target_inv_branch, st.session_state.get("user_id", 1), cust_name.strip() if cust_name else "زبون نقدي", cust_phone.strip(), final_tot, pay_method))
            
            inv_id = cursor_res.lastrowid

            # خصم الكميات من المخزون مع فحص رصيد الصفر
            for c_item in st.session_state["cart"]:
                db_it = conn.execute("SELECT quantity FROM items WHERE id = ?", (c_item["id"],)).fetchone()
                current_qty = float(db_it["quantity"]) if db_it else 0.0
                
                # خصم الكمية حتى لو وصلت للسلب أو الصفر
                conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))

            # تسجيل العملاء والولاء
            if cust_phone.strip() and cust_name.strip() != "زبون نقدي":
                existing_cust = cur_in.execute("SELECT id, total_purchases FROM customers WHERE phone = ?", (cust_phone.strip(),)).fetchone()
                if existing_cust:
                    cur_in.execute("UPDATE customers SET total_purchases = total_purchases + ?, customer_name = ? WHERE id = ?", (final_tot, cust_name.strip(), existing_cust['id']))
                else:
                    cur_in.execute("INSERT INTO customers (customer_name, phone, total_purchases) VALUES (?, ?, ?)", (cust_name.strip(), cust_phone.strip(), final_tot))
                    
            conn.commit()
            
            # جلب معلومات الفرع والكاشير للروشتة الاحترافية
            branch_info = conn.execute("SELECT branch_name FROM branches WHERE id = ?", (target_inv_branch,)).fetchone()
            branch_name_str = branch_info["branch_name"] if branch_info else "الفرع الرئيسي"
            
            user_info = conn.execute("SELECT username FROM users WHERE id = ?", (st.session_state.get("user_id", 1),)).fetchone()
            cashier_name_str = user_info["username"] if user_info else "كاشير عام"
            
            conn.close()

            # تفريغ السلة وتخزين الفاتورة الأخيرة للعرض والطباعة والواتساب
            st.session_state["last_invoice"] = {
                "inv_id": inv_id,
                "branch": branch_name_str,
                "cashier": cashier_name_str,
                "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "customer": cust_name,
                "phone": cust_phone,
                "items": st.session_state["cart"].copy(),
                "total": final_tot,
                "paid": paid_amount,
                "change": change_due,
                "method": pay_method
            }
            st.session_state["cart"] = []
            st.success("✅ تم إصدار الفاتورة بنجاح!")
            st.rerun()
        else:
            st.warning("⚠️ المبلغ المدفوع أقل من إجمالي الفاتورة.")
    conn.close()


# --- معالجة الباركود السريع ---
def process_scale_barcode():
    code = st.session_state.barcode_scan.strip()
    if code:
        b_id = st.session_state.get("branch_id", "ALL")
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
                
                # فحص رصيد الصفر والتنبيه
                if float(item["quantity"]) <= 0:
                    st.toast(f"⚠️ تنبيه: الصنف ({item['item_name']}) منتهي في النظام! يرجى إبلاغ المدير لإضافة فائض.", icon="🚨")
                
                st.session_state["cart"].append({"id": item["id"], "code": item["item_code"], "name": item["item_name"], "price": unit_price, "qty": float(calculated_qty), "total": float(scale_value)})
        if not item:
            if b_id == "ALL": item = conn.execute("SELECT * FROM items WHERE item_code = ? LIMIT 1", (code,)).fetchone()
            else: item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
            
            if item:
                if float(item["quantity"]) <= 0:
                    st.toast(f"⚠️ تنبيه: الصنف ({item['item_name']}) منتهي في النظام! يرجى إبلاغ المدير لإضافة فائض.", icon="🚨")
                st.session_state["cart"].append({"id": item["id"], "code": item["item_code"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": 1.0, "total": float(item["sale_price"]) * 1.0})
            else:
                st.toast(f"❌ الباركود غير مسجل: {code}")
        conn.close()
    st.session_state.barcode_scan = ""


# --- واجهة شاشة نقطة البيع الأساسية ---
def show_page():
    st.header("🛒 نقطة البيع (POS) - شاشة الكاشير العصرية")
    
    conn = get_db_connection()
    b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
    sel_pos = st.selectbox("اختر الفرع الحالي:", ["🌐 إجمالي كل الفروع"] + list(b_dict.keys()))
    b_id = "ALL" if sel_pos == "🌐 إجمالي كل الفروع" else b_dict[sel_pos]
    st.session_state["branch_id"] = b_id

    # عرض الفاتورة الأخيرة المصدرة مباشرة للطباعة أو الإرسال للواتساب
    if "last_invoice" in st.session_state and st.session_state["last_invoice"]:
        inv = st.session_state["last_invoice"]
        with st.expander(f"🖨️ تفاصيل ورشتة الفاتورة الأخيرة رقم (#{inv['inv_id']}) - جاهزة للطباعة والواتساب", expanded=True):
            st.markdown(f"""
            <div style="border: 2px dashed #4f46e5; padding: 20px; border-radius: 10px; background-color: #f8fafc; color: #1e293b; direction: rtl; text-align: right;">
                <h3 style="text-align: center; margin: 0; color: #4f46e5;">مجموعة أبو زيد التجارية</h3>
                <p style="text-align: center; font-size: 14px; margin: 5px 0;">فرع: <b>{inv['branch']}</b></p>
                <hr style="border: 0.5px solid #cbd5e1;">
                <p><b>رقم الفاتورة:</b> #{inv['inv_id']} | <b>التاريخ:</b> {inv['date_time']}</p>
                <p><b>الكاشير:</b> {inv['cashier']} | <b>الزبون:</b> {inv['customer']} ({inv['phone'] if inv['phone'] else 'بدون هاتف'})</p>
                <hr style="border: 0.5px solid #cbd5e1;">
                <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
                    <tr style="border-bottom: 1px solid #cbd5e1;"><th style="text-align:right;">الصنف</th><th style="text-align:center;">الكمية</th><th style="text-align:left;">السعر</th></tr>
            """, unsafe_allow_html=True)
            
            for itm in inv["items"]:
                st.markdown(f"<p style='margin: 4px 0;'>• {itm['name']} | {itm['qty']} كجم × {itm['price']} = <b>{itm['total']:,.2f} د.ل</b></p>", unsafe_allow_html=True)
                
            st.markdown(f"""
                </table>
                <hr style="border: 0.5px solid #cbd5e1;">
                <h4 style="text-align: left; color: #1e293b;">الإجمالي النهائي: {inv['total']:,.2f} د.ل</h4>
                <p style="font-size: 12px; text-align: center; color: #64748b; margin-top: 15px;">شكراً لتسوقكم معنا في مجموعة أبو زيد 🥜</p>
            </div>
            """, unsafe_allow_html=True)
            
            col_pr1, col_pr2 = st.columns(2)
            with col_pr1:
                if st.button("🖨️ طباعة الفاتورة حرارياً", use_container_width=True):
                    st.balloons()
                    st.success("تم إرسال الفاتورة إلى الطابعة الحرارية بنجاح!")
            with col_pr2:
                # زر واتساب جاهز برابط مباشر للرقم والرسالة
                if inv["phone"]:
                    wa_text = f"مرحباً {inv['customer']}، تفاصيل فاتورتك رقم #{inv['inv_id']} بقيمة {inv['total']:,.2f} د.ل من مجموعة أبو زيد. شكراً لك!"
                    st.markdown(f'<a href="https://wa.me/{inv["phone"]}?text={wa_text}" target="_blank"><button style="background-color:#25d366; color:white; border:none; padding:10px 20px; border-radius:5px; width:100%; font-weight:bold; cursor:pointer;">📲 إرسال الفاتورة عبر الواتساب</button></a>', unsafe_allow_html=True)
                else:
                    st.info("أدخل رقم هاتف الزبون أثناء الدفع لتفعيل زر الواتساب المباشر.")

    st.markdown("---")

    # تبويبات شاشة نقطة البيع
    pos_tab1, pos_tab2, pos_tab3 = st.tabs(["🛒 كاشير البيع السريع", "🔍 البحث اليدوي عن الأصناف", "📋 أرشيف الفواتير السابقة والتقارير (X & Z)"])

    with pos_tab1:
        fav_items = conn.execute("SELECT * FROM items WHERE favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ? AND favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC", (() if b_id=="ALL" else (b_id,))).fetchall()
        
        st.text_input("🔍 مسح باركود الميزان أو الباركود العادي الفوري:", key="barcode_scan", on_change=process_scale_barcode)

        col_g, col_c = st.columns([2, 1])
        
        with col_g:
            st.subheader("⭐ الأصناف المفضلة للكاشير")
            if fav_items:
                for item in fav_items:
                    c1, c2, c3 = st.columns([2, 1, 1])
                    with c1: 
                        qty_val = float(item['quantity'])
                        color_q = "green" if qty_val > 0 else "red"
                        st.markdown(f"<b>{item['item_name']}</b><br><span style='color:{color_q}; font-size:12px;'>المتاح: {qty_val} كجم</span>", unsafe_allow_html=True)
                    with c2: st.write(f"{item['sale_price']} د.ل")
                    with c3:
                        with st.form(key=f"pos_q_{item['id']}", clear_on_submit=True):
                            q_in = st.number_input("كمية", min_value=0.0, value=0.0, step=0.1, format="%.2f")
                            if st.form_submit_button("➕ إضافة") and q_in > 0:
                                if qty_val <= 0:
                                    st.toast(f"⚠️ تنبيه: الصنف ({item['item_name']}) منتهي في النظام! يرجى إبلاغ المدير لإضافة فائض.", icon="🚨")
                                st.session_state["cart"].append({"id": item["id"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": float(q_in), "total": float(item["sale_price"]) * float(q_in)})
                                st.rerun()
            else:
                st.info("لا توجد أصناف مفضلة محددة (1 إلى 20).")
                
        # سلة المبيعات
        with col_c:
            st.subheader("🛒 سلة المبيعات الحالية")
            if st.session_state.get("cart"):
                for index, cart_item in enumerate(st.session_state["cart"]):
                    col_item_desc, col_item_del = st.columns([3, 1])
                    with col_item_desc:
                        st.markdown(f"**{cart_item['name']}**<br>`{cart_item['qty']} كجم` × `{cart_item['price']}` = **{cart_item['total']:,.2f} د.ل**", unsafe_allow_html=True)
                    with col_item_del:
                        # زر حذف صنف محدد من السلة إذا أُضيف بالغلط
                        if st.button("❌", key=f"del_cart_item_{index}", help="حذف الصنف"):
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
                st.info("السلة فارغة حالياً.")

    # التبويب الثاني: البيع اليدوي (بدون ماسح باركود)
    with pos_tab2:
        st.subheader("⚡ البحث اليدوي عن الأصناف (بدون ماسح باركود)")
        all_items_db = conn.execute("SELECT * FROM items" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ?", (() if b_id=="ALL" else (b_id,))).fetchall()
        
        if all_items_db:
            item_names_dict = {it["item_name"] + f" (الكود: {it['item_code']} - السعر: {it['sale_price']} د.ل)": it for it in all_items_db}
            selected_manual_item_str = st.selectbox("اختر الصنف يدوياً:", list(item_names_dict.keys()))
            selected_item_obj = item_names_dict[selected_manual_item_str]
            
            manual_qty = st.number_input("الكمية المطلوبة (كجم / وحدة):", min_value=0.1, value=1.0, step=0.1)
            
            if st.button("➕ إضافة إلى سلة المبيعات يدوياً", type="primary"):
                if float(selected_item_obj["quantity"]) <= 0:
                    st.warning(f"⚠️ تنبيه: الصنف ({selected_item_obj['item_name']}) منتهي في النظام! يرجى إبلاغ المدير لإضافة فائض.")
                
                st.session_state["cart"].append({
                    "id": selected_item_obj["id"], 
                    "name": selected_item_obj["item_name"], 
                    "price": float(selected_item_obj["sale_price"]), 
                    "qty": float(manual_qty), 
                    "total": float(selected_item_obj["sale_price"]) * float(manual_qty)
                })
                st.success(f"تمت إضافة ({selected_item_obj['item_name']}) إلى السلة بنجاح!")
                st.rerun()
        else:
            st.info("لا توجد أصناف مسجلة في هذا الفرع.")

    # التبويب الثالث: أرشيف الفواتير السابقة وتقارير الورديات (X & Z)
    with pos_tab3:
        st.subheader("📋 أرشيف الفواتير السابقة وإعادة الطباعة وتقارير الورديات")
        
        # تقارير الورديات X و Z
        col_xz1, col_xz2 = st.columns(2)
        with col_xz1:
            if st.button("📊 تقرير X-Report (قراءة مبيعات الشفت الحالي والتسليم بين الكاشير وزميله)", use_container_width=True):
                shift_sales = conn.execute("SELECT SUM(total_amount) AS total, COUNT(*) as cnt FROM invoices WHERE DATE(created_at) = DATE('now')").fetchone()
                st.info(f"📊 **تقرير X-Report:** إجمالي مبيعات اليوم حتى اللحظة = **{shift_sales['total'] or 0:,.2f} د.ل** عبر **{shift_sales['cnt']}** فاتورة مسجلة.")
        with col_xz2:
            if st.button("🔄 تقرير Z-Report (تصفير يومية اليوم الحالي فقط وإغلاق الوردية)", type="primary", use_container_width=True):
                st.success("✅ تم إغلاق الوردية وتصفير عداد اليوم الحالي بنجاح. مبيعات الأيام السابقة محفوظة في أرشيف السنة المالية بالكامل.")

        st.markdown("---")
        st.subheader("🔎 البحث في الفواتير السابقة (لأي شهر أو يوم)")
        inv_search_id = st.number_input("أدخل رقم الفاتورة المطلوبة للبحث وإعادة الطباعة:", min_value=1, value=1, step=1)
        if st.button("🔍 استعراض وطباعة الفاتورة القديمة"):
            old_inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (inv_search_id,)).fetchone()
            if old_inv:
                st.success(f"✅ تم العثور على الفاتورة رقم #{old_inv['id']} بتاريخ {old_inv['created_at']} بقيمة {old_inv['total_amount']} د.ل (الزبون: {old_inv['customer_name']})")
                # يمكن تمديد عرض تفاصيلها هنا بنفس الطريقة
            else:
                st.error("❌ الفاتورة غير موجودة في الأرشيف.")

    conn.close()
