from project_os.ai.codex_provider import CodexProvider
from project_os.ai.mail_read_mcp_server import mcp_server_command

provider = CodexProvider.for_codex_cli(
    mcp_servers={"project-os-mail": mcp_server_command()},
)
try:
    result = provider.run_task(
        "Use the list_recent_messages tool to check my inbox, then tell me "
        "how many messages you found and the subject of the most recent one.",
        cwd="/tmp",
        timeout=180.0,
    )
    print("Codex said:", result)
finally:
    provider.close()
