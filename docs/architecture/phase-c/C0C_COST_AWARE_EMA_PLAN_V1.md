# C0C Cost-Aware EMA Walk-Forward Plan V1

Status: **DESIGN CANDIDATE**  
Mode: **BACKTEST ONLY**  
Live: **FORBIDDEN**

## 1. Decision after C0B

C0B Matrix #2 (`29352209123`) produced a valid `NO SURVIVOR` result. None of the nine deterministic strategy/timeframe candidates may proceed directly to Paper, Shadow, C0D, or Live.

The only research lead worth preserving is `C0BEMATrend@5m`:

- expected-cost return: approximately `-15.63%`;
- profit factor: approximately `0.885`;
- maximum drawdown: approximately `18.01%`;
- trades: `538`;
- estimated zero-cost return: approximately `+19.8%`;
- gross contribution was positive for BTC, ETH, and SOL and for every scored quarter;
- realistic round-trip cost of approximately `0.30%` reversed the weak gross edge into a loss.

This is evidence for one narrow hypothesis, not evidence that the existing EMA candidate is viable.

## 2. Falsifiable hypothesis

A five-minute EMA trend candidate may retain the broad gross directional edge observed in C0B while becoming net profitable only if entries require enough trend separation, volatility, and higher-timeframe strength to cover trading costs and materially reduce low-quality turnover.

The hypothesis is rejected if the preregistered candidate cannot pass the unchanged C0 paper-eligibility thresholds on development walk-forward tests before the fresh holdout is opened.

## 3. Explicit non-goals

C0C V1 does not:

- add AI, an LLM, FreqAI, or a learned router;
- add another strategy family;
- optimize Donchian or mean-reversion candidates;
- optimize leverage, shorting, derivatives, position stacking, or pair selection;
- optimize ROI, stoploss, trailing stop, stake size, or risk limits;
- modify B4/B5 execution, persistence, recovery, or Paper contracts;
- authorize Paper, Shadow, or Live;
- reuse the fresh holdout after a failed evaluation.

## 4. Fixed trading scope

- exchange data: OKX public historical data;
- market: spot;
- direction: long-only;
- leverage: none;
- base timeframe: `5m`;
- informative timeframe: `1h`;
- pairs: `BTC/USDT`, `ETH/USDT`, `SOL/USDT`;
- maximum simultaneous positions: one per pair;
- expected fee: `0.15%` per side;
- optimization fee: `0.225%` per side (`1.5x` expected cost);
- stress validation: `0.30%` per side (`2x` expected cost);
- result cache: disabled for authoritative runs;
- LIVE: `FORBIDDEN`.

## 5. Data boundaries and anti-leakage rule

### 5.1 Development period

`2024-01-01` through `2025-07-01` is a **seen development period** because C0B already evaluated it. It may be used for train/validation/development-test work, but it must never be described as untouched final evidence.

Warm-up data begins no later than `2023-11-01`.

### 5.2 Fresh final holdout

`2025-07-01` through `2026-07-01` is reserved as the fresh final holdout.

Rules:

1. Holdout candles may be downloaded and hashed, but no strategy result, metric, chart, trade list, or aggregate may be inspected before a development candidate is frozen.
2. The holdout is evaluated once for the exact frozen source SHA, parameters, configuration, pair universe, cost assumptions, and code path.
3. A failed holdout result is preserved and may not be used to retune the same candidate and then be relabeled untouched.
4. Any redesign after holdout failure receives a new candidate version and requires a future, genuinely unseen holdout period.

## 6. Candidate identity

Candidate ID:

```text
c0c-cost-aware-ema-v1
```

The candidate retains fixed EMA periods from the C0B lead:

```text
fast EMA = 20
slow EMA = 50
higher-timeframe EMA = 100 on 1h
```

The entry trigger must remain event-based, not sticky. It fires only when the normalized EMA spread crosses above a selected threshold.

Fixed exit and risk semantics:

- exit when fast EMA crosses below slow EMA;
- stoploss: `-5%`;
- ROI table: `0m -> 4%`, `720m -> 2%`, `1440m -> 0%`;
- no trailing stop;
- no custom stoploss;
- no exit-space, ROI-space, stoploss-space, trailing-space, protection-space, or trade-space optimization in V1.

## 7. Preregistered Hyperopt space

Only the `enter` space is optimized.

| Parameter | Type | Frozen range | Purpose |
|---|---|---:|---|
| `enter_spread_threshold` | Decimal, 3 decimals | `0.001`–`0.008` | minimum EMA separation event |
| `enter_slow_slope_min` | Decimal, 3 decimals | `0.001`–`0.010` | reject flat slow trends |
| `enter_atr_ratio_min` | Decimal, 3 decimals | `0.002`–`0.012` | require enough movement to cover cost |
| `enter_htf_slope_min` | Decimal, 3 decimals | `0.000`–`0.010` | require non-weak 1h regime |

All required indicator columns are precomputed without reading future candles. Hyperopt parameters are consumed only in entry-signal construction; they do not alter indicator calculation per epoch.

No parameter, range, precision, trigger family, cost assumption, loss function, epoch count, or data boundary may be changed after observing an authoritative C0C result without a prospective plan version increment.

