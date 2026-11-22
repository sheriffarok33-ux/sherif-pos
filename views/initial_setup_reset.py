"""Data preparation. Historical readers never replace the live connection."""
_PAGE_ERROR_UI_REVISION = 60
from views.page_guard import show_operation_error
import io
import json
import sqlite3
import tempfile
import zipfile
import hashlib
from pathlib import Path
from datetime import datetime
import streamlit as st
import pandas as pd
from offline_store import get_local_connection, maintenance_operation

def get_db_connection():
    return get_local_connection(queue_writes=False)
from backup_manager import table_catalog, quote_name, is_sqlite, create_data_backup
from views.ui_common import back_button

PROTECTED = {'users','branches','user_branch_permissions','role_permissions','app_settings','custom_labels',
             'local_meta','sync_queue','offline_sync_receipts','offline_operation_receipts',
             'sidebar_menu_order','sessions','logins'}
LABELS = {
 'financial_year_archives':'الأرشيفات المالية', 'financial_year_archive_rows':'تفاصيل الأرشيفات المالية',
 'invoices':'المبيعات والفواتير', 'negative_sales_logs':'سجل البيع بالسالب',
 'revenues':'الإيرادات', 'expenses':'المصروفات', 'items':'حذف الأصناف بالكامل (الأسماء والباركود والكميات والأسعار)',
 'inventory_batches':'دفعات المخزون والصلاحية', 'purchases':'المشتريات',
 'purchase_items':'بنود المشتريات', 'suppliers':'الموردون', 'customers':'العملاء',
 'supplier_payments':'دفعات الموردين', 'transfer_logs':'التزويد والتحويلات',
 'transfer_safety_log':'سجل التكرار والتراجع عن التزويد', 'stock_adjustments':'تسويات المخزون',
 'production_logs':'التحميص والخلط', 'damaged_stock':'المخزون التالف',
 'financial_vouchers':'سندات القبض والصرف', 'treasury_movements':'حركات الخزينة',
 'treasuries':'تعريف الخزائن', 'shift_closures':'إقفالات الورديات',
 'shift_settlement_adjustments':'تسويات الورديات', 'document_registry':'أرشيف المستندات',
 'employees':'الموظفون', 'employee_financial_transactions':'حركات الموظفين والرواتب',
 'activity_logs':'سجلات النشاط'}
# Logical relationships not declared as database foreign keys.
LINKS = [('purchase_items','purchase_id','purchases','id'),
         ('financial_year_archive_rows','archive_id','financial_year_archives','id'),
         ('transfer_safety_log','transfer_log_id','transfer_logs','id'),
         ('shift_settlement_adjustments','closure_id','shift_closures','id'),
         ('treasury_movements','treasury_id','treasuries','id'),
         ('employee_financial_transactions','employee_id','employees','id'),
         ('inventory_batches','item_id','items','id'),
         ('purchases','supplier_id','suppliers','id'),
         ('supplier_payments','supplier_id','suppliers','id'),
         ('purchase_items','item_id','items','id'),
         ('stock_adjustments','item_id','items','id'),
         ('production_logs','source_item_id','items','id'),
         ('production_logs','target_item_id','items','id')]
FISCAL = {'invoices','negative_sales_logs','purchases','purchase_items','revenues','expenses',
          'supplier_payments','transfer_logs','transfer_safety_log','stock_adjustments',
          'production_logs','financial_vouchers','treasury_movements','shift_closures',
          'shift_settlement_adjustments','document_registry','employee_financial_transactions','activity_logs'}


def _relations(conn, catalog):
    links = list(LINKS)
    if is_sqlite(conn):
        for t in catalog:
            for r in conn.execute('PRAGMA foreign_key_list('+quote_name(t)+')').fetchall():
                if r[1] != 0:
                    raise ValueError('علاقة مركبة تحتاج مراجعة قبل التصفير: '+t)
                links.append((t,r[3],r[2],r[4] or 'id'))
    else:
        rows = conn.execute("""SELECT c.conrelid::regclass::text, a.attname,
                    c.confrelid::regclass::text, b.attname, cardinality(c.conkey)
                FROM pg_constraint c
                JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
                JOIN pg_attribute b ON b.attrelid=c.confrelid AND b.attnum=c.confkey[1]
                JOIN pg_class t ON t.oid=c.conrelid
                JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE c.contype='f' AND n.nspname=current_schema()""").fetchall()
        for child,col,parent,pk,count in rows:
            if count != 1: raise ValueError('علاقة مركبة تحتاج مراجعة قبل التصفير: '+child)
            links.append((child,col,parent,pk))
    return sorted({r for r in links if r[0] in catalog and r[2] in catalog
                   and r[1] in catalog[r[0]] and r[3] in catalog[r[2]]})


