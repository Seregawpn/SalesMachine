import re
import sqlite3
from pathlib import Path


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
    )


def _current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    return row["v"] or 0


def run_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> int:
    _ensure_schema_version_table(conn)
    current = _current_version(conn)

    migration_files = sorted(
        migrations_dir.glob("*.sql"),
        key=lambda p: int(re.match(r"(\d+)_", p.name).group(1)),
    )

    for path in migration_files:
        number = int(re.match(r"(\d+)_", path.name).group(1))
        if number <= current:
            continue
        sql = path.read_text()
        # Temporarily switch to deferred isolation to handle transactions
        old_isolation = conn.isolation_level
        conn.isolation_level = "DEFERRED"
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (number,)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.isolation_level = old_isolation
        current = number

    return current
