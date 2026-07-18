# C2A Low-Turnover Allocation Result V1

## Status

- Stage: `C2A`
- Economic result: `REJECTED`
- Selected policy: `null`
- Confirmation opened: `false`
- C2B confirmation: `CLOSED`
- Holdout state: `HOLDOUT_CLOSED`
- Live: `FORBIDDEN`

This is a valid preregistered economic rejection. It is not an implementation or evidence failure, and it does not authorize threshold changes, in-place retuning, C2B access, paper trading, shadow trading, private OKX APIs, derivatives, leverage, or live execution.

## Authoritative evidence

- Candidate source SHA: `d39d3b10f5cda7edb1bda05ed0fd428767e0c8bb`
- PR merge-ref SHA: `ded87b9c086c7d078cbe8f45bd534a3ed5e5c4fa`
- Authoritative workflow: `C2A Low-Turnover Allocation Screen #7`
- Workflow run ID: `29643566811`
- Artifact ID: `8429351170`
- Artifact digest: `sha256:fead08e24596be9eb807d57c02677e10c7afb1f5f61bdcaa495dc1ddda3c4634`
- Independent readiness review: `4728450738`
- Independent artifact review: `4728547134`

Exact-head prerequisite validation:

- CI #825, run `29640452135`: `PASS`
- Freqtrade Validation #540, run `29640452132`: `PASS`
- Validation-summary artifact ID: `8429232798`
- Validation-summary digest: `sha256:400b0dfc8aff96a3a6a76a591981aeafd59ad4d8a62a96eb24500dd1071fbee1`

## Evidence integrity

The authoritative workflow and independent archive audit both passed.

- Every authoritative workflow step completed successfully.
- The independently downloaded artifact ZIP matched the GitHub artifact digest.
- Exact source and merge-ref bindings matched the values above.
- Exactly `27` policy/window/cost economic rows were retained.
- Exactly `27` comparator/window/cost rows were retained.
- Exactly `54` hidden `.last_result.json` pointers and `54` matching result exports were retained.
- All `3` data-boundary cells passed.
- All `3` startup and continuous-coverage cells passed.
- Each retained BTC/ETH/SOL daily dataset contained `519` rows from `2023-05-01` through `2024-09-30`, with zero duplicates and zero daily gaps.
- The public API returned overshoot through `2024-12-19`; the guard removed `80` rows per asset at or after the exclusive `2024-10-01` boundary before any research read.
- C2B and holdout therefore remained economically and statistically unopened.
- The effective-source inventory contained exactly `17` files, with hashes retained and verified.
- The manifest retained `122` files.
- The finalizer reported `201` checks passed and `errors=[]`.
- `confirmation_opened=false`, `HOLDOUT_CLOSED`, and `LIVE_FORBIDDEN` remained unchanged.

## Frozen screen

Policies:

1. `C2AEqualWeightRiskOn`
2. `C2AInverseVolRiskOn`
3. `C2ATopTwoPersistentMomentum`

Assets:

- `BTC/USDT`
- `ETH/USDT`
- `SOL/USDT`
- cash

Screen windows:

- S1: `2024-01-01` to `2024-04-01`
- S2: `2024-04-01` to `2024-07-01`
- S3: `2024-07-01` to `2024-10-01`

Fee multipliers:

- `1.0x`
- `1.5x`
- `2.0x`

The expected one-side fee at `1.0x` was `0.15%`.

## Policy decisions

### C2AEqualWeightRiskOn — ineligible

- Positive windows: `1 / 3`
- Median window return: `-2.7611%`
- Aggregate return: `+56.6946%`
- Aggregate 1.5x-cost return: `+56.1532%`
- Aggregate Sharpe: `1.6023`
- Maximum window drawdown: `17.5072%`
- Scheduled nonzero rebalances: `6`
- Minimum nonzero rebalances in a window: `2`
- Annualized one-way turnover: `6.5181x`
- Positive assets: `BTC/USDT`, `ETH/USDT`, `SOL/USDT`
- Maximum asset positive-PnL share: `45.0095%`
- Maximum window positive-PnL share: `100.0000%`
- Largest positive daily contribution share: `6.8781%`
- Top-three positive daily contribution share: `15.7762%`

