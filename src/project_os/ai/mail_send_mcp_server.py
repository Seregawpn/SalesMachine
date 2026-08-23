"""Send-only MCP server for Apple Mail.

Deliberately separate from `mail_read_mcp_server.py`: this module exposes
exactly one tool, `send_message`, and nothing else. Project OS only
enables this server for the one narrow "send this already-approved draft"
task — never for reading, classifying, or drafting tasks — so the model
has no tool-level path to send anything unless the caller specifically
chose to give it one.
"""

import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any, TextIO

SERVER_NAME = "project-os-mail-send"
PROTOCOL_VERSION = "2025-06-18"

_SEND_JXA_SCRIPT = r"""
function run(argv) {
  const request = JSON.parse(argv[0] || "{}");
  const Mail = Application("Mail");
  const outgoing = Mail.OutgoingMessage().make({
    withProperties: { subject: request.subject, content: request.body, visible: false }
  });
  outgoing.toRecipients.push(
    Mail.Recipient().make({ withProperties: { address: request.to } })
  );
  outgoing.send();
  return JSON.stringify({ sent: true });
}
"""

_REQUIRED_FIELDS = ("to", "subject", "body")


def mcp_server_command() -> tuple[str, list[str]]:
    """The (command, args) pair to launch this MCP server as a subprocess,
    using the interpreter currently running (so the venv this daemon is
    installed into is the same one that can import project_os)."""
    return (sys.executable, ["-m", "project_os.ai.mail_send_mcp_server"])


class MailSendError(RuntimeError):
    """Raised when Apple Mail cannot send the message."""


def send_via_jxa(
    payload: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    result = runner(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", _SEND_JXA_SCRIPT, json.dumps(payload)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0:
        raise MailSendError(result.stderr.strip() or "Apple Mail returned an error while sending.")


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "send_message",
            "description": "Send an email through Apple Mail.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address."},
                    "subject": {"type": "string", "description": "Email subject line."},
                    "body": {"type": "string", "description": "Plain-text email body."},
                },
                "required": list(_REQUIRED_FIELDS),
                "additionalProperties": False,
            },
        },
    ]


def _send_message_result(
    arguments: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    missing = [field for field in _REQUIRED_FIELDS if not arguments.get(field)]
    if missing:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Missing required argument(s): {', '.join(missing)}"}],
        }
    try:
        send_via_jxa({field: arguments[field] for field in _REQUIRED_FIELDS}, runner=runner)
        return {"content": [{"type": "text", "text": f"Message sent to {arguments['to']}."}]}
    except Exception as error:
        return {"isError": True, "content": [{"type": "text", "text": f"Apple Mail error: {error}"}]}


def handle_request(
    request: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tools()}}
    if method == "tools/call":
        params = request.get("params", {})
        if not isinstance(params, dict):
            params = {}
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        if name == "send_message":
            result = _send_message_result(arguments, runner=runner)
        else:
            result = {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def serve(
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    for line in stdin:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            request = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(request, dict):
            continue
        response = handle_request(request, runner=runner)
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0


def main(_argv: list[str] | None = None) -> int:
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
