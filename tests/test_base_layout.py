from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    conn.close()
    return TestClient(create_app(tmp_db_path))


def test_base_layout_loads_the_vendored_htmx_script(tmp_db_path):
    client = _client(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert '<script src="/static/vendor/htmx.min.js"></script>' in response.text


def test_base_layout_includes_all_four_nav_links(tmp_db_path):
    client = _client(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert 'href="/action-center"' in response.text
    assert 'href="/projects"' in response.text
    assert 'href="/contacts"' in response.text
    assert 'href="/interactions"' in response.text


def test_vendored_htmx_script_is_served_and_looks_like_htmx(tmp_db_path):
    client = _client(tmp_db_path)

    response = client.get("/static/vendor/htmx.min.js")

    assert response.status_code == 200
    assert "htmx" in response.text.lower()