## 8. Official optimization engine

Use Freqtrade Hyperopt and its official optional dependencies. Do not create a custom optimizer.

Frozen command properties:

- loss: `MultiMetricHyperOptLoss`;
- space: `enter` only;
- epochs: `200` per training run;
- random state: `20260715`;
- minimum trades: `30`;
- fee: `0.00225` per side;
- workers: bounded by the workflow, not unlimited by default;
- automatic parameter export must be captured and hashed;
- complete command, Freqtrade version, data hashes, strategy hash, config hash, seed, search space, and result artifacts must be retained.

The heavy Hyperopt dependency is installed only in a dedicated research extra/workflow. Ordinary CI and unrelated code paths must not acquire the Hyperopt dependency or launch C0C.

## 9. Development walk-forward protocol

Use three anchored folds on the seen development period:

| Fold | Train | Validation | Development test |
|---|---|---|---|
| 1 | 2024-01-01–2024-07-01 | 2024-07-01–2024-10-01 | 2024-10-01–2025-01-01 |
| 2 | 2024-01-01–2024-10-01 | 2024-10-01–2025-01-01 | 2025-01-01–2025-04-01 |
| 3 | 2024-01-01–2025-01-01 | 2025-01-01–2025-04-01 | 2025-04-01–2025-07-01 |

For every fold:

1. Hyperopt sees only the training interval.
2. The selected training candidates are evaluated on validation at expected, `1.5x`, and `2x` costs.
3. Selection is based on the preregistered risk-aware objective and validation evidence, not the development-test interval.
4. The selected fold candidate is evaluated once on that fold's development-test interval.
5. All attempted candidates and failed results remain in the artifact ledger.

The implementation must define a deterministic shortlist and tie-break procedure before authoritative execution. It may not manually pick a visually attractive epoch after seeing development-test results.

## 10. Gate before opening the holdout

The fresh holdout remains closed unless aggregate development-test evidence satisfies all original C0 thresholds:

1. net return after expected costs is positive;
2. median fold net return is positive;
3. profit factor is at least `1.10`;
4. maximum drawdown is no greater than `15%`;
5. return/drawdown exceeds the relevant buy-and-hold control;
6. aggregate result remains non-negative at `1.5x` costs;
7. no pair contributes more than `70%` of total positive profit;
8. no fold contributes more than `60%` of total positive profit;
9. at least two pairs and at least two development-test folds contribute positively;
10. at least `30` aggregate development-test trades exist;
11. lookahead and recursive analyses pass;
12. no single trade or small cluster explains the result.

Failure means `REJECTED` or `RESEARCH_ONLY`; it does not justify opening the holdout.

## 11. Final refit and holdout procedure

Only after the development gate passes:

1. rerun the same frozen Hyperopt procedure on `2024-01-01` through `2025-04-01`;
2. select parameters using only `2025-04-01` through `2025-07-01` validation evidence;
3. freeze exact parameters and all hashes;
4. run expected, `1.5x`, and `2x` cost cases on `2025-07-01` through `2026-07-01` once;
5. run lookahead and recursive analyses;
6. apply the original C0 paper-eligibility thresholds without modification.

A holdout pass may make the deterministic candidate `PAPER_ELIGIBLE`; it does not authorize Paper deployment automatically and cannot authorize Live.

## 12. Required implementation evidence

C0C implementation must produce:

- strategy and parameter-space contract tests;
- split and boundary tests proving no fold leakage;
- deterministic seed and command tests;
- manifest hashes for source, strategy, configs, data, parameters, logs, and reports;
- all Hyperopt trial/epoch results or the complete official result artifact;
- per-fold train, validation, and development-test reports;
- expected, `1.5x`, and `2x` cost results;
- pair, fold, exit-reason, turnover, and concentration attribution;
- explicit `HOLDOUT_CLOSED`, `HOLDOUT_OPENED`, or `HOLDOUT_EVALUATED` state;
- failure artifacts even when no candidate survives;
- secret scan;
- LIVE `FORBIDDEN` marker.

## 13. Efficiency policy

- Fast PR checks use synthetic fixtures, contract tests, ordinary full pytest, and secret scan.
- Hyperopt does not run on every commit.
- One authoritative development walk-forward run is triggered only for a clean exact-SHA candidate.
- The holdout is a separate explicit run and is impossible to trigger until the development gate artifact says PASS.
- A code-only fix reruns only affected fast checks until the clean candidate is frozen.
- Negative economic results are valid and must not be converted into workflow failures unless evidence integrity is broken.

## 14. Promotion decisions

Valid C0C V1 outcomes:

- `REJECTED` — no cost-surviving development edge;
- `RESEARCH_ONLY` — some evidence exists but one or more thresholds fail;
- `HOLDOUT_ELIGIBLE` — development gate passes and the exact candidate may open the fresh holdout;
- `PAPER_ELIGIBLE` — the single fresh holdout evaluation passes every unchanged C0 threshold.

No C0C status authorizes Shadow or Live. AI evaluation remains prohibited until a deterministic candidate becomes `PAPER_ELIGIBLE`.
