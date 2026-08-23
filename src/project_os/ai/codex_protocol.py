import json
from dataclasses import dataclass
from typing import Any


class CodexProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class CodexEvent:
    kind: str
    value: Any = None


def initialize_request(request_id: int) -> dict:
    return {
        "method": "initialize",
        "id": request_id,
        "params": {
            "clientInfo": {
                "name": "project_os",
                "title": "Project OS",
                "version": "0.1.0",
            }
        },
    }


def initialized_notification() -> dict:
    return {"method": "initialized", "params": {}}


def thread_start_request(
    request_id: int,
    cwd: str,
    developer_instructions: str,
    *,
    sandbox: str = "read-only",
    approval_policy: str = "never",
) -> dict:
    return {
        "method": "thread/start",
        "id": request_id,
        "params": {
            "cwd": cwd,
            "sandbox": sandbox,
            "approvalPolicy": approval_policy,
            "developerInstructions": developer_instructions,
        },
    }


def turn_start_request(request_id: int, thread_id: str, prompt: str) -> dict:
    return {
        "method": "turn/start",
        "id": request_id,
        "params": {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
        },
    }


def mcp_elicitation_response(request_id: int | str, action: str = "accept") -> dict:
    """Reply to an `mcp_elicitation_requested` event.

    Codex asks for explicit approval before running an MCP tool call even
    under `approvalPolicy: "never"` (confirmed live: a real turn hung
    indefinitely waiting for this exact reply). `action` is one of
    "accept"/"decline"/"cancel" — CodexProvider always accepts, since the
    only MCP servers it is ever configured with are Project OS's own
    (read-only unless `allow_send=True` was explicitly passed), so there
    is nothing here for the user to approve that Project OS didn't already
    choose to expose.
    """
    return {"id": request_id, "result": {"action": action}}


def parse_event(line: str) -> CodexEvent:
    try:
        message = json.loads(line)
    except json.JSONDecodeError as error:
        raise CodexProtocolError(f"Malformed JSON from Codex: {line!r}") from error
    if not isinstance(message, dict):
        raise CodexProtocolError(f"Unexpected non-object message from Codex: {line!r}")

    if "error" in message:
        return CodexEvent("error", str(message["error"].get("message", "Unknown Codex error")))

    thread = message.get("result", {})
    thread = thread.get("thread", {}) if isinstance(thread, dict) else {}
    if isinstance(thread.get("id"), str):
        return CodexEvent("thread_created", thread["id"])

    method = message.get("method")

    if method == "mcpServer/elicitation/request" and isinstance(message.get("id"), (int, str)):
        return CodexEvent("mcp_elicitation_requested", message["id"])

    params = message.get("params", {})
    if not isinstance(params, dict):
        return CodexEvent("ignored")

    if method == "turn/completed":
        return CodexEvent("turn_completed")

    item = params.get("item", {})
    if (
        method == "item/completed"
        and isinstance(item, dict)
        and item.get("type") == "agentMessage"
        and isinstance(item.get("text"), str)
        and item.get("phase") != "commentary"
    ):
        return CodexEvent("agent_message", item["text"])

    return CodexEvent("ignored")
