import streamlit as st
import pandas as pd
import io
from datetime import datetime
from database import get_db_connection

def to_excel(df):
    """دالة تحويل أي جدول إلى ملف Excel جاهز للتنزيل"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Expenses_Report')
    return output.getvalue()

def show_page():
    st.header("💰 إدارة وتوزيع المصروفات الذكية")
    st.info("💡 تسجيل المصروفات، توزيع مصروفات المخزن الرئيسي على الفروع، معالجة الفواتير بأثر رجعي، ومتابعة مصروفات كل فرع بشكل مستقل مع تصدير Excel.")

    conn = get_db_connection()
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع أولاً قبل تسكين المصروفات.")
        conn.close()
        return

    branch_dict = {b["branch_name"]: b["id"] for b in branches}

    # التبويبات لتنظيم الشاشة
    tab1, tab2 = st.tabs(["➕ تسجيل مصروف جديد", "📋 أرشيف المصروفات وتقارير الفروع (تصدير Excel)"])

    # --- التبويب الأول: تسجيل مصروف جديد ---
    with tab1:
        st.subheader("✍️ إدخال مصروف جديد وفق القواعد المالية")
        
        with st.form("expense_advanced_form", clear_on_submit=True):
            exp_scope = st.radio(
                "نطاق المصروف:", 
                ["📍 خاص بفرع أو مخزن معين", "🌍 مصروف عام للمخزن الرئيسي (يُقسَم بالتساوي على كافة الفروع)"]
            )
            
            sel_branch_name = ""
            if "خاص بفرع" in exp_scope:
                sel_branch_name = st.selectbox("اختر الفرع المستفيد:", list(branch_dict.keys()))

            col_a, col_b = st.columns(2)
            with col_a:
                amount = st.number_input("المبلغ الإجمالي (د.ل):", min_value=0.0, value=0.0, step=0.5)
                expense_type = st.selectbox("نوع المصروف:", ["تشغيلي عادي", "إيجار / مصروف مقدم (لفترة محددة)"])
            with col_b:
                current_year_month = datetime.now().strftime('%Y-%m')
                target_month = st.text_input("شهر الاستحقاق المحاسبي (YYYY-MM):", value=current_year_month, help="يُستخدم لتسجيل الفواتير المنسية لشهور سابقة لتدخل في أرباح ذلك الشهر.")
                expense_date = st.date_input("تاريخ التسجيل الفعلي:", value=datetime.now())

            description = st.text_input("البيان أو وصف المصروف (مثلاً: صيانة سيارة المخزن، إيجار محل...):")

            advance_end_date = None
            if "إيجار" in expense_type:
                st.markdown("---")
                st.warning("📌 إدارة الإيجارات والمصروفات المقدمة:")
                advance_end_date = st.text_input("تاريخ انتهاء فترة التغطية المقدمة (مثال: 2027-06-30):", value="", help="لكي يُظهر النظام أن رصيد الإيجار يغطي الفرع حتى هذا التاريخ.")

            submitted_exp = st.form_submit_button("💾 حفظ وترحيل المصروف", type="primary", use_container_width=True)

            if submitted_exp:
                if amount <= 0 or not description.strip():
                    st.error("⚠️ يجب إدخال مبلغ صحيح ووصف واضح للمصروف!")
                else:
                    cur_ex = conn.cursor()
                    total_branches_count = len(branches)

                    if "خاص بفرع" in exp_scope:
                        b_id = branch_dict[sel_branch_name]
                        if "إيجار" in expense_type and advance_end_date:
                            desc_final = f"[إيجار مقدم يغطي حتى {advance_end_date}] {description.strip()}"
                        else:
                            desc_final = description.strip()

                        cur_ex.execute("""
                            INSERT INTO expenses (branch_id, amount, description, is_general_store, expense_date)
                            VALUES (?, ?, ?, 0, ?)
                        """, (b_id, amount, f"[{target_month}] {desc_final}", expense_date.strftime('%Y-%m-%d')))
                    
                    else:
                        share_per_branch = amount / total_branches_count if total_branches_count > 0 else amount
                        desc_final = f"[مصروف عام موزع - نصيب الفرع: {share_per_branch:,.2f} د.ل] {description.strip()}"
                        
                        cur_ex.execute("""
                            INSERT INTO expenses (branch_id, amount, description, is_general_store, expense_date)
                            VALUES (NULL, ?, ?, 1, ?)
                        """, (amount, f"[{target_month}] {desc_final}", expense_date.strftime('%Y-%m-%d')))

                    conn.commit()
                    conn.close()
                    st.success("✅ تمت عملية تسجيل المصروف وتوزيع أثره المالي بنجاح تام!")
                    st.rerun()

    # --- التبويب الثاني: تقارير الفروع وسجل المصروفات مع تصدير Excel ---
    with tab2:
        st.subheader("📋 تقارير ومتابعة مصروفات الفروع")
        
        # 🔍 إضافة فلتر لاختيار فرع معين أو عرض الكل
        report_filter = st.selectbox(
            "عرض مصروفات حسب الفرع:", 
            ["🌐 عرض كل المصروفات (الإجمالي العام)"] + list(branch_dict.keys())
        )

        if report_filter == "🌐 عرض كل المصروفات (الإجمالي العام)":
            query = """
                SELECT 
                    expenses.id AS 'مسلسل', 
                    IFNULL(branches.branch_name, '🌍 مصروف عام للمخزن الرئيسي (موزع)') AS 'الفرع أو الجهة', 
                    expenses.amount AS 'المبلغ الإجمالي (د.ل)', 
                    expenses.description AS 'البيان وتفاصيل التوزيع', 
                    expenses.expense_date AS 'تاريخ التسجيل'
                FROM expenses 
                LEFT JOIN branches ON expenses.branch_id = branches.id 
                ORDER BY expenses.id DESC
            """
            exp_df = pd.read_sql(query, conn)
        else:
            selected_b_id = branch_dict[report_filter]
            query = """
                SELECT 
                    expenses.id AS 'مسلسل', 
                    branches.branch_name AS 'الفرع', 
                    expenses.amount AS 'المبلغ (د.ل)', 
                    expenses.description AS 'البيان', 
                    expenses.expense_date AS 'تاريخ التسجيل'
                FROM expenses 
                JOIN branches ON expenses.branch_id = branches.id 
                WHERE expenses.branch_id = ?
                ORDER BY expenses.id DESC
            """
            exp_df = pd.read_sql(query, conn, params=(selected_b_id,))

        if not exp_df.empty:
            # حساب وإظهار إجمالي المصروفات للفلتر الحالي
            total_filtered_amount = exp_df['المبلغ الإجمالي (د.ل)' if 'المبلغ الإجمالي (د.ل)' in exp_df.columns else 'المبلغ (د.ل)'].sum()
            st.metric(label=f"إجمالي المصروفات ({report_filter})", value=f"{total_filtered_amount:,.2f} د.ل")

            st.dataframe(exp_df, use_container_width=True)

            # 📥 زر تصدير Excel مخصص بحسب الفرع أو الإجمالي
            excel_data = to_excel(exp_df)
            file_suffix = "all_branches" if report_filter.startswith("🌐") else report_filter
            st.download_button(
                label=f"📥 تصدير جدول مصروفات ({report_filter}) إلى Excel",
                data=excel_data,
                file_name=f"expenses_{file_suffix}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

            st.markdown("---")
            st.markdown("### 🗑️ حذف مصروف خاطئ (يتطلب كلمة سر الأدمن)")
            del_id = st.selectbox("اختر مسلسل المصروف المراد حذفه:", exp_df["مسلسل"].tolist())
            
            admin_pass_del = st.text_input("🔒 أدخل كلمة السر لتأكيد الحذف:", type="password", key="exp_del_pass")
            if st.button("🗑️ حذف المصروف المختار", type="primary"):
                role = st.session_state.get("role", "")
                if role in ["Admin", "General_Supervisor"]:
                    user_chk = conn.execute("SELECT id FROM users WHERE id = ? AND password = ?", (st.session_state["user_id"], admin_pass_del)).fetchone()
                    if user_chk:
                        conn.execute("DELETE FROM expenses WHERE id = ?", (del_id,))
                        conn.commit()
                        conn.close()
                        st.success("✅ تم حذف المصروف بنجاح!")
                        st.rerun()
                    else:
                        st.error("❌ كلمة السر غير صحيحة!")
                else:
                    st.error("🚫 ليس لديك صلاحية الحذف!")
        else:
            st.info(f"لا توجد مصروفات مسجلة للفرع المحدد ({report_filter}).")

    conn.close()
