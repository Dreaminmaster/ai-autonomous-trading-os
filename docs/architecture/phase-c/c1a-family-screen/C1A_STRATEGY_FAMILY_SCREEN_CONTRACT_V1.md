# C1A Strategy Family Screen Contract V1

Status: `PREREGISTERED PLAN`

This contract defines the next Phase C research stage after the valid rejection of `C0CCostAwareEMA`. C1A is a fixed-parameter, development-only family screen. It is not a request to tune C0C, and it cannot access the holdout.

## 1. Objective

Select at most one genuinely different long-only spot strategy family for a later confirmation stage while minimizing data-mining, transaction-cost blindness, and architecture churn.

The final product requires a strategy pool rather than one repeatedly retuned EMA candidate. C1A therefore compares distinct economic hypotheses under one common evidence and cost framework.

## 2. Frozen authority and starting point

- Base branch: `main`
- Required base commit: `ba9b02d63ae8fb67b99307191b9e58cd014d8dd6`
- Prior result: `docs/architecture/phase-c/c0c/C0C_COST_AWARE_EMA_RESULT_V1.md`
- Prior candidate: `c0c-cost-aware-ema-v1 = REJECTED`
- Exchange: OKX public market data only
- Mode: backtest only
- Market type: spot
- Direction: long-only or cash
- Leverage/derivatives: forbidden
- Private OKX endpoints: forbidden
- LIVE: forbidden
- Holdout: `2025-07-01` through `2026-07-01`, economically and statistically closed

## 3. Research rationale

The C0C evidence showed robust positive validation in two later folds but complete failure in the earlier adverse fold, with losses concentrated in ETH/SOL and no BTC participation. The next step is not to relax thresholds or retune the same four parameters. It is to test whether broad-market regime control and different entry mechanics can produce a low-turnover, cost-robust edge across regimes.

The hypotheses are intentionally simple:

1. channel breakout can capture persistent moves without requiring moving-average cross timing;
2. pullback entry can reduce paying for already-extended trends while remaining conditional on an uptrend;
3. dual momentum can remain in cash unless both absolute and relative momentum are positive.

External research is background only, not proof that any candidate will pass:

- Moskowitz, Ooi, and Pedersen, *Time Series Momentum*, Journal of Financial Economics (2012).
- Hurst, Ooi, and Pedersen, *A Century of Evidence on Trend-Following Investing*.
- Begušić and Kostanjčar, *Momentum and liquidity in cryptocurrencies*, arXiv:1904.00890.

## 4. Data boundary and windows

C1A may read only candles with timestamps strictly earlier than `2024-10-01T00:00:00Z` for economic screening.

Data may be downloaded through `2025-07-01` only when the shared sanitizer removes all rows at or after the relevant stage boundary before any strategy/economic read. The C1A economic runner itself must be physically isolated from all timestamps at or after `2024-10-01T00:00:00Z`.

Screen windows:

| Window | Start inclusive | End exclusive |
|---|---|---|
| S1 | 2024-01-01 | 2024-04-01 |
| S2 | 2024-04-01 | 2024-07-01 |
| S3 | 2024-07-01 | 2024-10-01 |

Reserved confirmation windows, not opened by C1A:

| Window | Start inclusive | End exclusive |
|---|---|---|
| C1 | 2024-10-01 | 2025-01-01 |
| C2 | 2025-01-01 | 2025-04-01 |
| C3 | 2025-04-01 | 2025-07-01 |

The confirmation period is not claimed to be globally pristine because earlier research described its market regimes. It remains economically unopened for the new C1A candidate families until a separate C1B contract is frozen.

## 5. Common market/configuration scope

- Pairs: `BTC/USDT`, `ETH/USDT`, `SOL/USDT`
- Base timeframe: `1h`
- Informative timeframe: `1d`
- Starting balance: `1000 USDT`
- Equal fixed stake policy across candidates
- Maximum simultaneous positions: `3`
- No pyramiding, DCA, leverage, shorting, futures, swaps, or options
- Expected fee: `0.0015` per side
- Cost multipliers: `1.0`, `1.5`, `2.0`
- Slippage assumptions must remain explicit and identical across candidates
- Candle processing and signals must be chronological and closed-candle only
- All rolling extrema must exclude the current candle to prevent self-referential breakout signals

