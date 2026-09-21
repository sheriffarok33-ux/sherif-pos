import streamlit as st
import pandas as pd
from datetime import datetime
from database import get_db_connection

def show_page():
    st.header("📥 إدارة المشتريات وإدخال البضاعة للمخازن")
    
    conn = get_db_connection()
    b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
    
    # 🌟 زر سريع لإضافة مورد جديد مباشرة داخل شاشة المشتريات لكي لا يضطر المستخدم للخروج منها
    with st.expander("➕ إضافة مورد (تاجر) جديد سريعاً"):
        with st.form("quick_add_supplier_form_in_purchases", clear_on_submit=True):
            col_q1, col_q2 = st.columns(2)
            new_sup_name = col_q1.text_input("اسم المورد / الشركة الجديد:")
            new_sup_phone = col_q2.text_input("رقم الهاتف:")
            
            if st.form_submit_button("💾 حفظ المورد الجديد", type="primary"):
                if new_sup_name.strip():
                    try:
                        conn.execute("INSERT INTO suppliers (supplier_name, phone, balance) VALUES (?, ?, 0.0)", 
                                     (new_sup_name.strip(), new_sup_phone.strip()))
                        conn.commit()
                        st.success(f"✅ تمت إضافة المورد ({new_sup_name}) بنجاح!")
                        st.rerun()
                    except Exception as e:
                        st.error("⚠️ حدث خطأ، ربما اسم المورد موجود مسبقاً.")
                else:
                    st.warning("⚠️ يرجى إدخال اسم المورد على الأقل.")

    st.markdown("---")

    # جلب بيانات الموردين بعد التحديث
    suppliers_data = conn.execute("SELECT id, supplier_name, balance FROM suppliers").fetchall()
    s_dict = {s["supplier_name"]: s["id"] for s in suppliers_data}
    s_balance_dict = {s["supplier_name"]: float(s["balance"]) for s in suppliers_data}
    
    if not b_dict:
        st.warning("⚠️ لا يمكن إدخال مشتريات. يرجى التأكد من وجود فرع أو مخزن واحد على الأقل في النظام.")
        conn.close()
        return

    if not s_dict:
        st.warning("⚠️ لا يوجد أي مورد مسجل في النظام. يرجى استخدام زر الإضافة بالأعلى لإضافة مورد جديد.")
        conn.close()
        return

    col_h1, col_h2, col_h3, col_h4 = st.columns(4)
    pb = col_h1.selectbox("🏢 الفرع / المخزن المستلم:", list(b_dict.keys()))
    ps = col_h2.selectbox("🚛 المورد (التاجر):", list(s_dict.keys()))
    inv_num = col_h3.text_input("🧾 رقم فاتورة الشراء:")
    ptype = col_h4.selectbox("💳 طريقة الدفع:", ["كاش (مدفوعة بالكامل)", "آجل (تسجل على حساب المورد)"])

    # عرض رصيد المورد الحالي (الديون)
    current_supplier_balance = s_balance_dict.get(ps, 0.0)
    if current_supplier_balance > 0:
        st.markdown(f"<div style='background-color: #fee2e2; padding: 10px; border-radius: 8px; color: #991b1b; font-weight: bold; margin-bottom: 15px;'>⚠️ تنبيه مالي: إجمالي الدين الحالي المستحق لهذا المورد (في ذمة المحل) = {current_supplier_balance:,.2f} د.ل</div>", unsafe_allow_html=True)
    elif current_supplier_balance < 0:
        st.markdown(f"<div style='background-color: #d1fae5; padding: 10px; border-radius: 8px; color: #065f46; font-weight: bold; margin-bottom: 15px;'>✅ رصيد لصالح المحل عند هذا المورد = {abs(current_supplier_balance):,.2f} د.ل</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='background-color: #f1f5f9; padding: 10px; border-radius: 8px; color: #334155; font-weight: bold; margin-bottom: 15px;'>ℹ️ حساب المورد حالياً مسفّر (صفر د.ل)</div>", unsafe_allow_html=True)

    if "purch_cart" not in st.session_state: 
        st.session_state["purch_cart"] = []

    st.markdown("---")
    
    # إدخال أصناف الفاتورة
    db_items = conn.execute("SELECT id, item_code, item_name, buy_price FROM items WHERE branch_id = ?", (b_dict[pb],)).fetchall()
    i_opts = {f"[{i['item_code']}] {i['item_name']}": i for i in db_items} if db_items else {}
    
    if i_opts:
        with st.form("add_purch_item_form", clear_on_submit=True):
            col_i1, col_i2, col_i3 = st.columns([2, 1, 1])
            c_ik = col_i1.selectbox("اختر الصنف من المخزن:", list(i_opts.keys()))
            p_q = col_i2.number_input("الكمية المشتراة (كجم/وحدة):", min_value=0.01, value=1.0, step=1.0)
            p_pr = col_i3.number_input("سعر الشراء الفعلي للوحدة (د.ل):", min_value=0.0, value=0.0, step=0.5)
            
            if st.form_submit_button("➕ إضافة الصنف لفاتورة المشتريات"):
                if p_q > 0 and p_pr > 0:
                    it = i_opts[c_ik]
                    st.session_state["purch_cart"].append({"id": it['id'], "code": it['item_code'], "name": it['item_name'], "qty": p_q, "price": p_pr, "total": p_q * p_pr})
                    st.success("تمت إضافة الصنف للفاتورة!")
                    st.rerun()
    else:
        st.info(f"لا توجد أصناف معرفة في {pb}. يرجى تعريف الأصناف في المخزن أولاً.")

    # سلة المشتريات واعتماد الفاتورة
    if st.session_state["purch_cart"]:
        st.markdown("### 🛒 محتويات فاتورة الشراء الحالية")
        cart_df = pd.DataFrame(st.session_state["purch_cart"]).rename(columns={"code": "الكود", "name": "الصنف", "qty": "الكمية", "price": "سعر الوحدة", "total": "الإجمالي"})
        st.dataframe(cart_df[["الكود", "الصنف", "الكمية", "سعر الوحدة", "الإجمالي"]], use_container_width=True, hide_index=True)
        
        g_tot = sum([x["total"] for x in st.session_state["purch_cart"]])
        st.markdown(f"### 📌 إجمالي الفاتورة: <span style='color: #dc2626;'>{g_tot:,.2f} د.ل</span>", unsafe_allow_html=True)
        
        if st.button("💾 اعتماد فاتورة المشتريات (ترحيل للمخزن وتحديث متوسط التكلفة)", type="primary"):
            if not inv_num.strip():
                st.error("⚠️ يرجى إدخال رقم الفاتورة الورقية الخاصة بالمورد.")
            else:
                sup_id = s_dict[ps]
                cur_p = conn.cursor()
                det = []
                
                for pi in st.session_state["purch_cart"]:
                    old_r = cur_p.execute("SELECT quantity, avg_cost, buy_price FROM items WHERE id = ?", (pi['id'],)).fetchone()
                    old_q = float(old_r["quantity"])
                    old_avg = float(old_r["avg_cost"]) if float(old_r["avg_cost"]) > 0 else float(old_r["buy_price"])
                    
                    new_tot_q = old_q + pi['qty']
                    if new_tot_q > 0:
                        new_avg_cost = ((old_q * old_avg) + (pi['qty'] * pi['price'])) / new_tot_q
                    else:
                        new_avg_cost = pi['price']
                        
                    cur_p.execute("UPDATE items SET quantity = quantity + ?, buy_price = ?, avg_cost = ? WHERE id = ?", (pi['qty'], pi['price'], new_avg_cost, pi['id']))
                    det.append(f"{pi['name']} ({pi['qty']} كجم)")
                
                cur_p.execute("INSERT INTO purchases (branch_id, supplier_id, supplier_name, invoice_number, total_cost, payment_type, items_details, invoice_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                              (b_dict[pb], sup_id, ps, inv_num.strip(), g_tot, ptype, " - ".join(det), datetime.now().strftime('%Y-%m-%d')))
                
                if ptype == "آجل (تسجل على حساب المورد)": 
                    cur_p.execute("UPDATE suppliers SET balance = balance + ? WHERE id = ?", (g_tot, sup_id))
                
                conn.commit()
                st.session_state["purch_cart"] = []
                st.success("✅ تم ترحيل الفاتورة بنجاح، وتحديث المخزون، وحساب متوسط التكلفة الجديد!")
                st.rerun()

    conn.close()
