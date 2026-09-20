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
    st.info("💡 توزيع مصروفات المخزن الرئيسي حصرياً على الفروع التشغيلية بالتساوي مع ظهور الحصة لكل فرع بدقة، والمخزن الرئيسي بصفر.")

    conn = get_db_connection()
    branches = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
    
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع أولاً قبل تسكين المصروفات.")
        conn.close()
        return

    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    operational_branches = [b for b in branches if b["branch_type"] != "مخزن"]

    tab1, tab2 = st.tabs(["➕ تسجيل مصروف جديد", "📋 أرشيف المصروفات وتقارير الفروع (تصدير Excel)"])

    # --- التبويب الأول: تسجيل مصروف جديد مع التوزيع الصحيح ---
    with tab1:
        st.subheader("✍️ إدخال مصروف جديد وتوزيع الحصص")
        
        with st.form("expense_advanced_form", clear_on_submit=True):
            exp_scope = st.radio(
                "نطاق المصروف:", 
                ["📍 خاص بفرع أو مخزن معين", "🌍 مصروف عام للمخزن الرئيسي (يُقسَم حصرياً وبالتساوي على الفروع التشغيلية)"]
            )
            
            sel_branch_name = ""
            if "خاص بفرع" in exp_scope:
                sel_branch_name = st.selectbox("اختر الفرع أو المخزن المستفيد:", list(branch_dict.keys()))

            col_a, col_b = st.columns(2)
            with col_a:
                amount = st.number_input("المبلغ الإجمالي (د.ل):", min_value=0.0, value=0.0, step=0.5)
                expense_type = st.selectbox("نوع المصروف:", ["تشغيلي عادي", "إيجار / مصروف مقدم (لفترة محددة)"])
            with col_b:
                current_year_month = datetime.now().strftime('%Y-%m')
                target_month = st.text_input("شهر الاستحقاق المحاسبي (YYYY-MM):", value=current_year_month)
                expense_date = st.date_input("تاريخ التسجيل الفعلي:", value=datetime.now())

            description = st.text_input("البيان أو وصف المصروف (مثلاً: صيانة سيارة المخزن، فاتورة كهرباء...):")

            advance_end_date = None
            if "إيجار" in expense_type:
                st.markdown("---")
                st.warning("📌 إدارة الإيجارات والمصروفات المقدمة:")
                advance_end_date = st.text_input("تاريخ انتهاء فترة التغطية المقدمة (مثال: 2027-06-30):", value="")

            submitted_exp = st.form_submit_button("💾 حفظ وترحيل وتوزيع المصروف", type="primary", use_container_width=True)

            if submitted_exp:
                if amount <= 0 or not description.strip():
                    st.error("⚠️ يجب إدخال مبلغ صحيح ووصف واضح للمصروف!")
                else:
                    cur_ex = conn.cursor()

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
                        op_count = len(operational_branches)
                        if op_count == 0:
                            st.error("❌ عذراً، لا توجد فروع تشغيلية مسجلة لتوزيع المصروف عليها!")
                            conn.close()
                            st.stop()
                        
                        share_per_branch = amount / op_count
                        
                        # توزيع حصة متساوية لكل فرع تشغيلي وتسكينها باسم الفرع مباشرة ليظهر المبلغ بدقة
                        for op_b in operational_branches:
                            branch_desc = f"[{target_month}] [مصروف عام صادر من المخزن الرئيسي - إجمالي البند: {amount} د.ل] {description.strip()}"
                            cur_ex.execute("""
                                INSERT INTO expenses (branch_id, amount, description, is_general_store, expense_date)
                                VALUES (?, ?, ?, 1, ?)
                            """, (op_b["id"], share_per_branch, branch_desc, expense_date.strftime('%Y-%m-%d')))

                    conn.commit()
                    conn.close()
                    st.success("✅ تمت عملية تسجيل المصروف وتوزيعه الفعلي على الفروع التشغيلية بنجاح!")
                    st.rerun()

    # --- التبويب الثاني: التقارير والعرض ---
    with tab2:
        st.subheader("📋 تقارير ومتابعة مصروفات الفروع")
        
        report_filter = st.selectbox(
            "عرض مصروفات حسب الفرع:", 
            ["🌐 عرض كل المصروفات (الإجمالي العام)"] + list(branch_dict.keys())
        )

        if report_filter == "🌐 عرض كل المصروفات (الإجمالي العام)":
            query = """
                SELECT 
                    expenses.id AS 'مسلسل', 
                    branches.branch_name AS 'الفرع المستفيد', 
                    expenses.amount AS 'المبلغ الموزع (د.ل)', 
                    expenses.description AS 'البيان', 
                    expenses.expense_date AS 'تاريخ التسجيل'
                FROM expenses 
                JOIN branches ON expenses.branch_id = branches.id 
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
            total_filtered_amount = exp_df['المبلغ الموزع (د.ل)' if 'المبلغ الموزع (د.ل)' in exp_df.columns else 'المبلغ (د.ل)'].sum()
            st.metric(label=f"إجمالي المصروفات للجهة ({report_filter})", value=f"{total_filtered_amount:,.2f} د.ل")

            st.dataframe(exp_df, use_container_width=True)

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
