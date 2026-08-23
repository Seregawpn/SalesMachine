import json
import sqlite3
from typing import Any, Protocol

from project_os.repositories.actions import create_action, has_open_action_for
from project_os.repositories.contacts import create_contact, get_contact_by_email, get_project_contact, link_contact_to_project
from project_os.repositories.interactions import create_interaction, get_interaction_by_external_id

REQUIRED_MAIL_REPLY_FIELDS = (
    "message_id", "sender_email", "sender_name", "subject",
    "summary", "intent", "recommended_action", "draft_reply", "due_date",
)

_CHECK_MAIL_PROMPT = """\
Use the list_unread_messages tool to check the inbox for new messages.

For every message that is plausibly a sales-related reply (a person \
responding to outreach, asking a question about a product/service, or \
expressing interest or disinterest), respond with one JSON object per \
message. For messages that are clearly not sales-related (newsletters, \
notifications, spam, personal mail unrelated to sales), do not include \
them in the output at all.

Respond with ONLY a JSON array (no prose, no markdown code fences, no \
explanation before or after it) — a bare `[]` if there is nothing \
sales-relevant. Each object in the array must have exactly these fields:

- "message_id": the Apple Mail Message ID string exactly as returned by \
  the tool
- "sender_email": the sender's email address
- "sender_name": the sender's display name, or the email address again \
  if no display name is available
- "subject": the message subject line
- "summary": a one-to-two sentence factual summary of what the message says
- "intent": one of "positive", "neutral", "question", "objection", \
  "negative", "scheduling", "administrative", "not_sales_related"
- "recommended_action": a short, specific next step
- "draft_reply": a ready-to-send draft reply, or null if no reply is \
  warranted yet
- "due_date": an ISO date (YYYY-MM-DD) for when this should be followed \
  up on, or null if there is no clear due date

Never invent information that is not in the message. If you are not \
confident about a field, use "Unknown" for text fields or null for \
draft_reply/due_date rather than guessing.
"""


class SupportsRunTask(Protocol):
    def run_task(
        self, prompt: str, *, cwd: str = ".", developer_instructions: str = "", timeout: float = 60.0
    ) -> str: ...


class MailSyncError(RuntimeError):
    pass


def _validate_reply(reply: Any, index: int) -> dict:
    if not isinstance(reply, dict):
        raise MailSyncError(f"Item {index} in Codex's response is not a JSON object: {reply!r}")
    missing = [field for field in REQUIRED_MAIL_REPLY_FIELDS if field not in reply]
    if missing:
        raise MailSyncError(f"Item {index} in Codex's response is missing required field(s): {', '.join(missing)}")
    return reply


def check_for_new_mail(provider: SupportsRunTask, *, timeout: float = 120.0) -> list[dict]:
    raw_text = provider.run_task(_CHECK_MAIL_PROMPT, timeout=timeout)

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise MailSyncError(f"Codex's response was not valid JSON: {raw_text!r}") from error

    if not isinstance(parsed, list):
        raise MailSyncError(f"Codex's response was valid JSON but not an array: {raw_text!r}")

    return [_validate_reply(reply, index) for index, reply in enumerate(parsed)]


def _priority_for_intent(intent: str) -> str:
    if intent in ("positive", "question"):
        return "P1"
    if intent in ("neutral", "scheduling"):
        return "P2"
    return "P3"


def sync_mail_replies(
    conn: sqlite3.Connection,
    provider: SupportsRunTask,
    project_id: int,
    *,
    timeout: float = 120.0,
) -> int:
    replies = check_for_new_mail(provider, timeout=timeout)

    created = 0
    for reply in replies:
        if reply["intent"] == "not_sales_related":
            continue
        if get_interaction_by_external_id(conn, project_id, reply["message_id"]) is not None:
            continue

        contact = get_contact_by_email(conn, reply["sender_email"])
        if contact is None:
            contact_id = create_contact(conn, reply["sender_name"], email=reply["sender_email"])
        else:
            contact_id = contact["id"]

        if get_project_contact(conn, project_id, contact_id) is None:
            link_contact_to_project(conn, project_id, contact_id)

        create_interaction(
            conn, project_id, contact_id,
            channel="email", direction="inbound", subject=reply["subject"],
            ai_summary=reply["summary"], intent=reply["intent"],
            external_message_id=reply["message_id"],
        )

        reason = reply["recommended_action"]
        if not has_open_action_for(conn, "contacts", contact_id, reason):
            create_action(
                conn, project_id, module="Sales", reason=reason,
                priority=_priority_for_intent(reply["intent"]),
                due_date=reply["due_date"],
                linked_table="contacts", linked_id=contact_id,
                suggested_message=reply["draft_reply"],
            )
        created += 1

    return created
