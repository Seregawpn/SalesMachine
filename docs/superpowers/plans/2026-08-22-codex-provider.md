# Codex Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a minimal, testable `CodexProvider` that lets Project OS's daemon send a text task (classify an email, draft a reply, score a lead) to the user's own local Codex CLI and get back plain text — using the real, proven Codex app-server JSON-RPC protocol (confirmed working in the Nexy voice-codex-test app), stripped down to only what a headless backend task needs (no computer-use, no voice, no approval UI, no image inputs).

**Architecture:** Codex CLI is spawned as a subprocess (`codex app-server --stdio`) and speaks line-delimited JSON-RPC over stdin/stdout: `initialize` → `initialized` → `thread/start` (get a `threadId`) → `turn/start` (send the prompt) → a stream of events ending in `turn/completed`, with the actual answer arriving as an `item/completed` event of type `agentMessage` somewhere before that. `codex_protocol.py` holds pure message-builder/parser functions (no I/O, fully unit-testable). A `LineTransport` protocol abstracts "send a JSON message, read a JSON line back" so `CodexProvider`'s turn-taking logic can be tested against a fake transport with zero real subprocess or network activity — the same lesson learned in Phase 1 (never let a test suite make a live/expensive call by default). `ProcessTransport` is the real implementation, tested against a small fake stdio script instead of the real `codex` binary, so the suite stays fast, free, and offline; a separate manual smoke-test step at the end verifies it against the real CLI.

**Tech Stack:** Python 3.11+ (matches the existing `project_os` package), stdlib `subprocess`/`threading`/`queue`/`json` only — no new third-party dependency.

## Global Constraints

