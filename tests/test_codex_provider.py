import sys
from pathlib import Path

import pytest

from project_os.ai.codex_provider import CodexProvider, CodexProviderError
from project_os.ai.process_transport import ProcessTransport, TransportTimeout

FIXTURE_SCRIPT = Path(__file__).parent / "fixtures" / "fake_app_server.py"


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


class TimeoutFakeTransport(FakeTransport):
    """A LineTransport whose read_line always raises TransportTimeout,
    simulating a slow-but-alive process rather than a closed one."""

    def read_line(self, timeout: float | None = None) -> str | None:
        raise TransportTimeout(f"No line received within {timeout}s (process is still running).")


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


def test_for_codex_cli_builds_a_provider_with_a_process_transport():
    from project_os.ai.process_transport import ProcessTransport

    # We don't want this test to actually spawn `codex` (see Global
    # Constraints: no live external dependency in the automated suite),
    # so this only checks that for_codex_cli builds the right command —
    # it does not construct a real CodexProvider from it.
    from project_os.ai.codex_provider import CodexProvider

    command = CodexProvider._codex_cli_command("codex", "gpt-5.5")
    assert command == ["codex", "app-server", "--stdio", "-c", 'model="gpt-5.5"']


def test_init_raises_codex_provider_error_when_initialize_times_out():
    """If the transport times out (process alive, no response yet) while
    waiting for the initialize response, __init__ must not hang or treat
    it as a closed connection — it should raise a clear timeout error."""
    transport = TimeoutFakeTransport([])

    with pytest.raises(CodexProviderError, match="timed out"):
        CodexProvider(transport, timeout=0.01)


def test_init_still_raises_closed_connection_error_on_genuine_eof():
    """A transport returning None (genuine EOF, not a timeout) should still
    produce the original 'closed the connection' message, unchanged."""
    transport = FakeTransport([])  # empty list -> read_line returns None

    with pytest.raises(CodexProviderError, match="closed the connection"):
        CodexProvider(transport)


def test_for_codex_cli_closes_transport_and_does_not_leak_process_on_init_failure(monkeypatch):
    """If CodexProvider construction fails (e.g. the initialize handshake
    times out), for_codex_cli must close the transport it already spawned
    rather than leaking the subprocess."""
    created: dict[str, ProcessTransport] = {}
    original_init = ProcessTransport.__init__

    def spy_init(self, command):
        original_init(self, command)
        created["transport"] = self

    monkeypatch.setattr(ProcessTransport, "__init__", spy_init)
    monkeypatch.setattr(
        CodexProvider,
        "_codex_cli_command",
        staticmethod(lambda codex_path, model: [sys.executable, str(FIXTURE_SCRIPT)]),
    )

    # fake_app_server.py never replies to "initialize", so this times out
    # quickly while the subprocess is still alive.
    with pytest.raises(CodexProviderError):
        CodexProvider.for_codex_cli(timeout=0.2)

    transport = created["transport"]
    assert transport._process.poll() is not None, "subprocess was leaked instead of being closed"
