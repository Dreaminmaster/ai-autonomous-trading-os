from __future__ import annotations

from typing import Protocol

from atos.domain import Candle, StrategyCandidate


class Strategy(Protocol):
    strategy_id: str
    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None: ...


class TrendFollowingStrategy:
    strategy_id = "trend_following_v1"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        if len(candles) < 20:
            return None
        fast = sum(c.close for c in candles[-5:]) / 5
        slow = sum(c.close for c in candles[-20:]) / 20
        if fast > slow:
            return StrategyCandidate(self.strategy_id, symbol, "BUY", 0.65, 0.62, "fast average above slow average", 1.0, 2.0, 240, ["trend_up"], "trend can reverse quickly")
        return None


class MeanReversionStrategy:
    strategy_id = "mean_reversion_v1"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        if len(candles) < 20:
            return None
        closes = [c.close for c in candles[-20:]]
        avg = sum(closes) / len(closes)
        last = closes[-1]
        if last < avg * 0.985:
            return StrategyCandidate(self.strategy_id, symbol, "BUY", 0.58, 0.60, "price below recent average", 1.2, 1.8, 180, ["range", "mean_reversion"], "avoid strong downtrend")
        return None


class BreakoutStrategy:
    strategy_id = "breakout_v1"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        if len(candles) < 30:
            return None
        recent_high = max(c.high for c in candles[-30:-1])
        last = candles[-1]
        if last.close > recent_high and last.volume > 0:
            return StrategyCandidate(self.strategy_id, symbol, "BUY", 0.70, 0.63, "close broke recent high", 1.5, 3.0, 360, ["breakout"], "false breakout risk")
        return None


class HoldBaselineStrategy:
    strategy_id = "hold_baseline"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        return StrategyCandidate(self.strategy_id, symbol, "HOLD", 0.0, 1.0, "baseline hold", 0.0, 0.0, 0, ["all"], "safe default")


def default_strategies() -> list[Strategy]:
    return [TrendFollowingStrategy(), MeanReversionStrategy(), BreakoutStrategy(), HoldBaselineStrategy()]
