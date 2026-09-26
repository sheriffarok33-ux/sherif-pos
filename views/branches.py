import streamlit as st
import pandas as pd
from database import get_db_connection

@st.dialog("🔒 تأكيد أمني لحذف الفرع أو المخزن")
def confirm_delete_branch_dialog(branch_id, branch_name):
    st.warning(f"⚠️ تنبيه خطير: أنت على وشك حذف الكيان (**{branch_name}**).\n\nلا يمكن التراجع عن هذه الخطوة بعد تنفيذها!")
    
    admin_pass = st.text_input("أدخل كلمة المرور الخاصة بك للتأكيد:", type="password", key="del_branch_pass_input")
    
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("✅ تأكيد الحذف", type="primary", use_container_width=True):
            conn = get_db_connection()
            user_id = st.session_state.get("user_id")
            
            user_check = conn.execute("SELECT * FROM users WHERE id = ? AND password = ?", (user_id, admin_pass)).fetchone()
            
            if user_check:
                conn.execute("DELETE FROM branches WHERE id = ?", (branch_id,))
                conn.commit()
                conn.close()
                st.success("✅ تم حذف الفرع بنجاح!")
                st.rerun()
            else:
                conn.close()
                st.error("❌ كلمة المرور غير صحيحة!")
                
    with col_no:
        if st.button("❌ إلغاء", use_container_width=True):
            st.rerun()

def show_page():
    st.header("🏢 إدارة الفروع والمخازن المستقلة")
    st.info("💡 من هنا يمكنك إضافة الفروع الجديدة للبيع اليومي أو المخازن الرئيسية، وتعديل أو حذف الفروع الحالية.")
    
    current_user_role = st.session_state.get("role", "")
    
    if current_user_role == "Admin":
        st.caption("تلميح للإدارة: تحكم كامل في البنية التنظيمية للشركة وفروعها.")
    
    st.markdown("---")
    
    conn = get_db_connection()
    
    # تقسيم الشاشة إلى تبويبات واضحة لمنع أي تداخل
    tab_view, tab_add = st.tabs(["📋 عرض وتعديل الفروع الحالية", "➕ إضافة فرع أو مخزن جديد"])
    
    # --- 1. تبويب إضافة فرع جديد ---
    with tab_add:
        st.subheader("➕ إضافة فرع أو مخزن جديد للنظام")
        with st.form("new_branch_form_unique", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                nb_name = st.text_input("اسم الفرع أو المخزن الجديد:")
            with col2:
                nb_type = st.selectbox("نوع الكيان:", ["فرع", "مخزن"])
                
            if st.form_submit_button("💾 حفظ الكيان الجديد", type="primary"):
                if nb_name and nb_name.strip():
                    try:
                        conn.execute("INSERT INTO branches (branch_name, branch_type) VALUES (?, ?)", 
                                     (nb_name.strip(), nb_type))
                        conn.commit()
                        st.success(f"✅ تم إضافة ({nb_name.strip()}) بنجاح كـ ({nb_type})!")
                        st.rerun()
                    except Exception as e:
                        st.error("⚠️ عذراً، اسم هذا الفرع أو المخزن موجود مسبقاً.")
                else:
                    st.warning("⚠️ يرجى إدخال اسم صحيح.")

    # --- 2. تبويب عرض وتعديل وحذف الفروع ---
    with tab_view:
        st.subheader("📋 الفروع والمخازن المسجلة حالياً")
        
        raw_branches = conn.execute("SELECT id, branch_name, branch_type FROM branches ORDER BY id ASC").fetchall()
        
        if raw_branches:
            branch_rows = []
            branch_options = {}
            
            for idx, row in enumerate(raw_branches, start=1):
                branch_rows.append({
                    "المسلسل": row["id"],
                    "اسم الفرع أو المخزن": row["branch_name"],
                    "النوع": row["branch_type"]
                })
                branch_options[f"رقم {row['id']} - {row['branch_name']} ({row['branch_type']})"] = row["id"]

            branches_df = pd.DataFrame(branch_rows)
            st.dataframe(branches_df, use_container_width=True, hide_index=True)
            
            st.markdown("---")
            st.markdown("### ⚙️ تعديل أو حذف فرع / مخزن معين")
            
            selected_branch_label = st.selectbox("اختر الفرع أو المخزن للتحكم به:", list(branch_options.keys()))
            selected_b_id = branch_options[selected_branch_label]
            
            b_data = conn.execute("SELECT branch_name, branch_type FROM branches WHERE id = ?", (selected_b_id,)).fetchone()
            
            if b_data:
                with st.form("edit_branch_form_unique"):
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
                                st.success("✅ تم تحديث بيانات الكيان بنجاح!")
                                st.rerun()
                            except:
                                st.error("⚠️ خطأ في التعديل، قد يكون الاسم مستخدماً لفرع آخر.")
                        else:
                            st.warning("⚠️ لا يمكن ترك الاسم فارغاً.")
                            
                    if del_clicked:
                        if current_user_role != "Admin":
                            st.error("❌ عذراً، عملية حذف الفروع مقتصرة على الأدمن (Admin) فقط لأسباب أمنية!")
                        else:
                            confirm_delete_branch_dialog(selected_b_id, b_data["branch_name"])
        else:
            st.info("لا توجد فروع أو مخازن مسجلة حالياً.")
            
    conn.close()
