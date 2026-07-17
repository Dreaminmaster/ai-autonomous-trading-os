# C1A Strategy Family Screen Result V1

## Status

- Stage: `C1A`
- Economic result: `REJECTED`
- Selected family: `null`
- Confirmation opened: `false`
- Holdout state: `HOLDOUT_CLOSED`
- Live: `FORBIDDEN`

This is a valid preregistered economic rejection. It is not an implementation or evidence failure, and it does not authorize parameter changes, C1B confirmation, paper trading, shadow trading, holdout access, private OKX APIs, derivatives, leverage, or live execution.

## Authoritative evidence

- Candidate source SHA: `e89414418dd4d55f0d5307d5ed5ccf9f84ebe133`
- PR merge-ref SHA: `d918e651dcd418de55e3e01ca8351b23694d6973`
- Authoritative workflow: `C1A Strategy Family Screen #3`
- Workflow run ID: `29547632825`
- Artifact ID: `8394613215`
- Artifact digest: `sha256:33ee21d34ee0a71d29c5b95fb15b2ddfae6bbc04debf99baf87ef94d705d8c1b`
- Independent readiness review: `4718728084`
- Independent artifact review: `4718749284`

Exact-head prerequisite validation:

- CI #755, run `29534064680`: `PASS`
- Freqtrade Validation #490, run `29534064787`: `PASS`
- Validation-summary artifact ID: `8391614618`
- Validation-summary digest: `sha256:c70658d7bae19305f8887bf28a16d8fad6c493e02d7e0ac6b83d88839cd49668`

## Evidence integrity

The authoritative workflow and independent archive review both passed.

- All workflow steps completed successfully.
- The independently downloaded artifact ZIP matched the GitHub artifact digest.
- 198 files were retained.
- 30 effective source files were copied into the source snapshot and hash-verified.
- The exact workflow source snapshot was retained.
- All 27 hidden `.last_result.json` pointers were retained and pointed to existing exports.
- Six data-boundary cells passed.
- Six startup-coverage cells passed.
- Nine recursive/no-lookahead cells passed at startup candle count `1499`.
- Exactly 27 unique family/window/cost rows were retained.
- Every retained command, log, export, report, manifest, inventory, and snapshot hash matched.
- Final evidence reported `237` checks passed and `errors=[]`.
- The effective runtime was OKX spot dry-run, API disabled, with empty private credentials.
- No C1B confirmation window or holdout timerange was executed.

## Frozen screen

Families:

1. `C1ARegimeBreakout`
2. `C1ATrendPullback`
3. `C1ADualMomentum`

Screen windows:

- S1: `2024-01-01` to `2024-04-01`
- S2: `2024-04-01` to `2024-07-01`
- S3: `2024-07-01` to `2024-10-01`

Fee multipliers:

- `1.0x`
- `1.5x`
- `2.0x`

Expected one-side fee at `1.0x`: `0.0015`.

## Family decisions

### C1ARegimeBreakout — ineligible

- Positive windows: `1 / 3`
- Median expected-cost window return: `-4.4532%`
- Aggregate expected-cost return: `+14.8293%`
- Aggregate 1.5x-cost return: `+13.6464%`
- Aggregate expected-cost profit factor: `1.7739`
- Maximum expected-cost window drawdown: `8.3092%`
- Total trades: `26`
- Minimum trades in a window: `6`
- Positive pairs: `BTC/USDT`, `ETH/USDT`

Failed frozen gates:

- fewer than two positive windows;
- non-positive median window return;
- fewer than 30 total trades;
- maximum window profit share above 60%;
- largest positive trade share above 25%;
- top-three positive trade share above 50%.

Expected-cost window returns:

- S1: `+24.7050%`
- S2: `-4.4532%`
- S3: `-5.4224%`

### C1ATrendPullback — ineligible

- Positive windows: `1 / 3`
- Median expected-cost window return: `-6.9421%`
- Aggregate expected-cost return: `-20.3321%`
- Aggregate 1.5x-cost return: `-28.6543%`
- Aggregate expected-cost profit factor: `0.7117`
- Maximum expected-cost window drawdown: `21.1301%`
- Total trades: `185`
- Minimum trades in a window: `28`
- Positive pairs: none on aggregate

Failed frozen gates:

- fewer than two positive windows;
- non-positive median window return;
- non-positive aggregate expected-cost return;
- negative aggregate 1.5x-cost return;
- profit factor below `1.10`;
- maximum window drawdown above `15%`;
- fewer than two positive pairs;
- maximum window profit share above 60%.

Expected-cost window returns:

- S1: `+7.4984%`
- S2: `-20.8884%`
- S3: `-6.9421%`

### C1ADualMomentum — ineligible

- Positive windows: `1 / 3`
- Median expected-cost window return: `-8.6275%`
- Aggregate expected-cost return: `+7.1769%`
- Aggregate 1.5x-cost return: `+5.6843%`
- Aggregate expected-cost profit factor: `1.2360`
- Maximum expected-cost window drawdown: `12.4422%`
- Total trades: `33`
- Minimum trades in a window: `5`
- Positive pairs: `BTC/USDT`, `ETH/USDT`

Failed frozen gates:

- fewer than two positive windows;
- non-positive median window return;
- maximum pair profit share above 70%;
- maximum window profit share above 60%;
- largest positive trade share above 25%;
- top-three positive trade share above 50%.

Expected-cost window returns:

- S1: `+28.2466%`
- S2: `-12.4422%`
- S3: `-8.6275%`

## Decision

No family satisfied every frozen eligibility condition, so the eligible ranking is empty and `selected_family=null`.

The positive aggregate returns of regime breakout and dual momentum do not override the preregistered stability, breadth, trade-count, and concentration requirements. Their gains were concentrated in S1 and in a small number of trades or pairs. Trend pullback showed broader activity but failed profitability, drawdown, pair-breadth, and stress-cost requirements.

C1A is therefore frozen as `REJECTED`. The constants, gates, ranking, windows, and candidate implementations must not be modified in response to this result.

## Post-C1A state

- C1B confirmation: `CLOSED`
- Development confirmation windows C1-C3: not opened
- Holdout: `CLOSED`
- Paper trading: not authorized
- Shadow trading: not authorized
- Live trading: `FORBIDDEN`

Any future research direction must be defined as a new preregistered stage or strategy thesis rather than an in-place retuning of C1A.

`CONFIRMATION_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
