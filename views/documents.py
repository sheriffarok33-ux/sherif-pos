_PAGE_ERROR_UI_REVISION = 60
from views.page_guard import show_operation_error
from views.number_format import decimal_display
from views.ui_common import back_button
import streamlit as st
import html
from datetime import datetime
from database import get_db_connection


def _document_columns(conn, table):
    """Read schema without provoking/catching a PostgreSQL transaction error."""
    import sqlite3
    if table not in ('purchases','document_registry','purchase_items'):
        raise ValueError('Unexpected document table')
    ddl=getattr(conn, '_conn', conn)
    if isinstance(ddl, sqlite3.Connection):
        return {row[1] for row in ddl.execute('PRAGMA table_info('+table+')').fetchall()}
    return {row[0] for row in conn.execute(
        'SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?',
        (table,)).fetchall()}

def _document_schema_commands(conn, commands):
    """Recover only our schema savepoint; never commit/rollback the caller's work."""
    ddl=getattr(conn, '_conn', conn)
    ddl.execute('SAVEPOINT document_schema_guard')
    try:
        for command in commands:ddl.execute(command)
    except Exception:
        ddl.execute('ROLLBACK TO SAVEPOINT document_schema_guard')
        ddl.execute('RELEASE SAVEPOINT document_schema_guard')
        raise
    else:
        ddl.execute('RELEASE SAVEPOINT document_schema_guard')

def ensure_purchase_number_column(conn):
    import sqlite3
    if 'document_number' in _document_columns(conn, 'purchases'):return
    ddl=getattr(conn, '_conn', conn)
    clause='' if isinstance(ddl, sqlite3.Connection) else 'IF NOT EXISTS '
    _document_schema_commands(conn, ['ALTER TABLE purchases ADD COLUMN '+clause+'document_number TEXT'])

def ensure_document_schema(conn):
    required={
        'document_registry':{'id','document_number','document_type','source_table','source_id','external_number','branch_id','party_name','amount','document_date','created_by','created_at'},
        'purchase_items':{'id','purchase_id','item_id','item_code','item_name','quantity','unit','unit_price','line_total','expiry_date'},
    }
    if all(columns <= _document_columns(conn, table) for table, columns in required.items()):return
    _document_schema_commands(conn, ['\n        CREATE TABLE IF NOT EXISTS document_registry(\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            document_number TEXT NOT NULL UNIQUE,\n            document_type TEXT NOT NULL,\n            source_table TEXT,\n            source_id INTEGER,\n            external_number TEXT,\n            branch_id INTEGER,\n            party_name TEXT,\n            amount REAL DEFAULT 0,\n            document_date TEXT,\n            created_by INTEGER,\n            created_at TEXT DEFAULT CURRENT_TIMESTAMP\n        )\n    ', 'CREATE INDEX IF NOT EXISTS idx_document_registry_type_date ON document_registry(document_type, document_date)', 'CREATE INDEX IF NOT EXISTS idx_document_registry_external ON document_registry(external_number)', '\n        CREATE TABLE IF NOT EXISTS purchase_items(\n            id INTEGER PRIMARY KEY AUTOINCREMENT,\n            purchase_id INTEGER NOT NULL,\n            item_id INTEGER,\n            item_code TEXT,\n            item_name TEXT NOT NULL,\n            quantity REAL NOT NULL DEFAULT 0,\n            unit TEXT,\n            unit_price REAL NOT NULL DEFAULT 0,\n            line_total REAL NOT NULL DEFAULT 0,\n            expiry_date TEXT\n        )\n    ', 'CREATE INDEX IF NOT EXISTS idx_purchase_items_purchase ON purchase_items(purchase_id)'])


