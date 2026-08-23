from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.contacts import create_contact

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    create_contact(conn, "Jane Smith", email="jane@example.org")
    conn.close()
    return TestClient(create_app(tmp_db_path))


def test_contacts_index_lists_every_contact(tmp_db_path):
    client = _client(tmp_db_path)

    response = client.get("/contacts")

    assert response.status_code == 200
    assert "Jane Smith" in response.text
    assert "jane@example.org" in response.text


def test_contacts_index_shows_a_message_when_there_are_no_contacts(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    conn.close()
    client = TestClient(create_app(tmp_db_path))

    response = client.get("/contacts")

    assert response.status_code == 200
    assert "No contacts yet." in response.text
