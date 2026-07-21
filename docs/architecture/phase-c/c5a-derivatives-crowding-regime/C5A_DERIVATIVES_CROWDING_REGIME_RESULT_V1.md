# C5A Derivatives-Crowding Regime — Authoritative Result V1

## 1. Status

C5A completed as a valid negative economic result.

- Economic result: `REJECTED`
- Selected policy: `null`
- C5B confirmation: `CLOSED`
- Holdout: `CLOSED`
- Paper execution: `CLOSED`
- Shadow execution: `CLOSED`
- Live execution: `FORBIDDEN`

No threshold, cost, gate, window, crowding rule, trend rule, sizing rule, or safety state was weakened after observing the result. The non-selectable price-only ablation was not promoted.

## 2. Exact authority and provenance

### Frozen economic source

- Source SHA: `6042637f8b9afa8babe34f2353a779a2be56cc95`
- Required merged design main: `77e1796bd70b3e646595972af772c91af6c8f8a9`
- Original workflow-only head: `d99c2a2cb1ca7d7129c5866d824b552cd37b26d1`
- Economic merge-ref: `b903987bb58440b6649c8fd7e65f61bb6abcdfa0`

### Authoritative economic artifact

- Workflow run: `29801830531`
- Artifact ID: `8484045792`
- Artifact digest: `sha256:0d3b64a1e979bb6b1635542487253a2ebf54d301ef0ecf8d80f958568fa3b563`
- Economic screen step: `PASS`
- Economic result retained in the artifact: `REJECTED`
- Selected policy retained in the artifact: `null`

The original run failed only after the completed economic screen, during independent evidence finalization, because the frozen finalizer referenced the frozen contract constant `SWAP_INSTRUMENTS` without that name being re-exported by the frozen reference-recompute module.

### Independent final evidence

- Recovery/finalization run: `29807079163` — `PASS`
- Artifact ID: `8485899372`
- Artifact digest: `sha256:5a3f18bf070c5a04b912474a6becc0c97dd33333c598aaf7889f89bf68f28dee`
- Independent checks passed: `21`
- Errors: `[]`
- Complete manifest entries: `160`

The recovery downloaded no new market data and did not rerun any signal, portfolio, accounting, gate, ranking, or economic calculation. It hash-verified and restored the completed primitive artifact, then exposed the frozen contract tuple to the frozen finalizer at runtime solely to finish independent evidence packaging.

### Repository closeout

- Final workflow-removal head: `2ee45d4ba3bef79de0e39d6199c964cb1ec1a49f`
- C5A implementation merge commit: `1701bacb313400fa283bb1962549f840d3a21dd4`
- Final closeout CI: run `29807168871` — `PASS`
- Final closeout Freqtrade Validation: run `29807168831` — `PASS` after retry
- Final exact-head review: `4743660112` — `PASS`

The temporary executable C5A workflow was deleted before merge. Comparing the frozen economic source with the final workflow-removal head produced four workflow-only commits and zero net changed files. Comparing the final PR head with the merge commit also produced zero changed files.

## 3. Frozen data and evidence coverage

The authoritative evidence retained and independently checked:

- three OKX spot trade-candle series: `BTC-USDT`, `ETH-USDT`, and `SOL-USDT`;
- three corresponding perpetual-swap quote-volume series;
- three corresponding perpetual mark-price series;
- `2,940` four-hour rows per series;
- download interval: `2024-09-02T00:00:00Z` to `2026-01-05T00:00:00Z`, end exclusive;
- one boundary row at `2026-01-05T00:00:00Z` removed and recorded from each raw series before research use;
- `39` formation Mondays per asset, `117` calibration rows total;
- formation-only calibration interval: `2024-10-07T00:00:00Z` through `2025-06-30T00:00:00Z`;
- D1 screen: `2025-07-07T00:00:00Z` to `2025-10-06T00:00:00Z`;
- D2 screen: `2025-10-06T00:00:00Z` to `2026-01-05T00:00:00Z`;
- `12` policy cells and `18` comparator cells;
- `6` policy aggregates and `9` comparator aggregates;
- `30` result pointers and `30` result exports;
- `156` decisions and `468` per-asset signal rows;
- `63` complete rebalance-ledger entries;
- `156` weekly buckets and `156` explicit weekly accounting rows;
- `6` concentration numerator/denominator records;
- `33` effective-source inventory entries and `33` exact source snapshots;
- `160` final manifest entries with independently verified sizes and SHA-256 hashes.

No C5B timestamp, private API, account, order, leverage, short, paper, shadow, or live path was opened.

## 4. Preregistered policies

### Selectable candidate

`C5ADerivativesCrowdingFilteredRiskBalance` combined:

- positive 28-day trend;
- BTC trend and breadth regime controls;
- exclusion of the top 20% crowding score derived from seven-day mark/spot basis and swap/spot quote-volume participation percentiles;
- inverse-volatility sizing;
- 80% maximum invested weight, 20% cash target, and 40% per-asset cap;
- 10% one-way no-trade band;
- completed-Sunday signals and Monday execution.

### Non-selectable ablation

`C5APriceOnlyRiskBalanceAblation` used the same price trend, regime, sizing, costs, timing, and accounting but omitted the derivatives-crowding exclusion. It was diagnostic only and was never eligible for selection.

## 5. Candidate result

Expected cost is the preregistered one-side rate of `0.15%` (`1.0x`).

