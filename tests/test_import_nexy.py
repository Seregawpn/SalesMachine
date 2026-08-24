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
    # Jane Smith (Stage=Follow-up -> Contacted) and Alex Unclear (Stage=Follow-up -> Contacted) = 2
    # opportunities. John Doe (Stage=Research -> Research) is now skipped: import_row does not
    # create an opportunities row for Research-stage rows, since an unresearched prospect is not
    # yet a real pipeline deal and legitimately has no next action.
    # "Jane Smith Again" (Duplicate Email Org, Stage=Research) shares jane@example.org with Jane
    # Smith, so it resolves to the same contact_id and would be skipped either way (both because
    # its own stage is Research, and because get_opportunity_for_contact already finds Jane's
    # existing opportunity from row 1).
    # Research Only Org has no named contact -> no opportunity; Sam Tester is B2C -> no opportunity
    assert summary["opportunities"] == 2
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
