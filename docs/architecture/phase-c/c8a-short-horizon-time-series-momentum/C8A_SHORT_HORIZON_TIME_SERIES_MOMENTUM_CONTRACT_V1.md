# C8A Short-Horizon Time-Series Momentum — Contract V1

## 1. Status and authority

- Stage: `C8A`
- Change type: `DESIGN_ONLY`
- Selectable candidate count: `1`
- Historical economic result: `NOT_RUN`
- C7A: `CLOSED_ECONOMIC_FAIL`
- C8B prospective confirmation: `CLOSED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This document preregisters one historical research candidate. It authorizes no implementation, data download, economic run, authenticated API, account access, order placement, Paper execution, Shadow execution, derivatives execution, leverage, or Live execution.

## 2. Why C8A is structurally distinct

C0C through C5A tested long-only spot direction, allocation, mean reversion, cross-sectional momentum, and a derivatives-crowding filter. C6A tested same-asset spot/perpetual funding carry but closed before economics because historical contract metadata authority was unavailable. C7A tested cross-asset beta-neutral funding dispersion and failed economically after every frozen weekly signal remained in cash.

C8A does not relax or replace a C7A filter:

- its signal is the sign of each instrument's own trailing one-week mark-price return;
- funding is an accounted cash flow, not a rank, threshold, or predictor;
- BTC and ETH directions are decided independently;
- it can be long during positive trends and short during negative trends;
- it uses continuous USDT research notional and therefore does not project current contract metadata backward;
- it has no C7A beta regression, funding rank, projected-carry threshold, positive-funding-day threshold, or always-on funding orientation.

The new economic question is whether short-horizon price continuation on large OKX perpetuals survives conservative costs, exact funding cash flows, and five independent historical regimes. It is not an attempt to rescue C7A.

## 3. Research basis and claim boundary

Primary research reports positive own-return continuation in futures and in cryptocurrencies, including evidence that a cryptocurrency's current weekly return predicts returns one to four weeks ahead. Other peer-reviewed work questions whether time-series momentum is a distinct predictive effect, and recent crypto research emphasizes that costs, fat tails, and liquidation assumptions can erase apparent profits.

Those findings motivate a falsifiable test; they do not establish that C8A will pass.

References:

- Moskowitz, Ooi, and Pedersen, “Time Series Momentum,” *Journal of Financial Economics* 104(2), 2012: <https://doi.org/10.1016/j.jfineco.2011.11.003>
- Liu and Tsyvinski, “Risks and Returns of Cryptocurrency,” NBER Working Paper 24877; later published in *The Review of Financial Studies*: <https://www.nber.org/papers/w24877>
- Kim, Tse, and Wald, “Time Series Momentum: Is It There?”, *Journal of Financial Economics* 135(3), 2020: <https://doi.org/10.1016/j.jfineco.2019.08.004>
- Han, Kang, and Ryu, “Momentum in the Cryptocurrency Market: A Comprehensive Analysis under Realistic Assumptions”: <https://doi.org/10.2139/ssrn.4675565>
- OKX Historical Market Data: <https://www.okx.com/historical-data>
- OKX API Guide: <https://www.okx.com/docs-v5/en/>

## 4. Program-level anti-overfitting boundary

### 4.1 Historical status

All C8A H1–H5 data is `HISTORICAL_DEVELOPMENT_ONLY`. The intervals and broad market outcomes have been exposed elsewhere in the Phase C program. Therefore even a complete C8A pass is not described as a pristine holdout, prospective confirmation, Paper pass, or Shadow pass.

The five independent windows are fixed:

| Window | Start inclusive | End exclusive | Scored Mondays |
|---|---|---|---:|
| `H1` | `2024-01-01T00:00:00Z` | `2024-07-01T00:00:00Z` | `26` |
| `H2` | `2024-07-01T00:00:00Z` | `2024-12-30T00:00:00Z` | `26` |
| `H3` | `2024-12-30T00:00:00Z` | `2025-06-30T00:00:00Z` | `26` |
| `H4` | `2025-06-30T00:00:00Z` | `2025-12-29T00:00:00Z` | `26` |
| `H5` | `2025-12-29T00:00:00Z` | `2026-06-29T00:00:00Z` | `26` |

Required warm-up begins at `2023-12-25T00:00:00Z`. Every window starts from independent normalized equity `1.0`, cash collateral, and no position. No position, equity, signal, fee, funding cash flow, or risk state crosses between windows.

H1–H5 must be captured and evaluated together exactly once after implementation is frozen. Best-window selection, partial-window publication before the final classification, and rerunning after economic inspection are forbidden.

### 4.2 Prospective interval does not block C8A

A future C8B interval is reserved only to avoid pretending that historical program data is new:

- public-data custody start: `2026-08-03T00:00:00Z`;
- first possible scored decision: `2026-08-10T00:00:00Z`;
- scored end exclusive: `2027-02-08T00:00:00Z`;
- scored weeks: `26`.

C8B does not delay or block the C8A historical implementation and one-shot historical decision. C8B remains unreadable for C8A selection and may be opened only by a separate design after C8A passes every unchanged historical gate.

## 5. Fixed instruments and public inputs

Fixed instruments:

- `BTC-USDT-SWAP`
- `ETH-USDT-SWAP`

Required inputs:

- one-hour perpetual trade candles;
- one-hour perpetual mark-price candles;
- realized funding rates with exact settlement timestamps and realized rates.

Permitted official-public surfaces:

- OKX downloadable historical-data files;
- `GET /api/v5/market/history-candles`;
- `GET /api/v5/market/history-mark-price-candles`;
- `GET /api/v5/public/funding-rate-history`.

No current or historical contract value, lot size, minimum order size, account, balance, position, order, fill, fee tier, liquidation feed, private API, borrowing, lending, staking, external yield, order book, trade tape, open interest, sentiment, or non-OKX price may enter C8A selection.

Current public instrument metadata may be inspected only after an economic pass and only under a separate execution-readiness design. It may never be projected backward into C8A economics.

## 6. Data custody and integrity

The authoritative capture must persist raw response bytes before normalization and retain request URL, final URL, source timestamp, byte length, and SHA-256. Redirects may not change the official host, API path, or query semantics.

For every normalized series:

- timestamps are UTC, unique, and strictly increasing;
- required one-hour candles are gap-free;
- only confirmed and completed candles are retained;
- OHLC prices are finite and strictly positive;
- funding rates are finite and use exact official settlement timestamps;
- duplicate or contradictory settlements fail closed;
- funding interval frequency is never assumed;
- overshoot rows are removed before research read and recorded;
- missing, stale, unordered, malformed, or ambiguous data causes `EVIDENCE_FAILURE`, never interpolation or HOLD-based economic scoring;
- every retained raw and normalized file is bound into a recursive manifest.

No authenticated request may occur. The final package must state `authenticated=false`, `contains_account_data=false`, `contains_order_data=false`, `paper_side_effect=false`, and `shadow_side_effect=false`.

## 7. Decision clock and anti-lookahead rule

A decision occurs every Monday at `00:00:00Z`.

At decision time `t`, the latest permissible mark candle must have closed strictly before `t`. The candle whose close occurs exactly at `t` is not usable. The latest signal endpoint is therefore the close at `t - 1 hour`.

For instrument `i`, retain exactly the `169` consecutive hourly mark closes whose close times run from `t - 7 days - 1 hour` through `t - 1 hour`, inclusive. Define:

```text
momentum_7d_i(t)
  = latest_permitted_mark_close_i
    / mark_close_exactly_7_days_before_latest
    - 1
