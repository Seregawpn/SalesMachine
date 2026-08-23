import datetime
import sqlite3
from pathlib import Path


def run_backup(db_path: str, backup_dir: Path, now: datetime.date | None = None) -> Path:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    day = now or datetime.date.today()
    dest = backup_dir / f"{day.isoformat()}.sqlite"

    source_conn = sqlite3.connect(db_path)
    dest_conn = sqlite3.connect(dest)
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    return dest


def prune_old_backups(backup_dir: Path, keep: int = 30) -> None:
    backup_dir = Path(backup_dir)
    snapshots = sorted(backup_dir.glob("*.sqlite"))
    excess = len(snapshots) - keep
    for path in snapshots[:max(excess, 0)]:
        path.unlink()
