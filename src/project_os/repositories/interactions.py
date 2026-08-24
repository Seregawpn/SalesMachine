import sqlite3


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


def get_interaction_by_external_id(
    conn: sqlite3.Connection, project_id: int, external_message_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM interactions WHERE project_id = ? AND external_message_id = ?",
        (project_id, external_message_id),
    ).fetchone()


def list_interactions(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT i.*, c.name AS contact_name, p.name AS project_name
        FROM interactions i
        JOIN contacts c ON c.id = i.contact_id
        JOIN projects p ON p.id = i.project_id
        ORDER BY i.created_at DESC, i.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


def list_email_interactions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT i.*, c.name AS contact_name, p.name AS project_name,
               a.id AS open_action_id, a.suggested_message AS draft_reply
        FROM interactions i
        JOIN contacts c ON c.id = i.contact_id
        JOIN projects p ON p.id = i.project_id
        LEFT JOIN actions a ON a.source_interaction_id = i.id AND a.status = 'Open'
        WHERE i.channel = 'email'
        ORDER BY i.created_at DESC, i.id DESC
        """
    ).fetchall()
