from views.test_branch_policy import report_branch_ids
"""Windows local dashboard; read-only. Never touches offline queues."""
import html
import streamlit as st


def _num(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def _format_number(value):
    return f"{_num(value):.3f}".rstrip("0").rstrip(".")


def _money(value):
    return f"{_format_number(value)} د.ل"


def _query(conn, sql):
    cur = conn.execute(sql)
    try:
        return cur.fetchall()
    finally:
        try:
            cur.close()
        except Exception:
            pass


def show_dashboard(username, role, branch_id=None):
    from offline_store import get_local_connection
    st.markdown('''<style>
    .az-dashboard-title{direction:rtl !important;text-align:right !important;width:100%;font-weight:850;font-size:22px;color:#1e293b;margin:15px 0 12px;padding:0}
    [data-testid="stMetric"]{direction:rtl !important;text-align:right !important}
    [data-testid="stMetricLabel"],[data-testid="stMetricValue"]{direction:rtl !important;text-align:right !important;justify-content:flex-start !important}
    [data-testid="stMetricValue"] > div{direction:ltr !important;unicode-bidi:isolate;text-align:right !important}
    .az-intro{direction:rtl;text-align:right;padding:9px 14px;background:#ecfdf5;border-right:4px solid #16a34a;border-radius:7px;margin-bottom:12px}
    .az-branch{direction:rtl;text-align:right;font-weight:800;font-size:18px;margin:5px 0 8px}
    .az-branch small{color:#64748b;font-size:12px;font-weight:500}
    </style>''', unsafe_allow_html=True)
    conn = None
    try:
        conn = get_local_connection()
        company_row = conn.execute("SELECT setting_value FROM app_settings WHERE setting_key = 'company_name'").fetchone()
        company_name = str(company_row[0] or '').strip() if company_row else ''
        st.markdown(f'<div class="az-intro">☕ {html.escape(company_name or "SHERIF")} — أهلاً {html.escape(str(username))} | لوحة البيانات المحلية</div>', unsafe_allow_html=True)
        branches = _query(conn, 'SELECT id, branch_name FROM branches ORDER BY id')
        sales = dict(_query(conn, 'SELECT branch_id, COALESCE(SUM(total_amount),0) FROM invoices GROUP BY branch_id'))
        expenses = dict(_query(conn, 'SELECT branch_id, COALESCE(SUM(amount),0) FROM expenses GROUP BY branch_id'))
        revenues = dict(_query(conn, 'SELECT branch_id, COALESCE(SUM(amount),0) FROM revenues GROUP BY branch_id'))
        stocks = _query(conn, '''SELECT branch_id, COALESCE(SUM(quantity),0),
            COALESCE(SUM(quantity * COALESCE(NULLIF(avg_cost,0),buy_price,0)),0),
            COALESCE(SUM(quantity * COALESCE(sale_price,0)),0)
            FROM items GROUP BY branch_id''')
    except Exception as exc:
        st.error('تعذر قراءة بيانات لوحة التحكم من قاعدة Windows المحلية. ')
        st.caption(f'تفاصيل الاتصال: {str(exc)[:240]}')
        return
    finally:
        if conn is not None:
            conn.close()

    stock_by_branch = {r[0]: tuple(_num(v) for v in r[1:]) for r in stocks}
    privileged = role in ('Super_Admin', 'Admin', 'Manager', 'General_Supervisor')
    if not privileged:
        branches = [b for b in branches if str(b[0]) == str(branch_id)]

    ids = [b[0] for b in branches]
    def aggregate(bid):
        qty, cost, retail = stock_by_branch.get(bid, (0.0, 0.0, 0.0))
        return (_num(sales.get(bid)) + _num(revenues.get(bid)), _num(expenses.get(bid)), qty, cost, retail)

    def metrics(data):
        income, expense, qty, cost, retail = data
        cols = st.columns(3)
        cols[0].metric('💰 الإيرادات', _money(income))
        cols[1].metric('💸 المصروفات', _money(expense))
        cols[2].metric('📦 المخزون (مجموع كميات)', _format_number(qty))
        cols = st.columns(3)
        cols[0].metric('🏷️ المخزون بالتكلفة', _money(cost))
        cols[1].metric('🛒 المخزون بالبيع', _money(retail))
        cols[2].metric('📈 ربح المخزون المتوقع', _money(retail-cost))

    if privileged:
        totals = tuple(sum(aggregate(bid)[i] for bid in report_branch_ids(ids)) for i in range(5))
        st.markdown('<div class="az-dashboard-title">📊 إجمالي المجموعة</div>', unsafe_allow_html=True)
        metrics(totals)
        st.divider()
    st.markdown('<div class="az-dashboard-title">🏢 الفروع والمخزن الرئيسي</div>', unsafe_allow_html=True)
    if not branches:
        st.info('لا توجد فروع متاحة لهذا المستخدم.')
    for bid, name in branches:
        st.markdown(f'<div class="az-branch">🏢 {html.escape(str(name))}</div>', unsafe_allow_html=True)
        metrics(aggregate(bid))
        st.divider()
    st.caption('الإيرادات = الفواتير + الإيرادات اليدوية. الربح المتوقع يخص المخزون الحالي فقط، وليس صافي الربح. جمع الكميات عبر وحدات مختلفة مؤشر تقريبي.')
