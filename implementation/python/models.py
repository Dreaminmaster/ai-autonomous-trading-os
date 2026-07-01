from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any

from atos_core import Action


@dataclass
class TradeIntent:
    schema_version: str
    action: str
    symbol: str
    market_type: str
    confidence: float
    thesis: str
    evidence: list[str]
    selected_strategy_ids: list[str]
    position_size_pct: float
    stop_loss_pct: float
    take_profit_pct: float
    max_holding_minutes: int
    invalidation_conditions: list[str]
    risk_notes: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RiskDecision:
    schema_version: str
    decision: str
    reasons: list[str]
    risk_score: float
    checks: dict[str, Any]
    modified_trade_intent: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def hold_intent(reason: str, symbol: str = 'BTC-USDT') -> TradeIntent:
    return TradeIntent(
        schema_version='trade_intent.v1',
        action=Action.HOLD.value,
        symbol=symbol,
        market_type='paper_spot',
        confidence=0.0,
        thesis=f'No trade: {reason}',
        evidence=[reason],
        selected_strategy_ids=[],
        position_size_pct=0.0,
        stop_loss_pct=0.0,
        take_profit_pct=0.0,
        max_holding_minutes=0,
        invalidation_conditions=['No active thesis'],
        risk_notes=reason,
        metadata={'safe_default': True},
    )
