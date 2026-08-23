# Approve & Send for Mail Replies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the Mail Sync → CRM loop by letting a human review, edit, and send an AI-drafted reply directly from the Action Center, so the approved reply actually goes out through Apple Mail and the CRM's conversation history stays complete in both directions.

**Architecture:** A new `POST /actions/{id}/send` route re-validates the action is still sendable (via a new `get_reply_context` repository query), calls the existing `send_via_jxa` function (renamed public from `_send_via_jxa` in `mail_send_mcp_server.py`) directly — no AI call needed, the text is already human-approved — then closes the action and records an outbound `interaction` in one transaction. `actions` gains a `source_interaction_id` column so the reply's `Re: <subject>` can be derived reliably; `mail_sync.sync_mail_replies` is updated to populate it. The Action Center template gets a collapsible, editable reply-draft form per sendable action, plus a flash-error banner for failed sends.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2 templates (server-rendered, no JS), stdlib `sqlite3`, matches the existing `project_os` package conventions exactly (no ORM, no new dependency).

## Global Constraints

- No test in this codebase may spawn real Apple Mail or JXA — `send_via_jxa` is always exercised through its injectable `runner` parameter or monkeypatched at the call site, mirroring `mail_send_mcp_server.py`'s existing tests and the accepted mocking exception at that one genuine external-process boundary.
- No ORM, stdlib-first, direct SQL via `sqlite3.Connection` — follow the exact style already used in `repositories/actions.py`, `repositories/contacts.py`, `repositories/interactions.py`.
- Multi-statement DB writes that must not partially apply use the existing `conn.execute("BEGIN")` / `conn.commit()` / `conn.rollback()` pattern already used in `mail_sync.sync_mail_replies` — not a new transaction helper.
- This plan builds on top of `main` at commit `9663be1` (CRM, CodexProvider, Mail MCP, Mail Sync all already merged) and does not modify Mail Sync's classification/drafting logic — only how its output gets acted on.
- Server-rendered HTML only, no JavaScript, no new frontend dependency — matches every existing template in `src/project_os/web/templates/`.

---

## File Structure

```
~/ProjectOS/
  src/project_os/
    migrations/
      0004_action_source_interaction.sql   # new: actions.source_interaction_id column
    repositories/
      actions.py                            # modified: create_action gains a param, new get_reply_context()
    ai/
      mail_sync.py                          # modified: passes the inbound interaction id through to create_action
      mail_send_mcp_server.py               # modified: _send_via_jxa -> send_via_jxa (public rename)
    web/
      routes_action_center.py               # modified: new POST /actions/{id}/send route; GET route passes reply contexts + error
      templates/
        action_center.html                  # modified: collapsible reply-draft form, flash-error banner
  tests/
    test_actions_repo.py                    # modified: get_reply_context tests
    test_mail_sync.py                       # modified: source_interaction_id assertion
    test_mail_send_mcp_server.py            # modified: import/call rename
    test_action_center_routes.py            # modified: send route tests, template rendering tests
```

---

### Task 1: `source_interaction_id` column + `get_reply_context` repository query

**Files:**
- Create: `src/project_os/migrations/0004_action_source_interaction.sql`
- Modify: `src/project_os/repositories/actions.py:6-25` (`create_action`)
- Modify: `src/project_os/repositories/actions.py` (append `get_reply_context`)
- Test: `tests/test_actions_repo.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `create_action(..., source_interaction_id: int | None = None) -> int` (all prior params unchanged, this one is additive and optional). `get_reply_context(conn: sqlite3.Connection, action_id: int) -> dict | None` returning `{"to": str, "subject": str, "body": str}` or `None`.

`actions` currently has no link back to the specific inbound message a draft is replying to — only `linked_table='contacts'` / `linked_id=<contact_id>`. Without that link there is no reliable `Re: <subject>` to send, so this task adds it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_actions_repo.py` (append after the existing `test_has_open_action_for_prevents_duplicates`, and extend the import block at the top):

