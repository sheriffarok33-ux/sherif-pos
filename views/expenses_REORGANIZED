import streamlit as st
import pandas as pd
import io
from datetime import datetime
from database import get_db_connection


# ============================================================
# تحويل DataFrame إلى Excel
# ============================================================

def to_excel(df):
    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        df.to_excel(
            writer,
            index=False,
            sheet_name="Financial_Report"
        )

    return output.getvalue()


# ============================================================
# جلب الفروع
# ============================================================

def get_branches():

    conn = None

    try:
        conn = get_db_connection()

        return conn.execute(
            """
            SELECT
                id,
                branch_name,
                branch_type
            FROM branches
            ORDER BY id ASC
            """
        ).fetchall()

    finally:
        if conn:
            conn.close()


# ============================================================
# تسجيل مصروف خاص بفرع
# ============================================================

def add_branch_expense(
    branch_id,
    amount,
    description,
    target_month,
    expense_date,
    expense_type,
    advance_end_date
):

    conn = None

    try:
        conn = get_db_connection()

        if amount <= 0:
            raise ValueError(
                "قيمة المصروف يجب أن تكون أكبر من صفر."
            )

        if not description.strip():
            raise ValueError(
                "يجب إدخال وصف للمصروف."
            )

        desc_final = description.strip()

        if (
            "إيجار" in expense_type
            and advance_end_date.strip()
        ):
            desc_final = (
                f"[إيجار مقدم يغطي حتى "
                f"{advance_end_date.strip()}] "
                f"{desc_final}"
            )

        final_description = (
            f"[{target_month}] "
            f"{desc_final}"
        )

        conn.execute(
            """
            INSERT INTO expenses
            (
                branch_id,
                amount,
                description,
                is_general_store,
                expense_date
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                branch_id,
                amount,
                final_description,
                0,
                expense_date.strftime(
                    "%Y-%m-%d"
                )
            )
        )

        conn.commit()

        st.success(
            "✅ تم تسجيل المصروف بنجاح."
        )

        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تسجيل المصروف."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# توزيع مصروف عام على الفروع التشغيلية
# ============================================================

def add_general_expense(
    operational_branches,
    amount,
    description,
    target_month,
    expense_date
):

    conn = None

    try:
        conn = get_db_connection()

        if amount <= 0:
            raise ValueError(
                "قيمة المصروف يجب أن تكون أكبر من صفر."
            )

        if not description.strip():
            raise ValueError(
                "يجب إدخال وصف للمصروف."
            )

        if not operational_branches:
            raise ValueError(
                "لا توجد فروع تشغيلية "
                "لتوزيع المصروف عليها."
            )

        op_count = len(
            operational_branches
        )

        share_per_branch = (
            float(amount) / op_count
        )

        for branch in operational_branches:

            branch_desc = (
                f"[{target_month}] "
                f"[مصروف عام صادر من المخزن الرئيسي "
                f"- إجمالي البند: "
                f"{amount:.2f} د.ل] "
                f"{description.strip()}"
            )

            conn.execute(
                """
                INSERT INTO expenses
                (
                    branch_id,
                    amount,
                    description,
                    is_general_store,
                    expense_date
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    branch["id"],
                    share_per_branch,
                    branch_desc,
                    1,
                    expense_date.strftime(
                        "%Y-%m-%d"
                    )
                )
            )

        conn.commit()

        st.success(
            "✅ تم تسجيل المصروف العام "
            "وتوزيعه بالتساوي على "
            "الفروع التشغيلية بنجاح."
        )

        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تسجيل وتوزيع المصروف."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# تسجيل إيراد
# ============================================================

