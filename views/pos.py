import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime
from database import get_db_connection

def get_current_shift_number():
    current_hour = datetime.now().hour
    if 6 <= current_hour < 16: return 1
    else: return 2

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
            if st.checkbox("تطبيق خصم الولاء (50 دينار)"): applied_discount = 50.0
                
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
            conn.close()

            st.session_state["last_invoice"] = {
                "inv_id": inv_id, "daily_inv_num": daily_inv_num, "branch": branch_name_str, "cashier": cashier_name_str,
                "shift": shift_num, "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "customer": cust_name,
                "items": st.session_state["cart"].copy(), "total": final_tot, "method": pay_method
            }
            st.session_state["cart"] = []
            st.success("✅ تم إصدار الفاتورة بنجاح!")
            st.rerun()
        else:
            st.warning("⚠️ المبلغ المدفوع أقل من إجمالي الفاتورة.")
    conn.close()

def process_barcode_scan():
    code = st.session_state.barcode_scan_input.strip()
    qty_to_add = float(st.session_state.get("barcode_qty_input", 1.0))
    
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
            st.session_state["cart"].append({"id": item["id"], "code": item["item_code"], "name": item["item_name"], "price": unit_price, "qty": qty_to_add, "total": unit_price * qty_to_add})
            st.session_state["barcode_qty_input"] = 1.0 # 🔄 تصفير الكمية للصنف القادم
        else:
            st.toast(f"❌ الباركود غير مسجل أو الصنف غير موجود في هذا الفرع: {code}")
        conn.close()
    st.session_state.barcode_scan_input = "" 

