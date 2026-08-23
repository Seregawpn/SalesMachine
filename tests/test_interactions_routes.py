from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact
from project_os.repositories.interactions import create_interaction

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Re: pricing",
        ai_summary="Interested.", intent="positive", external_message_id="1",
    )
    conn.close()
    return TestClient(create_app(tmp_db_path))


def test_interactions_index_lists_recent_interactions(tmp_db_path):
    client = _client(tmp_db_path)

    response = client.get("/interactions")

    assert response.status_code == 200
    assert "Re: pricing" in response.text
    assert "Jane Smith" in response.text
    assert "Nexy" in response.text


def test_interactions_index_shows_a_message_when_there_are_none(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    conn.close()
    client = TestClient(create_app(tmp_db_path))

    response = client.get("/interactions")

    assert response.status_code == 200
    assert "No interactions yet." in response.text
