import sqlite3


def create_project(conn: sqlite3.Connection, name: str, description: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO projects (name, description) VALUES (?, ?)",
        (name, description),
    )
    return cur.lastrowid


def list_projects(conn: sqlite3.Connection, active_only: bool = True) -> list[sqlite3.Row]:
    if active_only:
        return conn.execute(
            "SELECT * FROM projects WHERE active = 1 ORDER BY name"
        ).fetchall()
    return conn.execute("SELECT * FROM projects ORDER BY name").fetchall()


def get_project(conn: sqlite3.Connection, project_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
