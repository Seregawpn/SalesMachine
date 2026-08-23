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
) -> int:
    cur = conn.execute(
        """
        INSERT INTO interactions
            (project_id, contact_id, channel, direction, subject, ai_summary, intent, external_message_id, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, contact_id, channel, direction, subject, ai_summary, intent, external_message_id, source),
    )
    return cur.lastrowid


def get_interaction_by_external_id(
    conn: sqlite3.Connection, project_id: int, external_message_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM interactions WHERE project_id = ? AND external_message_id = ?",
        (project_id, external_message_id),
    ).fetchone()
