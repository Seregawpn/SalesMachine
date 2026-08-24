from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, link_contact_to_project
from project_os.repositories.interactions import create_interaction
from project_os.repositories.actions import create_action

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client_no_emails(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    create_project(conn, "Nexy")
    conn.close()
    return TestClient(create_app(tmp_db_path))


def _client_with_email(tmp_db_path, with_open_action=False):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    link_contact_to_project(conn, project_id, contact_id)
    interaction_id = create_interaction(
        conn, project_id, contact_id, channel="email", direction="inbound",
        subject="Pricing question", ai_summary="Wants pricing.", intent="question",
        external_message_id="msg-1",
    )
    action_id = None
    if with_open_action:
        action_id = create_action(
            conn, project_id, module="Sales", reason="Reply with pricing",
            linked_table="contacts", linked_id=contact_id,
            suggested_message="Here is our pricing.",
            source_interaction_id=interaction_id,
        )
    conn.close()
    return TestClient(create_app(tmp_db_path)), project_id, interaction_id, action_id


def test_emails_index_shows_a_message_when_there_are_no_emails(tmp_db_path):
    client = _client_no_emails(tmp_db_path)

    response = client.get("/emails")

    assert response.status_code == 200
    assert "No emails yet." in response.text


def test_emails_index_lists_the_email_and_selects_it_by_default(tmp_db_path):
    client, project_id, interaction_id, _ = _client_with_email(tmp_db_path)

    response = client.get("/emails")

    assert response.status_code == 200
    assert "Pricing question" in response.text
    assert "Jane Smith" in response.text
    assert "Wants pricing." in response.text
    assert f'href="/emails/{interaction_id}"' in response.text


def test_emails_show_selects_the_requested_interaction(tmp_db_path):
    client, project_id, interaction_id, _ = _client_with_email(tmp_db_path)

    response = client.get(f"/emails/{interaction_id}")

    assert response.status_code == 200
    assert "Pricing question" in response.text


def test_emails_show_for_nonexistent_interaction_returns_404(tmp_db_path):
    client, project_id, interaction_id, _ = _client_with_email(tmp_db_path)

    response = client.get(f"/emails/{interaction_id + 999}")

    assert response.status_code == 404


def test_emails_detail_shows_reply_form_only_when_action_is_open(tmp_db_path):
    client, project_id, interaction_id, action_id = _client_with_email(tmp_db_path, with_open_action=True)

    response = client.get(f"/emails/{interaction_id}")

    assert response.status_code == 200
    assert "Here is our pricing." in response.text
    assert f'action="/actions/{action_id}/send"' in response.text
    assert 'name="view" value="emails"' in response.text


def test_emails_detail_hides_reply_form_when_no_open_action(tmp_db_path):
    client, project_id, interaction_id, _ = _client_with_email(tmp_db_path, with_open_action=False)

    response = client.get(f"/emails/{interaction_id}")

    assert response.status_code == 200
    assert "No action needed." in response.text
    assert "/send" not in response.text


def test_base_layout_includes_the_emails_nav_link(tmp_db_path):
    client = _client_no_emails(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert 'href="/emails"' in response.text
