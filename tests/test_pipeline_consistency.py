from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.opportunities import create_opportunity, set_next_action, update_stage
from project_os.repositories.actions import list_open_actions
from project_os.rules.pipeline_consistency import check_missing_next_action

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    return conn, project_id


def test_flags_opportunity_with_no_next_action(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id)

    created = check_missing_next_action(conn, project_id)

    assert created == 1
    actions = list_open_actions(conn, project_id)
    assert actions[0]["reason"] == "Missing next action"
    assert actions[0]["linked_table"] == "opportunities"
    assert actions[0]["linked_id"] == opp_id
    assert actions[0]["priority"] == "P2"


def test_does_not_flag_opportunity_with_next_action(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id)
    set_next_action(conn, opp_id, "Send proposal", "2026-09-01")

    created = check_missing_next_action(conn, project_id)

    assert created == 0
    assert list_open_actions(conn, project_id) == []


def test_does_not_flag_closed_opportunity(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id)
    update_stage(conn, opp_id, "Closed")

    created = check_missing_next_action(conn, project_id)

    assert created == 0


def test_running_twice_does_not_duplicate_the_action(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    create_opportunity(conn, project_id)

    check_missing_next_action(conn, project_id)
    second_run_created = check_missing_next_action(conn, project_id)

    assert second_run_created == 0
    assert len(list_open_actions(conn, project_id)) == 1
