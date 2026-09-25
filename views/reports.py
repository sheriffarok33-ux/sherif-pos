import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.title("📊 تقارير الأصناف والأرباح")
    st.markdown("---")

    # التحقق من صلاحيات المستخدم (الأدمن والمدير العام فقط)
    role = st.session_state.get("role", "")
    is_admin_or_supervisor = role in ["Admin", "General_Supervisor"]

    if not is_admin_or_supervisor:
        st.error("🚫 عذراً، هذا التقرير مخصص حصرياً للمدير العام والأدمن للاطلاع على الحسابات والأرباح.")
        return

    # جلب الفروع لعرض التقارير بناءً عليها
    conn = get_db_connection()
    branches = conn.execute("SELECT * FROM branches").fetchall()
    conn.close()

    if not branches:
        st.warning("⚠️ لا توجد فروع مسجلة في النظام حالياً.")
        return

    # خيارات تصفية الفرع
    branch_options = {b["branch_name"]: b["id"] for b in branches}
    selected_branch_name = st.selectbox("اختر الفرع لعرض تقرير الأصناف:", ["كل الفروع"] + list(branch_options.keys()))

    # جلب بيانات الأصناف من قاعدة البيانات
    conn = get_db_connection()
    if selected_branch_name == "كل الفروع":
        query = "SELECT * FROM items"
        df_items = pd.read_sql(query, conn)
    else:
        b_id = branch_options[selected_branch_name]
        query = "SELECT * FROM items WHERE branch_id = ?"
        df_items = pd.read_sql(query, conn, params=(b_id,))
    conn.close()

    if df_items.empty:
        st.info("ℹ️ لا توجد أصناف مسجلة في هذا الفرع حالياً.")
        return

    # حسابات متوسط التكلفة وهامش الربح للأدمن والمدير العام
    # المعادلة: هامش الربح بالقيمة = سعر البيع - متوسط التكلفة
    # نسبة الربح % = ((سعر البيع - متوسط التكلفة) / سعر البيع) * 100
    
    df_items["متوسط التكلفة"] = df_items["avg_cost"]
    df_items["سعر البيع"] = df_items["sale_price"]
    
    # حساب الربح بالقيمة
    df_items["هامش الربح (د.ل)"] = df_items["سعر البيع"] - df_items["متوسط التكلفة"]
    
    # حساب نسبة الربح تجنبًا للقسمة على صفر
    df_items["نسبة الربح (%)"] = df_items.apply(
        lambda row: round(((row["سعر البيع"] - row["متوسط التكلفة"]) / row["سعر البيع"]) * 100, 2) 
        if row["سعر البيع"] > 0 else 0, 
        axis=1
    )

    # تنظيم الأعمدة المعروضة لتكون احترافية
    display_columns = [
        "item_code", "item_name", "quantity", 
        "متوسط التكلفة", "سعر البيع", 
        "هامش الربح (د.ل)", "نسبة الربح (%)"
    ]
    
    # التأكد من عدم وجود أعمدة ناقصة
    available_cols = [col for col in display_columns if col in df_items.columns]
    
    st.subheader(f"📋 جدول تحليل المخزون والأرباح ({selected_branch_name})")
    
    # عرض الجدول مع تنسيق البيانات الماليّة
    st.dataframe(
        df_items[available_cols].rename(columns={
            "item_code": "كود الصنف",
            "item_name": "اسم الصنف",
            "quantity": "الكمية المتاحة"
        }),
        use_container_width=True,
        hide_index=True
    )

    # إحصائيات سريعة للأدمن والمدير العام
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("إجمالي عدد الأصناف", len(df_items))
    with col2:
        total_inventory_value = (df_items["quantity"] * df_items["متوسط التكلفة"]).sum()
        st.metric("إجمالي قيمة المخزون (تكلفة)", f"{total_inventory_value:,.2f} د.ل")
    with col3:
        avg_profit_margin = df_items["نسبة الربح (%)"].mean()
        st.metric("متوسط نسبة الربح العامة", f"{avg_profit_margin:,.2f} %")
