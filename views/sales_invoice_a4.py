"""Read-only A4 rendering; no sale, stock, ledger or sync writes."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from html import escape
import re
import sqlite3

BRAND_KEYS=('company_name','trade_name','company_phone','company_address','tax_number','commercial_register','logo_data')

def _text(value):
    return escape(str(value if value is not None else ''), quote=True)

def _decimal(value):
    try:
        number=Decimal(str(value if value is not None else 0))
    except (InvalidOperation,ValueError) as exc:
        raise ValueError('قيمة رقمية غير صالحة في الفاتورة المحفوظة') from exc
    if not number.is_finite():raise ValueError('قيمة غير محدودة في الفاتورة المحفوظة')
    return number

def _money(value):
    return f'{_decimal(value):,.2f}'

def _qty(value):
    return format(_decimal(value).normalize(),'f')

def _unit(value):
    value=str(value or '').strip()
    if value.casefold() in ('kg','kilogram','كيلو','كيلوجرام','كغ','كجم'):return 'كجم'
    return value or 'وحدة غير مسجلة'

def read_branding(conn):
    """Read existing official settings only; never initialize settings while printing."""
    ddl=getattr(conn,'_conn',conn)
    if isinstance(ddl,sqlite3.Connection):
        present=ddl.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_settings'").fetchone()
    else:
        present=conn.execute("SELECT to_regclass('app_settings')").fetchone()
        present=present and present[0]
    if not present:return {}
    placeholders=','.join('?' for _ in BRAND_KEYS)
    rows=conn.execute('SELECT setting_key,setting_value FROM app_settings WHERE setting_key IN ('+placeholders+')',BRAND_KEYS).fetchall()
    return {row[0]:row[1] or '' for row in rows}

def credit_balance_snapshot(conn,account_id,invoice_total):
    """Called once inside the existing sale transaction, before its customer update."""
    row=conn.execute('SELECT balance FROM customers WHERE id=? FOR UPDATE',(account_id,)).fetchone()
    if row is None:raise ValueError('الحساب الآجل المحدد غير موجود؛ لم تعتمد الفاتورة')
    previous=_decimal(row['balance'] or 0)
    ledger_scope='branch_local' if isinstance(getattr(conn,'_conn',conn),sqlite3.Connection) else 'central'
    return {'ledger_scope':ledger_scope,'previous_balance':str(previous),'invoice_amount':str(_decimal(invoice_total)),
            'amount_due':str(previous+_decimal(invoice_total)),'source':'sale_transaction'}

def build_invoice_a4_html(invoice,branding=None):
    """Render saved invoice data. Do not look up today's balance for an old invoice."""
    from views.invoice_qr_image import invoice_qr_html
    brand=dict(branding or {})
    company=brand.get('trade_name') or brand.get('company_name') or 'المنشأة'
    legal=brand.get('company_name') if brand.get('company_name')!=company else ''
    logo=str(brand.get('logo_data') or '')
    logo_ok=len(logo)<=4*1024*1024 and re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=\r\n]+',logo)
    logo_html='<img class="logo" alt="شعار المنشأة" src="'+_text(logo)+'">' if logo_ok else ''
    official=[]
    for key,label in (('company_address','العنوان'),('company_phone','الهاتف'),('commercial_register','السجل التجاري'),('tax_number','الرقم الضريبي')):
        if brand.get(key):official.append('<span>'+label+': '+_text(brand[key])+'</span>')
    quantities=defaultdict(Decimal)
    lines=[]
    for index,item in enumerate(invoice.get('items') or [],1):
        qty=_decimal(item.get('qty',item.get('quantity',0)))
        price=_decimal(item.get('price',item.get('unit_price',0)))
        total=_decimal(item['total']) if item.get('total') is not None else _decimal(item['line_total']) if item.get('line_total') is not None else qty*price
        unit=_unit(item.get('unit'))
        quantities[unit]+=qty
        description=str(item.get('description') or '')
        name=item.get('name') or item.get('item_name') or 'اسم غير مسجل'
        detail='<small>'+_text(description)+'</small>' if description and description!=name else ''
        price_label='للكيلو' if unit=='كجم' else 'لكل '+unit if unit!='وحدة غير مسجلة' else 'سعر الوحدة المسجل'
        lines.append('<tr><td>'+str(index)+'</td><td class="code">'+_text(item.get('code',item.get('item_code','')))+'</td><td class="description">'+_text(name)+detail+'</td><td class="number">'+_qty(qty)+'</td><td>'+_text(unit)+'</td><td class="number">'+_money(price)+'<small>'+_text(price_label)+'</small></td><td class="number">'+_money(total)+'</td></tr>')
    if not lines:lines.append('<tr><td colspan="7">تفاصيل الأصناف غير محفوظة لهذه الفاتورة</td></tr>')
    quantity_text=' ؛ '.join(_qty(qty)+' '+unit for unit,qty in quantities.items()) or 'غير مسجلة'
    total=_decimal(invoice.get('total',invoice.get('total_amount',0)))
    discount=_decimal(invoice.get('discount_amount',0))
    gross=invoice.get('gross_total')
    summary=''
    if gross is not None:summary+='<tr><th>الإجمالي قبل الخصم</th><td>'+_money(gross)+' د.ل</td></tr>'
    if discount:summary+='<tr><th>الخصم</th><td>'+_money(discount)+' د.ل</td></tr>'
    summary+='<tr class="grand"><th>قيمة الفاتورة النهائية</th><td>'+_money(total)+' د.ل</td></tr>'
    account=invoice.get('account_statement')
    if account and account.get('source')=='sale_transaction':
        if _decimal(account['invoice_amount'])!=total or _decimal(account['previous_balance'])+total!=_decimal(account['amount_due']):
            raise ValueError('بيان الحساب المحفوظ لا يطابق قيمة الفاتورة')
        local=account.get('ledger_scope')=='branch_local'
        previous_label='الرصيد المحلي المسجل قبل الفاتورة' if local else 'الرصيد السابق المحفوظ عند إصدار الفاتورة'
        due_label='المستحق المحلي المسجل عند الإصدار' if local else 'إجمالي المستحق المحفوظ عند الإصدار'
        summary+='<tr><th>'+previous_label+'</th><td>'+_money(account['previous_balance'])+' د.ل</td></tr>'
        summary+='<tr class="grand"><th>'+due_label+'</th><td>'+_money(account['amount_due'])+' د.ل</td></tr>'
        if local:summary+='<tr><td colspan="2">هذا بيان الحساب المحلي وقت البيع؛ تأكيد الرصيد المركزي يخضع للمزامنة.</td></tr>'
    elif 'آجل' in str(invoice.get('method','')):
        summary+='<tr><td colspan="2">الرصيد السابق والمستحق التاريخي غير محفوظين لهذه الفاتورة؛ لا يُستخدم الرصيد الحالي بدلًا منهما.</td></tr>'
    words=invoice.get('amount_in_words')
    if not words:
        try:
            from num2words import num2words
        except ImportError:
            pass
        else:
            try:words=num2words(total,lang='ar',to='currency',currency='LYD')
            except (NotImplementedError,ValueError,TypeError):pass
    words_html='<p class="words">فقط: '+_text(words)+'</p>' if words else ''
    note=invoice.get('print_notes') or invoice.get('remarks') or ''
    number=invoice.get('invoice_number') or '#'+str(invoice.get('inv_id',''))
    virtual='<div class="virtual">فاتورة تجريبية — غير مالية</div>' if invoice.get('_non_financial') else ''
    return '''<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>فاتورة مبيعات '''+_text(number)+'''</title><style>
@page{size:A4 portrait;margin:14mm 12mm}
*{box-sizing:border-box}body{font-family:Tahoma,Arial,sans-serif;color:#15242d;margin:0;background:#fff;font-size:12px;line-height:1.65}
.sheet{max-width:186mm;margin:auto}.toolbar{padding:12px;text-align:center;background:#f1f4f6}
button{padding:9px 24px;background:#183f4c;color:#fff;border:0;border-radius:4px;cursor:pointer}
header{display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid #214b58;padding:5mm 0}
h1{font-size:27px;margin:0;color:#183f4c}h2{font-size:21px;margin:0}p{margin:3px 0}
.logo{width:25mm;height:25mm;object-fit:contain}.official span{display:inline-block;margin-left:14px}
.invoice-title{padding:5mm 0;display:flex;justify-content:space-between;align-items:center}
.meta{border:1px solid #b8c6ca;padding:3mm;margin-bottom:5mm}.meta strong{display:inline-block;min-width:26mm}
table{border-collapse:collapse;width:100%;table-layout:fixed}th,td{border:1px solid #b5c2c8;padding:7px 5px;text-align:center;overflow-wrap:anywhere}
thead{display:table-header-group}thead th{background:#e8eff1;color:#163a46;font-size:12px}tr{break-inside:avoid;page-break-inside:avoid}
.description{text-align:right}.code{direction:ltr;unicode-bidi:plaintext}.number{direction:ltr;font-variant-numeric:tabular-nums;white-space:nowrap}
small{display:block;font-size:10px;color:#53616a;white-space:normal}.bottom{break-inside:avoid;page-break-inside:avoid;margin-top:5mm}
.quantity{border-bottom:1px solid #b5c2c8;padding:3mm 0}.summary{width:65%;margin:4mm 0 4mm auto}
.summary th{text-align:right}.grand{background:#e8eff1;font-size:14px;font-weight:bold}
.words,.notes{border:1px solid #c3cccf;padding:3mm;white-space:pre-wrap}
footer{margin-top:10mm;display:flex;justify-content:space-between;gap:10mm;text-align:center}
.signature{width:58mm;border-top:1px solid #61727a;padding-top:2mm;margin-top:8mm}.virtual{font-size:24px;text-align:center;color:#9a3412}
@media print{.toolbar{display:none}body{font-size:11px}header,.invoice-title,.meta{break-inside:avoid}thead th,.grand{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
</style></head><body><div class="toolbar"><button onclick="window.print()">طباعة فاتورة A4</button><p>مقاس A4 — اتجاه رأسي</p></div><main class="sheet">'''+virtual+'''
<header><div><h1>'''+_text(company)+'''</h1><p>'''+_text(legal)+'''</p><div class="official">'''+''.join(official)+'''</div></div>'''+logo_html+'''</header>
<section class="invoice-title"><h2>فاتورة مبيعات</h2><b>رقم الفاتورة: <bdi>'''+_text(number)+'''</bdi></b></section>
<section class="meta"><p><strong>السادة /</strong> '''+_text(invoice.get('customer') or 'اسم العميل غير مسجل')+'''</p><p><strong>التاريخ والوقت</strong> <bdi>'''+_text(invoice.get('date_time',''))+'''</bdi></p><p><strong>الفرع</strong> '''+_text(invoice.get('branch',''))+'''　<strong>طريقة الدفع</strong> '''+_text(invoice.get('method',''))+'''</p></section>
<table><colgroup><col style="width:4%"><col style="width:12%"><col style="width:28%"><col style="width:10%"><col style="width:10%"><col style="width:18%"><col style="width:18%"></colgroup>
<thead><tr><th>م</th><th>كود الصنف</th><th>الصنف والوصف</th><th>الكمية</th><th>الوحدة</th><th>سعر الكيلو / الوحدة</th><th>الإجمالي</th></tr></thead><tbody>'''+''.join(lines)+'''</tbody></table>
<section class="bottom"><p class="quantity"><b>إجمالي الكميات حسب الوحدة:</b> '''+_text(quantity_text)+'''</p><table class="summary">'''+summary+'''</table>'''+words_html+'''
<p class="notes"><b>ملاحظات:</b> '''+_text(note or '—')+'''</p>
<footer><div><p>شكرًا لثقتكم</p><p>نسعد باستمرار التعامل معكم</p></div><div class="signature">توقيع الإدارة</div></footer>'''+invoice_qr_html(invoice.get('invoice_qr_image'))+'''</section></main></body></html>'''

def _branding_connection():
    """Windows printing stays offline and never initializes or commits the POS store."""
    import os,sys
    from pathlib import Path
    if os.name=='nt':
        root=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
        from sherif_paths import local_db
        return sqlite3.connect(local_db().resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    from database import get_db_connection
    return get_db_connection()


def show_invoice_a4(invoice,key):
    import streamlit as st
    if st.button('طباعة فاتورة A4',key=key+'_button'):
        st.session_state[key+'_open']=True
    if not st.session_state.get(key+'_open'):return
    conn=_branding_connection()
    try:branding=read_branding(conn)
    finally:conn.close()
    html=build_invoice_a4_html(invoice,branding)
    st.caption('نسخة طباعة من الفاتورة المحفوظة؛ لا تنشئ بيعًا أو حركة مخزون جديدة.')
    if hasattr(st,'iframe'):st.iframe(html,height=740,alt='فاتورة مبيعات الشركات والأسواق A4')
    else:st.components.v1.html(html,height=740,scrolling=True)
    st.download_button('تحميل فاتورة A4',data=html.encode('utf-8'),file_name='Invoice_A4_'+str(invoice.get('inv_id',''))+'.html',mime='text/html',key=key+'_download',on_click='ignore',width='stretch')

