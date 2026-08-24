# Visual Parity Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the mockup-vs-app visual gaps identified after the first redesign pass: header chrome, a real pipeline funnel on the dashboard, a real activity feed + factual summary on Contacts' company detail, and closer LinkedIn board styling.

**Architecture:** Two new/extended repository read queries (no schema changes), one small route addition (Action Center passes a `funnel` context var), four template edits, and one CSS addition (new classes only, no changes to existing selectors).

**Tech Stack:** Python 3.13, FastAPI, Jinja2, sqlite3, pytest — unchanged.

## Global Constraints

- No new Python dependencies, no npm/build step.
- Every existing test in `tests/` must keep passing unmodified.
- No fabricated content: every new visual element is either decorative in the same inert way the mockup's own placeholder chrome is (no `onclick`, `aria-hidden="true"`, not a real `<input>`/`<button>`), or computed from real rows already in the database.
- No new CSS file rewrite — only new classes appended to `src/project_os/web/static/style.css`; every existing selector stays untouched.
- The "Individuals" bucket (`company["id"] is None`) in Contacts never gets `open_opportunities`/`activity` keys — there's no single organization to aggregate against.

---

### Task 1: Header chrome — decorative search + notification bell

**Files:**
- Modify: `src/project_os/web/templates/base.html`
- Modify: `src/project_os/web/static/style.css`

**Interfaces:** none (pure template/CSS, no backend).

- [ ] **Step 1: Add the CSS classes**

Append to `src/project_os/web/static/style.css`:

```css
.topbar-chrome { display: flex; align-items: center; gap: 10px; margin-left: auto; }
.topbar-search {
  display: flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 4px 10px;
  width: 220px;
  background: var(--row-alt-bg);
  color: var(--text-muted);
  font-size: 14px;
}
.topbar-bell {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--surface);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: var(--text-secondary);
}
```

- [ ] **Step 2: Update `base.html`**

Replace:

```html
    <header class="topbar">
      <div class="topbar-brand">Project OS</div>
      <nav class="tabs" aria-label="Primary">
        <a href="/action-center">Action Center</a>
        <a href="/emails">Emails</a>
        <a href="/projects">Projects</a>
        <a href="/contacts">Contacts</a>
        <a href="/interactions">Interactions</a>
      </nav>
    </header>
```

with:

```html
    <header class="topbar">
      <div class="topbar-brand">Project OS</div>
      <nav class="tabs" aria-label="Primary">
        <a href="/action-center">Action Center</a>
        <a href="/emails">Emails</a>
        <a href="/projects">Projects</a>
        <a href="/contacts">Contacts</a>
        <a href="/interactions">Interactions</a>
      </nav>
      <div class="topbar-chrome" aria-hidden="true">
        <div class="topbar-search">
          <span>⌕</span><span>Search people, deals, mail</span>
        </div>
        <span class="topbar-bell">🔔</span>
      </div>
    </header>
```

Both new elements are `aria-hidden="true"` (on the wrapping `.topbar-chrome`) and use non-interactive tags (`<div>`/`<span>`, no `<input>`/`<button>`, no `onclick`) — they're decoration only, matching the mockup's own non-functional placeholder chrome, and assistive tech won't announce a control that does nothing.

- [ ] **Step 3: Run the layout tests**

Run: `.venv/bin/python -m pytest tests/test_base_layout.py -v`
Expected: PASS (3 tests) — the htmx `<script>` tag and all 5 nav hrefs are untouched, only new sibling elements were added.

- [ ] **Step 4: Run the full suite for regressions**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/templates/base.html src/project_os/web/static/style.css
git commit -m "style: add decorative header search/notification chrome matching the mockup"
```

---

### Task 2: Dashboard funnel — real pipeline stage counts

**Files:**
- Modify: `src/project_os/repositories/opportunities.py`
- Modify: `src/project_os/web/routes_action_center.py`
- Modify: `src/project_os/web/templates/action_center.html`
- Modify: `src/project_os/web/static/style.css`
- Test: `tests/test_opportunities_repo.py`, `tests/test_action_center_routes.py`

**Interfaces:**
- Produces: `count_opportunities_by_stage(conn: sqlite3.Connection) -> list[dict]` — each dict `{"stage": str, "count": int, "width_pct": int}`, ordered per `pipeline.STAGES`, stages with zero opportunities omitted, `width_pct` scaled so the largest count is 100. Returns `[]` if there are no opportunities at all.

- [ ] **Step 1: Write the failing repo tests**

Append to `tests/test_opportunities_repo.py`:

```python
from project_os.repositories.opportunities import count_opportunities_by_stage


