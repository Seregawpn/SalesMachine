import json

from project_os.ai.mail_sync import check_for_new_mail, MailSyncError, REQUIRED_MAIL_REPLY_FIELDS


class FakeProvider:
    """A stand-in for CodexProvider that only needs .run_task — no real
    turn-taking, transport, or subprocess involved."""

    def __init__(self, response_text: str):
        self._response_text = response_text
        self.last_prompt = None

    def run_task(self, prompt, *, cwd=".", developer_instructions="", timeout=60.0):
        self.last_prompt = prompt
        return self._response_text


def _valid_reply(**overrides):
    reply = {
        "message_id": "15082",
        "sender_email": "jane@example.org",
        "sender_name": "Jane Smith",
        "subject": "Re: pricing",
        "summary": "Interested, asks about a demo.",
        "intent": "positive",
        "recommended_action": "Propose a demo time.",
        "draft_reply": "Happy to set up a demo — does Thursday work?",
        "due_date": "2026-08-25",
    }
    reply.update(overrides)
    return reply


def test_check_for_new_mail_returns_parsed_replies():
    provider = FakeProvider(json.dumps([_valid_reply()]))

    replies = check_for_new_mail(provider)

    assert len(replies) == 1
    assert replies[0]["sender_email"] == "jane@example.org"
    assert replies[0]["intent"] == "positive"


def test_check_for_new_mail_returns_empty_list_for_empty_json_array():
    provider = FakeProvider("[]")

    replies = check_for_new_mail(provider)

    assert replies == []


def test_check_for_new_mail_raises_on_non_json_response():
    provider = FakeProvider("Sure! Here's what I found: nothing much.")

    try:
        check_for_new_mail(provider)
        assert False, "expected MailSyncError"
    except MailSyncError as error:
        assert "JSON" in str(error)


def test_check_for_new_mail_raises_when_response_is_not_a_json_array():
    provider = FakeProvider(json.dumps({"message_id": "1"}))

    try:
        check_for_new_mail(provider)
        assert False, "expected MailSyncError"
    except MailSyncError as error:
        assert "array" in str(error).lower()


def test_check_for_new_mail_raises_on_missing_required_field():
    incomplete = _valid_reply()
    del incomplete["intent"]
    provider = FakeProvider(json.dumps([incomplete]))

    try:
        check_for_new_mail(provider)
        assert False, "expected MailSyncError"
    except MailSyncError as error:
        assert "intent" in str(error)


def test_check_for_new_mail_allows_null_draft_reply_and_due_date():
    reply = _valid_reply(draft_reply=None, due_date=None, intent="not_sales_related")
    provider = FakeProvider(json.dumps([reply]))

    replies = check_for_new_mail(provider)

    assert replies[0]["draft_reply"] is None
    assert replies[0]["due_date"] is None


def test_check_for_new_mail_prompt_mentions_the_mail_tool_and_json_only():
    provider = FakeProvider("[]")

    check_for_new_mail(provider)

    assert "list_unread_messages" in provider.last_prompt
    assert "JSON" in provider.last_prompt


def test_required_mail_reply_fields_match_what_is_validated():
    assert REQUIRED_MAIL_REPLY_FIELDS == (
        "message_id", "sender_email", "sender_name", "subject",
        "summary", "intent", "recommended_action", "draft_reply", "due_date",
    )


def test_check_for_new_mail_raises_on_non_string_message_id():
    reply = _valid_reply(message_id={"nested": 1})
    provider = FakeProvider(json.dumps([reply]))
    try:
        check_for_new_mail(provider)
        assert False, "expected MailSyncError"
    except MailSyncError as error:
        assert "message_id" in str(error)


def test_check_for_new_mail_raises_on_sender_email_without_at_sign():
    reply = _valid_reply(sender_email="Unknown")
    provider = FakeProvider(json.dumps([reply]))
    try:
        check_for_new_mail(provider)
        assert False, "expected MailSyncError"
    except MailSyncError as error:
        assert "sender_email" in str(error)


def test_check_for_new_mail_raises_on_unrecognized_intent():
    reply = _valid_reply(intent="Positive")
    provider = FakeProvider(json.dumps([reply]))
    try:
        check_for_new_mail(provider)
        assert False, "expected MailSyncError"
    except MailSyncError as error:
        assert "intent" in str(error)


