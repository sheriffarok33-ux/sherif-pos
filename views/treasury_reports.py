_PAGE_ERROR_UI_REVISION = 68
from views.test_branch_policy import report_predicate, report_branch_ids
from views.number_format import decimal_display
from datetime import date
from html import escape as _html_escape
import streamlit as st
import pandas as pd
from database import get_db_connection
from views.ui_common import back_button
from views.scoped_permissions import scoped_branch_ids


def _scalar(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return float((row[0] if row else 0) or 0)



def _money_display(value):
    """Display-only money formatting: 6828,54 د.ل."""
    return f"{decimal_display(value, 2)} د.ل"


def _money_metric(label, value):
    import html
    exact = _money_display(value)
    st.markdown(
        '<div style="direction:rtl;text-align:right;min-height:75px;padding:4px 0">'
        f'<div style="font-size:14px;font-weight:600">{html.escape(label)}</div>'
        f'<div style="font-size:20px;font-weight:750;line-height:1.6;direction:ltr;text-align:right;unicode-bidi:isolate">{html.escape(exact)}</div>'
        '</div>', unsafe_allow_html=True
    )


def _money_print(value):
    import html
    return f'<span dir="ltr">{html.escape(_money_display(value))}</span>'

def show_page():
    back_button(key="back_treasury_reports")
    st.header("🏦 الخزينة وجميع التقارير — الملخص المالي")
    st.info("المؤشرات هنا للمتابعة. تقارير المبيعات والمشتريات والمخزون والإنتاج والمصروفات متاحة من نفس القسم في القائمة الرئيسية.")

    conn = get_db_connection()
    try:
        branches = conn.execute("SELECT id, branch_name, branch_type FROM branches ORDER BY id").fetchall()
        role = str(st.session_state.get("role") or "")
        is_global_admin = role in ("Super_Admin", "Admin")
        if not is_global_admin:
            granted = scoped_branch_ids(conn, st.session_state.get("user_id"), "treasury_report_view")
            home_branch = st.session_state.get("branch_id")
            if home_branch is not None:
                granted.add(int(home_branch))
            branches = [b for b in branches if int(b["id"]) in granted]
            if not branches:
                st.warning("لا توجد فروع مصرح بعرض ملخصها المالي.")
                return
        names = (["كل الفروع"] if is_global_admin else []) + [b["branch_name"] for b in branches]
        selected = st.selectbox("الفرع / المخزن:", names, key="treasury_report_branch")
        branch_id = None if selected == "كل الفروع" else next(b["id"] for b in branches if b["branch_name"] == selected)
        predicate, params = report_predicate(branch_id)
        where = " WHERE "+predicate

        stock_cost = _scalar(conn, f"SELECT COALESCE(SUM(quantity * CASE WHEN COALESCE(avg_cost,0)>0 THEN avg_cost ELSE COALESCE(buy_price,0) END),0) FROM items{where}", params)
        stock_sale = _scalar(conn, f"SELECT COALESCE(SUM(quantity * COALESCE(sale_price,0)),0) FROM items{where}", params)

        c1,c2,c3 = st.columns(3)
        _money_metric("📦 إجمالي التكلفة الكلية للمخزون", stock_cost)
        _money_metric("🏷️ قيمة المخزون بسعر البيع", stock_sale)
        _money_metric("📈 الربح المتوقع بالمخزون", stock_sale-stock_cost)
        st.caption("الربح المتوقع بالمخزون ليس قائمة أرباح وخسائر محاسبية؛ هو فرق قيمة المخزون الحالية بسعر البيع عن تكلفته.")

        st.markdown("### 📊 الربح والخسارة لفترة")
        d1,d2 = st.columns(2)
        start = d1.date_input("من تاريخ", value=date.today().replace(day=1), key="pl_from")
        end = d2.date_input("إلى تاريخ", value=date.today(), key="pl_to")
        bw = " AND "+predicate
        bp = list(params)
        sales = _scalar(conn, f"SELECT COALESCE(SUM(total_amount),0) FROM invoices WHERE date(created_at) BETWEEN ? AND ?{bw}", (str(start),str(end),*bp))
        expenses = _scalar(conn, f"SELECT COALESCE(SUM(amount),0) FROM expenses WHERE date(expense_date) BETWEEN ? AND ?{bw}", (str(start),str(end),*bp))
        revenues = _scalar(conn, f"SELECT COALESCE(SUM(amount),0) FROM revenues WHERE date(revenue_date) BETWEEN ? AND ?{bw}", (str(start),str(end),*bp))
        # Current schema does not persist invoice COGS reliably; show an operational result and label it clearly.
        result = sales + revenues - expenses
        p1,p2,p3,p4 = st.columns(4)
        _money_metric("المبيعات", sales)
        _money_metric("إيرادات أخرى", revenues)
        _money_metric("المصروفات", expenses)
        _money_metric("النتيجة التشغيلية قبل تكلفة البضاعة المباعة", result)
        if st.session_state.get("role") == "Super_Admin":
            with st.expander("🛠️ ملاحظة فنية — Super Admin فقط"):
                st.warning("حساب تكلفة البضاعة المباعة التاريخية لكل فاتورة لم يكتمل بعد؛ لذلك لا تعتمد النتيجة الحالية كصافي ربح محاسبي نهائي.")

        report_html = f"""<html dir='rtl'><head><meta charset='utf-8'><style>body{{font-family:Arial;padding:25px;direction:rtl}} table{{width:100%;border-collapse:collapse}}td{{border:1px solid #999;padding:9px}}@media print{{.no-print{{display:none}}}}</style></head><body><h2 style='text-align:center'>ملخص الخزينة والتقارير</h2><p>الفترة: {start} إلى {end} — {_html_escape(str(selected))}</p><table><tr><td>تكلفة المخزون</td><td>{_money_print(stock_cost)}</td></tr><tr><td>قيمة المخزون بسعر البيع</td><td>{_money_print(stock_sale)}</td></tr><tr><td>المبيعات</td><td>{_money_print(sales)}</td></tr><tr><td>إيرادات أخرى</td><td>{_money_print(revenues)}</td></tr><tr><td>المصروفات</td><td>{_money_print(expenses)}</td></tr><tr><td>النتيجة قبل تكلفة البضاعة المباعة</td><td>{_money_print(result)}</td></tr></table><div class='no-print'><button onclick='window.print()'>🖨️ طباعة</button></div></body></html>"""
        q1,q2=st.columns(2)
        if q1.button("👁️ معاينة التقرير", use_container_width=True, key="preview_treasury_report"):
            st.session_state["show_treasury_report_preview"] = True
        if q2.button("🖨️ طباعة التقرير", use_container_width=True, key="print_treasury_report"):
            st.session_state["show_treasury_report_preview"] = True
        if st.session_state.get("show_treasury_report_preview"):
            st.components.v1.html(report_html, height=520, scrolling=True)

        st.markdown('### فائض صنف')
        from views.item_surplus import period_rows
        adjustment_rows=period_rows(conn,predicate,params,start,end)
        if adjustment_rows:
            adjustment_df=pd.DataFrame([{'الفرع':r['branch_id'],'الصنف':r['item_name'],'الكمية':float(r['quantity']),'القيمة بمتوسط التكلفة':float(r['loss_or_gain_value']),'التاريخ':str(r['created_at']),'المستخدم':__import__('json').loads(r['notes'])['user_id'],'نوع الحركة':'فائض صنف'} for r in adjustment_rows])
            st.dataframe(adjustment_df,hide_index=True,use_container_width=True)
            period_df=adjustment_df.copy()
            period_df['الشهر']=period_df['التاريخ'].str[:7]
            period_df['السنة']=period_df['التاريخ'].str[:4]
            for group,label in [('الشهر','فائض صنف — شهري'),('السنة','فائض صنف — سنوي')]:
                st.markdown('#### '+label)
                st.dataframe(period_df.groupby([group,'الفرع'],as_index=False)[['الكمية','القيمة بمتوسط التكلفة']].sum(),hide_index=True,use_container_width=True)
            st.download_button('تنزيل فائض صنف',adjustment_df.to_csv(index=False).encode('utf-8-sig'),file_name='item_surplus.csv',mime='text/csv')
        else:st.info('لا توجد حركات فائض صنف في الفترة المحددة.')

        # Reuse the already authorized branch list and current report selection.
        included_ids = report_branch_ids((b['id'] for b in branches), branch_id)
        rows = [b for b in branches if int(b['id']) in included_ids]
        if rows:
            st.markdown("### 🏢 الفروع والمخازن المشمولة")
            st.dataframe(pd.DataFrame([{"الاسم":r["branch_name"],"النوع":r["branch_type"]} for r in rows]), hide_index=True, use_container_width=True)
    finally:
        conn.close()
