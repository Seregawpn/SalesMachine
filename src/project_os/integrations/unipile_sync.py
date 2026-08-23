import sqlite3

from project_os.repositories.contacts import list_project_contacts
from project_os.repositories.linkedin import set_linkedin_state

# States a contact can still be promoted *into* "Accepted" from. A contact
# already past "Accepted" (e.g. "Message Sent", "Replied") or explicitly
# marked "Not relevant" should never be moved backwards by a sync run.
_PROMOTABLE_TO_ACCEPTED = {"Not started", "Pending Connection"}


def _normalize_linkedin_url(url: str) -> str:
    """Normalize a LinkedIn URL for comparison.

    Lowercases, strips the scheme, strips a leading "www.", and strips a
    trailing slash, so that e.g. "https://www.LinkedIn.com/in/jane/" and
    "linkedin.com/in/jane" compare equal.
    """
    normalized = url.strip().lower()
    for prefix in ("https://", "http://"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    if normalized.startswith("www."):
        normalized = normalized[len("www."):]
    normalized = normalized.rstrip("/")
    return normalized


def sync_linkedin_states(conn: sqlite3.Connection, client, project_id: int) -> int:
    """Sync LinkedIn connection state for a project's contacts via Unipile.

    Uses the confirmed `GET /users/relations` endpoint (see
    UnipileClient.get_relations) to find accepted connections and promotes
    matching contacts to "Accepted" via set_linkedin_state(actor="unipile-sync").
    Returns the count of contacts updated.

    Builds the project's contact list once and looks up each relation by a
    normalized LinkedIn URL, instead of re-querying the database per relation.
    """
    accounts = client.get_accounts()
    linkedin_account = next(
        (a for a in accounts if a.get("type") == "LINKEDIN"), None
    )
    if linkedin_account is None:
        return 0

    relations = client.get_relations(linkedin_account["id"])

    contacts_by_url = {}
    for contact in list_project_contacts(conn, project_id):
        contact_url = contact["contact_linkedin_url"]
        if contact_url:
            contacts_by_url[_normalize_linkedin_url(contact_url)] = contact

    updated_count = 0
    for relation in relations:
        linkedin_url = relation.get("public_profile_url")
        if not linkedin_url:
            continue

        contact = contacts_by_url.get(_normalize_linkedin_url(linkedin_url))
        if contact is None:
            continue

        if contact["linkedin_state"] not in _PROMOTABLE_TO_ACCEPTED:
            continue

        set_linkedin_state(conn, contact["id"], "Accepted", actor="unipile-sync")
        updated_count += 1

    return updated_count
