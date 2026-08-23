import json
from typing import Any, Protocol

from project_os.ai import codex_protocol
from project_os.ai.process_transport import ProcessTransport, TransportTimeout

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

    def __init__(self, transport: LineTransport, *, timeout: float = 30.0) -> None:
        self._transport = transport
        self._next_id = 1
        self._timeout = timeout
        self._initialize()

    @staticmethod
    def _codex_cli_command(
        codex_path: str,
        model: str,
        mcp_servers: dict[str, tuple[str, list[str]]] | None = None,
        *,
        allow_send: bool = False,
    ) -> list[str]:
        for name in (mcp_servers or {}):
            if "send" in name.lower() and not allow_send:
                raise ValueError(
                    f"MCP server {name!r} looks like a send-capable server, but "
                    f"allow_send=True was not passed. This is a deliberate guard: "
                    f"a Codex thread should only ever get send capability for the "
                    f"one narrow 'send this approved draft' task, never as a side "
                    f"effect of configuring other servers. Pass allow_send=True "
                    f"explicitly if this thread genuinely needs to send."
                )
        command = [codex_path, "app-server", "--stdio", "-c", f'model="{model}"']
        for name, (server_command, server_args) in (mcp_servers or {}).items():
            command.extend([
                "-c", f"mcp_servers.{name}.enabled=true",
                "-c", f"mcp_servers.{name}.command={json.dumps(server_command)}",
                "-c", f"mcp_servers.{name}.args={json.dumps(server_args)}",
            ])
        return command

    @classmethod
    def for_codex_cli(
        cls,
        codex_path: str = "codex",
        model: str = "gpt-5.5",
        mcp_servers: dict[str, tuple[str, list[str]]] | None = None,
        *,
        allow_send: bool = False,
        timeout: float = 30.0,
    ) -> "CodexProvider":
        """Build a CodexProvider that runs the real, locally installed Codex CLI.

        `mcp_servers` maps a server name to `(command, args)` — e.g.
        `{"project-os-mail": mail_read_mcp_server.mcp_server_command()}` —
        giving that Codex thread tool-level access to whatever the named
        server exposes. Omit it (the default) for a plain text-only task
        with no tools at all.

        Any server name containing "send" (case-insensitive) — e.g.
        `{"project-os-mail-send": mail_send_mcp_server.mcp_server_command()}` —
        requires `allow_send=True`, or this raises `ValueError`. This is a
        deliberate guard: a Codex thread should only ever get send
        capability for the one narrow "send this approved draft" task,
        never as an incidental side effect of whatever `mcp_servers` dict a
        caller happens to build.

        Use this for production/manual use, never in the automated test
        suite — it spawns a real subprocess and, on first task, makes a
        real call through the user's authenticated Codex/ChatGPT account.
        """
        transport = ProcessTransport(
            cls._codex_cli_command(codex_path, model, mcp_servers, allow_send=allow_send)
        )
        try:
            return cls(transport, timeout=timeout)
        except Exception:
            transport.close()
            raise

    def _request_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _initialize(self) -> None:
        self._transport.send(codex_protocol.initialize_request(self._request_id()))
        try:
            line = self._transport.read_line(timeout=self._timeout)
        except TransportTimeout:
            raise CodexProviderError(
                f"Codex app-server did not respond to initialize within {self._timeout}s (timed out)."
            ) from None
        if line is None:
            raise CodexProviderError("Codex app-server closed the connection before completing initialize.")
        # line is the initialize response; its contents are not needed.
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
            try:
                line = self._transport.read_line(timeout=timeout)
            except TransportTimeout:
                raise CodexProviderError(
                    f"Codex app-server did not start a thread within {timeout}s (timed out)."
                ) from None
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
            try:
                line = self._transport.read_line(timeout=timeout)
            except TransportTimeout:
                raise CodexProviderError(
                    f"Codex app-server did not complete the turn within {timeout}s (timed out)."
                ) from None
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
            elif event.kind == "mcp_elicitation_requested":
                self._transport.send(codex_protocol.mcp_elicitation_response(event.value, "accept"))

    def close(self) -> None:
        self._transport.close()
