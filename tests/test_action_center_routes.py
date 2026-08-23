from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.actions import create_action

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    create_action(conn, project_id, module="Sales", reason="Reply from decision maker", priority="P1", due_date="2026-08-22")
    conn.close()

    app = create_app(tmp_db_path)
    return TestClient(app), project_id


def test_action_center_lists_open_action_with_reason(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert "Reply from decision maker" in response.text
    assert "<table" in response.text


def test_completing_an_action_removes_it_from_the_page(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    action_id = client.get("/action-center").text
    # fetch the action id via the API layer directly for a stable test
    from project_os.db import get_connection
    conn = get_connection(tmp_db_path)
    row = conn.execute("SELECT id FROM actions LIMIT 1").fetchone()

    response = client.post(f"/actions/{row['id']}/complete", follow_redirects=True)

    assert response.status_code == 200
    assert "Reply from decision maker" not in response.text


def test_action_center_links_each_action_to_its_project(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert f'href="/projects/{project_id}"' in response.text


def test_completing_a_missing_action_returns_404(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    response = client.post("/actions/999999/complete")

    assert response.status_code == 404


def test_snoozing_a_missing_action_returns_404(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    response = client.post("/actions/999999/snooze", data={"new_due_date": "2026-09-01"})

    assert response.status_code == 404


def test_snoozing_an_action_updates_its_due_date_on_the_page(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    conn = get_connection(tmp_db_path)
    row = conn.execute("SELECT id FROM actions LIMIT 1").fetchone()
    conn.close()

    response = client.post(
        f"/actions/{row['id']}/snooze",
        data={"new_due_date": "2026-09-15"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "2026-09-15" in response.text
