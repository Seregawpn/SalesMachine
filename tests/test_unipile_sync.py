from pathlib import Path
from unittest.mock import MagicMock

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, link_contact_to_project
from project_os.repositories.linkedin import set_linkedin_state
from project_os.integrations.unipile_sync import match_contact_by_linkedin_url, sync_linkedin_states

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    return conn, project_id


def _fake_client(accounts, relations):
    client = MagicMock()
    client.get_accounts.return_value = accounts
    client.get_relations.return_value = relations
    return client


def test_match_contact_by_linkedin_url_finds_matching_contact(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    contact_id = create_contact(conn, "Jane Smith", linkedin_url="https://www.linkedin.com/in/janesmith/")
    pc_id = link_contact_to_project(conn, project_id, contact_id)

    result = match_contact_by_linkedin_url(conn, project_id, "https://www.linkedin.com/in/janesmith/")

    assert result == pc_id


def test_match_contact_by_linkedin_url_returns_none_when_no_match(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    create_contact(conn, "Jane Smith", linkedin_url="https://www.linkedin.com/in/janesmith/")

    result = match_contact_by_linkedin_url(conn, project_id, "https://www.linkedin.com/in/someone-else/")

    assert result is None


def test_sync_updates_state_for_matching_contact(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    contact_id = create_contact(conn, "Jane Smith", linkedin_url="https://www.linkedin.com/in/janesmith/")
    pc_id = link_contact_to_project(conn, project_id, contact_id)

    client = _fake_client(
        accounts=[{"id": "acc_1", "type": "LINKEDIN"}],
        relations=[{"public_profile_url": "https://www.linkedin.com/in/janesmith/"}],
    )

    updated_count = sync_linkedin_states(conn, client, project_id)

    row = conn.execute(
        "SELECT linkedin_state FROM project_contacts WHERE id = ?", (pc_id,)
    ).fetchone()
    assert row["linkedin_state"] == "Accepted"
    assert updated_count == 1
    client.get_relations.assert_called_once_with("acc_1")


def test_sync_skips_relation_with_no_matching_contact(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)

    client = _fake_client(
        accounts=[{"id": "acc_1", "type": "LINKEDIN"}],
        relations=[{"public_profile_url": "https://www.linkedin.com/in/unknown-person/"}],
    )

    updated_count = sync_linkedin_states(conn, client, project_id)

    assert updated_count == 0


def test_sync_does_not_downgrade_contact_already_past_accepted(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    contact_id = create_contact(conn, "Jane Smith", linkedin_url="https://www.linkedin.com/in/janesmith/")
    pc_id = link_contact_to_project(conn, project_id, contact_id)
    set_linkedin_state(conn, pc_id, "Accepted")
    set_linkedin_state(conn, pc_id, "Message Sent")

    client = _fake_client(
        accounts=[{"id": "acc_1", "type": "LINKEDIN"}],
        relations=[{"public_profile_url": "https://www.linkedin.com/in/janesmith/"}],
    )

    updated_count = sync_linkedin_states(conn, client, project_id)

    row = conn.execute(
        "SELECT linkedin_state FROM project_contacts WHERE id = ?", (pc_id,)
    ).fetchone()
    assert row["linkedin_state"] == "Message Sent"
    assert updated_count == 0


def test_sync_twice_with_unchanged_data_does_not_duplicate_audit_log(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    contact_id = create_contact(conn, "Jane Smith", linkedin_url="https://www.linkedin.com/in/janesmith/")
    pc_id = link_contact_to_project(conn, project_id, contact_id)

    client = _fake_client(
        accounts=[{"id": "acc_1", "type": "LINKEDIN"}],
        relations=[{"public_profile_url": "https://www.linkedin.com/in/janesmith/"}],
    )

    first_count = sync_linkedin_states(conn, client, project_id)
    second_count = sync_linkedin_states(conn, client, project_id)

    audit_rows = conn.execute(
        """
        SELECT * FROM audit_log
        WHERE entity_table = 'project_contacts' AND entity_id = ? AND field = 'linkedin_state'
        """,
        (pc_id,),
    ).fetchall()

    assert first_count == 1
    assert second_count == 0
    assert len(audit_rows) == 1


def test_sync_returns_zero_when_no_linkedin_account(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    create_contact(conn, "Jane Smith", linkedin_url="https://www.linkedin.com/in/janesmith/")

    client = _fake_client(accounts=[{"id": "acc_1", "type": "WHATSAPP"}], relations=[])

    updated_count = sync_linkedin_states(conn, client, project_id)

    assert updated_count == 0
    client.get_relations.assert_not_called()
