from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.actions import create_action, list_open_actions
from project_os.repositories.contacts import create_contact, link_contact_to_project
from project_os.repositories.interactions import create_interaction
from project_os.ai.mail_send_mcp_server import MailSendError

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    create_action(conn, project_id, module="Sales", reason="Reply from decision maker", priority="P1", due_date="2026-08-22")
    conn.close()

    app = create_app(tmp_db_path)
    return TestClient(app), project_id


def _client_with_reply_action(tmp_db_path):
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
    action_id = create_action(
        conn, project_id, module="Sales", reason="Reply with pricing",
        linked_table="contacts", linked_id=contact_id,
        suggested_message="Here is our pricing.",
        source_interaction_id=interaction_id,
    )
    conn.close()

    app = create_app(tmp_db_path)
    return TestClient(app), project_id, action_id


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


def test_sending_a_reply_completes_the_action_and_records_outbound_interaction(tmp_db_path, monkeypatch):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)
    captured = {}

    def fake_send_via_jxa(payload, *, runner=None):
        captured["payload"] = payload

    monkeypatch.setattr("project_os.web.routes_action_center.send_via_jxa", fake_send_via_jxa)

    response = client.post(
        f"/actions/{action_id}/send", data={"message": "Edited reply text."}, follow_redirects=True
    )

    assert response.status_code == 200
    assert captured["payload"] == {
        "to": "jane@example.org", "subject": "Re: Pricing question", "body": "Edited reply text.",
    }
    conn = get_connection(tmp_db_path)
    assert list_open_actions(conn, project_id) == []
    outbound = conn.execute("SELECT * FROM interactions WHERE direction = 'outbound'").fetchall()
    conn.close()
    assert len(outbound) == 1
    assert outbound[0]["subject"] == "Re: Pricing question"


def test_sending_a_reply_with_send_failure_leaves_the_action_open(tmp_db_path, monkeypatch):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)

    def fake_send_via_jxa(payload, *, runner=None):
        raise MailSendError("Mail is not configured.")

    monkeypatch.setattr("project_os.web.routes_action_center.send_via_jxa", fake_send_via_jxa)

    response = client.post(
        f"/actions/{action_id}/send", data={"message": "Edited reply text."}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/action-center?error=Mail%20is%20not%20configured."
    conn = get_connection(tmp_db_path)
    assert len(list_open_actions(conn, project_id)) == 1
    outbound = conn.execute("SELECT * FROM interactions WHERE direction = 'outbound'").fetchall()
    conn.close()
    assert outbound == []


def test_sending_a_reply_for_an_action_without_reply_context_returns_404(tmp_db_path):
    client, project_id = _client(tmp_db_path)
    conn = get_connection(tmp_db_path)
    row = conn.execute("SELECT id FROM actions LIMIT 1").fetchone()
    conn.close()

    response = client.post(f"/actions/{row['id']}/send", data={"message": "Some text"})

    assert response.status_code == 404
