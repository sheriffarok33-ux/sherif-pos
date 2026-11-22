"""An inventory-only adjustment; caller owns commit/rollback and offline outbox."""
import json,uuid,math,sqlite3
from decimal import Decimal
LABEL='فائض صنف'

def add_surplus(conn,branch_id,item_id,quantity,actor_id,operation_uuid):
    try:quantity=Decimal(str(quantity))
    except Exception:raise ValueError('الكمية غير صالحة') from None
    if not quantity.is_finite() or quantity<=0 or quantity>Decimal('1e12'):raise ValueError('الكمية يجب أن تكون موجبة ومحدودة')
    operation_uuid=str(uuid.UUID(str(operation_uuid)))
    actor=conn.execute('SELECT id,role,branch_id,allowed_branches,is_active FROM users WHERE id=?',(actor_id,)).fetchone()
    from views.branch_access import can_access_branch
    if not actor or actor['role'] not in ('Admin','Super_Admin','Manager') or not can_access_branch(dict(actor),branch_id):raise PermissionError('لا توجد صلاحية لإدارة مخزون الفرع')
    branch=conn.execute('SELECT branch_name,branch_type FROM branches WHERE id=?',(branch_id,)).fetchone()
    if not branch or branch['branch_type']=='مخزن' or 'رئيس' in str(branch['branch_name']):raise ValueError('اختر فرعًا لإضافة فائض صنف')
    raw=getattr(conn,'_conn',conn)
    local=isinstance(raw,sqlite3.Connection)
    if local:
        if not raw.in_transaction:conn.execute('BEGIN IMMEDIATE')
    else:conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('item-surplus:'+operation_uuid,))
    note=json.dumps({'operation':'فائض صنف','operation_uuid':operation_uuid,'user_id':int(actor_id),'branch_id':int(branch_id),'item_id':int(item_id),'quantity':str(quantity)},ensure_ascii=False,sort_keys=True,separators=(',',':'))
    # Stable ID survives a double submit and the existing ERP transaction receipt
    # protects lost acknowledgements during offline upload.
    found=conn.execute('SELECT id,notes FROM stock_adjustments WHERE adjustment_type=? AND notes LIKE ?', (LABEL,'%'+operation_uuid+'%')).fetchone()
    if found:
        if found['notes']!=note:raise ValueError('معرف فائض صنف مستخدم ببيانات مختلفة')
        return {'already_applied':True,'id':found['id']}
    item=conn.execute('SELECT id,item_name,quantity,avg_cost,buy_price FROM items WHERE id=? AND branch_id=?'+('' if local else ' FOR UPDATE'),(item_id,branch_id)).fetchone()
    if not item:raise ValueError('الصنف غير موجود في الفرع المحدد')
    value=item['avg_cost'] if item['avg_cost'] is not None else item['buy_price']
    if value is None:raise ValueError('متوسط تكلفة الصنف غير موثق')
    cost=Decimal(str(value))
    if not cost.is_finite() or cost<0:raise ValueError('متوسط تكلفة الصنف غير صالح')
    gain=quantity*cost
    conn.execute('UPDATE items SET quantity=quantity+? WHERE id=? AND branch_id=?',(float(quantity),item_id,branch_id))
    conn.execute('INSERT INTO inventory_batches(item_id,branch_id,quantity,remaining_quantity,unit_cost,source_type,created_at) VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)',(item_id,branch_id,float(quantity),float(quantity),float(cost),LABEL))
    conn.execute('INSERT INTO stock_adjustments(branch_id,item_id,item_name,quantity,adjustment_type,loss_or_gain_value,notes,created_at) VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)',(branch_id,item_id,item['item_name'],float(quantity),LABEL,float(gain),note))
    return {'already_applied':False,'quantity':float(quantity),'value':float(gain)}

def period_rows(conn,predicate,params,start,end):
    return conn.execute('SELECT branch_id,item_name,quantity,loss_or_gain_value,notes,created_at FROM stock_adjustments WHERE adjustment_type=? AND date(created_at) BETWEEN ? AND ? AND '+predicate+' ORDER BY created_at,id',(LABEL,str(start),str(end),*params)).fetchall()
