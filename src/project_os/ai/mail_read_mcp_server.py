"""Read-only MCP server for Apple Mail.

The server intentionally exposes no send, delete, archive, move, or
mark-read tools — sending is a separate, deliberately narrower MCP server
(`mail_send_mcp_server.py`), so a Codex thread configured with only this
server has no tool-level way to send anything, regardless of prompt
wording or model behavior.
"""

import json
import subprocess
import sys
from collections.abc import Callable
from typing import Any, TextIO

SERVER_NAME = "project-os-mail"
PROTOCOL_VERSION = "2025-06-18"

_JXA_SCRIPT = r"""
function run(argv) {
  const request = JSON.parse(argv[0] || "{}");
  const Mail = Application("Mail");

  function value(fn, fallback) {
    try {
      const result = fn();
      if (result === undefined || result === null) return fallback;
      return String(result);
    } catch (_) {
      return fallback;
    }
  }

  function boolValue(fn, fallback) {
    try {
      return Boolean(fn());
    } catch (_) {
      return fallback;
    }
  }

  function messageAccount(message) {
    return value(() => message.mailbox().account().name(), "");
  }

  function messageRecord(message, includeBody) {
    const record = {
      id: value(() => message.id(), ""),
      subject: value(() => message.subject(), "(no subject)"),
      sender: value(() => message.sender(), ""),
      date_received: value(() => message.dateReceived(), ""),
      mailbox: value(() => message.mailbox().name(), ""),
      account: messageAccount(message),
      read: boolValue(() => message.readStatus(), false)
    };
    if (includeBody) {
      record.body = value(() => message.content(), "");
    }
    return record;
  }

  function accountFilterList(raw) {
    if (!raw) return null;
    const items = Array.isArray(raw) ? raw : [raw];
    const names = items
      .filter(v => typeof v === "string" && v.trim().length > 0)
      .map(v => v.trim().toLowerCase());
    return names.length > 0 ? names : null;
  }

  function matchesAccountFilter(message, accountFilter) {
    if (!accountFilter) return true;
    return accountFilter.indexOf(messageAccount(message).toLowerCase()) !== -1;
  }

  function limitNumber(value, fallback) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 1) return fallback;
    return Math.min(Math.floor(parsed), 25);
  }

  function maxScanNumber(value, fallback) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 1) return fallback;
    return Math.min(Math.floor(parsed), 250);
  }

  const mode = request.mode || "recent";
  const limit = limitNumber(request.limit, 10);
  const maxScan = maxScanNumber(request.max_scan, 100);
  const accountFilter = accountFilterList(request.account);
  const inboxMessages = Mail.inbox.messages();
  let selected = [];
  let scanned = 0;

  if (mode === "read") {
    const requestedId = String(request.id || "");
    for (const message of inboxMessages) {
      scanned += 1;
      if (value(() => message.id(), "") === requestedId) {
        selected.push(messageRecord(message, true));
        break;
      }
      if (scanned >= maxScan) break;
    }
  } else if (mode === "unread") {
    // A plain bounded loop, not Mail.inbox.messages.whose({readStatus: false})():
    // .whose() forces Mail to evaluate the predicate against the entire
    // inbox before returning anything, which hangs on a large or
    // IMAP-backed mailbox even when Mail itself is healthy (confirmed
    // live against a ~5,400-message "All Mail"-mapped inbox: .whose()
    // timed out repeatedly while a bounded loop over just the first
    // maxScan messages - mirroring "recent" mode, which is reliably fast
    // - returned promptly). This can miss an unread message older than
    // the first maxScan messages in the mailbox's natural order, which is
    // an acceptable tradeoff: callers only need recent, sales-relevant
    // replies, not exhaustive history.
    for (const message of inboxMessages) {
      scanned += 1;
      if (boolValue(() => message.readStatus(), false) === false && matchesAccountFilter(message, accountFilter)) {
        selected.push(messageRecord(message, false));
        if (selected.length >= limit) break;
      }
      if (scanned >= maxScan) break;
    }
  } else if (mode === "search") {
    const query = String(request.query || "");
    let combined = [];
    if (query) {
      let inboxMatches = [];
      try {
        inboxMatches = Mail.inbox.messages.whose({
          _or: [
            { sender: { _contains: query } },
            { subject: { _contains: query } }
          ]
        })();
      } catch (_) {
        inboxMatches = [];
      }
      combined = inboxMatches;
      scanned = inboxMatches.length;
    }
    for (let i = 0; i < combined.length && selected.length < limit; i++) {
      if (matchesAccountFilter(combined[i], accountFilter)) {
        selected.push(messageRecord(combined[i], false));
      }
    }
  } else {
    for (const message of inboxMessages) {
      scanned += 1;
      if (matchesAccountFilter(message, accountFilter)) {
        selected.push(messageRecord(message, false));
        if (selected.length >= limit) break;
      }
      if (scanned >= maxScan) break;
    }
  }

  return JSON.stringify({ messages: selected, scanned: scanned });
}
"""


def mcp_server_command() -> tuple[str, list[str]]:
    """The (command, args) pair to launch this MCP server as a subprocess,
    using the interpreter currently running (so the venv this daemon is
    installed into is the same one that can import project_os)."""
    return (sys.executable, ["-m", "project_os.ai.mail_read_mcp_server"])


