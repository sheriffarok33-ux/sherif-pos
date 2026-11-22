"""Additional catalog barcodes; stable item_code and existing item rows stay intact."""
import re,sqlite3,uuid,math
from decimal import Decimal,InvalidOperation
TABLE='item_barcodes'
SCALE_KEYS={'scale_enabled','scale_prefix','scale_item_start','scale_item_length','scale_value_start','scale_value_length','scale_value_mode','scale_divisor'}

def raw(conn):return getattr(conn,'_conn',conn)
def is_sqlite(conn):return isinstance(raw(conn),sqlite3.Connection)
def exists(conn):
    if is_sqlite(conn):return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(TABLE,)).fetchone())
    return bool(conn.execute("SELECT 1 FROM information_schema.tables WHERE table_name=? AND table_schema=current_schema()",(TABLE,)).fetchone())
def ensure_schema(conn):
    key='INTEGER PRIMARY KEY AUTOINCREMENT' if is_sqlite(conn) else 'BIGSERIAL PRIMARY KEY'
    conn.execute('CREATE TABLE IF NOT EXISTS item_barcodes(id '+key+',item_code TEXT NOT NULL,namespace TEXT NOT NULL,barcode TEXT NOT NULL,kind TEXT NOT NULL,UNIQUE(namespace,barcode),CHECK(namespace IN (\'plain\',\'scale\')),CHECK(kind IN (\'manufacturer\',\'internal\',\'extra\',\'scale\')))')

    if getattr(conn,'_queue_writes',False):
        from offline_store import _erp_install_capture
        _erp_install_capture(conn)
def normalize(value):
    if value is None:return ''
    if not isinstance(value,str):raise ValueError('أدخل الباركود كنص للحفاظ على الأصفار الأولى')
    value=value.strip()
    if len(value)>80 or any(ord(c)<33 or ord(c)>126 for c in value):raise ValueError('الباركود يجب أن يكون نصًا صالحًا دون مسافات أو أحرف تحكم')
    return value
def internal_code():return 'AZ'+uuid.uuid4().hex.upper()
def settings(conn):
    return {str(r['setting_key']):str(r['setting_value']) for r in conn.execute("SELECT setting_key,setting_value FROM app_settings WHERE setting_key LIKE ?",('scale_%',)).fetchall() if r['setting_key'] in SCALE_KEYS}
def scale_key(code,width):
    code=normalize(code)
    if not code:return ''
    if not re.fullmatch('[0-9]+',code) or not 1<=int(width)<=18 or len(code)>int(width):raise ValueError('كود الميزان يجب أن يكون رقميًا وفي طول خانة الصنف المحددة')
    return code.zfill(int(width))
def parse_scale(code,cfg):
    if str(cfg.get('scale_enabled','1'))!='1':return None
    prefix=str(cfg.get('scale_prefix','90'))
    if prefix and not code.startswith(prefix):return None
    if not re.fullmatch('[0-9]+',code):
        if prefix and code.startswith(prefix):raise ValueError('باركود الميزان غير رقمي')
        return None
    try:
        start=int(cfg.get('scale_item_start',2));length=int(cfg.get('scale_item_length',5));vstart=int(cfg.get('scale_value_start',7));vlength=int(cfg.get('scale_value_length',5));divisor=Decimal(str(cfg.get('scale_divisor',100)));mode=cfg.get('scale_value_mode','price')
        if min(start,vstart)<len(prefix) or not 1<=length<=18 or not 1<=vlength<=18 or max(start+length,vstart+vlength)>80 or max(start,vstart)<min(start+length,vstart+vlength):raise ValueError('مواضع باركود الميزان متداخلة أو غير صحيحة')
        if not divisor.is_finite() or divisor<=0 or mode not in ('price','weight'):raise ValueError('نوع قيمة الميزان أو معامل القسمة غير صحيح')
        if len(code)<max(start+length,vstart+vlength):raise ValueError('باركود الميزان أقصر من الصيغة المحددة')
        value=float(Decimal(code[vstart:vstart+vlength])/divisor)
        if not math.isfinite(value):raise ValueError('قيمة الميزان أكبر من النطاق الحسابي المسموح')
        return {'item_code':code[start:start+length],'value':value,'value_decimal':str(Decimal(code[vstart:vstart+vlength])/divisor),'mode':mode}
    except (ValueError,ArithmeticError,TypeError) as exc:raise ValueError('تعذر فك باركود الميزان: '+str(exc)) from exc

