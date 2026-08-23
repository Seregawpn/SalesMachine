import sys
from pathlib import Path

import pytest

from project_os.ai.process_transport import ProcessTransport, TransportTimeout

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


def test_read_line_raises_transport_timeout_when_process_is_alive_but_slow():
    """fake_app_server.py never replies to "initialize" (see its docstring),
    so reading with a short timeout must raise TransportTimeout — not
    return None — because the process itself is still alive and running."""
    transport = ProcessTransport([sys.executable, str(FIXTURE_SCRIPT)])
    try:
        transport.send({"method": "initialize", "id": 1, "params": {}})
        with pytest.raises(TransportTimeout):
            transport.read_line(timeout=0.2)
        assert transport._process.poll() is None, "process should still be alive, not exited"
    finally:
        transport.close()
