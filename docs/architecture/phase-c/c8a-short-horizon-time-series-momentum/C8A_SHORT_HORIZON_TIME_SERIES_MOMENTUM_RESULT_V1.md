# C8A Short-Horizon Time-Series Momentum — Authoritative Result V1

## 1. Final classification

C8A completed official-public OKX source custody, strict normalization, all five frozen historical replays, cost and funding accounting, and a physically separate independent recomputation. The data and program succeeded; the frozen strategy failed five unchanged economic gates.

- Stage: `C8A_H1_H5_FINAL_CLASSIFICATION`
- Classification: `ECONOMIC_FAIL`
- Status: `FAIL`
- Data custody: `PASS`
- Independent recomputation: `PASS`
- Best-window selection: `NOT_PERFORMED`
- Retuning: `NOT_AUTHORIZED`
- Rerun after economic inspection: `NOT_AUTHORIZED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This is not a data failure or implementation failure. Positive returns and comparator outperformance do not override the preregistered all-gates requirement. C8A must not be tuned, rerun, or promoted in response to the observed H1–H5 economics.

## 2. Exact implementation and run authority

- Repository: `Dreaminmaster/ai-autonomous-trading-os`
- Implementation commit: `f37125f83ef6d35923bbd0a41f6d750e9d40e396`
- Authoritative workflow run: `32426312094`
- C8A authority job: `96608863918`
- Workflow URL: <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32426312094>
- Authority job URL: <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32426312094/job/96608863918>

The retained checkout bindings independently record the requested implementation SHA and observed repository head as the same exact commit, with a clean tracked worktree. The capture ran from `2026-08-20T22:54:14Z` through `22:59:26Z`; evaluation and independent recomputation completed at `22:59:55Z`; artifact upload completed before final classification enforcement.

The authority job conclusion is `failure` by design: capture exited `0`, while the evaluator exited `1` after writing a valid `ECONOMIC_FAIL`, and the final enforcement step rejected every non-`ECONOMIC_PASS` classification. The same dispatch's ATOS test job `96608863766` succeeded. Its ordinary Freqtrade job `96608863892` was cancelled only after the authoritative evidence was safely uploaded, because exact implementation SHA Freqtrade Validation run `32379506421` and CI run `32379506673` had already passed for PR #110.

## 3. Immutable source and evidence custody

The authoritative artifact is:

- Artifact ID: `9427676298`
- Name: `c8a-h1-h5-authoritative-32426312094`
- GitHub ZIP digest: `sha256:d669ac623ce7bf05b356e8d872a878b3b65dc36ef3a454171604bdb9a7798337`
- Created: `2026-08-20T22:59:59Z`
- Scheduled expiry: `2026-11-18T22:53:52Z`

Independent download and archive verification established:

- the downloaded ZIP independently hashed to the exact GitHub digest;
- capture manifest: `664 / 664` files matched exact size and SHA-256;
- evidence manifest: `17 / 17` files matched exact size and SHA-256;
- capture manifest file SHA-256: `7353c6a8004786acc091f29fafa4af87f5249b7cb970c927e4e024986ba55efe`;
- evidence manifest file SHA-256: `e26b8e103b6659f007da002c192a462659860c3b0c90f1b6f6e654779d573136`;
- source kind: `OFFICIAL_PUBLIC_OKX`;
- authenticated, private, account, and order access: `false`;
- Paper and Shadow side effects: `false`;
- Live state: `LIVE_FORBIDDEN`.

The capture index retained `656` response records: `442` mark-price candle API responses, `146` trade-candle API responses, `8` historical-data manifest responses, and `60` historical downloads. No retry was needed in the successful run. Every request and final URL, response byte length, media type, raw-response SHA-256, and retry provenance is retained.

Strict normalization produced:

| Data family | `BTC-USDT-SWAP` rows | `ETH-USDT-SWAP` rows |
|---|---:|---:|
| Hourly mark candles | `22,010` | `22,010` |
| Hourly trade candles | `21,841` | `21,841` |
| Funding settlements | `2,731` | `2,731` |

## 4. Frozen window results at expected cost

Every window started independently at equity `1.0`, held exactly `26` weekly decisions, and passed its source-level independent review. No state crossed between windows.

| Window | Start inclusive | End exclusive | Candidate net return | Always-long net return | Candidate max drawdown | Margin breaches |
|---|---|---|---:|---:|---:|---:|
| `H1` | `2024-01-01T00:00:00Z` | `2024-07-01T00:00:00Z` | `0.11926089023071507` | `0.19935292530203474` | `0.11428684245090402` | `0` |
| `H2` | `2024-07-01T00:00:00Z` | `2024-12-30T00:00:00Z` | `0.11724441401895014` | `0.10418569677246681` | `0.11197633210460507` | `1` |
| `H3` | `2024-12-30T00:00:00Z` | `2025-06-30T00:00:00Z` | `0.026898269635529104` | `-0.02203377743249746` | `0.11022882321575189` | `0` |
| `H4` | `2025-06-30T00:00:00Z` | `2025-12-29T00:00:00Z` | `0.038694539410528694` | `-0.002351191318040402` | `0.20260429417404138` | `0` |
| `H5` | `2025-12-29T00:00:00Z` | `2026-06-29T00:00:00Z` | `0.1798004099195416` | `-0.2172609508916481` | `0.13630626832314122` | `0` |

All five candidate windows were positive. The single margin-buffer breach occurred for `ETH-USDT-SWAP` at `2024-11-09T23:00:00Z` in H2; the retained sleeve buffer was `1.2324203060768169`. It was not discarded or excused.

## 5. Pooled economics and fixed comparator

| Policy / cost | Pooled net return | Annualized weekly Sharpe | PSR vs zero | Maximum window drawdown | Annualized one-way turnover | Margin breaches |
|---|---:|---:|---:|---:|---:|---:|
| Candidate `1.0x` | `0.573632563333969` | `0.895499731743871` | `0.9286912574078495` | `0.20260429417404138` | `27.85575291880607` | `1` |
| Candidate `1.5x` | `0.49350697592094517` | `0.8055995530791635` | `0.9056735504115654` | `0.2081767529567245` | `27.847883957724882` | `1` |
| Candidate `2.0x` | `0.41745886191403914` | `0.7155745584950086` | `0.8777180693962261` | `0.2137105868287243` | `27.840021096662532` | `1` |
| Always-long `1.0x` | `0.0113643937130401` | `0.14716434427031624` | `0.5919645091294627` | `0.27053822453692794` | `2.8797219539829535` | `0` |
| Always-long `1.5x` | `0.005917194003786541` | `0.13898074757179418` | `0.58691932179797` | `0.27071143840522816` | `2.8794284256474683` | `0` |
| Always-long `2.0x` | `0.0004993431618107724` | `0.13079803308979016` | `0.5818619488368925` | `0.2708845734293345` | `2.8791353695853465` | `0` |

At expected cost, BTC contributed `0.22695623557335173` and ETH contributed `0.2549422876419013`. Strategy beta to BTC was `-0.04159765295917239`; all `260` instrument-week directions were non-flat; missing decisions and unaccounted funding settlements were both zero.

Concentration gates also passed:

- maximum positive-instrument share: `0.5290372876449435`;
- maximum positive-window share: `0.3731084476455732`;
- maximum positive-week share: `0.06666732215089784`;
- top-three positive-week share: `0.1540307783575839`.

## 6. Unchanged gate decision

Exactly five preregistered gates failed:

| Gate | Frozen requirement | Observed | Result |
|---|---:|---:|---|
| Annualized weekly Sharpe | `>= 1.00` | `0.895499731743871` | `FAIL` |
| Weekly PSR vs zero | `>= 0.95` | `0.9286912574078495` | `FAIL` |
| Maximum drawdown in every window | `<= 0.15` | `0.20260429417404138` | `FAIL` |
| Annualized one-way turnover | `<= 26.0x` | `27.85575291880607` | `FAIL` |
| Margin-buffer breach count | `= 0` | `1` | `FAIL` |

Every other frozen economics, cost-sensitivity, stability, beta, activity, attribution, concentration, comparator, completeness, and funding-accounting gate passed. The contract requires all gates to pass, so the only valid classification is `ECONOMIC_FAIL`.

## 7. Independent recomputation

Each of H1–H5 has a physically separate independent review with `status=PASS`, no errors, a source-derived signal recomputation pass, and `imports_production_replay=false`. The pooled independent review separately recomputed and matched:

- all three candidate and comparator cost replays;
- weekly statistics, PSR, beta, window and pooled returns;
- drawdown, turnover, attribution, concentration, and accounting counts;
- every frozen gate and the final economic verdict.

The audit also independently verified exact manifest inventory, file size, and SHA-256 for both the source package and result package. There was no best-window selection, within-stage candidate count was exactly one, and the evidence explicitly records that the broader sequential Phase C history is not corrected by C8A's PSR.

## 8. Pre-economic infrastructure attempts

Two earlier dispatches failed before producing any economic result. They are retained as infrastructure/data provenance, not competing strategy trials:

| Run | Exact implementation SHA | Failure class | Cause | Artifact ID | Artifact ZIP digest |
|---:|---|---|---|---:|---|
| `32349256527` | `30df169ddd74de12b6029dee53072244dc9635ad` | `DATA_FAILURE` | OKX historical-download manifest rejected a ten-month inclusive range with HTTP `400`; the corrected public limit is nine UTC months | `9399327958` | `sha256:3e57ecf2e4427284d68bb2f1c21b902b6879e0b0d16ff7ae60b332ff00848bfe` |
| `32378162784` | `8739402d4d5ce8440d4b0bdb11c2f9608ca5efa6` | `DATA_FAILURE` | Official-public OKX funding-manifest request returned HTTP `429`; bounded idempotent retry and pacing were added | `9410040265` | `sha256:7a3c1033517b8f37e8937e9653c796924661c0d6b2c79d32ef763a22668b8fea` |

Neither failed attempt reached economic evaluation, exposed window performance, or authorized parameter changes. The remediations changed only public-data transport and source pagination behavior. They did not alter the frozen C8A signal, costs, sizing, comparator, statistics, windows, or economic gates.

## 9. Interpretation and closed actions

C8A supplied economically meaningful positive historical returns after the frozen cost schedule and materially beat the fixed always-long comparator. It nevertheless did not provide the complete preregistered evidence required for selection: risk-adjusted performance was below threshold, H4 drawdown was too large, turnover exceeded its cap, and one margin-buffer breach occurred.

The following actions are closed:

1. rerunning C8A on H1–H5 after observing these results;
2. tuning its signal horizon, rebalance time, sizing, leverage, costs, or instruments;
3. weakening the Sharpe, PSR, drawdown, turnover, or margin gate;
4. dropping H2, H4, the ETH breach, or any adverse week;
5. describing C8A as selected, validated edge, Paper-ready, or Shadow-ready;
6. opening C8B, Paper, Shadow, account access, order access, or Live for C8A.

The one-time C8A dispatch input and authority job are removed in the closeout change. Any further historical research must be a separately preregistered and structurally distinct candidate that discloses C8A as prior program history; it cannot be a renamed C8A retune.

## 10. Final state

`C8A_H1_H5_COMPLETE`

`C8A_ECONOMIC_FAIL`

`HISTORICAL_ECONOMIC_PASS_FALSE`

`RETUNING_NOT_AUTHORIZED`

`RERUN_AFTER_INSPECTION_NOT_AUTHORIZED`

`C8B_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
