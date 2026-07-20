# C4A Large-Liquid Cross-Sectional Momentum — Authoritative Result V1

## 1. Status

C4A completed as a valid negative economic result.

- Economic result: `REJECTED`
- Selected policy: `null`
- C4B confirmation: `CLOSED`
- Holdout: `CLOSED`
- Paper execution: `CLOSED`
- Shadow execution: `CLOSED`
- Live execution: `FORBIDDEN`

No threshold, cost, gate, window, ranking rule, universe rule, signal rule, or safety state was weakened after observing the result. No relatively best but ineligible policy was promoted.

## 2. Exact authority and provenance

### Frozen economic source

- Source SHA: `7723aec183a07dd654a1c3740e75bdcc47133fbe`
- Required merged design main: `96015f9f15c04a4a834878bb32215194ce05c7eb`
- Economic merge-ref: `e1374be21e701c1b0341cf32a2922b781bbaabca`

### Authoritative economic artifact

- Workflow run: `29746643601`
- Artifact ID: `8462729263`
- Artifact digest: `sha256:847ded9dde4e8ac55b77477f919f8acda15620db676557e4ed370fd896c59b0d`
- Economic result retained in the artifact: `REJECTED`
- Selected policy retained in the artifact: `null`

### Independent final evidence

- Recovery/finalization run: `29747259613` — `PASS`
- Artifact ID: `8462947136`
- Artifact digest: `sha256:0dbe2a10fa8fd9d7749d36c223dca86ccb9f297193946979c0646d6b63c42e5f`
- Independent checks passed: `20`
- Errors: `[]`

The finalization recovery did not download new market data and did not rerun the economic calculation. It reused the immutable completed economic artifact and normalized only equivalent UTC timestamp string representations during evidence postprocessing.

### Repository closeout

- Final workflow-removal head: `589fd6ed545571c0387c7a58dd0c3f07840d57ad`
- C4A implementation merge commit: `4515ff60c8a18220d84ef24fd985c311784f77f7`
- Final closeout CI: run `29747363497` — `PASS`
- Final closeout Freqtrade Validation: run `29747363565` — `PASS`

The temporary executable C4A workflow was deleted before merge. Comparing the frozen economic source with the final workflow-removal head produced zero net changed files, proving that the recovery commits were workflow-only and left no executable workflow or economic-source change behind.

## 3. Frozen data and evidence coverage

The authoritative evidence retained and independently checked:

- 12 preregistered OKX spot candidate pairs;
- 2,376 four-hour candles per pair;
- formation interval: `2023-09-01T00:00:00Z` to `2024-01-01T00:00:00Z`;
- screen interval: `2024-01-01T00:00:00Z` to `2024-10-01T00:00:00Z`, end exclusive;
- 27 policy cells;
- 36 comparator cells;
- 63 result pointers and 63 result exports;
- 120 expected-cost weekly schedule entries;
- 960 weekly signal rows;
- 39 full-week DSR observations per policy;
- 360 complete rebalance-ledger entries;
- 28 effective-source inventory entries and 28 exact source snapshots;
- 213 final manifest entries with independently verified sizes and SHA-256 hashes.

No confirmation, holdout, private API, order-book, derivatives, leverage, shorting, paper, shadow, or live data path was opened.

## 4. Formation-only selected universe

The fixed top-eight universe selected from formation-period median `close × base volume` was:

| Rank | Pair |
|---:|---|
| 1 | `BTC/USDT` |
| 2 | `ETH/USDT` |
| 3 | `SOL/USDT` |
| 4 | `XRP/USDT` |
| 5 | `DOGE/USDT` |
| 6 | `LTC/USDT` |
| 7 | `LINK/USDT` |
| 8 | `AVAX/USDT` |

The universe was frozen before the screen-period returns were evaluated.

## 5. Policy results at expected cost

Expected cost is the preregistered one-side rate of `0.15%` (`1.0x`).

| Policy | S1 net return | S2 net return | S3 net return | Aggregate net return | Aggregate Sharpe | Within-stage DSR probability | Max window drawdown | Annualized one-way turnover | Eligible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `C4AWeeklyReturnTopTwo` | 39.8839% | -19.6617% | -16.5867% | -6.2598% | 0.0361 | 0.3145 | 24.9365% | 39.5184× | No |
| `C4AHighProximityTopTwo` | 26.9273% | -3.5671% | -9.1652% | 11.1816% | 0.5784 | 0.5072 | 18.9893% | 32.4823× | No |
| `C4ACompositeMomentumTopTwo` | 59.2643% | -17.4247% | 4.0511% | 36.8407% | 1.2013 | 0.7191 | 18.9633% | 36.0019× | No |

### 5.1 Weekly-return policy rejection

`C4AWeeklyReturnTopTwo` failed:

