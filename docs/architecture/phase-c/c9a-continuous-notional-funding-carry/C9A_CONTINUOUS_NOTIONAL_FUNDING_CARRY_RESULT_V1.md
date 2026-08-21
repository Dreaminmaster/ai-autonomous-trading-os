# C9A Continuous-Notional Funding Carry — Authoritative Result V1

## 1. Final classification

C9A completed official-public OKX source custody, strict normalization, all five frozen historical replays, cost and funding accounting, and a separately implemented independent recomputation. The data and program succeeded; the single preregistered candidate failed seven unchanged economic gates.

- Stage: `C9A_W1_W5_FINAL_CLASSIFICATION`
- Classification: `ECONOMIC_FAIL`
- Status: `FAIL`
- Data custody: `PASS`
- Independent recomputation: `PASS`
- Best-window selection: `NOT_PERFORMED`
- Retuning: `NOT_AUTHORIZED`
- Rerun after economic inspection: `NOT_AUTHORIZED`
- Execution feasibility: `NOT_ESTABLISHED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This is not a data failure or program failure. The candidate remained positive after the expected and stressed cost schedules, but it did not satisfy the frozen all-gates rule and did not beat the fixed continuous always-on comparator. C9A must not be tuned, rerun, or promoted in response to the observed W1–W5 economics.

## 2. Exact implementation and run authority

- Repository: `Dreaminmaster/ai-autonomous-trading-os`
- Implementation commit: `883824b418d24c926423d2902681a9cf84006a26`
- Implementation PR: `#113`
- Authoritative workflow run: `32446134777`
- C9A authority job: `96665935258`
- Workflow URL: <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32446134777>
- Authority job URL: <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32446134777/job/96665935258>

The retained capture and evaluation checkout bindings both record the requested implementation SHA and observed repository head as the same exact commit, with a clean tracked worktree. The authority job started at `2026-08-21T04:12:53Z`, captured public source responses from `04:13:11Z` through `04:19:08Z`, completed evaluation and independent recomputation at `04:19:10Z`, uploaded the artifact, and completed successfully at `04:19:54Z`.

The authority job success means the capture, validation, replay, independent recomputation, and immutable upload completed. The evaluator returned its documented exit code `1` for a valid `ECONOMIC_FAIL`; the workflow accepts only exit codes `0` and `1` and would fail on data or program exit codes `2` or higher. The same dispatch's ATOS test job `96665935200` also succeeded.

## 3. Immutable source and evidence custody

The authoritative artifact is:

- Artifact ID: `9434241599`
- Name: `c9a-w1-w5-authority-883824b418d24c926423d2902681a9cf84006a26`
- GitHub ZIP digest: `sha256:69ba943583699636dde16d82ac8306108750b9e58810c415cd80e0e83c881175`
- ZIP size: `37,810,878` bytes
- Created: `2026-08-21T04:19:52Z`
- Scheduled expiry: `2026-09-20T04:19:47Z`

Independent download and archive verification established:

- the downloaded ZIP independently hashed to the exact GitHub digest and passed full ZIP integrity testing;
- archive inventory: `831` files;
- capture manifest: `810 / 810` files matched exact path, size, and SHA-256, with zero missing, extra, duplicate, or mismatched entries;
- evidence manifest: `17 / 17` files matched exact path, size, and SHA-256, with zero missing, extra, duplicate, or mismatched entries;
- capture manifest SHA-256: `84e967a69aa34bee360719d0ecfe066571f7e35293fd6085346e0968a0c27f2a`;
- capture index SHA-256: `e7f65827935ff7be4627e5b22935cef242aac5c310b729c8c7e24b971606e033`;
- capture checkout binding SHA-256: `907bd1e152fd257b44703975e1a4fc2a189229963e0002b12427ea85acc3173e`;
- evidence manifest SHA-256: `6aa9256406b87627b12c759b96d87447c685dbc2b267cc3a5ae03f5e353bb398`;
- final classification SHA-256: `5acce80c7138bf6fad729b0765605180a7d2425bd28cac5d14f68d9813188a7a`;
- pooled summary SHA-256: `3388b1665859c7c185371c82b616bded59d4b003724c547a4fd1ce726ec27752`;
- pooled independent review SHA-256: `b9a5bf257853532ca0f6ef468623cb6fb87390755cc0e7bffbf7b011818e304e`;
- all `20 / 20` authority source paths matched the exact size and SHA-256 of their Git objects at the implementation commit.

The capture retained `800` official response records: `438` mark-price candle API responses, `292` trade-candle API responses, `8` historical-download manifest responses, and `62` historical funding-download files. All request IDs and raw paths were unique. Requested and final URLs matched for every response, every response used an allowed official OKX host/path/query contract, and no retry was required.

