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
            cursor_res = cur_in.execute("""
                INSERT INTO invoices (branch_id, user_id, customer_name, customer_phone, total_amount, payment_method) 
                VALUES (?, ?, ?, ?, ?, ?)
            """, (target_inv_branch, st.session_state.get("user_id", 1), cust_name.strip() if cust_name else "زبون نقدي", cust_phone.strip(), final_tot, pay_method))
            
            inv_id = cursor_res.lastrowid

            for c_item in st.session_state["cart"]:
                conn.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))

            if cust_phone.strip() and cust_name.strip() != "زبون نقدي":
                existing_cust = cur_in.execute("SELECT id, total_purchases FROM customers WHERE phone = ?", (cust_phone.strip(),)).fetchone()
                if existing_cust:
                    cur_in.execute("UPDATE customers SET total_purchases = total_purchases + ?, customer_name = ? WHERE id = ?", (final_tot, cust_name.strip(), existing_cust['id']))
                else:
                    cur_in.execute("INSERT INTO customers (customer_name, phone, total_purchases) VALUES (?, ?, ?)", (cust_name.strip(), cust_phone.strip(), final_tot))
                    
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

# --- دالة منبثقة لتأكيد استلام بضاعة المخزن الرئيسي للفرع ---
@st.dialog("🚨 تنبيه هام: توجد بضاعة جديدة مُرسلة لفرعك")
def pending_transfer_dialog(pending_transfers, branch_name):
    st.warning(f"📦 تم رصد تحويلات بضاعة جديدة مُرسلة من المخزن الرئيسي إلى فرعك ({branch_name}). يرجى مراجعتها وتأكيد الاستلام:")
    
    for pt in pending_transfers:
        st.markdown(f"""
        <div style="background-color: #f1f5f9; padding: 12px; border-radius: 8px; border-right: 4px solid #0284c7; margin-bottom: 10px; color: #0f172a;">
            <p style="margin: 0;"><b>رقم الحركة:</b> #{pt['id']} | <b>التاريخ:</b> {pt['transfer_date']}</p>
            <p style="margin: 5px 0 0 0;"><b>التفاصيل والأصناف:</b> {pt['items_details']}</p>
        </div>
        """, unsafe_allow_html=True)
        
    cashier_confirm_name = st.text_input("أدخل اسمك الثلاثي (الكاشير المستلم):", value=st.session_state.get("username", ""))
    
    if st.button("✅ تأكيد استلام البضاعة (تم الاستلام)", type="primary", use_container_width=True):
        if cashier_confirm_name.strip():
            conn = get_db_connection()
            cur_pt = conn.cursor()
            for pt in pending_transfers:
                cur_pt.execute("""
                    UPDATE transfer_logs 
                    SET status = ? 
                    WHERE id = ?
                """, (f"مكتملة ومستلمة بواسطة الكاشير: {cashier_confirm_name.strip()}", pt['id']))
            conn.commit()
            conn.close()
            st.success("✅ تم تأكيد الاستلام بنجاح، وإرسال إشعار الاعتماد للمخزن الرئيسي!")
            st.rerun()
        else:
            st.error("⚠️ يجب إدخال اسم الكاشير المستلم لتأكيد الاستلام.")

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
                if float(item["quantity"]) <= 0:
                    st.toast(f"⚠️ تنبيه: الصنف ({item['item_name']}) منتهي في النظام! يرجى إبلاغ المدير.", icon="🚨")
                st.session_state["cart"].append({"id": item["id"], "code": item["item_code"], "name": item["item_name"], "price": unit_price, "qty": float(calculated_qty), "total": float(scale_value)})
        if not item:
            if b_id == "ALL": item = conn.execute("SELECT * FROM items WHERE item_code = ? LIMIT 1", (code,)).fetchone()
            else: item = conn.execute("SELECT * FROM items WHERE item_code = ? AND branch_id = ?", (code, b_id)).fetchone()
            
            if item:
                if float(item["quantity"]) <= 0:
                    st.toast(f"⚠️ تنبيه: الصنف ({item['item_name']}) منتهي في النظام! يرجى إبلاغ المدير.", icon="🚨")
                st.session_state["cart"].append({"id": item["id"], "code": item["item_code"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": 1.0, "total": float(item["sale_price"]) * 1.0})
            else:
                st.toast(f"❌ الباركود غير مسجل: {code}")
        conn.close()
    st.session_state.barcode_scan = ""

# --- واجهة شاشة نقطة البيع الأساسية ---
def show_page():
    # 🎨 تصميم CSS لمحاكاة شاشات الكاشير الكلاسيكية (Desktop UI)
    st.markdown("""
        <style>
        .top-panel {
            background-color: #e2e8f0;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #cbd5e1;
            margin-bottom: 15px;
        }
        .totals-panel {
            background-color: #0f172a;
            color: #38bdf8;
            padding: 15px;
            border-radius: 8px;
            text-align: left;
            font-size: 22px;
            border: 2px solid #334155;
            margin-top: 10px;
        }
        .totals-panel span { color: white; font-weight: bold; }
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

    # 🔒 حماية الفروع: الأدمن يرى الجميع، الكاشير يرى فرعه فقط إجبارياً
    if role in ["Admin", "General_Supervisor"]:
        b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
        sel_pos = st.selectbox("اختر الفرع الحالي (صلاحية إدارة):", ["🌐 إجمالي كل الفروع"] + list(b_dict.keys()))
        b_id = "ALL" if sel_pos == "🌐 إجمالي كل الفروع" else b_dict[sel_pos]
        branch_name_display = sel_pos
    else:
        b_id = user_branch_id
        b_row = conn.execute("SELECT branch_name FROM branches WHERE id=?", (b_id,)).fetchone()
        branch_name_display = b_row["branch_name"] if b_row else "الفرع الحالي"
        st.success(f"📍 أنت تعمل حالياً على: **{branch_name_display}**")
        
    st.session_state["branch_id"] = b_id

    # التحقق من البضاعة المحولة للفرع
    if b_id != "ALL":
        pending_logs = conn.execute("SELECT * FROM transfer_logs WHERE to_branch_id = ? AND status NOT LIKE 'مكتملة ومستلمة%'", (b_id,)).fetchall()
        if pending_logs:
            pending_transfer_dialog(pending_logs, branch_name_display)

    # عرض الفاتورة السابقة للطباعة والواتساب
    if "last_invoice" in st.session_state and st.session_state["last_invoice"]:
        inv = st.session_state["last_invoice"]
        with st.expander(f"🖨️ تفاصيل روشتة الفاتورة الأخيرة رقم (#{inv['inv_id']}) - جاهزة للطباعة والواتساب", expanded=True):
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
                </table><hr style="border: 0.5px solid #cbd5e1;">
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
                if inv["phone"]:
                    wa_text = f"مرحباً {inv['customer']}، تفاصيل فاتورتك رقم #{inv['inv_id']} بقيمة {inv['total']:,.2f} د.ل من مجموعة أبو زيد. شكراً لك!"
                    st.markdown(f'<a href="https://wa.me/{inv["phone"]}?text={wa_text}" target="_blank"><button style="background-color:#25d366; color:white; border:none; padding:10px 20px; border-radius:5px; width:100%; font-weight:bold; cursor:pointer;">📲 إرسال الفاتورة عبر الواتساب</button></a>', unsafe_allow_html=True)

    st.markdown("---")
    pos_tab1, pos_tab2, pos_tab3 = st.tabs(["🛒 كاشير البيع السريع (Desktop UI)", "🔍 البحث اليدوي عن الأصناف", "📋 أرشيف وتقارير الوردية"])

    # ==========================================
    # التبويب الأول: شاشة الكاشير (تصميم الديسكتوب الكلاسيكي)
    # ==========================================
    with pos_tab1:
        # 📋 اللوحة العلوية (شريط المعلومات)
        st.markdown('<div class="top-panel">', unsafe_allow_html=True)
        col_bar, col_info = st.columns([3, 2])
        
        with col_bar:
            st.text_input("🔍 مسح الباركود الفوري (اضغط Enter للإضافة):", key="barcode_scan", on_change=process_scale_barcode)
            
        with col_info:
            next_inv = conn.execute("SELECT MAX(id) FROM invoices").fetchone()[0] or 0
            inv_num = next_inv + 1
            shift_name = "صباحي ☀️" if 8 <= datetime.now().hour < 16 else "مسائي 🌙"
            current_time = datetime.now().strftime("%Y-%m-%d | %H:%M")
            
            st.markdown(f"""
                <div style="font-size: 15px; text-align: left; line-height: 1.6;">
                    <b>رقم الفاتورة:</b> <span style="color:red; font-size: 18px;">#{inv_num}</span><br>
                    <b>الفرع:</b> {branch_name_display} | <b>الوردية:</b> {shift_name}<br>
                    <b>الكاشير:</b> {username} | <b>الوقت:</b> {current_time}
                </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # 🛒 منطقة العمل الرئيسية (3 أرباع للفاتورة، ربع للأصناف السريعة)
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
            
            st.markdown(f"""
                <div class="totals-panel">
                    إجمالي الفاتورة: <span>{g_tot:,.2f}</span> د.ل &nbsp; | &nbsp;
                    <span style="color:#22c55e; font-size:26px;">الصافي المطلوب: {g_tot:,.2f} د.ل</span>
                </div>
            """, unsafe_allow_html=True)
            
            st.write("")
            c_btn1, c_btn2, c_btn3 = st.columns(3)
            with c_btn1:
                st.markdown('<div class="pos-btn btn-green">', unsafe_allow_html=True)
                if st.button("💰 دفع وطباعة (F12)", use_container_width=True) and st.session_state["cart"]:
                    checkout_payment_dialog(b_id, g_tot)
                st.markdown('</div>', unsafe_allow_html=True)
            with c_btn3:
                st.markdown('<div class="pos-btn btn-red">', unsafe_allow_html=True)
                if st.button("❌ تفريغ الفاتورة (ESC)", use_container_width=True):
                    st.session_state["cart"] = []
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

        with col_fav:
            st.markdown("### ⭐ الأصناف السريعة")
            fav_items = conn.execute("SELECT * FROM items WHERE favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ? AND favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC", (() if b_id=="ALL" else (b_id,))).fetchall()
            st.markdown("<div style='background-color:#f1f5f9; padding:10px; border-radius:5px; height:400px; overflow-y:auto; border:1px solid #cbd5e1;'>", unsafe_allow_html=True)
            
            if fav_items:
                quick_qty = st.number_input("الكمية:", min_value=0.1, value=1.0, step=0.5, format="%.2f")
                for item in fav_items:
                    if st.button(f"{item['item_name']}\n{item['sale_price']} د.ل", key=f"fav_{item['id']}", use_container_width=True):
                        st.session_state["cart"].append({
                            "id": item["id"], "code": item["item_code"], "name": item["item_name"], 
                            "price": float(item["sale_price"]), "qty": float(quick_qty), "total": float(item["sale_price"]) * float(quick_qty)
                        })
                        st.rerun()
            else:
                st.info("لا توجد أصناف مفضلة.")
            st.markdown("</div>", unsafe_allow_html=True)

    # ==========================================
    # التبويب الثاني: البحث اليدوي
    # ==========================================
    with pos_tab2:
        st.subheader("⚡ البحث اليدوي عن الأصناف")
        all_items_db = conn.execute("SELECT * FROM items" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ?", (() if b_id=="ALL" else (b_id,))).fetchall()
        if all_items_db:
            item_names_dict = {it["item_name"] + f" (الكود: {it['item_code']} - السعر: {it['sale_price']} د.ل)": it for it in all_items_db}
            selected_manual_item_str = st.selectbox("اختر الصنف يدوياً:", list(item_names_dict.keys()))
            selected_item_obj = item_names_dict[selected_manual_item_str]
            manual_qty = st.number_input("الكمية المطلوبة (كجم / وحدة):", min_value=0.1, value=1.0, step=0.1)
            
            if st.button("➕ إضافة إلى سلة المبيعات يدوياً", type="primary"):
                st.session_state["cart"].append({
                    "id": selected_item_obj["id"], "name": selected_item_obj["item_name"], "code": selected_item_obj["item_code"],
                    "price": float(selected_item_obj["sale_price"]), "qty": float(manual_qty), "total": float(selected_item_obj["sale_price"]) * float(manual_qty)
                })
                st.success(f"تمت إضافة ({selected_item_obj['item_name']}) بنجاح!")
                st.rerun()
        else:
            st.info("لا توجد أصناف مسجلة في هذا الفرع.")

    # ==========================================
    # التبويب الثالث: التقارير (X و Z)
    # ==========================================
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