```python
# Add to the existing import block at the top of the file:
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
```

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_actions_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_reply_context'` (and `create_action() got an unexpected keyword argument 'source_interaction_id'` once that import is fixed).

- [ ] **Step 3: Write the migration**

Create `src/project_os/migrations/0004_action_source_interaction.sql`:

```sql
ALTER TABLE actions ADD COLUMN source_interaction_id INTEGER REFERENCES interactions(id);
```

- [ ] **Step 4: Update `create_action` and add `get_reply_context`**

Replace `src/project_os/repositories/actions.py:6-25` with:

```python
def create_action(
    conn: sqlite3.Connection,
    project_id: int,
    module: str,
    reason: str,
    priority: str = "P2",
    due_date: str | None = None,
    linked_table: str | None = None,
    linked_id: int | None = None,
    suggested_message: str | None = None,
    source_interaction_id: int | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO actions
            (project_id, module, linked_table, linked_id, reason, priority, due_date,
             suggested_message, source_interaction_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id, module, linked_table, linked_id, reason, priority, due_date,
            suggested_message, source_interaction_id,
        ),
    )
    return cur.lastrowid
```

Append to `src/project_os/repositories/actions.py` (after `has_open_action_for`):

```python
def get_reply_context(conn: sqlite3.Connection, action_id: int) -> dict | None:
    row = conn.execute(
        """
        SELECT c.email AS to_email, i.subject AS interaction_subject, a.suggested_message AS body
        FROM actions a
        JOIN contacts c ON a.linked_table = 'contacts' AND c.id = a.linked_id
        JOIN interactions i ON i.id = a.source_interaction_id
        WHERE a.id = ?
          AND a.status = 'Open'
          AND a.suggested_message IS NOT NULL AND a.suggested_message != ''
          AND c.email IS NOT NULL AND c.email != ''
        """,
        (action_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "to": row["to_email"],
        "subject": f"Re: {row['interaction_subject']}",
        "body": row["body"],
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_actions_repo.py -v`
Expected: PASS (11 tests: 6 existing + 5 new)

- [ ] **Step 6: Commit**

```bash
git add src/project_os/migrations/0004_action_source_interaction.sql src/project_os/repositories/actions.py tests/test_actions_repo.py
git commit -m "feat: link actions to their source interaction for reply context"
```

---

### Task 2: Wire `source_interaction_id` through `mail_sync.sync_mail_replies`

**Files:**
- Modify: `src/project_os/ai/mail_sync.py:146-160`
- Test: `tests/test_mail_sync.py`