## 6. Non-selectable comparators

The report must include, but may not select:

- HOLD/cash baseline;
- per-pair buy-and-hold;
- the frozen C0C result as historical context, without rerunning or using its rejected SHA as current evidence.

## 7. Fixed candidate families

No Hyperopt or parameter search is allowed in C1A. Values below are frozen before execution.

### 7.1 `C1ARegimeBreakout`

Economic hypothesis: participate only in broad-market and pair uptrends, entering on a long channel breakout and exiting on channel failure.

Indicators:

- BTC daily `EMA(90)`;
- BTC daily `EMA(20)` slope over 5 daily candles;
- pair daily `EMA(90)`;
- pair hourly `ATR(14)`;
- pair 20-day hourly Donchian high: previous `480` completed 1h candles;
- pair 10-day hourly Donchian low: previous `240` completed 1h candles.

Entry, all required:

- BTC daily close > BTC daily EMA90;
- BTC EMA20 five-day slope > 0;
- pair daily close > pair daily EMA90;
- pair hourly close crosses above the prior 480-hour Donchian high;
- volume > 0.

Exit on first condition:

- pair hourly close crosses below the prior 240-hour Donchian low;
- BTC broad-market regime fails;
- pair daily close <= pair daily EMA90;
- hard adverse move reaches `2.5 * ATR(14)` from entry, implemented without future information.

### 7.2 `C1ATrendPullback`

Economic hypothesis: buy temporary weakness only inside an established broad and pair uptrend.

Indicators:

- same BTC and pair daily regime indicators as `C1ARegimeBreakout`;
- pair hourly `EMA(20)`;
- pair hourly `RSI(14)`;
- pair hourly `ATR(14)`.

Entry, all required:

- BTC broad-market regime passes;
- pair daily close > pair daily EMA90;
- hourly close < hourly EMA20;
- RSI14 <= `35`;
- volume > 0.

Exit on first condition:

- hourly close >= hourly EMA20;
- RSI14 >= `55`;
- BTC or pair daily regime fails;
- hard adverse move reaches `2.5 * ATR(14)` from entry;
- position age reaches `168` completed hourly candles.

### 7.3 `C1ADualMomentum`

Economic hypothesis: own a pair only when it has positive medium-term absolute momentum and positive momentum relative to BTC, otherwise hold cash.

Indicators, calculated from completed daily candles:

- pair 20-day return;
- pair 60-day return;
- BTC 20-day return;
- pair daily EMA90;
- BTC daily EMA90 and EMA20 five-day slope.

Entry, all required:

- BTC broad-market regime passes;
- pair daily close > pair daily EMA90;
- pair 20-day return > 0;
- pair 60-day return > 0;
- pair 20-day return > BTC 20-day return;
- signal changes from false to true on a completed daily candle.

Exit on first condition:

- any entry momentum/regime condition becomes false on a completed daily candle;
- no intraday discretionary or AI exit.

## 8. Evidence requirements before economic classification

Every candidate must independently pass:

- exact source SHA binding;
- exact workflow/merge-ref binding when run from a PR;
- version capture for Python, Freqtrade, CCXT, and strategy code hashes;
- boundary sanitizer with report and hash binding;
- coverage checks for every pair/timeframe cell;
- zero duplicates and zero unexplained gaps;
- recursive-analysis proof for all required indicators;
- explicit no-lookahead analysis;
- deterministic command ledger;
- per-trade fee verification for every cost multiplier;
- secret leakage scan;
- artifact manifest with hashes for every command, log, config, strategy, export, and report;
- report regeneration from retained exports.

Queued or in-progress work is never PASS.

## 9. C1A eligibility gate

Metrics are computed from the combined S1-S3 exports at the expected cost unless a stress metric is explicitly named.

A family is eligible only if all conditions hold:

