import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
from database import get_db_connection
import streamlit.components.v1 as components

# --- تحديد رقم الوردية (الشفت) تلقائياً (1 للصَباحي، 2 للمسائي) ---
def get_current_shift_number():
    current_hour = datetime.now().hour
    if 6 <= current_hour < 16:
        return 1  # وردية 1 (صباحي)
    else:
        return 2  # وردية 2 (مسائي)

# --- دالة شاشة إضافة صنف غير موجود (صنف طارئ/حر داخل شاشة البيع) ---
@st.dialog("⚠️ صنف غير مسجل - إضافة سريعة")
def add_missing_item_dialog(scanned_code, b_id):
    st.warning(f"الكود ({scanned_code}) غير موجود في قاعدة بيانات هذا الفرع. يمكنك إضافته وتبيعه فوراً:")
    with st.form("quick_add_missing_item_form"):
        new_item_name = st.text_input("اسم الصنف:")
        col_q1, col_q2 = st.columns(2)
        with col_q1:
            new_item_qty = st.number_input("الكمية:", min_value=0.01, value=1.0, step=1.0)
        with col_q2:
            new_item_price = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=0.0, step=0.5)
            
        if st.form_submit_button("💾 إضافة للسلة ومتابعة البيع", type="primary"):
            if new_item_name.strip() and new_item_price > 0:
                conn_add = get_db_connection()
                cur_add = conn_add.cursor()
                cur_add.execute("""
                    INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (b_id, scanned_code, new_item_name.strip(), 0.0, 0.0, new_item_price))
                conn_add.commit()
                
                new_item_id = cur_add.lastrowid
                conn_add.close()
                
                st.session_state["cart"].append({
                    "id": new_item_id, 
                    "code": scanned_code, 
                    "name": new_item_name.strip(), 
                    "price": float(new_item_price), 
                    "qty": float(new_item_qty), 
                    "total": float(new_item_price) * float(new_item_qty)
                })
                st.success("✅ تمت إضافة الصنف بنجاح!")
                st.rerun()
            else:
                st.error("⚠️ يرجى إدخال اسم الصنف وسعر بيع صحيح.")

# --- دالة شاشة إتمام الدفع وإصدار الفاتورة مع الدعم للعمل دون إنترنت ---
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
        accounts = conn.execute("SELECT id, customer_name, balance FROM customers").fetchall()
        if accounts:
            acc_opts = {f"{a['customer_name']} (الرصيد/المديونية: {a['balance']} د.ل)": a["id"] for a in accounts}
            sel_acc_str = st.selectbox("📌 اختر الزبون الآجل لتسجيل المديونية عليه:", list(acc_opts.keys()))
            selected_account_id = acc_opts[sel_acc_str]
        else:
            st.error("⚠️ لا توجد زبائن آجلين مسجلين في النظام!")
            st.stop()
            
    paid_amount = st.number_input("المبلغ المدفوع (د.ل):", min_value=0.0, value=float(final_tot), step=0.5, format="%.2f")
    change_due = paid_amount - final_tot
    
    if change_due >= 0: st.success(f"💵 الباقي المستحق للزبون: **{change_due:,.2f} د.ل**")
    else: st.error(f"⚠️ المبلغ غير كافٍ! العجز: **{abs(change_due):,.2f} د.ل**")
    
    if st.button("🖨️ تأكيد وإصدار الفاتورة", type="primary", use_container_width=True):
        if paid_amount >= final_tot or pay_method in ["آجل (على الحساب)", "خصم من حساب (مورد / زبون جملة)"]:
            cart_json = json.dumps(st.session_state["cart"], ensure_ascii=False)
            
            try:
                cur_in = conn.cursor()
                cursor_res = cur_in.execute("""
                    INSERT INTO invoices (branch_id, user_id, customer_name, customer_phone, total_amount, payment_method, notes, shift_status) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (b_id, st.session_state.get("user_id", 1), cust_name.strip() if cust_name else "زبون نقدي", cust_phone.strip(), final_tot, pay_method, cart_json, str(shift_num)))
                inv_id = cursor_res.lastrowid

                for c_item in st.session_state["cart"]:
                    if c_item.get("id") != 99999:
                        conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))

                if selected_account_id and pay_method in ["آجل (على الحساب)", "خصم من حساب (مورد / زبون جملة)"]:
                    conn.execute("UPDATE customers SET balance = balance + ?, total_purchases = total_purchases + ? WHERE id = ?", (final_tot, final_tot, selected_account_id))

                conn.commit()
            except Exception as db_err:
                # 🌐 في حال انقطاع الإنترنت أو فشل الاتصال بالسيرفر، يتم الحفظ احتياطياً في متصفح الكاشير محلياً
                cart_safe_json = json.dumps(st.session_state["cart"], ensure_ascii=False)
                offline_backup_script = f"""
                <script>
                    try {{
                        let pending = JSON.parse(localStorage.getItem('pending_invoices') || '[]');
                        pending.push({{
                            branch_id: {b_id},
                            user_id: {st.session_state.get("user_id", 1)},
                            customer_name: "{cust_name.strip() if cust_name else 'زبون نقدي'}",
                            customer_phone: "{cust_phone.strip()}",
                            total: {final_tot},
                            method: "{pay_method}",
                            items: {cart_safe_json},
                            shift: "{shift_num}",
                            timestamp: new Date().toISOString()
                        }});
                        localStorage.setItem('pending_invoices', JSON.stringify(pending));
                        console.log("تم حفظ الفاتورة محلياً لحين عودة الاتصال بالمخزن السحابي");
                        alert("⚠️ انقطع الاتصال بالسيرفر! تم حفظ الفاتورة محلياً وسيتم مزامنتها تلقائياً عند عودة الإنترنت.");
                    } catch (e) {{
                        console.error("خطأ في التخزين المحلي:", e);
                    }}
                </script>
                """
                components.html(offline_backup_script, height=0, width=0)
                st.warning("⚠️ انقطع الاتصال بالسيرفر السحابي، وتم تأمين الفاتورة في التخزين المحلي المؤقت لجهاز الكاشير.")
            
            conn.close()

            st.session_state["last_invoice"] = {
                "inv_id": locals().get("inv_id", 999),
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
            st.success("✅ تمت عملية إصدار الفاتورة بنجاح!")
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
            conn.close()
            add_missing_item_dialog(code, b_id)
            return
            
        conn.close()
    st.session_state.barcode_scan_input = "" 

# --- واجهة شاشة نقطة البيع الأساسية ---
def show_page():
    st.markdown("""
        <style>
        .top-panel { background-color: #e2e8f0; padding: 12px; border-radius: 8px; border: 1px solid #cbd5e1; margin-bottom: 12px; direction: rtl; text-align: right; }
        .totals-panel { background-color: #0f172a; color: #ffffff !important; padding: 12px; border-radius: 8px; text-align: center; font-size: 19px; border: 2px solid #334155; margin-top: 8px; direction: ltr; }
        .btn-green > button { background-color: #16a34a !important; }
        .btn-red > button { background-color: #dc2626 !important; }
        .rtl-container { direction: rtl !important; text-align: right !important; }
        
        div.stButton > button p, div.stButton > button span, div.stButton > button div {
            color: #ffffff !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h2 class="rtl-container">🛒 نقطة البيع (POS)</h2>', unsafe_allow_html=True)
    
    conn = get_db_connection()
    role = st.session_state.get("role", "")
    username = st.session_state.get("username", "")
    user_branch_id = st.session_state.get("branch_id")
    current_shift_number = get_current_shift_number()

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

    if b_id and b_id != "ALL":
        pending_logs = conn.execute("SELECT * FROM transfer_logs WHERE (to_branch_id = ? OR to_branch_id IN (SELECT id FROM branches WHERE branch_name LIKE '%مصراتة%' OR id = ?)) AND status NOT LIKE 'مكتملة ومستلمة%'", (b_id, b_id)).fetchall()
        if pending_logs:
            st.markdown(f"""
                <div style="background-color: #f0fdf4; padding: 20px; border-radius: 10px; border: 2px solid #22c55e; margin-bottom: 20px; color: #166534; direction: rtl; text-align: right;">
                    <h3 style="margin-top:0; color:#16a34a;">👋 مرحباً بك يا {username}</h3>
                    <p style="font-size: 17px; font-weight: bold;">📦 لقد تم تزويد فرعك ({branch_name_display}) بفاتورة بضاعة جديدة.</p>
            """, unsafe_allow_html=True)
            
            for pt in pending_logs:
                st.markdown(f"""
                <div style="background-color: #ffffff; padding: 12px; border-radius: 6px; border: 1px solid #bbf7d0; margin-bottom: 10px; color: #1e293b; direction: rtl; text-align: right;">
                    <p style="margin: 0; font-size: 15px;"><b>رقم الحركة:</b> #{pt['id']} | <b>التاريخ:</b> {pt['transfer_date']}</p>
                    <p style="margin: 5px 0 0 0; font-size: 15px;"><b>الأصناف والكميات الواردة:</b> {pt['items_details']}</p>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown('</div>', unsafe_allow_html=True)
            
            if st.button("✅ اضغط للموافقة وتأكيد استلام البضاعة وبدء العمل", type="primary", use_container_width=True):
                cur_pt = conn.cursor()
                for pt in pending_logs:
                    cur_pt.execute("""
                        UPDATE transfer_logs 
                        SET status = ? 
                        WHERE id = ?
                    """, (f"مكتملة ومستلمة بواسطة الكاشير: {username}", pt['id']))
                conn.commit()
                conn.close()
                st.success("✅ تم تأكيد استلام البضاعة بنجاح! جاري فتح نقطة البيع...")
                st.rerun()
            
            conn.close()
            st.stop()

    today_date = datetime.now().strftime("%Y-%m-%d")
    branch_inv_count = conn.execute("SELECT COUNT(*) FROM invoices WHERE branch_id = ? AND DATE(created_at) = ?", (b_id, today_date)).fetchone()[0]
    daily_inv_num = branch_inv_count + 1

    # --- قسم تقارير الإغلاق المالي وتسليم الورديات ---
    if role in ["Admin", "General_Supervisor", "Branch_Supervisor"]:
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align: center; color: #0f172a; font-weight: 900;'>📊 تقارير الإغلاق المالي وتسليم الورديات</h3>", unsafe_allow_html=True)
        
        c_x, c_z = st.columns(2)
        
        with c_x:
            st.markdown("<div style='background: #f1f5f9; padding: 15px; border-radius: 8px; border: 1px solid #cbd5e1;'>", unsafe_allow_html=True)
            st.markdown("#### 🕒 تقرير الوردية الحالية")
            shift_sales_row = conn.execute("""
                SELECT SUM(total_amount) FROM invoices 
                WHERE branch_id = ? AND DATE(created_at) = ? AND shift_status = ?
            """, (b_id, today_date, str(current_shift_number))).fetchone()
            shift_sales = shift_sales_row[0] if shift_sales_row and shift_sales_row[0] else 0.0
            
            st.info(f"مبيعات الوردية الحالية (رقم {current_shift_number}): **{shift_sales:,.2f} د.ل**")
            x_html = f"""
            <html dir="rtl"><head><meta charset="utf-8"></head>
            <body style="font-family: Arial; text-align: center; max-width: 350px; margin: auto; padding: 20px; border: 1px dashed #000;">
                <h2>مجموعة أبو زيد التجارية</h2><p>فرع: {branch_name_display}</p><hr>
                <h3>تقرير تسليم الوردية</h3>
                <p style="text-align: right;"><b>التاريخ والوقت:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>
                <b>الكاشير:</b> {username} | <b>وردية رقم:</b> {current_shift_number}</p><hr>
                <h3>إجمالي مبيعات الوردية: {shift_sales:,.2f} د.ل</h3><hr>
                <p style="font-size: 12px;">نهاية التقرير التشغيلي</p>
            </body></html>
            """
            st.download_button("🖨️ طباعة تقرير الوردية", data=x_html.encode('utf-8'), file_name=f"X_Read_{today_date}_Shift{current_shift_number}.html", mime="text/html", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with c_z:
            st.markdown("<div style='background: #f1f5f9; padding: 15px; border-radius: 8px; border: 1px solid #cbd5e1;'>", unsafe_allow_html=True)
            st.markdown("#### 🔒 تقرير الإغلاق المالي اليومي")
            day_sales_row = conn.execute("SELECT SUM(total_amount) FROM invoices WHERE branch_id = ? AND DATE(created_at) = ? AND shift_status != 'Z_Closed'", (b_id, today_date)).fetchone()
            day_sales = day_sales_row[0] if day_sales_row and day_sales_row[0] else 0.0
            
            prev_sales_row = conn.execute("SELECT SUM(total_amount) FROM invoices WHERE branch_id = ? AND (DATE(created_at) < ? OR shift_status = 'Z_Closed')", (b_id, today_date)).fetchone()
            cumulative_prev_sales = prev_sales_row[0] if prev_sales_row and prev_sales_row[0] else 0.0
            total_all_sales = day_sales + cumulative_prev_sales
            
            st.error(f"مبيعات اليوم: **{day_sales:,.2f} د.ل** | التراكمي السابق: **{cumulative_prev_sales:,.2f} د.ل**")
            z_html = f"""
            <html dir="rtl"><head><meta charset="utf-8"></head>
            <body style="font-family: Arial; text-align: center; max-width: 350px; margin: auto; padding: 20px; border: 1px dashed #000;">
                <h2>مجموعة أبو زيد التجارية</h2><p>فرع: {branch_name_display}</p><hr>
                <h3>تقرير الإغلاق المالي اليومي</h3>
                <p style="text-align: right;"><b>التاريخ والوقت:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>
                <b>بواسطة المشرف:</b> {username}</p><hr>
                <p style="text-align: right;"><b>مبيعات اليوم الحالي:</b> {day_sales:,.2f} د.ل<br><b>إجمالي الأيام السابقة (التراكمي):</b> {cumulative_prev_sales:,.2f} د.ل</p><hr>
                <h3>الإجمالي الكلي التراكمي: {total_all_sales:,.2f} د.ل</h3><hr>
                <p style="font-size: 12px;">تم الإغلاق المالي بنجاح</p>
            </body></html>
            """
            st.download_button("🖨️ طباعة تقرير الإغلاق الشامل", data=z_html.encode('utf-8'), file_name=f"Z_Read_{today_date}.html", mime="text/html", use_container_width=True)

            if st.button("⚙️ تنفيذ الإغلاق المالي وتصفير يومية الفرع", type="primary"):
                conn.execute("UPDATE invoices SET shift_status = 'Z_Closed' WHERE branch_id = ? AND DATE(created_at) = ?", (b_id, today_date))
                conn.commit()
                st.success("✅ تم تصفير مبيعات اليوم وترحيل المجموع للتراكمي بنجاح!")
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<hr>", unsafe_allow_html=True)

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
        st.markdown("<div style='border: 2px solid #0284c7; padding: 15px; border-radius: 10px; background-color: #f0f9ff; margin-bottom: 20px; direction: rtl;'>", unsafe_allow_html=True)
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
    if t_col3.button("📋 الأرشيف وإعادة الطباعة", use_container_width=True): st.session_state["pos_active_view"] = "الأرشيف"
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
                <div style="font-size: 14px; text-align: right; line-height: 1.5; direction: rtl;">
                    <b>رقم فاتورة اليوم:</b> <span style="color:red; font-size: 16px;">#{daily_inv_num}</span> | <b>الوردية:</b> <span style="color:blue;">رقم {current_shift_number}</span><br>
                    <b>الفرع:</b> {branch_name_display} | <b>الكاشير:</b> {username}
                </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        col_grid, col_fav = st.columns([3, 1])
        
        with col_grid:
            st.markdown("### 🧾 محتويات سلة المبيعات الحالية")
            
            cart_items_list = st.session_state.get("cart", [])
            total_cart_qty = sum(item["qty"] for item in cart_items_list)
            total_cart_val = sum(item["total"] for item in cart_items_list)
            
            stat_c1, stat_c2 = st.columns(2)
            with stat_c1:
                st.metric(label="📦 إجمالي الكمية بالسلة", value=f"{total_cart_qty:,.2f}")
            with stat_c2:
                st.metric(label="💰 إجمالي قيمة الفاتورة", value=f"{total_cart_val:,.2f} د.ل")
            st.markdown("---")

            if not cart_items_list:
                st.info("السلة فارغة حالياً.")
            else:
                for index, cart_item in enumerate(cart_items_list):
                    c_col1, c_col2, c_col3, c_col4, c_col5 = st.columns([2, 1, 1, 1, 0.6])
                    c_col1.write(f"🏷️ {cart_item['name']}")
                    c_col2.write(f"كمية: {cart_item['qty']}")
                    c_col3.write(f"سعر: {cart_item['price']} د.ل")
                    c_col4.write(f"إجمالي: {cart_item['total']} د.ل")
                    if c_col5.button("🗑️", key=f"del_cart_{index}", help="حذف هذا الصنف فقط"):
                        st.session_state["cart"].pop(index)
                        st.rerun()
                st.markdown("---")

            g_tot = total_cart_val
            st.markdown(f'<div class="totals-panel">الإجمالي: <b>{g_tot:,.2f} د.ل</b> &nbsp;|&nbsp; الصافي المطلوب: <span style="color:#22c55e;">{g_tot:,.2f} د.ل</span></div>', unsafe_allow_html=True)
            
            st.write("")
            c_btn1, c_btn3 = st.columns([2, 1])
            with c_btn1:
                st.markdown('<div class="pos-btn btn-green">', unsafe_allow_html=True)
                if st.button("💰 دفع واعتماد الفاتورة (F12)", use_container_width=True) and st.session_state["cart"]: 
                    checkout_payment_dialog(b_id, g_tot, branch_name_display, username, current_shift_number, daily_inv_num)
                st.markdown('</div>', unsafe_allow_html=True)
            with c_btn3:
                st.markdown('<div class="pos-btn btn-red">', unsafe_allow_html=True)
                if st.button("❌ تفريغ السلة بالكامل", use_container_width=True): 
                    st.session_state["cart"] = []
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

        with col_fav:
            st.markdown('<h3 class="rtl-container">⭐ المفضلة</h3>', unsafe_allow_html=True)
            fav_items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND favorite_rank = 1 LIMIT 12", (b_id,)).fetchall()
            
            st.markdown("<div style='background-color:#f1f5f9; padding:6px; border-radius:8px; height:360px; overflow-y:auto; border:1px solid #cbd5e1; direction: rtl;'>", unsafe_allow_html=True)
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
        st.markdown('<h3 class="rtl-container">⚡ البحث اليدوي عن الأصناف</h3>', unsafe_allow_html=True)
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
        st.markdown('<h3 class="rtl-container">🛒 بيع صنف حر (بدون كود)</h3>', unsafe_allow_html=True)
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
        st.markdown('<h3 class="rtl-container">📦 أرشيف فواتير التزويد الواردة لفرعك</h3>', unsafe_allow_html=True)
        branch_transfers = conn.execute("""
            SELECT id AS 'رقم التزويد', items_details AS 'تفاصيل الأصناف والكميات', status AS 'حالة الاستلام', transfer_date AS 'تاريخ الإرسال'
            FROM transfer_logs WHERE to_branch_id = ? ORDER BY id DESC
        """, (b_id,)).fetchall()
        
        if branch_transfers:
            trans_dict = {f"فاتورة تزويد #{r['رقم التزويد']} | التاريخ: {r['تاريخ الإرسال']} | الحالة: {r['حالة الاستلام']}": r for r in branch_transfers}
            sel_trans_str = st.selectbox("🔍 اختر فاتورة التزويد الواردة لعرضها وإعادة طباعتها:", ["-- اختر فاتورة التزويد --"] + list(trans_dict.keys()))
            
            if sel_trans_str != "-- اختر فاتورة التزويد --":
                trans_data = trans_dict[sel_trans_str]
                branch_columns = [col[1] for col in conn.execute("PRAGMA table_info(branches)").fetchall()]
                has_phone_col = "phone" in branch_columns
                b_info = conn.execute(f"SELECT branch_name {', phone' if has_phone_col else ''} FROM branches WHERE id = ?", (b_id,)).fetchone()
                b_phone_rep = b_info.get('phone', 'غير متوفر') if has_phone_col and b_info else 'غير متوفر'
                
                items_text = trans_data['تفاصيل الأصناف والكميات']
                items_html_reprint = ""
                notes_reprint = ""
                
                delim = '\n' if '\n' in items_text else (' | ' if ' | ' in items_text else ' - ')
                for line in items_text.split(delim):
                    line = line.strip()
                    if not line: continue
                    if "ملاحظات:" in line:
                        notes_reprint = line.replace("ملاحظات:", "").strip()
                    else:
                        if '(' in line and ')' in line:
                            name_part = line[:line.rfind('(')].replace('▪', '').replace('-', '').strip()
                            qty_part = line[line.rfind('(')+1:line.rfind(')')].replace('الكمية:', '').replace('كجم', '').strip()
                            items_html_reprint += f"<tr><td>{name_part}</td><td>{qty_part}</td></tr>"
                        else:
                            items_html_reprint += f"<tr><td colspan='2'>{line.replace('▪', '').replace('-', '').strip()}</td></tr>"
                
                notes_html_rep = f"<p style='text-align: right; font-size: 14px;'><b>ملاحظات:</b> {notes_reprint}</p>" if notes_reprint else ""
                
                trans_html_content = f"""
                <html dir="rtl"><head><meta charset="utf-8"></head>
                <body style="font-family: Arial; text-align: center; max-width: 350px; margin: auto; padding: 20px; border: 1px solid #000; background-color: #fdfdfd;">
                    <h2>مجموعة أبو زيد التجارية</h2>
                    <p style="margin-top: 0; font-weight: bold; background-color: #e2e8f0; padding: 5px;">فاتورة تزويد واردة للفرع</p><hr>
                    <p style="text-align: right;">
                    <b>فرع الاستلام:</b> {b_info['branch_name'] if b_info else 'غير محدد'} | هاتف: {b_phone_rep}<br>
                    <b>رقم حركة التزويد:</b> #{trans_data['رقم التزويد']}<br>
                    <b>التاريخ:</b> {trans_data['تاريخ الإرسال']}<br>
                    <b>المرسل:</b> المخزن الرئيسي<br>
                    <b>حالة الاستلام:</b> {trans_data['حالة الاستلام']}</p><hr>
                    <table style="width: 100%; text-align: right; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #000; background-color: #f1f5f9;"><th>الصنف</th><th>الكمية الواردة</th></tr>
                        {items_html_reprint}
                    </table><hr>
                    {notes_html_rep}
                    <p style="font-size: 12px; margin-top: 20px;">الرجاء مراجعة الكميات، توقيع المستلم: ........................</p>
                </body></html>
                """
                st.components.v1.html(trans_html_content, height=450, scrolling=True)
                st.download_button(label="📥 تحميل فاتورة التزويد (HTML)", data=trans_html_content.encode('utf-8'), file_name=f"Transfer_Invoice_Inbound_{trans_data['رقم التزويد']}.html", mime="text/html", use_container_width=True)
        else:
            st.info("📭 لا توجد فواتير تزويد بضائع سابقة مسجلة لهذا الفرع.")

        st.markdown("---")
        st.markdown('<h3 class="rtl-container">📋 أرشيف مبيعات الفرع وإعادة الطباعة</h3>', unsafe_allow_html=True)
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
        else:
            st.info("📭 لا توجد فواتير مبيعات سابقة مؤرشفة لهذا الفرع.")

    conn.close()
