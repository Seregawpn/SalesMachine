import pytest

from project_os.ai.codex_provider import CodexProvider, CodexProviderError


class FakeTransport:
    """An in-memory LineTransport: pre-loaded with the lines it will
    'receive', and it records every message sent to it."""

    def __init__(self, lines_to_receive: list[str | None]):
        self._lines = list(lines_to_receive)
        self.sent: list[dict] = []
        self.closed = False

    def send(self, message: dict) -> None:
        self.sent.append(message)

    def read_line(self, timeout: float | None = None) -> str | None:
        if not self._lines:
            return None
        return self._lines.pop(0)

    def close(self) -> None:
        self.closed = True


def _initialize_response_line() -> str:
    import json
    return json.dumps({"id": 1, "result": {}})


def _thread_created_line(thread_id: str = "thread-abc") -> str:
    import json
    return json.dumps({"id": 2, "result": {"thread": {"id": thread_id}}})


def _agent_message_line(text: str) -> str:
    import json
    return json.dumps({"method": "item/completed", "params": {"item": {"type": "agentMessage", "text": text}}})


def _turn_completed_line() -> str:
    import json
    return json.dumps({"method": "turn/completed", "params": {}})


def _error_line(message: str) -> str:
    import json
    return json.dumps({"error": {"message": message}})


def test_run_task_sends_initialize_thread_start_and_turn_start_in_order():
    transport = FakeTransport([
        _initialize_response_line(),
        _thread_created_line(),
        _agent_message_line("Positive reply, wants a demo."),
        _turn_completed_line(),
    ])

    provider = CodexProvider(transport)
    result = provider.run_task("Classify this reply.")

    assert result == "Positive reply, wants a demo."
    methods = [message["method"] for message in transport.sent]
    assert methods == ["initialize", "initialized", "thread/start", "turn/start"]


def test_run_task_returns_the_last_agent_message_before_turn_completed():
    transport = FakeTransport([
        _initialize_response_line(),
        _thread_created_line(),
        _agent_message_line("Draft 1"),
        _agent_message_line("Final draft"),
        _turn_completed_line(),
    ])

    provider = CodexProvider(transport)
    result = provider.run_task("Draft a reply.")

    assert result == "Final draft"


def test_run_task_raises_on_protocol_error_event():
    transport = FakeTransport([
        _initialize_response_line(),
        _error_line("model unavailable"),
    ])

    provider = CodexProvider(transport)

    with pytest.raises(CodexProviderError, match="model unavailable"):
        provider.run_task("Classify this reply.")


def test_run_task_raises_if_transport_closes_before_turn_completes():
    transport = FakeTransport([
        _initialize_response_line(),
        _thread_created_line(),
        _agent_message_line("partial"),
        None,  # transport closed / EOF
    ])

    provider = CodexProvider(transport)

    with pytest.raises(CodexProviderError):
        provider.run_task("Classify this reply.")


def test_close_closes_the_transport():
    transport = FakeTransport([_initialize_response_line()])
    provider = CodexProvider(transport)

    provider.close()

    assert transport.closed is True
