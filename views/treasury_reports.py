from datetime import date
import streamlit as st
import pandas as pd
from database import get_db_connection
from views.ui_common import back_button


def _scalar(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return float((row[0] if row else 0) or 0)


def show_page():
    back_button(key="back_treasury_reports")
    st.header("🏦 الخزينة وجميع التقارير — الملخص المالي")
    st.info("المؤشرات هنا للمتابعة. تقارير المبيعات والمشتريات والمخزون والإنتاج والمصروفات متاحة من نفس القسم في القائمة الرئيسية.")

    conn = get_db_connection()
    try:
        branches = conn.execute("SELECT id, branch_name, branch_type FROM branches ORDER BY id").fetchall()
        names = ["كل الفروع"] + [b["branch_name"] for b in branches]
        selected = st.selectbox("الفرع / المخزن:", names, key="treasury_report_branch")
        branch_id = None if selected == "كل الفروع" else next(b["id"] for b in branches if b["branch_name"] == selected)
        where = "" if branch_id is None else " WHERE branch_id=?"
        params = () if branch_id is None else (branch_id,)

        stock_cost = _scalar(conn, f"SELECT COALESCE(SUM(quantity * CASE WHEN COALESCE(avg_cost,0)>0 THEN avg_cost ELSE COALESCE(buy_price,0) END),0) FROM items{where}", params)
        stock_sale = _scalar(conn, f"SELECT COALESCE(SUM(quantity * COALESCE(sale_price,0)),0) FROM items{where}", params)

        c1,c2,c3 = st.columns(3)
        c1.metric("📦 إجمالي التكلفة الكلية للمخزون", f"{stock_cost:,.2f} د.ل")
        c2.metric("🏷️ قيمة المخزون بسعر البيع", f"{stock_sale:,.2f} د.ل")
        c3.metric("📈 الربح المتوقع بالمخزون", f"{stock_sale-stock_cost:,.2f} د.ل")
        st.caption("الربح المتوقع بالمخزون ليس قائمة أرباح وخسائر محاسبية؛ هو فرق قيمة المخزون الحالية بسعر البيع عن تكلفته.")

        st.markdown("### 📊 الربح والخسارة لفترة")
        d1,d2 = st.columns(2)
        start = d1.date_input("من تاريخ", value=date.today().replace(day=1), key="pl_from")
        end = d2.date_input("إلى تاريخ", value=date.today(), key="pl_to")
        bp = []
        bw = ""
        if branch_id is not None:
            bw = " AND branch_id=?"
            bp.append(branch_id)
        sales = _scalar(conn, f"SELECT COALESCE(SUM(total_amount),0) FROM invoices WHERE date(created_at) BETWEEN ? AND ?{bw}", (str(start),str(end),*bp))
        expenses = _scalar(conn, f"SELECT COALESCE(SUM(amount),0) FROM expenses WHERE date(expense_date) BETWEEN ? AND ?{bw}", (str(start),str(end),*bp))
        revenues = _scalar(conn, f"SELECT COALESCE(SUM(amount),0) FROM revenues WHERE date(revenue_date) BETWEEN ? AND ?{bw}", (str(start),str(end),*bp))
        # Current schema does not persist invoice COGS reliably; show an operational result and label it clearly.
        result = sales + revenues - expenses
        p1,p2,p3,p4 = st.columns(4)
        p1.metric("المبيعات", f"{sales:,.2f} د.ل")
        p2.metric("إيرادات أخرى", f"{revenues:,.2f} د.ل")
        p3.metric("المصروفات", f"{expenses:,.2f} د.ل")
        p4.metric("النتيجة التشغيلية قبل تكلفة البضاعة المباعة", f"{result:,.2f} د.ل")
        st.warning("حتى لا نعطي رقم ربح محاسبي مضلل: قاعدة البيانات الحالية لا تحفظ تكلفة البضاعة المباعة لكل فاتورة بشكل كامل. لذلك التقرير يعرض النتيجة قبل COGS إلى أن نربط التكلفة التاريخية بالفواتير.")

        report_html = f"""<html dir='rtl'><head><meta charset='utf-8'><style>body{{font-family:Arial;padding:25px;direction:rtl}} table{{width:100%;border-collapse:collapse}}td{{border:1px solid #999;padding:9px}}@media print{{.no-print{{display:none}}}}</style></head><body><h2 style='text-align:center'>ملخص الخزينة والتقارير</h2><p>الفترة: {start} إلى {end} — {selected}</p><table><tr><td>تكلفة المخزون</td><td>{stock_cost:,.2f} د.ل</td></tr><tr><td>قيمة المخزون بسعر البيع</td><td>{stock_sale:,.2f} د.ل</td></tr><tr><td>المبيعات</td><td>{sales:,.2f} د.ل</td></tr><tr><td>إيرادات أخرى</td><td>{revenues:,.2f} د.ل</td></tr><tr><td>المصروفات</td><td>{expenses:,.2f} د.ل</td></tr><tr><td>النتيجة قبل تكلفة البضاعة المباعة</td><td>{result:,.2f} د.ل</td></tr></table><div class='no-print'><button onclick='window.print()'>🖨️ طباعة</button></div></body></html>"""
        q1,q2=st.columns(2)
        if q1.button("👁️ معاينة التقرير", use_container_width=True, key="preview_treasury_report"):
            st.session_state["show_treasury_report_preview"] = True
        if q2.button("🖨️ طباعة التقرير", use_container_width=True, key="print_treasury_report"):
            st.session_state["show_treasury_report_preview"] = True
        if st.session_state.get("show_treasury_report_preview"):
            st.components.v1.html(report_html, height=520, scrolling=True)

        rows = conn.execute("SELECT branch_name, branch_type FROM branches ORDER BY id").fetchall()
        if rows:
            st.markdown("### 🏢 الفروع والمخازن المشمولة")
            st.dataframe(pd.DataFrame([{"الاسم":r["branch_name"],"النوع":r["branch_type"]} for r in rows]), hide_index=True, use_container_width=True)
    finally:
        conn.close()
