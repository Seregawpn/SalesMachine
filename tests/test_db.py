import sqlite3
from pathlib import Path

from project_os.db import get_connection, run_migrations

MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "project_os" / "migrations"


def test_run_migrations_creates_core_tables(tmp_db_path):
    conn = get_connection(tmp_db_path)
    version = run_migrations(conn, MIGRATIONS_DIR)
    assert version == 4

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
        "interactions",
    }:
        assert expected in tables


def test_run_migrations_is_idempotent(tmp_db_path):
    conn = get_connection(tmp_db_path)
    first = run_migrations(conn, MIGRATIONS_DIR)
    second = run_migrations(conn, MIGRATIONS_DIR)
    assert first == second == 4

    count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert count == 4


def test_get_connection_enables_wal_mode(tmp_db_path):
    conn = get_connection(tmp_db_path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_run_migrations_atomicity_on_failure(tmp_db_path, tmp_path):
    # Create a temporary migrations directory with valid and invalid migrations
    test_migrations_dir = tmp_path / "migrations"
    test_migrations_dir.mkdir()

    # Invalid migration file with syntax error in second statement
    # This tests that a failed migration doesn't partially commit
    invalid_sql = test_migrations_dir / "0001_invalid.sql"
    invalid_sql.write_text(
        "CREATE TABLE invalid_table1 (id INTEGER PRIMARY KEY);"
        "INVALID SQL SYNTAX ERROR;"
        "CREATE TABLE invalid_table2 (id INTEGER PRIMARY KEY);"
    )

    conn = get_connection(tmp_db_path)

    # Migration should fail and rollback completely
    try:
        run_migrations(conn, test_migrations_dir)
        assert False, "Expected migration to raise an exception"
    except Exception:
        pass

    # Verify atomicity: none of the invalid migration tables should exist
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "invalid_table1" not in tables, "Partial migration was committed"
    assert "invalid_table2" not in tables, "Partial migration was committed"

    # Verify schema_version wasn't advanced (should be 0 since no migration succeeded)
    version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert version is None, "Schema version was advanced despite migration failure"
