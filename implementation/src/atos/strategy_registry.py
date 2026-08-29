"""
Strategy Registry — more trading strategies for the AI pool.

New strategies beyond the original 4 (trend, mean_reversion, breakout, hold):
  5. range_grid: identifies sideways range, suggests grid entries
  6. volatility_breakout: bursts of volume + price range expansion
  7. orderbook_imbalance: (stub) uses bid/ask skew
  8. momentum: RSI-based momentum detection
  9. funding_basis: (stub) uses funding rate for carry trades
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Protocol

from atos.domain import Candle, StrategyCandidate


class StrategyRegistry:
    """Registry of available strategies that can be enabled/disabled."""

    def __init__(self):
        self._strategies: dict[str, Strategy] = {}
        self._enabled: set[str] = set()

    def register(self, strategy: Strategy, enabled: bool = True) -> None:
        self._strategies[strategy.strategy_id] = strategy
        if enabled:
            self._enabled.add(strategy.strategy_id)

    def enable(self, strategy_id: str) -> None:
        self._enabled.add(strategy_id)

    def disable(self, strategy_id: str) -> None:
        self._enabled.discard(strategy_id)

    def all_ids(self) -> list[str]:
        return list(self._strategies.keys())

    def enabled_ids(self) -> list[str]:
        return [sid for sid in self._strategies if sid in self._enabled]

    def get(self, strategy_id: str) -> Strategy | None:
        return self._strategies.get(strategy_id)

    def generate_all(
        self, symbol: str, candles: list[Candle]
    ) -> list[StrategyCandidate]:
        """Compatibility wrapper around the diagnostic plugin runner."""
        candidates, _ = self.generate_with_diagnostics(symbol, candles)
        return candidates

    def generate_with_diagnostics(
        self, symbol: str, candles: list[Candle]
    ) -> tuple[list[StrategyCandidate], list[dict]]:
        """Run enabled plugins deterministically and isolate invalid plugins.

        A plugin exception or malformed candidate is retained as a diagnostic
        and cannot bypass the HOLD baseline or abort the operating process.
        """
        candidates: list[StrategyCandidate] = []
        diagnostics: list[dict] = []
        for sid in self.enabled_ids():
            strategy = self._strategies[sid]
            try:
                candidate = strategy.generate(symbol, candles)
                if candidate is None:
                    diagnostics.append(
                        StrategyDiagnostic(sid, "NO_SIGNAL", "no candidate").to_dict()
                    )
                    continue
                self._validate_candidate(candidate, symbol, sid)
                candidates.append(candidate)
                diagnostics.append(
                    StrategyDiagnostic(sid, "OK", "candidate accepted").to_dict()
                )
            except Exception as exc:  # noqa: BLE001 - isolate untrusted plugins
                diagnostics.append(
                    StrategyDiagnostic(
                        sid,
                        "PLUGIN_FAILED",
                        f"{type(exc).__name__}: {exc}",
                    ).to_dict()
                )
        candidates.append(HoldBaselineStrategy().generate(symbol, candles))
        return candidates, diagnostics

    @staticmethod
    def _validate_candidate(
        candidate: StrategyCandidate, symbol: str, strategy_id: str
    ) -> None:
        if not isinstance(candidate, StrategyCandidate):
            raise TypeError("strategy plugin returned a non-StrategyCandidate")
        if candidate.strategy_id != strategy_id or candidate.symbol != symbol:
            raise ValueError("strategy candidate identity drift")
        if candidate.side not in {"BUY", "SELL", "HOLD"}:
            raise ValueError("strategy candidate side is invalid")
        if not all(
            math.isfinite(float(value))
            for value in (
                candidate.signal_strength,
                candidate.confidence,
                candidate.suggested_stop_loss_pct,
                candidate.suggested_take_profit_pct,
            )
        ):
            raise ValueError("strategy candidate contains non-finite numbers")
        if not 0.0 <= float(candidate.confidence) <= 1.0:
            raise ValueError("strategy candidate confidence is outside [0, 1]")


@dataclass(frozen=True)
class StrategyDiagnostic:
    strategy_id: str
    status: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


# ── Strategy Protocol ───────────────────────────────────────────────


class Strategy(Protocol):
    strategy_id: str

    def generate(
        self, symbol: str, candles: list[Candle]
    ) -> StrategyCandidate | None: ...


# ── New Strategies ──────────────────────────────────────────────────


class RangeGridStrategy:
    strategy_id = "range_grid_v1"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        if len(candles) < 30:
            return None
        highs = [c.high for c in candles[-30:]]
        lows = [c.low for c in candles[-30:]]
        top = max(highs)
        bottom = min(lows)
        last = candles[-1].close

        range_pct = (top - bottom) / bottom * 100 if bottom > 0 else 0
        if range_pct < 1.0 or range_pct > 5.0:
            return None  # not ranging enough or too wide

        # Buy near bottom of range
        position_in_range = (last - bottom) / (top - bottom) if top > bottom else 0.5
        if position_in_range < 0.3:
            return StrategyCandidate(
                self.strategy_id,
                symbol,
                "BUY",
                0.55,
                0.58,
                f"price near range bottom ({position_in_range:.1%})",
                0.8,
                1.5,
                120,
                ["range", "grid"],
                "range breakdown stops this strategy",
            )
        return None


class VolatilityBreakoutStrategy:
    strategy_id = "volatility_breakout_v1"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        if len(candles) < 20:
            return None

        recent = candles[-20:]
        volumes = [c.volume for c in recent]
        avg_vol = sum(volumes[:-1]) / len(volumes[:-1]) if len(volumes) > 1 else 0
        last_vol = volumes[-1]

        if avg_vol <= 0:
            return None
        vol_ratio = last_vol / avg_vol

        ranges = [c.high - c.low for c in recent]
        avg_range = sum(ranges[:-1]) / len(ranges[:-1]) if len(ranges) > 1 else 0
        last_range = ranges[-1]

        range_ratio = last_range / avg_range if avg_range > 0 else 1.0

        if vol_ratio > 1.5 and range_ratio > 1.3:
            direction = "BUY" if candles[-1].close > candles[-2].close else "SELL"
            return StrategyCandidate(
                self.strategy_id,
                symbol,
                direction,
                0.60,
                0.61,
                f"vol spike {vol_ratio:.1f}x, range {range_ratio:.1f}x",
                1.5,
                3.0,
                180,
                ["volatility", "breakout"],
                "false breakout risk is high — tight stop",
            )
        return None


class MomentumStrategy:
    strategy_id = "momentum_v1"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        if len(candles) < 14:
            return None
        closes = [c.close for c in candles]

        # Simple RSI-like calculation
        gains = [max(0, closes[i] - closes[i - 1]) for i in range(1, len(closes))]
        losses = [max(0, closes[i - 1] - closes[i]) for i in range(1, len(closes))]
        avg_gain = sum(gains[-14:]) / 14
        avg_loss = sum(losses[-14:]) / 14

        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - 100.0 / (1.0 + rs)

        # RSI 30-45: oversold, potential BUY
        # RSI 55-70: overbought, potential SELL
        if rsi < 35:
            return StrategyCandidate(
                self.strategy_id,
                symbol,
                "BUY",
                0.58,
                0.62,
                f"RSI oversold at {rsi:.1f}",
                1.0,
                2.0,
                120,
                ["momentum", "oversold"],
                "RSI can stay oversold in strong downtrend",
            )
        elif rsi > 65:
            return StrategyCandidate(
                self.strategy_id,
                symbol,
                "SELL",
                0.55,
                0.58,
                f"RSI overbought at {rsi:.1f}",
                1.0,
                2.0,
                120,
                ["momentum", "overbought"],
                "RSI can stay overbought in strong uptrend",
            )
        return None


class FundingBasisStrategy:
    strategy_id = "funding_basis_v1"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        # Stub — requires external funding rate data
        # In real implementation, funding rate would be in market_state
        return None


class OrderbookImbalanceStrategy:
    strategy_id = "orderbook_imbalance_v1"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        # Stub — requires orderbook data
        # In real implementation, orderbook snapshots would be in market_state
        return None


class HoldBaselineStrategy:
    strategy_id = "hold_baseline"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate | None:
        return StrategyCandidate(
            self.strategy_id,
            symbol,
            "HOLD",
            0.0,
            1.0,
            "baseline hold",
            0.0,
            0.0,
            0,
            ["all"],
            "safe default",
        )


# ── Convenience ─────────────────────────────────────────────────────


def create_default_registry() -> StrategyRegistry:
    from atos.strategies import (
        BreakoutStrategy,
        MeanReversionStrategy,
        TrendFollowingStrategy,
    )

    registry = StrategyRegistry()
    registry.register(TrendFollowingStrategy())
    registry.register(MeanReversionStrategy())
    registry.register(BreakoutStrategy())
    registry.register(RangeGridStrategy())
    registry.register(VolatilityBreakoutStrategy())
    registry.register(MomentumStrategy())
    registry.register(FundingBasisStrategy(), enabled=False)  # needs data
    registry.register(OrderbookImbalanceStrategy(), enabled=False)  # needs data
    return registry
