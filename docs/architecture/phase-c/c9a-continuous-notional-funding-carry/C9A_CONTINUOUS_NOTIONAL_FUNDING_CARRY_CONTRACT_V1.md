# C9A Continuous-Notional Funding Carry — Contract V1

## 1. Status and authority

- Stage: `C9A`
- Change type: `DESIGN_ONLY`
- Selectable candidate count: `1`
- Historical economic result: `NOT_RUN`
- C6A: `CLOSED_DATA_AUTHORITY_FAILURE_ECONOMICS_NOT_RUN`
- C8A: `CLOSED_ECONOMIC_FAIL`
- C9B prospective confirmation: `CLOSED`
- Execution-feasibility review: `CLOSED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This document preregisters one historical research candidate. It authorizes no implementation, market-data download, economic run, authenticated API, account access, order placement, Paper execution, Shadow execution, derivatives execution, leverage, or Live execution.

## 2. Hypothesis and separation from prior stages

C9A tests this falsifiable proposition:

> When realized perpetual funding has been persistently positive and sufficiently exceeds a conservative complete two-leg cost estimate, an exactly base-unit-neutral long-spot/short-perpetual research portfolio may retain positive net carry across independent regimes without relying on historical exchange contract specifications.

C9A is not a rerun or retuning of a completed economic result:

- C6A preregistered this economic mechanism but never accessed economic data and never produced an economic result. It closed because complete timestamp-effective `ctVal`, `lotSz`, `minSz`, tick-size, and listing-state authority could not be established.
- The C6A closeout explicitly permits a separately preregistered design whose economics do not require those unavailable historical conversion states.
- C7A tested cross-asset funding dispersion and beta fitting. C9A has neither cross-asset rank nor beta regression.
- C8A tested directional one-week price momentum and failed economically. C9A has no directional forecast; spot and perpetual base quantities are equal and opposite.

C9A retains the C6A hypothesis, assets, signal, costs, allocation, risk limits, comparators, windows, and economic gates. Its sole material model change is declared before data access: research positions use continuous base-currency quantities and never claim historical order feasibility. No C6A economic result exists from which this change could have been tuned.

## 3. Research basis and claim boundary

Official OKX public material documents historical candles, historical realized funding rates, and the rule that positive funding is paid by perpetual longs to shorts. Primary research documents that crypto carry can be large and time-varying because leveraged demand meets limits to arbitrage. Carry is not risk-free: basis changes, negative funding, execution costs, and margin stress can eliminate it.

References:

- OKX Historical Market Data: <https://www.okx.com/historical-data>
- OKX API Guide: <https://www.okx.com/docs-v5/en/>
- OKX Perpetual Funding Fee Mechanism: <https://www.okx.com/help/perpetual-futures-funding-fee-mechanism>
- Schmeling, Schrimpf, and Todorov, “Crypto Carry,” *Management Science* (2026): <https://doi.org/10.1287/mnsc.2024.05069>

These sources motivate the test; they do not establish that C9A will pass or that the continuous research portfolio can be executed.

## 4. Program-level anti-overfitting boundary

All C9A data is `HISTORICAL_DEVELOPMENT_ONLY`. The interval has been exposed by earlier Phase C work and is not a pristine holdout.

- Funding warm-up start: `2023-06-05T00:00:00Z`
- Price custody start: `2023-07-02T22:00:00Z`
- First scored decision: `2023-07-03T00:00:00Z`
- Scored end exclusive: `2025-12-29T00:00:00Z`
- Scored weeks: `130`
- Independent windows:
  - W1: `2023-07-03T00:00:00Z` to `2024-01-01T00:00:00Z`;
  - W2: `2024-01-01T00:00:00Z` to `2024-07-01T00:00:00Z`;
  - W3: `2024-07-01T00:00:00Z` to `2024-12-30T00:00:00Z`;
  - W4: `2024-12-30T00:00:00Z` to `2025-06-30T00:00:00Z`;
  - W5: `2025-06-30T00:00:00Z` to `2025-12-29T00:00:00Z`.

Each window begins independently with `1000 USDT`, no position, and no carried PnL or risk state. W1–W5 must be captured and evaluated together once after implementation is frozen. Partial-result inspection, best-window selection, and rerunning after economic inspection are forbidden.

A future C9B confirmation period may be opened only by a separate design after every unchanged C9A gate passes. C9A does not authorize or delay on C9B.

## 5. Fixed instruments and permitted public inputs

Spot legs:

- `BTC-USDT`
- `ETH-USDT`

USDT-margined perpetual reference legs:

- `BTC-USDT-SWAP`
- `ETH-USDT-SWAP`

Required public inputs:

- one-hour spot trade candles;
- one-hour perpetual trade candles;
- one-hour perpetual mark-price candles;
- realized funding rates with exact `fundingTime` and `realizedRate`.

Permitted official-public surfaces:

- OKX downloadable historical-data files;
- `GET /api/v5/market/history-candles`;
- `GET /api/v5/market/history-mark-price-candles`;
- `GET /api/v5/public/funding-rate-history` only for documented recent overlap checks.

Forbidden inputs include current or historical contract value, contract count, lot size, minimum order size, tick size, account, balance, position, order, fill, private fee tier, liquidation tier, borrowing, lending, staking, external yield, order book, trade tape, open interest, sentiment, and non-OKX prices.

## 6. Continuous-notional research boundary

C9A uses exact decimal base-currency quantities. For an active asset sleeve at a rebalance:

```text
spot_base_quantity = scaled_spot_target_notional / spot_trade_open
perpetual_short_base_quantity = spot_base_quantity
net_base_quantity = 0
```

There is no contract count, lot/minimum rounding, tick rounding, hidden quantity quantum, or projected historical instrument metadata. The perpetual trade and funding notionals use this continuous short base quantity multiplied by the applicable perpetual trade or mark price.

This is an economic-mechanism screen, not an execution backtest. A historical economic pass would establish only idealized continuous-notional evidence. It would not establish that orders of those quantities were admissible on OKX at any historical timestamp. Execution feasibility, current instrument metadata, order sizing, liquidity, and forward slippage require a separate post-pass design.

## 7. Data custody and fail-closed integrity

The authority run must persist raw bytes before normalization and retain request URL, final URL, collection timestamp, byte length, media type, retry record, and SHA-256. Redirects may not change the official host, API path, or query semantics.

For every normalized series:

- timestamps are UTC, unique, and strictly increasing;
- all required one-hour candles are present without gaps;
- candles are confirmed and completed before use;
- OHLC prices are finite and strictly positive;
- volumes and funding rates are finite;
- duplicate or contradictory funding settlements fail closed;
- actual settlement timestamps are authoritative and no fixed interval is assumed;
- a funding gap greater than eight hours plus one minute fails closed;
- overshoot rows are removed before research read and recorded;
- missing, stale, unordered, malformed, ambiguous, or non-reconciling input produces `DATA_FAILURE` or `PROGRAM_FAILURE`, never a synthetic HOLD and never an economic result;
- all raw, normalized, replay, review, and final evidence is bound by recursive SHA-256 manifests.

The terminal execution row stamped at a window's exclusive boundary may be retained only to supply that boundary open. It may not enter a signal, funding lookback, in-window valuation, or parameter choice.

No authenticated request may occur. Evidence must state `authenticated=false`, `contains_account_data=false`, `contains_order_data=false`, `paper_side_effect=false`, and `shadow_side_effect=false`.

## 8. Decision clock and anti-lookahead rule

A decision occurs every Monday at `00:00:00Z`. At decision time `t`:

- funding signal records satisfy `fundingTime < t`;
- the latest basis inputs are the spot and perpetual-mark candles stamped `t - 2 hours`, which close at `t - 1 hour`;
- the candles stamped `t - 1 hour`, which close at `t`, are forbidden to the decision;
- modeled transactions use the separate spot and perpetual trade-candle opens stamped `t`.

At a timestamp shared by funding and a trade, funding applies first to the carried position and the transaction occurs second. A newly opened position cannot collect same-time funding. A closing position receives or pays same-time funding except at an exclusive window boundary, where funding is excluded before terminal liquidation.

## 9. Frozen funding signal

For each swap instrument `i` at decision `t`:

```text
funding_sum_28d_i(t)
  = sum(realizedRate_j for fundingTime_j in [t - 28 days, t))