def _scope(table, columns, branch_id):
    if branch_id is None: return ('1=1',())
    if 'branch_id' in columns: return ('branch_id=?',(branch_id,))
    if 'from_branch_id' in columns and 'to_branch_id' in columns:
        return ('(from_branch_id=? OR to_branch_id=?)',(branch_id,branch_id))
    if 'source_branch_id' in columns and 'main_branch_id' in columns:
        return ('(source_branch_id=? OR main_branch_id=?)',(branch_id,branch_id))
    return None


def make_plan(conn, selected, branch_id=None, quantity=None, discard_pending=False):
    catalog = table_catalog(conn)
    if quantity is not None and float(quantity) != 0:
        raise ValueError('المتاح هنا تصفير الكميات فقط.')
    selected = set(selected)
    if discard_pending:
        if branch_id is not None:
            raise ValueError('التصفير الشامل للمعلّقات يتطلب نطاق جميع الفروع في هذه القاعدة.')
        selected = set(catalog) - PROTECTED
        if quantity is not None:
            selected.discard('items')
    if selected & PROTECTED: raise ValueError('لا يمكن حذف جداول الهوية والصلاحيات والمزامنة.')
    if not selected <= set(catalog): raise ValueError('تغيّر مخطط القاعدة؛ أعد المعاينة.')
    if quantity is not None and ('items' in selected or float(quantity)<0):
        raise ValueError('اختر حذف الأصناف أو ضبط الكميات، وليس الاثنين.')
    links = _relations(conn,catalog)
    chosen = set(selected)
    # These ledgers contain textual/polymorphic references without FK constraints.
    # Include their full selected branch scope explicitly in the review.
    money_sources = {'invoices','purchases','expenses','revenues','supplier_payments',
                     'shift_closures','shift_settlement_adjustments'}
    if chosen & money_sources:
        chosen |= {'document_registry','treasury_movements','financial_vouchers'} & set(catalog)
    if 'transfer_logs' in chosen:
        chosen |= {'document_registry'} & set(catalog)
    # Surface every dependent table in the preview; never use DELETE CASCADE.
    while True:
        expanded = chosen | {c for c,_,p,_ in links if p in chosen}
        if 'items' in expanded:
            expanded |= (FISCAL | {'inventory_batches','damaged_stock'}) & set(catalog)
        if expanded & money_sources:
            expanded |= {'document_registry','treasury_movements','financial_vouchers'} & set(catalog)
        if expanded == chosen: break
        chosen = expanded
    if chosen & PROTECTED: raise ValueError('الاختيار مرتبط بجدول محمي؛ لا يمكن تنفيذه.')
    predicates = {}
    def predicate(t, seen=()):
        if t in predicates: return predicates[t]
        if t in seen: raise ValueError('علاقة دائرية تحتاج مراجعة: '+t)
        direct = _scope(t,catalog[t],branch_id)
        if direct: predicates[t]=direct;return direct
        conditions=[];args=[]
        for child,col,parent,pk in links:
            if child==t and parent in chosen:
                pred,params=predicate(parent,seen+(t,))
                conditions.append(quote_name(col)+' IN (SELECT '+quote_name(pk)+' FROM '+quote_name(parent)+' WHERE '+pred+')')
                args.extend(params)
        if not conditions: raise ValueError('الجدول '+LABELS.get(t,t)+' مشترك ولا يمكن تصفيره لفرع منفرد.')
        predicates[t]=('('+' OR '.join(conditions)+')',tuple(args));return predicates[t]
    # Refuse deletion if an FK crosses the branch boundary instead of letting DB cascades delete unseen rows.
    for child,col,parent,pk in links:
        if parent not in chosen: continue
        cp,ca=predicate(child);pp,pa=predicate(parent)
        q='SELECT COUNT(*) FROM '+quote_name(child)+' WHERE '+quote_name(col)+' IN (SELECT '+quote_name(pk)+' FROM '+quote_name(parent)+' WHERE '+pp+') AND NOT COALESCE(('+cp+'), FALSE)'
        if conn.execute(q,pa+ca).fetchone()[0]:
            raise ValueError('علاقة بين الفروع خارج النطاق في '+child+'؛ اختر نطاقًا أوسع.')
    order=[];visiting=set()
    def visit(t):
        if t in order:return
        if t in visiting:raise ValueError('علاقة دائرية تحتاج مراجعة: '+t)
        visiting.add(t)
        for child,_,parent,_ in links:
            if parent==t and child in chosen:visit(child)
        visiting.remove(t);order.append(t)
    for t in sorted(chosen):visit(t)
    rows=[]
    for t in order:
        pred,args=predicate(t)
        count=int(conn.execute('SELECT COUNT(*) FROM '+quote_name(t)+' WHERE '+pred,args).fetchone()[0])
        rows.append({'table':t,'label':LABELS.get(t,t),'count':count,'where':pred,'args':args,'related':t not in selected})
    if quantity is not None:
        if 'items' not in catalog:raise ValueError('جدول الأصناف غير موجود.')
        pred,args=_scope('items',catalog['items'],branch_id)
        count=int(conn.execute('SELECT COUNT(*) FROM items WHERE '+pred,args).fetchone()[0])
        # Existing dated batches cannot be safely reconciled with a uniform stock quantity.
        if 'inventory_batches' in catalog and 'inventory_batches' not in chosen:
            bp,ba=_scope('inventory_batches',catalog['inventory_batches'],branch_id)
            if conn.execute('SELECT COUNT(*) FROM inventory_batches WHERE '+bp,ba).fetchone()[0]:
                raise ValueError('لضبط الكميات، اختر أيضًا حذف دفعات المخزون القديمة حتى تتطابق الأرصدة.')
        rows.append({'table':'items','label':'ضبط كمية كل صنف موجود إلى '+str(quantity),'count':count,
                     'where':pred,'args':args,'quantity':float(quantity),'related':False})
    if discard_pending and 'sync_queue' in catalog:
        count=int(conn.execute('SELECT COUNT(*) FROM sync_queue').fetchone()[0])
        rows.append({'table':'sync_queue','label':'طابور المزامنة بالكامل — إلغاء العمليات المعلّقة',
                     'count':count,'where':'1=1','args':(),'related':True})
    if not rows:raise ValueError('اختر بيانات أو تعديل الكميات أولًا.')
    return rows


