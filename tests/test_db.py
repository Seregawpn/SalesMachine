import sqlite3
from pathlib import Path

from project_os.db import get_connection, run_migrations

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def test_run_migrations_creates_core_tables(tmp_db_path):
    conn = get_connection(tmp_db_path)
    version = run_migrations(conn, MIGRATIONS_DIR)
    assert version == 1

    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for expected in {
        "schema_version",
        "projects",
        "organizations",
        "contacts",
        "project_organizations",
        "project_contacts",
        "opportunities",
        "actions",
        "audit_log",
    }:
        assert expected in tables


def test_run_migrations_is_idempotent(tmp_db_path):
    conn = get_connection(tmp_db_path)
    first = run_migrations(conn, MIGRATIONS_DIR)
    second = run_migrations(conn, MIGRATIONS_DIR)
    assert first == second == 1

    count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert count == 1


def test_get_connection_enables_wal_mode(tmp_db_path):
    conn = get_connection(tmp_db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
