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
