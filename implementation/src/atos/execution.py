from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from atos.core import new_id, utc_now


@dataclass
class ExecutionResult:
    order_id: str
    status: str
    symbol: str
    action: str
    price: float
    notional: float
    fee: float
    timestamp: str
    mode: str = "paper"
    execution_intent_id: str | None = None
    fill_id: str | None = None
    durable_outcome: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class PaperExecutor:
    def __init__(self, fee_bps: float = 10.0, slippage_bps: float = 5.0):
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    def execute(
        self,
        trade_intent: dict,
        risk_decision: dict,
        mark_price: float,
        equity_usdt: float,
        *,
        execution_context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        del execution_context
        if risk_decision.get("decision") != "APPROVED":
            return ExecutionResult(
                new_id("paper_order"),
                "BLOCKED_BY_RISK",
                trade_intent.get("symbol", ""),
                trade_intent.get("action", ""),
                mark_price,
                0.0,
                0.0,
                utc_now(),
            )
        action = trade_intent.get("action")
        if action == "HOLD":
            return ExecutionResult(
                new_id("paper_order"),
                "NOOP_HOLD",
                trade_intent.get("symbol", ""),
                action,
                mark_price,
                0.0,
                0.0,
                utc_now(),
            )
        notional = (
            equity_usdt * float(trade_intent.get("position_size_pct", 0.0)) / 100.0
        )
        slip = self.slippage_bps / 10000.0
        fill_price = mark_price * (1.0 + slip if action == "BUY" else 1.0 - slip)
        fee = notional * self.fee_bps / 10000.0
        return ExecutionResult(
            new_id("paper_order"),
            "FILLED_SIMULATED",
            trade_intent.get("symbol", ""),
            action,
            fill_price,
            notional,
            fee,
            utc_now(),
        )


class ShadowExecutor(PaperExecutor):
    """Public-data observation only; never sends or represents a real order."""

    def execute(self, *args, **kwargs) -> ExecutionResult:
        result = super().execute(*args, **kwargs)
        status = (
            "SHADOW_SIMULATED" if result.status == "FILLED_SIMULATED" else result.status
        )
        return replace(result, status=status, mode="shadow")


class GuardedExchangeExecutor:
    def __init__(self, enabled: bool = False):
        self.enabled = enabled

    def execute(self, *args, **kwargs):
        if not self.enabled:
            raise PermissionError("Guarded exchange path is disabled by default")
        raise NotImplementedError(
            "External exchange adapter must be connected locally behind this guard"
        )
