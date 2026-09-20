import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    # 1. عنوان قصير ومباشر
    st.header("📦 إدارة المخزن")
    st.markdown("---")
    
    conn = get_db_connection()
    
    # 2. تقسيم الشاشة: ربع للأزرار الجانبية (القائمة)، وثلاثة أرباع للتنفيذ والعرض
    col_menu, col_main = st.columns([1, 4])
    
    # تهيئة متغير الجلسة للتنقل بين الأوامر
    if "inv_action" not in st.session_state:
        st.session_state["inv_action"] = "view"

    # --- القائمة الجانبية للأزرار الصغيرة ---
    with col_menu:
        st.write("⚙️ الأوامر")
        if st.button("📋 عرض الكل", use_container_width=True):
            st.session_state["inv_action"] = "view"
            st.rerun()
            
        if st.button("➕ صنف جديد", use_container_width=True):
            st.session_state["inv_action"] = "add"
            st.rerun()
            
        if st.button("✏️ تعديل صنف", use_container_width=True):
            st.session_state["inv_action"] = "edit"
            st.rerun()
            
        if st.button("📥 تصدير إكسيل", use_container_width=True):
            st.session_state["inv_action"] = "export"
            st.rerun()

    # --- شاشة التنفيذ الرئيسية بناءً على الزر المضغوط ---
    with col_main:
        # عرض الأصناف
        if st.session_state["inv_action"] == "view":
            st.subheader("📋 قائمة الأصناف")
            df = pd.read_sql_query("SELECT item_code as 'الباركود', item_name as 'الصنف', quantity as 'الكمية', sale_price as 'سعر البيع' FROM items", conn)
            st.dataframe(df, use_container_width=True, hide_index=True)
            
        # إضافة صنف جديد
        elif st.session_state["inv_action"] == "add":
            st.subheader("➕ صنف جديد")
            with st.form("add_item_form"):
                c1, c2 = st.columns(2)
                code = c1.text_input("الباركود")
                name = c2.text_input("اسم الصنف")
                
                c3, c4 = st.columns(2)
                qty = c3.number_input("الكمية", min_value=0.0, step=1.0)
                price = c4.number_input("سعر البيع", min_value=0.0, step=0.5)
                
                # زر تنفيذ منفصل ومباشر
                if st.form_submit_button("💾 حفظ الصنف", type="primary"):
                    if name and code:
                        conn.execute("INSERT INTO items (item_code, item_name, quantity, sale_price) VALUES (?, ?, ?, ?)", (code, name, qty, price))
                        conn.commit()
                        st.success("✅ تم الحفظ بنجاح!")
                    else:
                        st.error("⚠️ يرجى إدخال اسم الصنف والباركود.")
                        
        # تعديل صنف موجود
        elif st.session_state["inv_action"] == "edit":
            st.subheader("✏️ تعديل صنف")
            items = conn.execute("SELECT id, item_name FROM items").fetchall()
            
            if items:
                item_dict = {it["item_name"]: it["id"] for it in items}
                sel_item = st.selectbox("اختر الصنف المراد تعديله:", list(item_dict.keys()))
                item_data = conn.execute("SELECT * FROM items WHERE id = ?", (item_dict[sel_item],)).fetchone()
                
                with st.form("edit_item_form"):
                    c1, c2 = st.columns(2)
                    new_qty = c1.number_input("الكمية الحالية", value=float(item_data["quantity"]), step=1.0)
                    new_price = c2.number_input("سعر البيع", value=float(item_data["sale_price"]), step=0.5)
                    
                    if st.form_submit_button("🔄 تحديث البيانات", type="primary"):
                        conn.execute("UPDATE items SET quantity = ?, sale_price = ? WHERE id = ?", (new_qty, new_price, item_dict[sel_item]))
                        conn.commit()
                        st.success("✅ تم التحديث بنجاح!")
            else:
                st.info("لا توجد أصناف مسجلة بعد.")
                
        # تصدير البيانات
        elif st.session_state["inv_action"] == "export":
            st.subheader("📥 تصدير البيانات")
            st.info("انقر على الزر أدناه لتحميل نسخة من المخزن كملف Excel.")
            
            # تجهيز الملف للتحميل
            df_export = pd.read_sql_query("SELECT * FROM items", conn)
            csv = df_export.to_csv(index=False).encode('utf-8')
            
            st.download_button(
                label="📥 تحميل ملف المخزن",
                data=csv,
                file_name="inventory.csv",
                mime="text/csv",
                type="primary"
            )
            
    conn.close()
