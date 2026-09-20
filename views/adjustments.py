import streamlit as st
import pandas as pd
from database import get_db_connection

# --- نافذة أمنية منبثقة لتأكيد أي عملية بكلمة المرور ---
@st.dialog("🔒 تأكيد أمني لتنفيذ العملية")
def secure_action_dialog(action_title, callback_func, *args):
    st.warning(f"⚠️ أنت على وشك تنفيذ: **{action_title}**.\n\nيرجى إدخال كلمة المرور لتأكيد التنفيذ:")
    password_input = st.text_input("كلمة المرور:", type="password", key="sec_action_pass_input")
    
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("✅ تأكيد وتنفيذ", type="primary", use_container_width=True):
            conn = get_db_connection()
            user_id = st.session_state.get("user_id")
            user_chk = conn.execute("SELECT * FROM users WHERE id = ? AND password = ?", (user_id, password_input)).fetchone()
            conn.close()
            
            if user_chk:
                callback_func(*args)
            else:
                st.error("❌ كلمة المرور غير صحيحة!")
    with col_no:
        if st.button("❌ إلغاء", use_container_width=True):
            st.rerun()

# --- تنفيذ إضافة فائض ---
def execute_add_surplus(b_id, item_id, qty_val):
    conn = get_db_connection()
    try:
        conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (qty_val, item_id))
        conn.commit()
        conn.close()
        st.success("✅ تمت إضافة الفائض وتحديث كمية الصنف بنجاح!")
        st.rerun()
    except Exception as e:
        conn.close()
        st.error(f"⚠️ حدث خطأ: {e}")

# --- تنفيذ التوالف أو المرتجعات ---
def execute_damage_return(b_id, item_id, qty_val, reason_type):
    conn = get_db_connection()
    try:
        # خصم الكمية من الفرع المحدد
        conn.execute("UPDATE items SET quantity = MAX(0, quantity - ?) WHERE id = ?", (qty_val, item_id))
        conn.commit()
        conn.close()
        st.success(f"✅ تم تسجيل العملية بنجاح (السبب: {reason_type}) وخصم الكمية!")
        st.rerun()
    except Exception as e:
        conn.close()
        st.error(f"⚠️ حدث خطأ: {e}")

# --- تنفيذ تعديل السعر وتعميمه على كافة الفروع ---
def execute_global_price_update(item_code, new_sale_price):
    conn = get_db_connection()
    try:
        # تعميم التعديل على نفس الصنف (بواسطة الكود) في كافة الفروع
        conn.execute("UPDATE items SET sale_price = ? WHERE item_code = ?", (new_sale_price, item_code))
        conn.commit()
        conn.close()
        st.success("✅ تم تعديل سعر البيع وتعميمه على كافة الفروع بنجاح!")
        st.rerun()
    except Exception as e:
        conn.close()
        st.error(f"⚠️ حدث خطأ أثناء تعميم السعر: {e}")

