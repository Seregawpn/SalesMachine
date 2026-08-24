from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact
from project_os.repositories.interactions import create_interaction, get_interaction_by_external_id, list_interactions, interaction_exists

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    return conn, project_id, contact_id


def test_create_interaction_stores_all_fields(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)

    interaction_id = create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Re: pricing",
        ai_summary="Interested, asks about a demo.", intent="positive",
        external_message_id="15082",
    )

    row = conn.execute("SELECT * FROM interactions WHERE id = ?", (interaction_id,)).fetchone()
    assert row["project_id"] == project_id
    assert row["contact_id"] == contact_id
    assert row["channel"] == "email"
    assert row["direction"] == "inbound"
    assert row["subject"] == "Re: pricing"
    assert row["ai_summary"] == "Interested, asks about a demo."
    assert row["intent"] == "positive"
    assert row["external_message_id"] == "15082"
    assert row["source"] == "apple-mail"


def test_get_interaction_by_external_id_finds_existing_row(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Re: pricing",
        ai_summary="Interested.", intent="positive", external_message_id="15082",
    )

    found = get_interaction_by_external_id(conn, project_id, "15082")
    missing = get_interaction_by_external_id(conn, project_id, "99999")

    assert found is not None
    assert found["external_message_id"] == "15082"
    assert missing is None


def test_get_interaction_by_external_id_is_scoped_by_project(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    other_project_id = create_project(conn, "Other Project")
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Re: pricing",
        ai_summary="Interested.", intent="positive", external_message_id="15082",
    )

    found_in_other_project = get_interaction_by_external_id(conn, other_project_id, "15082")

    assert found_in_other_project is None


def test_list_interactions_returns_most_recent_first_with_contact_and_project_names(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="First",
        ai_summary=None, intent=None, external_message_id="1",
    )
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="outbound", subject="Second",
        ai_summary=None, intent=None, external_message_id="2",
    )

    interactions = list_interactions(conn)

    assert [i["subject"] for i in interactions] == ["Second", "First"]
    assert interactions[0]["contact_name"] == "Jane Smith"
    assert interactions[0]["project_name"] == "Nexy"


def test_list_interactions_respects_the_limit(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    for i in range(3):
        create_interaction(
            conn, project_id, contact_id,
            channel="email", direction="inbound", subject=f"Message {i}",
            ai_summary=None, intent=None, external_message_id=str(i),
        )

    interactions = list_interactions(conn, limit=2)

    assert len(interactions) == 2


def test_create_interaction_accepts_explicit_created_at(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")

    interaction_id = create_interaction(
        conn, project_id, contact_id,
        channel="Email", direction="outbound", subject="Intro",
        ai_summary=None, intent=None, external_message_id=None,
        source="import-nexy-sheet", created_at="2026-08-10 00:00:00",
    )

    row = conn.execute("SELECT created_at FROM interactions WHERE id = ?", (interaction_id,)).fetchone()
    assert row["created_at"] == "2026-08-10 00:00:00"


def test_interaction_exists_detects_duplicates(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")

    assert interaction_exists(conn, contact_id, "Intro", "2026-08-10 00:00:00") is False

    create_interaction(
        conn, project_id, contact_id,
        channel="Email", direction="outbound", subject="Intro",
        ai_summary=None, intent=None, external_message_id=None,
        created_at="2026-08-10 00:00:00",
    )

    assert interaction_exists(conn, contact_id, "Intro", "2026-08-10 00:00:00") is True
    assert interaction_exists(conn, contact_id, "Different subject", "2026-08-10 00:00:00") is False
