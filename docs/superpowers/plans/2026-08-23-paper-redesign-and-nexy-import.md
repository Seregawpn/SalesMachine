# Paper Redesign & Nexy Data Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the six existing Project OS pages with the "paper" visual system from the mockup (`~/Desktop/Project OS CRM - standalone.html`), add company-grouped/expandable Contacts, and import the real ~638-row Nexy outreach spreadsheet into the DB.

**Architecture:** FastAPI + Jinja2 + vendored htmx, server-rendered, no build step (unchanged). One new migration adds two columns; the visual pass is CSS + template edits with no route-behavior changes; the import is a standalone, idempotent, get-or-create script reusing the existing repository layer.

**Tech Stack:** Python 3.13, FastAPI, Jinja2, sqlite3, pytest, htmx (vendored).

## Global Constraints

- No new Python dependencies, no npm/build step (per the existing "CRM Design System" design's stated architecture).
- Every existing test in `tests/` must keep passing unmodified except the one schema-version assertion this plan explicitly bumps (4 → 5).
- The source CSV (`data/imports/nexy_outreach.csv`) contains real names/emails and must never be committed — `data/` is already gitignored; do not touch `.gitignore`.
- Every htmx-enabled route's non-JS fallback (full-page redirect) must keep working — this plan changes no route logic, only migrations, repository helpers, templates, and CSS.

---

### Task 1: Migration 0005 — add `role` and `organization_id` to `project_contacts`

**Files:**
- Create: `src/project_os/migrations/0005_project_contacts_org_role.sql`
- Modify: `tests/test_db.py:9` (version assertion 4 → 5)
- Modify: `docs/superpowers/specs/2026-08-23-paper-redesign-and-nexy-import-design.md` (Part 1a note — see step 4)

**Interfaces:**
- Produces: `project_contacts.role TEXT` (free-text job title/role), `project_contacts.organization_id INTEGER REFERENCES organizations(id)` (nullable — which company this project-scoped contact belongs to, if any). Both are read by Task 2's `list_companies_with_contacts` and written by Task 2's `link_contact_to_project`.

- [ ] **Step 1: Write the migration file**

```sql
ALTER TABLE project_contacts ADD COLUMN role TEXT;
ALTER TABLE project_contacts ADD COLUMN organization_id INTEGER REFERENCES organizations(id);
```

- [ ] **Step 2: Update the schema-version test**

In `tests/test_db.py`, change:

```python
    version = run_migrations(conn, MIGRATIONS_DIR)
    assert version == 4
```

to:

```python
    version = run_migrations(conn, MIGRATIONS_DIR)
    assert version == 5
```

Also in `test_run_migrations_is_idempotent`, change both `== 4 == 4` occurrences to `== 5 == 5`:

```python
    first = run_migrations(conn, MIGRATIONS_DIR)
    second = run_migrations(conn, MIGRATIONS_DIR)
    assert first == second == 5

    count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert count == 5
```

- [ ] **Step 3: Run the migration tests**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS (5 tests)

- [ ] **Step 4: Note the schema addition in the design doc**

The committed design spec's Part 1a says grouping comes "for free" from the existing schema. It doesn't — there was no direct contact→organization link. Append this paragraph to the end of the "1a. Contacts: company-grouped, expandable" section in `docs/superpowers/specs/2026-08-23-paper-redesign-and-nexy-import-design.md`:

```
**Correction during implementation:** the schema had no direct contact-to-organization link (`project_contacts` and `project_organizations` were both project-scoped but not linked to each other). Migration `0005_project_contacts_org_role.sql` adds `project_contacts.organization_id` (nullable FK to `organizations`) alongside `role`, so a project-scoped contact can record which company it belongs to. Contacts with `organization_id IS NULL` (including all B2C individuals) fall into the synthetic "Individuals" bucket.
```

- [ ] **Step 5: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/migrations/0005_project_contacts_org_role.sql tests/test_db.py docs/superpowers/specs/2026-08-23-paper-redesign-and-nexy-import-design.md
git commit -m "feat: add project_contacts.role and organization_id (migration 0005)"
```

---

### Task 2: Repository helpers — organizations, contacts, grouped listing

**Files:**
- Modify: `src/project_os/repositories/contacts.py`
- Test: `tests/test_contacts_repo.py`

**Interfaces:**
- Consumes: migration 0005's `role`/`organization_id` columns (Task 1).
- Produces (used by Task 9 templates/routes and Task 12 import script):
  - `get_organization_by_name(conn, name: str) -> sqlite3.Row | None`
  - `get_or_create_organization(conn, name: str, website: str | None = None) -> int`
  - `link_organization_to_project(conn, project_id: int, organization_id: int, segment: str | None = None, relevance: str | None = None, status: str = "Research") -> int`
  - `find_contact_for_import(conn, name: str, email: str | None) -> sqlite3.Row | None`
  - `link_contact_to_project(conn, project_id, contact_id, status="Research", priority="Medium", pitch=None, role=None, organization_id=None) -> int` (extended, backward compatible)
  - `list_companies_with_contacts(conn) -> list[dict]` — each dict: `{"id": int|None, "name": str, "website": str|None, "people": list[sqlite3.Row]}`, "Individuals" (id=None) first when non-empty, then organizations alphabetically.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_contacts_repo.py`:

```python
from project_os.repositories.contacts import (
    create_contact,
    create_organization,
    find_contact_for_import,
    get_or_create_organization,
    get_organization_by_name,
    link_contact_to_project,
    link_organization_to_project,
    list_companies_with_contacts,
)
from project_os.repositories.projects import create_project


def test_get_organization_by_name_is_case_insensitive(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    create_organization(conn, "Example Org")

    found = get_organization_by_name(conn, "EXAMPLE org")

    assert found is not None
    assert found["name"] == "Example Org"
    assert get_organization_by_name(conn, "Nonexistent") is None


def test_get_or_create_organization_does_not_duplicate(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)

    first_id = get_or_create_organization(conn, "Example Org", website="https://example.org")
    second_id = get_or_create_organization(conn, "example org")

    assert first_id == second_id
    count = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    assert count == 1


def test_link_organization_to_project_is_idempotent(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    org_id = create_organization(conn, "Example Org")

    first = link_organization_to_project(conn, project_id, org_id, segment="Work", status="Research")
    second = link_organization_to_project(conn, project_id, org_id, segment="Different", status="Contacted")

    assert first == second
    row = conn.execute(
        "SELECT segment, status FROM project_organizations WHERE id = ?", (first,)
    ).fetchone()
    assert row["segment"] == "Work"  # first write wins, second call is a no-op
    assert row["status"] == "Research"


def test_find_contact_for_import_matches_by_email_then_name(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    with_email = create_contact(conn, "Jane Smith", email="jane@example.org")
    no_email = create_contact(conn, "No Email Guy")

    assert find_contact_for_import(conn, "Different Name", "jane@example.org")["id"] == with_email
    assert find_contact_for_import(conn, "No Email Guy", None)["id"] == no_email
    assert find_contact_for_import(conn, "Nobody Here", None) is None


def test_link_contact_to_project_stores_role_pitch_and_organization(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    org_id = create_organization(conn, "Example Org")
    contact_id = create_contact(conn, "Jane Smith")

    link_id = link_contact_to_project(
        conn, project_id, contact_id,
        status="Contacted", priority="High", pitch="Sent intro email",
        role="Director", organization_id=org_id,
    )

    row = conn.execute("SELECT * FROM project_contacts WHERE id = ?", (link_id,)).fetchone()
    assert row["pitch"] == "Sent intro email"
    assert row["role"] == "Director"
    assert row["organization_id"] == org_id


def test_list_companies_with_contacts_groups_by_organization(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    org_id = create_organization(conn, "Example Org")
    grouped_contact = create_contact(conn, "Jane Smith", email="jane@example.org")
    individual_contact = create_contact(conn, "Solo Tester", email="solo@example.org")
    orphan_contact = create_contact(conn, "Orphan Contact")  # never linked to any project

    link_contact_to_project(conn, project_id, grouped_contact, organization_id=org_id, role="Director")
    link_contact_to_project(conn, project_id, individual_contact, organization_id=None)

    companies = list_companies_with_contacts(conn)

    assert companies[0]["name"] == "Individuals"
    individual_names = {p["name"] for p in companies[0]["people"]}
    assert individual_names == {"Solo Tester", "Orphan Contact"}

    example_org = next(c for c in companies if c["name"] == "Example Org")
    assert [p["name"] for p in example_org["people"]] == ["Jane Smith"]
    assert example_org["people"][0]["role"] == "Director"


def test_list_companies_with_contacts_is_empty_when_no_contacts(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)

    assert list_companies_with_contacts(conn) == []
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/test_contacts_repo.py -v`
Expected: FAIL — `ImportError` (the new functions don't exist yet)

- [ ] **Step 3: Implement the repository functions**

In `src/project_os/repositories/contacts.py`, add after `create_organization`:

```python
def get_organization_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM organizations WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()


def get_or_create_organization(
    conn: sqlite3.Connection, name: str, website: str | None = None
) -> int:
    existing = get_organization_by_name(conn, name)
    if existing is not None:
        return existing["id"]
    return create_organization(conn, name, website)


def link_organization_to_project(
    conn: sqlite3.Connection,
    project_id: int,
    organization_id: int,
    segment: str | None = None,
    relevance: str | None = None,
    status: str = "Research",
) -> int:
    existing = conn.execute(
        "SELECT id FROM project_organizations WHERE project_id = ? AND organization_id = ?",
        (project_id, organization_id),
    ).fetchone()
    if existing is not None:
        return existing["id"]
    cur = conn.execute(
        """
        INSERT INTO project_organizations (project_id, organization_id, segment, relevance, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, organization_id, segment, relevance, status),
    )
    return cur.lastrowid


def find_contact_for_import(
    conn: sqlite3.Connection, name: str, email: str | None
) -> sqlite3.Row | None:
    if email:
        row = get_contact_by_email(conn, email)
        if row is not None:
            return row
    return conn.execute(
        "SELECT * FROM contacts WHERE LOWER(name) = LOWER(?) AND email IS NULL",
        (name,),
    ).fetchone()
```

Replace the existing `link_contact_to_project` with:

```python
def link_contact_to_project(
    conn: sqlite3.Connection,
    project_id: int,
    contact_id: int,
    status: str = "Research",
    priority: str = "Medium",
    pitch: str | None = None,
    role: str | None = None,
    organization_id: int | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO project_contacts (project_id, contact_id, status, priority, pitch, role, organization_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, contact_id, status, priority, pitch, role, organization_id),
    )
    return cur.lastrowid
```

Add at the end of the file:

```python
def list_companies_with_contacts(conn: sqlite3.Connection) -> list[dict]:
    orgs = conn.execute(
        """
        SELECT DISTINCT org.id, org.name, org.website
        FROM organizations org
        JOIN project_contacts pc ON pc.organization_id = org.id
        ORDER BY org.name
        """
    ).fetchall()

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

    individuals = conn.execute(
        """
        SELECT c.id, c.name, c.email, c.linkedin_url, pc.role, pc.status, pc.priority
        FROM project_contacts pc
        JOIN contacts c ON c.id = pc.contact_id
        WHERE pc.organization_id IS NULL
        ORDER BY c.name
        """
    ).fetchall()
    orphans = conn.execute(
        """
        SELECT c.id, c.name, c.email, c.linkedin_url,
               NULL AS role, NULL AS status, NULL AS priority
        FROM contacts c
        WHERE c.id NOT IN (SELECT contact_id FROM project_contacts)
        ORDER BY c.name
        """
    ).fetchall()
    all_individuals = list(individuals) + list(orphans)
    if all_individuals:
        companies.insert(
            0, {"id": None, "name": "Individuals", "website": None, "people": all_individuals}
        )
    return companies
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_contacts_repo.py -v`
Expected: PASS (all tests, including the 6 new ones)

- [ ] **Step 5: Run the full existing test suite for regressions**

Run: `python -m pytest tests/ -v -x`
Expected: PASS — `link_contact_to_project`'s existing callers (mail_sync, routes, other repo tests) only ever pass the first three positional/keyword args, so the new trailing optional params don't affect them.

- [ ] **Step 6: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/repositories/contacts.py tests/test_contacts_repo.py
git commit -m "feat: organization lookup, grouped contact listing, and richer project_contacts links"
```

---

### Task 3: `interactions.py` — explicit `created_at` and duplicate guard

**Files:**
- Modify: `src/project_os/repositories/interactions.py`
- Test: `tests/test_interactions_repo.py`

**Interfaces:**
- Produces (used by Task 12's import script): `create_interaction(..., created_at: str | None = None)` (new optional kwarg, backward compatible), `interaction_exists(conn, contact_id: int, subject: str | None, created_at: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_interactions_repo.py`:

```python
from project_os.repositories.interactions import interaction_exists


def test_create_interaction_accepts_explicit_created_at(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")

    interaction_id = create_interaction(
        conn, project_id, contact_id,
        channel="Email", direction="outbound", subject="Intro",
        ai_summary=None, intent=None, external_message_id=None,
        source="import-nexy-sheet", created_at="2026-08-10 00:00:00",
    )

    row = conn.execute("SELECT created_at FROM interactions WHERE id = ?", (interaction_id,)).fetchone()
    assert row["created_at"] == "2026-08-10 00:00:00"


def test_interaction_exists_detects_duplicates(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")

    assert interaction_exists(conn, contact_id, "Intro", "2026-08-10 00:00:00") is False

    create_interaction(
        conn, project_id, contact_id,
        channel="Email", direction="outbound", subject="Intro",
        ai_summary=None, intent=None, external_message_id=None,
        created_at="2026-08-10 00:00:00",
    )

    assert interaction_exists(conn, contact_id, "Intro", "2026-08-10 00:00:00") is True
    assert interaction_exists(conn, contact_id, "Different subject", "2026-08-10 00:00:00") is False
```

Check the top of `tests/test_interactions_repo.py` already imports `create_project`, `create_contact`, `create_interaction`, `get_connection`, `run_migrations`, `MIGRATIONS_DIR` — if any are missing, add them to match the existing import block's style in that file.

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m pytest tests/test_interactions_repo.py -v`
Expected: FAIL — `TypeError` (unexpected keyword `created_at`) and `ImportError` for `interaction_exists`

- [ ] **Step 3: Implement**

Replace `create_interaction` in `src/project_os/repositories/interactions.py` with:

```python
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
    created_at: str | None = None,
) -> int:
    if created_at is None:
        cur = conn.execute(
            """
            INSERT INTO interactions
                (project_id, contact_id, channel, direction, subject, ai_summary, intent, external_message_id, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, contact_id, channel, direction, subject, ai_summary, intent, external_message_id, source),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO interactions
                (project_id, contact_id, channel, direction, subject, ai_summary, intent, external_message_id, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, contact_id, channel, direction, subject, ai_summary, intent, external_message_id, source, created_at),
        )
    return cur.lastrowid


def interaction_exists(
    conn: sqlite3.Connection, contact_id: int, subject: str | None, created_at: str
) -> bool:
    row = conn.execute(
        "SELECT id FROM interactions WHERE contact_id = ? AND subject IS ? AND created_at = ?",
        (contact_id, subject, created_at),
    ).fetchone()
    return row is not None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_interactions_repo.py tests/test_action_center_routes.py tests/test_mail_sync.py -v`
Expected: PASS — existing callers in `mail_sync.py`/`routes_action_center.py` never pass `created_at`, so their behavior is unchanged.

- [ ] **Step 5: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/repositories/interactions.py tests/test_interactions_repo.py
git commit -m "feat: allow explicit interaction created_at and duplicate detection"
```

---

### Task 4: `opportunities.py` — richer `create_opportunity` and lookup by contact

**Files:**
- Modify: `src/project_os/repositories/opportunities.py`
- Test: `tests/test_opportunities_repo.py`

**Interfaces:**
- Produces (used by Task 12): `create_opportunity(..., offer=None, blocker=None, next_action=None, next_action_due=None)` (new optional kwargs, backward compatible), `get_opportunity_for_contact(conn, project_id: int, contact_id: int) -> sqlite3.Row | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_opportunities_repo.py`:

```python
from project_os.repositories.opportunities import get_opportunity_for_contact


def test_create_opportunity_accepts_offer_blocker_and_next_action(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith")
    org_id = create_organization(conn, "Example Org")

    opp_id = create_opportunity(
        conn, project_id, contact_id=contact_id, organization_id=org_id, stage="Research",
        offer="Pilot", blocker="Waiting on legal", next_action="Follow up", next_action_due="2026-09-01",
    )

    row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
    assert row["offer"] == "Pilot"
    assert row["blocker"] == "Waiting on legal"
    assert row["next_action"] == "Follow up"
    assert row["next_action_due"] == "2026-09-01"


def test_get_opportunity_for_contact_finds_existing(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith")

    assert get_opportunity_for_contact(conn, project_id, contact_id) is None

    opp_id = create_opportunity(conn, project_id, contact_id=contact_id)

    found = get_opportunity_for_contact(conn, project_id, contact_id)
    assert found["id"] == opp_id
```

Check that `tests/test_opportunities_repo.py` already imports `create_project` from `project_os.repositories.projects`, `get_connection`/`run_migrations` from `project_os.db`, and `MIGRATIONS_DIR` — match the file's existing import style if any are missing.

- [ ] **Step 2: Run tests to see them fail**

Run: `python -m pytest tests/test_opportunities_repo.py -v`
Expected: FAIL — `TypeError` for the unexpected kwargs, `ImportError` for `get_opportunity_for_contact`

- [ ] **Step 3: Implement**

Replace `create_opportunity` in `src/project_os/repositories/opportunities.py` with:

```python
def create_opportunity(
    conn: sqlite3.Connection,
    project_id: int,
    contact_id: int | None = None,
    organization_id: int | None = None,
    stage: str = "Research",
    offer: str | None = None,
    blocker: str | None = None,
    next_action: str | None = None,
    next_action_due: str | None = None,
) -> int:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    cur = conn.execute(
        """
        INSERT INTO opportunities
            (project_id, contact_id, organization_id, stage, offer, blocker, next_action, next_action_due)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, contact_id, organization_id, stage, offer, blocker, next_action, next_action_due),
    )
    return cur.lastrowid
```

Add at the end of the file:

```python
def get_opportunity_for_contact(
    conn: sqlite3.Connection, project_id: int, contact_id: int
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM opportunities WHERE project_id = ? AND contact_id = ? ORDER BY id LIMIT 1",
        (project_id, contact_id),
    ).fetchone()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_opportunities_repo.py tests/test_pipeline_routes.py tests/test_pipeline_consistency.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/repositories/opportunities.py tests/test_opportunities_repo.py
git commit -m "feat: create_opportunity accepts offer/blocker/next_action, add lookup by contact"
```

---

### Task 5: Rewrite `style.css` — paper visual system

**Files:**
- Modify: `src/project_os/web/static/style.css` (full rewrite)

**Interfaces:**
- Produces: CSS custom properties and classes consumed by Tasks 6–11's templates: `.topbar`, `.tabs`, `.content`, `.table-card`, `.badge`/`.badge-p0..p3`, `.btn`/`.btn-primary`, `.card-list`/`.project-card`, `.board`/`.board-col`/`.board-col-header`/`.li-row`/`.board-empty`, `.feed`/`.feed-row`/`.feed-meta`/`.feed-line`, `.tag`, `.company-group`/`.company-summary`/`.company-people`, `.flash-error`, `.skip-link`, `.sr-only`.

- [ ] **Step 1: Replace the file**

Write `src/project_os/web/static/style.css`:

```css
:root {
  --bg: #F5F5F4;
  --surface: #FFFFFF;
  --row-alt-bg: #FAFAF9;
  --border: #E5E4E1;
  --border-soft: #F1F0ED;
  --text-primary: #1A1A19;
  --text-secondary: #78776F;
  --text-muted: #A3A29B;
  --accent: oklch(43% 0.12 258);
  --accent-hover: oklch(36% 0.12 258);
  --badge-p0-bg: oklch(58% 0.18 25 / 0.14);
  --badge-p0-fg: oklch(45% 0.18 25);
  --badge-p1-bg: #fef3c7;
  --badge-p1-fg: #92400e;
  --badge-p2-bg: #e0e7ff;
  --badge-p2-fg: #3730a3;
  --badge-p3-bg: #F1F0ED;
  --badge-p3-fg: #78776F;
  --error-bg: oklch(58% 0.18 25 / 0.12);
  --error-fg: oklch(45% 0.18 25);
  --font-sans: "Helvetica Neue", Helvetica, Arial, -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
}

* { box-sizing: border-box; }

body {
  font-family: var(--font-sans);
  margin: 0;
  color: var(--text-primary);
  background: var(--bg);
  font-size: 15px;
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
}

.app-shell { min-height: 100vh; display: flex; flex-direction: column; }

.topbar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 0 24px;
  height: 56px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  flex: 0 0 auto;
}

.topbar-brand { font-size: 20px; letter-spacing: -0.01em; color: var(--text-primary); }

.tabs { display: flex; gap: 4px; }

.tabs a {
  padding: 8px 14px;
  border-radius: 6px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14.5px;
}

.tabs a:hover { background: var(--row-alt-bg); color: var(--text-primary); }

.content { flex: 1 1 auto; padding: 28px 24px 48px; max-width: 1180px; margin: 0 auto; width: 100%; }

h2 { font-size: 24px; letter-spacing: -0.01em; margin: 0 0 16px; font-weight: 500; }
h3 {
  font-size: 12.5px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
  margin: 22px 0 8px;
  font-family: var(--font-mono);
  font-weight: 600;
}

a { color: var(--accent); }

.table-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 16px;
}

table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border-soft); }
th {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
  background: var(--row-alt-bg);
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}
tbody tr:hover { background: var(--row-alt-bg); }
tbody tr:last-child td { border-bottom: none; }

.badge {
  display: inline-block;
  font-family: var(--font-mono);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.badge-p0 { background: var(--badge-p0-bg); color: var(--badge-p0-fg); }
.badge-p1 { background: var(--badge-p1-bg); color: var(--badge-p1-fg); }
.badge-p2 { background: var(--badge-p2-bg); color: var(--badge-p2-fg); }
.badge-p3 { background: var(--badge-p3-bg); color: var(--badge-p3-fg); }

button, .btn {
  font: inherit;
  cursor: pointer;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text-primary);
  padding: 6px 12px;
  font-size: 13.5px;
}
button:hover { border-color: var(--accent); color: var(--accent); }
button[type="submit"] { background: var(--accent); color: #fff; border-color: var(--accent); }
button[type="submit"]:hover { background: var(--accent-hover); border-color: var(--accent-hover); }

form { display: inline-flex; gap: 6px; align-items: center; }
input, select, textarea { font: inherit; border: 1px solid var(--border); border-radius: 6px; padding: 5px 8px; background: var(--surface); }

.card-list { display: flex; flex-direction: column; gap: 10px; }
.project-card {
  display: block;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 18px 20px;
  text-decoration: none;
  color: inherit;
}
.project-card:hover { border-color: var(--accent); }
.project-card .name { font-size: 19px; color: var(--text-primary); }

.board { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; align-items: start; margin-bottom: 20px; }
.board-col { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.board-col-header {
  padding: 10px 14px;
  background: var(--row-alt-bg);
  border-bottom: 1px solid var(--border);
  font-size: 13.5px;
  font-weight: 600;
}
.li-row { padding: 12px 14px; border-bottom: 1px solid var(--border-soft); display: flex; flex-direction: column; gap: 8px; }
.li-row:last-child { border-bottom: none; }
.li-row-name { font-size: 14.5px; color: var(--text-primary); }
.li-row-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.board-empty { padding: 16px 14px; color: var(--text-muted); font-size: 13.5px; }

.feed { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.feed-row { padding: 12px 16px; border-bottom: 1px solid var(--border-soft); }
.feed-row:last-child { border-bottom: none; }
.feed-meta { display: flex; align-items: baseline; gap: 8px; font-size: 12.5px; color: var(--text-muted); font-family: var(--font-mono); flex-wrap: wrap; }
.feed-line { margin-top: 4px; font-size: 14.5px; color: var(--text-primary); }

.tag {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--row-alt-bg);
  color: var(--text-secondary);
}

.company-group { border-bottom: 1px solid var(--border-soft); }
.company-group:last-child { border-bottom: none; }
.company-summary {
  cursor: pointer;
  padding: 13px 18px;
  display: flex;
  align-items: baseline;
  gap: 10px;
  list-style: none;
}
.company-summary::-webkit-details-marker { display: none; }
.company-summary .name { font-size: 15px; color: var(--text-primary); }
.company-summary .meta { color: var(--text-secondary); font-size: 13.5px; margin-left: auto; }
.company-people { background: var(--row-alt-bg); padding: 0 18px 14px 34px; }
.company-people table { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; }

.flash-error {
  background: var(--error-bg);
  color: var(--error-fg);
  padding: 10px 14px;
  border-radius: 6px;
  margin-bottom: 16px;
  font-size: 14px;
}

.skip-link { position: absolute; left: -9999px; }
.skip-link:focus { left: 8px; top: 8px; background: #fff; padding: 6px 10px; border-radius: 4px; z-index: 10; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
```

- [ ] **Step 2: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/static/style.css
git commit -m "feat: paper visual system (palette, cards, badges, board, feed)"
```

(No automated test — this is CSS only, verified visually in Task 13.)

---

### Task 6: `base.html` — top nav/tabs shell

**Files:**
- Modify: `src/project_os/web/templates/base.html`

**Interfaces:**
- Produces: the `.topbar`/`.tabs`/`.content` shell every other template renders inside via `{% block content %}`.

- [ ] **Step 1: Replace the file**

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
    <header class="topbar">
      <div class="topbar-brand">Project OS</div>
      <nav class="tabs" aria-label="Primary">
        <a href="/action-center">Action Center</a>
        <a href="/projects">Projects</a>
        <a href="/contacts">Contacts</a>
        <a href="/interactions">Interactions</a>
      </nav>
    </header>
    <main id="main" class="content">
      {% block content %}{% endblock %}
    </main>
  </div>
</body>
</html>
```

- [ ] **Step 2: Run the layout tests**

Run: `python -m pytest tests/test_base_layout.py -v`
Expected: PASS (3 tests) — the htmx `<script>` tag string and all four `href` values are unchanged, just moved from `<aside>` to `<header>`.

- [ ] **Step 3: Run the full suite for regressions**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/templates/base.html
git commit -m "feat: replace sidebar layout with top nav/tabs shell"
```

---

### Task 7: Wrap Action Center and Pipeline tables in `.table-card`

**Files:**
- Modify: `src/project_os/web/templates/action_center.html`
- Modify: `src/project_os/web/templates/pipeline.html`

**Interfaces:**
- Consumes: `.table-card` from Task 5's CSS.

- [ ] **Step 1: Update `action_center.html`**

Wrap the existing `<table>...</table>` block in a `<div class="table-card">`:

```html
{% extends "base.html" %}
{% block title %}Action Center — Project OS{% endblock %}
{% block content %}
<p id="flash-banner" role="alert" class="flash-error"{% if not error %} hidden{% endif %}>{{ error or "" }}</p>
<h2>Action Center</h2>
<div class="table-card">
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
</div>
{% endblock %}
```

- [ ] **Step 2: Update `pipeline.html`** the same way

```html
{% extends "base.html" %}
{% block title %}Pipeline — Project OS{% endblock %}
{% block content %}
<h2>Pipeline</h2>
<div class="table-card">
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
</div>
{% endblock %}
```

- [ ] **Step 3: Run the affected tests**

Run: `python -m pytest tests/test_action_center_routes.py tests/test_pipeline_routes.py -v`
Expected: PASS — both still contain `<table`, all row IDs/labels untouched (only the two full-page templates gained a wrapping `<div>`; the htmx partials `_action_row.html`/`_pipeline_row.html` are unchanged).

- [ ] **Step 4: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/templates/action_center.html src/project_os/web/templates/pipeline.html
git commit -m "style: wrap Action Center and Pipeline tables in paper card"
```

---

### Task 8: Restyle Projects index as a card list

**Files:**
- Modify: `src/project_os/web/templates/projects_index.html`

**Interfaces:**
- Consumes: `.card-list`/`.project-card` from Task 5's CSS.

- [ ] **Step 1: Replace the file**

```html
{% extends "base.html" %}
{% block title %}Projects — Project OS{% endblock %}
{% block content %}
<h2>Projects</h2>
{% if projects %}
<div class="card-list">
  {% for project in projects %}
  <a class="project-card" href="/projects/{{ project['id'] }}">
    <div class="name">{{ project["name"] }}</div>
    {% if project["description"] %}<p>{{ project["description"] }}</p>{% endif %}
  </a>
  {% endfor %}
</div>
{% else %}
<p>No projects yet.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_projects_routes.py -v`
Expected: PASS — `"Nexy" in response.text`, `href="/projects/{id}"`, and the literal `"No projects yet."` fallback are all preserved.

- [ ] **Step 3: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/templates/projects_index.html
git commit -m "style: restyle Projects index as a card list"
```

---

### Task 9: Restyle LinkedIn Queue as a 4-column board

**Files:**
- Modify: `src/project_os/web/templates/linkedin_queue.html`

**Interfaces:**
- Consumes: `.board`/`.board-col`/`.board-col-header`/`.li-row`/`.board-empty` from Task 5's CSS.
- The mutating route (`routes_linkedin.py`) is untouched — it already renders whichever template calls `hx-target`/`hx-swap` on the posted `<form>`; this task only changes the row wrapper element from `<tr>` to a `<div id="li-row-{id}">` and updates `hx-target` to match.

- [ ] **Step 1: Replace the file**

```html
{% extends "base.html" %}
{% block title %}LinkedIn — Project OS{% endblock %}
{% block content %}
<h2>LinkedIn</h2>

<div class="board">
  <div class="board-col">
    <div class="board-col-header">To connect</div>
    {% for row in queue["to_connect"] %}
    <div class="li-row" id="li-row-{{ row['id'] }}">
      <div class="li-row-name">{{ row["name"] }}</div>
      <div class="li-row-actions">
        <form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
              hx-post="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
              hx-target="#li-row-{{ row['id'] }}" hx-swap="outerHTML swap:0.2s">
          <input type="hidden" name="state" value="Pending Connection">
          <button type="submit">Connection sent</button>
        </form>
      </div>
    </div>
    {% else %}
    <div class="board-empty">Nothing to connect with right now.</div>
    {% endfor %}
  </div>

  <div class="board-col">
    <div class="board-col-header">Pending connections to re-check</div>
    {% for row in queue["pending_recheck"] %}
    <div class="li-row" id="li-row-{{ row['id'] }}">
      <div class="li-row-name">{{ row["name"] }}</div>
      <div class="li-row-actions">
        <form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
              hx-post="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
              hx-target="#li-row-{{ row['id'] }}" hx-swap="outerHTML swap:0.2s">
          <input type="hidden" name="state" value="Accepted">
          <button type="submit">Accepted</button>
        </form>
        <form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
              hx-post="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
              hx-target="#li-row-{{ row['id'] }}" hx-swap="outerHTML swap:0.2s">
          <input type="hidden" name="state" value="Not relevant">
          <button type="submit">Not relevant</button>
        </form>
      </div>
    </div>
    {% else %}
    <div class="board-empty">Nothing pending.</div>
    {% endfor %}
  </div>

  <div class="board-col">
    <div class="board-col-header">Accepted connections awaiting a message</div>
    {% for row in queue["awaiting_message"] %}
    <div class="li-row" id="li-row-{{ row['id'] }}">
      <div class="li-row-name">{{ row["name"] }}</div>
      <div class="li-row-actions">
        <form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
              hx-post="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
              hx-target="#li-row-{{ row['id'] }}" hx-swap="outerHTML swap:0.2s">
          <input type="hidden" name="state" value="Message Sent">
          <button type="submit">Message sent</button>
        </form>
      </div>
    </div>
    {% else %}
    <div class="board-empty">Nobody waiting on a message.</div>
    {% endfor %}
  </div>

  <div class="board-col">
    <div class="board-col-header">Conversations awaiting reply</div>
    {% for row in queue["awaiting_reply"] %}
    <div class="li-row" id="li-row-{{ row['id'] }}">
      <div class="li-row-name">{{ row["name"] }}</div>
      <div class="li-row-actions">
        <form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
              hx-post="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state"
              hx-target="#li-row-{{ row['id'] }}" hx-swap="outerHTML swap:0.2s">
          <input type="hidden" name="state" value="Replied">
          <button type="submit">Replied</button>
        </form>
      </div>
    </div>
    {% else %}
    <div class="board-empty">No open conversations.</div>
    {% endfor %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_linkedin_routes.py -v`
Expected: PASS — "Jane Smith", "Connection sent", "Nothing to connect with right now.", and the empty htmx-fragment response (`response.text == ""` on a successful state change) are all still exact matches; only the wrapper markup (`<tr>` → `<div>`) changed.

- [ ] **Step 3: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/templates/linkedin_queue.html
git commit -m "style: restyle LinkedIn Queue as a 4-column board"
```

---

### Task 10: Restyle Interactions as an activity feed

**Files:**
- Modify: `src/project_os/web/templates/interactions_index.html`

**Interfaces:**
- Consumes: `.feed`/`.feed-row`/`.feed-meta`/`.feed-line`/`.tag` from Task 5's CSS.

- [ ] **Step 1: Replace the file**

```html
{% extends "base.html" %}
{% block title %}Interactions — Project OS{% endblock %}
{% block content %}
<h2>Interactions</h2>
{% if interactions %}
<div class="feed">
  {% for interaction in interactions %}
  <div class="feed-row">
    <div class="feed-meta">
      <span class="tag">{{ interaction["direction"] }}</span>
      <span class="tag">{{ interaction["channel"] }}</span>
      <span>{{ interaction["contact_name"] }}</span>
      <span>{{ interaction["project_name"] }}</span>
      <span style="margin-left:auto;">{{ interaction["created_at"] }}</span>
    </div>
    <div class="feed-line">{{ interaction["subject"] or "Unknown" }}</div>
  </div>
  {% endfor %}
</div>
{% else %}
<p>No interactions yet.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_interactions_routes.py -v`
Expected: PASS — "Re: pricing", "Jane Smith", "Nexy", and "No interactions yet." are all preserved.

- [ ] **Step 3: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/templates/interactions_index.html
git commit -m "style: restyle Interactions as an activity feed"
```

---

### Task 11: Contacts — company-grouped, expandable

**Files:**
- Modify: `src/project_os/web/routes_contacts.py`
- Modify: `src/project_os/web/templates/contacts_index.html`

**Interfaces:**
- Consumes: `list_companies_with_contacts` from Task 2, `.company-group`/`.company-summary`/`.company-people` CSS from Task 5.

- [ ] **Step 1: Update the route**

```python
from fastapi import APIRouter, Request

from project_os.db import get_connection
from project_os.repositories.contacts import list_companies_with_contacts

router = APIRouter()


@router.get("/contacts")
def contacts_index(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        companies = list_companies_with_contacts(conn)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "contacts_index.html", {"companies": companies}
    )
```

- [ ] **Step 2: Update the template**

```html
{% extends "base.html" %}
{% block title %}Contacts — Project OS{% endblock %}
{% block content %}
<h2>Contacts</h2>
{% if companies %}
<div class="table-card">
  {% for company in companies %}
  <details class="company-group" {% if loop.first %}open{% endif %}>
    <summary class="company-summary">
      <span class="name">{{ company["name"] }}</span>
      <span class="meta">{{ company["people"] | length }} people</span>
    </summary>
    <div class="company-people">
      <table>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Role</th>
            <th scope="col">Email</th>
            <th scope="col">LinkedIn</th>
          </tr>
        </thead>
        <tbody>
          {% for person in company["people"] %}
          <tr>
            <td>{{ person["name"] }}</td>
            <td>{{ person["role"] or "Unknown" }}</td>
            <td>{{ person["email"] or "Unknown" }}</td>
            <td>
              {% if person["linkedin_url"] %}
              <a href="{{ person['linkedin_url'] }}">Profile</a>
              {% else %}
              Unknown
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </details>
  {% endfor %}
</div>
{% else %}
<p>No contacts yet.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 3: Run the tests**

Run: `python -m pytest tests/test_contacts_routes.py -v`
Expected: PASS — "Jane Smith" (an orphan contact with no `project_contacts` row in that test) surfaces inside the "Individuals" group, "jane@example.org" appears in her row, and "No contacts yet." shows when the DB is empty.

- [ ] **Step 4: Run the full suite for regressions**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/web/routes_contacts.py src/project_os/web/templates/contacts_index.html
git commit -m "feat: group global Contacts page by company with expandable people"
```

---

### Task 12: Nexy sheet import script

**Files:**
- Create: `src/project_os/import_nexy.py`
- Create: `tests/fixtures/nexy_sample.csv`
- Test: `tests/test_import_nexy.py`

**Interfaces:**
- Consumes: `get_or_create_organization`, `link_organization_to_project`, `find_contact_for_import`, `link_contact_to_project` (Task 2); `create_interaction`, `interaction_exists` (Task 3); `create_opportunity`, `get_opportunity_for_contact` (Task 4).
- Produces: `run_import(conn, project_id: int, csv_path: Path) -> dict[str, int]` (net new-row counts per table) and a `python -m project_os.import_nexy <csv> [--db PATH] [--project NAME]` CLI.

- [ ] **Step 1: Write the fixture CSV**

Create `tests/fixtures/nexy_sample.csv` with the real sheet's exact header plus 6 rows covering: a B2B org+contact, the same org's second contact (tests org dedup), a B2B org with no named contact yet (research-only), a B2C individual, a row with an unparseable date, and a duplicate email (tests contact dedup):

```csv
Type,Category,Subcategory,Company,Contact Name,Role / Title,Email,LinkedIn,Website,Country / Region,Lead Source,Priority,Stage,First Contact,Last Communication,Channel,What Was Sent,Response / Context,Next Step,Follow-up Date,Notes,Organization Type,Communicated?,Employees in Target Country (est.),Est. Blind/VI @ 0.5%,,,,,Account Name,Account Key,Contact Role,Account Control
B2B,Work,Workplace Accessibility,Example Org,Jane Smith,Director,jane@example.org,https://www.linkedin.com/in/janesmith/,https://example.org,United States,Research,High,Follow-up,,2026-08-10,Email,Intro email about Nexy,No reply yet,Follow up next week,2026-08-17,,Association / Nonprofit,Yes,,,,,,,Example Org,example-org,Decision Maker,CONTACTED ACCOUNT
B2B,Work,Workplace Accessibility,Example Org,John Doe,Coordinator,john@example.org,,https://example.org,United States,Research,Medium,Research,,,,,,,,,,Association / Nonprofit,,,,,,,,Example Org,example-org,Champion / Operational,CONTACTED ACCOUNT
B2B,Work,Employer Network,Research Only Org,,Accessibility Manager,accessibility@research-only.org,,https://research-only.org,Canada,Research,High,Research,,,,,,,,,,Large Employer,No,,,,,,,Research Only Org,research-only-org,,RESEARCH ACCOUNT
B2C,,,Individual,Sam Tester,Potential Tester,sam@example.com,,,,Previous users list,High,Follow-up,,2026-08-05,Email,Nexy testing invitation,No reply yet,Wait for install,,,,,,,,,,,Individual,individual,Contact,RESEARCH ACCOUNT
B2B,Education,Education / Training,Bad Date Org,Alex Unclear,Program Lead,alex@baddate.org,,https://baddate.org,United States,Research,Medium,Follow-up,,Not a real date,Email,Outreach sent,No reply yet,Wait,Not a real date either,,Association / Nonprofit,,,,,,,,Bad Date Org,bad-date-org,Decision Maker,CONTACTED ACCOUNT
B2B,Work,Workplace Accessibility,Duplicate Email Org,Jane Smith Again,Manager,jane@example.org,,https://duplicate.org,United States,Research,Medium,Research,,,,,,,,,,Large Employer,,,,,,,,Duplicate Email Org,duplicate-email-org,Decision Maker,RESEARCH ACCOUNT
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_import_nexy.py`:

```python
from pathlib import Path

import pytest

from project_os.db import get_connection, run_migrations
from project_os.import_nexy import run_import
from project_os.repositories.projects import create_project

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"
FIXTURE_CSV = Path(__file__).parent / "fixtures" / "nexy_sample.csv"


@pytest.fixture
def seeded_conn(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    return conn, project_id


def test_import_creates_organizations_contacts_opportunities_and_interactions(seeded_conn):
    conn, project_id = seeded_conn

    summary = run_import(conn, project_id, FIXTURE_CSV)

    # Example Org, Research Only Org, Bad Date Org, Duplicate Email Org = 4
    # (Individual is not an organization)
    assert summary["organizations"] == 4
    # Jane Smith, John Doe, Sam Tester, Alex Unclear = 4
    # ("Jane Smith Again" shares jane@example.org with Jane Smith -> same contact)
    assert summary["contacts"] == 4
    # Jane Smith, John Doe, Alex Unclear, Jane Smith Again's row (B2B, contact exists) = opportunities;
    # Research Only Org has no named contact -> no opportunity; Sam Tester is B2C -> no opportunity
    assert summary["opportunities"] == 4
    # Only rows with a valid YYYY-MM-DD Last Communication: Jane Smith row + Sam Tester row = 2
    assert summary["interactions"] == 2

    jane = conn.execute("SELECT * FROM contacts WHERE email = 'jane@example.org'").fetchone()
    assert jane is not None
    links = conn.execute(
        "SELECT * FROM project_contacts WHERE contact_id = ?", (jane["id"],)
    ).fetchall()
    assert len(links) == 1  # Jane Smith and "Jane Smith Again" merged into one project_contacts row

    research_only = conn.execute(
        "SELECT * FROM organizations WHERE name = 'Research Only Org'"
    ).fetchone()
    assert research_only is not None
    org_link = conn.execute(
        "SELECT * FROM project_organizations WHERE organization_id = ?", (research_only["id"],)
    ).fetchone()
    assert org_link["status"] == "Research"

    bad_date_contact = conn.execute("SELECT * FROM contacts WHERE email = 'alex@baddate.org'").fetchone()
    interactions_for_bad_date = conn.execute(
        "SELECT * FROM interactions WHERE contact_id = ?", (bad_date_contact["id"],)
    ).fetchall()
    assert interactions_for_bad_date == []  # unparseable date -> no interaction row


def test_import_is_idempotent(seeded_conn):
    conn, project_id = seeded_conn

    run_import(conn, project_id, FIXTURE_CSV)
    counts_after_first = _counts(conn)

    run_import(conn, project_id, FIXTURE_CSV)
    counts_after_second = _counts(conn)

    assert counts_after_first == counts_after_second


def _counts(conn):
    return {
        "organizations": conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0],
        "contacts": conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
        "project_contacts": conn.execute("SELECT COUNT(*) FROM project_contacts").fetchone()[0],
        "opportunities": conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0],
        "interactions": conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0],
    }
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `python -m pytest tests/test_import_nexy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'project_os.import_nexy'`

- [ ] **Step 4: Implement the import script**

Create `src/project_os/import_nexy.py`:

```python
"""One-time, idempotent import of the Nexy outreach spreadsheet into the DB.

Usage:
    python -m project_os.import_nexy data/imports/nexy_outreach.csv
    python -m project_os.import_nexy data/imports/nexy_outreach.csv --db data/project_os.sqlite --project Nexy
"""
import argparse
import csv
import re
import sys
from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.contacts import (
    create_contact,
    find_contact_for_import,
    get_or_create_organization,
    link_contact_to_project,
    link_organization_to_project,
)
from project_os.repositories.interactions import create_interaction, interaction_exists
from project_os.repositories.opportunities import create_opportunity, get_opportunity_for_contact
from project_os.repositories.projects import list_projects

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

ACCOUNT_CONTROL_TO_ORG_STATUS = {
    "RESEARCH ACCOUNT": "Research",
    "CONTACTED ACCOUNT": "Contacted",
    "ACTIVE ACCOUNT": "Engaged",
    "ARCHIVE / SKIP": "Closed",
}

STAGE_TO_PIPELINE_STAGE = {
    "Research": "Research",
    "Ready to Contact": "Ready to contact",
    "Contacted": "Contacted",
    "Follow-up": "Contacted",
    "Engaged": "Interested",
    "Meeting Scheduled": "Meeting booked",
    "Installed / Active Tester": "Pilot",
    "Paused / External Dependency": "Interested",
    "Closed Lost / Not Target": "Closed",
}

STATUS_NOISE = {"", "Low", "Medium", "High", "Medium-High", "Funding research", "NEW"}
VALID_PRIORITIES = {"Low", "Medium", "High"}


def clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def truncate(value: str | None, length: int) -> str | None:
    value = clean(value)
    if value is None:
        return None
    return value if len(value) <= length else value[: length - 1].rstrip() + "…"


def parse_iso_date(value: str | None) -> str | None:
    value = clean(value)
    if value and ISO_DATE_RE.match(value):
        return value
    return None


def first_email(value: str | None) -> str | None:
    if not value:
        return None
    match = EMAIL_RE.search(value)
    return match.group(0) if match else None


def project_contact_status(stage_raw: str | None) -> str:
    stage = clean(stage_raw)
    if stage is None or stage in STATUS_NOISE:
        return "Research"
    return stage


def opportunity_stage(stage_raw: str | None) -> tuple[str, str | None]:
    stage = clean(stage_raw)
    if stage is None:
        return "Research", None
    mapped = STAGE_TO_PIPELINE_STAGE.get(stage)
    if mapped:
        return mapped, None
    return "Research", f"Sheet stage: {stage}"


def import_row(conn, project_id: int, row: dict) -> None:
    row_type = clean(row.get("Type"))
    org_name = clean(row.get("Account Name")) or clean(row.get("Company"))
    contact_name = clean(row.get("Contact Name"))

    organization_id = None
    if org_name and org_name != "Individual":
        organization_id = get_or_create_organization(conn, org_name, website=clean(row.get("Website")))
        segment_parts = [p for p in [clean(row.get("Category")), clean(row.get("Subcategory"))] if p]
        link_organization_to_project(
            conn,
            project_id,
            organization_id,
            segment=" / ".join(segment_parts) or None,
            relevance=clean(row.get("Organization Type")),
            status=ACCOUNT_CONTROL_TO_ORG_STATUS.get(clean(row.get("Account Control")) or "", "Research"),
        )

    if not contact_name:
        return

    email = first_email(row.get("Email"))
    linkedin_url = clean(row.get("LinkedIn"))
    existing = find_contact_for_import(conn, contact_name, email)
    contact_id = (
        existing["id"]
        if existing is not None
        else create_contact(conn, contact_name, email=email, linkedin_url=linkedin_url)
    )

    already_linked = conn.execute(
        "SELECT id FROM project_contacts WHERE project_id = ? AND contact_id = ?",
        (project_id, contact_id),
    ).fetchone()
    if already_linked is None:
        priority_raw = clean(row.get("Priority"))
        link_contact_to_project(
            conn,
            project_id,
            contact_id,
            status=project_contact_status(row.get("Stage")),
            priority=priority_raw if priority_raw in VALID_PRIORITIES else "Medium",
            pitch=truncate(row.get("What Was Sent"), 500),
            role=clean(row.get("Contact Role")) or clean(row.get("Role / Title")),
            organization_id=organization_id,
        )

    if row_type in {"B2B", "Partner"} and get_opportunity_for_contact(conn, project_id, contact_id) is None:
        stage, note = opportunity_stage(row.get("Stage"))
        blocker = truncate(row.get("Response / Context"), 400)
        if note:
            blocker = f"{note}. {blocker}" if blocker else note
        create_opportunity(
            conn,
            project_id,
            contact_id=contact_id,
            organization_id=organization_id,
            stage=stage,
            offer=clean(row.get("Subcategory")),
            blocker=blocker,
            next_action=clean(row.get("Next Step")),
            next_action_due=parse_iso_date(row.get("Follow-up Date")),
        )

    interaction_date = parse_iso_date(row.get("Last Communication"))
    if interaction_date:
        created_at = f"{interaction_date} 00:00:00"
        subject = truncate(row.get("What Was Sent"), 120)
        if not interaction_exists(conn, contact_id, subject, created_at):
            create_interaction(
                conn,
                project_id,
                contact_id,
                channel=clean(row.get("Channel")) or "Unknown",
                direction="outbound",
                subject=subject,
                ai_summary=truncate(row.get("Response / Context"), 500),
                intent=None,
                external_message_id=None,
                source="import-nexy-sheet",
                created_at=created_at,
            )


def _counts(conn) -> dict[str, int]:
    return {
        "organizations": conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0],
        "contacts": conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
        "opportunities": conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0],
        "interactions": conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0],
    }


def run_import(conn, project_id: int, csv_path: Path) -> dict[str, int]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader if any((v or "").strip() for v in row.values())]

    before = _counts(conn)
    conn.execute("BEGIN")
    try:
        for row in rows:
            import_row(conn, project_id, row)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    after = _counts(conn)
    return {key: after[key] - before[key] for key in after}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--db", default="data/project_os.sqlite")
    parser.add_argument("--project", default="Nexy")
    args = parser.parse_args()

    conn = get_connection(args.db)
    run_migrations(conn, MIGRATIONS_DIR)
    project = next(
        (p for p in list_projects(conn, active_only=False) if p["name"] == args.project), None
    )
    if project is None:
        print(f"No project named {args.project!r} found in {args.db}", file=sys.stderr)
        raise SystemExit(1)

    summary = run_import(conn, project["id"], args.csv_path)
    conn.close()
    print(
        f"Imported {summary['organizations']} organizations, {summary['contacts']} contacts, "
        f"{summary['opportunities']} opportunities, {summary['interactions']} interactions."
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_import_nexy.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full suite for regressions**

Run: `python -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 7: Commit**

```bash
cd /Users/sergiyzasorin/ProjectOS
git add src/project_os/import_nexy.py tests/test_import_nexy.py tests/fixtures/nexy_sample.csv
git commit -m "feat: idempotent import script for the Nexy outreach spreadsheet"
```

---

### Task 13: Run the real import and visually verify against the mockup

**Files:** none (verification-only task; the CSV was already staged at `data/imports/nexy_outreach.csv` during brainstorming, gitignored).

**Interfaces:** none — this task only runs what Tasks 1–12 built.

- [ ] **Step 1: Run the full test suite one more time**

Run: `python -m pytest tests/ -v`
Expected: PASS — every test in the repo.

- [ ] **Step 2: Back up the real DB before writing real data into it**

```bash
cd /Users/sergiyzasorin/ProjectOS
cp data/project_os.sqlite "data/project_os.sqlite.bak-$(date +%Y%m%d-%H%M%S)"
```

- [ ] **Step 3: Run the real import**

```bash
cd /Users/sergiyzasorin/ProjectOS
python -m project_os.import_nexy data/imports/nexy_outreach.csv
```

Expected output: a line like `Imported N organizations, N contacts, N opportunities, N interactions.` with no traceback. If it errors, read the traceback — do not retry blindly; the most likely failure is a `ValueError: Unknown stage` from `create_opportunity` if a sheet `Stage` value maps to something outside `pipeline.STAGES`, which means `STAGE_TO_PIPELINE_STAGE` in `import_nexy.py` needs another entry.

- [ ] **Step 4: Spot-check the imported data**

```bash
cd /Users/sergiyzasorin/ProjectOS
sqlite3 data/project_os.sqlite "SELECT COUNT(*) FROM organizations;"
sqlite3 data/project_os.sqlite "SELECT COUNT(*) FROM contacts;"
sqlite3 data/project_os.sqlite "SELECT name FROM organizations ORDER BY name LIMIT 10;"
sqlite3 data/project_os.sqlite "SELECT stage, COUNT(*) FROM opportunities GROUP BY stage ORDER BY 2 DESC;"
```

Expected: organizations count in the low hundreds, contacts in the low hundreds, recognizable company names (CNIB, Perkins School for the Blind, National Federation of the Blind, etc.), and a stage breakdown with no obviously wrong bucket dominating.

- [ ] **Step 5: Start the app and visually verify each page**

```bash
cd /Users/sergiyzasorin/ProjectOS
python -m project_os.daemon &
```

This runs `uvicorn` on `http://127.0.0.1:8765` (confirmed in `src/project_os/daemon.py:111`). If a daemon is already running under the LaunchAgent (`launchagent/com.projectos.daemon.plist`), skip this step and use the already-running instance on the same port instead of starting a second one.

Use the Browser tool to open `http://127.0.0.1:8765/action-center`, `/projects`, `/contacts`, `/interactions`, `/projects/1`, `/projects/1/pipeline`, `/projects/1/linkedin` (substituting the real Nexy project id from Step 4 if not `1`). For each page, compare against the corresponding screen in `~/Desktop/Project OS CRM - standalone.html` and confirm: paper background, white cards with rounded borders, oklch blue accent on links/primary buttons, monospace uppercase table headers/badges, and — on `/contacts` — real company names as expandable groups with their people nested underneath.

- [ ] **Step 6: Stop the dev server**

```bash
kill %1
```

(No commit — this task only runs and verifies previously-committed code, plus writes real data into the gitignored `data/project_os.sqlite`.)
