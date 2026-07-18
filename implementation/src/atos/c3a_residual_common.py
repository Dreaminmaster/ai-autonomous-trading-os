from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

POLICY_IDS = (
    "C3AEthResidualReversion",
    "C3ASolResidualReversion",
    "C3AStrongestLaggardResidualReversion",
)
PAIR_TO_ASSET = {
    "BTC/USDT": "BTC",
    "ETH/USDT": "ETH",
    "SOL/USDT": "SOL",
}
WINDOWS = (
    ("S1", "2024-01-01T00:00:00Z", "2024-04-01T00:00:00Z"),
    ("S2", "2024-04-01T00:00:00Z", "2024-07-01T00:00:00Z"),
    ("S3", "2024-07-01T00:00:00Z", "2024-10-01T00:00:00Z"),
)
COST_RATES = {"1.0x": 0.0015, "1.5x": 0.00225, "2.0x": 0.003}
ANNUAL_BARS = 365 * 6
STARTING_EQUITY = 1000.0


class C3AError(RuntimeError):
    pass


@dataclass(frozen=True)
class Trade:
    asset: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    quantity: float
    entry_notional: float
    entry_cost: float
    exit_notional: float
    exit_cost: float
    net_pnl: float
    reason: str
    held_bars: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "entry_notional": self.entry_notional,
            "entry_cost": self.entry_cost,
            "exit_notional": self.exit_notional,
            "exit_cost": self.exit_cost,
            "net_pnl": self.net_pnl,
            "reason": self.reason,
            "held_bars": self.held_bars,
        }


@dataclass(frozen=True)
class CellResult:
    policy_id: str
    window_id: str
    cost_label: str
    cost_rate: float
    start: str
    end: str
    starting_equity: float
    final_equity: float
    net_return: float
    max_drawdown: float
    sharpe: float | None
    profit_factor: float | str
    closed_trades: int
    annualized_one_way_turnover: float
    exposure: float
    bars: int
    turnover_contributions: tuple[float, ...]
    trades: tuple[Trade, ...]
    equity: tuple[float, ...]
    returns: tuple[float, ...]

    def row(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "window_id": self.window_id,
            "cost_label": self.cost_label,
            "cost_rate": self.cost_rate,
            "start": self.start,
            "end": self.end,
            "starting_equity": self.starting_equity,
            "final_equity": self.final_equity,
            "net_return": self.net_return,
            "max_drawdown": self.max_drawdown,
            "sharpe": self.sharpe,
            "profit_factor": self.profit_factor,
            "closed_trades": self.closed_trades,
            "annualized_one_way_turnover": self.annualized_one_way_turnover,
            "exposure": self.exposure,
            "bars": self.bars,
        }


def _ensure_finite(name: str, value: float) -> float:
    value = float(value)
    if not isfinite(value):
        raise C3AError(f"non-finite {name}: {value!r}")
    return value


def _timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp


def _max_drawdown(equity: Sequence[float]) -> float:
    if not equity:
        raise C3AError("empty equity sequence")
    peak = float(equity[0])
    drawdown = 0.0
    for raw in equity:
        value = _ensure_finite("equity", raw)
        if value <= 0:
            raise C3AError("equity must stay positive")
        peak = max(peak, value)
        drawdown = max(drawdown, 1.0 - value / peak)
    return drawdown


def _equity_returns(equity: Sequence[float]) -> tuple[float, ...]:
    returns: list[float] = []
    for previous, current in zip(equity, equity[1:]):
        previous = _ensure_finite("previous equity", previous)
        current = _ensure_finite("current equity", current)
        if previous <= 0:
            raise C3AError("equity denominator must be positive")
        returns.append(current / previous - 1.0)
    return tuple(returns)


def _sharpe(returns: Sequence[float]) -> float | None:
    values = np.asarray(tuple(float(value) for value in returns), dtype=float)
    if len(values) < 2 or not np.isfinite(values).all():
        return None
    standard_deviation = float(values.std(ddof=1))
    if standard_deviation <= 0 or not isfinite(standard_deviation):
        return None
    result = float(values.mean() / standard_deviation * sqrt(ANNUAL_BARS))
    return result if isfinite(result) else None


def _profit_factor(trades: Sequence[Trade]) -> float | str:
    gross_profit = sum(max(trade.net_pnl, 0.0) for trade in trades)
    gross_loss = abs(sum(min(trade.net_pnl, 0.0) for trade in trades))
    if gross_profit <= 0:
        return 0.0
    if gross_loss <= 0:
        return "Infinity"
    return gross_profit / gross_loss


def _positive_share(values: Iterable[float]) -> float:
    positive = [max(float(value), 0.0) for value in values]
    denominator = sum(positive)
    return max(positive, default=0.0) / denominator if denominator > 0 else 1.0


def _top_positive_share(values: Iterable[float], count: int) -> float:
    positive = sorted((max(float(value), 0.0) for value in values), reverse=True)
    denominator = sum(positive)
    return sum(positive[:count]) / denominator if denominator > 0 else 1.0
