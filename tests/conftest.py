import pathlib
import sqlite3
import pytest

@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "project_os.sqlite")
