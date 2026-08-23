# CRM Design System & Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 6-line placeholder stylesheet and single-link nav with a real Dense & Functional / Charcoal & White design system, add the missing global Contacts and Interactions pages, and make key actions (Done/Snooze/Approve & Send/Pipeline stage/LinkedIn state) update in place via htmx instead of a full page reload — while keeping the app 100% functional with JS disabled.

**Architecture:** `htmx` (vendored, no CDN, no build step) is added to `base.html`; existing FastAPI routes gain an `if request.headers.get("hx-request") == "true":` branch that returns a small Jinja2 partial template instead of a `RedirectResponse` — the non-htmx path is byte-for-byte unchanged. A new CSS custom-property stylesheet replaces the old one. Two new read-only pages (Contacts, Interactions) are backed by two new repository functions over existing tables — no schema changes.

**Tech Stack:** FastAPI, Jinja2 (unchanged), htmx 1.9.12 (new, vendored static file), plain CSS custom properties (no preprocessor).

## Global Constraints

- No JavaScript framework, no `npm`, no build step — htmx is the only client-side script, vendored as a static file, not loaded from a CDN.
- Every htmx-enhanced route keeps its exact current non-htmx behavior (redirect, full page) as the default when the `HX-Request` header is absent — this is progressive enhancement, not a replacement.
- No schema changes. `list_contacts` and `list_interactions` are read-only queries over the existing `contacts`/`interactions`/`projects` tables.
- Pipeline and LinkedIn Queue are NOT promoted to the global sidebar — they stay reachable only from a project's own overview page, since they are project-scoped in the data model.
- No test spawns real Apple Mail/JXA/Codex — this plan touches web routes and templates only; existing test-isolation patterns (`monkeypatch.setattr` on `send_via_jxa`) are reused unchanged where relevant.

---

## File Structure

```
~/ProjectOS/
  src/project_os/
    repositories/
      contacts.py                          # modified: + list_contacts
      interactions.py                      # modified: + list_interactions
      opportunities.py                     # modified: + get_pipeline_row
    web/
      app.py                                # modified: register 2 new routers
      routes_contacts.py                    # new: GET /contacts
      routes_interactions.py                # new: GET /interactions
      routes_action_center.py               # modified: hx-request branches on complete/snooze/send
      routes_pipeline.py                    # modified: hx-request branch on stage change
      routes_linkedin.py                    # modified: hx-request branch on state change
      static/
        style.css                           # rewritten: design tokens, sidebar layout, dense tables, badges
        vendor/
          htmx.min.js                       # new: vendored htmx 1.9.12
      templates/
        base.html                           # modified: sidebar shell, htmx script tag, 2 new nav links
        action_center.html                  # modified: row markup extracted to _action_row.html, stable flash-banner id
        _action_row.html                    # new: partial, shared by full page and htmx responses
        _flash_banner.html                  # new: partial, OOB swap target for send failures
        pipeline.html                       # modified: row markup extracted to _pipeline_row.html
        _pipeline_row.html                  # new: partial
        linkedin_queue.html                 # modified: hx-* attributes added to existing forms
        contacts_index.html                 # new
        interactions_index.html             # new
  tests/
    test_base_layout.py                     # new
    test_contacts_repo.py                   # modified: + list_contacts test
    test_contacts_routes.py                 # new
    test_interactions_repo.py               # modified: + list_interactions test
    test_interactions_routes.py             # new
    test_action_center_routes.py            # modified: + hx-request tests
    test_pipeline_routes.py                 # modified: + hx-request test
    test_linkedin_routes.py                 # modified: + hx-request test
```

---

### Task 1: Design system foundation — vendor htmx, rewrite CSS, sidebar shell

**Files:**
- Create: `src/project_os/web/static/vendor/htmx.min.js`
- Modify: `src/project_os/web/static/style.css`
- Modify: `src/project_os/web/templates/base.html`
- Test: `tests/test_base_layout.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `base.html`'s sidebar nav gains 2 new links (`/contacts`, `/interactions` — routes don't exist until Tasks 2-3, that's fine, this task only adds the markup). CSS classes later tasks rely on: `.badge` + `.badge-p0`/`.badge-p1`/`.badge-p2`/`.badge-p3`, `.flash-error`, `.app-shell`/`.sidebar`/`.content`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_base_layout.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    conn.close()
    return TestClient(create_app(tmp_db_path))


def test_base_layout_loads_the_vendored_htmx_script(tmp_db_path):
    client = _client(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert '<script src="/static/vendor/htmx.min.js"></script>' in response.text


def test_base_layout_includes_all_four_nav_links(tmp_db_path):
    client = _client(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert 'href="/action-center"' in response.text
    assert 'href="/projects"' in response.text
    assert 'href="/contacts"' in response.text
    assert 'href="/interactions"' in response.text


def test_vendored_htmx_script_is_served_and_looks_like_htmx(tmp_db_path):
    client = _client(tmp_db_path)

    response = client.get("/static/vendor/htmx.min.js")

    assert response.status_code == 200
    assert "htmx" in response.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_base_layout.py -v`