def _single(rows):
    rows={int(r['id']):r for r in rows}
    if len(rows)>1:raise ValueError('الباركود مرتبط بأكثر من صنف؛ يلزم تصحيح الربط قبل البيع')
    return next(iter(rows.values()),None)
def resolve_plain(conn,branch_id,code):
    code=code.strip() if isinstance(code,str) else normalize(code);rows=list(conn.execute('SELECT * FROM items WHERE branch_id=? AND item_code=?',(branch_id,code)).fetchall())
    if exists(conn):rows+=list(conn.execute('SELECT i.* FROM items i JOIN item_barcodes b ON b.item_code=i.item_code WHERE i.branch_id=? AND b.namespace=? AND b.barcode=?',(branch_id,'plain',code)).fetchall())
    return _single(rows)
def resolve_scale(conn,branch_id,code,width):
    key=scale_key(code,width);rows=[]
    if exists(conn):rows=list(conn.execute('SELECT i.* FROM items i JOIN item_barcodes b ON b.item_code=i.item_code WHERE i.branch_id=? AND b.namespace=? AND b.barcode=?',(branch_id,'scale',key)).fetchall())
    legacy=conn.execute("SELECT * FROM items WHERE branch_id=? AND scale_code IS NOT NULL AND TRIM(scale_code)<>'' AND LTRIM(TRIM(scale_code),'0')=?",(branch_id,key.lstrip('0'))).fetchall()
    for row in legacy:
        try:match=scale_key(str(row['scale_code']),width)==key
        except ValueError:match=False
        if match:rows.append(row)
    if rows:return _single(rows)
    # Explicit scale mappings win. Retain the original numeric item_code fallback
    # only if it identifies exactly one item, never choose an arbitrary LIMIT1.
    rows=[]
    for row in conn.execute("SELECT * FROM items WHERE branch_id=? AND LTRIM(TRIM(item_code),'0')=?",(branch_id,key.lstrip('0'))).fetchall():
        try:match=scale_key(str(row['item_code']),width)==key
        except ValueError:match=False
        if match:rows.append(row)
    return _single(rows)
def lock_codes(conn,codes):
    if is_sqlite(conn):
        if not raw(conn).in_transaction:conn.execute('BEGIN IMMEDIATE')
    else:
        for code in sorted(set(codes)):conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('abuzaid:barcode:'+code,))
def guard_primary(conn,code):
    if exists(conn):
        row=conn.execute('SELECT item_code FROM item_barcodes WHERE namespace=? AND barcode=?',('plain',code)).fetchone()
        if row and row['item_code']!=code:raise ValueError('كود الصنف مستخدم كأحد باركودات صنف مختلف')
