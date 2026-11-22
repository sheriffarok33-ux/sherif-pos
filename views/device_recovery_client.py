"""Archive a verified old branch snapshot; never replace the active SQLite file."""
import json, sqlite3, os, hashlib
from pathlib import Path

def prepare_branch_archive(conn, recovery_id):
    # Caller holds _SYNC_LOCK and BEGIN IMMEDIATE. A separate read connection sees
    # a stable committed snapshot while no other writer can modify this database.
    import uuid
    rid=str(uuid.UUID(recovery_id))
    raw=getattr(conn,'_conn',conn)
    source=Path(raw.execute('PRAGMA database_list').fetchone()[2]).resolve()
    folder=source.parent/'device_history';folder.mkdir(exist_ok=True)
    archive=folder/(rid+'.sqlite.archive')
    tables=[r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    # This legacy AFTER INSERT invoice-number trigger cannot run during the
    # archive's DELETE-only invoice operations or its local_meta inserts.
    # Match the full known DDL, not just a name that arbitrary SQL could reuse.
    approved={('trg_abuzaid_device_invoice_number','invoices'):'e6290a9e93a5ec1396be7e94f38cd7ec9bd8d3ed3f09c39fc05dd36e8f7046d7'}
    for trigger in raw.execute("SELECT name,tbl_name,sql FROM sqlite_master WHERE type='trigger'"):
        if hashlib.sha256((trigger[2] or '').encode()).hexdigest()!=approved.get((trigger[0],trigger[1])):
            raise ValueError('توجد مشغلات محلية غير مدعومة للأرشفة؛ لم يتغير الفرع')
    for table in ('invoices','sync_queue','erp_outbox','exception_settlements'):
        if table in tables and raw.execute('SELECT 1 FROM "'+table+'"'+" WHERE COALESCE(sync_status,'pending') NOT IN ('synced','ignored','cancelled_reset') LIMIT 1").fetchone():
            raise ValueError('توجد معاملات معلقة؛ لا يمكن نقل الجهاز')
    if 'transfer_logs' in tables and raw.execute('SELECT 1 FROM transfer_logs WHERE receipt_pending=1 LIMIT 1').fetchone():
        raise ValueError('يوجد استلام معلق؛ لا يمكن نقل الجهاز')
    for row in raw.execute("SELECT value FROM local_meta WHERE key LIKE 'pos_sale_draft:v1:%'"):
        draft=json.loads(row[0])
        if draft.get('state')=='open' and draft.get('cart'):raise ValueError('توجد سلة غير مكتملة؛ لا يمكن نقل الجهاز')
    if archive.exists():
        check=sqlite3.connect(archive.as_uri()+'?mode=ro',uri=True)
        try:
            if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('الأرشيف السابق غير سليم')
            for table in tables:
                if table=='local_meta':continue
                quoted='"'+table.replace('"','""')+'"'
                a=[tuple(r) for r in raw.execute('SELECT * FROM '+quoted)]
                b=check.execute('SELECT * FROM '+quoted).fetchall()
                if a!=b:raise ValueError('تغيرت البيانات بعد الأرشفة؛ لم يُستكمل النقل تلقائيًا')
        finally:check.close()
        return str(archive),tables
    partial=archive.with_suffix('.partial')
    reader=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
    target=sqlite3.connect(partial)
    try:
        reader.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('فشل تحقق الأرشيف')
        for table in tables:
            quoted='"'+table.replace('"','""')+'"'
            if raw.execute('SELECT COUNT(*) FROM '+quoted).fetchone()[0]!=target.execute('SELECT COUNT(*) FROM '+quoted).fetchone()[0]:
                raise ValueError('عدد سجلات الأرشيف غير مطابق')
    finally:target.close();reader.close()
    os.replace(partial,archive)
    return str(archive),tables

def isolate_archived_branch(conn, archive, tables):
    raw=getattr(conn,'_conn',conn)
    raw.execute('PRAGMA defer_foreign_keys=ON')
    for table in tables:
        if table!='local_meta':raw.execute('DELETE FROM "'+table.replace('"','""')+'"')
    # Preserve identity, generation, recovery intent and explicit historical evidence.
    keep=('branch_id','bound_branch_id','bound_device_id','device_id','device_number','device_name',
          'device_token','device_active','server_enrolled','setup_complete','sync_generation','device_reconfigure_intent','device_command_intent')
    raw.execute('DELETE FROM local_meta WHERE key NOT IN ('+','.join('?' for _ in keep)+") AND key NOT LIKE 'historical_unconfirmed_shift%' AND key NOT LIKE 'device_history:%'",keep)
    raw.execute('INSERT INTO local_meta(key,value) VALUES(?,?)',('device_history:'+Path(archive).stem,json.dumps({'path':archive,'state':'historical_read_only_not_for_sync'},ensure_ascii=False)))
    if raw.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('فشل اتساق العزل؛ لم يُعتمد الحفظ المحلي')
