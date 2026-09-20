import streamlit as st
import pandas as pd
import os
from database import get_db_connection

def show_page():
    st.header("⭐ لوحة الأصناف المفضلة (لشاشة الكاشير)")
    st.info("💡 ضع رقم (1) في عمود 'مفضل' ليظهر الصنف في شاشة الكاشير السريعة. يمكنك أيضاً رفع صورة للصنف.")
    
    conn = get_db_connection()
    b_dict = {b["branch_name"]: b["id"] for b in conn.execute("SELECT id, branch_name FROM branches").fetchall()}
    sel_b = st.selectbox("اختر الفرع / المخزن:", list(b_dict.keys()))
    b_id = b_dict[sel_b]
    
    # جلب الأصناف
    items_df = pd.read_sql("SELECT id, item_code AS 'كود الصنف', item_name AS 'اسم الصنف', favorite_rank AS 'مفضل (1 نعم، 0 لا)' FROM items WHERE branch_id = ?", conn, params=(b_id,))
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("### 📋 تحديد الأصناف المفضلة")
        if not items_df.empty:
            edited_df = st.data_editor(items_df, hide_index=True, use_container_width=True)
            if st.button("💾 حفظ التعديلات", type="primary"):
                for idx, row in edited_df.iterrows():
                    conn.execute("UPDATE items SET favorite_rank = ? WHERE id = ?", (row['مفضل (1 نعم، 0 لا)'], row['id']))
                conn.commit()
                st.success("✅ تم حفظ الأصناف المفضلة بنجاح!")
                st.rerun()
        else:
            st.warning("لا توجد أصناف في هذا الفرع.")

    with col2:
        st.markdown("### 🖼️ إضافة صورة لصنف")
        if not items_df.empty:
            item_list = {f"[{row['كود الصنف']}] {row['اسم الصنف']}": row['كود الصنف'] for _, row in items_df.iterrows()}
            selected_item_label = st.selectbox("اختر الصنف لرفع صورته:", list(item_list.keys()))
            selected_code = item_list[selected_item_label]
            
            uploaded_file = st.file_uploader("اختر صورة (JPG, PNG)", type=["jpg", "jpeg", "png"])
            if uploaded_file is not None:
                if st.button("📤 رفع وحفظ الصورة", use_container_width=True):
                    # حفظ الصورة باسم كود الصنف في مجلد item_images
                    file_path = os.path.join("item_images", f"{selected_code}.jpg")
                    with open(file_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    st.success("✅ تم حفظ الصورة بنجاح! ستظهر الآن في شاشة الكاشير.")
            
            # معاينة الصورة إذا كانت موجودة
            preview_path = os.path.join("item_images", f"{selected_code}.jpg")
            if os.path.exists(preview_path):
                st.markdown("**الصورة الحالية:**")
                st.image(preview_path, use_container_width=True)
                
    conn.close()
