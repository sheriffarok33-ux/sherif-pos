"""POS quantity and reference freshness shared by server and offline client."""
def quantity_from_scale(decoded):
    import math
    if decoded['mode']!='weight':
        raise ValueError('باركود الميزان يحتوي على سعر فقط؛ أدخل الوزن الفعلي ولا يُستنتج من السعر.')
    qty=float(decoded['value'])
    if not math.isfinite(qty) or qty<=0:raise ValueError('كمية الميزان يجب أن تكون موجبة')
    return qty

def credit_freshness(conn):
    import sqlite3
    from datetime import datetime
    if not isinstance(getattr(conn,'_conn',conn),sqlite3.Connection):return ''
    row=conn.execute("SELECT value FROM local_meta WHERE key='party_reference_last_success'").fetchone()
    if not row:return 'الأرصدة محلية؛ لم يتأكد تنزيل الأرصدة المركزية بعد.'
    return 'آخر تنزيل للأرصدة: '+datetime.fromtimestamp(int(row[0])).strftime('%Y-%m-%d %H:%M')+' — تشمل الأرصدة الحركات المحفوظة محليًا.'