def test_count_opportunities_by_stage_omits_zero_count_stages(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_a = create_contact(conn, "Jane Smith")
    contact_b = create_contact(conn, "John Doe")
    contact_c = create_contact(conn, "Alex Lee")
    create_opportunity(conn, project_id, contact_id=contact_a, stage="Research")
    create_opportunity(conn, project_id, contact_id=contact_b, stage="Research")
    create_opportunity(conn, project_id, contact_id=contact_c, stage="Contacted")

    result = count_opportunities_by_stage(conn)

    assert result == [
        {"stage": "Research", "count": 2, "width_pct": 100},
        {"stage": "Contacted", "count": 1, "width_pct": 50},
    ]


def test_count_opportunities_by_stage_is_empty_with_no_opportunities(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)

    assert count_opportunities_by_stage(conn) == []
```

Check the top of `tests/test_opportunities_repo.py` for its existing imports (`get_connection`, `run_migrations`, `MIGRATIONS_DIR`, `create_project`, `create_contact`, `create_opportunity`) — add any that are missing, matching the file's existing import style.

- [ ] **Step 2: Run tests to see them fail**

Run: `.venv/bin/python -m pytest tests/test_opportunities_repo.py -v`
Expected: FAIL — `ImportError: cannot import name 'count_opportunities_by_stage'`

- [ ] **Step 3: Implement the repository function**

Append to `src/project_os/repositories/opportunities.py`:

```python
def count_opportunities_by_stage(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT stage, COUNT(*) AS count FROM opportunities GROUP BY stage"
    ).fetchall()
    counts = {row["stage"]: row["count"] for row in rows}
    ordered = [
        {"stage": stage, "count": counts[stage]}
        for stage in STAGES
        if counts.get(stage)
    ]
    if not ordered:
        return []
    max_count = max(item["count"] for item in ordered)
    for item in ordered:
        item["width_pct"] = round(item["count"] / max_count * 100)
    return ordered
```

- [ ] **Step 4: Run repo tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_opportunities_repo.py -v`
Expected: PASS (all tests, including the 2 new ones)

- [ ] **Step 5: Write the failing route test**

Append to `tests/test_action_center_routes.py`. Check the file's existing imports first (`create_project`, `create_contact`, `create_opportunity` may need adding — match the file's existing style):

```python
def test_action_center_shows_funnel_bars_for_stages_with_opportunities(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith")
    create_opportunity(conn, project_id, contact_id=contact_id, stage="Contacted")
    conn.close()
    client = TestClient(create_app(tmp_db_path))

    response = client.get("/action-center")

    assert response.status_code == 200
    assert "Contacted" in response.text
    assert "funnel-row" in response.text


def test_action_center_shows_no_funnel_section_when_there_are_no_opportunities(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    conn.close()
    client = TestClient(create_app(tmp_db_path))

    response = client.get("/action-center")

    assert response.status_code == 200
    assert "funnel-row" not in response.text
```

- [ ] **Step 6: Run tests to see them fail**

Run: `.venv/bin/python -m pytest tests/test_action_center_routes.py -v -k funnel`
Expected: FAIL — the funnel markup doesn't exist yet

- [ ] **Step 7: Wire the route**

In `src/project_os/web/routes_action_center.py`, add to the imports:

```python
from project_os.repositories.opportunities import count_opportunities_by_stage
```

Replace the `action_center` function body:

```python
@router.get("/action-center")
def action_center(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        actions = list_open_actions(conn)
        reply_contexts = {action["id"]: get_reply_context(conn, action["id"]) for action in actions}
        funnel = count_opportunities_by_stage(conn)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "action_center.html",
        {
            "actions": actions,
            "reply_contexts": reply_contexts,
            "error": request.query_params.get("error"),
            "funnel": funnel,
        },
    )
```

- [ ] **Step 8: Add the CSS classes**

Append to `src/project_os/web/static/style.css`:

```css
.funnel-card { padding: 14px 18px; }
.funnel-row { display: grid; grid-template-columns: 160px 1fr 40px; gap: 12px; align-items: center; padding: 6px 0; }
.funnel-track { height: 20px; background: var(--row-alt-bg); border-radius: 4px; overflow: hidden; }
.funnel-fill { height: 100%; background: var(--accent); border-radius: 4px; }
.funnel-count { font-family: var(--font-mono); font-size: 12.5px; color: var(--text-secondary); text-align: right; }
```

- [ ] **Step 9: Update `action_center.html`**

Replace:

```html
{% extends "base.html" %}
{% block title %}Action Center — Project OS{% endblock %}
{% block content %}
<p id="flash-banner" role="alert" class="flash-error"{% if not error %} hidden{% endif %}>{{ error or "" }}</p>
<h2>Action Center</h2>
<div class="table-card">
```

