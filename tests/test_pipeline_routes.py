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


def test_project_overview_links_to_linkedin_queue(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.get(f"/projects/{project_id}")

    assert response.status_code == 200
    assert f'href="/projects/{project_id}/linkedin"' in response.text


def test_changing_stage_to_invalid_value_returns_400(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/pipeline/{opp_id}/stage",
        data={"stage": "Not A Real Stage"},
    )

    assert response.status_code == 400


def test_project_overview_for_nonexistent_project_returns_404(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.get(f"/projects/{project_id + 999}")

    assert response.status_code == 404


def test_changing_stage_for_missing_opportunity_returns_404(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/pipeline/{opp_id + 999}/stage",
        data={"stage": "Contacted"},
    )

    assert response.status_code == 404


def test_changing_stage_via_a_different_projects_url_returns_404_and_leaves_it_unchanged(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    conn = get_connection(tmp_db_path)
    other_project_id = create_project(conn, "Other Project")
    conn.close()

    response = client.post(
        f"/projects/{other_project_id}/pipeline/{opp_id}/stage",
        data={"stage": "Contacted"},
    )

    assert response.status_code == 404

    conn = get_connection(tmp_db_path)
    row = conn.execute("SELECT stage FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
    conn.close()
    assert row["stage"] == "Research"


def test_changing_stage_via_hx_request_returns_the_updated_row_partial(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/pipeline/{opp_id}/stage",
        data={"stage": "Contacted"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "<html" not in response.text
    assert f'id="pipeline-row-{opp_id}"' in response.text
    assert 'selected' in response.text
    assert "Contacted" in response.text
