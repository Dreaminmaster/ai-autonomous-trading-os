# C3A Residual Mean-Reversion Result V1

## Status

- Stage: `C3A`
- Economic result: `REJECTED`
- Selected policy: `null`
- Confirmation opened: `false`
- C3B confirmation: `CLOSED`
- Holdout state: `HOLDOUT_CLOSED`
- Live: `FORBIDDEN`

This is a valid preregistered economic rejection. It is not an implementation or evidence failure, and it does not authorize threshold changes, in-place retuning, C3B access, paper trading, shadow trading, private OKX APIs, leverage, derivatives, shorts, or live execution.

## Authoritative evidence

- Frozen economic source SHA: `3cdf1e989d6084c7f66f33d6b1a8d297d3f76965`
- Workflow-only head SHA: `2fa745fabb4f988c71901a64c0e86e191bdaac83`
- PR merge-ref SHA: `cb568d291425f337f1292e5098e06b7d42658e00`
- Authoritative workflow: `C3A Authoritative Screen #3`
- Workflow run ID: `29688657555`
- Artifact ID: `8442879943`
- Artifact digest: `sha256:4079ef14a16969115e0666c2f9527b107a2f797e384197e468107afa34ef3aeb`
- Independent artifact audit comment: `5016168856`

Frozen-source prerequisite validation:

- CI #904, run `29672938761`: `PASS`
- Freqtrade Validation #605, run `29672938732`: `PASS`

Workflow-head normal validation:

- CI #910, run `29688634990`: `PASS`
- Freqtrade Validation #608, run `29688634993`: `PASS`

## Pre-economic incident chain

Two earlier workflow attempts are retained as evidence failures, not economic observations.

1. Run `29675135871` failed before public download because the runtime Freqtrade configuration did not exist. Download, boundary sealing, the economic screen, and the independent finalizer were skipped. Artifact digest: `sha256:363fa1934ac2ad429ae9dbf069406de7d5a07ca49580977c290537cd8129f6b5`.
2. Run `29683819964` failed at the start of `freqtrade download-data` because the required Freqtrade `user_data` directory did not exist. Boundary sealing, the economic screen, and the independent finalizer were skipped. Artifact digest: `sha256:7defbcfad37d2f596a49e34e598cad387e2d833cd9888bb250af218722f6cba6`.

The successful run independently checked both incident SHAs, step boundaries, artifact names, and artifact digests before downloading market data. Neither failed run exposed C3A economic results.

## Evidence integrity

The authoritative workflow and independent artifact audit both passed.

- Every economic-stage workflow step completed successfully.
- Failure-state recording was correctly skipped.
- Exact source, workflow-head, merge-ref, and prior-validation bindings matched the values above.
- Public OKX BTC/ETH/SOL four-hour data were downloaded with empty credentials, spot mode, dry-run mode, and no order-book use.
- Each retained dataset contained exactly `2,376` candles from `2023-09-01 00:00 UTC` through `2024-09-30 20:00 UTC`, with zero duplicates and zero four-hour gaps.
- The public API returned `23` overshoot candles per asset at or after the exclusive `2024-10-01` boundary; all were removed before research reads.
- Exactly `27` policy rows and `36` comparator rows were retained.
- Exactly `63` hidden `.last_result.json` pointers and `63` matching result exports were retained.
- The effective-source inventory contained exactly `18` files and `18` matching source snapshots.
- The final manifest contained `173` files; every indexed file independently matched its retained size and SHA-256.
- The separate plain-array finalizer reported `12` checks passed and `errors=[]`.
- `confirmation_opened=false`, `HOLDOUT_CLOSED`, and `LIVE_FORBIDDEN` remained unchanged.

The runtime `workflow_state.json` is the immutable start marker written before execution. Final authority is carried by `run_summary.json`, `decision.json`, `final_evidence.json`, `pre_manifest_verification.json`, and the completed manifest.

## Frozen screen

Policies:

1. `C3AEthResidualReversion`
2. `C3ASolResidualReversion`
3. `C3AStrongestLaggardResidualReversion`

Assets:

- `BTC/USDT` as the residual driver and regime filter
- `ETH/USDT`
- `SOL/USDT`
- cash

Screen windows:

- S1: `2024-01-01` to `2024-04-01`
- S2: `2024-04-01` to `2024-07-01`
- S3: `2024-07-01` to `2024-10-01`

Fee multipliers:

- `1.0x`: `0.15%` one side
- `1.5x`: `0.225%` one side
- `2.0x`: `0.30%` one side

## Policy decisions

### C3AEthResidualReversion — ineligible

