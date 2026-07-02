from __future__ import annotations

from dataclasses import dataclass, asdict

from atos.domain import Candle
from atos.runtime import AutonomousRuntime
from atos.evaluator import Evaluator


@dataclass
class ResearchLoopReport:
    windows: int
    ledger_events: int
    evaluation: dict

    def to_dict(self) -> dict:
        return asdict(self)


class ResearchLoop:
    def __init__(self, policy: dict):
        self.policy = policy

    def run_windows(self, symbol: str, windows: list[list[Candle]]) -> ResearchLoopReport:
        runtime = AutonomousRuntime(self.policy)
        results: list[float] = []
        for window in windows:
            if not window:
                continue
            output = runtime.run_once(symbol, window, mark_price=window[-1].close)
            if output.get("execution", {}).get("status") == "FILLED_SIMULATED":
                results.append(0.0)
        return ResearchLoopReport(windows=len(windows), ledger_events=runtime.ledger.count(), evaluation=Evaluator().summarize(results).to_dict())
