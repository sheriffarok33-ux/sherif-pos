from __future__ import annotations
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
from sherif_paths import local_db, backups
LOCAL_DB = local_db()
BACKUP_DIR = backups()
KEEP_DAYS = 30


def _safe_copy_sqlite(src: Path, dst: Path) -> None:
    """Create a consistent SQLite snapshot even while WAL mode is enabled."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        return
    source = sqlite3.connect(str(src), timeout=20)
    target = sqlite3.connect(str(dst), timeout=20)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def daily_backup(branch_id=None, keep_days: int = KEEP_DAYS):
    """One dated backup per day + Latest_Backup.db, retaining the newest N dated copies."""
    if not LOCAL_DB.exists():
        return {"created": False, "reason": "local_db_missing"}

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    branch = str(branch_id or "device")
    today = date.today().isoformat()
    dated = BACKUP_DIR / f"abu_zaid_branch_{branch}_{today}.db"
    latest = BACKUP_DIR / "Latest_Backup.db"

    created = False
    if not dated.exists():
        _safe_copy_sqlite(LOCAL_DB, dated)
        created = True

    # Latest is intentionally overwritten once per successful login/day state.
    _safe_copy_sqlite(LOCAL_DB, latest)

    dated_files = sorted(
        BACKUP_DIR.glob("abu_zaid_branch_*_????-??-??.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in dated_files[max(1, int(keep_days)):]:
        try:
            old.unlink()
        except OSError:
            pass

    return {
        "created": created,
        "dated": str(dated),
        "latest": str(latest),
        "time": datetime.now().isoformat(timespec="seconds"),
    }


def quote_name(name):
    return '"' + str(name).replace('"', '""') + '"'


def is_sqlite(conn):
    return isinstance(getattr(conn, '_conn', conn), sqlite3.Connection)


def table_catalog(conn):
    if is_sqlite(conn):
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    else:
        rows = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_type='BASE TABLE'").fetchall()
    result = {}
    for row in rows:
        name = row[0]
        cur = conn.execute('SELECT * FROM ' + quote_name(name) + ' WHERE 1=0')
        result[name] = [col[0] for col in cur.description]
        cur.close()
    return result


def _report_value(value):
    import json
    from decimal import Decimal
    if value is None or isinstance(value, (str, int, float, bytes)):
        return value
    if isinstance(value, Decimal):
        # Exact financial values remain decimal strings in reporting snapshots.
        return str(value)
    if isinstance(value, memoryview):
        return bytes(value)
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return json.dumps(value, ensure_ascii=False, default=str)


def create_data_backup(conn, year=None):
    """Persist native backup plus an isolated reporting copy; never overwrite a year."""
    import os, io, json, subprocess, tempfile, zipfile
    if year is not None and not 2000 <= int(year) <= 2200:
        raise ValueError('السنة غير صحيحة.')
    stamp = str(int(year)) if year is not None else datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    filename = 'abu_zaid_' + stamp + '.zip'
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    destination = BACKUP_DIR / filename
    # Reserve the name atomically; failed backups remove this reservation.
    output = destination.open('xb')
    os.chmod(destination, 0o600)
    try:
        with tempfile.TemporaryDirectory(prefix='abuzaid_backup_') as work:
            report = Path(work) / ('abu_zaid_local_' + stamp + '.db')
            if is_sqlite(conn):
                # Separate source connection: backup on a write transaction would block.
                raw = getattr(conn, '_conn', conn)
                source_path = raw.execute('PRAGMA database_list').fetchone()[2]
                if not source_path:
                    raise RuntimeError('النسخ يتطلب قاعدة محفوظة على القرص.')
                _safe_copy_sqlite(Path(source_path), report)
            else:
                # Caller supplies a stable read transaction or holds write-excluding locks.
                target = sqlite3.connect(str(report))
                try:
                    for table, columns in table_catalog(conn).items():
                        target.execute('CREATE TABLE ' + quote_name(table) + '(' + ','.join(quote_name(c) for c in columns) + ')')
                        cur = conn.execute('SELECT * FROM ' + quote_name(table))
                        while True:
                            rows = cur.fetchmany(1000)
                            if not rows: break
                            target.executemany('INSERT INTO ' + quote_name(table) + ' VALUES(' + ','.join('?' for _ in columns) + ')',
                                               [tuple(_report_value(v) for v in r) for r in rows])
                        cur.close()
                    target.commit()
                finally:
                    target.close()
            check = sqlite3.connect(str(report))
            try:
                if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('فشل فحص النسخة الاحتياطية.')
            finally:
                check.close()
            dump = None
            if not is_sqlite(conn):
                import streamlit as st
                pg = st.secrets['postgres']
                env = os.environ.copy()
                env['PGPASSWORD'] = str(pg['password'])
                env['PGSSLMODE'] = str(pg.get('sslmode', 'require'))
                dump = Path(work) / ('abu_zaid_' + stamp + '.dump')
                snapshot_id = conn.execute('SELECT pg_export_snapshot()').fetchone()[0]
                cmd = ['pg_dump','--snapshot',str(snapshot_id),'--format=custom','--no-owner','--no-acl','--host',str(pg['host']),
                       '--port',str(pg.get('port',5432)),'--username',str(pg['user']),
                       '--dbname',str(pg.get('dbname','postgres')),'--file',str(dump)]
                result = subprocess.run(cmd, env=env, capture_output=True, timeout=300)
                if result.returncode or not dump.exists() or not dump.stat().st_size:
                    raise RuntimeError('فشل pg_dump؛ لم يتم تصفير أي بيانات. تحقق من تثبيته وصلاحيات النسخ.')
            meta = {'created_at':datetime.now().isoformat(), 'financial_year':year,
                    'engine':'sqlite' if is_sqlite(conn) else 'postgresql',
                    'report_file':report.name, 'report_only':not is_sqlite(conn)}
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
                z.write(report, report.name)
                if dump: z.write(dump, dump.name)
                z.writestr('backup_info.json', json.dumps(meta, ensure_ascii=False, indent=2))
        output.close()
        return destination
    except BaseException:
        output.close()
        destination.unlink(missing_ok=True)
        raise


def full_backup_zip():
    from offline_store import get_local_connection, pending_count, pending_operations_count
    conn = get_local_connection(queue_writes=False)
    try:
        path = create_data_backup(conn)
        return path.read_bytes(), {'includes_postgresql': False, 'includes_local_sqlite': True,
                                  'pending_invoices': pending_count(),
                                  'pending_operations': pending_operations_count()}
    finally:
        conn.close()
