# 06 Evaluation Layer

## Purpose

The Evaluation Layer determines whether strategies, AI decisions, and strategy-weight updates are robust enough to be trusted.

Profit in one historical window is not enough.

## Required evaluation modes

### Historical replay

Replay market data in chronological order. At simulated time T, the system can only use data available at or before T.

### Backtest

Run strategies and AI decision policies on historical data with realistic execution assumptions.

Must include:

- fees,
- slippage,
- latency assumptions,
- orderbook depth assumptions,
- funding costs if applicable,
- unavailable-data handling.

### Walk-forward validation

Split history into rolling train/test windows.

Example:

```text
train window 1 -> test window 1
train window 2 -> test window 2
train window 3 -> test window 3
```

Strategy parameters and AI memory available in each window must be point-in-time.

### Out-of-sample testing

Hold back data that was not used for strategy design or parameter tuning.

### Parameter perturbation

Test nearby parameters.

A robust strategy should not collapse when parameters move slightly.

### Monte Carlo

Shuffle or resample trade outcomes to estimate:

- drawdown distribution,
- ruin probability,
- worst-case streaks,
- capital requirements.

### Fee/slippage stress test

Test higher-than-expected costs.

A strategy that only works with zero fees or perfect fills is not robust.

## Metrics

Required metrics:

- total return,
- annualized/period return,
- max drawdown,
- Sharpe-like ratio,
- Sortino-like ratio,
- Calmar-like ratio,
- win rate,
- profit factor,
- average win/loss,
- max consecutive losses,
- turnover,
- fees as percentage of PnL,
- slippage impact,
- exposure time,
- regime-specific performance.

## Anti-overfitting rules

A strategy should be demoted if:

- performance depends on one narrow window,
- performance disappears under fee/slippage stress,
- performance collapses under small parameter changes,
- most profit comes from one or two trades,
- strategy only works on one market regime,
- trade count is too low to infer anything,
- AI explanations are not supported by data.

## Anti-look-ahead rules

Backtests must prevent:

- future candle leakage,
- future news leakage,
- future funding leakage,
- hindsight regime labels,
- full-period normalization leakage,
- model memory of known historical events.

## LLM historical memory risk

When replaying historical events, a general LLM may know what happened later. Therefore:

- avoid asking the model about named future-sensitive events,
- provide only point-in-time data packets,
- prefer structured features over broad historical narratives,
- log every input packet,
- use mock/frozen decision policies for reproducibility tests,
- compare AI decisions against non-LLM baselines.

## Strategy promotion gate

A strategy may move from candidate to active only after:

1. backtest pass,
2. walk-forward pass,
3. out-of-sample pass,
4. fee/slippage stress pass,
5. paper trading pass,
6. review approval.

## Strategy demotion gate

A strategy is demoted or paused if:

- live/shadow performance deviates from expected distribution,
- drawdown exceeds policy,
- risk-adjusted return deteriorates,
- regime has changed,
- review finds repeated invalid theses.
