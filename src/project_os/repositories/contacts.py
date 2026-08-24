import sqlite3


def create_organization(conn: sqlite3.Connection, name: str, website: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO organizations (name, website) VALUES (?, ?)", (name, website)
    )
    return cur.lastrowid


def get_organization_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM organizations WHERE LOWER(name) = LOWER(?)", (name,)
    ).fetchone()


def get_or_create_organization(
    conn: sqlite3.Connection, name: str, website: str | None = None
) -> int:
    existing = get_organization_by_name(conn, name)
    if existing is not None:
        return existing["id"]
    return create_organization(conn, name, website)


def link_organization_to_project(
    conn: sqlite3.Connection,
    project_id: int,
    organization_id: int,
    segment: str | None = None,
    relevance: str | None = None,
    status: str = "Research",
) -> int:
    existing = conn.execute(
        "SELECT id FROM project_organizations WHERE project_id = ? AND organization_id = ?",
        (project_id, organization_id),
    ).fetchone()
    if existing is not None:
        return existing["id"]
    cur = conn.execute(
        """
        INSERT INTO project_organizations (project_id, organization_id, segment, relevance, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, organization_id, segment, relevance, status),
    )
    return cur.lastrowid


def find_contact_for_import(
    conn: sqlite3.Connection, name: str, email: str | None
) -> sqlite3.Row | None:
    if email:
        row = get_contact_by_email(conn, email)
        if row is not None:
            return row
    return conn.execute(
        "SELECT * FROM contacts WHERE LOWER(name) = LOWER(?) AND email IS NULL",
        (name,),
    ).fetchone()


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


def get_contact_by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM contacts WHERE LOWER(email) = LOWER(?)", (email,)
    ).fetchone()


def link_contact_to_project(
    conn: sqlite3.Connection,
    project_id: int,
    contact_id: int,
    status: str = "Research",
    priority: str = "Medium",
    pitch: str | None = None,
    role: str | None = None,
    organization_id: int | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO project_contacts (project_id, contact_id, status, priority, pitch, role, organization_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, contact_id, status, priority, pitch, role, organization_id),
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


def list_contacts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()


def list_companies_with_contacts(conn: sqlite3.Connection) -> list[dict]:
    orgs = conn.execute(
        """
        SELECT DISTINCT org.id, org.name, org.website
        FROM organizations org
        JOIN project_contacts pc ON pc.organization_id = org.id
        ORDER BY org.name
        """
    ).fetchall()

    companies = []
    for org in orgs:
        people = conn.execute(
            """
            SELECT c.id, c.name, c.email, c.linkedin_url, pc.role, pc.status, pc.priority
            FROM project_contacts pc
            JOIN contacts c ON c.id = pc.contact_id
            WHERE pc.organization_id = ?
            ORDER BY c.name
            """,
            (org["id"],),
        ).fetchall()
        open_opportunities = conn.execute(
            "SELECT COUNT(*) FROM opportunities WHERE organization_id = ? AND stage != 'Closed'",
            (org["id"],),
        ).fetchone()[0]
        activity = conn.execute(
            """
            SELECT i.*, c.name AS contact_name
            FROM interactions i
            JOIN contacts c ON c.id = i.contact_id
            JOIN project_contacts pc ON pc.contact_id = c.id AND pc.organization_id = ?
            ORDER BY i.created_at DESC, i.id DESC
            LIMIT 5
            """,
            (org["id"],),
        ).fetchall()
        companies.append(
            {
                "id": org["id"], "name": org["name"], "website": org["website"], "people": people,
                "open_opportunities": open_opportunities, "activity": activity,
            }
        )

    individuals = conn.execute(
        """
        SELECT c.id, c.name, c.email, c.linkedin_url, pc.role, pc.status, pc.priority
        FROM project_contacts pc
        JOIN contacts c ON c.id = pc.contact_id
        WHERE pc.organization_id IS NULL
        ORDER BY c.name
        """
    ).fetchall()
    orphans = conn.execute(
        """
        SELECT c.id, c.name, c.email, c.linkedin_url,
               NULL AS role, NULL AS status, NULL AS priority
        FROM contacts c
        WHERE c.id NOT IN (SELECT contact_id FROM project_contacts)
        ORDER BY c.name
        """
    ).fetchall()
    all_individuals = list(individuals) + list(orphans)
    if all_individuals:
        companies.insert(
            0, {"id": None, "name": "Individuals", "website": None, "people": all_individuals}
        )
    return companies