# --- الواجهة الرئيسية للشاشة ---
def show_page():
    st.header("➕ الفائض، التوالف، المرتجعات وتعديل الأسعار")
    st.info("💡 إدارة دقيقة ومستقلة لتصحيح كميات المخزون وتعميم الأسعار.")
    
    role = st.session_state.get("role", "")
    if role not in ["Admin", "General_Supervisor", "Manager"]:
        st.error("❌ عذراً، هذه الصفحة مخصصة للإدارة والمشرفين فقط!")
        return

    conn = get_db_connection()
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ لا توجد فروع مسجلة في النظام.")
        conn.close()
        return
        
    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    sel_branch_name = st.selectbox("اختر الفرع المستهدف:", list(branch_dict.keys()))
    sel_b_id = branch_dict[sel_branch_name]
    
    st.markdown("---")
    
    # تقسيم الشاشة إلى تبويبات (Tabs) منفصلة تماماً كما طلبت
    tab1, tab2, tab3 = st.tabs([
        "➕ إضافة فائض فرع (أصناف رصيدها صفر)", 
        "♻️ تسجيل التوالف والمرتجعات", 
        "✏️ تعديل وتعميم سعر الصنف"
    ])
    
    # --- التبويب الأول: إضافة فائض (للأصناف التي رصيدها صفر) ---
    with tab1:
        st.subheader("➕ إضافة كمية فائضة لفرع (الأصناف التي كميتها صفر)")
        zero_items = conn.execute("SELECT id, item_code, item_name, quantity FROM items WHERE branch_id = ? AND quantity <= 0", (sel_b_id,)).fetchall()
        
        if zero_items:
            zero_dict = {f"[{it['item_code'] or 'بدون'}] {it['item_name']}": it for it in zero_items}
            with st.form("surplus_form"):
                sel_zero_label = st.selectbox("اختر الصنف (الرصيد صفر):", list(zero_dict.keys()))
                surplus_qty = st.number_input("الكمية الفاضلة المراد إضافتها (كجم):", min_value=0.0, value=1.0, step=0.5, format="%.2f")
                
                if st.form_submit_button("🚀 اعتماد وإضافة الفائض", type="primary"):
                    chosen_item = zero_dict[sel_zero_label]
                    if surplus_qty > 0:
                        secure_action_dialog(
                            f"إضافة فائض بقيمة {surplus_qty} للصنف ({chosen_item['item_name']})",
                            execute_add_surplus, sel_b_id, chosen_item["id"], surplus_qty
                        )
                    else:
                        st.warning("⚠️ يرجى إدخال كمية صحيحة.")
        else:
            st.success(f"🎉 ممتاز! لا توجد أصناف برصيد (صفر) في فرع ({sel_branch_name}).")

    # --- التبويب الثاني: التوالف والمرتجعات مع تحديد السبب ---
    with tab2:
        st.subheader("♻️ تسجيل التوالف، منتهي الصلاحية، أو المرتجعات للتحويل")
        all_branch_items = conn.execute("SELECT id, item_code, item_name, quantity FROM items WHERE branch_id = ?", (sel_b_id,)).fetchall()
        
        if all_branch_items:
            branch_item_dict = {f"[{it['item_code'] or 'بدون'}] {it['item_name']} (المتاح: {it['quantity']})": it for it in all_branch_items}
            with st.form("damage_return_form"):
                sel_item_label = st.selectbox("اختر الصنف:", list(branch_item_dict.keys()))
                qty_val = st.number_input("الكمية المراد خصمها:", min_value=0.0, value=1.0, step=0.5, format="%.2f")
                
                reason_type = st.selectbox("سبب الخروج / الإرجاع:", [
                    "تالف / هالك", 
                    "منتهى الصلاحية", 
                    "للتحويل لفرع آخر"
                ])
                
                if st.form_submit_button("🚀 تنفيذ وخصم الكمية", type="primary"):
                    chosen_item = branch_item_dict[sel_item_label]
                    if qty_val > 0:
                        if qty_val > chosen_item["quantity"]:
                            st.error(f"⚠️ الكمية المطلوبة أكبر من الرصيد المتاح حالياً ({chosen_item['quantity']})!")
                        else:
                            secure_action_dialog(
                                f"تسجيل ({reason_type}) للصنف ({chosen_item['item_name']}) بكمية {qty_val}",
                                execute_damage_return, sel_b_id, chosen_item["id"], qty_val, reason_type
                            )
                    else:
                        st.warning("⚠️ يرجى إدخال كمية صحيحة.")
        else:
            st.info("لا توجد أصناف في هذا الفرع.")

    # --- التبويب الثالث: تعديل السعر وتعميمه على كافة الفروع ---
    with tab3:
        st.subheader("✏️ تعديل سعر البيع وتعميمه على كافة الفروع")
        if all_branch_items:
            price_dict = {f"[{it['item_code'] or 'بدون'}] {it['item_name']}": it for it in all_branch_items}
            with st.form("price_update_form"):
                sel_p_label = st.selectbox("اختر الصنف لتعديل سعره:", list(price_dict.keys()))
                chosen_p_item = price_dict[sel_p_label]
                
                # جلب السعر الحالي للصنف
                curr_price_row = conn.execute("SELECT sale_price FROM items WHERE id = ?", (chosen_p_item["id"],)).fetchone()
                curr_sale_price = curr_price_row["sale_price"] if curr_price_row else 0.0
                
                new_price = st.number_input("سعر البيع الجديد (د.ل):", min_value=0.0, value=float(curr_sale_price), step=0.5, format="%.2f")
                
                if st.form_submit_button("🚀 حفظ وتعميم السعر الجديد على كل الفروع", type="primary"):
                    if chosen_p_item["item_code"]:
                        secure_action_dialog(
                            f"تعديل وتعميم سعر الصنف ({chosen_p_item['item_name']}) إلى {new_price} د.ل لكل الفروع",
                            execute_global_price_update, chosen_p_item["item_code"], new_price
                        )
                    else:
                        st.error("❌ هذا الصنف لا يمتلك كود/باركود، ولا يمكن تعميم السعر بدونه. يرجى إعطاؤه كوداً أولاً.")
        else:
            st.info("لا توجد أصناف في هذا الفرع.")
            
    conn.close()
