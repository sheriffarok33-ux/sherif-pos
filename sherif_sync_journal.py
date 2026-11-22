"""Recoverable invoice-event mirror. The committed invoice is the durable outbox."""
import json
import sqlite3
import uuid
import threading
from pathlib import Path

_reconcile_lock = threading.RLock()


def sync_path(local_db):
    local_db = Path(local_db).resolve()
    with sqlite3.connect(local_db.as_uri() + '?mode=ro', uri=True) as local:
        row = local.execute("SELECT value FROM local_meta WHERE key='sherif_local_installation_id'").fetchone()
    if not row:
        return None
    identity = str(uuid.UUID(str(row[0])))
    return local_db.with_name(identity + '_sync.db')


def _reconcile(local_db):
    """Replay committed invoice changes in bounded batches; the cursor commits with the mirror."""
    path = sync_path(local_db)
    if path is None:
        return 0
    local_db = Path(local_db).resolve()
    processed = 0
    with sqlite3.connect(path, timeout=20) as target:
        target.execute('PRAGMA synchronous=FULL')
        target.execute("""CREATE TABLE IF NOT EXISTS invoice_events(
            operation_id TEXT PRIMARY KEY, invoice_id INTEGER NOT NULL UNIQUE,
            state TEXT NOT NULL, payload_json TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        target.execute("CREATE TABLE IF NOT EXISTS journal_cursor (id INTEGER PRIMARY KEY CHECK(id=1), seq INTEGER NOT NULL)")
        target.execute("INSERT OR IGNORE INTO journal_cursor(id,seq) VALUES(1,0)")
        target.commit()
        while True:
            cursor = target.execute('SELECT seq FROM journal_cursor WHERE id=1').fetchone()[0]
            with sqlite3.connect(local_db.as_uri()+'?mode=ro', uri=True, timeout=20) as local:
                local.row_factory = sqlite3.Row
                changes=local.execute("SELECT seq, invoice_id FROM sherif_invoice_changes WHERE seq>? ORDER BY seq LIMIT 200",(cursor,)).fetchall()
                if not changes:
                    return processed
                ids=list(dict.fromkeys(row['invoice_id'] for row in changes))
                rows=local.execute('SELECT * FROM invoices WHERE id IN ('+','.join('?' for _ in ids)+')',ids).fetchall()
            with target:
                for row in rows:
                    item=dict(row)
                    if not item.get('offline_uuid'): continue
                    state='synced' if item.get('sync_status')=='synced' else 'pending'
                    payload=json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
                    prior=target.execute('SELECT invoice_id FROM invoice_events WHERE operation_id=?',(item['offline_uuid'],)).fetchone()
                    if prior and prior[0]!=item['id']:
                        raise ValueError('Invoice identity collision; reconciliation stopped')
                    target.execute("""INSERT INTO invoice_events(operation_id,invoice_id,state,payload_json) VALUES(?,?,?,?)
                        ON CONFLICT(operation_id) DO UPDATE SET state=excluded.state,
                        payload_json=excluded.payload_json,updated_at=CURRENT_TIMESTAMP""",(item['offline_uuid'],item['id'],state,payload))
                target.execute('UPDATE journal_cursor SET seq=? WHERE id=1',(changes[-1]['seq'],))
            processed += len(changes)

def reconcile(local_db):
    with _reconcile_lock:
        return _reconcile(local_db)

def pending_invoice_ids(local_db):
    """Reconcile committed local invoices, then read the durable sending queue."""
    reconcile(local_db)
    path=sync_path(local_db)
    if path is None:
        raise ValueError('Local installation identity is not configured')
    with sqlite3.connect(path,timeout=20) as queue:
        return queue.execute("SELECT invoice_id,operation_id FROM invoice_events WHERE state='pending' ORDER BY invoice_id").fetchall()


# A mirror failure never rolls back a sale: its committed invoice is retried
# after the next invoice update or next process start.
import logging
import threading
_schedule_lock = threading.Lock()
_scheduled = {}

def schedule(local_db):
    path = str(Path(local_db).resolve())
    with _schedule_lock:
        if path in _scheduled:
            _scheduled[path] = True
            return
        _scheduled[path] = False
    def work():
        while True:
            try:
                reconcile(path)
            except Exception:
                logging.getLogger(__name__).exception('Invoice sync journal reconciliation failed; committed invoices remain available for retry')
            with _schedule_lock:
                if _scheduled[path]:
                    _scheduled[path] = False
                else:
                    del _scheduled[path]
                    return
    try:
        threading.Thread(target=work, name='sherif-invoice-journal', daemon=True).start()
    except Exception:
        with _schedule_lock:
            _scheduled.pop(path, None)
        logging.getLogger(__name__).exception('Invoice journal worker could not start; retry on restart')