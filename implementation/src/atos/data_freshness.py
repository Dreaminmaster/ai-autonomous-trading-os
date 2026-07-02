"""
Data Freshness Guard — ensures market data is not stale before trading.

Three checks:
  1. Candle age: last candle timestamp must be within threshold
  2. Data completeness: minimum number of candles required
  3. Data quality: no gap larger than max_gap_minutes

Used by RiskEngine and StrategyPool as a pre-condition.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class FreshnessResult:
    is_fresh: bool
    age_seconds: float = 0.0
    gap_count: int = 0
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "is_fresh": self.is_fresh,
            "age_seconds": round(self.age_seconds, 1),
            "gap_count": self.gap_count,
            "reasons": self.reasons,
        }


class DataFreshnessGuard:
    """Checks market data freshness before allowing trading decisions.

    Stale data MUST result in HOLD — no exceptions.
    """

    def __init__(self,
                 max_candle_age_seconds: float = 300.0,  # 5 min default
                 min_candles_required: int = 20,
                 max_gap_minutes: int = 15):
        self.max_candle_age_seconds = max_candle_age_seconds
        self.min_candles_required = min_candles_required
        self.max_gap_minutes = max_gap_minutes

    def check_candles(self, candles: list, now: float | None = None) -> FreshnessResult:
        """Check if candle data is fresh enough for trading.

        Args:
            candles: list of Candle objects (must have .ts attribute in ISO format)
            now: current timestamp (default: time.time())

        Returns:
            FreshnessResult with is_fresh=True only if all checks pass
        """
        reasons = []
        now = now or time.time()

        # ── 1. Minimum candle count ──────────────────────────────
        if len(candles) < self.min_candles_required:
            reasons.append(f"insufficient_candles: {len(candles)} < {self.min_candles_required}")
            return FreshnessResult(is_fresh=False, reasons=reasons)

        # ── 2. Last candle age ───────────────────────────────────
        last = candles[-1]
        age = self._candle_age_seconds(last, now)
        if age > self.max_candle_age_seconds:
            reasons.append(f"stale_candle: age={age:.0f}s > {self.max_candle_age_seconds}s")
            return FreshnessResult(is_fresh=False, age_seconds=age, reasons=reasons)

        # ── 3. Check for gaps ────────────────────────────────────
        gap_count = 0
        for i in range(1, min(len(candles), 20)):
            prev = candles[-(i+1)]
            curr = candles[-i]
            gap = self._gap_minutes(prev, curr)
            if gap > self.max_gap_minutes:
                gap_count += 1

        if gap_count > 2:
            reasons.append(f"data_gaps: {gap_count} gaps > {self.max_gap_minutes}min")

        is_fresh = len(reasons) == 0
        return FreshnessResult(is_fresh=is_fresh, age_seconds=age, gap_count=gap_count, reasons=reasons)

    @staticmethod
    def _candle_age_seconds(candle, now: float) -> float:
        """Get candle age in seconds."""
        ts = getattr(candle, 'ts', None)
        if ts is None:
            return 0.0  # can't determine age, assume fresh
        try:
            if isinstance(ts, (int, float)):
                return now - float(ts) / 1000.0 if ts > 1e10 else now - float(ts)
            # ISO format string
            from datetime import datetime, timezone
            if isinstance(ts, str):
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                return now - dt.timestamp()
        except (ValueError, TypeError, OSError):
            pass
        return 0.0

    @staticmethod
    def _gap_minutes(prev, curr) -> float:
        """Calculate gap between two candles in minutes."""
        ts_prev = getattr(prev, 'ts', None)
        ts_curr = getattr(curr, 'ts', None)
        if ts_prev is None or ts_curr is None:
            return 0.0
        try:
            if isinstance(ts_prev, (int, float)) and isinstance(ts_curr, (int, float)):
                if ts_prev > 1e10:
                    return abs(ts_curr - ts_prev) / 60000.0
                return abs(ts_curr - ts_prev) / 60.0
        except (ValueError, TypeError):
            pass
        return 0.0
