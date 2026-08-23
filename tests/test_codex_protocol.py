import json

from project_os.ai.codex_protocol import (
    initialize_request,
    initialized_notification,
    thread_start_request,
    turn_start_request,
    parse_event,
)


def test_initialize_request_has_client_info():
    request = initialize_request(1)
    assert request["method"] == "initialize"
    assert request["id"] == 1
    assert request["params"]["clientInfo"]["name"] == "project_os"


def test_initialized_notification_has_no_id():
    notification = initialized_notification()
    assert notification == {"method": "initialized", "params": {}}


def test_thread_start_request_defaults_to_read_only_never_approve():
    request = thread_start_request(2, cwd="/tmp", developer_instructions="Be terse.")
    assert request["method"] == "thread/start"
    assert request["id"] == 2
    assert request["params"]["cwd"] == "/tmp"
    assert request["params"]["sandbox"] == "read-only"
    assert request["params"]["approvalPolicy"] == "never"
    assert request["params"]["developerInstructions"] == "Be terse."


def test_turn_start_request_sends_prompt_as_text_input():
    request = turn_start_request(3, thread_id="thread-abc", prompt="Summarize this email.")
    assert request["method"] == "turn/start"
    assert request["id"] == 3
    assert request["params"]["threadId"] == "thread-abc"
    assert request["params"]["input"] == [{"type": "text", "text": "Summarize this email."}]


def test_parse_event_extracts_thread_id_from_thread_start_response():
    line = json.dumps({"id": 2, "result": {"thread": {"id": "thread-xyz"}}})
    event = parse_event(line)
    assert event.kind == "thread_created"
    assert event.value == "thread-xyz"


def test_parse_event_extracts_agent_message_text():
    line = json.dumps(
        {
            "method": "item/completed",
            "params": {"item": {"type": "agentMessage", "text": "The answer is 42."}},
        }
    )
    event = parse_event(line)
    assert event.kind == "agent_message"
    assert event.value == "The answer is 42."


def test_parse_event_ignores_commentary_phase_agent_messages():
    line = json.dumps(
        {
            "method": "item/completed",
            "params": {
                "item": {"type": "agentMessage", "text": "thinking out loud", "phase": "commentary"}
            },
        }
    )
    event = parse_event(line)
    assert event.kind != "agent_message"


def test_parse_event_recognizes_turn_completed():
    line = json.dumps({"method": "turn/completed", "params": {}})
    event = parse_event(line)
    assert event.kind == "turn_completed"


def test_parse_event_extracts_error_message():
    line = json.dumps({"error": {"message": "model unavailable"}})
    event = parse_event(line)
    assert event.kind == "error"
    assert event.value == "model unavailable"


def test_parse_event_falls_back_to_ignored_for_unknown_method():
    line = json.dumps({"method": "account/rateLimits/updated", "params": {}})
    event = parse_event(line)
    assert event.kind == "ignored"


def test_parse_event_raises_on_malformed_json():
    from project_os.ai.codex_protocol import CodexProtocolError
    import pytest

    with pytest.raises(CodexProtocolError):
        parse_event("not valid json{{{")