from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, link_contact_to_project, get_contact_by_email, get_project_contact
from project_os.repositories.interactions import get_interaction_by_external_id
from project_os.repositories.actions import list_open_actions
from project_os.ai.mail_sync import sync_mail_replies

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _project(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    return conn, project_id


def test_sync_mail_replies_creates_a_new_contact_interaction_and_action(tmp_db_path):
    conn, project_id = _project(tmp_db_path)
    provider = FakeProvider(json.dumps([_valid_reply()]))

    created = sync_mail_replies(conn, provider, project_id)

    assert created == 1
    contact = get_contact_by_email(conn, "jane@example.org")
    assert contact is not None
    assert contact["name"] == "Jane Smith"
    project_contact = get_project_contact(conn, project_id, contact["id"])
    assert project_contact is not None
    interaction = get_interaction_by_external_id(conn, project_id, "15082")
    assert interaction is not None
    assert interaction["ai_summary"] == "Interested, asks about a demo."
    actions = list_open_actions(conn, project_id)
    assert len(actions) == 1
    assert actions[0]["priority"] == "P1"
    assert actions[0]["suggested_message"] == "Happy to set up a demo — does Thursday work?"


def test_sync_mail_replies_reuses_an_existing_contact(tmp_db_path):
    conn, project_id = _project(tmp_db_path)
    existing_contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    provider = FakeProvider(json.dumps([_valid_reply()]))

    sync_mail_replies(conn, provider, project_id)

    all_contacts = conn.execute("SELECT COUNT(*) AS n FROM contacts WHERE email = 'jane@example.org'").fetchone()
    assert all_contacts["n"] == 1
    interaction = get_interaction_by_external_id(conn, project_id, "15082")
    assert interaction["contact_id"] == existing_contact_id


def test_sync_mail_replies_is_idempotent_across_two_runs(tmp_db_path):
    conn, project_id = _project(tmp_db_path)
    provider = FakeProvider(json.dumps([_valid_reply()]))

    first_run = sync_mail_replies(conn, provider, project_id)
    second_run = sync_mail_replies(conn, provider, project_id)

    assert first_run == 1
    assert second_run == 0
    interaction_count = conn.execute("SELECT COUNT(*) AS n FROM interactions").fetchone()["n"]
    assert interaction_count == 1
    assert len(list_open_actions(conn, project_id)) == 1


def test_sync_mail_replies_skips_not_sales_related_messages(tmp_db_path):
    conn, project_id = _project(tmp_db_path)
    reply = _valid_reply(intent="not_sales_related", draft_reply=None, due_date=None)
    provider = FakeProvider(json.dumps([reply]))

    created = sync_mail_replies(conn, provider, project_id)

    assert created == 0
    assert get_interaction_by_external_id(conn, project_id, "15082") is None
    assert list_open_actions(conn, project_id) == []


def test_sync_mail_replies_maps_intent_to_priority():
    # Documents the mapping directly for a reader of this test file, since
    # it's a business rule worth being explicit about rather than only
    # implicit in sync_mail_replies' body.
    from project_os.ai.mail_sync import _priority_for_intent

    assert _priority_for_intent("positive") == "P1"
    assert _priority_for_intent("question") == "P1"
    assert _priority_for_intent("neutral") == "P2"
    assert _priority_for_intent("scheduling") == "P2"
    assert _priority_for_intent("negative") == "P3"
    assert _priority_for_intent("objection") == "P3"
    assert _priority_for_intent("administrative") == "P3"


def test_sync_mail_replies_leaves_no_partial_state_if_action_creation_fails(tmp_db_path, monkeypatch):
    import project_os.ai.mail_sync as mail_sync_module

    conn, project_id = _project(tmp_db_path)
    provider = FakeProvider(json.dumps([_valid_reply()]))

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(mail_sync_module, "create_action", _boom)

    try:
        sync_mail_replies(conn, provider, project_id)
        assert False, "expected the simulated failure to propagate"
    except RuntimeError:
        pass

    # Nothing should have been committed: no interaction, no contact.
    assert get_interaction_by_external_id(conn, project_id, "15082") is None
    assert get_contact_by_email(conn, "jane@example.org") is None