- Local-only, zero recurring infrastructure cost — this uses the user's own already-authenticated `codex` CLI (ChatGPT Plus/Codex subscription, confirmed active), never a metered API (05_Decisions_And_Amendments §2.1, §3.2).
- No test in this codebase may make a live network call or depend on an external service being installed/authenticated by default — Phase 1's final review found exactly this class of bug in `tests/test_daemon.py` (a scheduler test that could silently hit the real Unipile API). `ProcessTransport` must be tested against a local fake script, never the real `codex` binary, in the automated suite.
- Never write API keys, tokens, or other secrets into this repository (05_Decisions_And_Amendments §3.5) — not applicable here directly (Codex CLI manages its own `~/.codex/auth.json`), but no test or fixture in this plan may read or depend on the contents of that file.
- Follow the existing `project_os` package conventions: no ORM anywhere in this codebase (not relevant to this plan directly, but keep the same "thin, direct, no framework magic" style), stdlib-first, real-behavior tests over mocks except at a genuine external-process/network boundary (mirroring the one accepted mocking exception from Phase 1's Unipile client task).
- This plan builds on top of the `project_os` package already on `main` (SQLite CRM, Action Center, daemon, Unipile sync from Phase 1) but does not modify any of it — `CodexProvider` is a new, independent module with no callers yet. Wiring it into an actual AI task (email classification, drafting) is a separate, later plan.

---

## File Structure

```
~/ProjectOS/
  src/project_os/
    ai/
      __init__.py
      codex_protocol.py       # pure message builders + event parser
      codex_provider.py       # CodexProvider: turn-taking logic, transport-agnostic
      process_transport.py    # ProcessTransport: spawns the real `codex app-server` subprocess
  tests/
    test_codex_protocol.py
    test_codex_provider.py
    test_process_transport.py
    fixtures/
      fake_app_server.py      # a tiny stdio script simulating codex app-server, for ProcessTransport tests
```

---

### Task 1: Codex protocol message builders + event parser

**Files:**
- Create: `src/project_os/ai/__init__.py`
- Create: `src/project_os/ai/codex_protocol.py`
- Test: `tests/test_codex_protocol.py`

**Interfaces:**
- Produces: `initialize_request(request_id: int) -> dict`, `initialized_notification() -> dict`, `thread_start_request(request_id: int, cwd: str, developer_instructions: str, *, sandbox: str = "read-only", approval_policy: str = "never") -> dict`, `turn_start_request(request_id: int, thread_id: str, prompt: str) -> dict`, `CodexEvent` (dataclass: `kind: str`, `value: Any = None`), `parse_event(line: str) -> CodexEvent` (kinds used by this plan: `"thread_created"`, `"agent_message"`, `"turn_completed"`, `"error"`, `"ignored"`).

This is a deliberately small subset of the real protocol used by Nexy's `voice_codex/protocol.py` — only what a headless text-in/text-out task needs. `sandbox="read-only"` (not Nexy's `"danger-full-access"`) because Project OS's backend tasks (classify, draft, score) never need Codex to run shell commands or edit files — they just need it to think and answer.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_codex_protocol.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_codex_protocol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.ai'`

- [ ] **Step 3: Write `src/project_os/ai/__init__.py`** (empty file)

- [ ] **Step 4: Write `src/project_os/ai/codex_protocol.py`**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_codex_protocol.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6: Commit**

```bash
git add src/project_os/ai/__init__.py src/project_os/ai/codex_protocol.py tests/test_codex_protocol.py
git commit -m "feat: Codex app-server protocol message builders and event parser"
```

---

### Task 2: CodexProvider (transport-agnostic turn-taking logic)

**Files:**
- Create: `src/project_os/ai/codex_provider.py`
- Test: `tests/test_codex_provider.py`

**Interfaces:**
- Consumes: `codex_protocol.initialize_request`, `initialized_notification`, `thread_start_request`, `turn_start_request`, `parse_event`, `CodexEvent` (Task 1).
- Produces: `LineTransport` (a `typing.Protocol` with `send(message: dict) -> None`, `read_line(timeout: float | None = None) -> str | None`, `close() -> None`), `CodexProviderError(RuntimeError)`, `CodexProvider(transport: LineTransport)` with `.run_task(prompt: str, *, cwd: str = ".", developer_instructions: str = DEFAULT_DEVELOPER_INSTRUCTIONS, timeout: float = 60.0) -> str` and `.close() -> None`.

**Why a fake transport, not a real subprocess, for this task's tests:** `CodexProvider`'s logic (send the right messages in the right order, correctly interpret the event stream, raise clearly on error/timeout) is independent of *how* those JSON lines get to and from Codex. Testing it against a fake, in-memory transport makes these tests instant, deterministic, and safe to run in CI with no `codex` binary installed and no network access — exactly the property Phase 1's final review found missing from `tests/test_daemon.py`. The real subprocess plumbing is Task 3's job, tested separately.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_codex_provider.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_codex_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.ai.codex_provider'`

- [ ] **Step 3: Write `src/project_os/ai/codex_provider.py`**

```python
from typing import Any, Protocol

from project_os.ai import codex_protocol

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_codex_provider.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/project_os/ai/codex_provider.py tests/test_codex_provider.py
git commit -m "feat: CodexProvider turn-taking logic against a pluggable transport"
```

---

### Task 3: ProcessTransport (real subprocess) tested against a fake stdio script

**Files:**
- Create: `src/project_os/ai/process_transport.py`
- Create: `tests/fixtures/fake_app_server.py`
- Test: `tests/test_process_transport.py`

**Interfaces:**
- Consumes: `LineTransport` protocol (Task 2, structural — `ProcessTransport` satisfies it by having the same three methods, no explicit inheritance needed).
- Produces: `ProcessTransport(command: list[str])` with `.send`, `.read_line`, `.close`, matching `LineTransport`.

**Why a fake script instead of the real `codex` binary:** this task proves `ProcessTransport`'s subprocess/threading/queue plumbing works — that bytes written to stdin arrive as lines on the fake process's stdin, and lines the fake process writes to stdout arrive back through `read_line`. It does not need to prove anything about Codex's actual behavior (Task 2 already covers the protocol logic against a fake transport). Using a tiny local Python script as the "process" keeps this test fast, deterministic, and independent of whether `codex` is installed or logged in on the machine running the tests.

- [ ] **Step 1: Write the fake app-server fixture script**

