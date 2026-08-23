import json
import subprocess
import sys

from project_os.ai.mail_read_mcp_server import handle_request, mcp_server_command, MailMcpError, _run_mail_jxa


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
             "date_received": "2026-08-20", "mailbox": "INBOX", "account": "Nexyai", "read": False},
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
    assert "Account: Nexyai" in text


def test_list_unread_messages_passes_a_single_account_filter_through():
    captured = {}

    def runner(*args, **kwargs):
        captured["payload"] = json.loads(args[0][-1])
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"messages": [], "scanned": 0}), stderr="")

    handle_request(
        {"id": 12, "method": "tools/call", "params": {"name": "list_unread_messages", "arguments": {"account": "Nexyai"}}},
        runner=runner,
    )
    assert captured["payload"]["account"] == "Nexyai"


def test_list_recent_messages_passes_a_list_of_accounts_through():
    captured = {}

    def runner(*args, **kwargs):
        captured["payload"] = json.loads(args[0][-1])
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"messages": [], "scanned": 0}), stderr="")

    handle_request(
        {
            "id": 13, "method": "tools/call",
            "params": {"name": "list_recent_messages", "arguments": {"account": ["Google", "Nexyai"]}},
        },
        runner=runner,
    )
    assert captured["payload"]["account"] == ["Google", "Nexyai"]


def test_search_messages_omits_account_filter_when_not_given():
    captured = {}

    def runner(*args, **kwargs):
        captured["payload"] = json.loads(args[0][-1])
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"messages": [], "scanned": 0}), stderr="")

    handle_request(
        {"id": 14, "method": "tools/call", "params": {"name": "search_messages", "arguments": {"query": "pricing"}}},
        runner=runner,
    )
    assert captured["payload"]["account"] is None


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


def test_list_unread_messages_requests_a_bounded_scan():
    captured = {}

    def runner(*args, **kwargs):
        captured["payload"] = json.loads(args[0][-1])
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"messages": [], "scanned": 0}), stderr="")

    handle_request(
        {"id": 11, "method": "tools/call", "params": {"name": "list_unread_messages", "arguments": {}}},
        runner=runner,
    )
    assert captured["payload"]["max_scan"] == 250


def test_read_message_requests_a_generous_max_scan():
    captured = {}

    def runner(*args, **kwargs):
        captured["payload"] = json.loads(args[0][-1])
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"messages": [], "scanned": 0}), stderr="")

    handle_request(
        {"id": 10, "method": "tools/call", "params": {"name": "read_message", "arguments": {"id": "msg-1"}}},
        runner=runner,
    )
    assert captured["payload"]["max_scan"] == 250


def test_mcp_server_command_uses_the_current_interpreter():
    command, args = mcp_server_command()
    assert command == sys.executable
    assert args == ["-m", "project_os.ai.mail_read_mcp_server"]