def validate_link(conn,item_code,namespace,barcode,kind,exclude_id=None,width=None):
    if namespace not in ('plain','scale') or kind not in ('manufacturer','internal','extra','scale') or (namespace=='scale')!=(kind=='scale'):raise ValueError('نوع ربط الباركود غير صحيح')
    barcode=normalize(barcode);item_code=str(item_code or "").strip()
    if not barcode or not item_code:raise ValueError('كود الصنف والباركود مطلوبان')
    cfg=settings(conn)
    width=int(width if width is not None else cfg.get('scale_item_length',5))
    if namespace=='scale' and barcode!=scale_key(barcode,width):raise ValueError('كود الميزان غير مطابق لطول خانة الصنف')
    lock_codes(conn,[barcode])
    target=conn.execute('SELECT item_name FROM items WHERE item_code=?',(item_code,)).fetchall()
    names={' '.join(str(r['item_name']).casefold().split()) for r in target}
    if not target or len(names)!=1:raise ValueError('كود الصنف غير موجود أو يخص أسماء أصناف متعارضة')
    if namespace=='plain':
        other=conn.execute('SELECT 1 FROM items WHERE item_code=? AND item_code<>? LIMIT 1',(barcode,item_code)).fetchone()
        if other:raise ValueError('باركود المصنع مستخدم ككود أساسي لصنف آخر')
        try:decoded=parse_scale(barcode,cfg)
        except ValueError:decoded=None
        if decoded:
            for branch in conn.execute('SELECT DISTINCT branch_id FROM items').fetchall():
                scale_item=resolve_scale(conn,branch['branch_id'],decoded['item_code'],width)
                if scale_item is not None and scale_item['item_code']!=item_code:raise ValueError('باركود المصنع مطابق لباركود ميزان لصنف مختلف')
    else:
        for row in conn.execute("SELECT item_code,scale_code FROM items WHERE scale_code IS NOT NULL AND TRIM(scale_code)<>''").fetchall():
            try:match=scale_key(str(row['scale_code']),width)==barcode
            except ValueError:match=False
            if match and row['item_code']!=item_code:raise ValueError('كود الميزان مرتبط بصنف آخر')
    if namespace=='scale':
        fixed=list(conn.execute('SELECT item_code,item_code AS barcode FROM items').fetchall())
        if exists(conn):fixed+=list(conn.execute('SELECT item_code,barcode FROM item_barcodes WHERE namespace=?',('plain',)).fetchall())
        for row in fixed:
            try:decoded=parse_scale(str(row['barcode']),cfg)
            except ValueError:decoded=None
            if decoded and scale_key(decoded['item_code'],width)==barcode and row['item_code']!=item_code:raise ValueError('كود الميزان ينتج باركودًا مطابقًا لباركود مصنع لصنف مختلف')
    if exists(conn):
        other=conn.execute('SELECT id,item_code FROM item_barcodes WHERE namespace=? AND barcode=?',(namespace,barcode)).fetchone()
        if other and (exclude_id is None or int(other['id'])!=int(exclude_id)) and other['item_code']!=item_code:raise ValueError('هذا الباركود مرتبط بصنف آخر')
    return barcode

def links(conn,item_code):
    return list(conn.execute('SELECT * FROM item_barcodes WHERE item_code=? ORDER BY id',(item_code,)).fetchall()) if exists(conn) else []
def payload_entries(payload,cfg):
    rows=[]
    for field,kind in (('manufacturer','manufacturer'),('internal','internal')):
        value=normalize(payload.get(field,''))
        if value:rows.append(('plain',value,kind))
    for value in str(payload.get('extra','')).splitlines():
        if value.strip():rows.append(('plain',normalize(value),'extra'))
    for value in str(payload.get('scale','')).splitlines():
        if value.strip():rows.append(('scale',scale_key(value,int(cfg.get('scale_item_length',5))),'scale'))
    keys=[x[:2] for x in rows]
    if len(keys)!=len(set(keys)):raise ValueError('يوجد باركود مكرر داخل بيانات الصنف')
    if len(rows)>100:raise ValueError('الحد الأقصى مائة باركود للصنف في الحفظ الواحد')
    return rows

def save_links(conn,actor_id,branch_id,item_code,payload):
    actor=conn.execute('SELECT role,is_active FROM users WHERE id=?',(actor_id,)).fetchone()
    if not actor or not actor['is_active'] or actor['role'] not in ('Super_Admin','Admin','Manager'):raise PermissionError('حفظ الباركودات يتطلب صلاحية الإدارة المركزية')
    branch=conn.execute('SELECT branch_name,branch_type FROM branches WHERE id=?',(branch_id,)).fetchone()
    if not branch or not (branch['branch_type']=='مخزن' or 'رئيس' in str(branch['branch_name'])):raise PermissionError('تُعرّف باركودات الأصناف من المخزن الرئيسي')
    cfg=settings(conn);entries=payload_entries(payload,cfg);ensure_schema(conn);lock_codes(conn,[x[1] for x in entries])
    old={(r['namespace'],r['barcode']):r for r in links(conn,item_code)};wanted={r[:2] for r in entries}
    for namespace,barcode,kind in entries:validate_link(conn,item_code,namespace,barcode,kind,old.get((namespace,barcode),{}).get('id') if isinstance(old.get((namespace,barcode)),dict) else (old[(namespace,barcode)]['id'] if (namespace,barcode) in old else None))
    for key,row in old.items():
        if key not in wanted:conn.execute('DELETE FROM item_barcodes WHERE id=?',(row['id'],))
    for namespace,barcode,kind in entries:
        prior=old.get((namespace,barcode))
        if prior:
            if prior['kind']!=kind:conn.execute('UPDATE item_barcodes SET kind=? WHERE id=?',(kind,prior['id']))
        else:conn.execute('INSERT INTO item_barcodes(item_code,namespace,barcode,kind) VALUES(?,?,?,?)',(item_code,namespace,barcode,kind))
    return entries

