from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.opportunities import create_opportunity
from project_os.daemon import build_scheduler

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def test_scheduler_runs_backup_and_consistency_jobs(tmp_db_path, tmp_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    create_opportunity(conn, project_id)  # has no next action -> should get flagged
    conn.close()

    backup_dir = tmp_path / "backups"
    scheduler = build_scheduler(tmp_db_path, backup_dir, include_unipile=False)

    ran = scheduler.run_pending(now=0.0)

    assert "backup" in ran
    assert "pipeline_consistency" in ran
    assert "unipile_sync" not in ran
    assert list(backup_dir.glob("*.sqlite"))

    conn = get_connection(tmp_db_path)
    from project_os.repositories.actions import list_open_actions
    actions = list_open_actions(conn, project_id)
    assert any(a["reason"] == "Missing next action" for a in actions)


def test_unipile_job_skips_silently_when_no_keychain_entry(tmp_db_path, tmp_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    conn.close()

    backup_dir = tmp_path / "backups"
    scheduler = build_scheduler(tmp_db_path, backup_dir, include_unipile=True)

    # This should not raise even though no Keychain entry exists for a fresh test env
    # (or, if one happens to exist locally, the job may run without error).
    ran = scheduler.run_pending(now=0.0)
    assert "backup" in ran
    assert "pipeline_consistency" in ran
