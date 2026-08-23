import json
from typing import Any, Protocol

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
