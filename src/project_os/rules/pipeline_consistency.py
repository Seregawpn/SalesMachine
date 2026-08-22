import sqlite3

from project_os.repositories.actions import create_action, has_open_action_for

_REASON = "Missing next action"


def check_missing_next_action(conn: sqlite3.Connection, project_id: int) -> int:
    rows = conn.execute(
        """
        SELECT id FROM opportunities
        WHERE project_id = ?
          AND stage != 'Closed'
          AND (next_action IS NULL OR next_action_due IS NULL)
        """,
        (project_id,),
    ).fetchall()

    created = 0
    for row in rows:
        opp_id = row["id"]
        if has_open_action_for(conn, "opportunities", opp_id, _REASON):
            continue
        create_action(
            conn,
            project_id,
            module="Sales",
            reason=_REASON,
            priority="P2",
            linked_table="opportunities",
            linked_id=opp_id,
        )
        created += 1
    return created
