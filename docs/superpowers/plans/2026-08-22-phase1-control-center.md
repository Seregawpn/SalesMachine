# Project OS — Phase 1: Control Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local-first "control center" foundation of Project OS — SQLite CRM schema, a background daemon skeleton with a scheduler and daily backups, and a table-first, accessible web UI (Action Center, Project Overview, Pipeline, manual LinkedIn tracking) — with no Gmail, Calendar, or AI integration yet.

**Architecture:** A single Python process (`project_os.daemon`) owns a SQLite database (WAL mode, single-writer) and runs two things in that process: a FastAPI app (served by uvicorn) that is the only reader/writer-facing interface, and a simple in-process scheduler loop that runs periodic jobs (backups, consistency checks) against the same database. The browser is a pure control surface — closing it does not stop the daemon. All templates render server-side (Jinja2 + htmx) so there is no separate frontend build step and semantic HTML is guaranteed.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, htmx (loaded from a vendored static file, no CDN), SQLite (stdlib `sqlite3`), pytest, `fastapi.testclient.TestClient`.

## Global Constraints

- Local-only, zero recurring infrastructure cost — no cloud database, no paid API, no hosted queue (spec: 02_Project_OS_Architecture §19; 05_Decisions_And_Amendments §2.1).
- SQLite is the sole source of truth, opened in WAL mode with single-writer discipline (02_Project_OS_Architecture §18).
- Schema changes ship as numbered SQL files (`NNNN_description.sql`) applied in order, tracked in a `schema_version` table (05_Decisions_And_Amendments §3.7).
- Opportunity pipeline stages, in order, are exactly: `Research`, `Ready to contact`, `Contacted`, `Replied`, `Meeting booked`, `Meeting completed`, `Interested`, `Pilot discussion`, `Proposal`, `Pilot`, `Paid`, `Closed` (01_Project_OS_Requirements §4). Stage history is never overwritten — every stage change is logged to `audit_log`.
- Every active (non-`Closed`) opportunity must have a next action and due date, or the automation must flag it (03_Project_OS_Automation_Logic §1, §11).
- LinkedIn state changes are always user-confirmed; the system never scrapes or bot-automates LinkedIn (05_Decisions_And_Amendments §3.1).
- UI is table-first: one record per row, fixed columns, no information conveyed by color alone, no required drag-and-drop, full keyboard operation, semantic `<table>` markup with real headers (04_Project_OS_UI_UX_Specification §3, §13, §18).
- Daily local backup of the SQLite file, retaining the last 30 snapshots (05_Decisions_And_Amendments §3.4).
- This is a new, standalone repository at `~/ProjectOS`, unrelated to any other project's git history or release process.

---

## File Structure

```
~/ProjectOS/
  pyproject.toml
  src/project_os/
    __init__.py
    db.py                          # connection + migration runner
    migrations/
      0001_init.sql
      0002_linkedin_fields.sql
    repositories/
      __init__.py
      projects.py
      contacts.py
      opportunities.py
      actions.py
      linkedin.py
    rules/
      __init__.py
      pipeline_consistency.py
    scheduler.py
    backup.py
    daemon.py
    web/
      __init__.py
      app.py
      routes_action_center.py
      routes_projects.py
      routes_pipeline.py
      routes_linkedin.py
      templates/
        base.html
        action_center.html
        project_overview.html
        pipeline.html
        linkedin_queue.html
      static/
        htmx.min.js
        style.css
  launchagent/
    com.projectos.daemon.plist
  tests/
    conftest.py
    test_db.py
    test_projects_repo.py
    test_contacts_repo.py
    test_opportunities_repo.py
    test_actions_repo.py
    test_pipeline_consistency.py
    test_linkedin_repo.py
    test_backup.py
    test_scheduler.py
    test_action_center_routes.py
    test_pipeline_routes.py
    test_linkedin_routes.py
    test_daemon.py
```

---

### Task 1: Project scaffolding + SQLite migration runner

**Files:**
- Create: `pyproject.toml`
- Create: `src/project_os/__init__.py`
- Create: `src/project_os/db.py`
- Create: `src/project_os/migrations/0001_init.sql`
- Test: `tests/conftest.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `get_connection(db_path: str) -> sqlite3.Connection`, `run_migrations(conn: sqlite3.Connection, migrations_dir: pathlib.Path) -> int` (returns the new schema version).

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "project-os"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "jinja2>=3.1",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
pythonpath = ["src"]
```

- [ ] **Step 2: Create the package init and migrations directory**

```bash
mkdir -p src/project_os/migrations
touch src/project_os/__init__.py
```

- [ ] **Step 3: Write the failing test for the migration runner**

```python
# tests/conftest.py
import pathlib
import sqlite3
import pytest

@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "project_os.sqlite")
```

```python
# tests/test_db.py
import sqlite3
from pathlib import Path

from project_os.db import get_connection, run_migrations

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def test_run_migrations_creates_core_tables(tmp_db_path):
    conn = get_connection(tmp_db_path)
    version = run_migrations(conn, MIGRATIONS_DIR)
    assert version == 1

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for expected in {
        "schema_version",
        "projects",
        "organizations",
        "contacts",
        "project_organizations",
        "project_contacts",
        "opportunities",
        "actions",
        "audit_log",
    }:
        assert expected in tables


def test_run_migrations_is_idempotent(tmp_db_path):
    conn = get_connection(tmp_db_path)
    first = run_migrations(conn, MIGRATIONS_DIR)
    second = run_migrations(conn, MIGRATIONS_DIR)
    assert first == second == 1

    count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert count == 1


def test_get_connection_enables_wal_mode(tmp_db_path):
    conn = get_connection(tmp_db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os'` (or `ImportError`).

- [ ] **Step 5: Write `src/project_os/db.py`**

```python
import re
import sqlite3
from pathlib import Path


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
    )


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return row["v"] or 0


def run_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> int:
    _ensure_schema_version_table(conn)
    current = _current_version(conn)

    migration_files = sorted(
        migrations_dir.glob("*.sql"),
        key=lambda p: int(re.match(r"(\d+)_", p.name).group(1)),
    )

    for path in migration_files:
        number = int(re.match(r"(\d+)_", path.name).group(1))
        if number <= current:
            continue
        sql = path.read_text()
        conn.execute("BEGIN")
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (number,)
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = number

    return current
```

- [ ] **Step 6: Write `src/project_os/migrations/0001_init.sql`**

