from __future__ import annotations

from dataclasses import dataclass, asdict
from statistics import mean


@dataclass
class StrategyScore:
    strategy_id: str
    trades: int
    wins: int
    losses: int
    avg_pnl_pct: float
    weight_delta: float
    recommendation: str

    def to_dict(self) -> dict:
        return asdict(self)


class ReviewLayer:
    def review_strategy(self, strategy_id: str, pnl_values: list[float]) -> StrategyScore:
        trades = len(pnl_values)
        wins = len([x for x in pnl_values if x > 0])
        losses = len([x for x in pnl_values if x < 0])
        avg = mean(pnl_values) if pnl_values else 0.0
        if trades < 10:
            recommendation = 'collect_more_evidence'
            delta = 0.0
        elif avg > 0 and wins >= losses:
            recommendation = 'increase_weight_carefully'
            delta = 0.02
        elif avg < 0:
            recommendation = 'decrease_or_pause'
            delta = -0.05
        else:
            recommendation = 'no_change'
            delta = 0.0
        return StrategyScore(strategy_id, trades, wins, losses, avg, delta, recommendation)

    def daily_review(self, pnl_by_strategy: dict[str, list[float]]) -> dict:
        return {
            strategy_id: self.review_strategy(strategy_id, values).to_dict()
            for strategy_id, values in pnl_by_strategy.items()
        }
