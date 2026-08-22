from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.actions import (
    create_action,
    list_open_actions,
    complete_action,
    snooze_action,
    has_open_action_for,
)

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    return conn, project_id


def test_create_and_list_open_actions_ordered_by_priority(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    create_action(conn, project_id, module="Sales", reason="Low priority", priority="P3", due_date="2026-09-05")
    create_action(conn, project_id, module="Sales", reason="Urgent", priority="P0", due_date="2026-08-25")

    rows = list_open_actions(conn, project_id)
    assert [r["reason"] for r in rows] == ["Urgent", "Low priority"]


def test_complete_action_removes_it_from_open_list(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    action_id = create_action(conn, project_id, module="Sales", reason="Follow up")

    complete_action(conn, action_id)

    assert list_open_actions(conn, project_id) == []


def test_snooze_action_updates_due_date_and_keeps_it_open(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    action_id = create_action(conn, project_id, module="Sales", reason="Follow up", due_date="2026-08-25")

    snooze_action(conn, action_id, "2026-09-01")

    rows = list_open_actions(conn, project_id)
    assert rows[0]["due_date"] == "2026-09-01"


def test_has_open_action_for_prevents_duplicates(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    create_action(
        conn, project_id, module="Sales", reason="Missing next action",
        linked_table="opportunities", linked_id=42,
    )

    assert has_open_action_for(conn, "opportunities", 42, "Missing next action") is True
    assert has_open_action_for(conn, "opportunities", 999, "Missing next action") is False
