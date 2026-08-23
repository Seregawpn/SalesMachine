from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, link_contact_to_project

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith")
    pc_id = link_contact_to_project(conn, project_id, contact_id)
    conn.close()

    app = create_app(tmp_db_path)
    return TestClient(app), project_id, pc_id


def test_linkedin_queue_lists_contact_to_connect(tmp_db_path):
    client, project_id, pc_id = _client(tmp_db_path)

    response = client.get(f"/projects/{project_id}/linkedin")

    assert response.status_code == 200
    assert "Jane Smith" in response.text
    assert "Connection sent" in response.text  # accessible button label, not icon-only


def test_confirming_connection_sent_moves_contact_to_pending(tmp_db_path):
    client, project_id, pc_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/linkedin/{pc_id}/state",
        data={"state": "Pending Connection"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    from project_os.db import get_connection
    conn = get_connection(tmp_db_path)
    row = conn.execute(
        "SELECT linkedin_state FROM project_contacts WHERE id = ?", (pc_id,)
    ).fetchone()
    assert row["linkedin_state"] == "Pending Connection"


def test_confirming_connection_sent_moves_contact_out_of_to_connect(tmp_db_path):
    client, project_id, pc_id = _client(tmp_db_path)

    client.post(
        f"/projects/{project_id}/linkedin/{pc_id}/state",
        data={"state": "Pending Connection"},
        follow_redirects=True,
    )

    response = client.get(f"/projects/{project_id}/linkedin")

    assert response.status_code == 200
    assert "Nothing to connect with right now." in response.text
    assert "Jane Smith" in response.text  # now shown in pending section


def test_invalid_state_returns_400(tmp_db_path):
    client, project_id, pc_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/linkedin/{pc_id}/state",
        data={"state": "Bogus State"},
        follow_redirects=True,
    )

    assert response.status_code == 400


def test_missing_project_contact_returns_400(tmp_db_path):
    client, project_id, pc_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/linkedin/999999/state",
        data={"state": "Pending Connection"},
        follow_redirects=True,
    )

    assert response.status_code == 400