```

Direction is fixed:

```text
momentum_7d > 0  -> LONG
momentum_7d < 0  -> SHORT
momentum_7d = 0  -> FLAT
```

No return magnitude threshold, alternate lookback, moving average, volatility filter, funding filter, beta filter, regime filter, ensemble, optimizer, machine learning model, or LLM signal is allowed.

The modeled trade occurs at the trade-candle open stamped `t`. This leaves at least one full hour between the latest permissible mark close and the modeled execution price. No intrabar high, low, close, VWAP, or later timestamp may determine the trade.

## 8. Portfolio construction

Each instrument owns a dedicated sleeve initialized with `0.50` of current portfolio equity. At each Monday decision:

```text
target_signed_notional_i
  = direction_i * 0.25 * current_total_equity
```

Therefore:

- maximum absolute notional per instrument is `0.25` of equity;
- maximum portfolio gross notional is `0.50` of equity;
- at least `0.50` of equity remains uncredited cash collateral;
- there is no borrowed asset, external collateral, leverage increase, or cross-window state.

The portfolio rebalances exactly to both targets every Monday. A same-direction resize trades only the absolute target-minus-current notional. A reversal closes the old signed notional and opens the new signed notional, so one-way traded notional is the full absolute signed change. A flat signal closes that sleeve.

No no-trade band or discretionary skip is allowed.

## 9. Hourly accounting, funding, and risk exits

Position PnL is computed from the modeled trade price and subsequent completed mark prices using signed continuous USDT notional. No contract-count conversion or hidden rounding is used.

For a position held immediately before a funding settlement, `signed_mark_notional` is quantity times the last completed predecessor mark, positive for long and negative for short:

```text
funding_pnl = -signed_mark_notional * realized_funding_rate
```

Thus a positive rate is paid by a long and received by a short. Every realized rate is applied exactly once. At a timestamp shared by a settlement and modeled trade, funding applies first to the position carried into that timestamp; the trade occurs second. A delayed official funding timestamp uses the last completed predecessor mark and may not be reassigned to an idealized hour.

Each sleeve starts with collateral equity equal to `0.50` of total equity. After every completed hourly valuation and funding event, compute:

```text
sleeve_buffer = sleeve_collateral_equity / abs(current_mark_notional)
```

If a non-flat sleeve first has `sleeve_buffer < 1.25`, it is force-closed at the next available one-hour trade-candle open and remains flat until the next scheduled Monday. The breach and close stay in evidence. Eligibility requires zero such breaches.

Non-positive total equity, non-finite state, missing next open, or an unreconciled event is `EVIDENCE_FAILURE`.

All remaining positions are closed at each window's exclusive-end trade open under identical costs. The terminal close is part of that window's PnL, turnover, drawdown, and concentration.

## 10. Frozen costs

One-side modeled execution cost per traded perpetual notional:

- expected `1.0x`: `0.0015`;
- stress `1.5x`: `0.00225`;
- stress `2.0x`: `0.0030`.

Every open, close, reversal, resize, risk exit, and terminal liquidation pays the applicable cost. No maker rebate, VIP tier, referral rebate, spread capture, cash yield, or unmodeled credit is allowed.

The same frozen directions and scheduled targets are replayed at all three cost levels. Costs may not change a historical signal or suppress a scheduled trade. Equity, target notional, fees, collateral state, and a resulting risk-exit timestamp are recomputed separately at each cost level rather than copied from the expected-cost replay.

## 11. Non-selectable comparators

The evidence must compute but may never select:

1. `CashComparator`: normalized equity remains `1.0`;
2. `AlwaysLongPerpetualComparator`: both instruments target `+0.25` of equity every Monday with identical price, funding, collateral, risk-exit, cost, and terminal rules, but no momentum direction.

The comparator starts independently in every window. It is not permitted as a fallback candidate even if it outperforms C8A.

## 12. Metrics

For every window and cost level, retain:

- all `26` decisions and `26` complete weekly returns;
- net return, gross price PnL, funding PnL, costs, and turnover;
- maximum drawdown from the complete hourly equity path;
- per-instrument and per-week contribution;
- margin-buffer minimum and breach count;
- long, short, flat, and reversal counts;
- missing-decision and unaccounted-settlement counts.

The five normalized window returns are compounded chronologically:

```text
pooled_net_return = product(1 + window_net_return) - 1
```

The `130` independent-window weekly returns are concatenated in H1–H5 order for statistics. Weekly Sharpe uses the sample standard deviation with `ddof=1` and annualizes only for reporting and the annualized-Sharpe gate:

```text
weekly_sharpe_raw = mean(weekly_returns) / sample_std(weekly_returns)
weekly_sharpe_annualized = weekly_sharpe_raw * sqrt(52)
```

PSR versus zero uses raw weekly Sharpe, sample skewness, ordinary kurtosis, and the standard non-normality correction. Fewer than two returns, zero/non-finite variance, or a non-positive/non-finite radicand yields PSR `0`, not a pass.

Strategy beta is the OLS slope of the candidate's `130` weekly returns on contemporaneous BTC weekly mark returns. Zero/non-finite BTC variance fails the beta gate.

One-way turnover for an event is absolute traded notional divided by total portfolio equity immediately before that event. Pooled annualized one-way turnover is the sum of those event ratios across all five independent 26-week windows divided by `2.5` years. Reversals use the full absolute signed-notional change.

## 13. Frozen eligibility gates

C8A is `SELECTED` only if every gate passes at expected cost unless another cost is named.

### 13.1 Economics and stability

- at least `4` of `5` windows have net return `> 0`;
- median window net return `> 0`;
- worst window net return `> -0.05`;
- pooled net return `> 0`;
- pooled net return at `1.5x` cost `> 0`;
- pooled net return at `2.0x` cost `>= 0`.

### 13.2 Risk and statistical evidence

- annualized weekly Sharpe `>= 1.00`;
- weekly PSR versus zero `>= 0.95`;
- maximum drawdown in every window `<= 0.15`;
- absolute weekly strategy beta to BTC `<= 0.65`;
- margin-buffer breach count `= 0`;
- missing decisions, non-finite equity states, non-positive equity states, and unaccounted funding settlements all equal `0`.

### 13.3 Activity, turnover, and concentration

- exactly `130` weekly decisions exist;
- at least `250` of `260` instrument-week directions are non-flat;
- annualized one-way notional turnover `<= 26.0x`;
- BTC and ETH each have positive net contribution;
- maximum positive-instrument PnL share `<= 0.75`;
- maximum positive-window PnL share `<= 0.45`;
- maximum positive-week PnL share `<= 0.20`;
- top-three positive-week PnL share `<= 0.45`.

### 13.4 Incremental value over the simple comparator

At expected cost:

- candidate pooled net return exceeds `AlwaysLongPerpetualComparator` pooled net return;
- candidate annualized weekly Sharpe exceeds the comparator by at least `0.10`;
- candidate maximum window drawdown is no greater than the comparator maximum window drawdown.

No relatively best but ineligible result may be promoted.

## 14. Multiple testing and allowed claim

C8A contains exactly one selectable candidate, one signal horizon, one rebalance clock, one sizing rule, and no variants. Within-stage DSR is not used.

The evidence must state:

```text
within_stage_candidate_count = 1
weekly_statistic = PSR_NOT_DSR
program_level_sequential_history_corrected = false
historical_data_status = HISTORICAL_DEVELOPMENT_ONLY
```

PSR does not erase the sequential C0C–C8A research history. A C8A `SELECTED` result means only `HISTORICAL_ECONOMIC_PASS`; it is not a global false-discovery correction and cannot itself authorize Paper, Shadow, derivatives execution, or Live.

## 15. Independent recomputation and evidence

The authoritative package must retain at minimum:

- exact source, design, implementation, workflow, run, and checkout hashes;
- request/final URLs, raw response bytes, normalized rows, and recursive manifests;
- boundary, coverage, confirmed-candle, funding-uniqueness, and checkout-cleanliness reports;
- every signal endpoint, source row identity, direction, target, trade, fee, mark PnL, funding event, collateral state, and risk decision;
- candidate and comparator replays at all three costs;
- weekly, window, pooled, attribution, concentration, PSR, beta, comparator, and final gate evidence;
- explicit data/program/economic failure classification.

A physically separate reference implementation must recompute source-derived signals, event accounting, costs, funding, metrics, comparators, and the final decision without importing the production candidate/replay engine. Any mismatch is `EVIDENCE_FAILURE`.

## 16. Implementation and authoritative-run boundary

After this design is reviewed and merged, a separate implementation PR may add:

- pure contract constants and types;
- source guards and normalization adapters;
- deterministic signal and replay engines;
- a physically separate reference recomputation;
- synthetic and adversarial tests;
- evidence packaging;
- one final manual-dispatch job in the existing Freqtrade Validation workflow.

The implementation stage may use synthetic fixtures only until its exact SHA passes static review and all applicable tests. One official-public H1–H5 capture/evaluation is then permitted. The manual-dispatch input and job must be removed immediately after the completed classification, regardless of economic result.

The following remain forbidden:

- changing any signal, window, cost, sizing, comparator, metric, or gate after seeing C8A economics;
- alternate lookbacks, thresholds, filters, no-trade bands, asset additions, exclusions, Hyperopt, grid search, ML, or LLM decisions;
- partial-result inspection followed by rerun;
- best-window selection or post-hoc comparator promotion;
- authenticated OKX access, accounts, orders, Paper side effects, Shadow side effects, derivatives execution, leverage, or Live.

## 17. Final design state

`C8A_DESIGN_ONLY`

`H1_H5_HISTORICAL_DEVELOPMENT_ONLY`

`C8A_ECONOMIC_RESULT_NOT_RUN`

`C8B_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