def _fingerprint(plan):
    return hashlib.sha256(json.dumps(plan,sort_keys=True,default=str).encode()).hexdigest()


@maintenance_operation
def execute_plan(selected, branch_id, quantity, fingerprint, year=None, discard_pending=False):
    conn=get_db_connection()
    backup=None
    try:
        if year is not None and discard_pending:
            raise ValueError('إلغاء المعلقات يخص التصفير الشامل، وليس إغلاق السنة.')
        catalog=table_catalog(conn)
        conn.rollback()
        if is_sqlite(conn):
            conn.execute('BEGIN IMMEDIATE')
            if not discard_pending and 'transfer_logs' in catalog and 'receipt_pending' in catalog['transfer_logs']:
                if conn.execute('SELECT COUNT(*) FROM transfer_logs WHERE receipt_pending=1').fetchone()[0]:
                    raise ValueError('توجد تأكيدات استلام معلقة؛ أتم المزامنة قبل الإغلاق أو اختر التصفير الشامل.')
            if not discard_pending and 'sync_queue' in catalog and conn.execute("SELECT COUNT(*) FROM sync_queue WHERE sync_status!='synced'").fetchone()[0]:
                raise ValueError('توجد عمليات مزامنة معلقة؛ لم يتم التصفير.')
            if not discard_pending and 'invoices' in catalog and 'sync_status' in catalog['invoices']:
                if conn.execute("SELECT COUNT(*) FROM invoices WHERE sync_status!='synced'").fetchone()[0]:
                    raise ValueError('توجد فواتير غير متزامنة؛ لم يتم التصفير.')
        else:
            conn.execute("SET LOCAL lock_timeout='10s'")
            conn.execute('LOCK TABLE '+','.join(quote_name(t) for t in sorted(catalog))+' IN SHARE ROW EXCLUSIVE MODE')
        if year is not None:
            if 'app_settings' not in catalog:
                raise ValueError('جدول إعدادات إغلاق السنة غير موجود.')
            key='closed_financial_year_'+str(int(year))
            if conn.execute('SELECT setting_value FROM app_settings WHERE setting_key=?',(key,)).fetchone():
                raise ValueError('هذه السنة مغلقة بالفعل.')
        plan=make_plan(conn,selected,branch_id,quantity,discard_pending)
        if _fingerprint(plan)!=fingerprint:raise ValueError('تغيرت البيانات منذ المعاينة. أعد المعاينة قبل التنفيذ.')
        backup=create_data_backup(conn,year)
        for row in plan:
            if 'quantity' in row:
                conn.execute('UPDATE items SET quantity=? WHERE '+row['where'],(row['quantity'],)+tuple(row['args']))
            else:
                conn.execute('DELETE FROM '+quote_name(row['table'])+' WHERE '+row['where'],row['args'])
        if is_sqlite(conn) and conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('فشل فحص ترابط البيانات؛ تم إلغاء التصفير.')
        if year is not None:
            conn.execute('INSERT INTO app_settings(setting_key,setting_value) VALUES(?,?)',
                         (key,json.dumps({'closed_at':datetime.now().isoformat(),'backup':backup.name})))
        conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('maintenance_reset_complete','1')")
        conn.commit()
        return backup
    except Exception:
        conn.rollback()
        raise
    finally:conn.close()



