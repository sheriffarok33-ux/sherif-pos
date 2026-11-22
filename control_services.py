"""Shared headless control services; no UI, network or database is opened on import."""

def _control_verify_password(password, stored):
    import hashlib, hmac
    stored = str(stored or '')
    if not stored.startswith('pbkdf2_sha256$'):
        return bool(stored) and hmac.compare_digest(str(password).encode('utf-8'), stored.encode('utf-8'))
    try:
        scheme, rounds, salt, expected = stored.split('$')
        if not 100000 <= int(rounds) <= 2000000 or len(bytes.fromhex(salt)) != 16:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', str(password).encode('utf-8'), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False

# Source fragment appended verbatim to both existing database.py files.
def _control_execute(conn, sql, params=()):
    import sqlite3
    raw = getattr(conn, '_conn', conn)
    if isinstance(raw, sqlite3.Connection):
        return raw.execute(sql, params)
    if hasattr(conn, 'execute'):
        return conn.execute(sql, params)
    from psycopg2.extras import DictCursor
    cur = conn.cursor(cursor_factory=DictCursor)
    cur.execute(sql.replace('?', '%s'), params)
    return cur


def _control_table_exists(conn, name):
    import sqlite3
    raw = getattr(conn, '_conn', conn)
    if isinstance(raw, sqlite3.Connection):
        return _control_execute(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
    return _control_execute(conn, 'SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=?', (name,)).fetchone() is not None


def business_date_today():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo('Africa/Tripoli')).date()


def ensure_governance_schema(conn):
    """Additive schema only; callers run migrations before business transactions."""
    ensure_exception_settlement_schema(conn)
    import sqlite3
    if isinstance(getattr(conn,'_conn',conn),sqlite3.Connection):
        _control_execute(conn,'''CREATE TABLE IF NOT EXISTS branch_exception_cache(
            id INTEGER PRIMARY KEY,branch_id INTEGER NOT NULL,user_id INTEGER,offline_uuid TEXT UNIQUE NOT NULL,
            notes TEXT NOT NULL,branch_name TEXT,username TEXT,authority_uuid TEXT NOT NULL)''')
    for sql in (
        '''CREATE TABLE IF NOT EXISTS audit_events_v1(
        event_uuid TEXT PRIMARY KEY, actor_user_id INTEGER, actor_role TEXT,
        branch_id INTEGER, device_id TEXT, action_type TEXT NOT NULL,
        entity_type TEXT NOT NULL, entity_id TEXT, outcome TEXT NOT NULL,
        occurred_at TEXT NOT NULL, recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        details_json TEXT NOT NULL, content_hash TEXT NOT NULL)''',
        '''CREATE INDEX IF NOT EXISTS ix_audit_events_v1_scope ON audit_events_v1(branch_id,occurred_at,event_uuid)''',
        '''CREATE TABLE IF NOT EXISTS account_lifecycle_decisions(
        decision_uuid TEXT PRIMARY KEY, employee_id INTEGER, user_id INTEGER NOT NULL,
        action_type TEXT NOT NULL, effective_on TEXT NOT NULL,
        approved_by INTEGER NOT NULL, approved_at TEXT NOT NULL,
        decision_state TEXT NOT NULL DEFAULT 'approved')''',
        '''CREATE INDEX IF NOT EXISTS ix_account_lifecycle_effective ON account_lifecycle_decisions(user_id,decision_state,effective_on)''',
        '''CREATE TABLE IF NOT EXISTS product_expiry_policies(
        branch_id INTEGER NOT NULL,item_id INTEGER NOT NULL,shelf_life_days INTEGER NOT NULL,
        approved_by INTEGER NOT NULL,approved_at TEXT NOT NULL,policy_version TEXT NOT NULL,
        PRIMARY KEY(branch_id,item_id))''',
    ):
        _control_execute(conn, sql)