class MailMcpError(RuntimeError):
    """Raised when Apple Mail data cannot be read."""


def _run_mail_jxa(
    payload: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    result = runner(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", _JXA_SCRIPT, json.dumps(payload)],
        check=False,
        capture_output=True,
        text=True,
        # 60s, not 20s: Mail.app can be intermittently slow to answer any
        # Apple Event at all while busy with its own background sync/
        # indexing (confirmed live), independent of query shape - the
        # bounded-scan queries (unread/search/read) stay well under this
        # in the common case, but this runs as a background daemon job
        # every 15 minutes, not something a user waits on synchronously, so
        # a generous worst-case timeout is an acceptable tradeoff.
        timeout=60,
    )
    if result.returncode != 0:
        raise MailMcpError(result.stderr.strip() or "Apple Mail returned an error.")
    try:
        parsed = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise MailMcpError("Apple Mail returned invalid data.") from error
    if not isinstance(parsed, dict):
        raise MailMcpError("Apple Mail returned unexpected data.")
    return parsed


def _clamp_limit(arguments: dict[str, Any], default: int = 10) -> int:
    value = arguments.get("limit", default)
    if not isinstance(value, int) or value < 1:
        return default
    return min(value, 25)


def _bounded_scan(limit: int) -> int:
    return min(max(limit * 25, 100), 250)


def _account_filter(arguments: dict[str, Any]) -> str | list[str] | None:
    value = arguments.get("account")
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, list):
        names = [v for v in value if isinstance(v, str) and v.strip()]
        return names or None
    return None


def _format_messages(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return "No matching Apple Mail messages were found."
    blocks: list[str] = []
    for index, message in enumerate(messages, 1):
        lines = [
            f"{index}. {message.get('subject') or '(no subject)'}",
            f"From: {message.get('sender') or 'unknown'}",
            f"Date: {message.get('date_received') or 'unknown'}",
            f"Mailbox: {message.get('mailbox') or 'unknown'}",
            f"Account: {message.get('account') or 'unknown'}",
            f"Message ID: {message.get('id') or 'unknown'}",
        ]
        body = message.get("body")
        if isinstance(body, str) and body.strip():
            lines.append("")
            lines.append(body.strip())
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _mail_tool_result(
    payload: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> dict[str, Any]:
    try:
        result = _run_mail_jxa(payload, runner=runner)
        messages = result.get("messages", [])
        if not isinstance(messages, list):
            raise MailMcpError("Apple Mail returned unexpected messages.")
        text = _format_messages([m for m in messages if isinstance(m, dict)])
        return {"content": [{"type": "text", "text": text}]}
    except Exception as error:
        return {"isError": True, "content": [{"type": "text", "text": f"Apple Mail error: {error}"}]}


def _tools() -> list[dict[str, Any]]:
    limit_schema = {
        "type": "integer", "minimum": 1, "maximum": 25,
        "description": "Maximum number of messages to return.",
    }
    account_schema = {
        "oneOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "string"}},
        ],
        "description": (
            "Restrict results to one or more Mail.app account names "
            "(e.g. \"Google\", \"Nexyai\", or an account's email address, "
            "exactly as Mail.app names it). Omit to include all accounts."
        ),
    }
    return [
        {
            "name": "list_unread_messages",
            "description": "List unread messages from the Apple Mail inbox.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": limit_schema, "account": account_schema},
                "additionalProperties": False,
            },
        },
        {
            "name": "list_recent_messages",
            "description": "List recent messages from the Apple Mail inbox.",
            "inputSchema": {
                "type": "object",
                "properties": {"limit": limit_schema, "account": account_schema},
                "additionalProperties": False,
            },
        },
        {
            "name": "search_messages",
            "description": "Search Apple Mail inbox messages by sender or subject.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for in sender or subject."},
                    "limit": limit_schema,
                    "account": account_schema,
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "read_message",
            "description": "Read one Apple Mail inbox message by Message ID.",
            "inputSchema": {
                "type": "object",
                "properties": {"id": {"type": "string", "description": "Apple Mail message id returned by list/search tools."}},
                "required": ["id"],
                "additionalProperties": False,
            },
        },
    ]


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
        if name == "list_unread_messages":
            limit = _clamp_limit(arguments)
            result = _mail_tool_result(
                {
                    "mode": "unread", "limit": limit, "max_scan": _bounded_scan(limit),
                    "account": _account_filter(arguments),
                },
                runner=runner,
            )
        elif name == "list_recent_messages":
            limit = _clamp_limit(arguments)
            result = _mail_tool_result(
                {
                    "mode": "recent", "limit": limit, "max_scan": _bounded_scan(limit),
                    "account": _account_filter(arguments),
                },
                runner=runner,
            )
        elif name == "search_messages":
            limit = _clamp_limit(arguments)
            result = _mail_tool_result(
                {
                    "mode": "search", "query": str(arguments.get("query", "")), "limit": limit,
                    "max_scan": _bounded_scan(limit), "account": _account_filter(arguments),
                },
                runner=runner,
            )
        elif name == "read_message":
            result = _mail_tool_result(
                {"mode": "read", "id": str(arguments.get("id", "")), "max_scan": 250},
                runner=runner,
            )
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
