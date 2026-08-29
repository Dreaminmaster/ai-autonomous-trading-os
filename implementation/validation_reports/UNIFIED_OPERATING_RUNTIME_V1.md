# Unified Operating Runtime V1 — Validation Report

## Result

**PASS for account-free Paper and read-only public-data Shadow operation.**

This result is an engineering/safety acceptance result. It is not evidence of
strategy profitability and does not authorize Live trading.

## Delivered execution path

```text
official OKX public market data or caller-supplied history
  -> strict snapshot and freshness validation
  -> deterministic strategy plugin registry
  -> structured provider result
  -> TradeIntent model and JSON-schema validation
  -> deterministic RiskEngine
  -> immutable RuntimeDatabase decision graph
  -> B5 execution idempotency claim
  -> deterministic Paper/Shadow simulated fill
  -> atomic fill and position accounting
  -> SQLite audit ledger
```

## Safety boundaries

- `live` is rejected during runtime construction, before market access.
- The public adapter exposes only allowlisted OKX public HTTPS GET endpoints.
- It has no account, credential, private API, transfer, withdrawal, or order
  method.
- Request redirects, malformed OKX envelopes, unconfirmed/duplicate/unsorted
  candles, ticker identity drift, and malformed/crossed order books fail closed.
- Strategy plugin exceptions are isolated; the HOLD baseline remains present.
- Invalid provider output is corrected to a schema-valid HOLD.
- Every intent passes deterministic risk checks.
- HOLD and rejected decisions create no execution intent, order, fill, or
  position side effect.
- Paper and Shadow execution are durable and replay-safe. Identical cycle
  replay is a terminal no-op.
- Durable open positions, net realized PnL, fees, current-symbol unrealized
  PnL, drawdown, and prospective gross/symbol exposure feed every new risk
  decision and survive process restarts.
- Startup detects incomplete durable cycles/executions and pauses new simulated
  execution with `RECOVERY_REQUIRED`; it never guesses or reconciles externally.
- Any simulated executor failure returns an audited HOLD/no-trade result.

## Verification

- Full pytest after all runtime, persistence, portfolio-risk, and recovery
  additions: `1624 passed, 7 skipped`.
- Focused snapshot/runtime/lifecycle regression after the additions:
  `116 passed`.
- Durable runtime/idempotency/lifecycle regression: `119 passed`.
- Ruff check and format check: PASS.
- All 6 workflow YAML files parsed: PASS.
- Repository secret-leakage scan: PASS.
- `git diff --check`: PASS.

## Official public-data Shadow smoke

One manual smoke used `BTC-USDT`, OKX official public endpoints, mode
`shadow`, one loop, and the default 1% simulated position limit.

- final status: `SHADOW_SIMULATED`
- Live: `FORBIDDEN`
- account access: none
- private API: none
- order submission: none
- durable outcome: `FILLED` (simulated only)
- persisted authority: one session, cycle, trade intent, risk decision,
  execution intent, idempotency claim, simulated order, simulated fill, and
  simulated position
- persisted venue/scope: `okx_shadow` / `simulated`

## Remaining product work

1. Add an operator-controlled recovery command for incomplete durable cycles;
   automatic external reconciliation remains forbidden.
2. Add a long-running read-only Shadow supervisor with health, liveness,
   graceful shutdown, and operational reports.
3. Connect review/strategy-weight updates to durable closed-position outcomes
   through an approved, bounded update mechanism.
4. Validate candidate strategies independently. Only an economic PASS may be
   promoted into Shadow; failed candidates remain closed.

Live execution remains outside this milestone and is physically unconnected.