The package records `source_kind=OFFICIAL_PUBLIC_OKX`, `authenticated=false`, `private_api=false`, `contains_account_data=false`, `contains_order_data=false`, `paper_side_effect=false`, `shadow_side_effect=false`, and `live_state=LIVE_FORBIDDEN`.

## 4. Strict normalized coverage

The normalized datasets contain:

| Data family | Instrument | Rows | First retained timestamp | Last retained timestamp |
|---|---|---:|---|---|
| Hourly mark candles | `BTC-USDT-SWAP` | `21,842` | `2023-07-02T22:00:00Z` | `2025-12-28T23:00:00Z` |
| Hourly mark candles | `ETH-USDT-SWAP` | `21,842` | `2023-07-02T22:00:00Z` | `2025-12-28T23:00:00Z` |
| Hourly trade candles | `BTC-USDT` | `21,843` | `2023-07-02T22:00:00Z` | `2025-12-29T00:00:00Z` |
| Hourly trade candles | `ETH-USDT` | `21,843` | `2023-07-02T22:00:00Z` | `2025-12-29T00:00:00Z` |
| Hourly trade candles | `BTC-USDT-SWAP` | `21,843` | `2023-07-02T22:00:00Z` | `2025-12-29T00:00:00Z` |
| Hourly trade candles | `ETH-USDT-SWAP` | `21,843` | `2023-07-02T22:00:00Z` | `2025-12-29T00:00:00Z` |
| Funding settlements | `BTC-USDT-SWAP` | `2,814` | `2023-06-05T00:00:00Z` | `2025-12-28T16:00:00Z` |
| Funding settlements | `ETH-USDT-SWAP` | `2,814` | `2023-06-05T00:00:00Z` | `2025-12-28T16:00:00Z` |

Independent sequence checks found zero duplicate, unordered, missing-hour, non-positive-price, or non-numeric-rate records. BTC funding settlements were exactly eight hours apart. ETH settlement timestamps retained the official files' one-to-three-second timing jitter around the eight-hour schedule; there was no missing settlement interval.

## 5. Frozen window results at expected cost

Every window started independently at equity `1000`, contained exactly `26` scored weeks, and passed its source-level independent review. No state crossed between windows.

| Window | Start inclusive | End exclusive | Candidate return | Always-on return | Spot buy-and-hold return | Candidate max drawdown | Active weeks | Active funding settlements |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `W1` | `2023-07-03T00:00:00Z` | `2024-01-01T00:00:00Z` | `0.005520111085961669727399772` | `0.011709464559353772918666939` | `0.27564943121176635257714781` | `0.0010496041285138369041746889` | `6` | `250` |
| `W2` | `2024-01-01T00:00:00Z` | `2024-07-01T00:00:00Z` | `0.012207492361214628527989308` | `0.023455178445388775634157877` | `0.491067293324194070288754562` | `0.0028052255883609060142170437` | `17` | `547` |
| `W3` | `2024-07-01T00:00:00Z` | `2024-12-30T00:00:00Z` | `0.004797472201672689323142439` | `0.012830246792771676106027776` | `0.231038147298048288750955006` | `0.0012984277486483977209521353` | `6` | `250` |
| `W4` | `2024-12-30T00:00:00Z` | `2025-06-30T00:00:00Z` | `-0.0013862048697912877512796999` | `0.002975964999637843707907353` | `-0.0523361750911346729000011926` | `0.0013862048697912877512796999` | `2` | `21` |
| `W5` | `2025-06-30T00:00:00Z` | `2025-12-29T00:00:00Z` | `0` | `0.004842886364676047325326733` | `-0.0070855767611075353587846292` | `0` | `0` | `0` |

The candidate generated no eligible position in W5. That zero-activity window is retained as a frozen adverse result and cannot be removed or reinterpreted after inspection.

## 6. Pooled economics and fixed comparators

| Policy / cost | Pooled return | Annualized weekly Sharpe | PSR vs zero | Maximum drawdown | Annualized paired one-way turnover | Active weeks | Funding settlements |
|---|---:|---:|---:|---:|---:|---:|---:|
| Candidate `1.0x` | `0.004227774155811539965450364` | `1.830825051210025` | `0.9999613759238298` | `0.0028052255883609060142170437` | `1.833299288775622233485169717` | `31` | `1068` |
| Candidate `1.5x` | `0.002843342741675774840455383` | `1.1994866924823762` | `0.9818405918663136` | `0.0043180250062670568368501618` | `1.833348442727285388468274886` | `31` | `1068` |
| Candidate `2.0x` | `0.001461568080637583357958989` | `0.5731003396833055` | `0.8185811112138123` | `0.0058520723603655956555967014` | `1.833396236531714203106934698` | `31` | `1068` |
| Always-on `1.0x` | `0.011162748232365623138417336` | `4.206267096567144` | `1.0` | `0.0012380718527432313851357125` | `2.034948638204199068906206516` | `130` | `5443` |
| Spot buy-and-hold `1.0x` | `0.187666623996353300671614311` | `0.879565267179406` | `0.9198102166096351` | `0.4428480857321214459067101180` | `0` | — | — |

