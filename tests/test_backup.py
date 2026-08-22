import datetime
import sqlite3
from pathlib import Path

from project_os.backup import run_backup, prune_old_backups


def test_run_backup_copies_db_with_dated_filename(tmp_path):
    db_path = tmp_path / "project_os.sqlite"
    sqlite3.connect(db_path).close()
    backup_dir = tmp_path / "backups"

    result = run_backup(str(db_path), backup_dir, now=datetime.date(2026, 8, 22))

    assert result.name == "2026-08-22.sqlite"
    assert result.exists()


def test_prune_old_backups_keeps_only_the_newest(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for day in range(1, 32):
        (backup_dir / f"2026-01-{day:02d}.sqlite").write_text("x")
    for day in range(1, 5):
        (backup_dir / f"2026-02-{day:02d}.sqlite").write_text("x")

    prune_old_backups(backup_dir, keep=30)

    remaining = sorted(p.name for p in backup_dir.glob("*.sqlite"))
    assert len(remaining) == 30
    assert remaining[0] == "2026-01-06.sqlite"
    assert remaining[-1] == "2026-02-04.sqlite"
