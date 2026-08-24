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
    get_opportunity_for_contact,
    count_opportunities_by_stage,
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


def test_update_stage_raises_lookup_error_for_missing_opportunity(tmp_db_path):
    conn, project_id, contact_id, org_id = _setup(tmp_db_path)

    with pytest.raises(LookupError):
        update_stage(conn, 999999, "Contacted")


def test_update_stage_raises_lookup_error_when_opportunity_belongs_to_different_project(tmp_db_path):
    conn, project_id, contact_id, org_id = _setup(tmp_db_path)
    opp_id = create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id)
    other_project_id = create_project(conn, "Other Project")

    with pytest.raises(LookupError):
        update_stage(conn, opp_id, "Contacted", project_id=other_project_id)

    row = conn.execute("SELECT stage FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
    assert row["stage"] == "Research"


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


def test_list_pipeline_orders_by_pipeline_stage_not_alphabetically(tmp_db_path):
    conn, project_id, contact_id, org_id = _setup(tmp_db_path)
    paid_id = create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id, stage="Paid")
    research_id = create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id, stage="Research")
    contacted_id = create_opportunity(conn, project_id, contact_id=contact_id, organization_id=org_id, stage="Contacted")

    rows = list_pipeline(conn, project_id)

    assert [r["id"] for r in rows] == [research_id, contacted_id, paid_id]


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