```python
# tests/fixtures/fake_app_server.py
"""A minimal stdio echo server for testing ProcessTransport.

Reads one JSON line at a time from stdin. For a "thread/start" request,
replies with a thread_created result. For a "turn/start" request, emits
an agentMessage event echoing the prompt back, then a turn/completed
event. Ignores everything else (including "initialize"/"initialized",
which ProcessTransport's own tests don't need a reply to).
"""
import json
import sys


def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        message = json.loads(raw_line)
        method = message.get("method")

        if method == "thread/start":
            response = {"id": message["id"], "result": {"thread": {"id": "fake-thread-1"}}}
            print(json.dumps(response), flush=True)

        elif method == "turn/start":
            prompt = message["params"]["input"][0]["text"]
            agent_message = {
                "method": "item/completed",
                "params": {"item": {"type": "agentMessage", "text": f"echo: {prompt}"}},
            }
            print(json.dumps(agent_message), flush=True)
            print(json.dumps({"method": "turn/completed", "params": {}}), flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_process_transport.py
import sys
from pathlib import Path

from project_os.ai.process_transport import ProcessTransport

FIXTURE_SCRIPT = Path(__file__).parent / "fixtures" / "fake_app_server.py"


def test_process_transport_round_trips_a_message_through_a_real_subprocess():
    transport = ProcessTransport([sys.executable, str(FIXTURE_SCRIPT)])
    try:
        transport.send({"method": "thread/start", "id": 1, "params": {}})
        line = transport.read_line(timeout=5.0)
        assert line is not None
        assert '"fake-thread-1"' in line
    finally:
        transport.close()


def test_process_transport_streams_multiple_lines_in_order():
    transport = ProcessTransport([sys.executable, str(FIXTURE_SCRIPT)])
    try:
        transport.send(
            {"method": "turn/start", "id": 2, "params": {"input": [{"type": "text", "text": "hello"}]}}
        )
        first_line = transport.read_line(timeout=5.0)
        second_line = transport.read_line(timeout=5.0)

        assert first_line is not None and "echo: hello" in first_line
        assert second_line is not None and "turn/completed" in second_line
    finally:
        transport.close()


def test_read_line_returns_none_after_the_process_exits():
    transport = ProcessTransport([sys.executable, "-c", "pass"])  # exits immediately, no output
    try:
        line = transport.read_line(timeout=5.0)
        assert line is None
    finally:
        transport.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_process_transport.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'project_os.ai.process_transport'`

- [ ] **Step 4: Write `src/project_os/ai/process_transport.py`**

```python
import json
import queue
import subprocess
import threading

_END_OF_STREAM = object()


class ProcessTransport:
    """A LineTransport backed by a real subprocess speaking line-delimited JSON."""

    def __init__(self, command: list[str]) -> None:
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        if self._process.stdin is None or self._process.stdout is None:
            self._process.kill()
            raise RuntimeError("Failed to open stdio pipes for the Codex subprocess.")

        self._lines: queue.Queue[str | object] = queue.Queue()
        self._reader = threading.Thread(target=self._read_output, daemon=True)
        self._reader.start()

    def _read_output(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                self._lines.put(line.rstrip("\n"))
        finally:
            self._lines.put(_END_OF_STREAM)

    def send(self, message: dict) -> None:
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(message) + "\n")
        self._process.stdin.flush()

    def read_line(self, timeout: float | None = None) -> str | None:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            return None
        if line is _END_OF_STREAM:
            return None
        return line

    def close(self) -> None:
        self._process.terminate()
        try:
            self._process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_process_transport.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `python -m pytest -v`
Expected: all tests pass (74 from Phase 1 + 10 + 5 + 3 = 92).

- [ ] **Step 7: Commit**

```bash
git add src/project_os/ai/process_transport.py tests/fixtures/fake_app_server.py tests/test_process_transport.py
git commit -m "feat: ProcessTransport for the real Codex app-server subprocess"
```

---

### Task 4: Wire ProcessTransport as CodexProvider's real-world default + manual smoke test

**Files:**
- Modify: `src/project_os/ai/codex_provider.py`
- Test: `tests/test_codex_provider.py` (one new test)

**Interfaces:**
- Consumes: `ProcessTransport` (Task 3).
- Produces: `CodexProvider.for_codex_cli(codex_path: str = "codex", model: str = "gpt-5.5") -> CodexProvider` — a convenience constructor that builds a real `ProcessTransport` running the actual Codex CLI, for production/manual use. The existing `CodexProvider(transport)` constructor is unchanged and stays the one every automated test uses.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_codex_provider.py

def test_for_codex_cli_builds_a_provider_with_a_process_transport():
    from project_os.ai.process_transport import ProcessTransport

    # We don't want this test to actually spawn `codex` (see Global
    # Constraints: no live external dependency in the automated suite),
    # so this only checks that for_codex_cli builds the right command —
    # it does not construct a real CodexProvider from it.
    from project_os.ai.codex_provider import CodexProvider

    command = CodexProvider._codex_cli_command("codex", "gpt-5.5")
    assert command == ["codex", "app-server", "--stdio", "-c", 'model="gpt-5.5"']
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_codex_provider.py -v`
Expected: FAIL with `AttributeError: type object 'CodexProvider' has no attribute '_codex_cli_command'`

