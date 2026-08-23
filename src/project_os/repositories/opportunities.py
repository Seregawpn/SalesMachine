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


def update_stage(
    conn: sqlite3.Connection,
    opportunity_id: int,
    new_stage: str,
    project_id: int | None = None,
    actor: str = "user",
) -> None:
    if new_stage not in STAGES:
        raise ValueError(f"Unknown stage: {new_stage}")

    if project_id is None:
        row = conn.execute(
            "SELECT stage FROM opportunities WHERE id = ?", (opportunity_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT stage FROM opportunities WHERE id = ? AND project_id = ?",
            (opportunity_id, project_id),
        ).fetchone()
    if row is None:
        raise LookupError(f"No opportunity with id {opportunity_id}")
    old_stage = row["stage"]

    if project_id is None:
        conn.execute(
            "UPDATE opportunities SET stage = ?, updated_at = datetime('now') WHERE id = ?",
            (new_stage, opportunity_id),
        )
    else:
        conn.execute(
            "UPDATE opportunities SET stage = ?, updated_at = datetime('now') WHERE id = ? AND project_id = ?",
            (new_stage, opportunity_id, project_id),
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
    rows = conn.execute(
        """
        SELECT o.*, org.name AS organization_name, c.name AS contact_name
        FROM opportunities o
        LEFT JOIN organizations org ON org.id = o.organization_id
        LEFT JOIN contacts c ON c.id = o.contact_id
        WHERE o.project_id = ?
        """,
        (project_id,),
    ).fetchall()
    stage_order = {stage: i for i, stage in enumerate(STAGES)}
    # Stable two-pass sort: most-recently-updated first within a stage,
    # then group by pipeline stage order (not alphabetical).
    by_recency = sorted(rows, key=lambda r: r["updated_at"], reverse=True)
    return sorted(by_recency, key=lambda r: stage_order.get(r["stage"], len(STAGES)))
