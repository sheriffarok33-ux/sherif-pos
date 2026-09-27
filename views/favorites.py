import streamlit as st
import pandas as pd
import os
import time
from database import get_db_connection

def show_page():
    role = st.session_state.get("role", "")
    if role not in ["Admin", "General_Supervisor"]:
        st.error("🔒 عذراً، هذه الشاشة مخصصة للمدير والمشرف العام فقط.")
        return

    st.header("⭐ لوحة الأصناف المفضلة (لشاشة الكاشير)")
    st.info("💡 ضع رقم (1) في عمود 'مفضل' ليظهر الصنف في شاشة الكاشير السريعة. يمكنك أيضاً رفع صورة للصنف.")
    
    conn = get_db_connection()
    b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
    sel_b = st.selectbox("اختر الفرع / المخزن:", list(b_dict.keys()))
    b_id = b_dict[sel_b]
    
    items_df = pd.read_sql("SELECT id, item_code AS 'كود الصنف', item_name AS 'اسم الصنف', favorite_rank AS 'مفضل (1 نعم، 0 لا)' FROM items WHERE branch_id = ?", conn, params=(b_id,))
    
    col1, col2 = st.columns([1.8, 1.2])
    
    with col1:
        st.markdown("### 📋 تحديد الأصناف المفضلة")
        if not items_df.empty:
            edited_df = st.data_editor(items_df, hide_index=True, use_container_width=True, height=500)
            if st.button("💾 حفظ التعديلات", type="primary", use_container_width=True):
                for idx, row in edited_df.iterrows():
                    conn.execute("UPDATE items SET favorite_rank = ? WHERE id = ?", (row['مفضل (1 نعم، 0 لا)'], row['id']))
                conn.commit()
                st.success("✅ تم حفظ الأصناف المفضلة بنجاح!")
                time.sleep(0.5)
                st.rerun()
        else:
            st.warning("لا توجد أصناف في هذا الفرع.")

    with col2:
        st.markdown("### 🖼️ إدارة صور الأصناف")
        with st.container(border=True):
            if not items_df.empty:
                item_list = {f"[{row['كود الصنف']}] {row['اسم الصنف']}": row['كود الصنف'] for _, row in items_df.iterrows()}
                selected_item_label = st.selectbox("اختر الصنف لرفع صورته:", list(item_list.keys()))
                selected_code = item_list[selected_item_label]
                
                uploaded_file = st.file_uploader("اختر صورة (JPG, PNG)", type=["jpg", "jpeg", "png"], key=f"upload_{selected_code}")
                
                if uploaded_file is not None:
                    if st.button("📤 رفع وحفظ الصورة", use_container_width=True):
                        file_path = os.path.join("item_images", f"{selected_code}.jpg")
                        with open(file_path, "wb") as f:
                            f.write(uploaded_file.getbuffer())
                        st.success("✅ تم حفظ الصورة بنجاح!")
                        time.sleep(0.5)
                        st.rerun()
                
                preview_path = os.path.join("item_images", f"{selected_code}.jpg")
                st.markdown("---")
                st.markdown("**📸 معاينة الصورة الحالية:**")
                if os.path.exists(preview_path):
                    try:
                        with open(preview_path, "rb") as f:
                            image_bytes = f.read()
                        st.image(image_bytes, use_container_width=True)
                    except Exception as e:
                        st.error("خطأ في قراءة الصورة.")
                else:
                    st.info("ℹ️ لا توجد صورة مرفوعة لهذا الصنف (سيظهر رمز 🥜 افتراضياً).")
            else:
                st.info("لا توجد أصناف متاحة.")
                
    conn.close()
