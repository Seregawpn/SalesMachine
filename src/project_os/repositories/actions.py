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
    cur = conn.execute(
        "UPDATE actions SET status = 'Completed', completed_at = datetime('now') WHERE id = ?",
        (action_id,),
    )
    if cur.rowcount == 0:
        raise LookupError(f"No action with id {action_id}")


def snooze_action(conn: sqlite3.Connection, action_id: int, new_due_date: str) -> None:
    cur = conn.execute("UPDATE actions SET due_date = ? WHERE id = ?", (new_due_date, action_id))
    if cur.rowcount == 0:
        raise LookupError(f"No action with id {action_id}")


def has_open_action_for(conn: sqlite3.Connection, linked_table: str, linked_id: int, reason: str) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM actions
        WHERE status = 'Open' AND linked_table = ? AND linked_id = ? AND reason = ?
        """,
        (linked_table, linked_id, reason),
    ).fetchone()
    return row is not None
