import subprocess
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


def test_sending_a_reply_with_non_mail_send_error_still_redirects_with_flash_error(tmp_db_path, monkeypatch):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)

    def fake_send_via_jxa(payload, *, runner=None):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=20)

    monkeypatch.setattr("project_os.web.routes_action_center.send_via_jxa", fake_send_via_jxa)

    response = client.post(
        f"/actions/{action_id}/send", data={"message": "Edited reply text."}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/action-center?error=")
    conn = get_connection(tmp_db_path)
    assert len(list_open_actions(conn, project_id)) == 1
    outbound = conn.execute("SELECT * FROM interactions WHERE direction = 'outbound'").fetchall()
    conn.close()
    assert outbound == []


def test_sending_a_blank_reply_is_rejected_without_sending(tmp_db_path, monkeypatch):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)
    calls = []

    def fake_send_via_jxa(payload, *, runner=None):
        calls.append(payload)

    monkeypatch.setattr("project_os.web.routes_action_center.send_via_jxa", fake_send_via_jxa)

    response = client.post(
        f"/actions/{action_id}/send", data={"message": "   "}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/action-center?error=Reply%20text%20cannot%20be%20empty."
    assert calls == []
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


def test_action_center_shows_reply_draft_for_a_sendable_action(tmp_db_path):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert "Reply draft" in response.text
    assert "Here is our pricing." in response.text
    assert "Approve &amp; Send" in response.text
    assert f'action="/actions/{action_id}/send"' in response.text


def test_action_center_hides_reply_draft_for_action_without_reply_context(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert "Reply draft" not in response.text


def test_action_center_shows_error_banner_from_query_param(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    response = client.get("/action-center?error=Mail%20is%20not%20configured.")

    assert response.status_code == 200
    assert "Mail is not configured." in response.text


def test_completing_an_action_via_hx_request_returns_an_empty_fragment(tmp_db_path):
    client, project_id = _client(tmp_db_path)
    conn = get_connection(tmp_db_path)
    row = conn.execute("SELECT id FROM actions LIMIT 1").fetchone()
    conn.close()

    response = client.post(f"/actions/{row['id']}/complete", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert f'id="action-row-{row["id"]}"' not in response.text


def test_snoozing_an_action_via_hx_request_returns_the_row_partial(tmp_db_path):
    client, project_id = _client(tmp_db_path)
    conn = get_connection(tmp_db_path)
    row = conn.execute("SELECT id FROM actions LIMIT 1").fetchone()
    conn.close()

    response = client.post(
        f"/actions/{row['id']}/snooze",
        data={"new_due_date": "2026-09-20"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "<html" not in response.text
    assert "2026-09-20" in response.text
    assert f'id="action-row-{row["id"]}"' in response.text


def test_sending_a_reply_via_hx_request_returns_an_empty_fragment_on_success(tmp_db_path, monkeypatch):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)

    def fake_send_via_jxa(payload, *, runner=None):
        pass

    monkeypatch.setattr("project_os.web.routes_action_center.send_via_jxa", fake_send_via_jxa)

    response = client.post(
        f"/actions/{action_id}/send",
        data={"message": "Edited reply text."},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert f'id="action-row-{action_id}"' not in response.text


def test_sending_a_reply_via_hx_request_returns_oob_banner_only_on_failure(tmp_db_path, monkeypatch):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)

    def fake_send_via_jxa(payload, *, runner=None):
        raise MailSendError("Mail is not configured.")

    monkeypatch.setattr("project_os.web.routes_action_center.send_via_jxa", fake_send_via_jxa)

    response = client.post(
        f"/actions/{action_id}/send",
        data={"message": "Edited reply text."},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert f'id="action-row-{action_id}"' not in response.text
    assert 'hx-swap-oob="true"' in response.text
    assert "Mail is not configured." in response.text
    assert response.headers["HX-Reswap"] == "none"
    conn = get_connection(tmp_db_path)
    assert len(list_open_actions(conn, project_id)) == 1
    conn.close()


def test_sending_a_blank_reply_via_hx_request_returns_oob_banner_only(tmp_db_path):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)

    response = client.post(
        f"/actions/{action_id}/send",
        data={"message": "   "},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert f'id="action-row-{action_id}"' not in response.text
    assert 'hx-swap-oob="true"' in response.text
    assert "Reply text cannot be empty." in response.text
    assert response.headers["HX-Reswap"] == "none"
    conn = get_connection(tmp_db_path)
    assert len(list_open_actions(conn, project_id)) == 1
    conn.close()


def test_completing_an_action_via_hx_request_resets_the_flash_banner(tmp_db_path):
    client, project_id = _client(tmp_db_path)
    conn = get_connection(tmp_db_path)
    row = conn.execute("SELECT id FROM actions LIMIT 1").fetchone()
    conn.close()

    response = client.post(f"/actions/{row['id']}/complete", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert 'id="flash-banner"' in response.text
    assert 'hx-swap-oob="true"' in response.text
    assert "hidden" in response.text


def test_sending_a_reply_via_hx_request_resets_the_flash_banner_on_success(tmp_db_path, monkeypatch):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)

    def fake_send_via_jxa(payload, *, runner=None):
        pass

    monkeypatch.setattr("project_os.web.routes_action_center.send_via_jxa", fake_send_via_jxa)

    response = client.post(
        f"/actions/{action_id}/send",
        data={"message": "Edited reply text."},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert 'id="flash-banner"' in response.text
    assert 'hx-swap-oob="true"' in response.text
    assert "hidden" in response.text


def test_sending_a_reply_with_view_emails_redirects_to_the_email_on_success(tmp_db_path, monkeypatch):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)
    conn = get_connection(tmp_db_path)
    interaction_id = conn.execute(
        "SELECT source_interaction_id FROM actions WHERE id = ?", (action_id,)
    ).fetchone()["source_interaction_id"]
    conn.close()

    def fake_send_via_jxa(payload):
        return None

    monkeypatch.setattr("project_os.web.routes_action_center.send_via_jxa", fake_send_via_jxa)

    response = client.post(
        f"/actions/{action_id}/send",
        data={"message": "Here is our pricing.", "view": "emails"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == f"/emails/{interaction_id}"


def test_sending_a_reply_with_view_emails_via_hx_returns_the_detail_partial(tmp_db_path, monkeypatch):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)

    def fake_send_via_jxa(payload):
        return None

    monkeypatch.setattr("project_os.web.routes_action_center.send_via_jxa", fake_send_via_jxa)

    response = client.post(
        f"/actions/{action_id}/send",
        data={"message": "Here is our pricing.", "view": "emails"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "<html" not in response.text
    assert "No action needed." in response.text
    # Pin down which interaction is actually shown: the original inbound
    # email (subject "Pricing question"), not the brand-new outbound reply
    # (subject "Re: Pricing question") that send_reply just created. Both
    # rows would satisfy "No action needed." alone, so that assertion
    # can't tell correct behavior from a regression that fell back to
    # rendering the newest/first row.
    assert "Pricing question" in response.text
    assert "Re: Pricing question" not in response.text


def test_sending_a_reply_without_view_field_still_redirects_to_action_center(tmp_db_path, monkeypatch):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)

    def fake_send_via_jxa(payload):
        return None

    monkeypatch.setattr("project_os.web.routes_action_center.send_via_jxa", fake_send_via_jxa)

    response = client.post(
        f"/actions/{action_id}/send",
        data={"message": "Here is our pricing."},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/action-center"
