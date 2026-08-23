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
