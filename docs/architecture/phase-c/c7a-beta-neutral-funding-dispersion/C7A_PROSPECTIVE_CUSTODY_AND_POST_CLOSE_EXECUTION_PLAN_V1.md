# C7A immediate validation and prospective confirmation policy V2

## 1. Correction and authority

The waiting-only interpretation previously recorded in this file is superseded.

It was incorrect to convert one prospective holdout interval into a project-wide prohibition on real public data, historical economic replay, read-only shadow observation, or further strategy development. That interpretation did not come from the product owner and conflicts with the project objective of reaching real, cost-adjusted, falsifiable evidence efficiently.

Current authority:

- immediate historical validation with official public OKX data: `AUTHORIZED`;
- immediate implementation of public-data acquisition and normalization: `AUTHORIZED`;
- read-only shadow observation after the historical pipeline passes: `AUTHORIZED`;
- parallel strategy research and system development: `AUTHORIZED`;
- private/account APIs: `FORBIDDEN` unless separately designed and approved;
- order submission and live capital: `LIVE_FORBIDDEN`.

## 2. What remains frozen

The merged C7A candidate semantics remain unchanged:

- candidate: `C7ABetaNeutralFundingDispersion`;
- instruments: `BTC-USDT-SWAP` and `ETH-USDT-SWAP`;
- 28-day funding and mark-return lookback;
- fixed beta/R-squared, projected-carry, activity, cost, risk, comparator, and concentration gates;
- producer/reviewer separation and complete evidence manifest;
- no parameter search after inspecting a scored window.

The interval from `2026-08-24T00:00:00Z` through `2027-02-22T00:00:00Z` remains a valuable prospective confirmation window. It is an additional holdout, not a blocker on current work and not the sole admissible source of evidence.

## 3. Immediate historical validation

Before downloading scored rows, the following five non-overlapping 26-week decision windows are fixed:

| Window | First scored decision | End exclusive |
| --- | --- | --- |
| `H1` | `2024-01-01T00:00:00Z` | `2024-07-01T00:00:00Z` |
| `H2` | `2024-07-01T00:00:00Z` | `2024-12-30T00:00:00Z` |
| `H3` | `2024-12-30T00:00:00Z` | `2025-06-30T00:00:00Z` |
| `H4` | `2025-06-30T00:00:00Z` | `2025-12-29T00:00:00Z` |
| `H5` | `2025-12-29T00:00:00Z` | `2026-06-29T00:00:00Z` |

Each window must contain exactly 26 Monday 00:00 UTC decisions. Its required source interval includes the complete 28-day funding lookback, 673 hourly mark closes for the first decision, and the full scored accounting interval.

The historical run must:

- use the already merged candidate and gate semantics without threshold changes;
- retrieve only official public OKX data;
- retain raw responses, normalized rows, source URLs without credentials, timestamps, hashes, and pagination provenance;
- fail closed on missing, duplicate, unordered, contradictory, non-finite, unconfirmed, or out-of-range rows;
- run the three fixed cost levels and all three preregistered comparators;
- produce per-window and pooled results without selecting the best window;
- independently recompute all aggregates and gates;
- distinguish data failure, implementation failure, and economic rejection;
- forbid retuning and rerunning the same historical windows after economic inspection.

Historical evidence is immediately decision-useful. A clear failure can reject or redesign the thesis now. A robust pass can justify read-only shadow progression now. The future prospective window remains an independent confirmation rather than an excuse to wait.

## 4. Public data authority

Permitted sources are limited to official unauthenticated OKX surfaces:

- OKX downloadable historical market-data files;
- `GET /api/v5/market/history-candles`;
- `GET /api/v5/market/history-mark-price-candles`;
- `GET /api/v5/public/funding-rate-history`.

The acquisition implementation must reject:

- API keys, passphrases, cookies, account headers, or authenticated endpoints;
- private/account/trade/order endpoints;
- undocumented mirrors, proxies, alternate exchanges, interpolation, or silent substitution;
- current instrument metadata projected backward as historical authority.

## 5. Immediate read-only shadow path

After the historical acquisition, accounting, and independent-review pipeline passes its engineering gates, C7A may enter read-only shadow observation immediately.

Shadow means:

- consume public market and funding data;
- generate and retain hypothetical decisions and accounting;
- send no order and call no private API;
- preserve deterministic risk and evidence boundaries;
- report performance and operational defects on a fixed cadence;
- remain unable to transition to live automatically.

Paper or live execution requires a separate exact-SHA design and explicit product-owner approval. Nothing in this policy authorizes real orders.

## 6. Parallel progress

C7A must not monopolize or freeze the project. While C7A historical and shadow evidence accumulates, the project may continue:

- evaluating other fixed strategy candidates;
- improving shared data quality and walk-forward tooling;
- strengthening paper/shadow runtime safety;
- reducing execution cost and operational fragility;
- building the review and strategy-evolution loop.

Work is prioritized by how much it reduces the distance to a stable, auditable, cost-adjusted positive-expectancy system—not by how many stages or documents it creates.

## 7. Current consequence

The repository is not in a waiting state.

The next work is immediate:

1. implement the fixed historical schedule and public-data boundary;
2. implement official OKX acquisition and normalization;
3. run the five preregistered historical windows once;
4. independently review the complete evidence;
5. decide whether C7A is rejected, revised under a new candidate identity, or advanced to read-only shadow;
6. continue parallel strategy and system work regardless of the 2027 confirmation window.

`C7A_IMMEDIATE_VALIDATION_AUTHORIZED` / `HISTORICAL_PUBLIC_DATA_ALLOWED` / `SHADOW_READ_ONLY_ALLOWED_AFTER_ENGINEERING_PASS` / `PROSPECTIVE_CONFIRMATION_NON_BLOCKING` / `PRIVATE_API_FORBIDDEN` / `LIVE_FORBIDDEN`
