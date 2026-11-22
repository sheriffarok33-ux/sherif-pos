"""Local installation identity and first-admin provisioning.

This module does not represent server enrollment or product licensing.
Call provisioning only on an intentionally new commercial database.
"""
import hashlib
import hmac
import secrets
import sqlite3
import uuid

ITERATIONS = 310_000
MODE_KEY = 'sherif_local_mode'
INSTALLATION_KEY = 'sherif_local_installation_id'
DEVICE_KEY = 'sherif_local_device_id'
BRANCH_KEY = 'sherif_local_branch_id'


def password_hash(password):
    if not isinstance(password, str) or len(password) != 4 or not password.isascii() or not password.isdecimal():
        raise ValueError('الرقم السري يجب أن يتكون من 4 أرقام إنجليزية فقط (0-9).')
    salt = secrets.token_bytes(16)
    value = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${salt.hex()}${value.hex()}'


def password_matches(password, encoded):
    try:
        scheme, rounds, salt, expected = encoded.split('$')
        rounds = int(rounds)
        salt, expected = bytes.fromhex(salt), bytes.fromhex(expected)
        if scheme != 'pbkdf2_sha256' or not 100_000 <= rounds <= 2_000_000 or len(salt) != 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, rounds)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return False


def provision(conn, username, password, branch_name):
    """Initialize an empty schema atomically; reject any existing user or branch."""
    username = str(username or '').strip()
    branch_name = str(branch_name or '').strip()
    if not username or len(username) > 100 or not branch_name or len(branch_name) > 120:
        raise ValueError('اكتب اسم مدير واسم فرع صالحين.')
    hashed = password_hash(password)
    if conn.in_transaction:
        raise RuntimeError('يجب بدء التهيئة خارج أي معاملة أخرى.')
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM users LIMIT 1').fetchone() or conn.execute('SELECT 1 FROM branches LIMIT 1').fetchone():
            raise ValueError('التهيئة متاحة فقط لقاعدة تجارية جديدة وخالية من المستخدمين والفروع.')
        if conn.execute("SELECT 1 FROM local_meta WHERE key IN (?, ?, ?, 'device_id', 'server_enrolled', 'setup_complete') LIMIT 1", (MODE_KEY, INSTALLATION_KEY, DEVICE_KEY)).fetchone():
            raise ValueError('توجد هوية أو تهيئة سابقة؛ لم تُغيّر البيانات.')
        install_id, device_id = str(uuid.uuid4()), str(uuid.uuid4())
        cur = conn.execute('INSERT INTO branches (branch_name, branch_type, is_active) VALUES (?, ?, 1)', (branch_name, 'branch'))
        branch_id = int(cur.lastrowid)
        cur = conn.execute('INSERT INTO users (username, password, role, branch_id, is_active) VALUES (?, ?, ?, ?, 1)', (username, hashed, 'Super_Admin', branch_id))
        user_id = int(cur.lastrowid)
        conn.executemany('INSERT INTO local_meta (key, value) VALUES (?, ?)', [(MODE_KEY, '1'), (INSTALLATION_KEY, install_id), (DEVICE_KEY, device_id), (BRANCH_KEY, str(branch_id))])
        conn.commit()
        return {'installation_id': install_id, 'device_id': device_id, 'branch_id': branch_id, 'user_id': user_id}
    except Exception:
        conn.rollback()
        raise


def authenticate(conn, username, password):
    row = conn.execute('SELECT id, username, password, role, branch_id, is_active FROM users WHERE username=?', (str(username or '').strip(),)).fetchone()
    if not row or not row[5] or not password_matches(password, row[2]):
        return None
    return {'id': row[0], 'username': row[1], 'role': row[3], 'branch_id': row[4]}


def local_identity(conn):
    values = dict(conn.execute('SELECT key, value FROM local_meta WHERE key IN (?, ?, ?, ?)', (MODE_KEY, INSTALLATION_KEY, DEVICE_KEY, BRANCH_KEY)).fetchall())
    if values.get(MODE_KEY) != '1':
        return None
    try:
        install_id = str(uuid.UUID(values[INSTALLATION_KEY]))
        device_id = str(uuid.UUID(values[DEVICE_KEY]))
        branch_id = int(values[BRANCH_KEY])
        if branch_id <= 0:
            return None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    branch = conn.execute('SELECT id, branch_name FROM branches WHERE id=? AND is_active=1', (branch_id,)).fetchone()
    if not branch:
        return None
    return {'installation_id': install_id, 'device_id': device_id, 'branch_id': branch_id, 'branch_name': branch[1]}