def _fresh_start_tab():
    """Windows-only clean start; local sync remains paused until central bootstrap."""
    conn = get_db_connection()
    try:
        if not is_sqlite(conn):
            raise ValueError('هذا الخيار مخصص لقاعدة الويندوز المحلية فقط.')
        catalog = table_catalog(conn)
        plan = make_plan(conn, [], None, 0.0, discard_pending=True)
        # Existing reset logic allows zero; change only the requested stock target.
        for row in plan:
            if row['table'] == 'items' and 'quantity' in row:
                row['quantity'] = 0.0
                row['label'] = 'تصفير الرصيد المحلي مؤقتًا لحين تنزيل رصيد السيرفر'
        # Receipts are historical synchronization logs, not identity/configuration.
        for table in ('offline_sync_receipts', 'offline_operation_receipts'):
            if table in catalog:
                count = int(conn.execute('SELECT COUNT(*) FROM ' + quote_name(table)).fetchone()[0])
                plan.append({'table':table, 'label':'تصفير سجل المزامنة '+table,
                             'count':count, 'where':'1=1', 'args':(), 'related':True})
        st.info('سيُحذف سجل المبيعات والمصروفات والحركات والورديات والمزامنة من هذا الجهاز فقط، وتُصفّر الكميات محليًا مؤقتًا حتى تنزيل الكميات والأسعار المعتمدة من السيرفر. المستخدمون والفروع والأصناف والإعدادات تبقى.')
        st.dataframe([{'البيانات':r['label'],'السجلات':r['count']} for r in plan],
                     hide_index=True, use_container_width=True)
        fingerprint = _fingerprint(plan)
    finally:
        conn.close()
    if st.button('تصفير التشغيل المحلي والبدء من جديد', type='primary', key='prep_fresh_execute'):
        if st.session_state.get('role') != 'Super_Admin':
            raise PermissionError('هنّي روحك وارجع للمهندس شريف 😄')
        backup_path = _execute_fresh_start(fingerprint)
        st.session_state['prep_backup_path'] = str(backup_path)
        st.session_state['prep_result'] = 'تم تصفير التشغيل المحلي. المزامنة موقوفة حتى تسجيل دخول السوبر أدمن أونلاين وتنزيل بيانات السيرفر من نفس الشاشة.'
        st.session_state['prep_done'] = True
        st.rerun()