At expected cost, candidate funding receipts covered total trading costs by `2.579942629964497942516367441`. BTC contributed `12.90925571506988295776905201` and ETH contributed `8.229615063987816869482766518`. Base-hedge mismatches, reconciliation failures, missing decisions, unaccounted funding settlements, non-finite states, non-positive equity states, and candidate collateral-buffer breaches were all zero.

## 7. Unchanged gate decision

Exactly seven preregistered gates failed:

| Gate | Frozen requirement | Observed | Result |
|---|---:|---:|---|
| Every window positive | all five `> 0` | W4 negative; W5 zero | `FAIL` |
| Active weeks total | `>= 52` | `31` | `FAIL` |
| Active weeks per window | `>= 6` | W4 `2`; W5 `0` | `FAIL` |
| Positive-window PnL concentration | `<= 0.40` | `0.541951225892483` | `FAIL` |
| Return versus always-on | candidate `>=` always-on | `0.00422777415581154 < 0.01116274823236562` | `FAIL` |
| Sharpe delta versus always-on | `>= 0.10` | `1.830825051210025 - 4.206267096567144` | `FAIL` |
| Drawdown versus always-on | candidate `<=` always-on | `0.002805225588360906 > 0.001238071852743231` | `FAIL` |

All other frozen return, cost-stress, Sharpe, PSR, absolute drawdown, turnover, funding-coverage, activity, attribution, week concentration, accounting, and numerical-safety gates passed. The contract requires every gate to pass, so the only valid classification is `ECONOMIC_FAIL`.

## 8. Independent recomputation and post-download audit

Each of W1–W5 contains six candidate/always-on replay reviews and six fixed comparator checks. All `30 / 30` replay reviews and `30 / 30` comparator checks passed, with zero false subchecks. The independent implementation records `imports_production_replay=false`, `imports_production_policy=false`, and `imports_production_metric_or_gate=false`. The pooled independent review separately matched all pooled metrics, all gate decisions, and `reference_final_verdict=ECONOMIC_FAIL`.

A second local evaluation over the downloaded immutable capture returned the documented exit code `1`, reproduced `ECONOMIC_FAIL`, and emitted a byte-identical final-classification file. Fifteen of sixteen time-independent evidence files were byte-identical. The only cross-platform difference was one binary floating-point least-significant digit in the spot buy-and-hold `2.0x` PSR (`0.9168751627277405` on the authority runner and `0.9168751627277406` locally), a difference of `1e-16`, far below the frozen `1e-10` numerical tolerance. It changed no metric gate, independent review status, or final classification.

## 9. Interpretation and closed actions

C9A demonstrated a small positive historical return after the frozen costs, positive funding-cost coverage, high absolute PSR at expected cost, and mechanically sound delta-neutral accounting. It nevertheless traded in only 31 of 130 weeks, was inactive throughout W5, lost money in W4, concentrated more than half of positive window PnL in W2, and materially underperformed the fixed always-on carry comparator on return, Sharpe, and drawdown.

The following actions are closed:

1. rerunning C9A on W1–W5 after observing these results;
2. tuning its funding threshold, lookback, basis filters, resizing band, allocation, costs, assets, or gates;
3. weakening activity, window, comparator, concentration, or drawdown requirements;
4. dropping W4, W5, ETH at the `2.0x` stress cost, or any adverse week;
5. describing C9A as selected, validated edge, execution-feasible, Paper-ready, or Shadow-ready;
6. opening C9B, Paper, Shadow, account access, order access, derivatives execution, or Live for C9A.

The one-time C9A dispatch input and authority job are removed in this closeout change. Any further historical research must be a separately preregistered and structurally distinct candidate that discloses the complete prior Phase C program history; it cannot be a renamed C9A retune.

## 10. Final state

`C9A_W1_W5_COMPLETE`

`C9A_ECONOMIC_FAIL`

`HISTORICAL_ECONOMIC_PASS_FALSE`

`RETUNING_NOT_AUTHORIZED`

`RERUN_AFTER_INSPECTION_NOT_AUTHORIZED`

`C9B_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
