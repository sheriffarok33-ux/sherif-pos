import streamlit as st
import pandas as pd
from database import get_db_connection

# --- 1. ديالوج تأكيد وتأمين التعديلات أو العمليات الحساسة ---
@st.dialog("🔒 تأكيد العملية بكلمة المرور")
def secure_action_dialog(action_title, callback_func, *args):
    st.warning(f"⚠️ أنت على وشك تنفيذ: **{action_title}**.\n\nيرجى إدخال كلمة المرور الخاصة بك لتأكيد التنفيذ:")
    
    password_input = st.text_input("كلمة المرور:", type="password", key="sec_action_pass")
    
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("✅ تأكيد وتنفيذ", type="primary", use_container_width=True):
            conn = get_db_connection()
            user_id = st.session_state.get("user_id")
            
            # التحقق من كلمة المرور للمستخدم الحالي
            user_chk = conn.execute("SELECT * FROM users WHERE id = ? AND password = ?", (user_id, password_input)).fetchone()
            conn.close()
            
            if user_chk:
                callback_func(*args)
            else:
                st.error("❌ كلمة المرور غير صحيحة!")
    with col_no:
        if st.button("❌ إلغاء", use_container_width=True):
            st.rerun()

# --- تنفيذ عملية تعديل السعر أو إضافة فائض/تالف في قاعدة البيانات ---
def execute_db_adjustment(b_id, item_id, adj_type, qty_val, new_price_val):
    conn = get_db_connection()
    try:
        if adj_type == "تعديل سعر البيع":
            conn.execute("UPDATE items SET sale_price = ? WHERE id = ?", (new_price_val, item_id))
            st.success("✅ تم تعديل سعر البيع بنجاح!")
        else:
            # الفائض يضاف للكمية، والتوالف والمرتجعات تطرح من الكمية
            if adj_type == "إضافة فائض":
                conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (qty_val, item_id))
                st.success(f"✅ تم إضافة فائض بقيمة {qty_val} بنجاح!")
            elif adj_type == "تسجيل توالف / هالك":
                conn.execute("UPDATE items SET quantity = MAX(0, quantity - ?) WHERE id = ?", (qty_val, item_id))
                st.success(f"✅ تم تسجيل التوالف بقيمة {qty_val} بنجاح!")
            elif adj_type == "تسجيل مرتجع زبون":
                conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (qty_val, item_id))
                st.success(f"✅ تم تسجيل المرتجع بقيمة {qty_val} بنجاح!")
        
        conn.commit()
        conn.close()
        st.rerun()
    except Exception as e:
        conn.close()
        st.error(f"⚠️ حدث خطأ أثناء تنفيذ العملية: {e}")

# --- واجهة الشاشة الأساسية ---
def show_page():
    st.header("➕ الفائض والتوالف والمرتجعات وتعديل السعر")
    st.info("💡 إدارة دقيقة لحركة المخزون وتصحيح الكميات أو الأسعار بحسب الفرع المختار.")
    
    role = st.session_state.get("role", "")
    # الحماية: السماح فقط للأدمن، المدير، أو المشرف
    if role not in ["Admin", "General_Supervisor", "Manager"]:
        st.error("❌ عذراً، هذه الصفحة مخصصة للإدارة والمشرفين فقط!")
        return

    conn = get_db_connection()
    
    # جلب الفروع والمخازن
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ لا توجد فروع مسجلة في النظام حالياً.")
        conn.close()
        return
        
    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    sel_branch_name = st.selectbox("اختر الفرع أو المخزن للتحكم بأصنافه:", list(branch_dict.keys()))
    sel_b_id = branch_dict[sel_branch_name]
    
    st.markdown("---")
    
    # جلب الأصناف الخاصة بهذا الفرع فقط بناءً على طلبك
    items = conn.execute("SELECT id, item_code, item_name, quantity, sale_price FROM items WHERE branch_id = ?", (sel_b_id,)).fetchall()
    
    if not items:
        st.info(f"📭 لا توجد أصناف مسجلة حالياً داخل ({sel_branch_name}).")
        conn.close()
        return
        
    item_dict = {f"({it['item_code'] or 'بدون كود'}) {it['item_name']} | المتاح: {it['quantity']}": it for it in items}
    sel_item_label = st.selectbox("اختر الصنف المطلوب:", list(item_dict.keys()))
    selected_item = item_dict[sel_item_label]
    
    st.markdown("---")
    st.subheader(f"⚙️ إجراء عملية على الصنف: {selected_item['item_name']}")
    
    with st.form("adjustment_form"):
        adj_type = st.selectbox("نوع العملية المطلوبة:", [
            "إضافة فائض", 
            "تسجيل توالف / هالك", 
            "تسجيل مرتجع زبون", 
            "تعديل سعر البيع"
        ])
        
        qty_input = 0.0
        price_input = float(selected_item["sale_price"])
        
        if adj_type != "تعديل سعر البيع":
            qty_input = st.number_input("الكمية المراد إضافتها أو خصمها:", min_value=0.0, value=1.0, step=0.5, format="%.2f")
        else:
            price_input = st.number_input("سعر البيع الجديد (د.ل):", min_value=0.0, value=float(selected_item["sale_price"]), step=0.5, format="%.2f")
            
        submitted = st.form_submit_button("🚀 تنفيذ العملية", type="primary", use_container_width=True)
        
        if submitted:
            if adj_type != "تعديل سعر البيع" and qty_input <= 0:
                st.warning("⚠️ يرجى إدخال كمية صحيحة أكبر من الصفر.")
            else:
                # استدعاء الديالوج الأمني لتأكيد العملية بكلمة المرور
                secure_action_dialog(
                    f"{adj_type} للصنف ({selected_item['item_name']})", 
                    execute_db_adjustment, 
                    sel_b_id, selected_item["id"], adj_type, qty_input, price_input
                )
                
    conn.close()