with:

```html
{% extends "base.html" %}
{% block title %}Action Center — Project OS{% endblock %}
{% block content %}
<p id="flash-banner" role="alert" class="flash-error"{% if not error %} hidden{% endif %}>{{ error or "" }}</p>
<h2>Action Center</h2>
{% if funnel %}
<div class="table-card funnel-card">
  {% for row in funnel %}
  <div class="funnel-row">
    <span>{{ row["stage"] }}</span>
    <div class="funnel-track"><div class="funnel-fill" style="width: {{ row['width_pct'] }}%;"></div></div>
    <span class="funnel-count">{{ row["count"] }}</span>
  </div>
  {% endfor %}
</div>
{% endif %}
<div class="table-card">
```

(the rest of the file — the existing `<table>` block and closing `</div>{% endblock %}` — is unchanged, just now preceded by the new funnel block).

- [ ] **Step 10: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_action_center_routes.py -v`
Expected: PASS (all tests, including the 2 new funnel ones)

- [ ] **Step 11: Run the full suite for regressions**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/repositories/opportunities.py src/project_os/web/routes_action_center.py src/project_os/web/templates/action_center.html src/project_os/web/static/style.css tests/test_opportunities_repo.py tests/test_action_center_routes.py
git commit -m "feat: real pipeline funnel on the Action Center dashboard"
```

---

### Task 3: Contacts — real activity feed + factual company summary

**Files:**
- Modify: `src/project_os/repositories/contacts.py`
- Modify: `src/project_os/web/templates/contacts_index.html`
- Modify: `src/project_os/web/static/style.css`
- Test: `tests/test_contacts_repo.py`

**Interfaces:**
- Modifies `list_companies_with_contacts`'s return shape: every company dict **except** the `id: None` "Individuals" bucket now also has `open_opportunities: int` and `activity: list[sqlite3.Row]` (each row: all `interactions` columns + `contact_name`, newest first, max 5).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_contacts_repo.py`. Check the file's existing imports for `create_opportunity` (from `project_os.repositories.opportunities`) and `create_interaction` (from `project_os.repositories.interactions`) — add if missing:

```python
from project_os.repositories.opportunities import create_opportunity
from project_os.repositories.interactions import create_interaction


def test_list_companies_with_contacts_includes_open_opportunities_and_activity(tmp_db_path):
    conn = _conn(tmp_db_path)
    project_id = create_project(conn, "Nexy")
    org_id = create_organization(conn, "Example Org")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    link_contact_to_project(conn, project_id, contact_id, organization_id=org_id)

    create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id, stage="Contacted")
    create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id, stage="Closed")
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="inbound", subject="Pricing question",
        ai_summary=None, intent=None, external_message_id=None,
        created_at="2026-08-10 00:00:00",
    )
    create_interaction(
        conn, project_id, contact_id,
        channel="email", direction="outbound", subject="Re: Pricing question",
        ai_summary=None, intent=None, external_message_id=None,
        created_at="2026-08-12 00:00:00",
    )

    companies = list_companies_with_contacts(conn)
    example_org = next(c for c in companies if c["name"] == "Example Org")

    assert example_org["open_opportunities"] == 1  # the Closed one is excluded
    assert [a["subject"] for a in example_org["activity"]] == ["Re: Pricing question", "Pricing question"]


def test_list_companies_with_contacts_caps_activity_at_five(tmp_db_path):
    conn = _conn(tmp_db_path)
    project_id = create_project(conn, "Nexy")
    org_id = create_organization(conn, "Example Org")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
    link_contact_to_project(conn, project_id, contact_id, organization_id=org_id)

    for i in range(7):
        create_interaction(
            conn, project_id, contact_id,
            channel="email", direction="outbound", subject=f"Message {i}",
            ai_summary=None, intent=None, external_message_id=None,
            created_at=f"2026-08-{10 + i:02d} 00:00:00",
        )

    companies = list_companies_with_contacts(conn)
    example_org = next(c for c in companies if c["name"] == "Example Org")

    assert len(example_org["activity"]) == 5
    assert example_org["activity"][0]["subject"] == "Message 6"  # newest first


def test_list_companies_with_contacts_individuals_bucket_has_no_opportunity_fields(tmp_db_path):
    conn = _conn(tmp_db_path)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Solo Tester")
    link_contact_to_project(conn, project_id, contact_id, organization_id=None)

    companies = list_companies_with_contacts(conn)

    assert companies[0]["name"] == "Individuals"
    assert "open_opportunities" not in companies[0]
    assert "activity" not in companies[0]
```

