import streamlit as st
import pandas as pd
from database import get_db_connection, reindex_table

@st.dialog("🔒 تأكيد أمني لحذف الكيان")
def confirm_delete_branch_dialog(branch_id, branch_name):
    st.warning(f"⚠️ تنبيه خطير: أنت على وشك حذف الفرع أو المخزن (**{branch_name}**).\n\nلا يمكن التراجع عن هذه الخطوة بعد تنفيذها!")
    
    admin_pass = st.text_input("أدخل كلمة المرور الخاصة بك للتأكيد:", type="password", key="del_branch_pass_input")
    
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("✅ تأكيد الحذف", type="primary", use_container_width=True):
            conn = get_db_connection()
            user_id = st.session_state.get("user_id")
            
            # التحقق من صحة كلمة المرور للمستخدم الحالي
            user_check = conn.execute("SELECT * FROM users WHERE id = ? AND password = ?", (user_id, admin_pass)).fetchone()
            
            if user_check:
                conn.execute("DELETE FROM branches WHERE id = ?", (branch_id,))
                conn.commit()
                reindex_table(conn, 'branches')
                conn.close()
                st.success("✅ تم حذف الكيان وإعادة تنظيم الترقيم بنجاح!")
                st.rerun()
            else:
                conn.close()
                st.error("❌ كلمة المرور غير صحيحة!")
                
    with col_no:
        if st.button("❌ إلغاء", use_container_width=True):
            st.rerun()

@st.dialog("💾 تأكيد حفظ التعديلات")
def confirm_edit_branch_dialog(branch_id, old_name, new_name, new_type):
    st.info(f"💡 هل أنت متأكد من رغبتك في تعديل بيانات الكيان من (**{old_name}**) إلى (**{new_name} - {new_type}**)؟")
    
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("✅ موافق وحفظ", type="primary", use_container_width=True):
            conn = get_db_connection()
            try:
                conn.execute("UPDATE branches SET branch_name = ?, branch_type = ? WHERE id = ?", 
                             (new_name.strip(), new_type, branch_id))
                conn.commit()
                conn.close()
                st.success("✅ تم تحديث بيانات الكيان بنجاح!")
                st.rerun()
            except Exception as e:
                conn.close()
                st.error("⚠️ خطأ في التعديل، قد يكون الاسم مستخدماً لفرع آخر.")
    with col_no:
        if st.button("❌ إلغاء", use_container_width=True):
            st.rerun()

def show_page():
    st.header("🏢 إدارة وتعديل وحذف الفروع والمخازن")
    
    current_user_role = st.session_state.get("role", "")
    
    # التعديل الأول: إخفاء النص عن الجميع وإظهاره للأدمن فقط كـ caption
    if current_user_role == "Admin":
        st.caption("تلميح للإدارة: من هنا يمكنك إضافة المخزن الرئيسي، إضافة الفروع الجديدة للبيع اليومي، أو تعديل وحذف الفروع الحالية.")
    
    st.markdown("---")
    
    conn = get_db_connection()
    
    # التعديل الثاني: تقسيم الشاشة (أزرار جانبية وشاشة عرض رئيسية)
    col_menu, col_main = st.columns([1, 4])
    
    if "branch_action" not in st.session_state:
        st.session_state["branch_action"] = "view"

    # --- القائمة الجانبية للأزرار ---
    with col_menu:
        st.write("⚙️ الأوامر")
        if st.button("📋 عرض وتعديل", use_container_width=True):
            st.session_state["branch_action"] = "view"
            st.rerun()
            
        if st.button("➕ فرع جديد", use_container_width=True):
            st.session_state["branch_action"] = "add"
            st.rerun()

    # --- شاشة التنفيذ الرئيسية ---
    with col_main:
        
        if st.session_state["branch_action"] == "add":
            st.subheader("➕ إضافة فرع أو مخزن جديد")
            with st.form("new_branch_form", clear_on_submit=True):
                col1, col2 = st.columns(2)
                with col1:
                    nb_name = st.text_input("اسم الفرع أو المخزن الجديد:")
                with col2:
                    nb_type = st.selectbox("نوع الكيان:", ["فرع", "مخزن"])
                    
                if st.form_submit_button("💾 حفظ الكيان الجديد", type="primary"):
                    if nb_name.strip():
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

        elif st.session_state["branch_action"] == "view":
            st.subheader("📋 الفروع والمخازن المسجلة حالياً")
            
            raw_branches = conn.execute("SELECT id, branch_name, branch_type FROM branches ORDER BY id ASC").fetchall()
            
            if raw_branches:
                branch_rows = []
                branch_options = {}
                
                for idx, row in enumerate(raw_branches, start=1):
                    branch_rows.append({
                        "المسلسل": idx,
                        "اسم الفرع أو المخزن": row["branch_name"],
                        "النوع": row["branch_type"]
                    })
                    branch_options[f"رقم {idx} - {row['branch_name']} ({row['branch_type']})"] = row["id"]

                branches_df = pd.DataFrame(branch_rows)
                st.dataframe(branches_df, use_container_width=True, hide_index=True)
                
                st.markdown("---")
                st.markdown("### ⚙️ تعديل أو حذف فرع / مخزن")
                
                selected_branch_label = st.selectbox("اختر الفرع أو المخزن للتحكم به:", list(branch_options.keys()))
                selected_b_id = branch_options[selected_branch_label]
                
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
                                confirm_edit_branch_dialog(selected_b_id, b_data["branch_name"], e_name.strip(), e_type)
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