| Metric | Candidate result | Frozen requirement | Pass |
|---|---:|---:|---|
| D1 net return | 5.7851% | > 0% | Yes |
| D2 net return | -10.0006% | > 0% | No |
| Aggregate net return | -4.7941% | > 0% | No |
| Aggregate return at `1.5x` cost | -5.3537% | >= 0% | No |
| Aggregate Sharpe | -0.2726 | >= 0.75 | No |
| Weekly PSR | 0.4289 | >= 0.90 | No |
| Maximum half drawdown | 15.1799% | <= 15% | No |
| Annualized one-way turnover | 14.3190× | <= 8× | No |
| Exposure ratio | 34.6154% | <= 80% | Yes |
| Active rebalances | 10 | >= 4 | Yes |
| Minimum active rebalances per half | 4 | >= 2 | Yes |
| Positive contributing assets | 1 | >= 2 | No |
| Maximum positive-half PnL share | 100.0000% | <= 70% | No |
| Maximum positive-asset PnL share | 100.0000% | <= 60% | No |
| Maximum positive-week PnL share | 37.6237% | <= 25% | No |
| Top-three positive-week PnL share | 82.7856% | <= 55% | No |

At `2.0x` cost, aggregate net return declined further to `-5.9100%`.

The expected-cost asset contributions were:

| Asset | Net contribution |
|---|---:|
| `BTC-USDT` | -66.8355 |
| `ETH-USDT` | 41.9276 |
| `SOL-USDT` | -17.2474 |

Only ETH contributed positively, so the candidate failed both breadth and asset-concentration requirements.

## 6. Incremental-information test against the price-only ablation

At expected cost:

| Metric | Crowding candidate | Price-only ablation | Candidate minus ablation | Incremental gate |
|---|---:|---:|---:|---|
| Aggregate net return | -4.7941% | 13.7777% | -18.5718 pp | Diagnostic |
| Aggregate Sharpe | -0.2726 | 1.1139 | -1.3865 | **Fail** |
| Maximum half drawdown | 15.1799% | 15.9081% | -0.7282 pp | Pass |
| Annualized one-way turnover | 14.3190× | 16.5075× | -2.1885× | Pass |

The crowding filter modestly reduced drawdown and turnover relative to the ablation, but it destroyed risk-adjusted performance and produced a negative aggregate return. It therefore failed the central preregistered requirement that derivatives-crowding information add value beyond otherwise identical price-only construction.

## 7. Price-only ablation context

The ablation was not selectable. Its positive aggregate headline did not make it eligible.

| Metric | Expected-cost result |
|---|---:|
| D1 net return | 29.4285% |
| D2 net return | -12.0922% |
| Aggregate net return | 13.7777% |
| Aggregate Sharpe | 1.1139 |
| Weekly PSR | 0.7613 |
| Maximum half drawdown | 15.9081% |
| Annualized one-way turnover | 16.5075× |
| Maximum positive-half PnL share | 100.0000% |
| Maximum positive-asset PnL share | 86.2946% |

The ablation still failed the positive-D2, weekly-PSR, drawdown, turnover, half-concentration, and asset-concentration standards. It cannot be treated as a selected fallback strategy.

## 8. Comparator context at expected cost

| Comparator | D1 net return | D2 net return | Aggregate net return | Maximum half drawdown |
|---|---:|---:|---:|---:|
| Cash | 0.0000% | 0.0000% | 0.0000% | 0.0000% |
| BTC buy-and-hold | 12.7356% | -26.0910% | -16.6782% | 34.3590% |
| BTC/ETH/SOL equal-weight buy-and-hold | 45.9694% | -32.7189% | -1.7901% | 41.5737% |

These comparators are descriptive context only. The candidate's lower drawdown than buy-and-hold did not compensate for its negative aggregate return, failed statistical evidence, excessive turnover, and concentration failures.

## 9. Interpretation

C5A falsified the preregistered proposition that this exact public perpetual-market crowding filter improved the risk-adjusted BTC/ETH/SOL spot allocation over otherwise identical price-only construction during the fresh C5A screen.

The principal observations are:

1. performance reversed sharply between D1 and D2;
2. the crowding filter reduced market participation but did not produce robustness;
3. expected-cost and stressed-cost aggregate returns were negative;
4. weekly PSR was far below the frozen confidence threshold;
5. turnover remained almost twice the permitted maximum;
6. positive PnL was concentrated in one half, one asset, and a few weeks;
7. the price-only ablation materially outperformed the candidate on return and Sharpe, so the added derivatives proxy had negative incremental information in this test.

This result does not establish that all derivatives information is useless. It establishes that this exact mark/spot-basis plus quote-volume-participation crowding construction, with the frozen calibration, timing, sizing, and gates, did not provide a selectable edge.

C5A must not be rerun with altered percentile thresholds, relaxed gates, changed costs, retrospectively selected windows, or promoted ablation results. C5B remains closed.

## 10. Limitations and claim boundary

This result is limited to:

- BTC, ETH, and SOL spot allocation;
- the exact three corresponding USDT perpetual instruments;
- public four-hour trade, mark-price, and quote-volume data;
- the exact formation-only empirical percentile calibration;
- the two fresh C5A development halves ending before the C5B boundary;
- long-only, volatility-balanced weekly allocation;
- the exact costs, accounting, no-trade band, concentration limits, and gates in the merged contract.

It does not establish general performance for other assets, exchanges, horizons, funding-rate definitions, open-interest data, order-book data, on-chain data, macro data, short portfolios, leverage, or adaptive calibration.

The weekly PSR corrects only the C5A candidate's within-stage weekly evidence. It does not correct the broader sequential C0C-through-C5A research-selection history.

## 11. Forward research boundary

Any future proposal must be a separate design-only change with a structurally distinct, prospectively frozen thesis. It must not be a threshold relaxation, percentile retune, window substitution, or post-hoc rescue of either C5A policy.

This result document approves no C5B run and no new strategy family by itself.

## 12. Final state

`C5A_REJECTED`

`SELECTED_POLICY_NULL`

`C5B_CLOSED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
