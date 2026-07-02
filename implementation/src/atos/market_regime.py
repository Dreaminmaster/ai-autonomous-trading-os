"""
Market Regime Detector — classifies current market condition.

Regimes:
  - trending_up: sustained upward movement, low volatility
  - trending_down: sustained downward movement, low volatility
  - volatile: high volatility, large swings
  - ranging: low volatility, mean-reverting
  - breakout: sharp move beyond recent range
  - unknown: insufficient data

Used by strategy pool to filter which strategies apply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean, stdev


@dataclass
class MarketRegime:
    regime: str  # trending_up, trending_down, volatile, ranging, breakout, unknown
    confidence: float  # 0-1
    trend_strength: float = 0.0
    volatility_pct: float = 0.0
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "confidence": self.confidence,
            "trend_strength": self.trend_strength,
            "volatility_pct": self.volatility_pct,
            "details": self.details,
        }


class MarketRegimeDetector:
    """Detects market regime from recent candles."""

    def __init__(self, lookback: int = 50):
        self.lookback = lookback

    def detect(self, closes: list[float], highs: list[float] | None = None,
               lows: list[float] | None = None) -> MarketRegime:
        """Classify the current market regime."""
        if len(closes) < 20:
            return MarketRegime(regime="unknown", confidence=0.0)

        closes = closes[-self.lookback:]
        highs = (highs or [])[-self.lookback:]
        lows = (lows or [])[-self.lookback:]

        # ── Volatility ──────────────────────────────────────────
        returns = [(closes[i] - closes[i-1]) / closes[i-1] * 100
                   for i in range(1, len(closes))]
        vol = stdev(returns) * (len(returns) ** 0.5) if len(returns) >= 2 else 0.0

        # ── Trend ───────────────────────────────────────────────
        short_ma = mean(closes[-5:]) if len(closes) >= 5 else closes[-1]
        long_ma = mean(closes) if closes else closes[-1]
        trend_pct = (short_ma - long_ma) / long_ma * 100 if long_ma > 0 else 0.0

        # ── Range ───────────────────────────────────────────────
        if highs and lows:
            recent_high = max(highs[-20:]) if len(highs) >= 20 else max(highs)
            recent_low = min(lows[-20:]) if len(lows) >= 20 else min(lows)
            range_pct = (recent_high - recent_low) / recent_low * 100 if recent_low > 0 else 0.0
        else:
            range_pct = 0.0

        # ── Classification ──────────────────────────────────────
        if vol > 5.0:
            return MarketRegime(regime="volatile", confidence=0.7, trend_strength=trend_pct, volatility_pct=vol)
        elif abs(trend_pct) > 1.5:
            if trend_pct > 0:
                return MarketRegime(regime="trending_up", confidence=0.7, trend_strength=trend_pct, volatility_pct=vol)
            else:
                return MarketRegime(regime="trending_down", confidence=0.7, trend_strength=trend_pct, volatility_pct=vol)
        elif range_pct > 0 and range_pct < 3.0:
            return MarketRegime(regime="ranging", confidence=0.6, trend_strength=trend_pct, volatility_pct=vol)
        elif range_pct >= 3.0:
            # Check for breakout: are we near the edge?
            last = closes[-1]
            recent_high = max(highs[-20:]) if len(highs) >= 20 else last
            recent_low = min(lows[-20:]) if len(lows) >= 20 else last
            mid = (recent_high + recent_low) / 2
            if abs(last - mid) / mid * 100 > range_pct * 0.4:
                return MarketRegime(regime="breakout", confidence=0.5, trend_strength=trend_pct, volatility_pct=vol)
            return MarketRegime(regime="ranging", confidence=0.5, trend_strength=trend_pct, volatility_pct=vol)
        else:
            return MarketRegime(regime="ranging", confidence=0.4, trend_strength=trend_pct, volatility_pct=vol)
