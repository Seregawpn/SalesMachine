import sqlite3

from project_os.repositories.actions import create_action

LINKEDIN_STATES = [
    "Not started",
    "Pending Connection",
    "Accepted",
    "Message Sent",
    "Replied",
    "Not relevant",
]


def set_linkedin_state(
    conn: sqlite3.Connection,
    project_contact_id: int,
    new_state: str,
    actor: str = "user",
) -> None:
    if new_state not in LINKEDIN_STATES:
        raise ValueError(f"Unknown LinkedIn state: {new_state}")

    row = conn.execute(
        "SELECT project_id, linkedin_state FROM project_contacts WHERE id = ?",
        (project_contact_id,),
    ).fetchone()
    project_id = row["project_id"]
    old_state = row["linkedin_state"]

    conn.execute(
        """
        UPDATE project_contacts
        SET linkedin_state = ?, linkedin_last_action_at = datetime('now')
        WHERE id = ?
        """,
        (new_state, project_contact_id),
    )
    conn.execute(
        """
        INSERT INTO audit_log (actor, entity_table, entity_id, field, old_value, new_value)
        VALUES (?, 'project_contacts', ?, 'linkedin_state', ?, ?)
        """,
        (actor, project_contact_id, old_state, new_state),
    )

    if new_state == "Accepted":
        create_action(
            conn, project_id, module="Sales",
            reason="Prepare first LinkedIn message", priority="P2",
            linked_table="project_contacts", linked_id=project_contact_id,
        )
    elif new_state == "Pending Connection":
        create_action(
            conn, project_id, module="Sales",
            reason="Re-check LinkedIn connection status", priority="P3",
            linked_table="project_contacts", linked_id=project_contact_id,
        )


def list_linkedin_queue(conn: sqlite3.Connection, project_id: int) -> dict[str, list[sqlite3.Row]]:
    rows = conn.execute(
        """
        SELECT pc.*, c.name, c.linkedin_url
        FROM project_contacts pc
        JOIN contacts c ON c.id = pc.contact_id
        WHERE pc.project_id = ?
        ORDER BY c.name
        """,
        (project_id,),
    ).fetchall()

    queue = {
        "to_connect": [],
        "pending_recheck": [],
        "awaiting_message": [],
        "awaiting_reply": [],
    }
    for row in rows:
        state = row["linkedin_state"]
        if state == "Not started":
            queue["to_connect"].append(row)
        elif state == "Pending Connection":
            queue["pending_recheck"].append(row)
        elif state == "Accepted":
            queue["awaiting_message"].append(row)
        elif state == "Message Sent":
            queue["awaiting_reply"].append(row)
    return queue