- minimum positive-window count;
- positive median-window return;
- positive expected-cost aggregate return;
- non-negative `1.5x`-cost aggregate return;
- aggregate Sharpe threshold;
- within-stage DSR threshold;
- maximum drawdown threshold;
- turnover threshold;
- window concentration threshold;
- single-week concentration threshold;
- top-three-week concentration threshold.

Its `1.5x`-cost aggregate return was `-8.3244%`.

### 5.2 High-proximity policy rejection

`C4AHighProximityTopTwo` failed:

- minimum positive-window count;
- positive median-window return;
- aggregate Sharpe threshold;
- within-stage DSR threshold;
- maximum drawdown threshold;
- turnover threshold;
- window concentration threshold;
- asset concentration threshold.

Its expected-cost aggregate return was positive, and its `1.5x`-cost aggregate return remained positive at `9.1650%`, but those facts did not override the failed preregistered eligibility gates.

### 5.3 Composite policy rejection

`C4ACompositeMomentumTopTwo` was the strongest-looking policy by headline return, but it remained ineligible. It failed:

- within-stage DSR probability: `0.7191`, below the `0.90` minimum;
- maximum window drawdown: `18.9633%`, above the `15%` maximum;
- annualized one-way turnover: `36.0019×`, above the `18×` maximum;
- maximum positive-window PnL share: `93.6018%`, above the `70%` maximum.

Its `1.5x`-cost aggregate return was `34.0924%`. This did not justify promotion because the result was statistically insufficient, too drawdown-heavy, too turnover-intensive, and overwhelmingly dependent on one positive window.

## 6. Comparator context at expected cost

| Comparator | S1 net return | S2 net return | S3 net return | Aggregate net return | Maximum window drawdown |
|---|---:|---:|---:|---:|---:|
| Cash | 0.0000% | 0.0000% | 0.0000% | 0.0000% | 0.0000% |
| BTC buy-and-hold | 68.0942% | -12.2041% | 0.5791% | 48.4343% | 26.2101% |
| Top-eight equal-weight buy-and-hold | 60.5117% | -26.7815% | -4.4272% | 12.3212% | 34.4797% |
| BTC/ETH/SOL equal-weight buy-and-hold | 75.2528% | -15.3244% | -6.7547% | 38.3727% | 33.0725% |

The comparator table is descriptive context, not a substitute for the C4A eligibility gates. In particular, the composite policy's aggregate return was close to the BTC/ETH/SOL comparator but did not demonstrate sufficiently stable, low-concentration, low-turnover risk-adjusted evidence.

## 7. Interpretation

C4A falsified the proposition that the three preregistered weekly, long-only, top-two price-momentum ranking policies provided a sufficiently robust development-stage edge over this fixed 2024 screen.

The result does not say that cross-sectional momentum can never work. It says that this exact implementation, fixed universe, fixed weekly schedule, fixed breadth rule, fixed costs, and fixed three-policy family did not clear the prospectively frozen standard.

The repeated failure pattern across the policies was not simply low headline return. The more important weaknesses were:

1. strong regime dependence across the three windows;
2. excessive turnover relative to the frozen limit;
3. drawdowns above the permitted limit for the stronger policies;
4. positive PnL concentrated in too few windows, weeks, or assets;
5. within-stage DSR evidence below the required confidence level.

Therefore C4A must not be rerun with altered thresholds or retrospectively tuned variants. C4B remains closed.

## 8. Limitations and claim boundary

This result is limited to:

- the exact 12-pair incumbent candidate pool;
- the formation-only top-eight universe selected from that pool;
- the exact 2024 development screen;
- spot, long-only, weekly top-two rotation;
- the exact costs, accounting, signals, gates, and ranking rules in the merged contract;
- within-stage DSR correction for exactly three C4A policy trials.

It does not establish general performance across all historical OKX listings, later market periods, other exchanges, shorter or longer horizons, adaptive universes, short portfolios, derivatives, order-book signals, funding, open interest, on-chain data, or macro data.

The DSR calculation corrects only the three within-stage C4A candidates. It does not erase the broader sequential research-selection history from C1A through C4A.

## 9. Forward research boundary

The next research proposal must be preregistered in a separate design-only change. It must not be framed as a threshold relaxation or a parameter retune of C4A.

The C4A diagnosis suggests that a future structurally distinct thesis should explicitly address, before implementation:

- slower effective turnover;
- volatility-aware or risk-balanced sizing rather than fixed 45%/45% concentration;
- regime robustness rather than dependence on one favorable quarter;
- explicit concentration controls embedded in construction rather than checked only after the fact;
- genuine incremental information beyond another closely related pure-price top-two ranking variant.

No such future thesis is approved by this result document itself.

## 10. Final state

`C4A_REJECTED`

`SELECTED_POLICY_NULL`

`C4B_CLOSED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
