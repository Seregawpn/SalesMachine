# Mail Sync → CRM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the already-working CodexProvider + Mail MCP stack into an actual Project OS feature: a scheduled job that asks Codex to check the inbox, gets back structured JSON describing sales-relevant replies, and writes that into the CRM (contacts, interactions, actions) — idempotently, so re-running the sync never creates duplicates.

**Architecture:** `check_for_new_mail(provider, ...)` runs one Codex task with the read-only Mail MCP server enabled and a prompt that forces strict JSON output (no prose) — this is the "AI output contract" from the original spec: facts, AI interpretation, and a recommendation are all separate fields, never mixed free text. `sync_mail_replies(conn, provider, project_id)` is pure CRM logic: it parses that JSON, matches or creates a canonical contact by email, records one immutable `interactions` row per message (skipping ones already recorded, keyed by the mail client's own message id), and creates an `actions` row via the existing Phase 1 `create_action`/`has_open_action_for` idempotency pattern. The daemon's scheduler gains one more job that calls `sync_mail_replies` for every active project every 15 minutes, exactly like the existing `pipeline_consistency` and `unipile_sync` jobs.

**Tech Stack:** Python 3.11+, stdlib `json` for the AI output contract, existing `project_os` SQLite/repository layer, existing `CodexProvider`/Mail MCP stack. No new third-party dependency.

## Global Constraints

- AI output that will update the CRM must be structured and schema-validated, never freeform prose parsed by guesswork — malformed output must be rejected with a clear error, not silently coerced or guessed at (03_Project_OS_Automation_Logic §18-19, "AI output contract").
- Every interaction record must be immutable and keyed for idempotency — processing the same email twice must never create two `interactions` rows or two `actions` rows for it (03_Project_OS_Automation_Logic §11, "one sent message creates one interaction; retries must not create duplicates" — the same principle applies to inbound messages).
- Never invent facts: if the AI can't confidently extract a field, it must say so explicitly (e.g. `"summary": "Unknown"`) rather than fabricate — 03_Project_OS_Automation_Logic §10 ("never fabricate ... prior interactions").
- No test in this codebase may make a live network/subprocess call — `check_for_new_mail`'s tests use a `CodexProvider` built from a `FakeTransport` (same pattern as the CodexProvider plan's own tests), never a real `codex` process; `sync_mail_replies`'s tests use a real SQLite DB (per every other Phase 1 repository test) plus a simple test double for the provider (not a real `CodexProvider` at all — this task doesn't need Codex's turn-taking logic, just something with a `run_task` method).
- This plan builds on the existing `project_os` package (Phase 1 CRM + CodexProvider + Mail MCP, all already merged into this branch) — follow existing conventions: numbered SQL migrations with `schema_version`, no ORM, `create_action`/`has_open_action_for` for Action Center idempotency.
- Sending is explicitly out of scope for this plan — this only reads mail and updates the CRM. Drafts get created as data (an `actions.suggested_message` value); nothing is ever sent without a human approving through the existing Action Center UI first.

---

## File Structure

```
~/ProjectOS/
  src/project_os/
    migrations/
      0003_interactions.sql
    repositories/
      contacts.py            # MODIFIED: add get_contact_by_email
      interactions.py        # NEW: create_interaction, get_interaction_by_external_id
    ai/
      mail_sync.py            # NEW: check_for_new_mail, sync_mail_replies, MailSyncError
    daemon.py                 # MODIFIED: build_scheduler registers the mail_sync job
  tests/
    test_interactions_repo.py
    test_contacts_repo.py     # MODIFIED: new test for get_contact_by_email
    test_mail_sync.py
    test_daemon.py            # MODIFIED: new test for the mail_sync job registration
```

---

### Task 1: `interactions` table + repository

**Files:**
- Create: `src/project_os/migrations/0003_interactions.sql`
- Create: `src/project_os/repositories/interactions.py`
- Test: `tests/test_interactions_repo.py`

