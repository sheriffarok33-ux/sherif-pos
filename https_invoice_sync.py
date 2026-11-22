"""Opt-in local-first HTTPS invoice synchronizer for SHERIF POS.
No PostgreSQL writes from this module. A server ACK is required before marking synced.
"""
import json
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path

DEFAULT_URL = None


def _post(url, payload, token=None, timeout=15):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


def sync_pending_invoices(username, password, api_url=DEFAULT_URL, db_path=None):
    """Return counters. Never mark synced without an invoice ACK from server."""
    if not username or not password:
        raise ValueError('Login credentials required')
    from sherif_network import server_enabled
    if not server_enabled(): raise ConnectionError('لم يُهيأ سيرفر للاتصال.')
    import sys
    from sherif_network import connection_dir
    configured = (connection_dir() / 'SERVER_URL.txt').read_text(encoding='utf-8-sig').strip().rstrip('/')
    if api_url and api_url.rstrip('/') != configured: raise ValueError('عنوان السيرفر لا يطابق إعداد الجهاز المعتمد.')
    api_url = configured
    auth = _post(api_url + '/auth/login', {'username': username, 'password': password})
    token = auth['access_token']
    from sherif_paths import local_db
    db_path = Path(db_path) if db_path else local_db()
    con = sqlite3.connect(str(db_path), timeout=20)
    con.row_factory = sqlite3.Row
    synced = failed = 0
    try:
        rows = con.execute("SELECT * FROM invoices WHERE sync_status='pending' ORDER BY id").fetchall()
        for inv in rows:
            try:
                body = {k: inv[k] for k in ('offline_uuid', 'branch_id', 'user_id', 'customer_name', 'customer_phone', 'total_amount', 'payment_method', 'notes', 'shift_status')}
                if not body['offline_uuid']:
                    raise ValueError('Missing offline_uuid')
                for optional in ('invoice_number', 'shift_uuid'):
                    if optional in inv.keys():
                        body[optional] = inv[optional]
                result = _post(api_url + '/sync/invoice', body, token)
                remote_id = result.get('remote_invoice_id')
                if not isinstance(remote_id, int) or remote_id <= 0:
                    raise ValueError('Server did not acknowledge invoice ID')
                con.execute("UPDATE invoices SET sync_status='synced', remote_invoice_id=?, sync_error=NULL WHERE id=? AND sync_status='pending'", (remote_id, inv['id']))
                con.commit()
                synced += 1
            except Exception as exc:
                con.rollback()
                # Record error only; invoice stays pending for retry.
                con.execute("UPDATE invoices SET sync_error=? WHERE id=? AND sync_status='pending'", (str(exc)[:500], inv['id']))
                con.commit()
                failed += 1
        return {'synced': synced, 'failed': failed, 'pending': con.execute("SELECT COUNT(*) FROM invoices WHERE sync_status='pending'").fetchone()[0]}
    finally:
        con.close()