@maintenance_operation
def _execute_fresh_start(fingerprint):
    conn = get_db_connection()
    try:
        if st.session_state.get('role') != 'Super_Admin':
            raise PermissionError('هنّي روحك وارجع للمهندس شريف 😄')
        if not is_sqlite(conn):
            raise ValueError('التصفير المحلي لا يعمل على قاعدة السيرفر.')
        conn.rollback()
        conn.execute('BEGIN IMMEDIATE')
        catalog = table_catalog(conn)
        plan = make_plan(conn, [], None, 0.0, discard_pending=True)
        for row in plan:
            if row['table'] == 'items' and 'quantity' in row:
                row['quantity'] = 0.0
                row['label'] = 'تصفير الرصيد المحلي مؤقتًا لحين تنزيل رصيد السيرفر'
        for table in ('offline_sync_receipts', 'offline_operation_receipts'):
            if table in catalog:
                count = int(conn.execute('SELECT COUNT(*) FROM ' + quote_name(table)).fetchone()[0])
                plan.append({'table':table, 'label':'تصفير سجل المزامنة '+table,
                             'count':count, 'where':'1=1', 'args':(), 'related':True})
        if _fingerprint(plan) != fingerprint:
            raise ValueError('تغيرت البيانات منذ عرضها؛ افتح الصفحة من جديد.')
        # A verified full backup must exist before any local test data is deleted.
        backup_path = create_data_backup(conn)
        if not Path(backup_path).is_file():
            raise RuntimeError('فشل التحقق من ملف النسخة الاحتياطية؛ لم يتم التصفير.')
        for row in plan:
            if 'quantity' in row:
                conn.execute('UPDATE items SET quantity=0 WHERE ' + row['where'], row['args'])
            else:
                conn.execute('DELETE FROM ' + quote_name(row['table']) + ' WHERE ' + row['where'], row['args'])
        # Reset AUTOINCREMENT only for tables completely emptied by this reset.
        for row in plan:
            if 'quantity' in row:
                continue
            table = row['table']
            if table in catalog and int(conn.execute('SELECT COUNT(*) FROM ' + quote_name(table)).fetchone()[0]) == 0:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sqlite_sequence'").fetchone():
                    conn.execute('DELETE FROM sqlite_sequence WHERE name=?', (table,))
        if conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('فشل فحص العلاقات؛ لم يتم اعتماد التصفير.')
        conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES('maintenance_reset_complete','1')")
        conn.commit()
        return backup_path
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _backup_tab():
    st.write('نسخة كاملة مؤرخة، محفوظة قبل أي تصفير ويمكن تنزيلها على جهازك.')
    st.caption('لاختيار مجلد التنزيل، فعّل سؤال المتصفح عن مكان حفظ كل ملف.')
    if st.button('إنشاء نسخة احتياطية كاملة',key='prep_backup_make'):
        conn=get_db_connection()
        try:
            if not is_sqlite(conn):conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            path=create_data_backup(conn)
            st.session_state['prep_backup_path']=str(path)
            st.success('تم إنشاء النسخة وفحص سلامتها.')
        except Exception as e:show_operation_error(e, announce=True, context='views/initial_setup_reset.py:330')
        finally:conn.rollback();conn.close()
    _download_backup()


def _download_backup():
    name=st.session_state.get('prep_backup_path')
    if name and Path(name).is_file():
        st.download_button('تنزيل النسخة الاحتياطية',Path(name).read_bytes(),file_name=Path(name).name,
                           mime='application/zip',key='prep_download')


