from pathlib import Path
import pytest

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, link_contact_to_project
from project_os.repositories.actions import list_open_actions
from project_os.repositories.linkedin import set_linkedin_state, list_linkedin_queue, LINKEDIN_STATES

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith")
    pc_id = link_contact_to_project(conn, project_id, contact_id)
    return conn, project_id, pc_id


def test_rejects_unknown_state(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)
    with pytest.raises(ValueError):
        set_linkedin_state(conn, pc_id, "Bogus State")


def test_rejects_invalid_project_contact_id(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)
    with pytest.raises(LookupError, match="No project_contact with id"):
        set_linkedin_state(conn, 999, "Accepted")


def test_accepted_creates_prepare_message_action(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)
    set_linkedin_state(conn, pc_id, "Accepted")

    row = conn.execute(
        "SELECT linkedin_state FROM project_contacts WHERE id = ?", (pc_id,)
    ).fetchone()
    assert row["linkedin_state"] == "Accepted"

    actions = list_open_actions(conn, project_id)
    assert any(a["reason"] == "Prepare first LinkedIn message" for a in actions)


def test_pending_connection_creates_recheck_action(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)
    set_linkedin_state(conn, pc_id, "Pending Connection")

    actions = list_open_actions(conn, project_id)
    assert any(a["reason"] == "Re-check LinkedIn connection status" for a in actions)


def test_list_linkedin_queue_groups_by_state(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)
    set_linkedin_state(conn, pc_id, "Pending Connection")

    queue = list_linkedin_queue(conn, project_id)
    assert len(queue["pending_recheck"]) == 1
    assert queue["to_connect"] == []


def test_linkedin_states_include_spec_values():
    assert LINKEDIN_STATES == [
        "Not started", "Pending Connection", "Accepted",
        "Message Sent", "Replied", "Not relevant",
    ]


def test_no_op_transition_does_not_duplicate_audit_log(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)

    set_linkedin_state(conn, pc_id, "Accepted")
    set_linkedin_state(conn, pc_id, "Accepted")  # no-op: same state again

    audit_rows = conn.execute(
        """
        SELECT * FROM audit_log
        WHERE entity_table = 'project_contacts' AND entity_id = ? AND field = 'linkedin_state'
        """,
        (pc_id,),
    ).fetchall()
    assert len(audit_rows) == 1


def test_duplicate_action_prevention_on_repeated_state(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)
    set_linkedin_state(conn, pc_id, "Accepted")
    set_linkedin_state(conn, pc_id, "Message Sent")
    set_linkedin_state(conn, pc_id, "Accepted")

    actions = list_open_actions(conn, project_id)
    prepare_actions = [a for a in actions if a["reason"] == "Prepare first LinkedIn message"]
    assert len(prepare_actions) == 1
