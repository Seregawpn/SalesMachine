# Emails Inbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated, browsable "Emails" inbox page (list + detail, matching the app's existing two-pane pattern) over email interactions the system already collects, reusing the existing Approve & Send flow.

**Architecture:** One new repository query, one new route module (`routes_emails.py`) with two GET routes and a shared render helper, two new templates, a five-line addition to the existing `send_reply` route in `routes_action_center.py` to support redirecting/re-rendering back into the Emails page instead of Action Center. No schema changes, no new AI/backend integration.

**Tech Stack:** Python 3.13, FastAPI, Jinja2, sqlite3, pytest, htmx (vendored) — unchanged from the rest of the app.

## Global Constraints

- No new Python dependencies, no npm/build step.
- Every existing test in `tests/` must keep passing unmodified.
- `send_reply`'s existing behavior (Action Center htmx/non-htmx paths) must be byte-identical when the new `view` form field is absent — the new branch is strictly additive and opt-in.
- No raw email body storage, no Regenerate/Not-relevant buttons, no live Apple Mail query — per the design's explicit non-goals.
- CSS: reuse existing classes only (`.table-card`, `.feed`, `.feed-row`, `.feed-meta`, `.feed-line`, `.tag`, `.flash-error`, `.sr-only`) — no new CSS file changes.

---

### Task 1: `list_email_interactions` repository query

**Files:**
- Modify: `src/project_os/repositories/interactions.py`
- Test: `tests/test_interactions_repo.py`

**Interfaces:**
- Produces: `list_email_interactions(conn: sqlite3.Connection) -> list[sqlite3.Row]` — each row has all `interactions` columns plus `contact_name`, `project_name`, `open_action_id` (nullable), `draft_reply` (nullable, from `actions.suggested_message`). Ordered `created_at DESC, id DESC`. Consumed by Task 2's routes.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_interactions_repo.py` (the file already imports `create_project`, `create_contact`, `get_connection`, `run_migrations`, `MIGRATIONS_DIR`, and has a `_setup` helper returning `(conn, project_id, contact_id)` — reuse it):

```python
from project_os.repositories.interactions import list_email_interactions
from project_os.repositories.actions import create_action, complete_action


def test_list_email_interactions_filters_to_email_channel_only(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    email_id = create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Pricing question",
        ai_summary="Wants pricing.", intent="question", external_message_id="msg-1",
    )
    create_interaction(
        conn, project_id, contact_id,
        channel="linkedin", direction="inbound", subject=None,
        ai_summary=None, intent=None, external_message_id=None,
    )

    rows = list_email_interactions(conn)

    assert len(rows) == 1
    assert rows[0]["id"] == email_id
    assert rows[0]["contact_name"] == "Jane Smith"
    assert rows[0]["project_name"] == "Nexy"


def test_list_email_interactions_reports_open_action_and_draft(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    interaction_id = create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Pricing question",
        ai_summary="Wants pricing.", intent="question", external_message_id="msg-1",
    )
    action_id = create_action(
        conn, project_id, module="Sales", reason="Reply with pricing",
        linked_table="contacts", linked_id=contact_id,
        suggested_message="Here is our pricing.",
        source_interaction_id=interaction_id,
    )

    rows = list_email_interactions(conn)

    assert rows[0]["open_action_id"] == action_id
    assert rows[0]["draft_reply"] == "Here is our pricing."

    complete_action(conn, action_id)
    rows_after = list_email_interactions(conn)

    assert rows_after[0]["open_action_id"] is None
    assert rows_after[0]["draft_reply"] is None


def test_list_email_interactions_orders_most_recent_first(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    older = create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="First",
        ai_summary=None, intent=None, external_message_id=None,
        created_at="2026-08-01 00:00:00",
    )
    newer = create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="outbound", subject="Second",
        ai_summary=None, intent=None, external_message_id=None,
        created_at="2026-08-10 00:00:00",
    )

    rows = list_email_interactions(conn)

    assert [r["id"] for r in rows] == [newer, older]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_interactions_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'list_email_interactions'`

- [ ] **Step 3: Implement**