def _history_tab():
    st.info('عرض مؤقت للقراءة فقط. قاعدة التشغيل الأساسية تظل متصلة بباقي البرنامج.')
    uploaded=st.file_uploader('فتح نسخة قديمة DB أو حزمة النسخ ZIP',type=['db','sqlite','zip'],key='prep_history_upload')
    if not uploaded:return
    with tempfile.TemporaryDirectory(prefix='abuzaid_history_') as work:
        path=Path(work)/'history.db'
        data=uploaded.getvalue()
        if uploaded.name.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                candidates=[i for i in z.infolist() if i.filename.lower().endswith(('.db','.sqlite'))]
                if not candidates:raise ValueError('الحزمة لا تحتوي نسخة تقارير SQLite. ملفات dump القديمة تحتاج استعادة معزولة أولًا.')
                names=[i.filename for i in candidates]
                chosen=st.selectbox('قاعدة داخل الحزمة',names,key='prep_history_member')
                info=z.getinfo(chosen)
                if info.file_size>512*1024*1024:raise ValueError('النسخة أكبر من حد العرض 512 ميجابايت.')
                data=z.read(chosen)
        if not data.startswith(b'SQLite format 3\x00'):raise ValueError('الملف ليس قاعدة SQLite صالحة.')
        path.write_bytes(data)
        conn=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)
        try:
            conn.execute('PRAGMA query_only=ON');conn.execute('PRAGMA trusted_schema=OFF')
            if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('النسخة تالفة.')
            catalog=table_catalog(conn)
            choices=sorted(set(catalog)-PROTECTED)
            if not choices:st.info('لا توجد بيانات تقارير.');return
            st.warning('أنت تعرض النسخة السابقة: '+uploaded.name)
            table=st.selectbox('التقرير / جدول البيانات',choices,format_func=lambda t:LABELS.get(t,t),key='prep_report_table')
            columns=catalog[table];where=[];args=[]
            if 'branch_id' in columns and 'branches' in catalog:
                branches=conn.execute('SELECT id,branch_name FROM branches ORDER BY id').fetchall()
                opts={None:'جميع الفروع',**{r[0]:str(r[1]) for r in branches}}
                bid=st.selectbox('الفرع',list(opts),format_func=lambda b:opts[b],key='prep_report_branch')
                if bid is not None:where.append('branch_id=?');args.append(bid)
            dates=[c for c in columns if c.endswith('_date') or c in ('created_at','closed_at','log_time')]
            if dates and st.checkbox('تحديد فترة',key='prep_report_period'):
                col=st.selectbox('حقل التاريخ',dates,key='prep_report_datecol')
                start=st.date_input('من تاريخ',key='prep_report_from');end=st.date_input('إلى تاريخ',key='prep_report_to')
                if start>end:st.error('تاريخ البداية بعد النهاية.');return
                where.append('date('+quote_name(col)+') BETWEEN ? AND ?');args.extend([start.isoformat(),end.isoformat()])
            q='SELECT * FROM '+quote_name(table)+(' WHERE '+' AND '.join(where) if where else '')
            frame=pd.read_sql_query(q,conn,params=args)
            search=st.text_input('بحث داخل التقرير',key='prep_report_search')
            if search:frame=frame[frame.astype(str).apply(lambda c:c.str.contains(search,regex=False,case=False)).any(axis=1)]
            st.write('عدد السجلات:',len(frame));st.dataframe(frame,use_container_width=True,hide_index=True)
            st.download_button('تنزيل التقرير CSV',frame.to_csv(index=False).encode('utf-8-sig'),file_name=table+'_report.csv',key='prep_report_csv')
            import html
            document='<!doctype html><html dir="rtl"><meta charset="utf-8"><title>تقرير سابق</title><style>body{font-family:Arial}table{border-collapse:collapse;width:100%}td,th{border:1px solid #aaa;padding:6px}@media print{button{display:none}}</style><button onclick="window.print()">طباعة التقرير</button><h2>'+html.escape(LABELS.get(table,table))+'</h2><p>'+html.escape(uploaded.name)+'</p>'+frame.to_html(index=False,escape=True)+'</html>'
            st.download_button('تنزيل نسخة للطباعة',document.encode(),file_name=table+'_report.html',mime='text/html',key='prep_report_print')
        finally:conn.close()


