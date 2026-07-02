from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Callable

from atos.domain import Candle
from atos.strategies import default_strategies
from atos.providers import ProviderManager, ProviderRequest
from atos.risk import RiskEngine
from atos.execution import PaperExecutor
from atos.ledger import Ledger


@dataclass
class RuntimeResult:
    loops: int
    ledger_events: int
    last_status: str

    def to_dict(self) -> dict:
        return {"loops": self.loops, "ledger_events": self.ledger_events, "last_status": self.last_status}


class AutonomousRuntime:
    def __init__(self, policy: dict, ledger: Ledger | None = None):
        self.policy = policy
        self.ledger = ledger or Ledger()
        self.providers = ProviderManager()
        self.risk = RiskEngine(policy)
        self.executor = PaperExecutor()

    def run_once(self, symbol: str, candles: list[Candle], mark_price: float = 100.0) -> dict:
        candidates = []
        for strategy in default_strategies():
            candidate = strategy.generate(symbol, candles)
            if candidate:
                candidates.append(candidate.to_dict())

        request = ProviderRequest(symbol=symbol, candidates=candidates, market_state={"mark_price": mark_price}, risk_state={})
        intent = self.providers.decide(request)
        risk_decision = self.risk.evaluate(intent.to_dict(), {"mode": self.policy.get("mode", "paper")})
        execution = self.executor.execute(intent.to_dict(), risk_decision.to_dict(), mark_price=mark_price, equity_usdt=1000.0)

        self.ledger.record("strategy_candidates", {"items": candidates})
        self.ledger.record("trade_intent", intent.to_dict())
        self.ledger.record("risk_decision", risk_decision.to_dict())
        self.ledger.record("execution", execution.to_dict())

        return {"candidates": candidates, "intent": intent.to_dict(), "risk": risk_decision.to_dict(), "execution": execution.to_dict()}

    def run_loop(self, symbol: str, candle_supplier: Callable[[], list[Candle]], loops: int = 1, interval_seconds: float = 0.0) -> RuntimeResult:
        last_status = "not_started"
        for _ in range(loops):
            candles = candle_supplier()
            mark_price = candles[-1].close if candles else 100.0
            result = self.run_once(symbol, candles, mark_price=mark_price)
            last_status = result["execution"]["status"]
            if interval_seconds > 0:
                sleep(interval_seconds)
        return RuntimeResult(loops=loops, ledger_events=self.ledger.count(), last_status=last_status)
