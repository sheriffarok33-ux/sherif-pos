import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    # 🌟 تنسيق الخط الأسود العريض والواضح لكافة عناصر التقارير والجداول
    st.markdown("""
        <style>
        .stDataFrame, .stDataFrame *, div[data-testid="stTable"] *, th, td {
            color: #000000 !important;
            font-family: 'Tajawal', sans-serif !important;
            font-weight: 900 !important;
            font-size: 16px !important;
            text-align: right !important;
        }
        th {
            background-color: #e2e8f0 !important;
            color: #000000 !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h2 style="color: #0f172a;">📊 تقارير الأرباح والخسائر وحركة الأصناف الشاملة</h2>', unsafe_allow_html=True)
    st.markdown("---")

    conn = get_db_connection()
    
    # التحقق من صلاحيات المستخدم (الأدمن والمشرف العام فقط من يريان الحسابات والأرباح المالية الكبرى)
    role = st.session_state.get("role", "")
    is_admin_or_supervisor = role in ["Admin", "General_Supervisor"]

    # جلب الفروع
    branches = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
    b_dict = {b["branch_name"]: b["id"] for b in branches}

    # تبويبات التقارير
    tab_pl, tab_items_rep = st.tabs([
        "💰 قائمة الأرباح والخسائر الشاملة (لكل فرع)", 
        "📦 تقرير تفصيلي للأصناف ومتوسط التكلفة وهامش الربح"
    ])

    # =========================================================================
    # 1. تبويب أرباح وخسائر الفروع (مع فلتر الفروع الدقيق)
    # =========================================================================
    with tab_pl:
        st.markdown("### 📈 الحسابات الختامية وأرباح الفروع")
        st.markdown("تقرير يجمع إجمالي المبيعات، يخصم منها المصروفات، والرواتب والإيجارات لكل فرع على حدة أو إجمالاً.")

        if not is_admin_or_supervisor:
            st.warning("🔒 عذراً، هذا التقرير المالي الشامل مخصص للمدير العام والأدمن فقط لأسباب تتعلق بسرية الأرباح والمصروفات.")
        else:
            if branches:
                # 🌟 إضافة فلتر الفروع هنا
                branch_filter_options = ["🌐 كافة الفروع (إجمالي الشركة)"] + list(b_dict.keys())
                selected_pl_branch = st.selectbox("فلترة التقرير المالي حسب الفرع:", branch_filter_options, key="pl_branch_filter_box")

                # تحديد الفروع المستهدفة بناءً على الفلتر
                if selected_pl_branch == "🌐 كافة الفروع (إجمالي الشركة)":
                    target_branches = branches
                else:
                    target_branches = [b for b in branches if b["branch_name"] == selected_pl_branch]

                pl_data = []
                total_global_sales = 0
                total_global_expenses = 0
                total_global_net = 0

                for b in target_branches:
                    b_id = b["id"]
                    b_name = b["branch_name"]

                    # 1. إجمالي مبيعات الفواتير لهذا الفرع
                    sales_row = conn.execute("SELECT SUM(total_amount) AS total_sales FROM invoices WHERE branch_id = ?", (b_id,)).fetchone()
                    b_sales = sales_row["total_sales"] if sales_row and sales_row["total_sales"] else 0.0

                    # 2. إجمالي المصروفات المسجلة لهذا الفرع (تتضمن إيجارات، رواتب، تشغيلية.. إلخ)
                    try:
                        exp_row = conn.execute("SELECT SUM(amount) AS total_exp FROM expenses WHERE branch_id = ?", (b_id,)).fetchone()
                        b_expenses = exp_row["total_exp"] if exp_row and exp_row["total_exp"] else 0.0
                    except:
                        b_expenses = 0.0

                    # صافي الربح التشغيلي للفرع
                    b_net_profit = b_sales - b_expenses

                    total_global_sales += b_sales
                    total_global_expenses += b_expenses
                    total_global_net += b_net_profit

                    pl_data.append({
                        "اسم الفرع": b_name,
                        "نوع المنشأة": b["branch_type"],
                        "إجمالي المبيعات (د.ل)": f"{b_sales:,.2f}",
                        "إجمالي المصروفات والرواتب والإيجارات (د.ل)": f"{b_expenses:,.2f}",
                        "صافي الربح التقديري (د.ل)": f"{b_net_profit:,.2f}"
                    })

                df_pl = pd.DataFrame(pl_data)
                st.dataframe(df_pl, use_container_width=True, hide_index=True)

                # عرض إجمالي النتائج المعروضة
                label_text = "ملخص الأداء المالي العام لكل الفروع:" if selected_pl_branch == "🌐 كافة الفروع (إجمالي الشركة)" else f"ملخص الأداء المالي للفرع ({selected_pl_branch}):"
                
                st.markdown(f"""
                    <div style="background: #e2e8f0; padding: 15px; border-radius: 10px; border: 1px solid #94a3b8; margin-top: 15px;">
                        <h4 style="margin:0; color: #0f172a;">🏢 {label_text}</h4>
                        <p style="margin: 5px 0; color: #000000;">💰 إجمالي المبيعات: <b>{total_global_sales:,.2f} د.ل</b></p>
                        <p style="margin: 5px 0; color: #000000;">💸 إجمالي المصروفات والرواتب والإيجارات: <b>{total_global_expenses:,.2f} د.ل</b></p>
                        <p style="margin: 0; color: #0284c7; font-size: 19px;">📈 صافي الربح الإجمالي: <b>{total_global_net:,.2f} د.ل</b></p>
                    </div>
                """, unsafe_allow_html=True)
            else:
                st.info("لا توجد فروع مسجلة لعرض تقارير الأرباح.")

    # =========================================================================
    # 2. تقرير الأصناف ومتوسط التكلفة وهامش الربح
    # =========================================================================
    with tab_items_rep:
        st.markdown("### 📦 تقرير مخزون الأصناف ومتوسط التكلفة وهامش الربح")
        
        filter_b = st.selectbox("اختر الفرع لعرض أصنافه:", ["كل الفروع"] + list(b_dict.keys()), key="rep_branch_filter")

        if filter_b == "كل الفروع":
            query = """
                SELECT items.item_code AS 'كود الصنف', 
                       items.item_name AS 'اسم الصنف', 
                       branches.branch_name AS 'الفرع', 
                       items.quantity AS 'الكمية المتاحة', 
                       items.buy_price AS 'سعر الشراء الأساسي', 
                       items.avg_cost AS 'متوسط التكلفة الفعلي', 
                       items.sale_price AS 'سعر البيع الحالي'
                FROM items 
                JOIN branches ON items.branch_id = branches.id
            """
            df_items = pd.read_sql(query, conn)
        else:
            b_id_sel = b_dict[filter_b]
            query = """
                SELECT items.item_code AS 'كود الصنف', 
                       items.item_name AS 'اسم الصنف', 
                       branches.branch_name AS 'الفرع', 
                       items.quantity AS 'الكمية المتاحة', 
                       items.buy_price AS 'سعر الشراء الأساسي', 
                       items.avg_cost AS 'متوسط التكلفة الفعلي', 
                       items.sale_price AS 'سعر البيع الحالي'
                FROM items 
                JOIN branches ON items.branch_id = branches.id
                WHERE branches.id = ?
            """
            df_items = pd.read_sql(query, conn, params=(b_id_sel,))

        if not df_items.empty:
            if is_admin_or_supervisor:
                cost_col = df_items['متوسط التكلفة الفعلي'].apply(lambda x: x if x > 0 else 0)
                df_items['هامش الربح (د.ل)'] = df_items['سعر البيع الحالي'] - cost_col
                df_items['نسبة هامش الربح (%)'] = df_items.apply(
                    lambda row: f"{((row['سعر البيع الحالي'] - row['متوسط التكلفة الفعلي']) / row['سعر البيع الحالي'] * 100):.1f}%" 
                    if row['سعر البيع الحالي'] > 0 and row['متوسط التكلفة الفعلي'] > 0 else "0.0%", 
                    axis=1
                )
                st.success("🔒 يتم عرض بيانات متوسط التكلفة وهامش الربح بدقة (صلاحية الأدمن مفعلة).")
            else:
                df_items = df_items.drop(columns=['سعر الشراء الأساسي', 'متوسط التكلفة الفعلي'], errors='ignore')
                st.info("ℹ️ ملاحظة: أعمدة التكاليف وهامش الربح محجوبة لغير الأدمن.")

            st.dataframe(df_items, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد أصناف مسجلة في هذا الفرع.")

    conn.close()