def _reset_tab(year_end=False):
    conn=get_db_connection()
    try:
        catalog=table_catalog(conn)
        branches=conn.execute('SELECT id,branch_name FROM branches ORDER BY id').fetchall() if 'branches' in catalog else []
        opts={None:'جميع الفروع والمخزن الرئيسي',**{r[0]:str(r[1])+' — '+str(r[0]) for r in branches}}
        bid=None if year_end else st.selectbox('نطاق العملية',list(opts),format_func=lambda b:opts[b],key='prep_scope')
        year=st.number_input('السنة المالية التي ستُغلق',2000,2200,datetime.now().year,key='prep_year') if year_end else None
        if year_end:
            st.info('أرشفة كاملة باسم السنة ثم حذف حركات التشغيل المعروضة. تبقى كميات الأصناف والأسعار وأرصدة العملاء والموردين كما هي كأرصدة افتتاحية. يشمل الإغلاق كل الحركات الحالية؛ راجع أن القاعدة تخص هذه السنة فقط.')
            selected=sorted(FISCAL & set(catalog))
        else:
            selectable=sorted(set(catalog)-PROTECTED,key=lambda t:(0 if 'archive' in t else 1,LABELS.get(t,t)))
            st.caption('جميع جداول البيانات المكتشفة معروضة؛ الهوية والفروع والصلاحيات وإعدادات المزامنة محمية.')
            if 'prep_selected' in st.session_state:
                st.session_state['prep_selected']=[t for t in st.session_state['prep_selected'] if t in selectable]
            selected=st.multiselect('البيانات المطلوب حذفها',selectable,format_func=lambda t:LABELS.get(t,t)+' ['+t+']',key='prep_selected')
        delete_items=False
        if not year_end and 'items' in catalog:
            delete_items=st.checkbox('حذف الأصناف بالكامل لإدخال قائمة أصناف جديدة',key='prep_delete_items')
            if delete_items and 'items' not in selected:
                selected=list(selected)+['items']
            delete_items='items' in selected
            if delete_items:
                st.warning('سيتم حذف تعريفات الأصناف والباركود والكميات والأسعار داخل النطاق المختار، مع حركات التشغيل المرتبطة التي تظهر في المعاينة، ومنها المبيعات والتزويدات. تبقى المستخدمون والفروع.')
                st.session_state['prep_zero_quantities']=False
        quantity=None
        if not year_end and st.checkbox('تصفير كميات الأصناف فقط مع الاحتفاظ بالأسماء والأسعار',key='prep_zero_quantities',disabled=delete_items):
            quantity=0.0
            if 'inventory_batches' in catalog and 'inventory_batches' not in selected:
                selected=list(selected)+['inventory_batches']
            st.caption('تُصفّر الأرصدة وتُحذف دفعات المخزون القديمة ضمن النطاق المختار.')
        discard_pending=False
        if not year_end:
            discard_pending=st.checkbox('تصفير شامل لكل بيانات التشغيل والأرشيفات، بما فيها الفواتير والعمليات المعلّقة',key='prep_discard_pending')
            if discard_pending:
                st.warning('هذا الاختيار يشمل جميع بيانات التشغيل في القاعدة الحالية مهما كانت الاختيارات أعلاه. تُحفظ نسخة كاملة أولًا، ثم تُلغى العمليات المعلّقة دون إرسالها. تبقى الهوية والفروع والمستخدمون والصلاحيات؛ وتبقى الأصناف إذا اخترت تصفير كمياتها.')
        if not selected and quantity is None and not discard_pending:st.info('اختر البيانات لتظهر المعاينة.');return
        plan=make_plan(conn,selected,bid,quantity,discard_pending)
        st.dataframe([{'البيانات':r['label'],'عدد السجلات':r['count'],'مضاف بسبب الارتباط':r['related']} for r in plan],hide_index=True,use_container_width=True)
        st.warning('سيُحذف كامل نطاق الجداول المعروضة، بما فيها الجداول المرتبطة. التحويلات تشمل الفرع كمصدر أو كوجهة. لن يتم تغيير أسماء قاعدة التشغيل أو إعادة استخدام أرقام السجلات.')
        fp=_fingerprint(plan)
    finally:conn.close()
    st.error('قبل التنفيذ: أوقف البيع والمزامنة في جميع الأجهزة. بعد تصفير السيرفر، أعد تجهيز النسخ المحلية من حالته الجديدة قبل إعادة تشغيلها؛ تشغيل نسخة قديمة قد يعيد بيانات حُذفت. هذه الحزمة لا تعيد تجهيز أجهزة الفروع عن بُعد.')
    paused=st.checkbox('أوقفت البيع والمزامنة، وسأعيد تجهيز الأجهزة المحلية قبل تشغيلها.',key='prep_paused')
    phrase=st.text_input('اكتب تنفيذ التصفير للتأكيد',key='prep_confirmation')
    if st.button('أخذ نسخة احتياطية ثم تنفيذ العملية',disabled=not(paused and phrase=='تنفيذ التصفير'),key='prep_execute'):
        if st.session_state.get('role')!='Super_Admin':raise PermissionError('الصلاحية غير كافية.')
        with st.spinner('نسخ وفحص ثم تنفيذ داخل معاملة واحدة...'):
            path=execute_plan(selected,bid,quantity,fp,int(year) if year_end else None,discard_pending)
        st.session_state['prep_backup_path']=str(path)
        st.session_state['prep_result']='تم التنفيذ وحفظ النسخة السابقة. أعد تجهيز أجهزة الفروع قبل استئناف المزامنة.'
        st.session_state['prep_done']=True
        st.rerun()


