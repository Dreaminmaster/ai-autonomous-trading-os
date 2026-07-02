from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Callable


@dataclass
class TimerResult:
    runs: int
    completed: bool
    last_error: str | None = None

    def to_dict(self) -> dict:
        return {"runs": self.runs, "completed": self.completed, "last_error": self.last_error}


class FixedTimer:
    def run(self, fn: Callable[[], None], runs: int = 1, interval_seconds: float = 0.0) -> TimerResult:
        count = 0
        try:
            for _ in range(runs):
                fn()
                count += 1
                if interval_seconds > 0:
                    sleep(interval_seconds)
            return TimerResult(count, True)
        except Exception as exc:
            return TimerResult(count, False, str(exc))
