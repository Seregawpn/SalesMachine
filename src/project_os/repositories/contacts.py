import sqlite3


def create_organization(conn: sqlite3.Connection, name: str, website: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO organizations (name, website) VALUES (?, ?)", (name, website)
    )
    return cur.lastrowid


def create_contact(
    conn: sqlite3.Connection,
    name: str,
    email: str | None = None,
    linkedin_url: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO contacts (name, email, linkedin_url) VALUES (?, ?, ?)",
        (name, email, linkedin_url),
    )
    return cur.lastrowid


def link_contact_to_project(
    conn: sqlite3.Connection,
    project_id: int,
    contact_id: int,
    status: str = "Research",
    priority: str = "Medium",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO project_contacts (project_id, contact_id, status, priority)
        VALUES (?, ?, ?, ?)
        """,
        (project_id, contact_id, status, priority),
    )
    return cur.lastrowid


def get_project_contact(conn: sqlite3.Connection, project_id: int, contact_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT pc.*, c.name, c.email, c.linkedin_url AS contact_linkedin_url
        FROM project_contacts pc
        JOIN contacts c ON c.id = pc.contact_id
        WHERE pc.project_id = ? AND pc.contact_id = ?
        """,
        (project_id, contact_id),
    ).fetchone()


def list_project_contacts(conn: sqlite3.Connection, project_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT pc.*, c.name, c.email, c.linkedin_url AS contact_linkedin_url
        FROM project_contacts pc
        JOIN contacts c ON c.id = pc.contact_id
        WHERE pc.project_id = ?
        ORDER BY c.name
        """,
        (project_id,),
    ).fetchall()