**Interfaces:**
- Consumes: `get_connection`, `run_migrations` (existing), `create_project`, `create_contact` (existing repositories).
- Produces: `create_interaction(conn, project_id, contact_id, *, channel, direction, subject, ai_summary, intent, external_message_id, source="apple-mail") -> int`, `get_interaction_by_external_id(conn, project_id, external_message_id) -> sqlite3.Row | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interactions_repo.py
from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact
from project_os.repositories.interactions import create_interaction, get_interaction_by_external_id

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    return conn, project_id, contact_id


def test_create_interaction_stores_all_fields(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)

    interaction_id = create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Re: pricing",
        ai_summary="Interested, asks about a demo.", intent="positive",
        external_message_id="15082",
    )

    row = conn.execute("SELECT * FROM interactions WHERE id = ?", (interaction_id,)).fetchone()
    assert row["project_id"] == project_id
    assert row["contact_id"] == contact_id
    assert row["channel"] == "email"
    assert row["direction"] == "inbound"
    assert row["subject"] == "Re: pricing"
    assert row["ai_summary"] == "Interested, asks about a demo."
    assert row["intent"] == "positive"
    assert row["external_message_id"] == "15082"
    assert row["source"] == "apple-mail"


def test_get_interaction_by_external_id_finds_existing_row(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Re: pricing",
        ai_summary="Interested.", intent="positive", external_message_id="15082",
    )

    found = get_interaction_by_external_id(conn, project_id, "15082")
    missing = get_interaction_by_external_id(conn, project_id, "99999")

    assert found is not None
    assert found["external_message_id"] == "15082"
    assert missing is None


def test_get_interaction_by_external_id_is_scoped_by_project(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    other_project_id = create_project(conn, "Other Project")
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Re: pricing",
        ai_summary="Interested.", intent="positive", external_message_id="15082",
    )

    found_in_other_project = get_interaction_by_external_id(conn, other_project_id, "15082")

    assert found_in_other_project is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_interactions_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.repositories.interactions'`

- [ ] **Step 3: Write `src/project_os/migrations/0003_interactions.sql`**

```sql
CREATE TABLE interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    channel TEXT NOT NULL,
    direction TEXT NOT NULL,
    subject TEXT,
    ai_summary TEXT,
    intent TEXT,
    external_message_id TEXT,
    source TEXT NOT NULL DEFAULT 'apple-mail',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_interactions_external_id ON interactions(project_id, external_message_id);
```

- [ ] **Step 4: Write `src/project_os/repositories/interactions.py`**

```python
import sqlite3


def create_interaction(
    conn: sqlite3.Connection,
    project_id: int,
    contact_id: int,
    *,
    channel: str,
    direction: str,
    subject: str | None,
    ai_summary: str | None,
    intent: str | None,
    external_message_id: str | None,
    source: str = "apple-mail",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO interactions
            (project_id, contact_id, channel, direction, subject, ai_summary, intent, external_message_id, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, contact_id, channel, direction, subject, ai_summary, intent, external_message_id, source),
    )
    return cur.lastrowid


def get_interaction_by_external_id(
    conn: sqlite3.Connection, project_id: int, external_message_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM interactions WHERE project_id = ? AND external_message_id = ?",
        (project_id, external_message_id),
    ).fetchone()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_interactions_repo.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/project_os/migrations/0003_interactions.sql src/project_os/repositories/interactions.py tests/test_interactions_repo.py
git commit -m "feat: interactions table for immutable inbound/outbound communication history"
```

---

### Task 2: `get_contact_by_email` on the contacts repository

**Files:**
- Modify: `src/project_os/repositories/contacts.py`
- Test: `tests/test_contacts_repo.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `get_contact_by_email(conn, email: str) -> sqlite3.Row | None` (canonical `contacts` row, matched by exact email — case-insensitive, since email addresses are conventionally case-insensitive on the domain and typically on the local part too for this use case).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_contacts_repo.py

def test_get_contact_by_email_finds_existing_contact(tmp_db_path):
    conn = _conn(tmp_db_path)
    create_contact(conn, "Jane Smith", email="Jane@Example.org")

    found = get_contact_by_email(conn, "jane@example.org")
    missing = get_contact_by_email(conn, "nobody@example.org")

    assert found is not None
    assert found["name"] == "Jane Smith"
    assert missing is None
```