Window returns: S1 `+76.7567%`, S2 `-2.7611%`, S3 `-8.8328%`.

Failed gates: fewer than two positive windows; non-positive median window return; maximum window drawdown above `15%`; annualized one-way turnover above `6x`; maximum window positive-PnL share above `60%`.

### C2AInverseVolRiskOn — ineligible

- Positive windows: `1 / 3`
- Median window return: `-2.9470%`
- Aggregate return: `+56.2769%`
- Aggregate 1.5x-cost return: `+55.7084%`
- Aggregate Sharpe: `1.6318`
- Maximum window drawdown: `16.2723%`
- Scheduled nonzero rebalances: `6`
- Minimum nonzero rebalances in a window: `2`
- Annualized one-way turnover: `6.5425x`
- Positive assets: `BTC/USDT`, `ETH/USDT`, `SOL/USDT`
- Maximum asset positive-PnL share: `37.2699%`
- Maximum window positive-PnL share: `100.0000%`
- Largest positive daily contribution share: `6.7375%`
- Top-three positive daily contribution share: `15.3219%`

Window returns: S1 `+73.4945%`, S2 `-2.9470%`, S3 `-7.1888%`.

Failed gates: fewer than two positive windows; non-positive median window return; maximum window drawdown above `15%`; annualized one-way turnover above `6x`; maximum window positive-PnL share above `60%`.

### C2ATopTwoPersistentMomentum — ineligible

- Positive windows: `1 / 3`
- Median window return: `-6.4545%`
- Aggregate return: `+60.1730%`
- Aggregate 1.5x-cost return: `+59.5534%`
- Aggregate Sharpe: `1.5914`
- Maximum window drawdown: `22.1823%`
- Scheduled nonzero rebalances: `7`
- Minimum nonzero rebalances in a window: `2`
- Annualized one-way turnover: `7.2291x`
- Positive assets: `BTC/USDT`, `SOL/USDT`
- Maximum asset positive-PnL share: `59.0700%`
- Maximum window positive-PnL share: `100.0000%`
- Largest positive daily contribution share: `6.5786%`
- Top-three positive daily contribution share: `15.8503%`

Window returns: S1 `+85.3414%`, S2 `-6.4545%`, S3 `-7.6166%`.

Failed gates: fewer than two positive windows; non-positive median window return; maximum window drawdown above `15%`; annualized one-way turnover above `6x`; maximum window positive-PnL share above `60%`.

## Comparator context

At expected cost:

- Cash aggregate return: `0.0000%`, maximum window drawdown `0.0000%`.
- BTC buy-and-hold aggregate return: `+48.4343%`, maximum window drawdown `20.9273%`.
- Equal-weight buy-and-hold aggregate return: `+38.3727%`, maximum window drawdown `30.0346%`.

All three C2A policies exceeded the aggregate comparator returns, but this did not override the frozen stability, drawdown, turnover, and window-concentration requirements.

## Decision

No policy satisfied every frozen eligibility condition, so the eligible ranking is empty and `selected_policy=null`.

The high aggregate returns were concentrated entirely in S1. Every policy lost money in both S2 and S3, produced a negative median window return, exceeded the `15%` maximum-window drawdown gate, exceeded the `6x` annualized one-way turnover ceiling, and assigned `100%` of positive window PnL to a single window. The positive aggregate and stress-cost results therefore do not constitute a robust development-screen pass.

C2A is frozen as `REJECTED`. Its constants, gates, ranking, windows, costs, and candidate implementations must not be modified in response to this result.

## Post-C2A state

- C2B confirmation: `CLOSED`
- Holdout: `CLOSED`
- Paper trading: not authorized
- Shadow trading: not authorized
- Private OKX APIs: not authorized
- Live trading: `FORBIDDEN`

Any future research direction must be defined as a genuinely structural new preregistered thesis rather than an in-place retuning of C2A.

`CONFIRMATION_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