def add_revenue(
    branch_id,
    revenue_source,
    amount,
    notes,
    revenue_date
):

    conn = None

    try:
        conn = get_db_connection()

        if amount <= 0:
            raise ValueError(
                "قيمة الإيراد يجب أن تكون أكبر من صفر."
            )

        if not revenue_source.strip():
            raise ValueError(
                "يجب إدخال مصدر الإيراد."
            )

        description = revenue_source.strip()

        if notes.strip():
            description = (
                f"{description} - {notes.strip()}"
            )

        conn.execute(
            """
            INSERT INTO revenues
            (
                branch_id,
                revenue_source,
                amount,
                notes,
                description,
                revenue_date
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                branch_id,
                revenue_source.strip(),
                amount,
                notes.strip(),
                description,
                revenue_date.strftime("%Y-%m-%d")
            )
        )

        conn.commit()

        st.success(
            "✅ تم تسجيل الإيراد بنجاح "
            "في خزينة الفرع / المخزن."
        )

        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تسجيل الإيراد."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# تحميل المصروفات
# ============================================================

def load_expenses(branch_id=None):

    conn = None

    try:
        conn = get_db_connection()

        if branch_id is None:

            rows = conn.execute(
                """
                SELECT
                    expenses.id,
                    branches.branch_name,
                    expenses.amount,
                    expenses.description,
                    expenses.expense_date
                FROM expenses

                JOIN branches
                    ON expenses.branch_id =
                       branches.id

                ORDER BY expenses.id DESC
                """
            ).fetchall()

        else:

            rows = conn.execute(
                """
                SELECT
                    expenses.id,
                    branches.branch_name,
                    expenses.amount,
                    expenses.description,
                    expenses.expense_date
                FROM expenses

                JOIN branches
                    ON expenses.branch_id =
                       branches.id

                WHERE expenses.branch_id = ?

                ORDER BY expenses.id DESC
                """,
                (branch_id,)
            ).fetchall()

        data = []

        for row in rows:

            data.append(
                {
                    "مسلسل":
                        row["id"],

                    "الفرع":
                        row["branch_name"],

                    "المبلغ (د.ل)":
                        float(
                            row["amount"] or 0
                        ),

                    "البيان":
                        row["description"],

                    "تاريخ التسجيل":
                        row["expense_date"]
                }
            )

        return pd.DataFrame(data)

    finally:

        if conn:
            conn.close()


# ============================================================
# حذف مصروف
# ============================================================

def delete_expense(
    expense_id,
    password
):

    conn = None

    try:
        conn = get_db_connection()

        role = st.session_state.get(
            "role",
            ""
        )

        user_id = st.session_state.get(
            "user_id"
        )

        if role not in [
            "Admin",
            "General_Supervisor"
        ]:

            raise PermissionError(
                "ليس لديك صلاحية حذف المصروفات."
            )

        if not user_id:

            raise PermissionError(
                "تعذر تحديد المستخدم الحالي."
            )

        user_chk = conn.execute(
            """
            SELECT id
            FROM users
            WHERE id = ?
            AND password = ?
            """,
            (
                user_id,
                password
            )
        ).fetchone()

        if not user_chk:

            raise PermissionError(
                "كلمة المرور غير صحيحة."
            )

        expense = conn.execute(
            """
            SELECT id
            FROM expenses
            WHERE id = ?
            FOR UPDATE
            """,
            (expense_id,)
        ).fetchone()

        if not expense:

            raise ValueError(
                "المصروف غير موجود "
                "أو تم حذفه مسبقاً."
            )

        conn.execute(
            """
            DELETE FROM expenses
            WHERE id = ?
            """,
            (expense_id,)
        )

        conn.commit()

        st.success(
            "✅ تم حذف المصروف بنجاح."
        )

        st.rerun()

    except PermissionError as e:

        if conn:
            conn.rollback()

        st.error(
            f"🚫 {e}"
        )

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر حذف المصروف."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# الصفحة الرئيسية
# ============================================================

def show_page():

    st.header(
        "💰 إدارة وتوزيع المصروفات "
        "والإيرادات الذكية"
    )

    st.info(
        "💡 توزيع مصروفات المخزن الرئيسي "
        "حصرياً على الفروع التشغيلية بالتساوي، "
        "مع إمكانية تسجيل المصروفات الخاصة "
        "والإيرادات ومراجعة الأرشيف."
    )

    # ========================================================
    # تحميل الفروع
    # ========================================================

    try:
        branches = get_branches()

    except Exception as e:

        st.error(
            "❌ تعذر تحميل الفروع."
        )

        st.code(str(e))

        return

    if not branches:

        st.warning(
            "⚠️ يرجى إضافة فروع أولاً "
            "قبل تسجيل المصروفات أو الإيرادات."
        )

        return

    branch_dict = {
        b["branch_name"]: b["id"]
        for b in branches
    }

    operational_branches = [
        b
        for b in branches
        if b["branch_type"] != "مخزن"
    ]

    # ========================================================
    # اختيار القسم
    # ========================================================

    selected_mode = st.radio(
        "🎯 اختر القسم المطلوب:",
        [
            "➕ تسجيل مصروف جديد",
            "💵 تسجيل إيراد جديد",
            "📋 أرشيف المصروفات وتقارير الفروع (تصدير Excel)"
        ],
        horizontal=True
    )

    st.markdown("---")

    # ========================================================
    # 1 - تسجيل مصروف
    # ========================================================

    if selected_mode.startswith("➕"):

        st.subheader(
            "✍️ إدخال مصروف جديد "
            "وتوزيع الحصص"
        )

        with st.form(
            "expense_advanced_form",
            clear_on_submit=True
        ):

            exp_scope = st.radio(
                "نطاق المصروف:",
                [
                    "📍 خاص بفرع أو مخزن معين",
                    "🌍 مصروف عام للمخزن الرئيسي "
                    "(يُقسَم حصرياً وبالتساوي "
                    "على الفروع التشغيلية)"
                ]
            )

            sel_branch_name = None

            if "خاص بفرع" in exp_scope:

                sel_branch_name = st.selectbox(
                    "اختر الفرع أو المخزن المستفيد:",
                    list(branch_dict.keys())
                )

            col_a, col_b = st.columns(2)

            with col_a:

                amount = st.number_input(
                    "المبلغ الإجمالي (د.ل):",
                    min_value=0.0,
                    value=0.0,
                    step=0.5,
                    format="%.2f"
                )

                expense_type = st.selectbox(
                    "نوع المصروف:",
                    [
                        "تشغيلي عادي",
                        "إيجار / مصروف مقدم "
                        "(لفترة محددة)"
                    ]
                )

            with col_b:

                current_year_month = (
                    datetime.now().strftime(
                        "%Y-%m"
                    )
                )

                target_month = st.text_input(
                    "شهر الاستحقاق المحاسبي "
                    "(YYYY-MM):",
                    value=current_year_month
                )

                expense_date = st.date_input(
                    "تاريخ التسجيل الفعلي:",
                    value=datetime.now()
                )

            description = st.text_input(
                "البيان أو وصف المصروف "
                "(مثلاً: صيانة سيارة المخزن، "
                "فاتورة كهرباء...):"
            )

            advance_end_date = ""

            if "إيجار" in expense_type:

                st.markdown("---")

                st.warning(
                    "📌 إدارة الإيجارات "
                    "والمصروفات المقدمة:"
                )

                advance_end_date = st.text_input(
                    "تاريخ انتهاء فترة التغطية "
                    "المقدمة "
                    "(مثال: 2027-06-30):",
                    value=""
                )

            submitted_exp = (
                st.form_submit_button(
                    "💾 حفظ وترحيل وتوزيع المصروف",
                    type="primary",
                    use_container_width=True
                )
            )

        if submitted_exp:

            if (
                amount <= 0
                or not description.strip()
            ):

                st.error(
                    "⚠️ يجب إدخال مبلغ صحيح "
                    "ووصف واضح للمصروف."
                )

            elif "خاص بفرع" in exp_scope:

                branch_id = branch_dict[
                    sel_branch_name
                ]

                add_branch_expense(
                    branch_id,
                    amount,
                    description,
                    target_month,
                    expense_date,
                    expense_type,
                    advance_end_date
                )

            else:

                add_general_expense(
                    operational_branches,
                    amount,
                    description,
                    target_month,
                    expense_date
                )

    # ========================================================
    # 2 - تسجيل إيراد
    # ========================================================

    elif selected_mode.startswith("💵"):

        st.subheader(
            "💵 تسجيل إيراد جديد "
            "(خارجي أو خدمي)"
        )

        with st.form(
            "revenue_form_new",
            clear_on_submit=True
        ):

            rev_branch = st.selectbox(
                "الفرع أو المخزن "
                "المستفيد من الإيراد:",
                list(branch_dict.keys())
            )

            rev_source = st.text_input(
                "مصدر الإيراد "
                "(مثال: بيع خردة، "
                "إيراد خدمات، "
                "أرباح رأسمالية...):"
            )

            rev_amount = st.number_input(
                "مبلغ الإيراد (د.ل):",
                min_value=0.0,
                step=0.5,
                format="%.2f"
            )

            rev_date = st.date_input(
                "تاريخ الإيراد:",
                value=datetime.now(),
                key="revenue_date"
            )

            rev_notes = st.text_area(
                "ملاحظات إضافية:"
            )

            submit_rev = (
                st.form_submit_button(
                    "💾 حفظ وتسجيل الإيراد",
                    type="primary",
                    use_container_width=True
                )
            )

        if submit_rev:

            if (
                rev_amount <= 0
                or not rev_source.strip()
            ):

                st.warning(
                    "⚠️ يرجى إدخال مصدر "
                    "الإيراد ومبلغ صحيح."
                )

            else:

                b_id = branch_dict[
                    rev_branch
                ]

                add_revenue(
                    b_id,
                    rev_source,
                    rev_amount,
                    rev_notes,
                    rev_date
                )

    # ========================================================
    # 3 - الأرشيف والتقارير
    # ========================================================

    elif selected_mode.startswith("📋"):

        st.subheader(
            "📋 تقارير ومتابعة "
            "مصروفات الفروع"
        )

        report_filter = st.selectbox(
            "عرض مصروفات حسب الفرع:",
            [
                "🌐 عرض كل المصروفات "
                "(الإجمالي العام)"
            ]
            + list(branch_dict.keys())
        )

        try:

            if report_filter.startswith(
                "🌐"
            ):

                exp_df = load_expenses()

            else:

                selected_b_id = (
                    branch_dict[
                        report_filter
                    ]
                )

                exp_df = load_expenses(
                    selected_b_id
                )

        except Exception as e:

            st.error(
                "❌ تعذر تحميل تقرير "
                "المصروفات."
            )

            st.code(str(e))

            exp_df = pd.DataFrame()

        if not exp_df.empty:

            total_filtered_amount = float(
                exp_df[
                    "المبلغ (د.ل)"
                ].sum()
            )

            st.metric(
                label=(
                    "إجمالي المصروفات للجهة "
                    f"({report_filter})"
                ),
                value=(
                    f"{total_filtered_amount:,.2f} "
                    "د.ل"
                )
            )

            st.dataframe(
                exp_df,
                use_container_width=True,
                hide_index=True
            )

            # ------------------------------------------------
            # Excel
            # ------------------------------------------------

            excel_data = to_excel(
                exp_df
            )

            if report_filter.startswith(
                "🌐"
            ):

                file_suffix = (
                    "all_branches"
                )

            else:

                file_suffix = (
                    report_filter
                    .replace("/", "-")
                    .replace("\\", "-")
                )

            st.download_button(
                label=(
                    "📥 تصدير جدول مصروفات "
                    f"({report_filter}) إلى Excel"
                ),
                data=excel_data,
                file_name=(
                    f"expenses_{file_suffix}_"
                    f"{datetime.now().strftime('%Y%m%d')}"
                    ".xlsx"
                ),
                mime=(
                    "application/vnd.openxmlformats-"
                    "officedocument.spreadsheetml.sheet"
                ),
                use_container_width=True
            )

            # ------------------------------------------------
            # حذف مصروف
            # ------------------------------------------------

            st.markdown("---")

            st.markdown(
                "### 🗑️ حذف مصروف خاطئ "
                "(يتطلب كلمة مرور)"
            )

            del_id = st.selectbox(
                "اختر مسلسل المصروف "
                "المراد حذفه:",
                exp_df["مسلسل"].tolist()
            )

            admin_pass_del = st.text_input(
                "🔒 أدخل كلمة المرور "
                "لتأكيد الحذف:",
                type="password",
                key="exp_del_pass"
            )

            if st.button(
                "🗑️ حذف المصروف المختار",
                type="primary"
            ):

                delete_expense(
                    del_id,
                    admin_pass_del
                )

        else:

            st.info(
                f"لا توجد مصروفات مسجلة "
                f"للجهة المحددة "
                f"({report_filter})."
            )
