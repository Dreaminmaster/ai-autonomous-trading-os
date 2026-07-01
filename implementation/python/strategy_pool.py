from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Protocol


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class StrategyCandidate:
    strategy_id: str
    symbol: str
    side: str
    signal_strength: float
    confidence: float
    entry_reason: str
    suggested_stop_loss_pct: float
    suggested_take_profit_pct: float
    max_holding_minutes: int

    def to_dict(self) -> dict:
        return asdict(self)


class Strategy(Protocol):
    strategy_id: str
    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None: ...


class TrendFollowingStrategy:
    strategy_id = 'trend_following_v1'

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        if len(candles) < 5:
            return None
        closes = [c.close for c in candles[-5:]]
        average_previous = sum(closes[:-1]) / 4
        if closes[-1] > average_previous:
            return StrategyCandidate(
                self.strategy_id,
                symbol,
                'BUY',
                0.62,
                0.61,
                'short trend strength positive',
                1.0,
                2.0,
                240,
            )
        return None


class HoldBaselineStrategy:
    strategy_id = 'hold_baseline'

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        return StrategyCandidate(self.strategy_id, symbol, 'HOLD', 0.0, 1.0, 'baseline hold', 0.0, 0.0, 0)


def default_strategies() -> list[Strategy]:
    return [TrendFollowingStrategy(), HoldBaselineStrategy()]
