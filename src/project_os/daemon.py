import time
from pathlib import Path

import uvicorn

from project_os.backup import run_backup, prune_old_backups
from project_os.db import get_connection
from project_os.repositories.projects import list_projects
from project_os.rules.pipeline_consistency import check_missing_next_action
from project_os.scheduler import Scheduler
from project_os.web.app import create_app

DB_PATH = str(Path.home() / "ProjectOS" / "data" / "project_os.sqlite")
BACKUP_DIR = Path.home() / "ProjectOS" / "data" / "backups"


def build_scheduler(db_path: str, backup_dir: Path) -> Scheduler:
    scheduler = Scheduler()

    def _backup_job() -> None:
        run_backup(db_path, backup_dir)
        prune_old_backups(backup_dir, keep=30)

    def _consistency_job() -> None:
        conn = get_connection(db_path)
        for project in list_projects(conn):
            check_missing_next_action(conn, project["id"])
        conn.close()

    scheduler.register("backup", interval_seconds=24 * 60 * 60, func=_backup_job)
    scheduler.register("pipeline_consistency", interval_seconds=15 * 60, func=_consistency_job)
    return scheduler


def main() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    app = create_app(DB_PATH)
    scheduler = build_scheduler(DB_PATH, BACKUP_DIR)

    import threading

    def _scheduler_loop() -> None:
        while True:
            scheduler.run_pending()
            time.sleep(60)

    threading.Thread(target=_scheduler_loop, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
