"""Read-only update acceptance snapshots. No row values or credentials are saved.

Snapshots are taken under the updater's application lock after a clean exit.
Business databases are never restored, deleted, migrated, or opened for writing.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
from datetime import datetime, timezone


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _cell(value):
    if value is None:
        return ['null', None]
    if isinstance(value, bytes):
        return ['bytes', value.hex()]
    if isinstance(value, int):
        return ['integer', str(value)]
    if isinstance(value, float):
        return ['float', value.hex()]
    return ['text', str(value)]


def database_snapshot(path):
    path = Path(path)
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        schema = conn.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        # Read-only display caches may be created on the first dashboard visit.
        # They are still fingerprinted below, but are not the business data ABI.
        display_caches = {'central_inventory_view_cache', 'central_z_summary_cache'}
        business_schema = [row for row in schema if row[2] not in display_caches]
        result = {'schema_sha256': hashlib.sha256(json.dumps(business_schema, ensure_ascii=False).encode()).hexdigest(),
                  'tables': {}}
        for name, in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            columns = [row[1] for row in conn.execute('PRAGMA table_info(' + _quoted(name) + ')')]
            hashes = []
            cursor = conn.execute('SELECT * FROM ' + _quoted(name))
            while True:
                batch = cursor.fetchmany(512)
                if not batch:
                    break
                for row in batch:
                    data = json.dumps([_cell(value) for value in row], ensure_ascii=False, separators=(',', ':')).encode()
                    hashes.append(hashlib.sha256(data).digest())
            # Row order is intentionally irrelevant; duplicates remain counted.
            digest = hashlib.sha256()
            for value in sorted(hashes):
                digest.update(value)
            result['tables'][name] = {'rows': len(hashes), 'sha256': digest.hexdigest(), 'columns': columns}
        if 'invoices' in result['tables'] and 'sync_status' in result['tables']['invoices']['columns']:
            result['invoice_sync_counts'] = {str(row[0]): row[1] for row in conn.execute(
                'SELECT sync_status,COUNT(*) FROM invoices GROUP BY sync_status')}
        for table in ('erp_outbox', 'sync_queue'):
            if table in result['tables'] and 'sync_status' in result['tables'][table]['columns']:
                result[table + '_counts'] = {str(row[0]): row[1] for row in conn.execute(
                    'SELECT sync_status,COUNT(*) FROM ' + _quoted(table) + ' GROUP BY sync_status')}
        conn.rollback()
        return result


def public_identity(root):
    import os
    if os.environ.get('SHERIF_DATA_DIR') and Path(root).resolve() == Path(__file__).resolve().parent:
        from sherif_paths import local_db
        path = local_db()
    else: path = Path(root) / 'abu_zaid_local.db'
    if not path.is_file():
        return {}
    allowed = ('device_id', 'bound_device_id', 'branch_id', 'bound_branch_id', 'device_number',
               'device_active', 'server_enrolled', 'setup_complete')
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_meta'").fetchone()
        if not exists:
            return {}
        data = dict(conn.execute('SELECT key,value FROM local_meta WHERE key IN (' + ','.join('?' for _ in allowed) + ')', allowed))
        row = conn.execute("SELECT 1 FROM local_meta WHERE key='device_token' AND value IS NOT NULL AND value<>''").fetchone()
        data['device_auth_present'] = bool(row)
        return data


def snapshot(root):
    root = Path(root).resolve()
    result = {'captured_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'identity': public_identity(root), 'databases': {}, 'protected_files': {}}
    for path in sorted(root.iterdir()):
        if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked paths require manual update review')
        if path.is_file() and path.suffix.lower() in ('.db', '.sqlite', '.sqlite3'):
            result['databases'][path.name] = database_snapshot(path)
        elif path.is_file() and path.name != 'APP_VERSION.json' and path.suffix.lower() in ('.txt', '.ini', '.toml', '.json'):
            result['protected_files'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for folder in ('item_images', '.streamlit'):
        base = root / folder
        if base.is_dir():
            for path in sorted(base.rglob('*')):
                if path.is_symlink() or getattr(path.stat(), 'st_file_attributes', 0) & 0x400:
                    raise ValueError('Linked data path requires manual update review')
                if path.is_file():
                    result['protected_files'][path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def compare(before, after):
    differences = []
    for key in ('identity', 'databases', 'protected_files'):
        if before[key] != after[key]:
            if key == 'databases':
                for name in sorted(set(before[key]) | set(after[key])):
                    if before[key].get(name) != after[key].get(name):
                        differences.append('database:' + name)
            elif key == 'protected_files':
                for name in sorted(set(before[key]) | set(after[key])):
                    if before[key].get(name) != after[key].get(name):
                        differences.append('protected_file:' + name)
            else:
                differences.append('device_identity')
    return {'unchanged': not differences, 'differences': differences}
