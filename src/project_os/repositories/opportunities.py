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