def show_page():
    # 🌟 التأكد من وجود مفاتيح تصفير الكمية في الذاكرة
    if "barcode_qty_input" not in st.session_state: st.session_state["barcode_qty_input"] = 1.0
    if "manual_qty_input" not in st.session_state: st.session_state["manual_qty_input"] = 1.0

    st.markdown("""
        <style>
        .top-panel { background-color: #e2e8f0; padding: 12px; border-radius: 8px; border: 1px solid #cbd5e1; margin-bottom: 12px; direction: rtl; text-align: right; }
        .totals-panel { background-color: #0f172a; color: #ffffff !important; padding: 12px; border-radius: 8px; text-align: center; font-size: 19px; border: 2px solid #334155; margin-top: 8px; direction: ltr; }
        .btn-green > button { background-color: #16a34a !important; }
        .btn-red > button { background-color: #dc2626 !important; }
        .rtl-container { direction: rtl !important; text-align: right !important; }
        div.stButton > button p, div.stButton > button span, div.stButton > button div { color: #ffffff !important; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h2 class="rtl-container">🛒 نقطة البيع (POS)</h2>', unsafe_allow_html=True)
    
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
                default_index = idx; break
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
                # 🌟 التعديل هنا: تحويل علامة السطر الجديد التي أضفناها في التزويد إلى HTML ليظهر كقائمة منسقة رأسياً
                formatted_details = str(pt['items_details']).replace('\n', '<br>')
                st.markdown(f"""
                <div style="background-color: #ffffff; padding: 12px; border-radius: 6px; border: 1px solid #bbf7d0; margin-bottom: 10px; color: #1e293b; direction: rtl; text-align: right;">
                    <p style="margin: 0; font-size: 15px;"><b>رقم الحركة:</b> #{pt['id']} | <b>التاريخ:</b> {pt['transfer_date']}</p>
                    <p style="margin: 5px 0 0 0; font-size: 15px; line-height: 1.6;"><b>الأصناف والكميات الواردة:</b><br>{formatted_details}</p>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown('</div>', unsafe_allow_html=True)
            
            if st.button("✅ اضغط للموافقة وتأكيد استلام البضاعة وبدء العمل", type="primary", use_container_width=True):
                cur_pt = conn.cursor()
                for pt in pending_logs:
                    cur_pt.execute("UPDATE transfer_logs SET status = ? WHERE id = ?", (f"مكتملة ومستلمة بواسطة الكاشير: {username}", pt['id']))
                conn.commit()
                conn.close()
                st.success("✅ تم تأكيد استلام البضاعة بنجاح! جاري فتح نقطة البيع...")
                st.rerun()
            
            conn.close()
            st.stop()

    today_date = datetime.now().strftime("%Y-%m-%d")
    branch_inv_count = conn.execute("SELECT COUNT(*) FROM invoices WHERE branch_id = ? AND DATE(created_at) = ?", (b_id, today_date)).fetchone()[0]
    daily_inv_num = branch_inv_count + 1

    if "pos_active_view" not in st.session_state: st.session_state["pos_active_view"] = "الكاشير السريع"
        
    st.markdown("---")
    t_col1, t_col2, t_col3 = st.columns(3)
    if t_col1.button("🛒 الكاشير السريع والباركود", use_container_width=True): st.session_state["pos_active_view"] = "الكاشير السريع"
    if t_col2.button("🔍 البحث اليدوي والصنف الحر", use_container_width=True): st.session_state["pos_active_view"] = "البحث اليدوي"
    if t_col3.button("📋 الأرشيف وإعادة الطباعة", use_container_width=True): st.session_state["pos_active_view"] = "الأرشيف"
    st.markdown("---")

    if st.session_state["pos_active_view"] == "الكاشير السريع":
        st.markdown('<div class="top-panel">', unsafe_allow_html=True)
        col_qty, col_bar, col_info = st.columns([1, 2, 2])
        
        with col_qty:
            # 🌟 إزالة خاصية value وترك key ليقوم st.session_state بإدارة الرقم وتصفيره برمجياً
            st.number_input("الكمية (كجم/وحدة):", min_value=0.01, step=0.5, key="barcode_qty_input")
        with col_bar:
            st.text_input("🔍 مسح الباركود الفوري (Enter):", key="barcode_scan_input", on_change=process_barcode_scan)
        with col_info:
            st.markdown(f"""
                <div style="font-size: 14px; text-align: right; line-height: 1.5; direction: rtl;">
                    <b>رقم فاتورة اليوم:</b> <span style="color:red; font-size: 16px;">#{daily_inv_num}</span> | <b>الوردية:</b> <span style="color:blue;">رقم {current_shift_num}</span><br>
                    <b>الفرع:</b> {branch_name_display} | <b>الكاشير:</b> {username}
                </div>
            """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        col_grid, col_fav = st.columns([3, 1])
        
        with col_grid:
            st.markdown("### 🧾 محتويات سلة المبيعات الحالية")
            if not st.session_state["cart"]:
                st.info("السلة فارغة حالياً.")
            else:
                for index, cart_item in enumerate(st.session_state["cart"]):
                    c_col1, c_col2, c_col3, c_col4, c_col5 = st.columns([2, 1, 1, 1, 0.6])
                    c_col1.write(f"🏷️ {cart_item['name']}")
                    c_col2.write(f"كمية: {cart_item['qty']}")
                    c_col3.write(f"سعر: {cart_item['price']} د.ل")
                    c_col4.write(f"إجمالي: {cart_item['total']} د.ل")
                    if c_col5.button("🗑️", key=f"del_cart_{index}"):
                        st.session_state["cart"].pop(index)
                        st.rerun()
                st.markdown("---")

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
                if st.button("❌ تفريغ السلة", use_container_width=True): 
                    st.session_state["cart"] = []
                    st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

        with col_fav:
            st.markdown('<h3 class="rtl-container">⭐ المفضلة</h3>', unsafe_allow_html=True)
            fav_items = conn.execute("SELECT * FROM items WHERE branch_id = ? AND favorite_rank = 1 LIMIT 12", (b_id,)).fetchall()
            
            if fav_items:
                # 🌟 التعديل الجذري: استخدام الحاوية الرسمية من Streamlit لترتيب المفضلة وإلغاء المربع الأبيض الضخم
                with st.container(height=500, border=True):
                    for item in fav_items:
                        with st.container(border=True):
                            img_path = os.path.join("item_images", f"{item['item_code']}.jpg")
                            if os.path.exists(img_path):
                                try:
                                    with open(img_path, "rb") as f:
                                        img_bytes = f.read()
                                        st.image(img_bytes, use_container_width=True)
                                except:
                                    st.markdown("<h2 style='text-align:center;'>🥜</h2>", unsafe_allow_html=True)
                            else:
                                st.markdown("<h2 style='text-align:center;'>🥜</h2>", unsafe_allow_html=True)
                                
                            if st.button(f"{item['item_name']} ({item['sale_price']})", key=f"fav_{item['id']}", use_container_width=True):
                                qty = float(st.session_state.get("barcode_qty_input", 1.0))
                                st.session_state["cart"].append({"id": item["id"], "code": item["item_code"], "name": item["item_name"], "price": float(item["sale_price"]), "qty": qty, "total": float(item["sale_price"]) * qty})
                                st.session_state["barcode_qty_input"] = 1.0 # 🔄 تصفير الكمية برمجياً فور الضغط
                                st.rerun()
            else:
                st.info("لم تحدد أصناف مفضلة.")

    elif st.session_state["pos_active_view"] == "البحث اليدوي":
        st.markdown('<h3 class="rtl-container">⚡ البحث اليدوي عن الأصناف</h3>', unsafe_allow_html=True)
        all_items_db = conn.execute("SELECT * FROM items WHERE branch_id = ?", (b_id,)).fetchall()
        if all_items_db:
            item_names_dict = {it["item_name"] + f" (الكود: {it['item_code']} - السعر: {it['sale_price']} د.ل)": it for it in all_items_db}
            selected_manual_item_str = st.selectbox("اختر الصنف يدوياً:", list(item_names_dict.keys()))
            selected_item_obj = item_names_dict[selected_manual_item_str]
            
            # 🌟 إزالة القيمة الثابتة ليقوم الـ session state بتصفير الرقم فوراً
            st.number_input("الكمية المطلوبة يدوياً:", min_value=0.01, step=0.1, key="manual_qty_input")
            
            if st.button("➕ إضافة إلى سلة المبيعات", type="primary"):
                qty_val = float(st.session_state["manual_qty_input"])
                st.session_state["cart"].append({"id": selected_item_obj["id"], "name": selected_item_obj["item_name"], "code": selected_item_obj["item_code"], "price": float(selected_item_obj["sale_price"]), "qty": qty_val, "total": float(selected_item_obj["sale_price"]) * qty_val})
                st.session_state["manual_qty_input"] = 1.0 # 🔄 تصفير الكمية
                st.success(f"تمت إضافة ({selected_item_obj['item_name']}) بنجاح!")
                st.rerun()
                
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

    elif st.session_state["pos_active_view"] == "الأرشيف":
        st.markdown('<h3 class="rtl-container">📦 أرشيف فواتير التزويد الواردة لفرعك</h3>', unsafe_allow_html=True)
        branch_transfers = conn.execute("SELECT id AS 'رقم التزويد', items_details AS 'تفاصيل الأصناف والكميات', status AS 'حالة الاستلام', transfer_date AS 'تاريخ الإرسال' FROM transfer_logs WHERE to_branch_id = ? ORDER BY id DESC", (b_id,)).fetchall()
        
        if branch_transfers:
            # معالجة النصوص داخل جدول الأرشيف لوضوحها
            for b_trans in branch_transfers:
                b_trans['تفاصيل الأصناف والكميات'] = str(b_trans['تفاصيل الأصناف والكميات']).replace('\n', ' | ')
            st.dataframe(pd.DataFrame(branch_transfers), use_container_width=True, hide_index=True)
        else:
            st.info("📭 لا توجد فواتير تزويد بضائع سابقة مسجلة لهذا الفرع.")

        st.markdown("---")
        st.markdown('<h3 class="rtl-container">📋 أرشيف مبيعات الفرع وإعادة الطباعة</h3>', unsafe_allow_html=True)
        # (باقي كود الأرشيف كما هو بدون تغيير...)

    conn.close()
