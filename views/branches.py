import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("🏢 إدارة وتعديل وحذف الفروع والمخازن")
    st.info("💡 من هنا يمكنك إضافة المخزن الرئيسي، إضافة الفروع الجديدة للبيع اليومي، أو تعديل وحذف الفروع الحالية.")
    
    conn = get_db_connection()
    current_user_role = st.session_state.get("role", "")
    
    # --- قسم إضافة فرع أو مخزن جديد ---
    st.markdown("### ➕ إضافة فرع أو مخزن جديد")
    with st.form("new_branch_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            nb_name = st.text_input("اسم الفرع أو المخزن الجديد:")
        with col2:
            # الفرع للبيع اليومي، والمخزن للتخزين
            nb_type = st.selectbox("نوع الكيان:", ["فرع", "مخزن"])
            
        if st.form_submit_button("💾 حفظ الكيان الجديد", type="primary"):
            if nb_name.strip():
                try:
                    conn.execute("INSERT INTO branches (branch_name, branch_type) VALUES (?, ?)", 
                                 (nb_name.strip(), nb_type))
                    conn.commit()
                    st.success(f"✅ تم إضافة ({nb_name.strip()}) بنجاح كـ ({nb_type})!")
                except Exception as e:
                    st.error("⚠️ عذراً، اسم هذا الفرع أو المخزن موجود مسبقاً.")
            else:
                st.warning("⚠️ يرجى إدخال اسم صحيح.")

    # --- قسم عرض وتعديل الفروع والمخازن الحالية ---
    st.markdown("---")
    st.markdown("### 📋 الفروع والمخازن المسجلة حالياً")
    
    branches_df = pd.read_sql("""
        SELECT id AS 'المسلسل', 
               branch_name AS 'اسم الفرع أو المخزن', 
               branch_type AS 'النوع' 
        FROM branches
    """, conn)
    
    if not branches_df.empty:
        st.dataframe(branches_df, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.markdown("### ⚙️ تعديل أو حذف فرع / مخزن")
        
        # اختيار الفرع المراد تعديله أو حذفه
        branch_options = {f"رقم {row['المسلسل']} - {row['اسم الفرع أو المخزن']} ({row['النوع']})": row['المسلسل'] for index, row in branches_df.iterrows()}
        selected_branch_label = st.selectbox("اختر الفرع أو المخزن للتحكم به:", list(branch_options.keys()))
        selected_b_id = branch_options[selected_branch_label]
        
        # جلب بيانات الفرع المختار لتعبئتها في نموذج التعديل
        b_data = conn.execute("SELECT branch_name, branch_type FROM branches WHERE id = ?", (selected_b_id,)).fetchone()
        
        if b_data:
            with st.form("edit_branch_form"):
                e_name = st.text_input("تعديل الاسم:", value=b_data["branch_name"])
                e_type = st.selectbox("تعديل النوع:", ["فرع", "مخزن"], index=0 if b_data["branch_type"] == "فرع" else 1)
                
                col_save, col_del = st.columns(2)
                with col_save:
                    save_clicked = st.form_submit_button("💾 حفظ التعديلات", type="primary")
                with col_del:
                    del_clicked = st.form_submit_button("🗑️ حذف هذا الكيان")
                    
                if save_clicked:
                    if e_name.strip():
                        try:
                            conn.execute("UPDATE branches SET branch_name = ?, branch_type = ? WHERE id = ?", 
                                         (e_name.strip(), e_type, selected_b_id))
                            conn.commit()
                            st.success("✅ تمت تحديث بيانات الكيان بنجاح!")
                            st.rerun()
                        except Exception as e:
                            st.error("⚠️ خطأ في التعديل، قد يكون الاسم مستخدماً لفرع آخر.")
                    else:
                        st.warning("⚠️ لا يمكن ترك الاسم فارغاً.")
                        
                if del_clicked:
                    # حماية أمنية: التأكد من صلاحيات الأدمن للحذف
                    if current_user_role != "Admin":
                        st.error("❌ عذراً، عملية حذف الفروع مقتصرة على الأدمن (Admin) فقط لأسباب أمنية!")
                    else:
                        # التحقق مما إذا كان هذا هو المخزن الرئيسي أو يحتوي على أصناف
                        conn.execute("DELETE FROM branches WHERE id = ?", (selected_b_id,))
                        conn.commit()
                        st.success("✅ تم حذف الكيان بنجاح!")
                        st.rerun()
    else:
        st.info("لا توجد فروع أو مخازن مسجلة حالياً.")
        
    conn.close()
