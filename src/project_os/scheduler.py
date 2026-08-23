import logging
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class _Job:
    name: str
    interval_seconds: float
    func: Callable[[], None]
    last_run: float = float('-inf')


class Scheduler:
    def __init__(self) -> None:
        self._jobs: list[_Job] = []

    def register(self, name: str, interval_seconds: float, func: Callable[[], None]) -> None:
        self._jobs.append(_Job(name=name, interval_seconds=interval_seconds, func=func))

    def run_pending(self, now: float | None = None) -> list[str]:
        current = now if now is not None else time.time()
        ran = []
        for job in self._jobs:
            if current - job.last_run >= job.interval_seconds:
                job.last_run = current
                try:
                    job.func()
                except Exception:
                    logger.exception("scheduled job %r failed", job.name)
                    continue
                ran.append(job.name)
        return ran
