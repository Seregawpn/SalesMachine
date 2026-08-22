import datetime
import shutil
from pathlib import Path


def run_backup(db_path: str, backup_dir: Path, now: datetime.date | None = None) -> Path:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    day = now or datetime.date.today()
    dest = backup_dir / f"{day.isoformat()}.sqlite"
    shutil.copyfile(db_path, dest)
    return dest


def prune_old_backups(backup_dir: Path, keep: int = 30) -> None:
    backup_dir = Path(backup_dir)
    snapshots = sorted(backup_dir.glob("*.sqlite"))
    excess = len(snapshots) - keep
    for path in snapshots[:max(excess, 0)]:
        path.unlink()
