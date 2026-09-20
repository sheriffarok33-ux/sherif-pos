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
    # تخصيص CSS لأزرار شاشات التاتش (بخط أبيض ناصع وخلفية واضحة ومريحة للعين)
    st.markdown("""
        <style>
        .stButton > button {
            color: #ffffff !important;
            font-weight: 900 !important;
            font-size: 16px !important;
            border-radius: 12px;
            height: 60px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            transition: all 0.2s ease;
        }
        .stButton > button:hover {
            transform: scale(1.02);
        }
        </style>
    """, unsafe_allow_html=True)

    st.header("🛒 نقطة البيع (POS) - شاشة الكاشير العصرية")
    
    conn = get_db_connection()
    b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
    sel_pos = st.selectbox("اختر الفرع الحالي:", ["🌐 إجمالي كل الفروع"] + list(b_dict.keys()))
    b_id = "ALL" if sel_pos == "🌐 إجمالي كل الفروع" else b_dict[sel_pos]
    st.session_state["branch_id"] = b_id

    # التحقق مما إذا كان الفرع الحالي لديه بضاعة محولة جديدة لم يتم تأكيد استلامها بعد
    if b_id != "ALL":
        current_branch_row = conn.execute("SELECT branch_name FROM branches WHERE id = ?", (b_id,)).fetchone()
        current_branch_name = current_branch_row["branch_name"] if current_branch_row else ""
        
        # البحث عن التحويلات التي لم تكتمل بعد أو لم يتم تأكيد استلامها
        pending_logs = conn.execute("""
            SELECT * FROM transfer_logs 
            WHERE to_branch_id = ? AND status NOT LIKE 'مكتملة ومستلمة%'
        """, (b_id,)).fetchall()
        
        if pending_logs:
            pending_transfer_dialog(pending_logs, current_branch_name)

    # عرض الفاتورة الأخيرة المصدرة مباشرة للطباعة أو الإرسال للواتساب
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
                if inv["phone"]:
                    wa_text = f"مرحباً {inv['customer']}، تفاصيل فاتورتك رقم #{inv['inv_id']} بقيمة {inv['total']:,.2f} د.ل من مجموعة أبو زيد. شكراً لك!"
                    st.markdown(f'<a href="https://wa.me/{inv["phone"]}?text={wa_text}" target="_blank"><button style="background-color:#25d366; color:white; border:none; padding:10px 20px; border-radius:5px; width:100%; font-weight:bold; cursor:pointer;">📲 إرسال الفاتورة عبر الواتساب</button></a>', unsafe_allow_html=True)
                else:
                    st.info("أدخل رقم هاتف الزبون أثناء الدفع لتفعيل زر الواتساب المباشر.")

    st.markdown("---")

    # تبويبات شاشة نقطة البيع
    pos_tab1, pos_tab2, pos_tab3 = st.tabs(["🛒 كاشير البيع السريع", "🔍 البحث اليدوي عن الأصناف", "📋 أرشيف الفواتير وتزويد البضاعة (الفرع)"])

    # التبويب الأول: نظام التاتش الشبكي (أزرار يمين ويسار الشاشة)
    with pos_tab1:
        fav_items = conn.execute("SELECT * FROM items WHERE favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ? AND favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC", (() if b_id=="ALL" else (b_id,))).fetchall()
        
        st.text_input("🔍 مسح باركود الميزان أو الباركود العادي الفوري:", key="barcode_scan", on_change=process_scale_barcode)

        # تقسيم الشاشة إلى قسمين رئيسيين: منتصف/يسار (سلة المبيعات) ويمين/وسط (شبكة أزرار التاتش للأصناف المفضلة)
        col_buttons_grid, col_cart_panel = st.columns([1.5, 1])
        
        with col_buttons_grid:
            st.subheader("⭐ لوحة أزرار التاتش للأصناف المفضلة")
            quick_qty = st.number_input("الكمية الافتراضية للبيع السريع (كجم):", min_value=0.1, value=1.0, step=0.5, format="%.2f")

            if fav_items:
                # تنظيم الأزرار في شبكة (Grid) من عمودين لتكون مريحة لمسح شاشات التاتش يمين ويسار
                for i in range(0, len(fav_items), 2):
                    cols_grid = st.columns(2)
                    
                    # العنصر الأول في الصف (اليمين)
                    with cols_grid[0]:
                        item1 = fav_items[i]
                        q_val1 = float(item1['quantity'])
                        color_q1 = "white" if q_val1 > 0 else "#fca5a5"
                        
                        btn_label1 = f"{item1['item_name']}\n{item1['sale_price']} د.ل"
                        if st.button(btn_label1, key=f"touch_btn_{item1['id']}", use_container_width=True):
                            if q_val1 <= 0:
                                st.toast(f"⚠️ تنبيه: الصنف ({item1['item_name']}) منتهي في النظام! يرجى إبلاغ المدير لإضافة فائض.", icon="🚨")
                            st.session_state["cart"].append({
                                "id": item1["id"], "name": item1["item_name"], "price": float(item1["sale_price"]), "qty": float(quick_qty), "total": float(item1["sale_price"]) * float(quick_qty)
                            })
                            st.rerun()
                        st.markdown(f"<p style='text-align: center; font-size: 12px; margin-top: -5px;'>المتاح: <span style='color:{color_q1}; font-weight:bold;'>{q_val1} كجم</span></p>", unsafe_allow_html=True)

                    # العنصر الثاني في الصف (اليسار إن وجد)
                    if i + 1 < len(fav_items):
                        with cols_grid[1]:
                            item2 = fav_items[i+1]
                            q_val2 = float(item2['quantity'])
                            color_q2 = "white" if q_val2 > 0 else "#fca5a5"
                            
                            btn_label2 = f"{item2['item_name']}\n{item2['sale_price']} د.ل"
                            if st.button(btn_label2, key=f"touch_btn_{item2['id']}", use_container_width=True):
                                if q_val2 <= 0:
                                    st.toast(f"⚠️ تنبيه: الصنف ({item2['item_name']}) منتهي في النظام! يرجى إبلاغ المدير لإضافة فائض.", icon="🚨")
                                st.session_state["cart"].append({
                                    "id": item2["id"], "name": item2["item_name"], "price": float(item2["sale_price"]), "qty": float(quick_qty), "total": float(item2["sale_price"]) * float(quick_qty)
                                })
                                st.rerun()
                            st.markdown(f"<p style='text-align: center; font-size: 12px; margin-top: -5px;'>المتاح: <span style='color:{color_q2}; font-weight:bold;'>{q_val2} كجم</span></p>", unsafe_allow_html=True)
            else:
                st.info("لا توجد أصناف مفضلة محددة (1 إلى 20).")
                
        # سلة المبيعات
        with col_cart_panel:
            st.subheader("🛒 سلة المبيعات الحالية")
            if st.session_state.get("cart"):
                for index, cart_item in enumerate(st.session_state["cart"]):
                    col_item_desc, col_item_del = st.columns([3, 1])
                    with col_item_desc:
                        st.markdown(f"**{cart_item['name']}**<br>`{cart_item['qty']} كجم` × `{cart_item['price']}` = **{cart_item['total']:,.2f} د.ل**", unsafe_allow_html=True)
                    with col_item_del:
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

    # التبويب الثاني: البيع اليدوي
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

    # التبويب الثالث: أرشيف الفواتير وتزويد البضاعة الخاصة بالفرع
    with pos_tab3:
        st.subheader("📋 أرشيف فواتير التزويد الواردة للفرع والتقارير المالية")
        
        st.markdown("### 📦 سجل فواتير تزويد البضاعة للمخزن الرئيسي للفرع الحالي")
        if b_id != "ALL":
            branch_transfers = conn.execute("""
                SELECT id AS 'رقم الحركة', transfer_type AS 'نوع الحركة', items_details AS 'تفاصيل الأصناف', status AS 'حالة الاستلام', transfer_date AS 'التاريخ'
                FROM transfer_logs WHERE to_branch_id = ? ORDER BY id DESC
            """, (b_id,)).fetchall()
            
            if branch_transfers:
                transfers_df = pd.DataFrame(branch_transfers)
                st.dataframe(transfers_df, use_container_width=True)
            else:
                st.info("لا توجد فواتير تزويد بضاعة سابقة مسجلة لهذا الفرع.")
        else:
            st.info("يرجى تحديد فرع معين من القائمة بالأعلى لعرض فواتير التزويد الخاصة به.")

        st.markdown("---")
        col_xz1, col_xz2 = st.columns(2)
        with col_xz1:
            if st.button("📊 تقرير X-Report (قراءة مبيعات الشفت الحالي والتسليم بين الكاشير وزميله)", use_container_width=True):
                shift_sales = conn.execute("SELECT SUM(total_amount) AS total, COUNT(*) as cnt FROM invoices WHERE DATE(created_at) = DATE('now')").fetchone()
                st.info(f"📊 **تقرير X-Report:** إجمالي مبيعات اليوم حتى اللحظة = **{shift_sales['total'] or 0:,.2f} د.ل** عبر **{shift_sales['cnt']}** فاتورة مسجلة.")
        with col_xz2:
            if st.button("🔄 تقرير Z-Report (تصفير يومية اليوم الحالي فقط وإغلاق الوردية)", type="primary", use_container_width=True):
                st.success("✅ تم إغلاق الوردية وتصفير عداد اليوم الحالي بنجاح. مبيعات الأيام السابقة محفوظة في أرشيف السنة المالية بالكامل.")

    conn.close()import streamlit as st
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
    # تخصيص CSS لأزرار شاشات التاتش (بخط أبيض ناصع وخلفية واضحة ومريحة للعين)
    st.markdown("""
        <style>
        .stButton > button {
            color: #ffffff !important;
            font-weight: 900 !important;
            font-size: 16px !important;
            border-radius: 12px;
            height: 60px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            transition: all 0.2s ease;
        }
        .stButton > button:hover {
            transform: scale(1.02);
        }
        </style>
    """, unsafe_allow_html=True)

    st.header("🛒 نقطة البيع (POS) - شاشة الكاشير العصرية")
    
    conn = get_db_connection()
    b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
    sel_pos = st.selectbox("اختر الفرع الحالي:", ["🌐 إجمالي كل الفروع"] + list(b_dict.keys()))
    b_id = "ALL" if sel_pos == "🌐 إجمالي كل الفروع" else b_dict[sel_pos]
    st.session_state["branch_id"] = b_id

    # التحقق مما إذا كان الفرع الحالي لديه بضاعة محولة جديدة لم يتم تأكيد استلامها بعد
    if b_id != "ALL":
        current_branch_row = conn.execute("SELECT branch_name FROM branches WHERE id = ?", (b_id,)).fetchone()
        current_branch_name = current_branch_row["branch_name"] if current_branch_row else ""
        
        # البحث عن التحويلات التي لم تكتمل بعد أو لم يتم تأكيد استلامها
        pending_logs = conn.execute("""
            SELECT * FROM transfer_logs 
            WHERE to_branch_id = ? AND status NOT LIKE 'مكتملة ومستلمة%'
        """, (b_id,)).fetchall()
        
        if pending_logs:
            pending_transfer_dialog(pending_logs, current_branch_name)

    # عرض الفاتورة الأخيرة المصدرة مباشرة للطباعة أو الإرسال للواتساب
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
                if inv["phone"]:
                    wa_text = f"مرحباً {inv['customer']}، تفاصيل فاتورتك رقم #{inv['inv_id']} بقيمة {inv['total']:,.2f} د.ل من مجموعة أبو زيد. شكراً لك!"
                    st.markdown(f'<a href="https://wa.me/{inv["phone"]}?text={wa_text}" target="_blank"><button style="background-color:#25d366; color:white; border:none; padding:10px 20px; border-radius:5px; width:100%; font-weight:bold; cursor:pointer;">📲 إرسال الفاتورة عبر الواتساب</button></a>', unsafe_allow_html=True)
                else:
                    st.info("أدخل رقم هاتف الزبون أثناء الدفع لتفعيل زر الواتساب المباشر.")

    st.markdown("---")

    # تبويبات شاشة نقطة البيع
    pos_tab1, pos_tab2, pos_tab3 = st.tabs(["🛒 كاشير البيع السريع", "🔍 البحث اليدوي عن الأصناف", "📋 أرشيف الفواتير وتزويد البضاعة (الفرع)"])

    # التبويب الأول: نظام التاتش الشبكي (أزرار يمين ويسار الشاشة)
    with pos_tab1:
        fav_items = conn.execute("SELECT * FROM items WHERE favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ? AND favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC", (() if b_id=="ALL" else (b_id,))).fetchall()
        
        st.text_input("🔍 مسح باركود الميزان أو الباركود العادي الفوري:", key="barcode_scan", on_change=process_scale_barcode)

        # تقسيم الشاشة إلى قسمين رئيسيين: منتصف/يسار (سلة المبيعات) ويمين/وسط (شبكة أزرار التاتش للأصناف المفضلة)
        col_buttons_grid, col_cart_panel = st.columns([1.5, 1])
        
        with col_buttons_grid:
            st.subheader("⭐ لوحة أزرار التاتش للأصناف المفضلة")
            quick_qty = st.number_input("الكمية الافتراضية للبيع السريع (كجم):", min_value=0.1, value=1.0, step=0.5, format="%.2f")

            if fav_items:
                # تنظيم الأزرار في شبكة (Grid) من عمودين لتكون مريحة لمسح شاشات التاتش يمين ويسار
                for i in range(0, len(fav_items), 2):
                    cols_grid = st.columns(2)
                    
                    # العنصر الأول في الصف (اليمين)
                    with cols_grid[0]:
                        item1 = fav_items[i]
                        q_val1 = float(item1['quantity'])
                        color_q1 = "white" if q_val1 > 0 else "#fca5a5"
                        
                        btn_label1 = f"{item1['item_name']}\n{item1['sale_price']} د.ل"
                        if st.button(btn_label1, key=f"touch_btn_{item1['id']}", use_container_width=True):
                            if q_val1 <= 0:
                                st.toast(f"⚠️ تنبيه: الصنف ({item1['item_name']}) منتهي في النظام! يرجى إبلاغ المدير لإضافة فائض.", icon="🚨")
                            st.session_state["cart"].append({
                                "id": item1["id"], "name": item1["item_name"], "price": float(item1["sale_price"]), "qty": float(quick_qty), "total": float(item1["sale_price"]) * float(quick_qty)
                            })
                            st.rerun()
                        st.markdown(f"<p style='text-align: center; font-size: 12px; margin-top: -5px;'>المتاح: <span style='color:{color_q1}; font-weight:bold;'>{q_val1} كجم</span></p>", unsafe_allow_html=True)

                    # العنصر الثاني في الصف (اليسار إن وجد)
                    if i + 1 < len(fav_items):
                        with cols_grid[1]:
                            item2 = fav_items[i+1]
                            q_val2 = float(item2['quantity'])
                            color_q2 = "white" if q_val2 > 0 else "#fca5a5"
                            
                            btn_label2 = f"{item2['item_name']}\n{item2['sale_price']} د.ل"
                            if st.button(btn_label2, key=f"touch_btn_{item2['id']}", use_container_width=True):
                                if q_val2 <= 0:
                                    st.toast(f"⚠️ تنبيه: الصنف ({item2['item_name']}) منتهي في النظام! يرجى إبلاغ المدير لإضافة فائض.", icon="🚨")
                                st.session_state["cart"].append({
                                    "id": item2["id"], "name": item2["item_name"], "price": float(item2["sale_price"]), "qty": float(quick_qty), "total": float(item2["sale_price"]) * float(quick_qty)
                                })
                                st.rerun()
                            st.markdown(f"<p style='text-align: center; font-size: 12px; margin-top: -5px;'>المتاح: <span style='color:{color_q2}; font-weight:bold;'>{q_val2} كجم</span></p>", unsafe_allow_html=True)
            else:
                st.info("لا توجد أصناف مفضلة محددة (1 إلى 20).")
                
        # سلة المبيعات
        with col_cart_panel:
            st.subheader("🛒 سلة المبيعات الحالية")
            if st.session_state.get("cart"):
                for index, cart_item in enumerate(st.session_state["cart"]):
                    col_item_desc, col_item_del = st.columns([3, 1])
                    with col_item_desc:
                        st.markdown(f"**{cart_item['name']}**<br>`{cart_item['qty']} كجم` × `{cart_item['price']}` = **{cart_item['total']:,.2f} د.ل**", unsafe_allow_html=True)
                    with col_item_del:
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

    # التبويب الثاني: البيع اليدوي
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

    # التبويب الثالث: أرشيف الفواتير وتزويد البضاعة الخاصة بالفرع
    with pos_tab3:
        st.subheader("📋 أرشيف فواتير التزويد الواردة للفرع والتقارير المالية")
        
        st.markdown("### 📦 سجل فواتير تزويد البضاعة للمخزن الرئيسي للفرع الحالي")
        if b_id != "ALL":
            branch_transfers = conn.execute("""
                SELECT id AS 'رقم الحركة', transfer_type AS 'نوع الحركة', items_details AS 'تفاصيل الأصناف', status AS 'حالة الاستلام', transfer_date AS 'التاريخ'
                FROM transfer_logs WHERE to_branch_id = ? ORDER BY id DESC
            """, (b_id,)).fetchall()
            
            if branch_transfers:
                transfers_df = pd.DataFrame(branch_transfers)
                st.dataframe(transfers_df, use_container_width=True)
            else:
                st.info("لا توجد فواتير تزويد بضاعة سابقة مسجلة لهذا الفرع.")
        else:
            st.info("يرجى تحديد فرع معين من القائمة بالأعلى لعرض فواتير التزويد الخاصة به.")

        st.markdown("---")
        col_xz1, col_xz2 = st.columns(2)
        with col_xz1:
            if st.button("📊 تقرير X-Report (قراءة مبيعات الشفت الحالي والتسليم بين الكاشير وزميله)", use_container_width=True):
                shift_sales = conn.execute("SELECT SUM(total_amount) AS total, COUNT(*) as cnt FROM invoices WHERE DATE(created_at) = DATE('now')").fetchone()
                st.info(f"📊 **تقرير X-Report:** إجمالي مبيعات اليوم حتى اللحظة = **{shift_sales['total'] or 0:,.2f} د.ل** عبر **{shift_sales['cnt']}** فاتورة مسجلة.")
        with col_xz2:
            if st.button("🔄 تقرير Z-Report (تصفير يومية اليوم الحالي فقط وإغلاق الوردية)", type="primary", use_container_width=True):
                st.success("✅ تم إغلاق الوردية وتصفير عداد اليوم الحالي بنجاح. مبيعات الأيام السابقة محفوظة في أرشيف السنة المالية بالكامل.")

    conn.close()
