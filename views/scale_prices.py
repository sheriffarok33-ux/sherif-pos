"""Central scale-price field and existing snapshot/import integration."""
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
import sqlite3,math

def is_kg(item):
    return str(dict(item).get('unit_type') or dict(item).get('unit') or '').strip().lower() in ('kg','كجم','كيلو','كيلوجرام','kilogram','kilo','weight')

def valid_price(value):
    if value is None or str(value).strip() in ('',):return None
    if isinstance(value,bool):raise ValueError('سعر الميزان يجب أن يكون رقمًا')
    try:p=Decimal(str(value).strip())
    except (InvalidOperation,ValueError):raise ValueError('سعر الميزان غير رقمي') from None
    if not p.is_finite() or p<0 or p>Decimal('1000000000'):raise ValueError('سعر الميزان سالب أو غير صالح أو خارج النطاق')
    return p.quantize(Decimal('0.000001'),rounding=ROUND_HALF_UP)

def import_prices(conn,actor_id,branch_ids,rows):
    from views.branch_access import can_access_branch
    actor=conn.execute('SELECT id,role,branch_id,allowed_branches,is_active FROM users WHERE id=?',(actor_id,)).fetchone()
    if not actor or actor['role'] not in ('Admin','Super_Admin','Manager') or not actor['is_active']:raise PermissionError('تحديث سعر الميزان يتطلب صلاحية الإدارة')
    branch_ids=list(dict.fromkeys(int(x) for x in branch_ids))
    if not branch_ids or any(not can_access_branch(dict(actor),b) for b in branch_ids):raise PermissionError('الفرع خارج نطاق صلاحيات الحساب')
    raw=getattr(conn,'_conn',conn)
    if isinstance(raw,sqlite3.Connection):raise PermissionError('يُحدّث سعر الميزان عبر السيرفر المركزي فقط')
    values={};errors=[];skipped=0
    for index,row in enumerate(rows,2):
        try:
            price=valid_price(row.get('سعر الميزان'))
            if price is None:skipped+=1;continue
            code=str(row.get('كود الصنف') or '').strip()
            if not code:raise ValueError('كود الصنف مطلوب')
            if code in values and values[code]!=price:raise ValueError('سعران مختلفان لنفس كود الصنف')
            values[code]=price
        except ValueError as e:errors.append(f'صف {index}: {e}')
    plans=[]
    for code,price in values.items():
        for branch in branch_ids:
            matches=conn.execute('SELECT id,unit_type,unit FROM items WHERE branch_id=? AND item_code=? FOR UPDATE',(branch,code)).fetchall()
            if len(matches)!=1:errors.append(f'الفرع {branch}، الصنف {code}: المعرف مفقود أو مكرر؛ لا ينشأ صنف جديد');continue
            item=matches[0]
            if not is_kg(item):errors.append(f'الفرع {branch}، الصنف {code}: سعر الميزان للأصناف بالكيلو فقط');continue
            plans.append((str(price),item['id']))
    if errors:raise ValueError('؛ '.join(errors[:30]))
    for price,ident in plans:conn.execute('UPDATE items SET scale_price=? WHERE id=?',(price,ident))
    return {'updated':len(plans),'blank_skipped':skipped}

def measurement(decoded,item,divisor):
    value=Decimal(str(decoded.get('value_decimal',decoded['value'])))
    if not value.is_finite() or value<=0:raise ValueError('قيمة باركود الميزان يجب أن تكون موجبة')
    if decoded['mode']=='weight':return value,{'mode':'weight','weight':str(value)}
    if decoded['mode']!='price':raise ValueError('صيغة الميزان غير معتمدة')
    if not is_kg(item):raise ValueError('باركود السعر باستخدام سعر الميزان للأصناف بالكيلو فقط')
    price=valid_price(dict(item).get('scale_price'))
    if price is None or price<=0:raise ValueError('سعر الميزان مفقود أو صفر؛ حدّثه من استيراد الأصناف')
    quantum=Decimal(1)/Decimal(str(divisor))
    weight=(value/price).quantize(Decimal('0.000001'),rounding=ROUND_HALF_UP)
    if weight<=0:raise ValueError('الوزن المحسوب أقل من الدقة المدعومة')
    # The label stores a rounded price: record its uncertainty, not an invented
    # original physical weight. Final invoice and stock both use this same weight.
    return weight,{'mode':'price','encoded_price':str(value),'scale_price_used':str(price),'weight':str(weight),'price_quantum':str(quantum),'weight_rounding_uncertainty':str(quantum/(2*price))}

def apply_snapshot_prices(conn,items,branch_id):
    for row in items:
        if int(row['branch_id'])!=int(branch_id):raise ValueError('سعر ميزان خارج نطاق الفرع')
        if 'scale_price' not in row:continue # A compatible older API cannot clear prices.
        price=valid_price(row['scale_price'])
        if price is not None and not is_kg(row):raise ValueError('سعر ميزان لصنف غير مباع بالكيلو')
        local=conn.execute('SELECT id FROM items WHERE branch_id=? AND item_code=?',(branch_id,row['item_code'])).fetchall()
        if len(local)>1:raise ValueError('كود صنف محلي مكرر؛ لم يُخمن ربط السعر')
        if local:conn.execute('UPDATE items SET scale_price=? WHERE id=?',(float(price) if price is not None else None,local[0]['id']))