def show_page():
    back_button(key='back_initial_setup_reset')
    if st.session_state.get('role')!='Super_Admin':
        st.error('هنّي روحك وارجع للمهندس شريف 😄');return
    st.title('🗂️ تجهيز البيانات')
    _sync_controls()
    if st.session_state.get('prep_done'):
        st.success(st.session_state.get('prep_result','تم التنفيذ.'));_download_backup()
        if st.button('عملية جديدة',key='prep_new'):
            for k in list(st.session_state):
                if k.startswith('prep_'):st.session_state.pop(k,None)
            st.rerun()
        return
    mode=st.radio('المهمة',['تصفير التشغيل المحلي','نسخة احتياطية','فتح نسخة سابقة وتقارير','تصفير بالفلتر','إغلاق سنة مالية'],horizontal=True,key='prep_mode')
    try:
        if mode=='تصفير التشغيل المحلي':_fresh_start_tab()
        elif mode=='نسخة احتياطية':_backup_tab()
        elif mode=='فتح نسخة سابقة وتقارير':_history_tab()
        else:_reset_tab(mode=='إغلاق سنة مالية')
    except Exception as exc:show_operation_error(exc, announce=True, context='views/initial_setup_reset.py:468')


def _sync_controls():
    from offline_store import sync_is_paused, resume_after_preparation
    if sync_is_paused():
        st.warning('مزامنة الرفع متوقفة لحماية السيرفر من بيانات النسخة القديمة. نفّذ تجهيز القاعدة المحلية أولًا، ثم استأنف من هنا.')
        st.caption('للاستئناف، يلزم توثيق حساب السوبر أدمن أونلاين حتى لو كانت جلسة المتصفح مفتوحة.')
        with st.form('prep_resume_online_auth'):
            sync_username = st.text_input('اسم مستخدم السوبر أدمن', value=st.session_state.get('username', ''), key='prep_sync_username')
            sync_password = st.text_input('كلمة المرور', type='password', key='prep_sync_password')
            sync_submit = st.form_submit_button('تسجيل الدخول أونلاين وتنزيل البيانات واستئناف المزامنة')
        if sync_submit:
            try:
                from branch_auth import online_login
                authenticated = online_login(sync_username, sync_password)
                if authenticated.get('role') != 'Super_Admin' or int(authenticated.get('id')) != int(st.session_state.get('user_id')):
                    from branch_auth import clear_online_credentials
                    clear_online_credentials()
                    raise PermissionError('يجب تسجيل الدخول أونلاين بنفس حساب السوبر أدمن الحالي.')
                resume_after_preparation()
                st.session_state['connection_mode'] = 'online'
                st.success('تم تنزيل البيانات واستئناف المزامنة.')
                st.rerun()
            except Exception as exc:
                show_operation_error(exc, announce=True, context='views/initial_setup_reset.py:493')
    else:
        st.caption('المزامنة مفعلة. تنفيذ أي تصفير يوقفها حتى تستأنفها من هذه الشاشة.')
