from __future__ import annotations
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
LOCAL_DB = APP_DIR / "abu_zaid_local.db"
BACKUP_DIR = APP_DIR / "backups"
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