positive_funding_share_28d_i(t)
  = count(realizedRate_j > 0) / count(all settlements in [t - 28 days, t))

basis_i(t)
  = latest_permitted_mark_close_i / latest_permitted_spot_close_i - 1
```

An asset is eligible only when every condition holds:

```text
funding_sum_28d_i(t) > 0.009
positive_funding_share_28d_i(t) >= 2/3
abs(basis_i(t)) <= 0.02
```

The realized rate is used once per actual settlement. There is no annualization, rank, beta fit, alternate lookback, parameter variant, optimizer, machine learning model, or LLM signal.

## 10. Single selectable candidate and allocation

Candidate ID:

```text
C9AContinuousNotionalFundingCarry
```

At each decision, current total equity is divided equally among eligible assets. If no asset is eligible, the portfolio holds USDT cash.

For raw sleeve capital `C_i`:

```text
raw_spot_target_notional_i = C_i / 3
raw_dedicated_perpetual_collateral_i = 2 * C_i / 3
```

The base-unit hedge is exact. Maximum initial short notional can vary slightly from spot notional because spot and perpetual execution prices differ; the exact difference and basis are retained.

Weekly actions are frozen:

- close a sleeve that is no longer eligible;
- open a newly eligible sleeve;
- equalize raw sleeve capital across eligible assets;
- for an already-active eligible sleeve, skip resizing only when the absolute raw target-minus-current spot notional is strictly less than `10%` of current spot notional;
- otherwise resize both legs to exact equal base quantity.

After actions are fixed, a single deterministic decimal scale `lambda` in `[0, 1]` applies to all new or resized raw sleeve targets. Held sleeves remain unchanged. The solver maximizes `lambda` subject to non-negative free cash after spot purchases, dedicated-collateral transfers, and spot-leg costs, and positive active margin after perpetual-leg costs. It uses at least 160 fixed bisection iterations. Both costs reduce total equity exactly once. A negative cash balance, hidden borrowing, collateral creation, or post-trade reconciliation residual greater than `1e-10 USDT` fails closed.

## 11. Ledger, funding, and risk

The ledger explicitly retains free USDT cash and, for each sleeve, spot base quantity, short perpetual base quantity, spot value, dedicated margin cash, price PnL, funding PnL, costs, and equity.

For unchanged positions:

```text
spot_price_pnl = spot_base_quantity * (spot_price_new - spot_price_old)
perpetual_price_pnl = short_base_quantity * (mark_price_old - mark_price_new)
funding_pnl = short_base_quantity * preceding_completed_mark_close * realizedRate
```

Transaction costs are:

```text
spot_cost = abs(delta_spot_base) * spot_trade_open * cost_rate
swap_cost = abs(delta_short_base) * swap_trade_open * cost_rate
```

Dedicated perpetual margin cash changes only through collateral transfer at a scheduled rebalance, perpetual price PnL, funding PnL, and perpetual costs. Spot purchases and spot costs change free cash. Closing collateral, after perpetual costs, returns to free cash. Between decisions, no sleeve may draw on free cash or another sleeve to cure a breach.

After every funding event and every completed hourly observation:

```text
collateral_buffer = dedicated_margin_cash / current_short_mark_notional
```

A sleeve is marked for forced close when either condition is first observed:

- `collateral_buffer < 1.25`;
- `abs(mark_close / spot_close - 1) > 0.05`.

It closes at the next available one-hour spot and perpetual trade opens and remains flat until the first scheduled Monday strictly after that forced close. It cannot close and reopen at the same timestamp. The breach and close remain in evidence, and eligibility requires zero buffer breaches and zero base-hedge mismatches. Non-positive equity, non-positive margin cash for an active short, missing next opens, or non-finite state is `PROGRAM_FAILURE` or `DATA_FAILURE` as applicable.

At every exclusive window boundary, all positions close using the boundary spot and perpetual trade opens and the same costs. Funding stamped exactly at the boundary is excluded. No state crosses windows.

## 12. Frozen costs

All-in one-side modeled execution cost per leg:

- expected `1.0x`: `0.0015`;
- stress `1.5x`: `0.00225`;
- stress `2.0x`: `0.0030`.

Every opening, closing, reversal, resize, forced close, and terminal liquidation charges each changed leg separately. No maker rebate, VIP fee, referral rebate, spread income, cash yield, staking yield, lending yield, or unmodeled credit is allowed.

The same frozen signal inputs, eligibility classifications, and target formulas are replayed at all cost levels. Costs, equity-dependent raw targets, target scale, quantities, margin state, risk exits, and equity are recomputed independently for each level.

## 13. Non-selectable comparators

The evidence must compute but may never select:

1. `CashComparator`: `100%` USDT, zero return;
2. `AlwaysOnContinuousDeltaNeutralComparator`: both BTC and ETH are always eligible and otherwise use identical allocation, sizing, costs, collateral, basis-risk, resizing, funding, and terminal rules;
3. `SpotBuyAndHoldComparator`: equal-weight BTC/ETH spot from each window's first trade open to its boundary open, with entry and exit costs recomputed at each cost scenario; descriptive only.

## 14. Metrics and aggregate semantics

Each window retains exactly `26` decisions and weekly buckets. Weekly start equity is measured before same-time funding and trades; the next boundary's funding and trades belong to the next week, except terminal liquidation cost, which belongs to the ending window.

For each window:

```text
window_return = final_equity / 1000 - 1
```

The five windows have equal independent initial capital:

```text
aggregate_return = sum(final_equity_W1..W5) / 5000 - 1
```

The `130` weekly returns, including inactive weeks, are concatenated only for statistics. Annualized weekly Sharpe uses sample standard deviation with `ddof=1`. PSR versus zero uses raw weekly Sharpe, unbiased sample skewness, ordinary kurtosis, and the standard non-normality correction. Invalid variance or radicand yields PSR `0`.

Maximum drawdown is the maximum within-window drawdown over complete hourly post-event equity paths. Annualized one-way paired-notional turnover is the sum of event-level paired turnover ratios divided by `2.5` years, where paired notional is half the sum of absolute spot and perpetual leg changes. One scheduled Monday portfolio rebalance is one simultaneous event with one pre-rebalance equity denominator; all terminal closes at a shared boundary are likewise one event. A single-sleeve forced close is its own event.

Every weekly, window, asset, and aggregate PnL must reconcile to spot-price PnL, perpetual-price PnL, funding, spot costs, and perpetual costs within `1e-10 USDT`.

## 15. Frozen eligibility gates

C9A is `SELECTED` only if every gate passes at expected cost unless another cost is named.

### 15.1 Economics and stability

- every W1–W5 net return is `> 0`;
- aggregate net return is `> 0`;
- aggregate net return at `1.5x` cost is `> 0`;
- aggregate net return at `2.0x` cost is `>= 0`.

### 15.2 Risk and statistics

- annualized weekly Sharpe `>= 1.00`;
- weekly PSR versus zero `>= 0.95`;
- maximum drawdown `<= 0.10`;
- collateral-buffer breach count `= 0`;
- base-hedge mismatch count `= 0`;
- missing decisions, unaccounted funding, non-finite states, non-positive equity states, and reconciliation failures all equal `0`.

### 15.3 Cost and activity

- annualized one-way paired-notional turnover `<= 6.0x`;
- gross positive funding receipts divided by total trading costs `>= 2.0`;
- at least `52` active weekly buckets overall;
- at least `6` active weekly buckets in every window;
- at least `100` funding settlements occur while positions are active.

### 15.4 Breadth and concentration

- BTC and ETH each have positive net contribution;
- maximum positive-asset PnL share `<= 0.70`;
- maximum positive-window PnL share `<= 0.40`;
- maximum positive-week PnL share `<= 0.15`;
- top-three positive-week PnL share `<= 0.35`.

### 15.5 Incremental value over always-on carry

At expected cost:

- candidate aggregate return minus always-on aggregate return is `> 0`;
- candidate annualized Sharpe minus always-on annualized Sharpe is `>= 0.10`;
- candidate maximum drawdown is no greater than always-on maximum drawdown;
- candidate annualized turnover is no greater than always-on annualized turnover.

No relatively best but ineligible result and no comparator may be promoted.

## 16. Multiple testing and allowed claim

C9A has one selectable candidate, one lookback, one threshold set, one sizing rule, and no variants. The evidence must state:

```text
within_stage_candidate_count = 1
within_stage_dsr_used = false
weekly_statistic = PSR_NOT_DSR
program_level_sequential_history_corrected = false
historical_data_status = HISTORICAL_DEVELOPMENT_ONLY
execution_feasibility_established = false
```

PSR does not erase the sequential C0C–C9A research history. A passing result means only `HISTORICAL_CONTINUOUS_NOTIONAL_ECONOMIC_PASS`. It cannot authorize execution, Paper, Shadow, derivatives access, or Live.

## 17. Independent recomputation and evidence

The authoritative package must retain at minimum:

- exact design, implementation, workflow, run, job, checkout, source, and manifest hashes;
- request and final URLs, raw response bytes, normalized rows, retry records, and recursive manifests;
- boundary, coverage, confirmation, funding-uniqueness, and worktree-cleanliness reports;
- every signal input, decision, target, scale, base quantity, trade, fee, collateral transfer, price PnL, funding event, risk state, and terminal close;
- candidate and comparator replays at all costs;
- weekly, window, aggregate, attribution, concentration, PSR, comparator, and final gate evidence;
- explicit `DATA_FAILURE`, `PROGRAM_FAILURE`, or `ECONOMIC_FAIL/PASS` classification.

A physically separate reference implementation must reconstruct signals, continuous quantities, cash and margin ledgers, funding, costs, risk exits, metrics, comparators, and the final decision from primitive normalized public rows. It must not import the production replay, policy, metric, gate, or finalizer. Any mismatch is `PROGRAM_FAILURE`.

## 18. Implementation and one-shot authority boundary

After this design is reviewed and merged, a separate implementation PR may add pure calculation code, source adapters, synthetic/adversarial tests, evidence packaging, and one final manual-dispatch job inside the existing Freqtrade Validation workflow.

Only the exact reviewed implementation SHA may run. The implementation stage may use synthetic fixtures only before that dispatch. The one-shot input and job must be removed immediately after a complete classification, regardless of result.

Forbidden:

- changing any window, signal, threshold, cost, allocation, resize band, risk limit, comparator, statistic, or gate after economic inspection;
- adding variants, selecting only favorable assets/windows, or rerunning after result inspection;
- projecting current instrument metadata backward or claiming historical order feasibility;
- using private OKX APIs, account data, order APIs, Paper effects, Shadow effects, leverage, real derivatives execution, or Live.

## 19. Final design state

`C9A_DESIGN_ONLY`

`C9A_ECONOMIC_RESULT_NOT_RUN`

`HISTORICAL_DEVELOPMENT_ONLY`

`EXECUTION_FEASIBILITY_NOT_ESTABLISHED`

`C9B_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