def write_audit_event(conn, action, actor_id, branch_id, entity_type, entity_id,
                      details=None, event_uuid=None, device_id=None, outcome='success', occurred_at=None):
    """Audit failure propagates: the caller must roll back the business transaction."""
    import json, hashlib, uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo
    allowed = {'employee_id','effective_on','quantity','old_quantity','new_quantity',
               'amount','reason_code','decision_uuid','source_transaction_uuid',
               'records','table','fields','policy_version','shelf_life_days'}
    details = dict(details or {})
    if set(details) - allowed:
        raise ValueError('Unapproved audit detail fields')
    role = 'SYSTEM'
    if actor_id is not None:
        row = _control_execute(conn, 'SELECT role FROM users WHERE id=?', (actor_id,)).fetchone()
        role = str(row[0]) if row else 'UNKNOWN'
    event_uuid = str(event_uuid or uuid.uuid4())
    seen = _control_execute(conn, 'SELECT content_hash,occurred_at FROM audit_events_v1 WHERE event_uuid=?', (event_uuid,)).fetchone()
    # A retry without an explicit source time reuses the first event's time.
    # Every other payload field is still compared, so UUID reuse cannot overwrite evidence.
    if seen and occurred_at is None:
        occurred_at = seen[1]
    payload = {'actor_user_id':actor_id,'actor_role':role,'branch_id':branch_id,
               'device_id':device_id,'action_type':action,'entity_type':entity_type,
               'entity_id':None if entity_id is None else str(entity_id),'outcome':outcome,
               'occurred_at':occurred_at or datetime.now(ZoneInfo('Africa/Tripoli')).isoformat(timespec='seconds'),
               'details_json':json.dumps(details,ensure_ascii=False,sort_keys=True,separators=(',',':'))}
    digest = hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if seen:
        if seen[0] != digest:
            raise ValueError('Audit event identity conflict')
        return event_uuid
    _control_execute(conn, '''INSERT INTO audit_events_v1(event_uuid,actor_user_id,actor_role,branch_id,device_id,
        action_type,entity_type,entity_id,outcome,occurred_at,details_json,content_hash)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (event_uuid,*payload.values(),digest))
    return event_uuid


def _lock_account_lifecycle(conn):
    import sqlite3
    raw = getattr(conn, '_conn', conn)
    if isinstance(raw, sqlite3.Connection):
        if not raw.in_transaction:
            raw.execute('BEGIN IMMEDIATE')
    else:
        _control_execute(conn, 'SELECT pg_advisory_xact_lock(728919,1)')


def _current_super_admin(conn, actor_id):
    row = _control_execute(conn, 'SELECT role,is_active FROM users WHERE id=?', (actor_id,)).fetchone()
    if not row or row[0] != 'Super_Admin' or not row[1] or not account_login_allowed(conn, actor_id):
        raise PermissionError('Only a current active Super_Admin may approve this decision')


def assert_future_super_admin_coverage(conn, excluding_user_id=None, proposed_termination=None):
    """Protect every scheduled date, including schedules approved in reverse order."""
    from datetime import date
    supers = {int(r[0]) for r in _control_execute(conn, "SELECT id FROM users WHERE role='Super_Admin' AND is_active=1").fetchall()}
    if excluding_user_id is not None:
        supers.discard(int(excluding_user_id))
    endings = {}
    if _control_table_exists(conn, 'account_lifecycle_decisions'):
        for uid,effective in _control_execute(conn, "SELECT user_id,effective_on FROM account_lifecycle_decisions WHERE decision_state='approved' AND action_type IN ('terminate','disable')").fetchall():
            if int(uid) in supers:
                when = date.fromisoformat(str(effective))
                endings[int(uid)] = min(when,endings.get(int(uid),when))
    if proposed_termination and int(proposed_termination[0]) in supers:
        uid,when = int(proposed_termination[0]),proposed_termination[1]
        endings[uid] = min(when,endings.get(uid,when))
    dates = {business_date_today(),*endings.values()}
    if any(not any(uid not in endings or endings[uid] > when for uid in supers) for when in dates):
        raise ValueError('لا يمكن إنهاء أو تعطيل آخر Super_Admin نشط، بما في ذلك القرارات المستقبلية.')


def account_login_allowed(conn, user_id, on_date=None):
    row = _control_execute(conn, 'SELECT is_active FROM users WHERE id=?', (user_id,)).fetchone()
    if not row or not row[0]:
        return False
    if not _control_table_exists(conn, 'account_lifecycle_decisions'):
        return True  # Old database: no scheduled decisions can exist there.
    when = str(on_date or business_date_today())
    return _control_execute(conn, """SELECT 1 FROM account_lifecycle_decisions
        WHERE user_id=? AND decision_state='approved' AND action_type IN ('terminate','disable')
        AND effective_on<=? LIMIT 1""", (user_id,when)).fetchone() is None


def _verify_super_confirmation(conn, actor_id, password):
    actor = _control_execute(conn, 'SELECT password FROM users WHERE id=?', (actor_id,)).fetchone()
    valid_password = bool(actor) and _control_verify_password(password, actor[0])
    if actor and not actor[0]:
        import sqlite3
        if isinstance(getattr(conn, '_conn', conn), sqlite3.Connection):
            from branch_auth import verify_local_user_password
            valid_password = verify_local_user_password(actor_id, password)
    if not valid_password:
        raise PermissionError('كلمة مرور التأكيد غير صحيحة.')


def approve_account_state(conn, user_id, enabled, actor_id, password):
    """No commit here: state and mandatory audit are one caller-owned transaction."""
    import uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _lock_account_lifecycle(conn)
    _current_super_admin(conn, actor_id)
    _verify_super_confirmation(conn, actor_id, password)
    target = _control_execute(conn, 'SELECT role,is_active,branch_id FROM users WHERE id=?', (user_id,)).fetchone()
    if not target:
        raise ValueError('الحساب غير موجود.')
    if enabled:
        ended = _control_execute(conn, "SELECT 1 FROM account_lifecycle_decisions WHERE user_id=? AND action_type='terminate' AND decision_state='approved' AND effective_on<=?", (user_id,str(business_date_today()))).fetchone()
        if ended:
            raise ValueError('يلزم اعتماد عودة الموظف للخدمة قبل تفعيل حسابه.')
    elif target[0] == 'Super_Admin':
        assert_future_super_admin_coverage(conn, excluding_user_id=user_id)
    _control_execute(conn, "UPDATE account_lifecycle_decisions SET decision_state='superseded' WHERE user_id=? AND action_type='disable' AND decision_state='approved'", (user_id,))
    decision = str(uuid.uuid4())
    action = 'enable' if enabled else 'disable'
    _control_execute(conn, '''INSERT INTO account_lifecycle_decisions(decision_uuid,user_id,action_type,effective_on,approved_by,approved_at)
        VALUES(?,?,?,?,?,?)''', (decision,user_id,action,str(business_date_today()),actor_id,datetime.now(ZoneInfo('Africa/Tripoli')).isoformat(timespec='seconds')))
    _control_execute(conn, 'UPDATE users SET is_active=? WHERE id=?', (1 if enabled else 0,user_id))
    write_audit_event(conn,'account_'+action,actor_id,target[2],'users',user_id,{'decision_uuid':decision})
    return decision


def approve_employee_termination(conn, employee, ended, effective_on, actor_id, password=None):
    """Only Super_Admin changes the approved employment termination decision."""
    import uuid
    from datetime import datetime,date
    from zoneinfo import ZoneInfo
    _lock_account_lifecycle(conn)
    current = _control_execute(conn,'SELECT * FROM employees WHERE id=?',(employee['id'],)).fetchone()
    if not current:
        raise ValueError('ملف الموظف غير موجود.')
    if any(str(current[key] or '') != str(employee[key] or '') for key in ('user_id','termination_date','employment_status')):
        raise ValueError('تغير قرار الموظف أثناء التعديل؛ أعد تحميل الملف قبل الاعتماد.')
    employee = current
    existing = employee['termination_date']
    existing = None if existing in (None,'') else str(existing)[:10]
    desired = str(effective_on)[:10] if ended else None
    was_ended = existing is not None or employee['employment_status'] != 'active'
    if existing == desired and was_ended == bool(ended):
        return  # Ordinary edits do not acquire a new termination authority.
    _lock_account_lifecycle(conn)
    _current_super_admin(conn, actor_id)
    _verify_super_confirmation(conn, actor_id, password)
    uid = employee['user_id']
    if uid is not None and ended:
        assert_future_super_admin_coverage(conn, proposed_termination=(uid,date.fromisoformat(desired)))
    _control_execute(conn, "UPDATE account_lifecycle_decisions SET decision_state='superseded' WHERE employee_id=? AND action_type='terminate' AND decision_state='approved'", (employee['id'],))
    decision = str(uuid.uuid4())
    if uid is not None and ended:
        _control_execute(conn, '''INSERT INTO account_lifecycle_decisions(decision_uuid,employee_id,user_id,action_type,effective_on,approved_by,approved_at)
            VALUES(?,?,?,'terminate',?,?,?)''', (decision,employee['id'],uid,desired,actor_id,datetime.now(ZoneInfo('Africa/Tripoli')).isoformat(timespec='seconds')))
        if date.fromisoformat(desired) <= business_date_today():
            _control_execute(conn,'UPDATE users SET is_active=0 WHERE id=?',(uid,))
    write_audit_event(conn,'employment_termination' if ended else 'employment_termination_cancelled',actor_id,employee['branch_id'],
                      'employees',employee['id'],{'employee_id':employee['id'],'effective_on':desired,'decision_uuid':decision})


def set_product_expiry_policy(conn, branch_id, item_id, days, actor_id):
    import uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _current_super_admin(conn, actor_id)
    if type(days) is not int or not 1 <= days <= 36500:
        raise ValueError('مدة صلاحية الإنتاج يجب أن تكون عدداً صحيحاً موجباً بالأيام.')
    if not _control_execute(conn,'SELECT 1 FROM items WHERE id=? AND branch_id=?',(item_id,branch_id)).fetchone():
        raise ValueError('الصنف لا يتبع الفرع المحدد.')
    version = str(uuid.uuid4())
    _control_execute(conn, '''INSERT INTO product_expiry_policies(branch_id,item_id,shelf_life_days,approved_by,approved_at,policy_version)
        VALUES(?,?,?,?,?,?) ON CONFLICT(branch_id,item_id) DO UPDATE SET shelf_life_days=excluded.shelf_life_days,
        approved_by=excluded.approved_by,approved_at=excluded.approved_at,policy_version=excluded.policy_version''',
        (branch_id,item_id,days,actor_id,datetime.now(ZoneInfo('Africa/Tripoli')).isoformat(timespec='seconds'),version))
    write_audit_event(conn,'production_expiry_policy',actor_id,branch_id,'items',item_id,{'policy_version':version,'shelf_life_days':days})
    return version



def install_local_financial_audit(conn, actor_id, device_id):
    """Connection-local SQLite triggers; audit and business rows commit together.

    No network, raw SQL parameters, notes, passwords or credentials are logged.
    An audit INSERT failure aborts the same business statement/transaction.
    """
    import sqlite3,json,hashlib,uuid
    raw=getattr(conn,'_conn',conn)
    if not isinstance(raw,sqlite3.Connection):raise TypeError('SQLite audit capture required')
    ensure_governance_schema(raw)
    actor='NULL' if actor_id is None else str(int(actor_id))
    device="'"+str(device_id or '').replace("'","''")+"'"
    role="COALESCE((SELECT role FROM users WHERE id="+actor+"),'SYSTEM')"
    raw.create_function('local_audit_uuid',0,lambda:str(uuid.uuid4()))
    def digest(*values):
        keys=('actor_user_id','actor_role','branch_id','device_id','action_type','entity_type','entity_id','outcome','occurred_at','details_json')
        return hashlib.sha256(json.dumps(dict(zip(keys,values)),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    raw.create_function('local_audit_digest',10,digest)
    tables=('invoices','expenses','revenues','stock_adjustments','production_logs',
            'transfer_logs','financial_vouchers','treasury_movements','supplier_payments',
            'purchases','purchase_items','employee_financial_transactions','damaged_stock',
            'inventory_batches','items','shifts','shift_closures')
    for table in tables:
        if not _control_table_exists(raw,table):continue
        columns=[row[1] for row in raw.execute('PRAGMA table_info("'+table+'")')]
        if 'id' not in columns:continue
        # Synchronization bookkeeping alone is not a second financial action.
        relevant=[x for x in columns if x not in ('sync_status','sync_error','synced_at','is_synced','remote_id','updated_at')]
        changed=' OR '.join('OLD."'+x+'" IS NOT NEW."'+x+'"' for x in relevant)
        details="json_object('table','"+table+"','fields',json_array("+','.join("'"+x+"'" for x in relevant if x not in ('notes','password','token'))+'))'
        for operation in ('INSERT','UPDATE','DELETE'):
            image='OLD' if operation=='DELETE' else 'NEW'
            branch=image+'.branch_id' if 'branch_id' in columns else 'NULL'
            if 'branch_id' not in columns and 'from_branch_id' in columns:branch=image+'.from_branch_id'
            entity='CAST('+image+'.id AS TEXT)';action="'"+table+'_'+operation.lower()+"'"
            timestamp="strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            event_details = details
            if operation == 'UPDATE':
                fields = ["CASE WHEN OLD.\""+x+"\" IS NOT NEW.\""+x+"\" THEN '"+x+"' END" for x in relevant if x not in ('notes','password','token')]
                event_details = "json_object('table','"+table+"','fields',json((SELECT json_group_array(value) FROM json_each(json_array("+','.join(fields)+")) WHERE value IS NOT NULL)))"
            values=[actor,role,branch,device,action,"'"+table+"'",entity,"'success'",timestamp,event_details]
            condition=' WHEN '+changed if operation=='UPDATE' else ''
            raw.execute('CREATE TEMP TRIGGER IF NOT EXISTS "mandatory_audit_'+table+'_'+operation.lower()+'" AFTER '+operation+' ON main."'+table+'"'+condition+''' BEGIN
                INSERT INTO audit_events_v1(event_uuid,actor_user_id,actor_role,branch_id,device_id,action_type,
                entity_type,entity_id,outcome,occurred_at,details_json,content_hash) SELECT local_audit_uuid(),'''+','.join(values)+',local_audit_digest('+','.join(values)+'); END')


def ensure_postgres_financial_audit(conn):
    """Isolated/deployment migration only. Never called by a report reader."""
    import sqlite3
    if isinstance(getattr(conn,'_conn',conn),sqlite3.Connection):return
    ensure_governance_schema(conn)
    _control_execute(conn,r'''
    CREATE OR REPLACE FUNCTION abuzaid_financial_audit_v1() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
        row_data jsonb; before_data jsonb; actor integer; actor_role_value text;
        branch integer; device text; fields json; details_text text; action_value text;
        entity_value text; stamp text; canonical text;
    BEGIN
        IF COALESCE(current_setting('abuzaid.require_audit',true),'') <> 'on' THEN
            IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
        END IF;
        actor := NULLIF(current_setting('abuzaid.actor_id',true),'')::integer;
        SELECT role INTO actor_role_value FROM users WHERE id=actor AND is_active=1;
        IF actor_role_value IS NULL OR EXISTS(
            SELECT 1 FROM account_lifecycle_decisions WHERE user_id=actor AND decision_state='approved'
            AND action_type IN ('terminate','disable') AND effective_on <= to_char(now() AT TIME ZONE 'Africa/Tripoli','YYYY-MM-DD')) THEN
            RAISE EXCEPTION USING ERRCODE='42501',MESSAGE='Current audit actor is not authorized';
        END IF;
        row_data := CASE WHEN TG_OP='DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
        before_data := CASE WHEN TG_OP='INSERT' THEN '{}'::jsonb ELSE to_jsonb(OLD) END;
        SELECT COALESCE(json_agg(key ORDER BY key),'[]'::json) INTO fields
            FROM jsonb_object_keys(row_data || before_data) AS x(key)
            WHERE key NOT IN ('sync_status','sync_error','synced_at','is_synced','remote_id','updated_at')
            AND (TG_OP<>'UPDATE' OR row_data->key IS DISTINCT FROM before_data->key);
        IF TG_OP='UPDATE' AND json_array_length(fields)=0 THEN RETURN NEW; END IF;
        branch := NULLIF(COALESCE(row_data->>'branch_id',row_data->>'from_branch_id'),'')::integer;
        IF branch IS NULL AND TG_TABLE_NAME='purchase_items' THEN
            SELECT branch_id INTO branch FROM purchases WHERE id=(row_data->>'purchase_id')::integer;
        END IF;
        device := NULLIF(current_setting('abuzaid.device_id',true),'');
        action_value := TG_TABLE_NAME || '_' || lower(TG_OP);
        entity_value := row_data->>'id';
        stamp := to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"');
        details_text := json_build_object('fields',fields,'table',TG_TABLE_NAME)::text;
        canonical := '{"action_type":' || to_json(action_value)::text ||
            ',"actor_role":' || to_json(actor_role_value)::text ||
            ',"actor_user_id":' || actor::text || ',"branch_id":' || COALESCE(branch::text,'null') ||
            ',"details_json":' || to_json(details_text)::text || ',"device_id":' || COALESCE(to_json(device)::text,'null') ||
            ',"entity_id":' || COALESCE(to_json(entity_value)::text,'null') ||
            ',"entity_type":' || to_json(TG_TABLE_NAME)::text || ',"occurred_at":' || to_json(stamp)::text ||
            ',"outcome":"success"}';
        BEGIN
        INSERT INTO audit_events_v1(event_uuid,actor_user_id,actor_role,branch_id,device_id,action_type,
            entity_type,entity_id,outcome,occurred_at,details_json,content_hash)
            VALUES(gen_random_uuid()::text,actor,actor_role_value,branch,device,action_value,TG_TABLE_NAME,
            entity_value,'success',stamp,details_text,encode(sha256(convert_to(canonical,'UTF8')),'hex'));
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION USING ERRCODE='PZ001',MESSAGE='Mandatory financial audit storage failure';
        END;
        IF TG_OP='DELETE' THEN RETURN OLD; ELSE RETURN NEW; END IF;
    END $$''')
    for table in ('invoices','expenses','revenues','stock_adjustments','production_logs','transfer_logs',
                  'financial_vouchers','treasury_movements','supplier_payments','purchases','purchase_items',
                  'employee_financial_transactions','damaged_stock','inventory_batches','items','shifts','shift_closures'):
        if not _control_table_exists(conn,table):continue
        columns=_control_execute(conn,"SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?",(table,)).fetchall()
        if not any(row[0]=='id' for row in columns):continue
        _control_execute(conn,'CREATE OR REPLACE TRIGGER mandatory_audit_'+table+' AFTER INSERT OR UPDATE OR DELETE ON "'+table+'" FOR EACH ROW EXECUTE FUNCTION abuzaid_financial_audit_v1()')



def weighted_inventory_receipt(old_quantity,old_unit_cost,received_quantity,received_unit_cost):
    """Preserve signed book value. No extra financial journal or guessed old cost."""
    from decimal import Decimal,InvalidOperation
    import math
    try:
        old,cost,received,price=(Decimal(str(x)) for x in (old_quantity,old_unit_cost,received_quantity,received_unit_cost))
    except (InvalidOperation,ValueError,TypeError):
        raise ValueError('كمية أو تكلفة المخزون غير صالحة؛ لم يُحفظ التوريد.')
    if not all(x.is_finite() for x in (old,cost,received,price)) or received<=0 or cost<0 or price<0:
        raise ValueError('كمية أو تكلفة المخزون غير صالحة؛ لم يُحفظ التوريد.')
    quantity=old+received;value=old*cost+received*price
    if quantity==0:
        if value!=0:
            raise ValueError('الرصيد النهائي صفر مع قيمة دفترية متبقية؛ يلزم اعتماد معالجة القيمة. المسودة محفوظة دون قيد إضافي.')
        average=price  # No stock value remains; retain the received price as the existing fallback.
    else:
        average=value/quantity
    if average<0 or not all(math.isfinite(float(x)) for x in (quantity,average)):
        raise ValueError('القيمة الدفترية تعطي متوسط تكلفة غير صالح؛ راجع المعالجة دون إسقاط العجز.')
    return float(quantity),float(average)


def ensure_exception_settlement_schema(conn):
    _control_execute(conn,'''CREATE TABLE IF NOT EXISTS branch_settlement_authorities(
        branch_id INTEGER PRIMARY KEY,device_id TEXT NOT NULL,authority_uuid TEXT NOT NULL,
        approved_by INTEGER NOT NULL,approved_at TEXT NOT NULL,is_released INTEGER NOT NULL DEFAULT 0)''')
    import sqlite3
    raw=getattr(conn,'_conn',conn)
    if isinstance(raw,sqlite3.Connection):
        columns={r[1] for r in raw.execute('PRAGMA table_info(branch_settlement_authorities)')}
    else:
        columns={r[0] for r in _control_execute(conn,"SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='branch_settlement_authorities'").fetchall()}
    if 'is_released' not in columns:
        _control_execute(conn,'ALTER TABLE branch_settlement_authorities ADD COLUMN is_released INTEGER NOT NULL DEFAULT 0')
    _control_execute(conn,'''CREATE TABLE IF NOT EXISTS exception_settlements(
        settlement_uuid TEXT PRIMARY KEY,branch_id INTEGER NOT NULL,item_id INTEGER NOT NULL,
        invoice_identity TEXT NOT NULL,device_id TEXT NOT NULL,authority_uuid TEXT NOT NULL,
        quantity TEXT NOT NULL,actor_id INTEGER NOT NULL,payload_json TEXT NOT NULL,
        payload_hash TEXT NOT NULL,result_json TEXT NOT NULL,sync_status TEXT NOT NULL,
        created_at TEXT NOT NULL)''')


def apply_exception_settlement(conn, *, settlement_uuid, branch_id, item_id, invoice_id,
                               invoice_identity, device_id, authority_uuid, quantity,
                               actor_id, payload_json, sync_status='pending', exception_item_id=None, invoice_table='invoices'):
    """One transaction, one approved device, bounded partial amounts, immutable receipt."""
    import json,hashlib
    from decimal import Decimal
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import sqlite3
    raw=getattr(conn,'_conn',conn)
    if isinstance(raw,sqlite3.Connection) and not raw.in_transaction:raw.execute('BEGIN IMMEDIATE')
    lock='' if isinstance(raw,sqlite3.Connection) else ' FOR UPDATE'
    _control_execute(conn,'SELECT id FROM branches WHERE id=?'+lock,(branch_id,)).fetchone()
    digest=hashlib.sha256(payload_json.encode('utf-8')).hexdigest()
    old=_control_execute(conn,'SELECT payload_hash,result_json FROM exception_settlements WHERE settlement_uuid=?',(settlement_uuid,)).fetchone()
    if old:
        if old['payload_hash']!=digest:raise ValueError('هوية التسوية مستخدمة بمحتوى مختلف')
        return json.loads(old['result_json'])
    actor=_control_execute(conn,'SELECT role,is_active FROM users WHERE id=?',(actor_id,)).fetchone()
    if not actor or not actor['is_active'] or not account_login_allowed(conn,actor_id) or actor['role'] not in ('Super_Admin','Admin','Manager','General_Supervisor'):
        raise PermissionError('لا توجد صلاحية لتسوية العجز')
    authority=_control_execute(conn,'SELECT device_id,authority_uuid,is_released FROM branch_settlement_authorities WHERE branch_id=?'+lock,(branch_id,)).fetchone()
    if not authority or authority['is_released'] or authority['device_id']!=device_id or authority['authority_uuid']!=authority_uuid:
        raise PermissionError('هذا الجهاز غير مفوض لتسويات الفرع')
    if invoice_table not in ('invoices','branch_exception_cache'):raise ValueError('Invalid invoice evidence source')
    if invoice_table=='branch_exception_cache':
        cache=_control_execute(conn,'SELECT authority_uuid FROM branch_exception_cache WHERE id=?',(invoice_id,)).fetchone()
        if not cache or cache['authority_uuid']!=authority_uuid:raise ValueError('Cached exception authority is stale')
    invoice=_control_execute(conn,'SELECT branch_id,notes FROM '+invoice_table+' WHERE id=?'+lock,(invoice_id,)).fetchone()
    item=_control_execute(conn,'SELECT item_name FROM items WHERE id=? AND branch_id=?'+lock,(item_id,branch_id)).fetchone()
    if not invoice or int(invoice['branch_id'])!=int(branch_id) or not item:raise ValueError('مرجع التسوية لا يتبع الفرع')
    notes=json.loads(invoice['notes'] or '{}')
    matches=[e for e in notes.get('stock_exceptions',[]) if str(e.get('item_id'))==str(item_id if exception_item_id is None else exception_item_id)]
    if len(matches)!=1:raise ValueError('مرجع الاستثناء مفقود أو ملتبس؛ يلزم مراجعة')
    exception=matches[0];shortfall=Decimal(str(exception['shortfall_qty']));amount=Decimal(str(quantity))
    if not shortfall.is_finite() or not amount.is_finite() or shortfall<=0 or amount<=0:raise ValueError('كمية التسوية غير صالحة')
    rows=_control_execute(conn,'SELECT quantity FROM exception_settlements WHERE branch_id=? AND item_id=? AND invoice_identity=?',
                          (branch_id,item_id,invoice_identity)).fetchall()
    total=sum((Decimal(str(r['quantity'])) for r in rows),Decimal(0))
    if invoice_table=='branch_exception_cache':
        baseline=Decimal(str(exception['surplus_baseline_qty']))
        if not baseline.is_finite() or baseline<0:raise ValueError('Invalid proven settlement baseline')
        total+=baseline
    if invoice_table=='invoices' and not rows and (exception.get('surplus_adjustment_done') or exception.get('surplus_adjustment_qty')):
        raise ValueError('توجد تسوية قديمة بلا إيصال جزئي؛ راجعها إدارياً قبل المتابعة')
    if total+amount>shortfall:raise ValueError('التسوية تتجاوز العجز المتبقي')
    settled=total+amount;remaining=shortfall-settled
    now=datetime.now(ZoneInfo('Africa/Tripoli')).isoformat(timespec='seconds')
    result={'settlement_uuid':settlement_uuid,'payload_hash':digest,'settled_quantity':str(settled),
            'remaining_quantity':str(remaining),'accepted':True}
    _control_execute(conn,'UPDATE items SET quantity=quantity+? WHERE id=? AND branch_id=?',(float(amount),item_id,branch_id))
    _control_execute(conn,'''INSERT INTO stock_adjustments(branch_id,item_id,item_name,quantity,adjustment_type,loss_or_gain_value,notes)
        VALUES(?,?,?,?,?,?,?)''',(branch_id,item_id,item['item_name'],float(amount),'فائض',0,
        'exception-settlement:'+settlement_uuid+' invoice:'+invoice_identity))
    exception.update(surplus_adjustment_done=remaining==0,surplus_adjustment_qty=float(settled),
                     surplus_remaining_qty=float(remaining),surplus_adjustment_by=actor_id,surplus_adjustment_at=now)
    _control_execute(conn,'UPDATE '+invoice_table+' SET notes=? WHERE id=?',(json.dumps(notes,ensure_ascii=False),invoice_id))
    _control_execute(conn,'''INSERT INTO exception_settlements(settlement_uuid,branch_id,item_id,invoice_identity,
        device_id,authority_uuid,quantity,actor_id,payload_json,payload_hash,result_json,sync_status,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(settlement_uuid,branch_id,item_id,invoice_identity,device_id,
        authority_uuid,str(amount),actor_id,payload_json,digest,json.dumps(result),sync_status,now))
    write_audit_event(conn,'exception_settlement',actor_id,branch_id,'invoice',invoice_identity,
                      {'quantity':float(amount)},event_uuid=settlement_uuid,device_id=device_id,occurred_at=now)
    return result


RECONCILE_TABLES = ('invoices','items','inventory_batches','purchases','purchase_items','suppliers','customers',
    'expenses','revenues','stock_adjustments','production_logs','transfer_logs',
    'transfer_safety_log','financial_vouchers','treasury_movements','supplier_payments',
    'employees','employee_financial_transactions','document_registry','damaged_stock',
    'shift_closures','shift_settlement_adjustments','users','user_branch_permissions')


def reconciliation_columns(columns):
    """Public business fields only; credentials/session data never enter a digest."""
    import re
    return sorted(c for c in columns if c not in ('id','synced_at','sync_status','sync_error',
        'receipt_pending','device_synced_at','server_id','local_id') and
        not re.search(r'password|token|secret|credential|verifier|salt|auth_key',c,re.I))


def reconciliation_digest(row, columns):
    import json,hashlib,math
    from decimal import Decimal
    from datetime import datetime,date
    def normal(value):
        if value is None:return None
        if isinstance(value,bool):return str(int(value))
        if isinstance(value,(int,float,Decimal)):
            d=Decimal(str(value))
            if not d.is_finite():raise ValueError('Invalid reconciliation number')
            return format(d.quantize(Decimal('0.00000001')).normalize(),'f')
        if isinstance(value,datetime):return value.isoformat(timespec='microseconds')
        if isinstance(value,date):return value.isoformat()
        if isinstance(value,dict):return {str(k):normal(v) for k,v in sorted(value.items())}
        if isinstance(value,list):return [normal(v) for v in value]
        text=str(value)
        if len(text)>=19 and text[4:5]=='-' and text[7:8]=='-' and text[10:11] in (' ','T'):
            try:return datetime.fromisoformat(text).isoformat(timespec='microseconds')
            except ValueError:pass
        if text[:1] in ('{','['):
            try:return normal(json.loads(text))
            except (ValueError,TypeError):pass
        return text
    image={c:normal(row.get(c)) for c in sorted(columns)}
    return hashlib.sha256(json.dumps(image,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()