def guard_scale(conn,item_code,code):
    if not str(code or '').strip():return
    width=int(settings(conn).get('scale_item_length',5));key=scale_key(str(code),width)
    # Validation needs an existing target only when linking aliases; a newly
    # created item can be checked for conflicts before its INSERT.
    lock_codes(conn,[key])
    if exists(conn):
        r=conn.execute('SELECT item_code FROM item_barcodes WHERE namespace=? AND barcode=?',('scale',key)).fetchone()
        if r and r['item_code']!=item_code:raise ValueError('كود الميزان مرتبط بصنف آخر')
    for r in conn.execute("SELECT item_code,scale_code FROM items WHERE scale_code IS NOT NULL AND TRIM(scale_code)<>''").fetchall():
        try:match=scale_key(str(r['scale_code']),width)==key
        except ValueError:match=False
        if match and r['item_code']!=item_code:raise ValueError('كود الميزان مرتبط بصنف آخر')


def apply_snapshot(conn,rows,allowed_codes,scale_settings):
    if not isinstance(rows,list) or not isinstance(scale_settings,dict) or set(scale_settings)-SCALE_KEYS:raise ValueError('استجابة الباركود أو إعدادات الميزان غير صحيحة')
    cfg=settings(conn);cfg.update({k:str(v) for k,v in scale_settings.items()})
    width=int(cfg.get('scale_item_length',5));seen=set();remote_ids=set()
    for row in rows:
        if set(row)!={'id','item_code','namespace','barcode','kind'} or row['item_code'] not in allowed_codes:raise ValueError('ربط باركود خارج بيانات الفرع المسموح بها')
        barcode=normalize(row['barcode']);namespace=row['namespace'];kind=row['kind'];remote=int(row['id']);key=(namespace,barcode)
        if namespace not in ('plain','scale') or kind not in ('manufacturer','internal','extra','scale') or (namespace=='scale')!=(kind=='scale') or not barcode or remote<=0 or key in seen or remote in remote_ids:raise ValueError('تعارض في استجابة الباركود')
        if namespace=='scale' and scale_key(barcode,width)!=barcode:raise ValueError('كود ميزان غير مطابق للصيغة')
        seen.add(key);remote_ids.add(remote)
    ensure_schema(conn);kept=set()
    for row in rows:
        mapping=conn.execute('SELECT local_id FROM erp_id_map WHERE table_name=? AND remote_id=?',(TABLE,row['id'])).fetchone()
        prior=conn.execute('SELECT id FROM item_barcodes WHERE namespace=? AND barcode=?',(row['namespace'],row['barcode'])).fetchone()
        local_id=int(mapping['local_id']) if mapping else int(prior['id']) if prior else None
        if local_id is None:
            cursor=conn.execute('INSERT INTO item_barcodes(item_code,namespace,barcode,kind) VALUES(?,?,?,?)',tuple(row[k] for k in ('item_code','namespace','barcode','kind')));local_id=cursor.lastrowid
        else:
            conn.execute('INSERT INTO item_barcodes(id,item_code,namespace,barcode,kind) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET item_code=excluded.item_code,namespace=excluded.namespace,barcode=excluded.barcode,kind=excluded.kind',(local_id,)+tuple(row[k] for k in ('item_code','namespace','barcode','kind')))
        conn.execute('INSERT INTO erp_id_map(table_name,local_id,remote_id) VALUES(?,?,?) ON CONFLICT(table_name,local_id) DO UPDATE SET remote_id=excluded.remote_id',(TABLE,local_id,row['id']));kept.add(local_id)
    for row in conn.execute('SELECT id FROM item_barcodes').fetchall():
        if int(row['id']) not in kept:conn.execute('DELETE FROM item_barcodes WHERE id=?',(row['id'],))
    for key,value in scale_settings.items():conn.execute('INSERT INTO app_settings(setting_key,setting_value) VALUES(?,?) ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value',(key,str(value)))
