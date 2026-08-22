from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project, list_projects, get_project

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _conn(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    return conn


def test_create_and_get_project(tmp_db_path):
    conn = _conn(tmp_db_path)
    project_id = create_project(conn, "Nexy", description="Accessibility voice assistant")
    row = get_project(conn, project_id)
    assert row["name"] == "Nexy"
    assert row["active"] == 1


def test_list_projects_filters_inactive(tmp_db_path):
    conn = _conn(tmp_db_path)
    create_project(conn, "Nexy")
    other_id = create_project(conn, "Old Project")
    conn.execute("UPDATE projects SET active = 0 WHERE id = ?", (other_id,))

    active = list_projects(conn)
    all_projects = list_projects(conn, active_only=False)

    assert [p["name"] for p in active] == ["Nexy"]
    assert len(all_projects) == 2
