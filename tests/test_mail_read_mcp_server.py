import json
import subprocess

from project_os.ai.mail_read_mcp_server import handle_request, MailMcpError, _run_mail_jxa


def _fake_runner(stdout_payload: dict, returncode: int = 0):
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=returncode,
            stdout=json.dumps(stdout_payload) if returncode == 0 else "",
            stderr="" if returncode == 0 else "Mail is not running.",
        )
    return runner


def test_initialize_returns_server_info():
    response = handle_request({"id": 1, "method": "initialize"})
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "project-os-mail"


def test_tools_list_exposes_only_read_tools():
    response = handle_request({"id": 2, "method": "tools/list"})
    tool_names = {tool["name"] for tool in response["result"]["tools"]}
    assert tool_names == {
        "list_unread_messages",
        "list_recent_messages",
        "search_messages",
        "read_message",
    }


def test_list_unread_messages_formats_results_from_jxa_output():
    runner = _fake_runner({
        "messages": [
            {"id": "msg-1", "subject": "Re: pricing", "sender": "Jane <jane@example.org>",
             "date_received": "2026-08-20", "mailbox": "INBOX", "read": False},
        ],
        "scanned": 5,
    })
    response = handle_request(
        {"id": 3, "method": "tools/call", "params": {"name": "list_unread_messages", "arguments": {"limit": 5}}},
        runner=runner,
    )
    text = response["result"]["content"][0]["text"]
    assert "Re: pricing" in text
    assert "jane@example.org" in text
    assert "msg-1" in text


def test_read_message_includes_body_when_jxa_returns_one():
    runner = _fake_runner({
        "messages": [
            {"id": "msg-1", "subject": "Re: pricing", "sender": "jane@example.org",
             "date_received": "2026-08-20", "mailbox": "INBOX", "read": True,
             "body": "Sounds good, let's set up a demo."},
        ],
        "scanned": 1,
    })
    response = handle_request(
        {"id": 4, "method": "tools/call", "params": {"name": "read_message", "arguments": {"id": "msg-1"}}},
        runner=runner,
    )
    text = response["result"]["content"][0]["text"]
    assert "Sounds good, let's set up a demo." in text


def test_tool_call_reports_isError_when_jxa_fails():
    runner = _fake_runner({}, returncode=1)
    response = handle_request(
        {"id": 5, "method": "tools/call", "params": {"name": "list_recent_messages", "arguments": {}}},
        runner=runner,
    )
    assert response["result"]["isError"] is True
    assert "Mail is not running" in response["result"]["content"][0]["text"]


def test_unknown_tool_name_reports_isError():
    response = handle_request(
        {"id": 6, "method": "tools/call", "params": {"name": "delete_message", "arguments": {}}},
        runner=_fake_runner({"messages": []}),
    )
    assert response["result"]["isError"] is True
    assert "Unknown tool" in response["result"]["content"][0]["text"]


def test_run_mail_jxa_raises_mail_mcp_error_on_nonzero_exit():
    runner = _fake_runner({}, returncode=1)
    try:
        _run_mail_jxa({"mode": "recent", "limit": 5}, runner=runner)
        assert False, "expected MailMcpError"
    except MailMcpError as error:
        assert "Mail is not running" in str(error)


def test_unknown_method_returns_json_rpc_error():
    response = handle_request({"id": 7, "method": "resources/list"})
    assert response["error"]["code"] == -32601