- Positive windows: `1 / 3`
- Window returns: S1 `+7.0404%`, S2 `-2.3241%`, S3 `-3.4280%`
- Median window return: `-2.3241%`
- Aggregate expected-cost return: `+0.9686%`
- Aggregate 1.5x-cost return: `+0.5902%`
- Aggregate Sharpe: `0.2454`
- Profit factor: `1.2240`
- Closed trades: `5`
- Minimum closed trades in a window: `1`
- Maximum window drawdown: `3.4280%`
- Annualized one-way turnover: `6.6680x`
- Exposure ratio: `2.0073%`
- Maximum window positive-PnL share: `100.0000%`
- Maximum single-trade positive-PnL share: `74.6266%`
- Maximum top-three positive-PnL share: `100.0000%`

Failed gates: positive windows, positive median window return, aggregate Sharpe, total closed trades, minimum per-window closed trades, window concentration, single-trade concentration, and top-three-trade concentration.

### C3ASolResidualReversion — ineligible

- Positive windows: `1 / 3`
- Window returns: S1 `+13.3162%`, S2 `-7.0944%`, S3 `-1.3712%`
- Median window return: `-1.3712%`
- Aggregate expected-cost return: `+3.8336%`
- Aggregate 1.5x-cost return: `+2.7470%`
- Aggregate Sharpe: `0.4815`
- Profit factor: `1.3418`
- Closed trades: `14`
- Minimum closed trades in a window: `4`
- Maximum window drawdown: `9.6632%`
- Annualized one-way turnover: `18.6780x`
- Exposure ratio: `3.8321%`
- Maximum window positive-PnL share: `100.0000%`
- Maximum single-trade positive-PnL share: `31.1516%`
- Maximum top-three positive-PnL share: `65.4947%`

Failed gates: positive windows, positive median window return, aggregate Sharpe, total closed trades, window concentration, single-trade concentration, and top-three-trade concentration.

### C3AStrongestLaggardResidualReversion — ineligible

- Positive windows: `1 / 3`
- Window returns: S1 `+14.6597%`, S2 `-5.6050%`, S3 `-7.2121%`
- Median window return: `-5.6050%`
- Aggregate expected-cost return: `+0.4271%`
- Aggregate 1.5x-cost return: `-0.6972%`
- Aggregate Sharpe: `0.1069`
- Profit factor: `1.1283`
- Closed trades: `15`
- Minimum closed trades in a window: `4`
- Maximum window drawdown: `9.4418%`
- Annualized one-way turnover: `19.9893x`
- Exposure ratio: `4.1971%`
- Maximum window positive-PnL share: `100.0000%`
- Maximum single-trade positive-PnL share: `33.2500%`
- Maximum top-three positive-PnL share: `71.5830%`
- Maximum asset positive-PnL share: `77.1273%`

Failed gates: positive windows, positive median window return, nonnegative 1.5x-cost aggregate return, aggregate Sharpe, profit factor, total closed trades, window concentration, single-trade concentration, top-three-trade concentration, and asset concentration.

## Comparator context

At expected cost:

- Cash aggregate return: `0.0000%`, maximum window drawdown `0.0000%`.
- BTC buy-and-hold aggregate return: `+48.4343%`, maximum window drawdown `26.2101%`.
- ETH buy-and-hold aggregate return: `+12.9979%`, maximum window drawdown `37.1375%`.
- SOL buy-and-hold aggregate return: `+48.5489%`, maximum window drawdown `40.5347%`.

The residual policies had much lower drawdowns and exposure than directional buy-and-hold, but their small aggregate gains were concentrated in S1, their median window returns were negative, and their trade samples were too sparse or concentrated to satisfy the frozen robustness gates.

## Decision

No policy satisfied every frozen eligibility condition, so the eligible ranking is empty and `selected_policy=null`.

All three policies produced only one positive window. S2 and S3 were negative for every policy, making every median window return negative. No policy reached the `0.75` aggregate-Sharpe floor or the `18`-trade minimum, and all violated positive-PnL concentration limits. The strongest-laggard variant also became negative under the preregistered 1.5x-cost stress and failed the profit-factor and asset-concentration gates.

C3A is frozen as `REJECTED`. Its constants, gates, ranking, windows, costs, and candidate implementations must not be modified in response to this result.

## Post-C3A state

- C3B confirmation: `CLOSED`
- Holdout: `CLOSED`
- Paper trading: not authorized
- Shadow trading: not authorized
- Private OKX APIs: not authorized
- Leverage, derivatives, and shorts: not authorized
- Live trading: `FORBIDDEN`

Any future research direction must be defined as a genuinely structural new preregistered thesis rather than an in-place retuning of C3A.

`C3B_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
