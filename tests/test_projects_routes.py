from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    conn.close()

    app = create_app(tmp_db_path)
    return TestClient(app), project_id


def test_projects_index_lists_each_project_with_a_link(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    response = client.get("/projects")

    assert response.status_code == 200
    assert "Nexy" in response.text
    assert f'href="/projects/{project_id}"' in response.text


def test_projects_index_shows_a_message_when_there_are_no_projects(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    conn.close()
    app = create_app(tmp_db_path)
    client = TestClient(app)

    response = client.get("/projects")

    assert response.status_code == 200
    assert "No projects yet." in response.text


def test_action_center_navigation_links_to_the_projects_index(tmp_db_path):
    client, _project_id = _client(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert 'href="/projects"' in response.text