**Interfaces:**
- Consumes: `create_action(..., source_interaction_id: int | None = None)`, `get_reply_context` (Task 1, for context only — this task doesn't call it directly).
- Produces: no new public interface — `sync_mail_replies`'s signature and return value are unchanged; only the `actions` rows it creates now carry `source_interaction_id`.

`create_interaction` (in `repositories/interactions.py`) already returns the new row's id via `cur.lastrowid` — `sync_mail_replies` just wasn't capturing it.

- [ ] **Step 1: Write the failing test**

Modify the existing test in `tests/test_mail_sync.py` — find `test_sync_mail_replies_creates_a_new_contact_interaction_and_action` and add one assertion at the end:

```python
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
    assert actions[0]["source_interaction_id"] == interaction["id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mail_sync.py -v -k creates_a_new_contact`
Expected: FAIL — `assert None == interaction["id"]`

- [ ] **Step 3: Update `sync_mail_replies`**

In `src/project_os/ai/mail_sync.py`, replace lines 146-160:

```python
            create_interaction(
                conn, project_id, contact_id,
                channel="email", direction="inbound", subject=reply["subject"],
                ai_summary=reply["summary"], intent=reply["intent"],
                external_message_id=reply["message_id"],
            )

            create_action(
                conn, project_id, module="Sales", reason=reply["recommended_action"],
                priority=_priority_for_intent(reply["intent"]),
                due_date=reply["due_date"],
                linked_table="contacts", linked_id=contact_id,
                suggested_message=reply["draft_reply"],
            )
```

with:

```python
            interaction_id = create_interaction(
                conn, project_id, contact_id,
                channel="email", direction="inbound", subject=reply["subject"],
                ai_summary=reply["summary"], intent=reply["intent"],
                external_message_id=reply["message_id"],
            )

            create_action(
                conn, project_id, module="Sales", reason=reply["recommended_action"],
                priority=_priority_for_intent(reply["intent"]),
                due_date=reply["due_date"],
                linked_table="contacts", linked_id=contact_id,
                suggested_message=reply["draft_reply"],
                source_interaction_id=interaction_id,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mail_sync.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Commit**

```bash
git add src/project_os/ai/mail_sync.py tests/test_mail_sync.py
git commit -m "feat: mail sync records which interaction an action's draft is replying to"
```

---

### Task 3: Make `send_via_jxa` public

**Files:**
- Modify: `src/project_os/ai/mail_send_mcp_server.py:49,96`
- Test: `tests/test_mail_send_mcp_server.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `send_via_jxa(payload: dict[str, Any], *, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None` (identical signature and behavior to the old `_send_via_jxa` — pure rename, no logic change). Raises `MailSendError` on non-zero exit, exactly as before.

This is a pure rename so both the MCP tool path (Codex calling `send_message`) and the new direct path (a human's approved click, Task 4) can call the same function without going through the MCP JSON-RPC envelope. `MailSendError` (already public) is unchanged.

- [ ] **Step 1: Write the failing test**

In `tests/test_mail_send_mcp_server.py`, change the import line:

```python
from project_os.ai.mail_send_mcp_server import handle_request, mcp_server_command, MailSendError, _send_via_jxa
```

to:

```python
from project_os.ai.mail_send_mcp_server import handle_request, mcp_server_command, MailSendError, send_via_jxa
```

And in `test_send_via_jxa_raises_mail_send_error_on_failure` (near the end of the file), change:

```python
def test_send_via_jxa_raises_mail_send_error_on_failure():
    try:
        _send_via_jxa({"to": "x@example.org", "subject": "s", "body": "b"}, runner=_fake_runner(returncode=1, stderr="boom"))
        assert False, "expected MailSendError"
    except MailSendError as error:
        assert "boom" in str(error)
```

to:

```python
def test_send_via_jxa_raises_mail_send_error_on_failure():
    try:
        send_via_jxa({"to": "x@example.org", "subject": "s", "body": "b"}, runner=_fake_runner(returncode=1, stderr="boom"))
        assert False, "expected MailSendError"
    except MailSendError as error:
        assert "boom" in str(error)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mail_send_mcp_server.py -v`
Expected: FAIL — `ImportError: cannot import name 'send_via_jxa'`

- [ ] **Step 3: Rename in the source file**

In `src/project_os/ai/mail_send_mcp_server.py`, line 49, change the function definition:

```python
def _send_via_jxa(
```

to:

```python
def send_via_jxa(
```

And line 96, change the call site inside `_send_message_result`:

```python
        _send_via_jxa({field: arguments[field] for field in _REQUIRED_FIELDS}, runner=runner)
```

to:

```python
        send_via_jxa({field: arguments[field] for field in _REQUIRED_FIELDS}, runner=runner)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mail_send_mcp_server.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass, no other file references `_send_via_jxa`.

- [ ] **Step 6: Commit**

```bash
git add src/project_os/ai/mail_send_mcp_server.py tests/test_mail_send_mcp_server.py
git commit -m "refactor: make send_via_jxa public so non-MCP callers can send approved replies"
```

---

### Task 4: `POST /actions/{id}/send` route

**Files:**
- Modify: `src/project_os/web/routes_action_center.py`
- Test: `tests/test_action_center_routes.py`

**Interfaces:**
- Consumes: `get_reply_context` (Task 1), `send_via_jxa`, `MailSendError` (Task 3), `create_interaction` (existing, `repositories/interactions.py`), `complete_action` (existing).
- Produces: `POST /actions/{action_id}/send` (form field `message: str`) — on success, redirects `303` to `/action-center`; on a send failure, redirects `303` to `/action-center?error=<url-encoded message>`; on an action with no valid reply context, returns `404`.

This task only adds the POST route's backend behavior. The Action Center page does not yet show the reply-draft form or the error banner — that's Task 5. This task's tests drive the route directly with `client.post(...)`, not by clicking a UI form.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_action_center_routes.py` — the file already has `from project_os.repositories.actions import create_action` at the top; change that line to:

```python
from project_os.repositories.actions import create_action, list_open_actions
```

And add these new import lines below it:

```python
from project_os.repositories.contacts import create_contact, link_contact_to_project
from project_os.repositories.interactions import create_interaction
from project_os.ai.mail_send_mcp_server import MailSendError
```

Add this helper after `_client`:

```python
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
```

Add these tests:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_action_center_routes.py -v -k sending_a_reply`
Expected: FAIL — `404 Not Found` for all three (the route doesn't exist yet).

- [ ] **Step 3: Add the route**

Replace `src/project_os/web/routes_action_center.py:1-5` with:

```python
from urllib.parse import quote

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse

from project_os.db import get_connection
from project_os.repositories.actions import list_open_actions, complete_action, snooze_action, get_reply_context
from project_os.repositories.interactions import create_interaction
from project_os.ai.mail_send_mcp_server import send_via_jxa, MailSendError
```

Append at the end of `src/project_os/web/routes_action_center.py`:

```python
@router.post("/actions/{action_id}/send")
def send_reply(request: Request, action_id: int, message: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    try:
        context = get_reply_context(conn, action_id)
        if context is None:
            raise HTTPException(status_code=404, detail=f"No sendable reply for action {action_id}")

        action_row = conn.execute(
            "SELECT project_id, linked_id FROM actions WHERE id = ?", (action_id,)
        ).fetchone()

        try:
            send_via_jxa({"to": context["to"], "subject": context["subject"], "body": message})
        except MailSendError as error:
            return RedirectResponse(
                url=f"/action-center?error={quote(str(error))}", status_code=303
            )

        conn.execute("BEGIN")
        try:
            complete_action(conn, action_id)
            create_interaction(
                conn, action_row["project_id"], action_row["linked_id"],
                channel="email", direction="outbound", subject=context["subject"],
                ai_summary=None, intent=None, external_message_id=None,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()
    return RedirectResponse(url="/action-center", status_code=303)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_action_center_routes.py -v`
Expected: PASS (all tests in the file, including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add src/project_os/web/routes_action_center.py tests/test_action_center_routes.py
git commit -m "feat: POST /actions/{id}/send sends an approved reply and closes the action"
```

---

### Task 5: Reply-draft UI and flash-error banner

**Files:**
- Modify: `src/project_os/web/routes_action_center.py:10-19` (`action_center` GET handler)
- Modify: `src/project_os/web/templates/action_center.html`
- Test: `tests/test_action_center_routes.py`

**Interfaces:**
- Consumes: `get_reply_context` (Task 1, already imported by Task 4's changes to `routes_action_center.py`), `_client_with_reply_action` (Task 4, test helper already in `tests/test_action_center_routes.py`).
- Produces: no new Python interface — the GET `/action-center` template context gains `reply_contexts: dict[int, dict | None]` and `error: str | None`, consumed only by `action_center.html`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_action_center_routes.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_action_center_routes.py -v -k "reply_draft or error_banner"`
Expected: FAIL — `"Reply draft" in response.text` is `False` (template doesn't render it yet), and the error-banner test fails the same way.

- [ ] **Step 3: Update the GET route to pass reply contexts and the error message**

Replace `src/project_os/web/routes_action_center.py:10-19` (the `action_center` function) with:

```python
@router.get("/action-center")
def action_center(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        actions = list_open_actions(conn)
        reply_contexts = {action["id"]: get_reply_context(conn, action["id"]) for action in actions}
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "action_center.html",
        {
            "actions": actions,
            "reply_contexts": reply_contexts,
            "error": request.query_params.get("error"),
        },
    )
```

- [ ] **Step 4: Update the template**

Replace `src/project_os/web/templates/action_center.html:3-4`:

```html
{% block content %}
<h2>Action Center</h2>
```

with:

```html
{% block content %}
{% if error %}
<p role="alert" class="flash-error">{{ error }}</p>
{% endif %}
<h2>Action Center</h2>
```

Replace `src/project_os/web/templates/action_center.html:25-34` (the whole `Action` `<td>`):

```html
      <td>
        <form method="post" action="/actions/{{ action['id'] }}/complete">
          <button type="submit">Done</button>
        </form>
        <form method="post" action="/actions/{{ action['id'] }}/snooze">
          <label for="snooze-{{ action['id'] }}" class="sr-only">New due date for {{ action["reason"] }}</label>
          <input type="date" id="snooze-{{ action['id'] }}" name="new_due_date" required>
          <button type="submit">Snooze</button>
        </form>
      </td>
```

with:

```html
      <td>
        <form method="post" action="/actions/{{ action['id'] }}/complete">
          <button type="submit">Done</button>
        </form>
        <form method="post" action="/actions/{{ action['id'] }}/snooze">
          <label for="snooze-{{ action['id'] }}" class="sr-only">New due date for {{ action["reason"] }}</label>
          <input type="date" id="snooze-{{ action['id'] }}" name="new_due_date" required>
          <button type="submit">Snooze</button>
        </form>
        {% set reply = reply_contexts.get(action['id']) %}
        {% if reply %}
        <details>
          <summary>Reply draft ▾</summary>
          <form method="post" action="/actions/{{ action['id'] }}/send">
            <label for="message-{{ action['id'] }}" class="sr-only">Reply text for {{ action["reason"] }}</label>
            <textarea id="message-{{ action['id'] }}" name="message" rows="6" required>{{ reply["body"] }}</textarea>
            <button type="submit">Approve &amp; Send</button>
          </form>
        </details>
        {% endif %}
      </td>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_action_center_routes.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass (98 from before this plan + 5 from Task 1 + 0 net-new from Task 2 (existing test extended) + 0 net-new from Task 3 (existing test modified) + 3 from Task 4 + 3 from Task 5 = 109).

- [ ] **Step 7: Commit**

```bash
git add src/project_os/web/routes_action_center.py src/project_os/web/templates/action_center.html tests/test_action_center_routes.py
git commit -m "feat: Action Center shows an editable reply draft and Approve & Send button"
```

---

## Self-Review Notes

- **Spec coverage:** migration + `source_interaction_id` (spec's Data Model section) → Task 1. `mail_sync` wiring → Task 2. `send_via_jxa` rename (spec's Backend section) → Task 3. `POST /actions/{id}/send` (spec's Backend section) → Task 4. Collapsible reply-draft UI + flash banner (spec's UI section) → Task 5. Testing section's four bullet points map one-to-one onto Tasks 1, 2, 3, and 4/5.
- **Explicitly out of scope for this plan** (per spec's Non-goals): calendar/scheduling, rich-text editing, changes to `mail_sync`'s classification/drafting prompt or validation logic.
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code including exact line ranges to replace.
- **Type consistency:** `get_reply_context` returns `dict | None` with keys `to`/`subject`/`body` consistently across Task 1 (definition), Task 4 (route consumes `context["to"]`, `context["subject"]`), and Task 5 (template consumes `reply["body"]`). `create_action`'s `source_interaction_id` parameter name matches the column name added in Task 1's migration and the value passed in Task 2. `send_via_jxa`'s signature (`payload: dict`, `runner` keyword) is unchanged by the Task 3 rename and used identically at both call sites (`mail_send_mcp_server.py`'s own `_send_message_result`, and Task 4's new route).