Add `get_contact_by_email` to the existing import line at the top of the file:
```python
from project_os.repositories.contacts import (
    create_organization,
    create_contact,
    link_contact_to_project,
    get_project_contact,
    list_project_contacts,
    get_contact_by_email,
)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_contacts_repo.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_contact_by_email'`

- [ ] **Step 3: Modify `src/project_os/repositories/contacts.py`** — add this function (place it near `create_contact`):

```python
def get_contact_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM contacts WHERE LOWER(email) = LOWER(?)", (email,)
    ).fetchone()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_contacts_repo.py -v`
Expected: PASS (all tests in the file, including the new one)

- [ ] **Step 5: Commit**

```bash
git add src/project_os/repositories/contacts.py tests/test_contacts_repo.py
git commit -m "feat: look up a canonical contact by email"
```

---

### Task 3: `check_for_new_mail` — the AI task with a strict JSON output contract

**Files:**
- Create: `src/project_os/ai/mail_sync.py`
- Test: `tests/test_mail_sync.py`

**Interfaces:**
- Consumes: `CodexProvider` (has a `.run_task(prompt, *, cwd=..., developer_instructions=..., timeout=...) -> str` method — this task only needs that one method, so any object with it works, real or fake).
- Produces: `MailSyncError(RuntimeError)`, `REQUIRED_MAIL_REPLY_FIELDS: tuple[str, ...]`, `check_for_new_mail(provider, *, timeout: float = 120.0) -> list[dict]` — returns a list of dicts, each with keys `message_id`, `sender_email`, `sender_name`, `subject`, `summary`, `intent`, `recommended_action`, `draft_reply`, `due_date` (the last two may be `None`).

This is the AI output contract in code: Codex's raw text response is untrusted input until it's been parsed as JSON and every required field has been checked to exist and be the right type. A response that fails this check is a hard error (`MailSyncError`), never a best-effort partial parse — matching the spec's "reject malformed output" principle.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mail_sync.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mail_sync.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.ai.mail_sync'`

- [ ] **Step 3: Write `src/project_os/ai/mail_sync.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_mail_sync.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add src/project_os/ai/mail_sync.py tests/test_mail_sync.py
git commit -m "feat: check_for_new_mail AI task with a strict JSON output contract"
```

---

### Task 4: `sync_mail_replies` — CRM wiring with idempotency

**Files:**
- Modify: `src/project_os/ai/mail_sync.py`
- Test: `tests/test_mail_sync.py`

**Interfaces:**
- Consumes: `check_for_new_mail` (this file, Task 3), `get_contact_by_email`/`create_contact`/`link_contact_to_project`/`get_project_contact` (Task 2 + existing `contacts.py`), `get_interaction_by_external_id`/`create_interaction` (Task 1), `create_action`/`has_open_action_for` (existing `actions.py`).
- Produces: `sync_mail_replies(conn, provider: SupportsRunTask, project_id: int, *, timeout: float = 120.0) -> int` — returns the count of *new* interactions recorded (skips ones already known).

**Priority mapping** (matches the existing P0-P3 vocabulary from `actions.py`/Phase 1): `intent in ("positive", "question")` → `"P1"`; `intent in ("neutral", "scheduling")` → `"P2"`; `intent in ("negative", "objection", "administrative")` → `"P3"`; `intent == "not_sales_related"` → skip entirely (no interaction, no action — nothing to act on).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_mail_sync.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_mail_sync.py -v`
Expected: FAIL with `ImportError: cannot import name 'sync_mail_replies'`

- [ ] **Step 3: Modify `src/project_os/ai/mail_sync.py`** — add these imports at the top and the two functions at the end of the file:

```python
# add to the top of the file, alongside the existing imports:
import sqlite3

from project_os.repositories.actions import create_action, has_open_action_for
from project_os.repositories.contacts import create_contact, get_contact_by_email, get_project_contact, link_contact_to_project
from project_os.repositories.interactions import create_interaction, get_interaction_by_external_id
```

```python
# add at the end of the file:

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_mail_sync.py -v`
Expected: PASS (13 tests: 8 from Task 3 + 5 from this task)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `python -m pytest -v`
Expected: all tests pass (124 from the prior plans + 3 + 1 + 13 = 141).

