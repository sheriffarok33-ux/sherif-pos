import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
from database import get_db_connection

# --- تحديد رقم الوردية (الشفت) تلقائياً (1 للصَباحي، 2 للمسائي) ---
def get_current_shift_number():
    current_hour = datetime.now().hour
    if 6 <= current_hour < 16:
        return 1  # وردية 1 (صباحي)
    else:
        return 2  # وردية 2 (مسائي)

# --- دالة شاشة إتمام الدفع وإصدار الفاتورة ---
@st.dialog("💳 إتمام الدفع وإصدار الفاتورة")
def checkout_payment_dialog(b_id, g_tot, branch_name_str, cashier_name_str, shift_num, daily_inv_num):
    st.subheader(f"إجمالي الفاتورة المطلوب: {g_tot:,.2f} د.ل")
    cust_name = st.text_input("اسم الزبون (اختياري للعملاء العاديين):", value="زبون نقدي")
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
    pay_method = st.selectbox("نوع الدفع:", ["كاش (نقدي)", "شبكة / بطاقة", "آجل (على الحساب)", "خصم من حساب (مورد / زبون جملة)"])
    
    selected_account_id = None
    if pay_method in ["آجل (على الحساب)", "خصم من حساب (مورد / زبون جملة)"]:
        accounts = conn.execute("SELECT id, supplier_name, balance FROM suppliers").fetchall()
        if accounts:
            acc_opts = {f"{a['supplier_name']} (الرصيد الحالي: {a['balance']} د.ل)": a["id"] for a in accounts}
            sel_acc_str = st.selectbox("📌 اختر الحساب لترحيل/خصم المبلغ:", list(acc_opts.keys()))
            selected_account_id = acc_opts[sel_acc_str]
        else:
            st.error("⚠️ لا توجد جهات تعامل مسجلة!")
            st.stop()
            
    paid_amount = st.number_input("المبلغ المدفوع (د.ل):", min_value=0.0, value=float(final_tot), step=0.5, format="%.2f")
    change_due = paid_amount - final_tot
    
    if change_due >= 0: st.success(f"💵 الباقي المستحق للزبون: **{change_due:,.2f} د.ل**")
    else: st.error(f"⚠️ المبلغ غير كافٍ! العجز: **{abs(change_due):,.2f} د.ل**")
    
    if st.button("🖨️ تأكيد وإصدار الفاتورة", type="primary", use_container_width=True):
        if paid_amount >= final_tot or pay_method in ["آجل (على الحساب)", "خصم من حساب (مورد / زبون جملة)"]:
            cart_json = json.dumps(st.session_state["cart"], ensure_ascii=False)
            cur_in = conn.cursor()
            
            cursor_res = cur_in.execute("""
                INSERT INTO invoices (branch_id, user_id, customer_name, customer_phone, total_amount, payment_method, notes, shift_status) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (b_id, st.session_state.get("user_id", 1), cust_name.strip() if cust_name else "زبون نقدي", cust_phone.strip(), final_tot, pay_method, cart_json, str(shift_num)))
            inv_id = cursor_res.lastrowid

            for c_item in st.session_state["cart"]:
                if c_item.get("id") != 99999:
                    conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))

            if selected_account_id:
                conn.execute("UPDATE suppliers SET balance = balance - ? WHERE id = ?", (final_tot, selected_account_id))

            conn.commit()
            conn.close()

            st.session_state["last_invoice"] = {
                "inv_id": inv_id,
                "daily_inv_num": daily_inv_num,
                "branch": branch_name_str,
                "cashier": cashier_name_str,
                "shift": shift_num,
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

# --- معالجة الباركود ---
def process_barcode_scan():
    code = st.session_state.barcode_scan_input.strip()
    qty_to_add = st.session_state.get("barcode_qty_input", 1.0)
    
    if code:
        b_id = st.session_state.get("branch_id", "ALL")
        conn = get_db_connection()
        item = None
        
        if code.startswith("20") and len(code) >= 12:
            item_code = code[2:7]
            weight_value = float(code[7:12]) / 1000.0
            item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (item_code, b_id)).fetchone()
            if item: qty_to_add = weight_value 
                
        if not item:
            item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
            
        if item:
            unit_price = float(item["sale_price"])
            st.session_state["cart"].append({
                "id": item["id"], "code": item["item_code"], "name": item["item_name"], 
                "price": unit_price, "qty": float(qty_to_add), "total": unit_price * qty_to_add
            })
        else:
            st.toast(f"❌ الباركود غير مسجل أو الصنف غير موجود في هذا الفرع: {code}")
        conn.close()
    st.session_state.barcode_scan_input = "" 

# --- واجهة شاشة نقطة البيع الأساسية ---
def show_page():
    st.markdown("""
        <style>
        .top-panel { background-color: #e2e8f0; padding: 10px; border-radius: 8px; border: 1px solid #cbd5e1; margin-bottom: 10px; }
        .totals-panel { background-color: #0f172a; color: #ffffff !important; padding: 12px; border-radius: 8px; text-align: center; font-size: 19px; border: 2px solid #334155; margin-top: 8px; direction: ltr; }
        .btn-green > button { background-color: #16a34a !important; }
        .btn-red > button { background-color: #dc2626 !important; }
        </style>
    """, unsafe_allow_html=True)

    st.header("🛒 نقطة البيع (POS)")
    
    conn = get_db_connection()
    role = st.session_state.get("role", "")
    username = st.session_state.get("username", "")
    user_branch_id = st.session_state.get("branch_id")
    current_shift_num = get_current_shift_number()

    if role in ["Admin", "General_Supervisor"]:
        branches_data = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
        b_dict = {b["branch_name"]: b["id"] for b in branches_data}
        default_index = 0
        for idx, b in enumerate(branches_data):
            if b["branch_type"] == "مخزن":
                default_index = idx
                break
        sel_pos = st.selectbox("اختر الفرع الحالي للبيع:", list(b_dict.keys()), index=default_index)
        b_id = b_dict[sel_pos]
        branch_name_display = sel_pos
    else:
        b_id = user_branch_id
        b_row = conn.execute("SELECT branch_name FROM branches WHERE id=?", (b_id,)).fetchone()
        branch_name_display = b_row["branch_name"] if b_row else "الفرع الحالي"
        
    st.session_state["branch_id"] = b_id

    today_date = datetime.now().strftime("%Y-%m-%d")
    branch_inv_count = conn.execute("SELECT COUNT(*) FROM invoices WHERE branch_id = ? AND DATE(created_at) = ?", (b_id, today_date)).fetchone()[0]
    daily_inv_num = branch_inv_count + 1

    # عرض الفاتورة بعد الحفظ
    if "last_invoice" in st.session_state and st.session_state["last_invoice"]:
        inv = st.session_state["last_invoice"]
        items_html = "".join([f"<tr><td>{i['name']}</td><td>{i['qty']}</td><td>{i['price']}</td><td>{i['total']}</td></tr>" for i in inv["items"]])
        html_file_content = f"""
        <html dir="rtl">
        <head><meta charset="utf-8"></head>
        <body style="font-family: Arial; text-align: center; max-width: 350px; margin: auto; padding: 20px; border: 1px dashed #000;">
            <h2 style="margin-bottom: 5px;">مجموعة أبو زيد التجارية</h2>
            <p style="margin-top: 0;">فرع: {inv['branch']}</p><hr>
            <p style="text-align: right;">
            <b>رقم فاتورة اليوم:</b> #{inv['daily_inv_num']}<br>
            <b>التاريخ:</b> {inv['date_time']}<br>
            <b>الكاشير:</b> {inv['cashier']} | <b>وردية رقم:</b> {inv['shift']}<br>
            <b>الزبون:</b> {inv['customer']} <br><b>طريقة الدفع:</b> {inv['method']}</p><hr>
            <table style="width: 100%; text-align: right; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #000;"><th>الصنف</th><th>الكمية</th><th>السعر</th><th>المجموع</th></tr>
                {items_html}
            </table><hr>
            <h3 style="text-align: left;">الإجمالي: {inv['total']:,.2f} د.ل</h3>
            <p style="font-size: 12px; margin-top: 20px;">شكراً لتسوقكم معنا 🥜</p>
        </body>
        </html>
        """
        st.success("✅ تمت عملية الدفع بنجاح!")
        st.markdown("<div style='border: 2px solid #0284c7; padding: 15px; border-radius: 10px; background-color: #f0f9ff; margin-bottom: 20px;'>", unsafe_allow_html=True)
        st.components.v1.html(html_file_content, height=450, scrolling=True)
        c_inv1, c_inv2 = st.columns(2)
        with c_inv1: st.download_button("📥 تحميل الفاتورة (HTML)", data=html_file_content.encode('utf-8'), file_name=f"Invoice_{inv['inv_id']}.html", mime="text/html", use_container_width=True)
        with c_inv2: 
            if st.button("✖️ إخفاء الفاتورة ومتابعة البيع", type="primary", use_container_width=True): 
                st.session_state["last_invoice"] = None
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    if "pos_active_view" not in st.session_state: st.session_state["pos_active_view"] = "الكاشير السريع"
        
    st.markdown("---")
    t_col1, t_col2, t_col3 = st.columns(3)
    if t_col1.button("🛒 الكاشير السريع والباركود", use_container_width=True): st.session_state["pos_active_view"] = "الكاشير السريع"
    if t_col2.button("🔍 البحث اليدوي والصنف الحر", use_container_width=True): st.session_state["pos_active_view"] = "البحث اليدوي"
    if t_col3.button("📋 الأرشيف والتقارير", use_container_width=True): st.session_state["pos_active_view"] = "الأرشيف"
    st.markdown("---")

    # ==========================================
    # 1. شاشة الكاشير السريع
    # ==========================================
    if st.session_state["pos_active_view"] == "الكاشير السريع":
        st.markdown('<div class="top-panel">', unsafe_allow_html=True)
        col_qty, col_bar, col_info = st.columns([1, 2, 2])
        
        with col_qty:
            st.number_input("الكمية (كجم/وحدة):", min_value=0.01, value=1.00, step=0.5, key="barcode_qty_input")
        with col_bar:
            st.text_input("🔍 مسح الباركود الفوري (Enter):", key="barcode_scan_input", on_change=process_barcode_scan)
        with col_info:
            st.markdown(f"""
                <div style="font-size: 14px; text-align: left; line-height: 1.5;">
                    <b>رقم فاتورة اليوم:</b> <span style="color:red; font-size: 16px;">#{daily_inv_num}</span> | <b>الوردية:</b> <span style="color:blue;">رقم {current_shift_num}</span><br>
                    <b>الفرع:</b> {branch_name_display} | <b>الكاشير:</b> {username}
                </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # 🌟 جعل الجدول وشبكة الصور في الأعلى تماماً وبجانب بعضهما مباشرة
        col_grid, col_fav = st.columns([3, 1])
        
        with col_grid:
            if not st.session_state["cart"]:
                st.dataframe(pd.DataFrame(columns=["الكود", "اسم الصنف", "الكمية", "السعر", "الإجمالي"]), use_container_width=True, height=260)
            else:
                st.dataframe(pd.DataFrame([{"الكود": i.get("code", "-"), "اسم الصنف": i["name"], "الكمية": i["qty"], "السعر": i["price"], "الإجمالي": i["total"]} for i in st.session_state["cart"]]), use_container_width=True, height=260, hide_index=True)

            g_tot = sum(item["total"] for item in st.session_state.get("cart", []))
            st.markdown(f'<div class="totals-panel">الإجمالي: <b>{g_tot:,.2f} د.ل</b> &nbsp;|&nbsp; الصافي المطلوب: <span style="color:#22c55e;">{g_tot:,.2f} د.ل</span></div>', unsafe_allow_html=True)
            
            st.write("")
            c_btn1, c_btn3 = st.columns([2, 1])
            with c_btn1:
                st.markdown('<div class="pos-btn btn-green">', unsafe_allow_html=True)
                if st.button("💰 دفع واعتماد الفاتورة (F12)", use_container_width=True) and st.session_state["cart"]: 
                    checkout_payment_dialog(b_id, g_tot, branch_name_display, username, current_shift_num, daily_inv_num)
                st.markdown('</div>', unsafe_allow_html=True)
            with c_btn3:
                st.markdown('<div class="pos-btn btn-red">', unsafe_allow_html=True)
                if st.button("❌ تفريغ الفاتورة", use_container_width=True): 
                    st.session_state["cart"] = []
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

        # 🌟 قسم المفضلة والصور في الأعلى بجانب الجدول تماماً وبدون نزول للأسفل
        with col_fav:
            st.markdown("### ⭐ المفضلة")
            fav_items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND favorite_rank = 1 LIMIT 12", (b_id,)).fetchall()
            
            st.markdown("<div style='background-color:#f1f5f9; padding:6px; border-radius:8px; height:360px; overflow-y:auto; border:1px solid #cbd5e1;'>", unsafe_allow_html=True)
            if fav_items:
                for item in fav_items:
                    st.markdown("<div style='background:white; padding:4px; border-radius:6px; margin-bottom:6px; border:1px solid #e2e8f0; text-align:center;'>", unsafe_allow_html=True)
                    img_path = os.path.join("item_images", f"{item['item_code']}.jpg")
                    if os.path.exists(img_path):
                        try:
                            with open(img_path, "rb") as f:
                                img_bytes = f.read()
                            st.image(img_bytes, use_container_width=True)
                        except:
                            st.markdown("🥜")
                    else:
                        st.markdown("<div style='font-size:20px;'>🥜</div>", unsafe_allow_html=True)
                        
                    if st.button(f"{item['item_name']} ({item['sale_price']})", key=f"fav_{item['id']}", use_container_width=True):
                        qty = st.session_state.get("barcode_qty_input", 1.0)
                        st.session_state["cart"].append({"id": item["id"], "code": item["item_code"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": float(qty), "total": float(item["sale_price"]) * float(qty)})
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.info("لم تحدد أصناف مفضلة.")
            st.markdown("</div>", unsafe_allow_html=True)

    # ==========================================
    # 2. البحث اليدوي والصنف الحر
    # ==========================================
    elif st.session_state["pos_active_view"] == "البحث اليدوي":
        st.subheader("⚡ البحث اليدوي عن الأصناف")
        all_items_db = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
        if all_items_db:
            item_names_dict = {it["item_name"] + f" (الكود: {it['item_code']} - السعر: {it['sale_price']} د.ل)": it for it in all_items_db}
            selected_manual_item_str = st.selectbox("اختر الصنف يدوياً:", list(item_names_dict.keys()))
            selected_item_obj = item_names_dict[selected_manual_item_str]
            manual_qty = st.number_input("الكمية المطلوبة يدوياً:", min_value=0.01, value=1.0, step=0.1)
            
            if st.button("➕ إضافة إلى سلة المبيعات", type="primary"):
                st.session_state["cart"].append({"id": selected_item_obj["id"], "name": selected_item_obj["item_name"], "code": selected_item_obj["item_code"], "price": float(selected_item_obj["sale_price"]), "qty": float(manual_qty), "total": float(selected_item_obj["sale_price"]) * float(manual_qty)})
                st.success(f"تمت إضافة ({selected_item_obj['item_name']}) بنجاح!")
                
        st.markdown("---")
        st.subheader("🛒 بيع صنف حر (بدون كود)")
        col_f1, col_f2, col_f3 = st.columns(3)
        free_name = col_f1.text_input("اسم الصنف (اختياري):", value="صنف عام / خدمة")
        free_price = col_f2.number_input("السعر (د.ل):", min_value=0.0, step=1.0)
        free_qty = col_f3.number_input("الكمية (للصنف الحر):", min_value=0.01, value=1.0, step=1.0)
        
        if st.button("➕ إضافة الصنف الحر للفاتورة"):
            if free_price > 0:
                st.session_state["cart"].append({"id": 99999, "name": free_name, "code": "FREE", "price": float(free_price), "qty": float(free_qty), "total": float(free_price) * float(free_qty)})
                st.success("تم إضافة الصنف الحر بنجاح!")
            else: st.warning("يرجى إدخال سعر صحيح للصنف الحر.")

    # ==========================================
    # 3. الأرشيف وإعادة الطباعة
    # ==========================================
    elif st.session_state["pos_active_view"] == "الأرشيف":
        st.subheader("📋 أرشيف وإعادة الطباعة")
        recent_invs = conn.execute("SELECT id, customer_name, total_amount, created_at FROM invoices WHERE branch_id = ? ORDER BY id DESC LIMIT 100", (b_id,)).fetchall()
        
        if recent_invs:
            inv_dict = {f"فاتورة مرجعية #{r['id']} | الزبون: {r['customer_name']} | المبلغ: {r['total_amount']} د.ل | التاريخ: {r['created_at']}": r['id'] for r in recent_invs}
            sel_inv_str = st.selectbox("🔍 اختر الفاتورة لعرضها وإعادة طباعتها:", ["-- اختر الفاتورة --"] + list(inv_dict.keys()))
            
            if sel_inv_str != "-- اختر الفاتورة --":
                target_inv_id = inv_dict[sel_inv_str]
                inv_data = conn.execute("SELECT * FROM invoices WHERE id = ?", (target_inv_id,)).fetchone()
                
                if inv_data:
                    try: saved_items = json.loads(inv_data["notes"]) if inv_data["notes"] else []
                    except: saved_items = [{"name": "أصناف الفاتورة", "qty": "-", "price": "-", "total": inv_data["total_amount"]}]
                    
                    b_info = conn.execute("SELECT branch_name FROM branches WHERE id = ?", (inv_data["branch_id"],)).fetchone()
                    u_info = conn.execute("SELECT username FROM users WHERE id = ?", (inv_data["user_id"],)).fetchone()
                    
                    items_html_reprint = "".join([f"<tr><td>{i['name']}</td><td>{i['qty']}</td><td>{i['price']}</td><td>{i['total']}</td></tr>" for i in saved_items])
                    html_reprint_content = f"""
                    <html dir="rtl"><head><meta charset="utf-8"></head>
                    <body style="font-family: Arial; text-align: center; max-width: 350px; margin: auto; padding: 20px; border: 1px solid #000; background-color: #fdfdfd;">
                        <h2>مجموعة أبو زيد التجارية</h2><p>فرع: {b_info['branch_name'] if b_info else 'غير محدد'} <br><small>(نسخة مسترجعة)</small></p><hr>
                        <p style="text-align: right;"><b>رقم الفاتورة المرجعية:</b> #{inv_data['id']}<br><b>التاريخ:</b> {inv_data['created_at']}<br>
                        <b>الكاشير:</b> {u_info['username'] if u_info else 'غير محدد'}<br><b>الوردية:</b> رقم {inv_data['shift_status']}<br><b>طريقة الدفع:</b> {inv_data['payment_method']}</p><hr>
                        <table style="width: 100%; text-align: right; border-collapse: collapse;">
                            <tr style="border-bottom: 1px solid #000;"><th>الصنف</th><th>الكمية</th><th>السعر</th><th>المجموع</th></tr>
                            {items_html_reprint}
                        </table><hr><h3 style="text-align: left;">الإجمالي: {inv_data['total_amount']:,.2f} د.ل</h3>
                    </body></html>
                    """
                    st.components.v1.html(html_reprint_content, height=350, scrolling=True)
                    st.download_button(label="📥 تحميل الفاتورة المسترجعة (HTML)", data=html_reprint_content.encode('utf-8'), file_name=f"Invoice_Reprint_{target_inv_id}.html", mime="text/html", use_container_width=True)
        
        st.markdown("---")
        col_xz1, col_xz2 = st.columns(2)
        with col_xz1:
            if st.button("📊 تقرير X-Report (مبيعات اليوم للفرع)", use_container_width=True):
                shift_sales = conn.execute("SELECT SUM(total_amount) AS total, COUNT(*) as cnt FROM invoices WHERE DATE(created_at) = ? AND branch_id = ?", (today_date, b_id)).fetchone()
                st.info(f"📊 مبيعات اليوم لفرع ({branch_name_display}) = **{shift_sales['total'] or 0:,.2f} د.ل** عبر **{shift_sales['cnt']}** فاتورة.")
        with col_xz2:
            if st.button("🔄 تقرير Z-Report (إغلاق الوردية)", type="primary", use_container_width=True):
                st.success("✅ تم إغلاق الوردية بنجاح وتسجيل المبيعات في العهدة.")

    conn.close()
