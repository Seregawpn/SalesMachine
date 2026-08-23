from typing import Any, Protocol

from project_os.ai import codex_protocol
from project_os.ai.process_transport import ProcessTransport

DEFAULT_DEVELOPER_INSTRUCTIONS = (
    "You are a backend text-processing worker for a sales CRM. "
    "Respond with exactly the requested output and nothing else — "
    "no greetings, no explanations, no markdown formatting unless asked for it."
)


class CodexProviderError(RuntimeError):
    pass


class LineTransport(Protocol):
    def send(self, message: dict) -> None: ...
    def read_line(self, timeout: float | None = None) -> str | None: ...
    def close(self) -> None: ...


class CodexProvider:
    """Runs one-shot text tasks through a Codex app-server transport."""

    def __init__(self, transport: LineTransport) -> None:
        self._transport = transport
        self._next_id = 1
        self._initialize()

    @staticmethod
    def _codex_cli_command(codex_path: str, model: str) -> list[str]:
        return [codex_path, "app-server", "--stdio", "-c", f'model="{model}"']

    @classmethod
    def for_codex_cli(cls, codex_path: str = "codex", model: str = "gpt-5.5") -> "CodexProvider":
        """Build a CodexProvider that runs the real, locally installed Codex CLI.

        Use this for production/manual use, never in the automated test
        suite — it spawns a real subprocess and, on first task, makes a
        real call through the user's authenticated Codex/ChatGPT account.
        """
        transport = ProcessTransport(cls._codex_cli_command(codex_path, model))
        return cls(transport)

    def _request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _initialize(self) -> None:
        self._transport.send(codex_protocol.initialize_request(self._request_id()))
        self._transport.read_line()  # discard the initialize response
        self._transport.send(codex_protocol.initialized_notification())

    def run_task(
        self,
        prompt: str,
        *,
        cwd: str = ".",
        developer_instructions: str = DEFAULT_DEVELOPER_INSTRUCTIONS,
        timeout: float = 60.0,
    ) -> str:
        self._transport.send(
            codex_protocol.thread_start_request(self._request_id(), cwd, developer_instructions)
        )
        thread_id = self._wait_for_thread_id(timeout)

        self._transport.send(
            codex_protocol.turn_start_request(self._request_id(), thread_id, prompt)
        )
        return self._wait_for_agent_message(timeout)

    def _wait_for_thread_id(self, timeout: float) -> str:
        while True:
            line = self._transport.read_line(timeout=timeout)
            if line is None:
                raise CodexProviderError("Codex app-server closed the connection before starting a thread.")
            event = codex_protocol.parse_event(line)
            if event.kind == "thread_created":
                return event.value
            if event.kind == "error":
                raise CodexProviderError(event.value)

    def _wait_for_agent_message(self, timeout: float) -> str:
        agent_text: str | None = None
        while True:
            line = self._transport.read_line(timeout=timeout)
            if line is None:
                raise CodexProviderError("Codex app-server closed the connection before the turn completed.")
            event = codex_protocol.parse_event(line)
            if event.kind == "agent_message":
                agent_text = event.value
            elif event.kind == "turn_completed":
                if agent_text is None:
                    raise CodexProviderError("Codex completed the turn without producing an agent message.")
                return agent_text
            elif event.kind == "error":
                raise CodexProviderError(event.value)

    def close(self) -> None:
        self._transport.close()