- [ ] **Step 3: Modify `src/project_os/ai/codex_provider.py`**

Add these two additions (keep everything else in the file unchanged):

```python
# Add this import at the top, alongside the existing codex_protocol import:
from project_os.ai.process_transport import ProcessTransport
```

```python
# Add these as methods on the CodexProvider class, alongside __init__:

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_codex_provider.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `python -m pytest -v`
Expected: all 93 tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/project_os/ai/codex_provider.py tests/test_codex_provider.py
git commit -m "feat: CodexProvider.for_codex_cli production entrypoint"
```

- [ ] **Step 7: Manual smoke test against the real Codex CLI (not part of the automated suite)**

This step proves the whole stack actually works end-to-end against the real `codex` binary and the user's real ChatGPT/Codex subscription — something no automated test in this plan does, by design (Global Constraints). Run this by hand once, from the repo root, with the venv active:

```bash
python3 - <<'EOF'
from project_os.ai.codex_provider import CodexProvider

provider = CodexProvider.for_codex_cli()
try:
    result = provider.run_task(
        "Reply with exactly the two words: task complete",
        cwd="/tmp",
    )
    print("Codex said:", repr(result))
finally:
    provider.close()
EOF
```

Expected: prints `Codex said: 'task complete'` (or very close to it — the model may not follow "exactly" perfectly; the point is that a real response comes back within a few seconds and the process exits cleanly, not that the wording is byte-exact). If this hangs, check that `codex login` has been run and the account is authenticated (`codex_account_plan.py`'s pattern of reading `~/.codex/auth.json` in the Nexy codebase is a reference for how to check this programmatically later, if needed — not needed for this manual step).

---

## Self-Review Notes

- **Spec coverage:** every function/class named in each task's "Produces" is implemented in that same task with real code — no forward references to undefined names. `CodexProvider`'s constructor signature (`transport: LineTransport`) is identical across Tasks 2 and 4; Task 4 only adds `for_codex_cli` and `_codex_cli_command`, it does not change the existing constructor, so every Task 2 test keeps passing unmodified.
- **Explicitly out of scope for this plan:** wiring `CodexProvider` into an actual Project OS task (email classification, draft generation, lead scoring) — that requires the `AI task contract` from the original spec (task_id, project_id, task_type, structured output schema, retry/Needs-Review states) and belongs in the Gmail-integration plan that follows this one, not here. Structured/JSON-schema-validated output is also out of scope here — this plan only proves plain-text round-trip; schema validation is a concern for whichever later plan defines the first structured AI task.
- **Placeholder scan:** no TBD/TODO markers; every step has runnable code, including the fixture script.
- **Type consistency:** `LineTransport`'s three methods (`send`, `read_line`, `close`) have identical signatures across `codex_provider.py` (the Protocol definition) and `process_transport.py` (`ProcessTransport`, which satisfies it structurally). `CodexEvent.kind`/`CodexEvent.value` naming is consistent between `codex_protocol.py` and every consumer in `codex_provider.py`.
