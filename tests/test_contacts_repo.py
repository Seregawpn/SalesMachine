from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.repositories.contacts import (
    create_organization,
    create_contact,
    find_contact_for_import,
    get_or_create_organization,
    get_organization_by_name,
    link_contact_to_project,
    link_organization_to_project,
    list_companies_with_contacts,
    get_project_contact,
    list_project_contacts,
    get_contact_by_email,
    list_contacts,
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


def test_list_contacts_returns_every_contact_ordered_by_name(tmp_db_path):
    conn = _conn(tmp_db_path)
    create_contact(conn, "Zed Adams", email="zed@example.org")
    create_contact(conn, "Anna Baker", email="anna@example.org")

    contacts = list_contacts(conn)

    assert [c["name"] for c in contacts] == ["Anna Baker", "Zed Adams"]


def test_get_organization_by_name_is_case_insensitive(tmp_db_path):
    conn = _conn(tmp_db_path)
    create_organization(conn, "Example Org")

    found = get_organization_by_name(conn, "EXAMPLE org")

    assert found is not None
    assert found["name"] == "Example Org"
    assert get_organization_by_name(conn, "Nonexistent") is None


def test_get_or_create_organization_does_not_duplicate(tmp_db_path):
    conn = _conn(tmp_db_path)

    first_id = get_or_create_organization(conn, "Example Org", website="https://example.org")
    second_id = get_or_create_organization(conn, "example org")

    assert first_id == second_id
    count = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()[0]
    assert count == 1


def test_link_organization_to_project_is_idempotent(tmp_db_path):
    conn = _conn(tmp_db_path)
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
    conn = _conn(tmp_db_path)
    with_email = create_contact(conn, "Jane Smith", email="jane@example.org")
    no_email = create_contact(conn, "No Email Guy")

    assert find_contact_for_import(conn, "Different Name", "jane@example.org")["id"] == with_email
    assert find_contact_for_import(conn, "No Email Guy", None)["id"] == no_email
    assert find_contact_for_import(conn, "Nobody Here", None) is None


def test_link_contact_to_project_stores_role_pitch_and_organization(tmp_db_path):
    conn = _conn(tmp_db_path)
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
    conn = _conn(tmp_db_path)
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
    conn = _conn(tmp_db_path)

    assert list_companies_with_contacts(conn) == []
