from __future__ import annotations

from dataclasses import dataclass, asdict

from atos_core import new_id, utc_now


@dataclass
class PaperExecutionResult:
    order_id: str
    status: str
    symbol: str
    action: str
    price: float
    notional: float
    fee: float
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


class PaperExecutor:
    def __init__(self, fee_bps: float = 10.0, slippage_bps: float = 5.0):
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps

    def execute(self, trade_intent: dict, risk_decision: dict, mark_price: float, equity_usdt: float) -> PaperExecutionResult:
        if risk_decision.get('decision') != 'APPROVED':
            return PaperExecutionResult(new_id('paper_order'), 'BLOCKED_BY_RISK', trade_intent.get('symbol', ''), trade_intent.get('action', ''), mark_price, 0.0, 0.0, utc_now())

        action = trade_intent['action']
        if action == 'HOLD':
            return PaperExecutionResult(new_id('paper_order'), 'NOOP_HOLD', trade_intent['symbol'], action, mark_price, 0.0, 0.0, utc_now())

        notional = equity_usdt * float(trade_intent.get('position_size_pct', 0.0)) / 100.0
        fee = notional * self.fee_bps / 10000.0
        return PaperExecutionResult(new_id('paper_order'), 'FILLED_SIMULATED', trade_intent['symbol'], action, mark_price, notional, fee, utc_now())