```sql
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    website TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    linkedin_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE project_organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    segment TEXT,
    relevance TEXT,
    status TEXT NOT NULL DEFAULT 'Research',
    UNIQUE(project_id, organization_id)
);

CREATE TABLE project_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    status TEXT NOT NULL DEFAULT 'Research',
    priority TEXT NOT NULL DEFAULT 'Medium',
    pitch TEXT,
    linkedin_state TEXT NOT NULL DEFAULT 'Not started',
    linkedin_last_action_at TEXT,
    linkedin_next_action_due TEXT,
    UNIQUE(project_id, contact_id)
);

CREATE TABLE opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    contact_id INTEGER REFERENCES contacts(id),
    organization_id INTEGER REFERENCES organizations(id),
    stage TEXT NOT NULL DEFAULT 'Research',
    offer TEXT,
    value REAL,
    blocker TEXT,
    next_action TEXT,
    next_action_due TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    module TEXT NOT NULL,
    linked_table TEXT,
    linked_id INTEGER,
    reason TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'P2',
    due_date TEXT,
    suggested_message TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    actor TEXT NOT NULL,
    entity_table TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    reason TEXT
);
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `python -m pytest tests/test_db.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml src/project_os/__init__.py src/project_os/db.py src/project_os/migrations/0001_init.sql tests/conftest.py tests/test_db.py
git commit -m "feat: SQLite schema and migration runner"
```

---

### Task 2: Projects repository

**Files:**
- Create: `src/project_os/repositories/__init__.py`
- Create: `src/project_os/repositories/projects.py`
- Test: `tests/test_projects_repo.py`

**Interfaces:**
- Consumes: `get_connection`, `run_migrations` from Task 1.
- Produces: `create_project(conn, name: str, description: str | None = None) -> int`, `list_projects(conn, active_only: bool = True) -> list[sqlite3.Row]`, `get_project(conn, project_id: int) -> sqlite3.Row | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_projects_repo.py
from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project, list_projects, get_project

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _conn(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    return conn


def test_create_and_get_project(tmp_db_path):
    conn = _conn(tmp_db_path)
    project_id = create_project(conn, "Nexy", description="Accessibility voice assistant")
    row = get_project(conn, project_id)
    assert row["name"] == "Nexy"
    assert row["active"] == 1


def test_list_projects_filters_inactive(tmp_db_path):
    conn = _conn(tmp_db_path)
    create_project(conn, "Nexy")
    other_id = create_project(conn, "Old Project")
    conn.execute("UPDATE projects SET active = 0 WHERE id = ?", (other_id,))

    active = list_projects(conn)
    all_projects = list_projects(conn, active_only=False)

    assert [p["name"] for p in active] == ["Nexy"]
    assert len(all_projects) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_projects_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.repositories'`

- [ ] **Step 3: Write `src/project_os/repositories/__init__.py`** (empty file)

- [ ] **Step 4: Write `src/project_os/repositories/projects.py`**

```python
import sqlite3


def create_project(conn: sqlite3.Connection, name: str, description: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO projects (name, description) VALUES (?, ?)",
        (name, description),
    )
    return cur.lastrowid


def list_projects(conn: sqlite3.Connection, active_only: bool = True) -> list[sqlite3.Row]:
    if active_only:
        return conn.execute(
            "SELECT * FROM projects WHERE active = 1 ORDER BY name"
        ).fetchall()
    return conn.execute("SELECT * FROM projects ORDER BY name").fetchall()


def get_project(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_projects_repo.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add src/project_os/repositories/__init__.py src/project_os/repositories/projects.py tests/test_projects_repo.py
git commit -m "feat: projects repository"
```

---

### Task 3: Canonical contacts/organizations + project relations

**Files:**
- Create: `src/project_os/repositories/contacts.py`
- Test: `tests/test_contacts_repo.py`

**Interfaces:**
- Consumes: `get_connection`, `run_migrations`, `create_project` from Tasks 1–2.
- Produces: `create_organization(conn, name, website=None) -> int`, `create_contact(conn, name, email=None, linkedin_url=None) -> int`, `link_contact_to_project(conn, project_id, contact_id, status="Research", priority="Medium") -> int` (returns `project_contacts.id`), `get_project_contact(conn, project_id, contact_id) -> sqlite3.Row | None`, `list_project_contacts(conn, project_id) -> list[sqlite3.Row]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_contacts_repo.py
from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import (
    create_organization,
    create_contact,
    link_contact_to_project,
    get_project_contact,
    list_project_contacts,
)

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _conn(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    return conn


def test_link_contact_to_project(tmp_db_path):
    conn = _conn(tmp_db_path)
    project_id = create_project(conn, "Nexy")
    org_id = create_organization(conn, "Example Org")
    contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")

    link_id = link_contact_to_project(conn, project_id, contact_id, status="Contacted", priority="High")

    row = get_project_contact(conn, project_id, contact_id)
    assert row["id"] == link_id
    assert row["status"] == "Contacted"
    assert row["priority"] == "High"
    assert row["name"] == "Jane Smith"
    assert row["email"] == "jane@example.org"


def test_same_contact_can_join_two_projects(tmp_db_path):
    conn = _conn(tmp_db_path)
    project_a = create_project(conn, "Nexy")
    project_b = create_project(conn, "AI Automation Services")
    contact_id = create_contact(conn, "Jane Smith")

    link_contact_to_project(conn, project_a, contact_id, status="Contacted")
    link_contact_to_project(conn, project_b, contact_id, status="Research")

    row_a = get_project_contact(conn, project_a, contact_id)
    row_b = get_project_contact(conn, project_b, contact_id)
    assert row_a["status"] == "Contacted"
    assert row_b["status"] == "Research"


def test_list_project_contacts(tmp_db_path):
    conn = _conn(tmp_db_path)
    project_id = create_project(conn, "Nexy")
    c1 = create_contact(conn, "Jane Smith")
    c2 = create_contact(conn, "John Doe")
    link_contact_to_project(conn, project_id, c1)
    link_contact_to_project(conn, project_id, c2)

    rows = list_project_contacts(conn, project_id)
    assert {r["name"] for r in rows} == {"Jane Smith", "John Doe"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_contacts_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.repositories.contacts'`

- [ ] **Step 3: Write `src/project_os/repositories/contacts.py`**

```python
import sqlite3


def create_organization(conn: sqlite3.Connection, name: str, website: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO organizations (name, website) VALUES (?, ?)", (name, website)
    )
    return cur.lastrowid


def create_contact(
    conn: sqlite3.Connection,
    name: str,
    email: str | None = None,
    linkedin_url: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO contacts (name, email, linkedin_url) VALUES (?, ?, ?)",
        (name, email, linkedin_url),
    )
    return cur.lastrowid


def link_contact_to_project(
    conn: sqlite3.Connection,
    project_id: int,
    contact_id: int,
    status: str = "Research",
    priority: str = "Medium",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO project_contacts (project_id, contact_id, status, priority)
        VALUES (?, ?, ?, ?)
        """,
        (project_id, contact_id, status, priority),
    )
    return cur.lastrowid


def get_project_contact(conn: sqlite3.Connection, project_id: int, contact_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT pc.*, c.name, c.email, c.linkedin_url AS contact_linkedin_url
        FROM project_contacts pc
        JOIN contacts c ON c.id = pc.contact_id
        WHERE pc.project_id = ? AND pc.contact_id = ?
        """,
        (project_id, contact_id),
    ).fetchone()


def list_project_contacts(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT pc.*, c.name, c.email, c.linkedin_url AS contact_linkedin_url
        FROM project_contacts pc
        JOIN contacts c ON c.id = pc.contact_id
        WHERE pc.project_id = ?
        ORDER BY c.name
        """,
        (project_id,),
    ).fetchall()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_contacts_repo.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/project_os/repositories/contacts.py tests/test_contacts_repo.py
git commit -m "feat: canonical contacts/organizations with per-project relations"
```

---

### Task 4: Opportunities & pipeline stages

**Files:**
- Create: `src/project_os/pipeline.py`
- Create: `src/project_os/repositories/opportunities.py`
- Test: `tests/test_opportunities_repo.py`

**Interfaces:**
- Consumes: `get_connection`, `run_migrations`, `create_project`, `create_contact`, `create_organization` from earlier tasks.
- Produces: `pipeline.STAGES: list[str]`, `create_opportunity(conn, project_id, contact_id=None, organization_id=None, stage="Research") -> int`, `update_stage(conn, opportunity_id, new_stage, actor="user") -> None` (raises `ValueError` for an unknown stage), `set_next_action(conn, opportunity_id, next_action, due_date) -> None`, `list_pipeline(conn, project_id) -> list[sqlite3.Row]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_opportunities_repo.py
from pathlib import Path
import pytest

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, create_organization
from project_os.repositories.opportunities import (
    create_opportunity,
    update_stage,
    set_next_action,
    list_pipeline,
)
from project_os.pipeline import STAGES

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith")
    org_id = create_organization(conn, "Example Org")
    return conn, project_id, contact_id, org_id


def test_stage_order_matches_spec():
    assert STAGES == [
        "Research", "Ready to contact", "Contacted", "Replied",
        "Meeting booked", "Meeting completed", "Interested",
        "Pilot discussion", "Proposal", "Pilot", "Paid", "Closed",
    ]


def test_create_opportunity_defaults_to_research_stage(tmp_db_path):
    conn, project_id, contact_id, org_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id)

    row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
    assert row["stage"] == "Research"


def test_update_stage_writes_audit_log(tmp_db_path):
    conn, project_id, contact_id, org_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id)

    update_stage(conn, opp_id, "Contacted", actor="user")

    row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
    assert row["stage"] == "Contacted"

    audit = conn.execute(
        "SELECT * FROM audit_log WHERE entity_table = 'opportunities' AND entity_id = ?",
        (opp_id,),
    ).fetchone()
    assert audit["field"] == "stage"
    assert audit["old_value"] == "Research"
    assert audit["new_value"] == "Contacted"
    assert audit["actor"] == "user"


def test_update_stage_rejects_unknown_stage(tmp_db_path):
    conn, project_id, contact_id, org_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id)

    with pytest.raises(ValueError):
        update_stage(conn, opp_id, "Not A Real Stage")


def test_list_pipeline_returns_joined_rows(tmp_db_path):
    conn, project_id, contact_id, org_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id)
    set_next_action(conn, opp_id, "Send proposal", "2026-09-01")

    rows = list_pipeline(conn, project_id)
    assert len(rows) == 1
    assert rows[0]["organization_name"] == "Example Org"
    assert rows[0]["contact_name"] == "Jane Smith"
    assert rows[0]["next_action"] == "Send proposal"
    assert rows[0]["next_action_due"] == "2026-09-01"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_opportunities_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.pipeline'`

- [ ] **Step 3: Write `src/project_os/pipeline.py`**

```python
STAGES = [
    "Research",
    "Ready to contact",
    "Contacted",
    "Replied",
    "Meeting booked",
    "Meeting completed",
    "Interested",
    "Pilot discussion",
    "Proposal",
    "Pilot",
    "Paid",
    "Closed",
]
```

- [ ] **Step 4: Write `src/project_os/repositories/opportunities.py`**

```python
import sqlite3

from project_os.pipeline import STAGES


def create_opportunity(
    conn: sqlite3.Connection,
    project_id: int,
    contact_id: int | None = None,
    organization_id: int | None = None,
    stage: str = "Research",
) -> int:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    cur = conn.execute(
        """
        INSERT INTO opportunities (project_id, contact_id, organization_id, stage)
        VALUES (?, ?, ?, ?)
        """,
        (project_id, contact_id, organization_id, stage),
    )
    return cur.lastrowid


def update_stage(conn: sqlite3.Connection, opportunity_id: int, new_stage: str, actor: str = "user") -> None:
    if new_stage not in STAGES:
        raise ValueError(f"Unknown stage: {new_stage}")

    row = conn.execute(
        "SELECT stage FROM opportunities WHERE id = ?", (opportunity_id,)
    ).fetchone()
    old_stage = row["stage"]

    conn.execute(
        "UPDATE opportunities SET stage = ?, updated_at = datetime('now') WHERE id = ?",
        (new_stage, opportunity_id),
    )
    conn.execute(
        """
        INSERT INTO audit_log (actor, entity_table, entity_id, field, old_value, new_value)
        VALUES (?, 'opportunities', ?, 'stage', ?, ?)
        """,
        (actor, opportunity_id, old_stage, new_stage),
    )


def set_next_action(conn: sqlite3.Connection, opportunity_id: int, next_action: str, due_date: str) -> None:
    conn.execute(
        """
        UPDATE opportunities
        SET next_action = ?, next_action_due = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (next_action, due_date, opportunity_id),
    )


def list_pipeline(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT o.*, org.name AS organization_name, c.name AS contact_name
        FROM opportunities o
        LEFT JOIN organizations org ON org.id = o.organization_id
        LEFT JOIN contacts c ON c.id = o.contact_id
        WHERE o.project_id = ?
        ORDER BY o.stage, o.updated_at DESC
        """,
        (project_id,),
    ).fetchall()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_opportunities_repo.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add src/project_os/pipeline.py src/project_os/repositories/opportunities.py tests/test_opportunities_repo.py
git commit -m "feat: opportunities repository with audited stage transitions"
```

---

### Task 5: Actions repository + missing-next-action consistency rule

**Files:**
- Create: `src/project_os/repositories/actions.py`
- Create: `src/project_os/rules/__init__.py`
- Create: `src/project_os/rules/pipeline_consistency.py`
- Test: `tests/test_actions_repo.py`
- Test: `tests/test_pipeline_consistency.py`

**Interfaces:**
- Consumes: `create_project`, `create_opportunity` from earlier tasks.
- Produces: `create_action(conn, project_id, module, reason, priority="P2", due_date=None, linked_table=None, linked_id=None, suggested_message=None) -> int`, `list_open_actions(conn, project_id=None) -> list[sqlite3.Row]` (ordered by priority then due_date), `complete_action(conn, action_id) -> None`, `snooze_action(conn, action_id, new_due_date) -> None`, `has_open_action_for(conn, linked_table, linked_id, reason) -> bool`; `rules.pipeline_consistency.check_missing_next_action(conn, project_id) -> int` (returns number of actions created).

- [ ] **Step 1: Write the failing test for the actions repository**

```python
# tests/test_actions_repo.py
from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.actions import (
    create_action,
    list_open_actions,
    complete_action,
    snooze_action,
    has_open_action_for,
)

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    return conn, project_id


def test_create_and_list_open_actions_ordered_by_priority(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    create_action(conn, project_id, module="Sales", reason="Low priority", priority="P3", due_date="2026-09-05")
    create_action(conn, project_id, module="Sales", reason="Urgent", priority="P0", due_date="2026-08-25")

    rows = list_open_actions(conn, project_id)
    assert [r["reason"] for r in rows] == ["Urgent", "Low priority"]


def test_complete_action_removes_it_from_open_list(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    action_id = create_action(conn, project_id, module="Sales", reason="Follow up")

    complete_action(conn, action_id)

    assert list_open_actions(conn, project_id) == []


def test_snooze_action_updates_due_date_and_keeps_it_open(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    action_id = create_action(conn, project_id, module="Sales", reason="Follow up", due_date="2026-08-25")

    snooze_action(conn, action_id, "2026-09-01")

    rows = list_open_actions(conn, project_id)
    assert rows[0]["due_date"] == "2026-09-01"


def test_has_open_action_for_prevents_duplicates(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    create_action(
        conn, project_id, module="Sales", reason="Missing next action",
        linked_table="opportunities", linked_id=42,
    )

    assert has_open_action_for(conn, "opportunities", 42, "Missing next action") is True
    assert has_open_action_for(conn, "opportunities", 999, "Missing next action") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_actions_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.repositories.actions'`

- [ ] **Step 3: Write `src/project_os/repositories/actions.py`**

```python
import sqlite3

_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


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
) -> int:
    cur = conn.execute(
        """
        INSERT INTO actions
            (project_id, module, linked_table, linked_id, reason, priority, due_date, suggested_message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, module, linked_table, linked_id, reason, priority, due_date, suggested_message),
    )
    return cur.lastrowid


def list_open_actions(conn: sqlite3.Connection, project_id: int | None = None) -> list[sqlite3.Row]:
    if project_id is None:
        rows = conn.execute("SELECT * FROM actions WHERE status = 'Open'").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM actions WHERE status = 'Open' AND project_id = ?", (project_id,)
        ).fetchall()

    return sorted(
        rows,
        key=lambda r: (
            _PRIORITY_ORDER.get(r["priority"], 9),
            r["due_date"] or "9999-99-99",
        ),
    )


def complete_action(conn: sqlite3.Connection, action_id: int) -> None:
    conn.execute(
        "UPDATE actions SET status = 'Completed', completed_at = datetime('now') WHERE id = ?",
        (action_id,),
    )


def snooze_action(conn: sqlite3.Connection, action_id: int, new_due_date: str) -> None:
    conn.execute("UPDATE actions SET due_date = ? WHERE id = ?", (new_due_date, action_id))


def has_open_action_for(conn: sqlite3.Connection, linked_table: str, linked_id: int, reason: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM actions
        WHERE status = 'Open' AND linked_table = ? AND linked_id = ? AND reason = ?
        """,
        (linked_table, linked_id, reason),
    ).fetchone()
    return row is not None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_actions_repo.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Write the failing test for the consistency rule**

```python
# tests/test_pipeline_consistency.py
from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.opportunities import create_opportunity, set_next_action, update_stage
from project_os.repositories.actions import list_open_actions
from project_os.rules.pipeline_consistency import check_missing_next_action

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    return conn, project_id


def test_flags_opportunity_with_no_next_action(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id)

    created = check_missing_next_action(conn, project_id)

    assert created == 1
    actions = list_open_actions(conn, project_id)
    assert actions[0]["reason"] == "Missing next action"
    assert actions[0]["linked_table"] == "opportunities"
    assert actions[0]["linked_id"] == opp_id
    assert actions[0]["priority"] == "P2"


def test_does_not_flag_opportunity_with_next_action(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id)
    set_next_action(conn, opp_id, "Send proposal", "2026-09-01")

    created = check_missing_next_action(conn, project_id)

    assert created == 0
    assert list_open_actions(conn, project_id) == []


def test_does_not_flag_closed_opportunity(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id)
    update_stage(conn, opp_id, "Closed")

    created = check_missing_next_action(conn, project_id)

    assert created == 0


def test_running_twice_does_not_duplicate_the_action(tmp_db_path):
    conn, project_id = _setup(tmp_db_path)
    create_opportunity(conn, project_id)

    check_missing_next_action(conn, project_id)
    second_run_created = check_missing_next_action(conn, project_id)

    assert second_run_created == 0
    assert len(list_open_actions(conn, project_id)) == 1
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_consistency.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.rules'`

- [ ] **Step 7: Write `src/project_os/rules/__init__.py`** (empty file)

- [ ] **Step 8: Write `src/project_os/rules/pipeline_consistency.py`**

```python
import sqlite3

from project_os.repositories.actions import create_action, has_open_action_for

_REASON = "Missing next action"


def check_missing_next_action(conn: sqlite3.Connection, project_id: int) -> int:
    rows = conn.execute(
        """
        SELECT id FROM opportunities
        WHERE project_id = ?
          AND stage != 'Closed'
          AND (next_action IS NULL OR next_action_due IS NULL)
        """,
        (project_id,),
    ).fetchall()

    created = 0
    for row in rows:
        opp_id = row["id"]
        if has_open_action_for(conn, "opportunities", opp_id, _REASON):
            continue
        create_action(
            conn,
            project_id,
            module="Sales",
            reason=_REASON,
            priority="P2",
            linked_table="opportunities",
            linked_id=opp_id,
        )
        created += 1
    return created
```

- [ ] **Step 9: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline_consistency.py -v`
Expected: PASS (4 tests)

- [ ] **Step 10: Commit**

```bash
git add src/project_os/repositories/actions.py src/project_os/rules tests/test_actions_repo.py tests/test_pipeline_consistency.py
git commit -m "feat: unified actions repository and missing-next-action rule"
```

---

### Task 6: LinkedIn manual state tracking

**Files:**
- Create: `src/project_os/migrations/0002_linkedin_fields.sql`
- Create: `src/project_os/repositories/linkedin.py`
- Test: `tests/test_linkedin_repo.py`

Note: `project_contacts.linkedin_state`, `linkedin_last_action_at`, and `linkedin_next_action_due` already exist from `0001_init.sql`. This migration only adds the CHECK constraint table used to validate transitions, since SQLite cannot add a CHECK constraint to an existing column via `ALTER TABLE`.

**Interfaces:**
- Consumes: `link_contact_to_project`, `create_action` from earlier tasks.
- Produces: `LINKEDIN_STATES: list[str]`, `set_linkedin_state(conn, project_contact_id, new_state, actor="user") -> None` (raises `ValueError` for an unknown state), `list_linkedin_queue(conn, project_id) -> dict[str, list[sqlite3.Row]]` grouped into `to_connect`, `pending_recheck`, `awaiting_message`, `awaiting_reply`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_linkedin_repo.py
from pathlib import Path
import pytest

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, link_contact_to_project
from project_os.repositories.actions import list_open_actions
from project_os.repositories.linkedin import set_linkedin_state, list_linkedin_queue, LINKEDIN_STATES

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _setup(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith")
    pc_id = link_contact_to_project(conn, project_id, contact_id)
    return conn, project_id, pc_id


def test_rejects_unknown_state(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)
    with pytest.raises(ValueError):
        set_linkedin_state(conn, pc_id, "Bogus State")


def test_accepted_creates_prepare_message_action(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)
    set_linkedin_state(conn, pc_id, "Accepted")

    row = conn.execute(
        "SELECT linkedin_state FROM project_contacts WHERE id = ?", (pc_id,)
    ).fetchone()
    assert row["linkedin_state"] == "Accepted"

    actions = list_open_actions(conn, project_id)
    assert any(a["reason"] == "Prepare first LinkedIn message" for a in actions)


def test_pending_connection_creates_recheck_action(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)
    set_linkedin_state(conn, pc_id, "Pending Connection")

    actions = list_open_actions(conn, project_id)
    assert any(a["reason"] == "Re-check LinkedIn connection status" for a in actions)


def test_list_linkedin_queue_groups_by_state(tmp_db_path):
    conn, project_id, pc_id = _setup(tmp_db_path)
    set_linkedin_state(conn, pc_id, "Pending Connection")

    queue = list_linkedin_queue(conn, project_id)
    assert len(queue["pending_recheck"]) == 1
    assert queue["to_connect"] == []


def test_linkedin_states_include_spec_values():
    assert LINKEDIN_STATES == [
        "Not started", "Pending Connection", "Accepted",
        "Message Sent", "Replied", "Not relevant",
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_linkedin_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.repositories.linkedin'`

- [ ] **Step 3: Write `src/project_os/migrations/0002_linkedin_fields.sql`**

```sql
-- Columns already exist from 0001_init.sql. This migration is a no-op
-- placeholder that reserves version 2 for the LinkedIn feature so future
-- LinkedIn-related schema changes have a clean place to append.
CREATE TABLE IF NOT EXISTS linkedin_state_reference (
    state TEXT PRIMARY KEY
);
INSERT OR IGNORE INTO linkedin_state_reference (state) VALUES
    ('Not started'), ('Pending Connection'), ('Accepted'),
    ('Message Sent'), ('Replied'), ('Not relevant');
```

- [ ] **Step 4: Write `src/project_os/repositories/linkedin.py`**

```python
import sqlite3

from project_os.repositories.actions import create_action

LINKEDIN_STATES = [
    "Not started",
    "Pending Connection",
    "Accepted",
    "Message Sent",
    "Replied",
    "Not relevant",
]


def set_linkedin_state(
    conn: sqlite3.Connection,
    project_contact_id: int,
    new_state: str,
    actor: str = "user",
) -> None:
    if new_state not in LINKEDIN_STATES:
        raise ValueError(f"Unknown LinkedIn state: {new_state}")

    row = conn.execute(
        "SELECT project_id, linkedin_state FROM project_contacts WHERE id = ?",
        (project_contact_id,),
    ).fetchone()
    project_id = row["project_id"]
    old_state = row["linkedin_state"]

    conn.execute(
        """
        UPDATE project_contacts
        SET linkedin_state = ?, linkedin_last_action_at = datetime('now')
        WHERE id = ?
        """,
        (new_state, project_contact_id),
    )
    conn.execute(
        """
        INSERT INTO audit_log (actor, entity_table, entity_id, field, old_value, new_value)
        VALUES (?, 'project_contacts', ?, 'linkedin_state', ?, ?)
        """,
        (actor, project_contact_id, old_state, new_state),
    )

    if new_state == "Accepted":
        create_action(
            conn, project_id, module="Sales",
            reason="Prepare first LinkedIn message", priority="P2",
            linked_table="project_contacts", linked_id=project_contact_id,
        )
    elif new_state == "Pending Connection":
        create_action(
            conn, project_id, module="Sales",
            reason="Re-check LinkedIn connection status", priority="P3",
            linked_table="project_contacts", linked_id=project_contact_id,
        )


def list_linkedin_queue(conn: sqlite3.Connection, project_id: int) -> dict[str, list[sqlite3.Row]]:
    rows = conn.execute(
        """
        SELECT pc.*, c.name, c.linkedin_url
        FROM project_contacts pc
        JOIN contacts c ON c.id = pc.contact_id
        WHERE pc.project_id = ?
        ORDER BY c.name
        """,
        (project_id,),
    ).fetchall()

    queue = {
        "to_connect": [],
        "pending_recheck": [],
        "awaiting_message": [],
        "awaiting_reply": [],
    }
    for row in rows:
        state = row["linkedin_state"]
        if state == "Not started":
            queue["to_connect"].append(row)
        elif state == "Pending Connection":
            queue["pending_recheck"].append(row)
        elif state == "Accepted":
            queue["awaiting_message"].append(row)
        elif state == "Message Sent":
            queue["awaiting_reply"].append(row)
    return queue
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_linkedin_repo.py -v`
Expected: PASS (5 tests)

- [ ] **Step 6: Commit**

```bash
git add src/project_os/migrations/0002_linkedin_fields.sql src/project_os/repositories/linkedin.py tests/test_linkedin_repo.py
git commit -m "feat: manual LinkedIn state tracking with follow-up actions"
```

---

### Task 7: Daily backup job + scheduler

**Files:**
- Create: `src/project_os/backup.py`
- Create: `src/project_os/scheduler.py`
- Test: `tests/test_backup.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Produces: `run_backup(db_path: str, backup_dir: pathlib.Path, now: datetime.date | None = None) -> pathlib.Path`, `prune_old_backups(backup_dir: pathlib.Path, keep: int = 30) -> None`, `Scheduler` class with `register(name: str, interval_seconds: int, func: Callable[[], None]) -> None` and `run_pending(now: float | None = None) -> list[str]` (returns names of jobs that ran).

- [ ] **Step 1: Write the failing test for backups**

```python
# tests/test_backup.py
import datetime
import sqlite3
from pathlib import Path

from project_os.backup import run_backup, prune_old_backups


def test_run_backup_copies_db_with_dated_filename(tmp_path):
    db_path = tmp_path / "project_os.sqlite"
    sqlite3.connect(db_path).close()
    backup_dir = tmp_path / "backups"

    result = run_backup(str(db_path), backup_dir, now=datetime.date(2026, 8, 22))

    assert result.name == "2026-08-22.sqlite"
    assert result.exists()


def test_prune_old_backups_keeps_only_the_newest(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for day in range(1, 36):
        (backup_dir / f"2026-01-{day:02d}.sqlite").write_text("x")

    prune_old_backups(backup_dir, keep=30)

    remaining = sorted(p.name for p in backup_dir.glob("*.sqlite"))
    assert len(remaining) == 30
    assert remaining[0] == "2026-01-06.sqlite"
    assert remaining[-1] == "2026-02-04.sqlite"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.backup'`

- [ ] **Step 3: Write `src/project_os/backup.py`**

```python
import datetime
import shutil
from pathlib import Path


def run_backup(db_path: str, backup_dir: Path, now: datetime.date | None = None) -> Path:
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    day = now or datetime.date.today()
    dest = backup_dir / f"{day.isoformat()}.sqlite"
    shutil.copyfile(db_path, dest)
    return dest


def prune_old_backups(backup_dir: Path, keep: int = 30) -> None:
    backup_dir = Path(backup_dir)
    snapshots = sorted(backup_dir.glob("*.sqlite"))
    excess = len(snapshots) - keep
    for path in snapshots[:max(excess, 0)]:
        path.unlink()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backup.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Write the failing test for the scheduler**

```python
# tests/test_scheduler.py
from project_os.scheduler import Scheduler


def test_run_pending_runs_job_on_first_call():
    calls = []
    scheduler = Scheduler()
    scheduler.register("backup", interval_seconds=3600, func=lambda: calls.append("backup"))

    ran = scheduler.run_pending(now=1000.0)

    assert ran == ["backup"]
    assert calls == ["backup"]


def test_run_pending_skips_job_before_interval_elapses():
    calls = []
    scheduler = Scheduler()
    scheduler.register("backup", interval_seconds=3600, func=lambda: calls.append("backup"))

    scheduler.run_pending(now=1000.0)
    ran_again = scheduler.run_pending(now=1500.0)

    assert ran_again == []
    assert calls == ["backup"]


def test_run_pending_runs_job_again_after_interval_elapses():
    calls = []
    scheduler = Scheduler()
    scheduler.register("backup", interval_seconds=3600, func=lambda: calls.append("backup"))

    scheduler.run_pending(now=1000.0)
    ran_later = scheduler.run_pending(now=1000.0 + 3600)

    assert ran_later == ["backup"]
    assert calls == ["backup", "backup"]
```

- [ ] **Step 6: Run test to verify it fails**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.scheduler'`

- [ ] **Step 7: Write `src/project_os/scheduler.py`**

```python
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class _Job:
    name: str
    interval_seconds: float
    func: Callable[[], None]
    last_run: float = 0.0


class Scheduler:
    def __init__(self) -> None:
        self._jobs: list[_Job] = []

    def register(self, name: str, interval_seconds: float, func: Callable[[], None]) -> None:
        self._jobs.append(_Job(name=name, interval_seconds=interval_seconds, func=func))

    def run_pending(self, now: float | None = None) -> list[str]:
        current = now if now is not None else time.time()
        ran = []
        for job in self._jobs:
            if current - job.last_run >= job.interval_seconds:
                job.func()
                job.last_run = current
                ran.append(job.name)
        return ran
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Commit**

```bash
git add src/project_os/backup.py src/project_os/scheduler.py tests/test_backup.py tests/test_scheduler.py
git commit -m "feat: daily backup job and in-process job scheduler"
```

---

### Task 8: FastAPI app shell + Action Center page

**Files:**
- Create: `src/project_os/web/__init__.py`
- Create: `src/project_os/web/app.py`
- Create: `src/project_os/web/routes_action_center.py`
- Create: `src/project_os/web/templates/base.html`
- Create: `src/project_os/web/templates/action_center.html`
- Create: `src/project_os/web/static/style.css`
- Test: `tests/test_action_center_routes.py`

**Interfaces:**
- Consumes: `get_connection`, `run_migrations`, `create_project`, `create_action`, `list_open_actions`, `complete_action`, `snooze_action` from earlier tasks.
- Produces: `create_app(db_path: str) -> fastapi.FastAPI`. Every later route-adding task extends this same `create_app` function.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_action_center_routes.py
from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.actions import create_action

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    create_action(conn, project_id, module="Sales", reason="Reply from decision maker", priority="P1", due_date="2026-08-22")
    conn.close()

    app = create_app(tmp_db_path)
    return TestClient(app), project_id


def test_action_center_lists_open_action_with_reason(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    response = client.get("/action-center")

    assert response.status_code == 200
    assert "Reply from decision maker" in response.text
    assert "<table" in response.text


def test_completing_an_action_removes_it_from_the_page(tmp_db_path):
    client, project_id = _client(tmp_db_path)

    action_id = client.get("/action-center").text
    # fetch the action id via the API layer directly for a stable test
    from project_os.db import get_connection
    conn = get_connection(tmp_db_path)
    row = conn.execute("SELECT id FROM actions LIMIT 1").fetchone()

    response = client.post(f"/actions/{row['id']}/complete", follow_redirects=True)

    assert response.status_code == 200
    assert "Reply from decision maker" not in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_action_center_routes.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.web'`

- [ ] **Step 3: Write `src/project_os/web/__init__.py`** (empty file)

- [ ] **Step 4: Write `src/project_os/web/app.py`**

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from project_os.db import get_connection, run_migrations

WEB_DIR = Path(__file__).parent
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(title="Project OS")
    app.state.db_path = db_path
    app.state.templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    conn = get_connection(db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    conn.close()

    from project_os.web.routes_action_center import router as action_center_router
    app.include_router(action_center_router)

    return app


def get_db(request):
    return get_connection(request.app.state.db_path)
```

- [ ] **Step 5: Write `src/project_os/web/routes_action_center.py`**

```python
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from project_os.db import get_connection
from project_os.repositories.actions import list_open_actions, complete_action, snooze_action

router = APIRouter()


@router.get("/action-center")
def action_center(request: Request):
    conn = get_connection(request.app.state.db_path)
    actions = list_open_actions(conn)
    conn.close()
    return request.app.state.templates.TemplateResponse(
        "action_center.html", {"request": request, "actions": actions}
    )


@router.post("/actions/{action_id}/complete")
def complete(request: Request, action_id: int):
    conn = get_connection(request.app.state.db_path)
    complete_action(conn, action_id)
    conn.close()
    return RedirectResponse(url="/action-center", status_code=303)


@router.post("/actions/{action_id}/snooze")
def snooze(request: Request, action_id: int, new_due_date: str):
    conn = get_connection(request.app.state.db_path)
    snooze_action(conn, action_id, new_due_date)
    conn.close()
    return RedirectResponse(url="/action-center", status_code=303)
```

- [ ] **Step 6: Write `src/project_os/web/templates/base.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{% block title %}Project OS{% endblock %}</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <a href="#main" class="skip-link">Skip to main content</a>
  <header>
    <h1>Project OS</h1>
    <nav aria-label="Primary">
      <a href="/action-center">Action Center</a>
    </nav>
  </header>
  <main id="main">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

- [ ] **Step 7: Write `src/project_os/web/templates/action_center.html`**

```html
{% extends "base.html" %}
{% block title %}Action Center — Project OS{% endblock %}
{% block content %}
<h2>Action Center</h2>
<table>
  <caption class="sr-only">Open actions across all projects</caption>
  <thead>
    <tr>
      <th scope="col">Priority</th>
      <th scope="col">Area</th>
      <th scope="col">Reason</th>
      <th scope="col">Due</th>
      <th scope="col">Action</th>
    </tr>
  </thead>
  <tbody>
    {% for action in actions %}
    <tr>
      <td>{{ action["priority"] }}</td>
      <td>{{ action["module"] }}</td>
      <td>{{ action["reason"] }}</td>
      <td>{{ action["due_date"] or "Unknown" }}</td>
      <td>
        <form method="post" action="/actions/{{ action['id'] }}/complete">
          <button type="submit">Done</button>
        </form>
      </td>
    </tr>
    {% else %}
    <tr><td colspan="5">Nothing needs attention right now.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 8: Write `src/project_os/web/static/style.css`**

```css
body { font-family: system-ui, sans-serif; margin: 0; padding: 0 1.5rem; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid #ccc; padding: 0.5rem; text-align: left; }
.skip-link { position: absolute; left: -9999px; }
.skip-link:focus { left: 0.5rem; top: 0.5rem; }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
```

- [ ] **Step 9: Run test to verify it passes**

Run: `python -m pytest tests/test_action_center_routes.py -v`
Expected: PASS (2 tests)

- [ ] **Step 10: Commit**

```bash
git add src/project_os/web tests/test_action_center_routes.py
git commit -m "feat: FastAPI app shell and Action Center page"
```

---

### Task 9: Project Overview + Pipeline UI

**Files:**
- Create: `src/project_os/web/routes_projects.py`
- Create: `src/project_os/web/routes_pipeline.py`
- Create: `src/project_os/web/templates/project_overview.html`
- Create: `src/project_os/web/templates/pipeline.html`
- Modify: `src/project_os/web/app.py` (register the two new routers)
- Modify: `src/project_os/web/templates/base.html` (add nav link pattern used by tests)
- Test: `tests/test_pipeline_routes.py`

**Interfaces:**
- Consumes: `list_pipeline`, `update_stage`, `list_open_actions` from earlier tasks; `create_app` from Task 8.
- Produces: routes `GET /projects/{project_id}`, `GET /projects/{project_id}/pipeline`, `POST /projects/{project_id}/pipeline/{opportunity_id}/stage`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_routes.py
from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, create_organization
from project_os.repositories.opportunities import create_opportunity
from project_os.pipeline import STAGES

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith")
    org_id = create_organization(conn, "Example Org")
    opp_id = create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id)
    conn.close()

    app = create_app(tmp_db_path)
    return TestClient(app), project_id, opp_id


def test_pipeline_page_lists_opportunity_in_a_table(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.get(f"/projects/{project_id}/pipeline")

    assert response.status_code == 200
    assert "Example Org" in response.text
    assert "Jane Smith" in response.text
    assert "<table" in response.text
    for stage in STAGES:
        assert stage in response.text  # stage dropdown lists every valid stage


def test_changing_stage_via_form_updates_pipeline(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/pipeline/{opp_id}/stage",
        data={"stage": "Contacted"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Contacted" in response.text


def test_project_overview_shows_needs_attention_actions(tmp_db_path):
    client, project_id, opp_id = _client(tmp_db_path)

    response = client.get(f"/projects/{project_id}")

    assert response.status_code == 200
    assert "Needs attention" in response.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline_routes.py -v`
Expected: FAIL with `404 Not Found` assertions / `ModuleNotFoundError` for `routes_pipeline`.

- [ ] **Step 3: Write `src/project_os/web/routes_pipeline.py`**

```python
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from project_os.db import get_connection
from project_os.repositories.opportunities import list_pipeline, update_stage
from project_os.pipeline import STAGES

router = APIRouter()


@router.get("/projects/{project_id}/pipeline")
def pipeline(request: Request, project_id: int):
    conn = get_connection(request.app.state.db_path)
    opportunities = list_pipeline(conn, project_id)
    conn.close()
    return request.app.state.templates.TemplateResponse(
        "pipeline.html",
        {"request": request, "project_id": project_id, "opportunities": opportunities, "stages": STAGES},
    )


@router.post("/projects/{project_id}/pipeline/{opportunity_id}/stage")
def change_stage(request: Request, project_id: int, opportunity_id: int, stage: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    update_stage(conn, opportunity_id, stage, actor="user")
    conn.close()
    return RedirectResponse(url=f"/projects/{project_id}/pipeline", status_code=303)
```

- [ ] **Step 4: Write `src/project_os/web/routes_projects.py`**

```python
from fastapi import APIRouter, Request

from project_os.db import get_connection
from project_os.repositories.projects import get_project
from project_os.repositories.actions import list_open_actions

router = APIRouter()

_HIGH_PRIORITY = {"P0", "P1"}


@router.get("/projects/{project_id}")
def project_overview(request: Request, project_id: int):
    conn = get_connection(request.app.state.db_path)
    project = get_project(conn, project_id)
    actions = list_open_actions(conn, project_id)
    conn.close()

    needs_attention = [a for a in actions if a["priority"] in _HIGH_PRIORITY]

    return request.app.state.templates.TemplateResponse(
        "project_overview.html",
        {"request": request, "project": project, "needs_attention": needs_attention},
    )
```

- [ ] **Step 5: Write `src/project_os/web/templates/pipeline.html`**

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
    <tr>
      <td>{{ opp["organization_name"] or "Unknown" }}</td>
      <td>{{ opp["contact_name"] or "Unknown" }}</td>
      <td>
        <form method="post" action="/projects/{{ project_id }}/pipeline/{{ opp['id'] }}/stage">
          <label for="stage-{{ opp['id'] }}" class="sr-only">Stage for {{ opp["organization_name"] }}</label>
          <select id="stage-{{ opp['id'] }}" name="stage" onchange="this.form.submit()">
            {% for stage in stages %}
            <option value="{{ stage }}" {% if stage == opp["stage"] %}selected{% endif %}>{{ stage }}</option>
            {% endfor %}
          </select>
          <noscript><button type="submit">Update stage</button></noscript>
        </form>
      </td>
      <td>{{ opp["value"] or "Unknown" }}</td>
      <td>{{ opp["blocker"] or "None" }}</td>
      <td>{{ opp["next_action"] or "Unknown" }}</td>
      <td>{{ opp["next_action_due"] or "Unknown" }}</td>
    </tr>
    {% else %}
    <tr><td colspan="7">No opportunities yet.</td></tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 6: Write `src/project_os/web/templates/project_overview.html`**

```html
{% extends "base.html" %}
{% block title %}{{ project["name"] }} — Project OS{% endblock %}
{% block content %}
<h2>{{ project["name"] }}</h2>
<section aria-labelledby="needs-attention-heading">
  <h3 id="needs-attention-heading">Needs attention</h3>
  <table>
    <caption class="sr-only">P0 and P1 actions for {{ project["name"] }}</caption>
    <thead>
      <tr>
        <th scope="col">Priority</th>
        <th scope="col">Reason</th>
        <th scope="col">Due</th>
      </tr>
    </thead>
    <tbody>
      {% for action in needs_attention %}
      <tr>
        <td>{{ action["priority"] }}</td>
        <td>{{ action["reason"] }}</td>
        <td>{{ action["due_date"] or "Unknown" }}</td>
      </tr>
      {% else %}
      <tr><td colspan="3">Nothing critical right now.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</section>
<p><a href="/projects/{{ project['id'] }}/pipeline">Open Sales Pipeline</a></p>
{% endblock %}
```

- [ ] **Step 7: Modify `src/project_os/web/app.py`** to register the two new routers (add inside `create_app`, after the existing `action_center_router` include):

```python
    from project_os.web.routes_projects import router as projects_router
    from project_os.web.routes_pipeline import router as pipeline_router
    app.include_router(projects_router)
    app.include_router(pipeline_router)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_pipeline_routes.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Run the full test suite to check for regressions**

Run: `python -m pytest -v`
Expected: All tests PASS.

- [ ] **Step 10: Commit**

```bash
git add src/project_os/web tests/test_pipeline_routes.py
git commit -m "feat: project overview and pipeline UI"
```

---

### Task 10: LinkedIn queue UI

**Files:**
- Create: `src/project_os/web/routes_linkedin.py`
- Create: `src/project_os/web/templates/linkedin_queue.html`
- Modify: `src/project_os/web/app.py` (register the new router)
- Test: `tests/test_linkedin_routes.py`

**Interfaces:**
- Consumes: `list_linkedin_queue`, `set_linkedin_state`, `LINKEDIN_STATES` from Task 6.
- Produces: routes `GET /projects/{project_id}/linkedin`, `POST /projects/{project_id}/linkedin/{project_contact_id}/state`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_linkedin_routes.py
from pathlib import Path

from fastapi.testclient import TestClient

from project_os.web.app import create_app
from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, link_contact_to_project

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def _client(tmp_db_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    contact_id = create_contact(conn, "Jane Smith")
    pc_id = link_contact_to_project(conn, project_id, contact_id)
    conn.close()

    app = create_app(tmp_db_path)
    return TestClient(app), project_id, pc_id


def test_linkedin_queue_lists_contact_to_connect(tmp_db_path):
    client, project_id, pc_id = _client(tmp_db_path)

    response = client.get(f"/projects/{project_id}/linkedin")

    assert response.status_code == 200
    assert "Jane Smith" in response.text
    assert "Connection sent" in response.text  # accessible button label, not icon-only


def test_confirming_connection_sent_moves_contact_to_pending(tmp_db_path):
    client, project_id, pc_id = _client(tmp_db_path)

    response = client.post(
        f"/projects/{project_id}/linkedin/{pc_id}/state",
        data={"state": "Pending Connection"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    from project_os.db import get_connection
    conn = get_connection(tmp_db_path)
    row = conn.execute(
        "SELECT linkedin_state FROM project_contacts WHERE id = ?", (pc_id,)
    ).fetchone()
    assert row["linkedin_state"] == "Pending Connection"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_linkedin_routes.py -v`
Expected: FAIL with `404 Not Found`

- [ ] **Step 3: Write `src/project_os/web/routes_linkedin.py`**

```python
from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from project_os.db import get_connection
from project_os.repositories.linkedin import list_linkedin_queue, set_linkedin_state

router = APIRouter()


@router.get("/projects/{project_id}/linkedin")
def linkedin_queue(request: Request, project_id: int):
    conn = get_connection(request.app.state.db_path)
    queue = list_linkedin_queue(conn, project_id)
    conn.close()
    return request.app.state.templates.TemplateResponse(
        "linkedin_queue.html", {"request": request, "project_id": project_id, "queue": queue}
    )


@router.post("/projects/{project_id}/linkedin/{project_contact_id}/state")
def update_linkedin_state(request: Request, project_id: int, project_contact_id: int, state: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    set_linkedin_state(conn, project_contact_id, state, actor="user")
    conn.close()
    return RedirectResponse(url=f"/projects/{project_id}/linkedin", status_code=303)
```

- [ ] **Step 4: Write `src/project_os/web/templates/linkedin_queue.html`**

```html
{% extends "base.html" %}
{% block title %}LinkedIn — Project OS{% endblock %}
{% block content %}
<h2>LinkedIn</h2>

<section aria-labelledby="to-connect-heading">
  <h3 id="to-connect-heading">To connect</h3>
  <table>
    <thead><tr><th scope="col">Name</th><th scope="col">Action</th></tr></thead>
    <tbody>
      {% for row in queue["to_connect"] %}
      <tr>
        <td>{{ row["name"] }}</td>
        <td>
          <form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state">
            <input type="hidden" name="state" value="Pending Connection">
            <button type="submit">Connection sent</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="2">Nothing to connect with right now.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</section>

<section aria-labelledby="pending-heading">
  <h3 id="pending-heading">Pending connections to re-check</h3>
  <table>
    <thead><tr><th scope="col">Name</th><th scope="col">Action</th></tr></thead>
    <tbody>
      {% for row in queue["pending_recheck"] %}
      <tr>
        <td>{{ row["name"] }}</td>
        <td>
          <form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state">
            <input type="hidden" name="state" value="Accepted">
            <button type="submit">Accepted</button>
          </form>
          <form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state">
            <input type="hidden" name="state" value="Not relevant">
            <button type="submit">Not relevant</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="2">Nothing pending.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</section>

<section aria-labelledby="awaiting-message-heading">
  <h3 id="awaiting-message-heading">Accepted connections awaiting a message</h3>
  <table>
    <thead><tr><th scope="col">Name</th><th scope="col">Action</th></tr></thead>
    <tbody>
      {% for row in queue["awaiting_message"] %}
      <tr>
        <td>{{ row["name"] }}</td>
        <td>
          <form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state">
            <input type="hidden" name="state" value="Message Sent">
            <button type="submit">Message sent</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="2">Nobody waiting on a message.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</section>

<section aria-labelledby="awaiting-reply-heading">
  <h3 id="awaiting-reply-heading">Conversations awaiting reply</h3>
  <table>
    <thead><tr><th scope="col">Name</th><th scope="col">Action</th></tr></thead>
    <tbody>
      {% for row in queue["awaiting_reply"] %}
      <tr>
        <td>{{ row["name"] }}</td>
        <td>
          <form method="post" action="/projects/{{ project_id }}/linkedin/{{ row['id'] }}/state">
            <input type="hidden" name="state" value="Replied">
            <button type="submit">Replied</button>
          </form>
        </td>
      </tr>
      {% else %}
      <tr><td colspan="2">No open conversations.</td></tr>
      {% endfor %}
    </tbody>
  </table>
</section>
{% endblock %}
```

- [ ] **Step 5: Modify `src/project_os/web/app.py`** to register the LinkedIn router (add after the pipeline router include):

```python
    from project_os.web.routes_linkedin import router as linkedin_router
    app.include_router(linkedin_router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_linkedin_routes.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add src/project_os/web tests/test_linkedin_routes.py
git commit -m "feat: LinkedIn manual tracking UI"
```

---

### Task 11: Daemon entrypoint + LaunchAgent

**Files:**
- Create: `src/project_os/daemon.py`
- Create: `launchagent/com.projectos.daemon.plist`
- Test: `tests/test_daemon.py`

**Interfaces:**
- Consumes: `create_app` (Task 8), `Scheduler` (Task 7), `run_backup`, `prune_old_backups` (Task 7), `check_missing_next_action` (Task 5), `list_projects` (Task 2).
- Produces: `build_scheduler(db_path: str, backup_dir: pathlib.Path) -> Scheduler`, `main() -> None` (module entrypoint, not directly unit tested).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_daemon.py
from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.opportunities import create_opportunity
from project_os.daemon import build_scheduler

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def test_scheduler_runs_backup_and_consistency_jobs(tmp_db_path, tmp_path):
    conn = get_connection(tmp_db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    project_id = create_project(conn, "Nexy")
    create_opportunity(conn, project_id)  # has no next action -> should get flagged
    conn.close()

    backup_dir = tmp_path / "backups"
    scheduler = build_scheduler(tmp_db_path, backup_dir)

    ran = scheduler.run_pending(now=0.0)

    assert "backup" in ran
    assert "pipeline_consistency" in ran
    assert list(backup_dir.glob("*.sqlite"))

    conn = get_connection(tmp_db_path)
    from project_os.repositories.actions import list_open_actions
    actions = list_open_actions(conn, project_id)
    assert any(a["reason"] == "Missing next action" for a in actions)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_daemon.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.daemon'`

- [ ] **Step 3: Write `src/project_os/daemon.py`**

```python
import time
from pathlib import Path

import uvicorn

from project_os.backup import run_backup, prune_old_backups
from project_os.db import get_connection
from project_os.repositories.projects import list_projects
from project_os.rules.pipeline_consistency import check_missing_next_action
from project_os.scheduler import Scheduler
from project_os.web.app import create_app

DB_PATH = str(Path.home() / "ProjectOS" / "data" / "project_os.sqlite")
BACKUP_DIR = Path.home() / "ProjectOS" / "data" / "backups"


def build_scheduler(db_path: str, backup_dir: Path) -> Scheduler:
    scheduler = Scheduler()

    def _backup_job() -> None:
        run_backup(db_path, backup_dir)
        prune_old_backups(backup_dir, keep=30)

    def _consistency_job() -> None:
        conn = get_connection(db_path)
        for project in list_projects(conn):
            check_missing_next_action(conn, project["id"])
        conn.close()

    scheduler.register("backup", interval_seconds=24 * 60 * 60, func=_backup_job)
    scheduler.register("pipeline_consistency", interval_seconds=15 * 60, func=_consistency_job)
    return scheduler


def main() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    app = create_app(DB_PATH)
    scheduler = build_scheduler(DB_PATH, BACKUP_DIR)

    import threading

    def _scheduler_loop() -> None:
        while True:
            scheduler.run_pending()
            time.sleep(60)

    threading.Thread(target=_scheduler_loop, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_daemon.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Write `launchagent/com.projectos.daemon.plist`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.projectos.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>python3</string>
    <string>-m</string>
    <string>project_os.daemon</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/YOUR_USERNAME/ProjectOS</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/YOUR_USERNAME/ProjectOS/data/daemon.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOUR_USERNAME/ProjectOS/data/daemon.err.log</string>
</dict>
</plist>
```

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `python -m pytest -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/project_os/daemon.py launchagent/com.projectos.daemon.plist tests/test_daemon.py
git commit -m "feat: daemon entrypoint with scheduler and LaunchAgent template"
```

---

### Task 12: Manual acceptance walk-through

**Files:** none (verification only).

**Interfaces:** none — this task exercises the running application through Task 11's `main()`.

- [ ] **Step 1: Install dependencies and run the full automated test suite**

```bash
cd ~/ProjectOS
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -v
```

Expected: every test from Tasks 1–11 passes.

- [ ] **Step 2: Start the daemon by hand (not via LaunchAgent yet)**

```bash
python -m project_os.daemon
```

Expected: server starts on `http://127.0.0.1:8765` with no errors; `~/ProjectOS/data/project_os.sqlite` is created.

- [ ] **Step 3: Seed one project manually for a smoke test**

```bash
python3 - <<'EOF'
from project_os.db import get_connection
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import create_contact, create_organization, link_contact_to_project
from project_os.repositories.opportunities import create_opportunity

conn = get_connection("/Users/YOUR_USERNAME/ProjectOS/data/project_os.sqlite")
project_id = create_project(conn, "Nexy")
org_id = create_organization(conn, "Example Org")
contact_id = create_contact(conn, "Jane Smith", email="jane@example.org")
link_contact_to_project(conn, project_id, contact_id)
create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id)
print("project_id:", project_id)
EOF
```

- [ ] **Step 4: Verify each screen in a browser**

Open `http://127.0.0.1:8765/action-center` — confirm the table renders (may be empty until the 15-minute consistency check runs; that's expected).
Open `http://127.0.0.1:8765/projects/<project_id>` — confirm "Needs attention" section renders.
Open `http://127.0.0.1:8765/projects/<project_id>/pipeline` — confirm Example Org / Jane Smith row appears with a working stage dropdown.
Open `http://127.0.0.1:8765/projects/<project_id>/linkedin` — confirm Jane Smith appears under "To connect" and clicking "Connection sent" moves her to "Pending connections to re-check".

- [ ] **Step 5: Verify keyboard-only navigation**

Using only Tab / Shift+Tab / Enter / Space (no mouse), confirm you can reach and activate: the skip link, the primary nav link, every table's action buttons/selects, and the LinkedIn state buttons.

- [ ] **Step 6: Verify against Phase 1 acceptance criteria**

Confirm each of the following is true (source: 04_Project_OS_UI_UX_Specification §25, scoped to Phase 1's modules):
- Every operational list (Action Center, Pipeline, LinkedIn queue) is a structured `<table>` with real `<th>` headers.
- No information is conveyed by color alone (Priority and Status are always shown as text).
- No control requires drag-and-drop; the pipeline stage change uses a `<select>`.
- An opportunity with a missing next action appears in the Action Center within 15 minutes without manual intervention.

- [ ] **Step 7: Install the LaunchAgent (optional — only if daily backups outside manual runs are needed now)**

```bash
sed "s/YOUR_USERNAME/$(whoami)/g" launchagent/com.projectos.daemon.plist > ~/Library/LaunchAgents/com.projectos.daemon.plist
launchctl load ~/Library/LaunchAgents/com.projectos.daemon.plist
```

Verify: `curl http://127.0.0.1:8765/action-center` returns 200 after logging out and back in.

---

## Self-Review Notes

- **Spec coverage:** CRM normalization + multi-project (01 §2–3, §15) → Tasks 1–3. Pipeline with preserved history (01 §4) → Task 4. Action Center + unified priority (01 §2, 03 §9) → Task 5, 8. Missing-next-action detection (03 §1, §11) → Task 5. Manual LinkedIn tracking (01 §6, 05 §3.1) → Task 6, 10. Daily backups (05 §3.4) → Task 7. Numbered migrations + schema_version (05 §3.7) → Task 1, 6. Table-first, keyboard/VoiceOver-friendly UI, no drag-and-drop (04 §3, §13, §18) → Tasks 8–10, verified in Task 12. LaunchAgent daemon, local-only (02 §17–18, 05 §2.1) → Task 11.
- **Explicitly out of scope for Phase 1** (deferred to later phases per 02 §13): Gmail sync, Calendar sync, AI drafting/classification, research campaigns, funding intelligence, Product module, Goals module, secrets/Keychain integration (not needed until an external integration exists), send-mistake recovery flow (needs sent-email tracking from Phase 2).
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code.
- **Type consistency:** `create_action` signature (Task 5) matches every call site in Tasks 5, 6, and 11. `list_open_actions` return type (`list[sqlite3.Row]`) is consistent everywhere it's consumed (Tasks 8, 9, 11). `STAGES` from Task 4 is the single source used by Task 9's dropdown — no duplicate stage list.