- [ ] **Step 6: Commit**

```bash
git add src/project_os/ai/mail_sync.py tests/test_mail_sync.py
git commit -m "feat: sync_mail_replies wires AI-extracted mail replies into the CRM idempotently"
```

---

### Task 5: Wire the mail sync job into the daemon scheduler

**Files:**
- Modify: `src/project_os/daemon.py`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `sync_mail_replies` (Task 4), `CodexProvider.for_codex_cli` (existing), `mail_read_mcp_server.mcp_server_command` (existing), `list_projects` (existing), `Scheduler` (existing).
- Produces: `build_scheduler` (existing function, modified) registers one more job, `"mail_sync"`, at a 15-minute interval, alongside the existing `pipeline_consistency` and `unipile_sync` jobs.

Read the current `src/project_os/daemon.py` first — this task adds one more job function and one more `scheduler.register(...)` call inside the existing `build_scheduler`, following the exact same shape as the existing `pipeline_consistency`/`unipile_sync` jobs (open a connection, iterate active projects, catch and log a specific expected failure mode without crashing the scheduler thread — mirroring the `LookupError`-on-missing-Keychain-entry pattern already used for `unipile_sync`, and the per-job exception isolation already added to `Scheduler.run_pending` in a prior fix).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_daemon.py

def test_build_scheduler_registers_mail_sync_job(tmp_db_path, tmp_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    create_project(conn, "Nexy")
    conn.close()

    backup_dir = tmp_path / "backups"
    scheduler = build_scheduler(tmp_db_path, backup_dir, include_unipile=False)

    job_names = [job.name for job in scheduler._jobs]

    assert "mail_sync" in job_names


def test_mail_sync_job_does_not_crash_the_scheduler_when_codex_is_unavailable(tmp_db_path, tmp_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    create_project(conn, "Nexy")
    conn.close()

    backup_dir = tmp_path / "backups"
    scheduler = build_scheduler(
        tmp_db_path, backup_dir, include_unipile=False,
        codex_path="definitely-not-a-real-codex-binary",
    )

    # Codex isn't actually installed under this fake name, so the job
    # should fail internally and be caught — run_pending must not raise,
    # and the other jobs must still run.
    ran = scheduler.run_pending(now=0.0)

    assert "backup" in ran
    assert "pipeline_consistency" in ran
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_daemon.py -v`
Expected: FAIL — `mail_sync` not in `job_names` (the job doesn't exist yet), and/or `TypeError: build_scheduler() got an unexpected keyword argument 'codex_path'`.

- [ ] **Step 3: Modify `src/project_os/daemon.py`**

Read the current file first to see the exact existing signature of `build_scheduler` and the existing job closures (`_backup_job`, `_consistency_job`, `_unipile_sync_job` or equivalent) before editing, so your diff matches the file's actual current shape rather than an assumed one. Add:

1. A new keyword parameter to `build_scheduler`: `codex_path: str = "codex"` (defaults to the real CLI name; the test above overrides it to a fake name specifically to prove failures are caught, without needing to mock anything).
2. A new job closure, following the same pattern as the existing project-iterating jobs:

```python
    def _mail_sync_job() -> None:
        from project_os.ai.codex_provider import CodexProvider
        from project_os.ai.mail_read_mcp_server import mcp_server_command
        from project_os.ai.mail_sync import sync_mail_replies

        conn = get_connection(db_path)
        try:
            projects = list_projects(conn)
        finally:
            pass
        for project in projects:
            provider = CodexProvider.for_codex_cli(
                codex_path=codex_path,
                mcp_servers={"project-os-mail": mcp_server_command()},
            )
            try:
                sync_mail_replies(conn, provider, project["id"])
            finally:
                provider.close()
        conn.close()

    scheduler.register("mail_sync", interval_seconds=15 * 60, func=_mail_sync_job)
```

(Adjust connection-lifecycle details — e.g. whether to open one connection per job run vs. per project — to match whatever pattern the existing `_consistency_job`/`_unipile_sync_job` closures in the current file actually use, for consistency. The important behavioral requirements are: every active project gets a sync attempt, and any exception from `CodexProvider.for_codex_cli` or `sync_mail_replies` for one project must not prevent later projects from being attempted or crash the job — wrap the per-project body in its own `try/except Exception` that logs and continues, the same defensive shape already used elsewhere in this file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_daemon.py -v`
Expected: PASS (both new tests, plus all pre-existing daemon tests still passing)

- [ ] **Step 5: Run the full suite one more time**

Run: `python -m pytest -v`
Expected: all 143 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/project_os/daemon.py tests/test_daemon.py
git commit -m "feat: wire mail sync into the daemon scheduler"
```

- [ ] **Step 7: Manual end-to-end smoke test (not part of the automated suite)**

This is the real proof the whole feature works, from a cold inbox check through to a visible CRM record. Run by hand, with the venv active, Mail.app open, and at least one message in the inbox that plausibly looks sales-related (or just observe what Codex classifies as `not_sales_related` for ordinary mail — that's a valid, useful result too):

```bash
python3 - <<'EOF'
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.ai.codex_provider import CodexProvider
from project_os.ai.mail_read_mcp_server import mcp_server_command
from project_os.ai.mail_sync import sync_mail_replies
from pathlib import Path

db_path = "/tmp/mail_sync_smoke_test.sqlite"
conn = get_connection(db_path)
run_migrations(conn, Path("src/project_os/migrations"))
project_id = create_project(conn, "Smoke Test Project")

provider = CodexProvider.for_codex_cli(mcp_servers={"project-os-mail": mcp_server_command()})
try:
    created = sync_mail_replies(conn, provider, project_id, timeout=180.0)
finally:
    provider.close()

print(f"Created {created} new interaction(s).")
for row in conn.execute("SELECT * FROM interactions"):
    print(dict(row))
for row in conn.execute("SELECT * FROM actions"):
    print(dict(row))
EOF
```

Expected: the script completes without raising, prints `Created N new interaction(s)` for whatever N is real for your current inbox, and any printed `interactions`/`actions` rows describe genuine messages from your actual Mail.app inbox — not fabricated content. Delete `/tmp/mail_sync_smoke_test.sqlite` afterward; it's scratch data for this one manual check.

---

## Self-Review Notes

- **Spec coverage:** immutable interaction history (02_Project_OS_Architecture §5 "interactions") → Task 1. AI output contract with reject-on-malformed (03_Project_OS_Automation_Logic §18-19) → Task 3. CRM contact matching/creation, one-interaction-per-message idempotency (03_Project_OS_Automation_Logic §11) → Task 4. Unified Action Center priority (03_Project_OS_Automation_Logic §9) applied to inbound-mail-derived actions → Task 4's `_priority_for_intent`. Scheduled background processing (02_Project_OS_Architecture §7-8) → Task 5.
- **Explicitly out of scope for this plan:** sending anything (draft review/approval UI already exists from Phase 1's Action Center; this plan only ever writes a *suggested* message into `actions.suggested_message`, never calls the send MCP server). Calendar/meeting sync. Multi-account mail (only whatever Mail.app's primary inbox surfaces). Deduplicating the *same* real-world contact who emails from two different addresses (handled by the existing per-project contact model as two separate contacts, same as Phase 1's existing behavior — not a new gap this plan introduces).
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code. Task 5's job-closure code is presented as "the important behavioral requirements are X and Y, adjust connection-lifecycle details to match the existing file's pattern" rather than a rigid byte-for-byte diff, because the actual current shape of `daemon.py`'s existing jobs (after two prior plans' fix waves) needs to be read before this integration point is edited — this is a deliberate instruction to read-then-match, not a placeholder for missing logic.
- **Type consistency:** `check_for_new_mail`'s return type (`list[dict]`, each with `REQUIRED_MAIL_REPLY_FIELDS`) is exactly what `sync_mail_replies` consumes — same file, same task boundary, no drift possible. `SupportsRunTask` (a `Protocol`) is satisfied structurally by both `FakeProvider` (tests) and the real `CodexProvider` (production) — neither needs to inherit from it explicitly.