- [ ] **Step 2: Run tests to see them fail**

Run: `.venv/bin/python -m pytest tests/test_contacts_repo.py -v`
Expected: FAIL — `KeyError` (the new dict keys don't exist yet)

- [ ] **Step 3: Implement**

Replace the org-loop body inside `list_companies_with_contacts` in `src/project_os/repositories/contacts.py`. Change:

```python
    companies = []
    for org in orgs:
        people = conn.execute(
            """
            SELECT c.id, c.name, c.email, c.linkedin_url, pc.role, pc.status, pc.priority
            FROM project_contacts pc
            JOIN contacts c ON c.id = pc.contact_id
            WHERE pc.organization_id = ?
            ORDER BY c.name
            """,
            (org["id"],),
        ).fetchall()
        companies.append(
            {"id": org["id"], "name": org["name"], "website": org["website"], "people": people}
        )
```

to:

```python
    companies = []
    for org in orgs:
        people = conn.execute(
            """
            SELECT c.id, c.name, c.email, c.linkedin_url, pc.role, pc.status, pc.priority
            FROM project_contacts pc
            JOIN contacts c ON c.id = pc.contact_id
            WHERE pc.organization_id = ?
            ORDER BY c.name
            """,
            (org["id"],),
        ).fetchall()
        open_opportunities = conn.execute(
            "SELECT COUNT(*) FROM opportunities WHERE organization_id = ? AND stage != 'Closed'",
            (org["id"],),
        ).fetchone()[0]
        activity = conn.execute(
            """
            SELECT i.*, c.name AS contact_name
            FROM interactions i
            JOIN contacts c ON c.id = i.contact_id
            JOIN project_contacts pc ON pc.contact_id = c.id AND pc.organization_id = ?
            ORDER BY i.created_at DESC, i.id DESC
            LIMIT 5
            """,
            (org["id"],),
        ).fetchall()
        companies.append(
            {
                "id": org["id"], "name": org["name"], "website": org["website"], "people": people,
                "open_opportunities": open_opportunities, "activity": activity,
            }
        )
```

The "Individuals" bucket block below is untouched — it still builds `{"id": None, "name": "Individuals", "website": None, "people": all_individuals}` with no `open_opportunities`/`activity` keys.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_contacts_repo.py -v`
Expected: PASS (all tests, including the 3 new ones)

- [ ] **Step 5: Add the CSS class**

Append to `src/project_os/web/static/style.css`:

```css
.company-summary-line { padding: 10px 0 4px; color: var(--text-secondary); font-size: 13.5px; }
```

- [ ] **Step 6: Update `contacts_index.html`**

Replace:

```html
  <details class="company-group" {% if loop.first %}open{% endif %}>
    <summary class="company-summary">
      <span class="name">{{ company["name"] }}</span>
      <span class="meta">{{ company["people"] | length }} people</span>
    </summary>
    <div class="company-people">
      <table>
```

with:

```html
  <details class="company-group" {% if loop.first %}open{% endif %}>
    <summary class="company-summary">
      <span class="name">{{ company["name"] }}</span>
      <span class="meta">{{ company["people"] | length }} people</span>
    </summary>
    <div class="company-people">
      {% if company["id"] %}
      <div class="company-summary-line">
        {{ company["open_opportunities"] }} open opportunit{{ "y" if company["open_opportunities"] == 1 else "ies" }}
        {% if company["activity"] %} · last activity {{ company["activity"][0]["created_at"] }}{% else %} · no activity yet{% endif %}
      </div>
      {% endif %}
      <table>
```

and replace the block right after the closing `</table>` and before `</div>\n  </details>`:

```html
      </table>
    </div>
  </details>
```

with:

```html
      </table>
      {% if company["id"] and company["activity"] %}
      <div class="feed" style="margin-top: 12px;">
        {% for a in company["activity"] %}
        <div class="feed-row">
          <div class="feed-meta">
            <span class="tag">{{ a["channel"] }}</span>
            <span>{{ a["contact_name"] }}</span>
            <span style="margin-left: auto;">{{ a["created_at"] }}</span>
          </div>
          <div class="feed-line">{{ a["subject"] or "Unknown" }}</div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </div>
  </details>
```

- [ ] **Step 7: Run the contacts route tests**

Run: `.venv/bin/python -m pytest tests/test_contacts_routes.py tests/test_contacts_repo.py -v`
Expected: PASS — `test_contacts_routes.py`'s fixture creates "Jane Smith" via `create_contact` only (an orphan, no organization), so she's in the "Individuals" bucket and the template's `{% if company["id"] %}` guard means the new summary-line/activity blocks are correctly skipped for her, with no `KeyError`.

- [ ] **Step 8: Run the full suite for regressions**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/repositories/contacts.py src/project_os/web/templates/contacts_index.html src/project_os/web/static/style.css tests/test_contacts_repo.py
git commit -m "feat: real activity feed and factual summary on Contacts company detail"
```

---

### Task 4: LinkedIn board — role subtitle + column counts

**Files:**
- Modify: `src/project_os/web/templates/linkedin_queue.html`
- Modify: `src/project_os/web/static/style.css`

**Interfaces:** none — `project_contacts.role` is already selected via `pc.*` in `list_linkedin_queue` (`repositories/linkedin.py`, unchanged), no repository or route change needed.

- [ ] **Step 1: Add the CSS classes**

Append to `src/project_os/web/static/style.css`:

```css
.board-col-count { font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); margin-left: 6px; }
.li-row-role { color: var(--text-secondary); font-size: 13px; margin-top: -4px; }
```

- [ ] **Step 2: Update `linkedin_queue.html`**

For each of the 4 columns, add a count span to the header and a role line under the name. Replace all 4 occurrences of this pattern (the exact heading text differs per column — `To connect`, `Pending connections to re-check`, `Accepted connections awaiting a message`, `Conversations awaiting reply` — apply the same transformation to each):

```html
    <h3 class="board-col-header" id="to-connect-heading">To connect</h3>
```

becomes:

```html
    <h3 class="board-col-header" id="to-connect-heading">To connect<span class="board-col-count">{{ queue["to_connect"] | length }}</span></h3>
```

(same pattern for the other 3 headings, using `pending_recheck`, `awaiting_message`, `awaiting_reply` as the dict keys respectively — match each heading to its own section's existing `{% for row in queue["..."] %}` key, don't mix them up).

And for each of the 4 `<div class="li-row-name">{{ row["name"] }}</div>` occurrences, add directly after it:

```html
      {% if row["role"] %}<div class="li-row-role">{{ row["role"] }}</div>{% endif %}
```

- [ ] **Step 3: Run the LinkedIn route tests**

Run: `.venv/bin/python -m pytest tests/test_linkedin_routes.py -v`
Expected: PASS — button labels and empty-state texts are untouched; the test fixture's "Jane Smith" is created via `create_contact(conn, "Jane Smith")` with no `role` set, so `row["role"]` is `None`/falsy and the role line is correctly omitted (no empty `<div class="li-row-role"></div>` clutter).

- [ ] **Step 4: Run the full suite for regressions**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/templates/linkedin_queue.html src/project_os/web/static/style.css
git commit -m "style: show role and column counts on the LinkedIn board"
```

---

### Task 5: Verify against the mockup

**Files:** none (verification-only task).

**Interfaces:** none.

- [ ] **Step 1: Run the full suite one more time**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS — every test in the repo.

- [ ] **Step 2: Start the app against a copy of the real data**

```bash
cd /Users/sergiyzasorin/ProjectOS
mkdir -p data
cp /Users/sergiyzasorin/ProjectOS/data/project_os.sqlite data/project_os.sqlite
```

(If running from a worktree, `/Users/sergiyzasorin/ProjectOS/data/project_os.sqlite` is the real production DB in the main checkout — copy it in, don't write back to it.) Start the app on a throwaway port so the real LaunchAgent daemon on 8765 is undisturbed:

```bash
cat > /tmp/run_visual_parity_daemon.py << 'EOF'
import uvicorn
from project_os.web.app import create_app

app = create_app("data/project_os.sqlite")
uvicorn.run(app, host="127.0.0.1", port=8768)
EOF
nohup .venv/bin/python /tmp/run_visual_parity_daemon.py > /tmp/pos_visual_parity_daemon.log 2>&1 &
sleep 1.5
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8768/action-center
```

- [ ] **Step 3: Visually verify each area against the mockup**

Use the Browser tool. Open `http://127.0.0.1:8768/action-center` — confirm the funnel bars appear above the priority queue with real stage names/counts, and the header shows the decorative search box + bell on the right of the tabs. Open `http://127.0.0.1:8768/contacts`, expand a company with real opportunities/interactions in the data — confirm the "N open opportunities · last activity ..." line and the activity feed appear (a company with none should just show "0 open opportunities · no activity yet" and no feed section). Open `http://127.0.0.1:8768/projects/1/linkedin` — confirm role text appears under names that have one, and each column header shows a count.

- [ ] **Step 4: Stop the throwaway server**

```bash
pkill -f "run_visual_parity_daemon.py"
```

(No commit — this task only verifies previously-committed code.)