def authorized_branch(conn, user_id):
    """Resolve a validated local binding while keeping user/branch checks."""
    identity = local_identity(conn)
    if not identity:
        raise PermissionError('هوية الجهاز المحلي أو فرعه غير صالحة.')
    actor = conn.execute('SELECT role, branch_id, is_active FROM users WHERE id=?', (user_id,)).fetchone()
    if not actor or not actor[2]:
        raise PermissionError('الحساب غير نشط.')
    if actor[0] == 'Cashier' and actor[1] != identity['branch_id']:
        raise PermissionError('حساب الكاشير لا يتبع فرع الجهاز.')
    return identity


LOCAL_AUTH_KEY = 'sherif_local_auth'


def provision_fresh(conn, company, branch_name, device_name, username, password, business_type=''):
    """Provision only a genuinely empty local schema, atomically and without network."""
    company, branch_name, device_name, username, business_type = (str(x or '').strip() for x in (company, branch_name, device_name, username, business_type))
    if not all((company, branch_name, device_name, username)) or any(len(x) > 120 for x in (company, branch_name, device_name, username, business_type)):
        raise ValueError('أكمل بيانات المنشأة والفرع والجهاز والمدير بأسماء صالحة.')
    hashed = password_hash(password)
    if conn.in_transaction:
        raise RuntimeError('تعذر بدء التهيئة داخل معاملة أخرى.')
    try:
        conn.execute('BEGIN IMMEDIATE')
        tables=[row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            if table in ('local_meta','treasuries'): continue
            quoted='"'+table.replace('"','""')+'"'
            if conn.execute('SELECT 1 FROM '+quoted+' LIMIT 1').fetchone():
                raise ValueError('هذه القاعدة تحتوي بيانات سابقة؛ لم تبدأ التهيئة.')
        if 'treasuries' in tables:
            treasury=[tuple(row) for row in conn.execute('SELECT treasury_name,treasury_type,branch_id,is_active FROM treasuries').fetchall()]
            if treasury not in ([], [('الخزينة الرئيسية','company',None,1)]):
                raise ValueError('توجد بيانات خزينة سابقة؛ لم تبدأ التهيئة.')
        metadata=dict(conn.execute('SELECT key,value FROM local_meta'))
        if set(metadata)-{'device_id','invoice_sequence','sherif_invoice_change_log_v1'} or metadata.get('invoice_sequence','0')!='0' or metadata.get('sherif_invoice_change_log_v1','1')!='1':
            raise ValueError('توجد هوية أو عمليات سابقة؛ لم تبدأ التهيئة.')
        device_id=str(uuid.UUID(metadata['device_id'])) if metadata.get('device_id') else str(uuid.uuid4())
        install_id=str(uuid.uuid4())
        branch=conn.execute('INSERT INTO branches(branch_name,branch_type,is_active) VALUES(?,?,1)',(branch_name,'branch')).lastrowid
        uid=conn.execute('INSERT INTO users(username,password,role,branch_id,is_active) VALUES(?,?,?,?,1)',(username,hashed,'Super_Admin',branch)).lastrowid
        values={MODE_KEY:'1',INSTALLATION_KEY:install_id,DEVICE_KEY:device_id,BRANCH_KEY:str(branch),LOCAL_AUTH_KEY:'local_hash_v1',
                'device_id':device_id,'bound_device_id':device_id,'branch_id':str(branch),'bound_branch_id':str(branch),
                'device_number':'1','device_name':device_name,'device_active':'1','setup_complete':'1','invoice_sequence':'0'}
        conn.executemany('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',values.items())
        conn.executemany('INSERT OR REPLACE INTO app_settings(setting_key,setting_value) VALUES(?,?)', [('company_name',company),('business_type',business_type)])
        conn.commit()
        return {'installation_id':install_id,'device_id':device_id,'branch_id':branch,'user_id':uid}
    except Exception:
        conn.rollback()
        raise