def register_document(conn, document_number, document_type, source_table, source_id,
                      external_number=None, branch_id=None, party_name=None, amount=0,
                      document_date=None, created_by=None):
    ensure_document_schema(conn)
    existing = conn.execute("SELECT id FROM document_registry WHERE document_number=? LIMIT 1", (document_number,)).fetchone()
    values = (document_type, source_table, source_id, external_number, branch_id, party_name, float(amount or 0),
              document_date or datetime.now().date().isoformat(), created_by)
    if existing:
        conn.execute("""UPDATE document_registry SET document_type=?,source_table=?,source_id=?,external_number=?,branch_id=?,party_name=?,amount=?,document_date=?,created_by=? WHERE document_number=?""", values + (document_number,))
    else:
        conn.execute("""INSERT INTO document_registry
            (document_type,source_table,source_id,external_number,branch_id,party_name,amount,document_date,created_by,document_number)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", values + (document_number,))


def _backfill(conn):
    ensure_document_schema(conn)
    for r in conn.execute("SELECT id,document_number,invoice_number,branch_id,supplier_name,total_cost,invoice_date FROM purchases WHERE COALESCE(document_number,'')<>''").fetchall():
        register_document(conn, r['document_number'], 'فاتورة مشتريات', 'purchases', r['id'], r['invoice_number'], r['branch_id'], r['supplier_name'], r['total_cost'], r['invoice_date'])
    for r in conn.execute("SELECT id,voucher_no,voucher_type,branch_id,party_name,amount,created_at,user_id FROM financial_vouchers WHERE COALESCE(voucher_no,'')<>''").fetchall():
        dtype = 'سند صرف' if r['voucher_type']=='دفع' else 'سند قبض'
        register_document(conn, r['voucher_no'], dtype, 'financial_vouchers', r['id'], None, r['branch_id'], r['party_name'], r['amount'], r['created_at'], r['user_id'])
    conn.commit()


def _purchase_rows(conn, purchase_id):
    rows = conn.execute("SELECT item_code,item_name,quantity,unit,unit_price,line_total,expiry_date FROM purchase_items WHERE purchase_id=? ORDER BY id", (purchase_id,)).fetchall()
    return rows


def _purchase_html(conn, source_id):
    p=conn.execute("""SELECT p.*,COALESCE(b.branch_name,'') branch_name FROM purchases p LEFT JOIN branches b ON b.id=p.branch_id WHERE p.id=?""",(source_id,)).fetchone()
    if not p: return '<p>المستند غير موجود.</p>'
    lines=_purchase_rows(conn, source_id)
    trs=''.join(f"<tr><td>{html.escape(str(x['item_code'] or ''))}</td><td>{html.escape(str(x['item_name']))}</td><td>{decimal_display(float(x['quantity']), 3)}</td><td>{html.escape(str(x['unit'] or ''))}</td><td>{decimal_display(float(x['unit_price']), 2)}</td><td>{decimal_display(float(x['line_total']), 2)}</td><td>{html.escape(str(x['expiry_date'] or '-'))}</td></tr>" for x in lines)
    if not trs:
        trs=f"<tr><td colspan='7' style='text-align:right'>{html.escape(str(p['items_details'] or '-')).replace(chr(10),'<br>')}</td></tr>"
    return f"""<html dir='rtl'><head><meta charset='utf-8'><style>body{{font-family:Arial;direction:rtl;text-align:right;padding:24px}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #999;padding:8px;text-align:right}}h2{{text-align:center}}@media print{{button{{display:none}}}}</style></head><body>
    <h2>فاتورة مشتريات</h2><table><tr><th>رقم مستند النظام</th><td>{html.escape(str(p['document_number']))}</td><th>رقم فاتورة المورد</th><td>{html.escape(str(p['invoice_number'] or '-'))}</td></tr><tr><th>المورد</th><td>{html.escape(str(p['supplier_name']))}</td><th>التاريخ</th><td>{html.escape(str(p['invoice_date']))}</td></tr><tr><th>الفرع</th><td>{html.escape(str(p['branch_name'] or '-'))}</td><th>الإجمالي</th><td>{decimal_display(float(p['total_cost'] or 0), 2)} د.ل</td></tr></table>
    <h3>الأصناف</h3><table><thead><tr><th>الكود</th><th>الصنف</th><th>الكمية</th><th>الوحدة</th><th>سعر الشراء</th><th>الإجمالي</th><th>الصلاحية</th></tr></thead><tbody>{trs}</tbody></table><br><button onclick='window.print()'>🖨️ طباعة</button></body></html>"""


def show_page():
    back_button(key='back_documents')
    st.header('🔎 البحث عن مستند')
    st.caption('اكتب رقم مستند النظام مباشرة مثل PUR أو PAY أو REC، ويمكن كذلك البحث برقم فاتورة المورد أو اسم الجهة.')
    q=st.text_input('رقم المستند / الرقم الخارجي / الجهة', placeholder='مثال: PUR-... أو PAY-000001')
    conn=get_db_connection()
    try:
        _backfill(conn)
        if not q.strip():
            st.info('أدخل رقم المستند للوصول إليه مباشرة بدون البحث اليدوي داخل الأرشيفات.')
            return
        like=f"%{q.strip()}%"
        rows=conn.execute("""SELECT d.*,COALESCE(b.branch_name,'') branch_name FROM document_registry d LEFT JOIN branches b ON b.id=d.branch_id WHERE d.document_number LIKE ? OR COALESCE(d.external_number,'') LIKE ? OR COALESCE(d.party_name,'') LIKE ? ORDER BY d.id DESC LIMIT 100""",(like,like,like)).fetchall()
        if not rows:
            st.warning('لا يوجد مستند مطابق.')
            return
        st.dataframe([{'رقم المستند':r['document_number'],'النوع':r['document_type'],'الرقم الخارجي':r['external_number'] or '-','التاريخ':r['document_date'],'الجهة':r['party_name'] or '-','الفرع':r['branch_name'] or '-','القيمة':float(r['amount'] or 0)} for r in rows],use_container_width=True,hide_index=True)
        for r in rows:
            with st.expander(f"{r['document_number']} — {r['document_type']} — {r['party_name'] or ''}"):
                if r['source_table']=='purchases':
                    doc_html=_purchase_html(conn,r['source_id'])
                    st.components.v1.html(doc_html,height=620,scrolling=True)
                elif r['source_table']=='financial_vouchers':
                    v=conn.execute('SELECT * FROM financial_vouchers WHERE id=?',(r['source_id'],)).fetchone()
                    if v:
                        st.write(f"**رقم المستند:** {v['voucher_no']}")
                        st.write(f"**الجهة:** {v['party_name']} — **المبلغ:** {decimal_display(float(v['amount']), 2)} د.ل")
                        st.write(f"**البيان:** {v['notes'] or '-'}")
                else:
                    st.info('المستند مسجل في الفهرس، والمعاينة التفصيلية لهذا النوع ستستخدم شاشة المصدر.')
    finally:
        conn.close()