Expected: FAIL — `'<script src="/static/vendor/htmx.min.js"></script>' in response.text` is `False` (script not in `base.html` yet), and `GET /static/vendor/htmx.min.js` returns 404 (file doesn't exist yet).

- [ ] **Step 3: Vendor htmx**

```bash
mkdir -p src/project_os/web/static/vendor
curl -sSL -o src/project_os/web/static/vendor/htmx.min.js https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js
```

Verify the download succeeded and looks like htmx:

```bash
head -c 200 src/project_os/web/static/vendor/htmx.min.js
```

Expected: output starts with something like `// htmx 0.0.0` or minified JS containing the string `htmx` — if the command fails or the file is empty/HTML (e.g. an error page), stop and report rather than committing a broken asset.

- [ ] **Step 4: Rewrite `style.css`**

Replace the entire contents of `src/project_os/web/static/style.css`:

```css
:root {
  --sidebar-bg: #18181b;
  --sidebar-fg: #d4d4d8;
  --sidebar-active-bg: #27272a;
  --sidebar-active-fg: #ffffff;
  --content-bg: #ffffff;
  --row-alt-bg: #f4f4f5;
  --border: #d4d4d8;
  --text-primary: #18181b;
  --text-secondary: #71717a;
  --badge-p0-bg: #fee2e2;
  --badge-p0-fg: #b91c1c;
  --badge-p1-bg: #fef3c7;
  --badge-p1-fg: #92400e;
  --badge-p2-bg: #e0e7ff;
  --badge-p2-fg: #3730a3;
  --badge-p3-bg: #f4f4f5;
  --badge-p3-fg: #52525b;
  --error-bg: #fee2e2;
  --error-fg: #b91c1c;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* { box-sizing: border-box; }

body {
  font-family: var(--font-sans);
  margin: 0;
  color: var(--text-primary);
  background: var(--content-bg);
  font-size: 14px;
}

.app-shell { display: flex; min-height: 100vh; align-items: stretch; }

.sidebar {
  width: 200px;
  flex-shrink: 0;
  background: var(--sidebar-bg);
  color: var(--sidebar-fg);
  padding: 1rem 0.75rem;
}

.sidebar h1 {
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #fff;
  margin: 0 0 1rem 0.5rem;
}

.sidebar nav { display: flex; flex-direction: column; gap: 2px; }

.sidebar nav a {
  display: block;
  padding: 0.4rem 0.5rem;
  border-radius: 4px;
  color: var(--sidebar-fg);
  text-decoration: none;
  font-size: 0.85rem;
}

.sidebar nav a:hover {
  background: var(--sidebar-active-bg);
  color: var(--sidebar-active-fg);
}

.content { flex: 1; padding: 1.25rem 1.5rem; min-width: 0; }

h2 { font-size: 1.15rem; margin: 0 0 1rem; }
h3 { font-size: 0.95rem; margin: 1.25rem 0 0.5rem; }

table { border-collapse: collapse; width: 100%; font-size: 0.85rem; }
th, td { padding: 0.4rem 0.6rem; text-align: left; border-bottom: 1px solid var(--border); }
th {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--text-secondary);
  font-weight: 600;
}
tbody tr:nth-child(even) { background: var(--row-alt-bg); }

.badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 0.7rem;
  font-weight: 700;
}
.badge-p0 { background: var(--badge-p0-bg); color: var(--badge-p0-fg); }
.badge-p1 { background: var(--badge-p1-bg); color: var(--badge-p1-fg); }
.badge-p2 { background: var(--badge-p2-bg); color: var(--badge-p2-fg); }
.badge-p3 { background: var(--badge-p3-bg); color: var(--badge-p3-fg); }

.flash-error {
  background: var(--error-bg);
  color: var(--error-fg);
  padding: 0.5rem 0.75rem;
  border-radius: 4px;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.skip-link { position: absolute; left: -9999px; }
.skip-link:focus { left: 0.5rem; top: 0.5rem; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
```

- [ ] **Step 5: Rewrite `base.html`**

Replace the entire contents of `src/project_os/web/templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{% block title %}Project OS{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/vendor/htmx.min.js"></script>
</head>
<body>
  <a href="#main" class="skip-link">Skip to main content</a>
  <div class="app-shell">
    <aside class="sidebar">
      <h1>Project OS</h1>
      <nav aria-label="Primary">
        <a href="/action-center">Action Center</a>
        <a href="/projects">Projects</a>
        <a href="/contacts">Contacts</a>
        <a href="/interactions">Interactions</a>
      </nav>
    </aside>
    <main id="main" class="content">
      {% block content %}{% endblock %}
    </main>
  </div>
</body>
</html>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_base_layout.py -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all previously-passing tests still pass. Some existing tests assert on old markup that no longer exists (e.g. a bare `<header>` tag, if any test checked for it) — if any fail here, read the failure: if it's asserting on structure this task deliberately changed (not content/data), that's an expected, acceptable break to note in the task report, not a bug to silently work around.

- [ ] **Step 8: Commit**

```bash
git add src/project_os/web/static/vendor/htmx.min.js src/project_os/web/static/style.css src/project_os/web/templates/base.html tests/test_base_layout.py
git commit -m "feat: Dense & Functional / Charcoal & White design system, vendor htmx"
```

---

### Task 2: Global Contacts page

**Files:**
- Modify: `src/project_os/repositories/contacts.py` (append `list_contacts`)
- Create: `src/project_os/web/routes_contacts.py`
- Create: `src/project_os/web/templates/contacts_index.html`
- Modify: `src/project_os/web/app.py` (register the new router)
- Test: `tests/test_contacts_repo.py` (append), `tests/test_contacts_routes.py` (new)

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `list_contacts(conn: sqlite3.Connection) -> list[sqlite3.Row]`. `GET /contacts`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_contacts_repo.py` (add `list_contacts` to the existing import line from `project_os.repositories.contacts`):

```python
def test_list_contacts_returns_every_contact_ordered_by_name(tmp_db_path):
    conn = _conn(tmp_db_path)
    create_contact(conn, "Zed Adams", email="zed@example.org")
    create_contact(conn, "Anna Baker", email="anna@example.org")

    contacts = list_contacts(conn)

    assert [c["name"] for c in contacts] == ["Anna Baker", "Zed Adams"]
```

Create `tests/test_contacts_routes.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.contacts import create_contact

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    create_contact(conn, "Jane Smith", email="jane@example.org")
    conn.close()
    return TestClient(create_app(tmp_db_path))


def test_contacts_index_lists_every_contact(tmp_db_path):
    client = _client(tmp_db_path)

    response = client.get("/contacts")

    assert response.status_code == 200
    assert "Jane Smith" in response.text
    assert "jane@example.org" in response.text


def test_contacts_index_shows_a_message_when_there_are_no_contacts(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    conn.close()
    client = TestClient(create_app(tmp_db_path))

    response = client.get("/contacts")

    assert response.status_code == 200
    assert "No contacts yet." in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_contacts_repo.py tests/test_contacts_routes.py -v`
Expected: FAIL — `ImportError: cannot import name 'list_contacts'`, and `404 Not Found` for `GET /contacts`.

- [ ] **Step 3: Add `list_contacts`**

Append to `src/project_os/repositories/contacts.py`:

```python
def list_contacts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()
```

- [ ] **Step 4: Create the route**

Create `src/project_os/web/routes_contacts.py`:

```python
from fastapi import APIRouter, Request

from project_os.db import get_connection
from project_os.repositories.contacts import list_contacts

router = APIRouter()


@router.get("/contacts")
def contacts_index(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        contacts = list_contacts(conn)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "contacts_index.html", {"contacts": contacts}
    )
```

- [ ] **Step 5: Create the template**

Create `src/project_os/web/templates/contacts_index.html`:

```html
{% extends "base.html" %}
{% block title %}Contacts — Project OS{% endblock %}
{% block content %}
<h2>Contacts</h2>
<table>
  <caption class="sr-only">All contacts across every project</caption>
  <thead>
    <tr>
      <th scope="col">Name</th>
      <th scope="col">Email</th>
      <th scope="col">LinkedIn</th>
    </tr>
  </thead>
  <tbody>
    {% for contact in contacts %}
    <tr>
      <td>{{ contact["name"] }}</td>
      <td>{{ contact["email"] or "Unknown" }}</td>
      <td>
        {% if contact["linkedin_url"] %}
        <a href="{{ contact['linkedin_url'] }}">Profile</a>
        {% else %}
        Unknown
        {% endif %}
      </td>
    </tr>
    {% else %}
    <tr><td colspan="3">No contacts yet.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 6: Register the router**

In `src/project_os/web/app.py`, add alongside the other router registrations (after the `linkedin_router` block):

```python
    from project_os.web.routes_contacts import router as contacts_router
    app.include_router(contacts_router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_contacts_repo.py tests/test_contacts_routes.py -v`
Expected: PASS (all tests in both files)

- [ ] **Step 8: Commit**

```bash
git add src/project_os/repositories/contacts.py src/project_os/web/routes_contacts.py src/project_os/web/templates/contacts_index.html src/project_os/web/app.py tests/test_contacts_repo.py tests/test_contacts_routes.py
git commit -m "feat: global Contacts page"
```

---

### Task 3: Global Interactions feed

**Files:**
- Modify: `src/project_os/repositories/interactions.py` (append `list_interactions`)
- Create: `src/project_os/web/routes_interactions.py`
- Create: `src/project_os/web/templates/interactions_index.html`
- Modify: `src/project_os/web/app.py` (register the new router)
- Test: `tests/test_interactions_repo.py` (append), `tests/test_interactions_routes.py` (new)

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `list_interactions(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]`, each row carrying `contact_name` and `project_name` in addition to the `interactions` table's own columns. `GET /interactions`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_interactions_repo.py` (add `list_interactions` to the existing import line, and `from project_os.repositories.projects import create_project` is already imported):

```python
def test_list_interactions_returns_most_recent_first_with_contact_and_project_names(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="First",
        ai_summary=None, intent=None, external_message_id="1",
    )
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="outbound", subject="Second",
        ai_summary=None, intent=None, external_message_id="2",
    )

    interactions = list_interactions(conn)

    assert [i["subject"] for i in interactions] == ["Second", "First"]
    assert interactions[0]["contact_name"] == "Jane Smith"
    assert interactions[0]["project_name"] == "Nexy"


def test_list_interactions_respects_the_limit(tmp_db_path):
    conn, project_id, contact_id = _setup(tmp_db_path)
    for i in range(3):
        create_interaction(
            conn, project_id, contact_id,
            channel="email", direction="inbound", subject=f"Message {i}",
            ai_summary=None, intent=None, external_message_id=str(i),
        )

    interactions = list_interactions(conn, limit=2)

    assert len(interactions) == 2
```

Create `tests/test_interactions_routes.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact
from project_os.repositories.interactions import create_interaction

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Re: pricing",
        ai_summary="Interested.", intent="positive", external_message_id="1",
    )
    conn.close()
    return TestClient(create_app(tmp_db_path))


def test_interactions_index_lists_recent_interactions(tmp_db_path):
    client = _client(tmp_db_path)

    response = client.get("/interactions")

    assert response.status_code == 200
    assert "Re: pricing" in response.text
    assert "Jane Smith" in response.text
    assert "Nexy" in response.text


def test_interactions_index_shows_a_message_when_there_are_none(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    conn.close()
    client = TestClient(create_app(tmp_db_path))

    response = client.get("/interactions")

    assert response.status_code == 200
    assert "No interactions yet." in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_interactions_repo.py tests/test_interactions_routes.py -v`
Expected: FAIL — `ImportError: cannot import name 'list_interactions'`, and `404 Not Found` for `GET /interactions`.

- [ ] **Step 3: Add `list_interactions`**

Append to `src/project_os/repositories/interactions.py`:

```python
def list_interactions(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT i.*, c.name AS contact_name, p.name AS project_name
        FROM interactions i
        JOIN contacts c ON c.id = i.contact_id
        JOIN projects p ON p.id = i.project_id
        ORDER BY i.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
```

- [ ] **Step 4: Create the route**

Create `src/project_os/web/routes_interactions.py`:

```python
from fastapi import APIRouter, Request

from project_os.db import get_connection
from project_os.repositories.interactions import list_interactions

router = APIRouter()


@router.get("/interactions")
def interactions_index(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        interactions = list_interactions(conn)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "interactions_index.html", {"interactions": interactions}
    )
```

- [ ] **Step 5: Create the template**

Create `src/project_os/web/templates/interactions_index.html`:

```html
{% extends "base.html" %}
{% block title %}Interactions — Project OS{% endblock %}
{% block content %}
<h2>Interactions</h2>
<table>
  <caption class="sr-only">Most recent communication across every project</caption>
  <thead>
    <tr>
      <th scope="col">Date</th>
      <th scope="col">Contact</th>
      <th scope="col">Project</th>
      <th scope="col">Channel</th>
      <th scope="col">Direction</th>
      <th scope="col">Subject</th>
    </tr>
  </thead>
  <tbody>
    {% for interaction in interactions %}
    <tr>
      <td>{{ interaction["created_at"] }}</td>
      <td>{{ interaction["contact_name"] }}</td>
      <td>{{ interaction["project_name"] }}</td>
      <td>{{ interaction["channel"] }}</td>
      <td>{{ interaction["direction"] }}</td>
      <td>{{ interaction["subject"] or "Unknown" }}</td>
    </tr>
    {% else %}
    <tr><td colspan="6">No interactions yet.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 6: Register the router**

In `src/project_os/web/app.py`, add alongside the other router registrations:

```python
    from project_os.web.routes_interactions import router as interactions_router
    app.include_router(interactions_router)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_interactions_repo.py tests/test_interactions_routes.py -v`
Expected: PASS (all tests in both files)

- [ ] **Step 8: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/project_os/repositories/interactions.py src/project_os/web/routes_interactions.py src/project_os/web/templates/interactions_index.html src/project_os/web/app.py tests/test_interactions_repo.py tests/test_interactions_routes.py
git commit -m "feat: global Interactions feed"
```

---

### Task 4: htmx for Action Center (complete, snooze, send)

**Files:**
- Create: `src/project_os/web/templates/_action_row.html`
- Create: `src/project_os/web/templates/_flash_banner.html`
- Modify: `src/project_os/web/templates/action_center.html`
- Modify: `src/project_os/web/routes_action_center.py`
- Test: `tests/test_action_center_routes.py`

**Interfaces:**
- Consumes: `get_reply_context`, `complete_action`, `snooze_action`, `send_via_jxa`, `create_interaction` (all pre-existing, unchanged signatures).
- Produces: `_action_row.html` (partial, context: `action`, `reply_contexts` — a `{action_id: dict|None}` map, matching what the full-page route already builds), `_flash_banner.html` (partial, context: `error`). Both are shared by the full-page render (via `{% include %}`) and the htmx partial responses, so the row markup exists in exactly one place.

This is the task with the most moving parts — read the whole task before starting, since the `send` route's htmx and non-htmx failure paths interleave.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_action_center_routes.py`:

```python
def test_completing_an_action_via_hx_request_returns_an_empty_fragment(tmp_db_path):
    client, project_id = _client(tmp_db_path)
    conn = get_connection(tmp_db_path)
    row = conn.execute("SELECT id FROM actions LIMIT 1").fetchone()
    conn.close()

    response = client.post(f"/actions/{row['id']}/complete", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert response.text == ""


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
    assert response.text == ""


def test_sending_a_reply_via_hx_request_returns_row_and_oob_banner_on_failure(tmp_db_path, monkeypatch):
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
    assert f'id="action-row-{action_id}"' in response.text
    assert 'hx-swap-oob="true"' in response.text
    assert "Mail is not configured." in response.text
    conn = get_connection(tmp_db_path)
    assert len(list_open_actions(conn, project_id)) == 1
    conn.close()


def test_sending_a_blank_reply_via_hx_request_returns_row_and_oob_banner(tmp_db_path):
    client, project_id, action_id = _client_with_reply_action(tmp_db_path)

    response = client.post(
        f"/actions/{action_id}/send",
        data={"message": "   "},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert 'hx-swap-oob="true"' in response.text
    assert "Reply text cannot be empty." in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_action_center_routes.py -v -k hx_request`
Expected: FAIL — non-htmx redirect responses returned instead (status `303`, not `200`; empty-fragment/partial assertions fail).

- [ ] **Step 3: Create `_action_row.html`**

Create `src/project_os/web/templates/_action_row.html`:

```html
<tr id="action-row-{{ action['id'] }}">
  <td><span class="badge badge-{{ action['priority']|lower }}">{{ action["priority"] }}</span></td>
  <td><a href="/projects/{{ action['project_id'] }}">Project {{ action['project_id'] }}</a></td>
  <td>{{ action["module"] }}</td>
  <td>{{ action["reason"] }}</td>
  <td>{{ action["due_date"] or "Unknown" }}</td>
  <td>
    <form method="post" action="/actions/{{ action['id'] }}/complete"
          hx-post="/actions/{{ action['id'] }}/complete"
          hx-target="#action-row-{{ action['id'] }}" hx-swap="outerHTML swap:0.2s">
      <button type="submit">Done</button>
    </form>
    <form method="post" action="/actions/{{ action['id'] }}/snooze"
          hx-post="/actions/{{ action['id'] }}/snooze"
          hx-target="#action-row-{{ action['id'] }}" hx-swap="outerHTML">
      <label for="snooze-{{ action['id'] }}" class="sr-only">New due date for {{ action["reason"] }}</label>
      <input type="date" id="snooze-{{ action['id'] }}" name="new_due_date" required>
      <button type="submit">Snooze</button>
    </form>
    {% set reply = reply_contexts.get(action['id']) %}
    {% if reply %}
    <details>
      <summary>Reply draft ▾</summary>
      <form method="post" action="/actions/{{ action['id'] }}/send"
            hx-post="/actions/{{ action['id'] }}/send"
            hx-target="#action-row-{{ action['id'] }}" hx-swap="outerHTML swap:0.2s">
        <label for="message-{{ action['id'] }}" class="sr-only">Reply text for {{ action["reason"] }}</label>
        <textarea id="message-{{ action['id'] }}" name="message" rows="6" required>{{ reply["body"] }}</textarea>
        <button type="submit">Approve &amp; Send</button>
      </form>
    </details>
    {% endif %}
  </td>
</tr>
```

- [ ] **Step 4: Create `_flash_banner.html`**

Create `src/project_os/web/templates/_flash_banner.html`:

```html
<p id="flash-banner" role="alert" class="flash-error" hx-swap-oob="true">{{ error }}</p>
```

- [ ] **Step 5: Update `action_center.html`**

Replace the entire contents of `src/project_os/web/templates/action_center.html`:

```html
{% extends "base.html" %}
{% block title %}Action Center — Project OS{% endblock %}
{% block content %}
<p id="flash-banner" role="alert" class="flash-error"{% if not error %} hidden{% endif %}>{{ error or "" }}</p>
<h2>Action Center</h2>
<table>
  <caption class="sr-only">Open actions across all projects</caption>
  <thead>
    <tr>
      <th scope="col">Priority</th>
      <th scope="col">Project</th>
      <th scope="col">Area</th>
      <th scope="col">Reason</th>
      <th scope="col">Due</th>
      <th scope="col">Action</th>
    </tr>
  </thead>
  <tbody>
    {% for action in actions %}
    {% include "_action_row.html" %}
    {% else %}
    <tr><td colspan="6">Nothing needs attention right now.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 6: Update `routes_action_center.py`**

Replace `src/project_os/web/routes_action_center.py` in full:

```python
from urllib.parse import quote

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from project_os.db import get_connection
from project_os.repositories.actions import list_open_actions, complete_action, snooze_action, get_reply_context
from project_os.repositories.interactions import create_interaction
from project_os.ai.mail_send_mcp_server import send_via_jxa, MailSendError

router = APIRouter()


def _is_hx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def _render_action_row(request: Request, conn, action_id: int):
    action_row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
    reply = get_reply_context(conn, action_id)
    return request.app.state.templates.get_template("_action_row.html").render(
        {"action": action_row, "reply_contexts": {action_id: reply}}
    )


def _render_flash_banner(request: Request, error_message: str) -> str:
    return request.app.state.templates.get_template("_flash_banner.html").render({"error": error_message})


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


@router.post("/actions/{action_id}/complete")
def complete(request: Request, action_id: int):
    conn = get_connection(request.app.state.db_path)
    try:
        complete_action(conn, action_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()
    if _is_hx(request):
        return HTMLResponse("")
    return RedirectResponse(url="/action-center", status_code=303)


@router.post("/actions/{action_id}/snooze")
def snooze(request: Request, action_id: int, new_due_date: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    try:
        snooze_action(conn, action_id, new_due_date)
        if _is_hx(request):
            return HTMLResponse(_render_action_row(request, conn, action_id))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()
    return RedirectResponse(url="/action-center", status_code=303)


@router.post("/actions/{action_id}/send")
def send_reply(request: Request, action_id: int, message: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    is_hx = _is_hx(request)
    try:
        context = get_reply_context(conn, action_id)
        if context is None:
            raise HTTPException(status_code=404, detail=f"No sendable reply for action {action_id}")

        if not message.strip():
            if is_hx:
                return HTMLResponse(
                    _render_action_row(request, conn, action_id)
                    + _render_flash_banner(request, "Reply text cannot be empty.")
                )
            return RedirectResponse(
                url="/action-center?error=Reply text cannot be empty.", status_code=303
            )

        action_row = conn.execute(
            "SELECT project_id, linked_id FROM actions WHERE id = ?", (action_id,)
        ).fetchone()

        try:
            send_via_jxa({"to": context["to"], "subject": context["subject"], "body": message})
        except Exception as error:
            if is_hx:
                return HTMLResponse(
                    _render_action_row(request, conn, action_id)
                    + _render_flash_banner(request, str(error))
                )
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

        if is_hx:
            return HTMLResponse("")
    finally:
        conn.close()
    return RedirectResponse(url="/action-center", status_code=303)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_action_center_routes.py -v`
Expected: PASS (all tests in the file, including the 5 new ones)

- [ ] **Step 8: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass — the non-htmx tests from the Approve & Send plan (redirect-based) must still pass unchanged, since `_is_hx(request)` is `False` for them.

- [ ] **Step 9: Commit**

```bash
git add src/project_os/web/templates/_action_row.html src/project_os/web/templates/_flash_banner.html src/project_os/web/templates/action_center.html src/project_os/web/routes_action_center.py tests/test_action_center_routes.py
git commit -m "feat: Action Center actions update in place via htmx"
```

---

### Task 5: htmx for Pipeline stage changes

**Files:**
- Modify: `src/project_os/repositories/opportunities.py` (append `get_pipeline_row`)
- Create: `src/project_os/web/templates/_pipeline_row.html`
- Modify: `src/project_os/web/templates/pipeline.html`
- Modify: `src/project_os/web/routes_pipeline.py`
- Test: `tests/test_pipeline_routes.py`

**Interfaces:**
- Consumes: `update_stage`, `STAGES` (pre-existing, unchanged).
- Produces: `get_pipeline_row(conn: sqlite3.Connection, opportunity_id: int) -> sqlite3.Row | None` (same `organization_name`/`contact_name` join shape as `list_pipeline`'s rows, for exactly one opportunity). `_pipeline_row.html` (partial, context: `opp`, `project_id`, `stages`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline_routes.py`:

```python
def test_changing_stage_via_hx_request_returns_the_updated_row_partial(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/pipeline/{opp_id}/stage",
        data={"stage": "Negotiation"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "<html" not in response.text
    assert f'id="pipeline-row-{opp_id}"' in response.text
    assert 'selected' in response.text
    assert "Negotiation" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline_routes.py -v -k hx_request`
Expected: FAIL — response is a 303 redirect, not a 200 fragment.

- [ ] **Step 3: Add `get_pipeline_row`**

Append to `src/project_os/repositories/opportunities.py`:

```python
def get_pipeline_row(conn: sqlite3.Connection, opportunity_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT o.*, org.name AS organization_name, c.name AS contact_name
        FROM opportunities o
        LEFT JOIN organizations org ON org.id = o.organization_id
        LEFT JOIN contacts c ON c.id = o.contact_id
        WHERE o.id = ?
        """,
        (opportunity_id,),
    ).fetchone()
```

- [ ] **Step 4: Create `_pipeline_row.html`**

Create `src/project_os/web/templates/_pipeline_row.html`:

```html
<tr id="pipeline-row-{{ opp['id'] }}">
  <td>{{ opp["organization_name"] or "Unknown" }}</td>
  <td>{{ opp["contact_name"] or "Unknown" }}</td>
  <td>
    <form method="post" action="/projects/{{ project_id }}/pipeline/{{ opp['id'] }}/stage"
          hx-post="/projects/{{ project_id }}/pipeline/{{ opp['id'] }}/stage"
          hx-target="#pipeline-row-{{ opp['id'] }}" hx-swap="outerHTML">
      <label for="stage-{{ opp['id'] }}" class="sr-only">Stage for {{ opp["organization_name"] or "Unknown" }}</label>
      <select id="stage-{{ opp['id'] }}" name="stage">
        {% for stage in stages %}
        <option value="{{ stage }}" {% if stage == opp["stage"] %}selected{% endif %}>{{ stage }}</option>
        {% endfor %}
      </select>
      <button type="submit">Update stage</button>
    </form>
  </td>
  <td>{{ opp["value"] or "Unknown" }}</td>
  <td>{{ opp["blocker"] or "None" }}</td>
  <td>{{ opp["next_action"] or "Unknown" }}</td>
  <td>{{ opp["next_action_due"] or "Unknown" }}</td>
</tr>
```

- [ ] **Step 5: Update `pipeline.html`**

Replace `src/project_os/web/templates/pipeline.html` in full:

```html
{% extends "base.html" %}
{% block title %}Pipeline — Project OS{% endblock %}
{% block content %}
<h2>Pipeline</h2>
<table>
  <caption class="sr-only">Opportunities grouped by stage</caption>
  <thead>
    <tr>
      <th scope="col">Organization</th>
      <th scope="col">Contact</th>
      <th scope="col">Stage</th>
      <th scope="col">Value</th>
      <th scope="col">Blocker</th>
      <th scope="col">Next action</th>
      <th scope="col">Due</th>
    </tr>
  </thead>
  <tbody>
    {% for opp in opportunities %}
    {% include "_pipeline_row.html" %}
    {% else %}
    <tr><td colspan="7">No opportunities yet.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 6: Update `routes_pipeline.py`**

Replace `src/project_os/web/routes_pipeline.py` in full:

```python
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse

from project_os.db import get_connection
from project_os.repositories.opportunities import list_pipeline, update_stage, get_pipeline_row
from project_os.pipeline import STAGES

router = APIRouter()


@router.get("/projects/{project_id}/pipeline")
def pipeline(request: Request, project_id: int):
    conn = get_connection(request.app.state.db_path)
    try:
        opportunities = list_pipeline(conn, project_id)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request,
        "pipeline.html",
        {"project_id": project_id, "opportunities": opportunities, "stages": STAGES},
    )


@router.post("/projects/{project_id}/pipeline/{opportunity_id}/stage")
def change_stage(request: Request, project_id: int, opportunity_id: int, stage: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    try:
        update_stage(conn, opportunity_id, stage, project_id=project_id, actor="user")
        if request.headers.get("hx-request") == "true":
            opp = get_pipeline_row(conn, opportunity_id)
            return request.app.state.templates.TemplateResponse(
                request, "_pipeline_row.html",
                {"opp": opp, "project_id": project_id, "stages": STAGES},
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()
    return RedirectResponse(url=f"/projects/{project_id}/pipeline", status_code=303)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline_routes.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 8: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/project_os/repositories/opportunities.py src/project_os/web/templates/_pipeline_row.html src/project_os/web/templates/pipeline.html src/project_os/web/routes_pipeline.py tests/test_pipeline_routes.py
git commit -m "feat: Pipeline stage changes update in place via htmx"
```

---

### Task 6: htmx for LinkedIn Queue state changes

**Files:**
- Modify: `src/project_os/web/templates/linkedin_queue.html`
- Modify: `src/project_os/web/routes_linkedin.py`
- Test: `tests/test_linkedin_routes.py`

**Interfaces:**
- Consumes: `set_linkedin_state` (pre-existing, unchanged).
- Produces: no new function — this task only adds an `hx-request` branch to the existing route.

A LinkedIn state change conceptually moves a contact from one section of the page (e.g. "To connect") to another (e.g. "Pending connections") — correctly re-rendering that move via a single-row htmx swap would require knowing which section the row is moving *to*, which the current per-section template structure doesn't cleanly support. This task deliberately keeps it simple, matching the "Done" pattern from Action Center: on success, the row disappears from its current section (via an empty-fragment swap on `hx-target="closest tr"`); the user sees it's gone from where it was and can trust it reappeared in the right place on next full page load. Do not attempt to render the row in its destination section — that's out of scope for this task.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_linkedin_routes.py`. The existing `_client(tmp_db_path)` helper already returns `(client, project_id, pc_id)` — reuse it exactly as the other tests in this file do:

```python
def test_changing_linkedin_state_via_hx_request_returns_an_empty_fragment(tmp_db_path):
    client, project_id, pc_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/linkedin/{pc_id}/state",
        data={"state": "Pending Connection"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert response.text == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_linkedin_routes.py -v -k hx_request`
Expected: FAIL — response is a 303 redirect, not a 200 empty fragment.

- [ ] **Step 3: Update `routes_linkedin.py`**

Replace `src/project_os/web/routes_linkedin.py` in full:

```python
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from project_os.db import get_connection
from project_os.repositories.linkedin import list_linkedin_queue, set_linkedin_state

router = APIRouter()


@router.get("/projects/{project_id}/linkedin")
def linkedin_queue(request: Request, project_id: int):
    conn = get_connection(request.app.state.db_path)
    try:
        queue = list_linkedin_queue(conn, project_id)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request,
        "linkedin_queue.html",
        {"project_id": project_id, "queue": queue},
    )


@router.post("/projects/{project_id}/linkedin/{project_contact_id}/state")
def update_linkedin_state(request: Request, project_id: int, project_contact_id: int, state: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    try:
        set_linkedin_state(conn, project_contact_id, state, project_id=project_id, actor="user")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()
    if request.headers.get("hx-request") == "true":
        return HTMLResponse("")
    return RedirectResponse(url=f"/projects/{project_id}/linkedin", status_code=303)
```

- [ ] **Step 4: Add `hx-post`/`hx-target`/`hx-swap` to every form in `linkedin_queue.html`**

In `src/project_os/web/templates/linkedin_queue.html`, each of the 5 `<form method="post" action="...">` elements gets the same three attributes added (keep the existing `action=` attribute for the non-JS fallback path — do not remove it):

```html
hx-post="{{ same URL as the action attribute }}" hx-target="closest tr" hx-swap="outerHTML swap:0.2s"
```

Concretely, each form tag changes from e.g.:

```html
<form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state">
  <input type="hidden" name="state" value="Pending Connection">
  <button type="submit">Connection sent</button>
</form>
```

to:

```html
<form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
      hx-post="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
      hx-target="closest tr" hx-swap="outerHTML swap:0.2s">
  <input type="hidden" name="state" value="Pending Connection">
  <button type="submit">Connection sent</button>
</form>
```

Apply this identically to all 5 forms in the file (the single-button forms in "To connect" / "Accepted connections awaiting a message" / "Conversations awaiting reply" sections, and both buttons in the "Pending connections to re-check" section) — each form's `hx-post` URL matches its own already-existing `action` URL exactly.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_linkedin_routes.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `.venv/bin/python -m pytest -v`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/project_os/web/templates/linkedin_queue.html src/project_os/web/routes_linkedin.py tests/test_linkedin_routes.py
git commit -m "feat: LinkedIn Queue state changes update in place via htmx"
```

---

## Self-Review Notes

- **Spec coverage:** Visual direction (Dense & Functional / Charcoal & White) → Task 1's CSS. htmx architecture, vendoring → Task 1. Navigation (Contacts, Interactions added; Pipeline/LinkedIn deliberately NOT globalized) → Task 1 (nav links) + Tasks 2-3 (the pages themselves). htmx interactivity table from the spec → Tasks 4-6, one row of that table per task grouping (Action Center's 3 routes in Task 4, Pipeline in Task 5, LinkedIn in Task 6). Testing approach (non-htmx path unchanged, `HX-Request` header tests, repo tests for the two new listing queries) → present in every task.
- **Explicitly out of scope, per the design spec:** promoting Pipeline/LinkedIn to global nav, search/filtering on Contacts/Interactions, a metrics dashboard home page, any change to `mail_sync` or the schema.
- **Placeholder scan:** no TBD/TODO; every step has exact, runnable code, including the exact `curl` command and URL for vendoring htmx (already verified reachable before writing this plan).
- **Type consistency:** `get_reply_context`'s return shape (`{"to", "subject", "body"}` or `None`) is used identically in Task 4's `_render_action_row` helper and `_action_row.html`'s `{% set reply = reply_contexts.get(action['id']) %}`, matching the shape established in the earlier Approve & Send plan — this plan does not change that function. `get_pipeline_row`'s column aliases (`organization_name`, `contact_name`) match `list_pipeline`'s existing aliases exactly, so `_pipeline_row.html` renders identically whether reached via the full list or the single-row htmx response. `_is_hx`/`request.headers.get("hx-request") == "true"` is the one condition used consistently across all three modified route files (Action Center, Pipeline, LinkedIn) — no route invents a different way to detect an htmx request.
