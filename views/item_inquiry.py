"""Read-only item movement and balances inquiry."""
_PAGE_ERROR_UI_REVISION = 60
from views.page_guard import show_operation_error
import json
import streamlit as st
from offline_store import get_local_connection


def _open_readonly():
    return get_local_connection(), 'قاعدة البيانات المحلية SQLite'


def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def show_page():
    st.title('🔎 استعلام حركة وأرصدة الأصناف')
    conn = None
    try:
        conn, source = _open_readonly()
        query = st.text_input('ابحث باسم الصنف أو الباركود', key='item_inquiry_search').strip()
        if not query:
            st.info('اكتب اسم الصنف أو الباركود لعرض أرصدته وحركاته.')
            return
        pattern = '%' + query.lower() + '%'
        matches = _rows(conn, '''SELECT DISTINCT COALESCE(NULLIF(item_code,''),item_name) AS lookup_key,
                    item_name,COALESCE(item_code,'') AS item_code FROM items
                    WHERE LOWER(item_name) LIKE ? OR LOWER(COALESCE(item_code,'')) LIKE ?
                    ORDER BY item_name LIMIT 100''', (pattern,pattern))
        if not matches:
            st.info('لا توجد أصناف مطابقة.')
            return
        opts = {f"{r['item_name']} — {r['item_code'] or 'بدون باركود'}":r for r in matches}
        selected = opts[st.selectbox('اختر الصنف',list(opts))]
        if selected['item_code']:
            where, params = 'i.item_code=?', (selected['item_code'],)
            mov_where, mov_params = '(a.item_id IN (SELECT id FROM items WHERE item_code=?) OR a.item_name=?)', (selected['item_code'],selected['item_name'])
        else:
            where, params = 'i.item_name=?', (selected['item_name'],)
            mov_where, mov_params = 'a.item_name=?', (selected['item_name'],)
        balances = _rows(conn, f'''SELECT b.branch_name AS "الفرع / المخزن", i.item_name AS "الصنف",
            COALESCE(i.quantity,0) AS "الرصيد", COALESCE(i.sale_price,0) AS "سعر البيع"
            FROM items i LEFT JOIN branches b ON b.id=i.branch_id WHERE {where}
            ORDER BY b.branch_name''', params)
        st.subheader('الأرصدة في جميع الفروع والمخزن')
        st.dataframe(balances, use_container_width=True, hide_index=True)
        st.subheader('حركات الصنف المسجلة')
        movements = _rows(conn, f'''SELECT a.created_at AS "التاريخ", b.branch_name AS "الفرع / المخزن",
            a.adjustment_type AS "نوع الحركة",a.quantity AS "الكمية",a.notes AS "ملاحظات"
            FROM stock_adjustments a LEFT JOIN branches b ON b.id=a.branch_id
            WHERE {mov_where} ORDER BY a.created_at DESC,a.id DESC LIMIT 1000''',mov_params)
        # Invoices store line details in notes JSON; read without changing the invoices.
        invoices = _rows(conn, '''SELECT inv.id,inv.created_at,inv.notes,b.branch_name
            FROM invoices inv LEFT JOIN branches b ON b.id=inv.branch_id
            WHERE inv.notes IS NOT NULL ORDER BY inv.created_at DESC LIMIT 3000''')
        for inv in invoices:
            try:
                payload = json.loads(inv['notes'])
                lines = payload.get('items', []) if isinstance(payload,dict) else []
                for line in lines:
                    code = str(line.get('item_code') or line.get('barcode') or '')
                    name = str(line.get('item_name') or line.get('name') or '')
                    if (selected['item_code'] and code == selected['item_code']) or (not selected['item_code'] and name == selected['item_name']):
                        movements.append({'التاريخ':inv['created_at'],'الفرع / المخزن':inv['branch_name'],
                            'نوع الحركة':'بيع — فاتورة '+str(inv['id']),
                            'الكمية':line.get('qty',line.get('quantity',0)),'ملاحظات':''})
            except (ValueError,TypeError,AttributeError):
                continue
        movements.sort(key=lambda x:str(x.get('التاريخ') or ''),reverse=True)
        st.dataframe(movements,use_container_width=True,hide_index=True)
        st.caption('تظهر الحركات المسجلة في التسويات والمبيعات المحفوظة بتفاصيل الأصناف. بقية أنواع الحركات تتطلب مصادرها التفصيلية.')
    except Exception as exc:
        show_operation_error(exc, announce=True, context='views/item_inquiry.py:72')
    finally:
        if conn is not None:
            conn.close()