Append to `src/project_os/repositories/interactions.py`:

```python
def list_email_interactions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT i.*, c.name AS contact_name, p.name AS project_name,
               a.id AS open_action_id, a.suggested_message AS draft_reply
        FROM interactions i
        JOIN contacts c ON c.id = i.contact_id
        JOIN projects p ON p.id = i.project_id
        LEFT JOIN actions a ON a.source_interaction_id = i.id AND a.status = 'Open'
        WHERE i.channel = 'email'
        ORDER BY i.created_at DESC, i.id DESC
        """
    ).fetchall()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_interactions_repo.py -v`
Expected: PASS (all tests, including the 3 new ones)

- [ ] **Step 5: Run the full suite for regressions**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/repositories/interactions.py tests/test_interactions_repo.py
git commit -m "feat: add list_email_interactions repository query"
```

---

### Task 2: Emails page — routes, templates, nav

**Files:**
- Create: `src/project_os/web/routes_emails.py`
- Create: `src/project_os/web/templates/emails_index.html`
- Create: `src/project_os/web/templates/_email_detail.html`
- Modify: `src/project_os/web/templates/base.html`
- Modify: `src/project_os/web/app.py`
- Test: `tests/test_emails_routes.py`

**Interfaces:**
- Consumes: `list_email_interactions` (Task 1).
- Produces (used by Task 3): `render_email_detail(request: Request, conn, interaction_id: int) -> str`, a module-level function in `routes_emails.py` that renders `_email_detail.html` for one interaction. Task 3 imports this directly: `from project_os.web.routes_emails import render_email_detail`.
- The `_email_detail.html` partial expects one context variable, `selected` (an `sqlite3.Row` from `list_email_interactions`, or `None`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_emails_routes.py`:

```python
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
```

- [ ] **Step 2: Run tests to see them fail**

