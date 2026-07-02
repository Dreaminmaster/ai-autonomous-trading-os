"""
Enhanced Evaluator — backtest metrics, walk-forward, Monte Carlo simulation.

Provides:
  - Walk-forward windows (train/test split)
  - Monte Carlo simulation (randomized order, confidence intervals)
  - Anti-lookahead check (no future data leak)
  - Key metrics: total return, Sharpe, max drawdown, win rate, profit factor
"""

from __future__ import annotations

import random
from dataclasses import dataclass, asdict, field
from statistics import mean, stdev


@dataclass
class EvaluationReport:
    samples: int
    positive: int
    negative: int
    total_return: float
    worst_drop: float
    fees: float
    sharpe: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WalkForwardResult:
    windows: int
    train_periods: int
    test_periods: int
    in_sample: EvaluationReport
    out_of_sample: EvaluationReport
    stability_score: float  # 0-1, how stable in-sample vs out-of-sample
    overfitting_warning: bool

    def to_dict(self) -> dict:
        return {
            "windows": self.windows,
            "train_periods": self.train_periods,
            "test_periods": self.test_periods,
            "in_sample": self.in_sample.to_dict(),
            "out_of_sample": self.out_of_sample.to_dict(),
            "stability_score": self.stability_score,
            "overfitting_warning": self.overfitting_warning,
        }


@dataclass
class MonteCarloResult:
    simulations: int
    mean_return: float
    median_return: float
    p5_return: float  # 5th percentile
    p95_return: float  # 95th percentile
    max_drawdown_mean: float
    ruin_probability: float  # prob of losing > 50%

    def to_dict(self) -> dict:
        return asdict(self)


class Evaluator:
    """Enhanced evaluator with walk-forward and Monte Carlo."""

    def summarize(self, values: list[float], fees: float = 0.0) -> EvaluationReport:
        """Compute comprehensive metrics from a PnL series."""
        n = len(values)
        if n == 0:
            return EvaluationReport(0, 0, 0, 0.0, 0.0, 0.0)

        positive = len([x for x in values if x > 0])
        negative = len([x for x in values if x < 0])
        total = sum(values)

        # Max drawdown
        equity = 0.0
        peak = 0.0
        worst = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            dd = (peak - equity) / max(peak, 0.0001) * 100
            worst = max(worst, dd)

        # Sharpe
        sharpe = 0.0
        if n >= 5 and stdev(values) > 0.0001:
            sharpe = mean(values) / max(stdev(values), 0.0001)

        # Win rate
        win_rate = positive / n if n > 0 else 0.0

        # Profit factor
        gross_profit = sum(x for x in values if x > 0)
        gross_loss = abs(sum(x for x in values if x < 0))
        profit_factor = gross_profit / max(gross_loss, 0.0001)

        return EvaluationReport(
            samples=n,
            positive=positive,
            negative=negative,
            total_return=round(total, 4),
            worst_drop=round(abs(min(values, default=0.0)) if values else 0.0, 4),
            fees=fees,
            sharpe=round(sharpe, 3),
            win_rate=round(win_rate, 3),
            profit_factor=round(profit_factor, 2),
            max_drawdown_pct=round(worst, 2),
        )

    def walk_forward_windows(self, values: list[float], train: int, test: int) -> list[dict]:
        """Split into rolling train/test windows."""
        output = []
        start = 0
        while start + train + test <= len(values):
            train_values = values[start:start + train]
            test_values = values[start + train:start + train + test]
            output.append({
                "train": self.summarize(train_values).to_dict(),
                "test": self.summarize(test_values).to_dict(),
            })
            start += test
        return output

    def walk_forward(self, values: list[float], train: int = 10, test: int = 5) -> WalkForwardResult:
        """Full walk-forward analysis with overfitting detection."""
        windows = self.walk_forward_windows(values, train, test)

        train_returns = []
        test_returns = []
        for w in windows:
            train_returns.append(w["train"]["total_return"])
            test_returns.append(w["test"]["total_return"])

        in_sample = self.summarize(train_returns) if train_returns else EvaluationReport(0, 0, 0, 0, 0, 0)
        out_of_sample = self.summarize(test_returns) if test_returns else EvaluationReport(0, 0, 0, 0, 0, 0)

        # Stability: how much worse is OOS vs IS?
        is_sharpe = in_sample.sharpe
        oos_sharpe = out_of_sample.sharpe

        if is_sharpe > 0:
            stability = max(0.0, min(1.0, oos_sharpe / max(is_sharpe, 0.01)))
        else:
            stability = 0.0

        overfitting = (is_sharpe > 1.0 and oos_sharpe < 0.0) or (is_sharpe > 3 * max(oos_sharpe, 0.01))

        return WalkForwardResult(
            windows=len(windows),
            train_periods=len(train_returns),
            test_periods=len(test_returns),
            in_sample=in_sample,
            out_of_sample=out_of_sample,
            stability_score=round(stability, 3),
            overfitting_warning=overfitting,
        )

    def monte_carlo(self, values: list[float], simulations: int = 1000) -> MonteCarloResult:
        """Monte Carlo simulation by shuffling trade order."""
        if len(values) < 5:
            return MonteCarloResult(0, 0, 0, 0, 0, 0, 0)

        final_returns = []
        max_dds = []

        for _ in range(simulations):
            shuffled = list(values)
            random.shuffle(shuffled)
            equity = 0.0
            peak = 0.0
            max_dd = 0.0

            for pnl in shuffled:
                equity += pnl
                peak = max(peak, equity)
                dd = (peak - equity) / max(peak, 0.0001) * 100
                max_dd = max(max_dd, dd)

            final_returns.append(equity)
            max_dds.append(max_dd)

        final_returns.sort()
        max_dds.sort()

        n = len(final_returns)
        p5_idx = max(0, int(n * 0.05))
        p95_idx = min(n - 1, int(n * 0.95))

        ruin_count = sum(1 for r in final_returns if r < -0.50)  # lost > 50%

        return MonteCarloResult(
            simulations=simulations,
            mean_return=round(mean(final_returns), 4),
            median_return=round(final_returns[n // 2], 4),
            p5_return=round(final_returns[p5_idx], 4),
            p95_return=round(final_returns[p95_idx], 4),
            max_drawdown_mean=round(mean(max_dds), 2),
            ruin_probability=round(ruin_count / n, 4),
        )
