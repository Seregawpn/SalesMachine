from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import (
    create_organization,
    create_contact,
    link_contact_to_project,
    get_project_contact,
    list_project_contacts,
    get_contact_by_email,
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


def test_get_contact_by_email_finds_existing_contact(tmp_db_path):
    conn = _conn(tmp_db_path)
    create_contact(conn, "Jane Smith", email="Jane@Example.org")

    found = get_contact_by_email(conn, "jane@example.org")
    missing = get_contact_by_email(conn, "nobody@example.org")

    assert found is not None
    assert found["name"] == "Jane Smith"
    assert missing is None
