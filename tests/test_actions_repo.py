from pathlib import Path

import pytest

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.actions import (
    create_action,
    list_open_actions,
    complete_action,
    snooze_action,
    has_open_action_for,
    get_reply_context,
)
from project_os.repositories.contacts import create_contact, link_contact_to_project
from project_os.repositories.interactions import create_interaction

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    return conn, project_id


def test_create_and_list_open_actions_ordered_by_priority(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    create_action(conn, project_id, module="Sales", reason="Low priority", priority="P3", due_date="2026-09-05")
    create_action(conn, project_id, module="Sales", reason="Urgent", priority="P0", due_date="2026-08-25")

    rows = list_open_actions(conn, project_id)
    assert [r["reason"] for r in rows] == ["Urgent", "Low priority"]


def test_complete_action_removes_it_from_open_list(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    action_id = create_action(conn, project_id, module="Sales", reason="Follow up")

    complete_action(conn, action_id)

    assert list_open_actions(conn, project_id) == []


def test_snooze_action_updates_due_date_and_keeps_it_open(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    action_id = create_action(conn, project_id, module="Sales", reason="Follow up", due_date="2026-08-25")

    snooze_action(conn, action_id, "2026-09-01")

    rows = list_open_actions(conn, project_id)
    assert rows[0]["due_date"] == "2026-09-01"


def test_complete_action_raises_lookup_error_for_missing_id(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)

    with pytest.raises(LookupError):
        complete_action(conn, 999999)


def test_snooze_action_raises_lookup_error_for_missing_id(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)

    with pytest.raises(LookupError):
        snooze_action(conn, 999999, "2026-09-01")


def test_has_open_action_for_prevents_duplicates(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    create_action(
        conn, project_id, module="Sales", reason="Missing next action",
        linked_table="opportunities", linked_id=42,
    )

    assert has_open_action_for(conn, "opportunities", 42, "Missing next action") is True
    assert has_open_action_for(conn, "opportunities", 999, "Missing next action") is False


def test_get_reply_context_returns_send_details_for_a_valid_mail_reply_action(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
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

    context = get_reply_context(conn, action_id)

    assert context == {
        "to": "jane@example.org",
        "subject": "Re: Pricing question",
        "body": "Here is our pricing.",
    }


def test_get_reply_context_returns_none_without_source_interaction_id(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    action_id = create_action(
        conn, project_id, module="Sales", reason="Reply",
        linked_table="contacts", linked_id=contact_id,
        suggested_message="Draft text.",
    )

    assert get_reply_context(conn, action_id) is None


def test_get_reply_context_returns_none_when_contact_has_no_email(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    contact_id = create_contact(conn, "Jane Smith")
    interaction_id = create_interaction(
        conn, project_id, contact_id, channel="email", direction="inbound",
        subject="Hi", ai_summary=None, intent=None, external_message_id="msg-2",
    )
    action_id = create_action(
        conn, project_id, module="Sales", reason="Reply",
        linked_table="contacts", linked_id=contact_id,
        suggested_message="Draft text.", source_interaction_id=interaction_id,
    )

    assert get_reply_context(conn, action_id) is None


def test_get_reply_context_returns_none_when_suggested_message_is_empty(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    interaction_id = create_interaction(
        conn, project_id, contact_id, channel="email", direction="inbound",
        subject="Hi", ai_summary=None, intent=None, external_message_id="msg-3",
    )
    action_id = create_action(
        conn, project_id, module="Sales", reason="Reply",
        linked_table="contacts", linked_id=contact_id,
        source_interaction_id=interaction_id,
    )

    assert get_reply_context(conn, action_id) is None


def test_get_reply_context_returns_none_for_a_completed_action(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    interaction_id = create_interaction(
        conn, project_id, contact_id, channel="email", direction="inbound",
        subject="Hi", ai_summary=None, intent=None, external_message_id="msg-4",
    )
    action_id = create_action(
        conn, project_id, module="Sales", reason="Reply",
        linked_table="contacts", linked_id=contact_id,
        suggested_message="Draft text.", source_interaction_id=interaction_id,
    )
    complete_action(conn, action_id)

    assert get_reply_context(conn, action_id) is None
