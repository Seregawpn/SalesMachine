import json
import subprocess
import sys

from project_os.ai.mail_send_mcp_server import handle_request, mcp_server_command, MailSendError, _send_via_jxa


def _fake_runner(returncode: int = 0, stderr: str = ""):
    def runner(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=returncode,
            stdout=json.dumps({"sent": True}) if returncode == 0 else "",
            stderr=stderr,
        )
    return runner


def test_tools_list_exposes_only_send_message():
    response = handle_request({"id": 1, "method": "tools/list"})
    tool_names = {tool["name"] for tool in response["result"]["tools"]}
    assert tool_names == {"send_message"}


def test_send_message_invokes_jxa_with_exact_arguments():
    captured = {}

    def runner(*args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps({"sent": True}), stderr="")

    response = handle_request(
        {
            "id": 2, "method": "tools/call",
            "params": {"name": "send_message", "arguments": {
                "to": "jane@example.org", "subject": "Re: pricing", "body": "Here's the pricing sheet.",
            }},
        },
        runner=runner,
    )
    payload = json.loads(captured["args"][0][-1])
    assert payload == {"to": "jane@example.org", "subject": "Re: pricing", "body": "Here's the pricing sheet."}
    assert "Message sent" in response["result"]["content"][0]["text"]


def test_send_message_reports_isError_when_a_required_argument_is_missing():
    response = handle_request(
        {"id": 3, "method": "tools/call", "params": {"name": "send_message", "arguments": {"to": "jane@example.org"}}},
        runner=_fake_runner(),
    )
    assert response["result"]["isError"] is True
    assert "subject" in response["result"]["content"][0]["text"] or "required" in response["result"]["content"][0]["text"].lower()


def test_send_message_reports_isError_when_jxa_fails():
    response = handle_request(
        {"id": 4, "method": "tools/call", "params": {"name": "send_message", "arguments": {
            "to": "jane@example.org", "subject": "Hi", "body": "Hi",
        }}},
        runner=_fake_runner(returncode=1, stderr="Mail is not configured."),
    )
    assert response["result"]["isError"] is True
    assert "Mail is not configured" in response["result"]["content"][0]["text"]


def test_unknown_tool_name_is_rejected():
    response = handle_request(
        {"id": 5, "method": "tools/call", "params": {"name": "list_unread_messages", "arguments": {}}},
        runner=_fake_runner(),
    )
    assert response["result"]["isError"] is True
    assert "Unknown tool" in response["result"]["content"][0]["text"]


def test_send_via_jxa_raises_mail_send_error_on_failure():
    try:
        _send_via_jxa({"to": "x@example.org", "subject": "s", "body": "b"}, runner=_fake_runner(returncode=1, stderr="boom"))
        assert False, "expected MailSendError"
    except MailSendError as error:
        assert "boom" in str(error)


def test_mcp_server_command_uses_the_current_interpreter():
    command, args = mcp_server_command()
    assert command == sys.executable
    assert args == ["-m", "project_os.ai.mail_send_mcp_server"]
