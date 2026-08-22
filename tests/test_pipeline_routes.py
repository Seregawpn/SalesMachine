from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, create_organization
from project_os.repositories.opportunities import create_opportunity
from project_os.pipeline import STAGES

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith")
    org_id = create_organization(conn, "Example Org")
    opp_id = create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id)
    conn.close()

    app = create_app(tmp_db_path)
    return TestClient(app), project_id, opp_id


def test_pipeline_page_lists_opportunity_in_a_table(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.get(f"/projects/{project_id}/pipeline")

    assert response.status_code == 200
    assert "Example Org" in response.text
    assert "Jane Smith" in response.text
    assert "<table" in response.text
    for stage in STAGES:
        assert stage in response.text  # stage dropdown lists every valid stage


def test_changing_stage_via_form_updates_pipeline(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/pipeline/{opp_id}/stage",
        data={"stage": "Contacted"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Contacted" in response.text


def test_project_overview_shows_needs_attention_actions(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.get(f"/projects/{project_id}")

    assert response.status_code == 200
    assert "Needs attention" in response.text
