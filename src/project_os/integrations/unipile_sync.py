import sqlite3

from project_os.repositories.contacts import list_project_contacts
from project_os.repositories.linkedin import set_linkedin_state

# States a contact can still be promoted *into* "Accepted" from. A contact
# already past "Accepted" (e.g. "Message Sent", "Replied") or explicitly
# marked "Not relevant" should never be moved backwards by a sync run.
_PROMOTABLE_TO_ACCEPTED = {"Not started", "Pending Connection"}


def match_contact_by_linkedin_url(
    conn: sqlite3.Connection, project_id: int, linkedin_url: str
) -> int | None:
    """Return the project_contacts.id whose contact.linkedin_url matches, or None."""
    for contact in list_project_contacts(conn, project_id):
        if contact["contact_linkedin_url"] == linkedin_url:
            return contact["id"]
    return None


def sync_linkedin_states(conn: sqlite3.Connection, client, project_id: int) -> int:
    """Sync LinkedIn connection state for a project's contacts via Unipile.

    Uses the confirmed `GET /users/relations` endpoint (see
    UnipileClient.get_relations) to find accepted connections and promotes
    matching contacts to "Accepted" via set_linkedin_state(actor="unipile-sync").
    Returns the count of contacts updated.
    """
    accounts = client.get_accounts()
    linkedin_account = next(
        (a for a in accounts if a.get("type") == "LINKEDIN"), None
    )
    if linkedin_account is None:
        return 0

    relations = client.get_relations(linkedin_account["id"])

    updated_count = 0
    for relation in relations:
        linkedin_url = relation.get("public_profile_url")
        if not linkedin_url:
            continue

        pc_id = match_contact_by_linkedin_url(conn, project_id, linkedin_url)
        if pc_id is None:
            continue

        row = conn.execute(
            "SELECT linkedin_state FROM project_contacts WHERE id = ?", (pc_id,)
        ).fetchone()
        if row["linkedin_state"] not in _PROMOTABLE_TO_ACCEPTED:
            continue

        set_linkedin_state(conn, pc_id, "Accepted", actor="unipile-sync")
        updated_count += 1

    return updated_count
