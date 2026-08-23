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
