from pathlib import Path

from project_os.db import get_connection, run_migrations
from project_os.repositories.projects import create_project
from project_os.ai.codex_provider import CodexProvider
from project_os.ai.mail_read_mcp_server import mcp_server_command
from project_os.ai.mail_sync import sync_mail_replies

db_path = "/tmp/mail_sync_smoke_test.sqlite"
conn = get_connection(db_path)
run_migrations(conn, Path("src/project_os/migrations"))
project_id = create_project(conn, "Smoke Test Project")

provider = CodexProvider.for_codex_cli(mcp_servers={"project-os-mail": mcp_server_command()})
try:
    created = sync_mail_replies(conn, provider, project_id, timeout=180.0)
finally:
    provider.close()

print(f"Created {created} new interaction(s).")
for row in conn.execute("SELECT * FROM interactions"):
    print(dict(row))
for row in conn.execute("SELECT * FROM actions"):
    print(dict(row))