Run: `.venv/bin/python -m pytest tests/test_emails_routes.py -v`
Expected: FAIL — `404 Not Found` for `/emails` (route doesn't exist yet), and the nav-link test fails too

- [ ] **Step 3: Implement the route module**

Create `src/project_os/web/routes_emails.py`:

```python
from fastapi import APIRouter, HTTPException, Request

from project_os.db import get_connection
from project_os.repositories.interactions import list_email_interactions

router = APIRouter()


def _select(interactions: list, interaction_id: int | None):
    if interaction_id is None:
        return interactions[0] if interactions else None
    selected = next((i for i in interactions if i["id"] == interaction_id), None)
    if selected is None:
        raise HTTPException(status_code=404, detail=f"No email interaction with id {interaction_id}")
    return selected


def render_email_detail(request: Request, conn, interaction_id: int) -> str:
    interactions = list_email_interactions(conn)
    selected = _select(interactions, interaction_id)
    return request.app.state.templates.get_template("_email_detail.html").render(
        {"selected": selected}
    )


@router.get("/emails")
def emails_index(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        interactions = list_email_interactions(conn)
        selected = _select(interactions, None)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "emails_index.html",
        {"interactions": interactions, "selected": selected, "error": request.query_params.get("error")},
    )


@router.get("/emails/{interaction_id}")
def emails_show(request: Request, interaction_id: int):
    conn = get_connection(request.app.state.db_path)
    try:
        interactions = list_email_interactions(conn)
        selected = _select(interactions, interaction_id)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "emails_index.html",
        {"interactions": interactions, "selected": selected, "error": request.query_params.get("error")},
    )
```

- [ ] **Step 4: Create the templates**

Create `src/project_os/web/templates/_email_detail.html`:

```html
{% if selected %}
<div style="padding: 20px;">
  <div style="font-size: 20px; margin-bottom: 6px;">{{ selected["subject"] or "Unknown" }}</div>
  <div class="feed-meta" style="margin-bottom: 14px;">
    <span class="tag">{{ selected["direction"] }}</span>
    <span>{{ selected["contact_name"] }}</span>
    <span>{{ selected["project_name"] }}</span>
    <span style="margin-left: auto;">{{ selected["created_at"] }}</span>
  </div>
  {% if selected["ai_summary"] %}
  <div style="border-left: 2px solid var(--accent); padding: 2px 0 2px 14px; margin-bottom: 18px; color: var(--text-secondary);">
    <div class="tag" style="margin-bottom: 6px;">AI summary</div>
    <div>{{ selected["ai_summary"] }}</div>
  </div>
  {% endif %}
  {% if selected["open_action_id"] %}
  <form method="post" action="/actions/{{ selected['open_action_id'] }}/send"
        hx-post="/actions/{{ selected['open_action_id'] }}/send"
        hx-target="#email-detail" hx-swap="innerHTML">
    <input type="hidden" name="view" value="emails">
    <label for="message-{{ selected['id'] }}" class="sr-only">Reply text</label>
    <textarea id="message-{{ selected['id'] }}" name="message" rows="8" required style="width: 100%;">{{ selected["draft_reply"] }}</textarea>
    <button type="submit">Approve &amp; Send</button>
  </form>
  {% else %}
  <p style="color: var(--text-muted);">No action needed.</p>
  {% endif %}
</div>
{% else %}
<p style="padding: 20px; color: var(--text-muted);">No email selected.</p>
{% endif %}
```

Create `src/project_os/web/templates/emails_index.html`:

```html
{% extends "base.html" %}
{% block title %}Emails — Project OS{% endblock %}
{% block content %}
<p id="flash-banner" role="alert" class="flash-error"{% if not error %} hidden{% endif %}>{{ error or "" }}</p>
<h2>Emails</h2>
{% if interactions %}
<div style="display: grid; grid-template-columns: minmax(280px, 340px) 1fr; gap: 16px; align-items: start;">
  <div class="table-card">
    <div class="feed">
      {% for i in interactions %}
      <a href="/emails/{{ i['id'] }}" style="display: block; text-decoration: none; color: inherit;">
        <div class="feed-row"{% if selected and i['id'] == selected['id'] %} style="background: var(--row-alt-bg);"{% endif %}>
          <div class="feed-meta">
            <span class="tag">{{ i["direction"] }}</span>
            <span>{{ i["contact_name"] }}</span>
            <span style="margin-left: auto;">{{ i["created_at"] }}</span>
          </div>
          <div class="feed-line">{{ i["subject"] or "Unknown" }}</div>
        </div>
      </a>
      {% endfor %}
    </div>
  </div>
  <div class="table-card" id="email-detail">
    {% include "_email_detail.html" %}
  </div>
</div>
{% else %}
<p>No emails yet.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Add the nav link to `base.html`**

In `src/project_os/web/templates/base.html`, change:

```html
      <nav class="tabs" aria-label="Primary">
        <a href="/action-center">Action Center</a>
        <a href="/projects">Projects</a>
        <a href="/contacts">Contacts</a>
        <a href="/interactions">Interactions</a>
      </nav>
```

to:

```html
      <nav class="tabs" aria-label="Primary">
        <a href="/action-center">Action Center</a>
        <a href="/emails">Emails</a>
        <a href="/projects">Projects</a>
        <a href="/contacts">Contacts</a>
        <a href="/interactions">Interactions</a>
      </nav>
```

- [ ] **Step 6: Register the router in `app.py`**

In `src/project_os/web/app.py`, after the `interactions_router` block, add:

```python
    from project_os.web.routes_emails import router as emails_router
    app.include_router(emails_router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_emails_routes.py -v`
Expected: PASS (all 7 tests)

- [ ] **Step 8: Run the full suite for regressions**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS — `tests/test_base_layout.py` doesn't assert an exact/exhaustive nav-link count, only that the original 4 hrefs are present, so adding a 5th link doesn't break it (verify this assumption holds by reading its output, not just assuming).

- [ ] **Step 9: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/routes_emails.py src/project_os/web/templates/emails_index.html src/project_os/web/templates/_email_detail.html src/project_os/web/templates/base.html src/project_os/web/app.py tests/test_emails_routes.py
git commit -m "feat: add Emails inbox page (list + detail, read-only reply surfacing)"
```

---

### Task 3: Wire Approve & Send back into the Emails page

**Files:**
- Modify: `src/project_os/web/routes_action_center.py`
- Test: `tests/test_action_center_routes.py`

**Interfaces:**
- Consumes: `render_email_detail` from `routes_emails.py` (Task 2).
- No new interfaces produced — this task only extends `send_reply`'s existing behavior.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_action_center_routes.py`. The file already has a `_client_with_reply_action` helper (returns `(client, project_id, action_id)`) and imports `get_connection`. Add:

```python
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
```

- [ ] **Step 2: Run tests to see them fail**

Run: `.venv/bin/python -m pytest tests/test_action_center_routes.py -v -k view_emails`
Expected: FAIL — the third test (`without_view_field`) currently passes already (it matches today's behavior), but the first two fail since `view` is not yet read by the route.

- [ ] **Step 3: Implement**

Replace `send_reply` in `src/project_os/web/routes_action_center.py` with:

```python
@router.post("/actions/{action_id}/send")
def send_reply(request: Request, action_id: int, message: str = Form(...), view: str | None = Form(None)):
    conn = get_connection(request.app.state.db_path)
    is_hx = _is_hx(request)
    from_emails = view == "emails"
    try:
        context = get_reply_context(conn, action_id)
        if context is None:
            raise HTTPException(status_code=404, detail=f"No sendable reply for action {action_id}")

        action_row = conn.execute(
            "SELECT project_id, linked_id, source_interaction_id FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        redirect_url = f"/emails/{action_row['source_interaction_id']}" if from_emails else "/action-center"

        if not message.strip():
            if is_hx:
                response = HTMLResponse(_render_flash_banner(request, "Reply text cannot be empty."))
                response.headers["HX-Reswap"] = "none"
                return response
            return RedirectResponse(
                url=f"{redirect_url}?error=Reply text cannot be empty.", status_code=303
            )

        try:
            send_via_jxa({"to": context["to"], "subject": context["subject"], "body": message})
        except Exception as error:
            if is_hx:
                response = HTMLResponse(_render_flash_banner(request, str(error)))
                response.headers["HX-Reswap"] = "none"
                return response
            return RedirectResponse(
                url=f"{redirect_url}?error={quote(str(error))}", status_code=303
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

        if is_hx:
            if from_emails:
                return HTMLResponse(render_email_detail(request, conn, action_row["source_interaction_id"]))
            return HTMLResponse(_BANNER_RESET)
    finally:
        conn.close()
    return RedirectResponse(url=redirect_url, status_code=303)
```

Add the import at the top of the file, alongside the existing imports:

```python
from project_os.web.routes_emails import render_email_detail
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_action_center_routes.py -v`
Expected: PASS — every existing test in this file (the ones that never pass `view`) plus the 3 new ones.

- [ ] **Step 5: Run the full suite for regressions**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/routes_action_center.py tests/test_action_center_routes.py
git commit -m "feat: Approve & Send redirects/re-renders back into the Emails page when sent from there"
```

---

### Task 4: Verify against the running app

**Files:** none (verification-only task).

**Interfaces:** none.

- [ ] **Step 1: Run the full suite one more time**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS — every test in the repo.

- [ ] **Step 2: Start the app and visually verify**

```bash
cd /Users/sergiyzasorin/ProjectOS
python -m project_os.daemon &
```

This runs on `http://127.0.0.1:8765` (per `daemon.py:111`). If the LaunchAgent daemon is already running on this port, use it directly instead of starting a second instance — check with `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/emails` first.

Use the Browser tool to open `http://127.0.0.1:8765/emails`. Confirm: the "Emails" tab appears in the top nav between Action Center and Projects; the list column shows every email interaction currently in the DB (there should be real ones from the earlier Nexy import's `interactions` table); clicking a row selects it and shows the detail pane; for any email with an open action, the draft textarea and "Approve & Send" button appear — do not actually click Approve & Send against the real Mail.app unless you intend to send a real email; verify the button and form are present and correctly wired by inspecting the page, not by submitting it.

- [ ] **Step 3: Stop the dev server if you started one**

```bash
kill %1
```

(No commit — this task only verifies previously-committed code.)