1. expected-cost net return is positive in at least `2 of 3` screen windows;
2. median expected-cost window net return is positive;
3. aggregate expected-cost net return is positive;
4. aggregate 1.5x-cost net return is nonnegative;
5. aggregate expected-cost profit factor is at least `1.10`;
6. maximum window drawdown is no more than `15%`;
7. at least `30` total trades across S1-S3;
8. every screen window contains at least `5` trades;
9. at least `2` pairs have positive expected-cost net profit;
10. no pair contributes more than `70%` of positive profit;
11. no screen window contributes more than `60%` of positive profit;
12. the largest positive trade contributes no more than `25%` of positive profit;
13. the top three positive trades contribute no more than `50%` of positive profit;
14. no result depends on missing candles, unverified fees, lookahead, recursive instability, or unbound exports.

A family with zero trades is a valid economic rejection, not an implementation error, provided the signal code and data evidence pass.

## 10. Deterministic selection

If no family is eligible:

```text
status = REJECTED
selected_family = null
confirmation_opened = false
```

If one or more families are eligible, select exactly one using this frozen order:

1. median window return/drawdown ratio, descending;
2. aggregate 1.5x-cost net return, descending;
3. aggregate expected-cost profit factor, descending;
4. maximum window drawdown, ascending;
5. turnover ratio, ascending;
6. total trades, descending;
7. family identifier, ascending.

Selection is a C1A screen result only. It does not authorize confirmation, holdout, paper, shadow, or live execution.

## 11. Required outputs

The authoritative artifact must include:

- `c1a_family_screen_manifest.json`;
- `c1a_family_screen_report.json`;
- `c1a_family_screen_report.md`;
- exact strategy source copies and hashes;
- data-boundary and coverage reports;
- recursive/no-lookahead reports;
- one command ledger per candidate/window/cost;
- retained Freqtrade exports and logs;
- per-window, per-pair, per-exit, turnover, concentration, and cost-attribution tables;
- deterministic eligibility and ranking decisions;
- explicit fields:
  - `status`;
  - `selected_family`;
  - `confirmation_opened=false`;
  - `holdout_state=HOLDOUT_CLOSED`;
  - `live=FORBIDDEN`.

## 12. Implementation scope

The C1A implementation PR may:

- add the three fixed strategy files;
- add a C1A-specific config and runner;
- reuse generic C0C evidence utilities only through explicit, tested interfaces;
- extract truly generic helpers when doing so reduces duplication without changing C0C evidence semantics;
- add focused tests and one authoritative C1A workflow triggered only after exact-SHA review.

It must not:

- modify C0C result files or reinterpret C0C as PASS;
- change existing economic thresholds;
- add Hyperopt, ML, LLM signals, orderbook, funding, on-chain data, or private account data;
- inspect C1/C2/C3 confirmation performance;
- access the holdout;
- create paper, shadow, or live execution paths;
- add leverage or derivatives;
- retry or mutate parameters after seeing C1A economic output.

## 13. Tests

At minimum:

- exact indicator/parameter contract tests for all three strategies;
- current-candle exclusion tests for Donchian extrema;
- closed-daily-candle informative-data tests;
- regime transition and signal-crossing tests;
- ATR stop/time-stop tests without future leakage;
- boundary and coverage tests for `1h` and `1d` cells;
- recursive/no-lookahead parser tests against current Freqtrade output;
- cost multiplier and per-trade fee-binding tests;
- aggregation, concentration, eligibility, tie-break, and fail-closed tests;
- exact-source manifest tests;
- secret scan and LIVE-forbidden assertions.

## 14. Failure handling

- Implementation/evidence failure: correct only the adapter or evidence defect, validate the new exact SHA, and never reuse old evidence.
- Valid economic rejection: freeze `REJECTED`; do not change constants or gates inside C1A.
- External data failure: retain diagnostics, keep the PR Draft, and do not classify economics.
- Any accidental read at or after the C1A boundary invalidates the run and requires a new exact SHA after correction.

## 15. Post-C1A path

Only an eligible selected family may receive a new C1B confirmation contract. C1B must use the frozen family code and parameters on C1-C3 without C1A retuning. Holdout remains closed until C1B passes and an independent exact-SHA review freezes a separate holdout protocol.

`HOLDOUT_CLOSED` / `LIVE FORBIDDEN`
