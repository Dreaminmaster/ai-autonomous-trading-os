"""
Strategy Scoring Engine — evaluates strategy performance.

Computes:
  - Win rate, loss rate
  - Average PnL
  - Sharpe ratio (approximate, assuming 0 risk-free rate)
  - Max drawdown
  - Profit factor (gross profit / gross loss)
  - Weight delta (bounded [-0.1, +0.05] per review)
  - Status recommendations: active, caution, paused

Used by the Review Engine to update strategy weights.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from statistics import mean, stdev


@dataclass
class StrategyScore:
    strategy_id: str
    trades: int
    wins: int
    losses: int
    avg_pnl_pct: float
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    profit_factor: float = 0.0
    weight_delta: float = 0.0
    recommendation: str = "no_change"
    status: str = "active"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DailyReview:
    date: str
    strategies: dict[str, StrategyScore]
    total_trades: int
    total_pnl_pct: float
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "strategies": {k: v.to_dict() for k, v in self.strategies.items()},
            "total_trades": self.total_trades,
            "total_pnl_pct": self.total_pnl_pct,
            "notes": self.notes,
        }


class ScoringEngine:
    """Computes strategy scores from PnL streams.

    Weight deltas are BOUNDED:
      - Max increase per review: +0.05
      - Max decrease per review: -0.10
      - Min weight: 0.01 (to keep in pool, can be paused)
      - Max weight: 0.50 (no single strategy dominates)
    """

    MAX_WEIGHT_INCREASE = 0.05
    MAX_WEIGHT_DECREASE = -0.10

    def score_strategy(self, strategy_id: str, pnl_values: list[float]) -> StrategyScore:
        trades = len(pnl_values)
        if trades == 0:
            return StrategyScore(strategy_id, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, "collect_more_evidence", "active")

        wins = len([x for x in pnl_values if x > 0])
        losses = len([x for x in pnl_values if x < 0])
        avg = mean(pnl_values) if pnl_values else 0.0

        # Sharpe ratio (simplified)
        if trades >= 5 and stdev(pnl_values) > 0.0001:
            sharpe = avg / max(stdev(pnl_values), 0.0001)
        else:
            sharpe = 0.0

        # Max drawdown
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in pnl_values:
            equity += pnl
            if equity > peak:
                peak = equity
            elif peak > 0:
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd

        # Profit factor
        gross_profit = sum(x for x in pnl_values if x > 0)
        gross_loss = abs(sum(x for x in pnl_values if x < 0))
        profit_factor = gross_profit / max(gross_loss, 0.0001)

        # ── Recommendation logic ──────────────────────────────

        recommendation = "no_change"
        weight_delta = 0.0

        if trades < 10:
            recommendation = "collect_more_evidence"
        elif avg > 0 and wins >= losses and sharpe > 0.3:
            recommendation = "increase_weight_carefully"
            weight_delta = min(self.MAX_WEIGHT_INCREASE, 0.01 + avg * 0.5)
        elif avg > 0 and wins >= losses:
            recommendation = "maintain_weight"
        elif avg < -0.5 or (losses > wins * 2 and trades >= 10):
            recommendation = "reduce_weight"
            weight_delta = max(self.MAX_WEIGHT_DECREASE, -0.05 - abs(avg) * 0.5)
        elif avg < 0:
            recommendation = "reduce_weight"
            weight_delta = -0.02

        # ── Status ────────────────────────────────────────────

        status = "active"
        if trades >= 10:
            if losses > wins * 3:
                status = "paused"
            elif losses > wins * 2:
                status = "caution"
            elif max_dd > 15.0:
                status = "caution"

        return StrategyScore(
            strategy_id=strategy_id,
            trades=trades,
            wins=wins,
            losses=losses,
            avg_pnl_pct=round(avg, 4),
            sharpe_ratio=round(sharpe, 3),
            max_drawdown_pct=round(max_dd, 2),
            profit_factor=round(profit_factor, 2),
            weight_delta=round(weight_delta, 4),
            recommendation=recommendation,
            status=status,
            metadata={"win_rate": round(wins / max(trades, 1), 3)},
        )

    def daily_scores(self, pnl_by_strategy: dict[str, list[float]]) -> dict:
        return {sid: self.score_strategy(sid, values).to_dict() for sid, values in pnl_by_strategy.items()}

    def daily_review(self, date: str, pnl_by_strategy: dict[str, list[float]]) -> DailyReview:
        scores = {sid: self.score_strategy(sid, values) for sid, values in pnl_by_strategy.items()}
        total_trades = sum(s.trades for s in scores.values())
        total_pnl = sum(s.avg_pnl_pct * s.trades for s in scores.values()) / max(total_trades, 1)

        notes = []
        for sid, s in scores.items():
            if s.status == "paused":
                notes.append(f"PAUSED: {sid} — {s.losses} losses in {s.trades} trades")
            elif s.status == "caution":
                notes.append(f"CAUTION: {sid} — drawdown {s.max_drawdown_pct:.1f}%")
            elif s.recommendation == "increase_weight_carefully":
                notes.append(f"PROMOTE: {sid} — Sharpe {s.sharpe_ratio:.2f}, win rate {s.metadata.get('win_rate', 0)}")

        return DailyReview(date=date, strategies=scores, total_trades=total_trades, total_pnl_pct=round(total_pnl, 4), notes=notes)


class StrategyWeightManager:
    """Manages strategy weights with bounds and normalization.

    Weights are always normalized to sum to 1.0.
    Weight changes are bounded and tracked.
    """

    def __init__(self, initial_weights: dict[str, float] | None = None):
        self.weights: dict[str, float] = dict(initial_weights) if initial_weights else {}
        self.history: list[dict] = []

    def apply_score(self, strategy_id: str, weight_delta: float) -> None:
        """Apply a weight delta from a strategy score."""
        if strategy_id not in self.weights:
            self.weights[strategy_id] = 0.10  # new strategy starts at 10%

        old = self.weights[strategy_id]
        new = old + weight_delta
        new = max(0.01, min(0.50, new))  # bounded [1%, 50%]
        self.weights[strategy_id] = new

        # Normalize to sum 1.0
        total = sum(self.weights.values())
        if total > 0:
            for k in self.weights:
                self.weights[k] /= total

        self.history.append({"strategy_id": strategy_id, "old_weight": old, "new_weight": self.weights[strategy_id], "delta": weight_delta})

    def get_weights(self) -> dict[str, float]:
        return dict(self.weights)

    def get_history(self) -> list[dict]:
        return self.history[-100:]  # last 100 changes
