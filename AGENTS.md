# AGENTS.md

This file is the primary instruction document for any implementation agent working on this repository.

## Mission

Implement an OKX AI Autonomous Trading OS from this specification. The system should allow AI to analyze markets, select strategies, generate structured trade intents, review outcomes, and adjust strategy weights. It must not allow unconstrained LLM-driven exchange control.

## Hard safety rules

1. Do not place live orders during design, scaffold, tests, or MVP setup.
2. Do not call real OKX order endpoints unless the user explicitly enables live mode in a later phase.
3. Do not use or request OKX API keys with withdrawal permissions.
4. Do not store API keys in code, Git, logs, prompts, reports, SQLite, or test fixtures.
5. Do not print API keys or secrets.
6. Do not allow the LLM to call OKX directly.
7. All AI outputs that could lead to trading must be structured JSON and schema-validated.
8. All trade intents must pass deterministic Python risk checks.
9. If model/provider/key/risk/data validation fails, default to HOLD / no trade.
10. Keep paper trading and live trading clearly separated.

## Required execution path

```text
market/account data
  -> feature builder
  -> strategy candidates
  -> AI decision layer
  -> trade_intent.schema.json validation
  -> risk_manager.py deterministic checks
  -> execution adapter: paper first, live only when explicitly enabled
  -> ledger/audit log
  -> review/strategy evolution
```

## Implementation priority

Build in this order:

1. Project scaffold and configuration system.
2. Data models and database schema.
3. JSON schemas and validators.
4. Paper trading execution engine.
5. Deterministic risk manager.
6. Strategy registry and baseline strategies.
7. AI decision interface with mock provider first.
8. Backtest and historical replay.
9. Review engine and strategy score updates.
10. OKX read-only data adapter.
11. OKX live execution adapter, disabled by default.

## Mode separation

The implementation must support explicit modes:

- `design`: docs and planning only.
- `backtest`: historical replay only.
- `paper`: simulated execution only.
- `shadow`: observes live market and creates simulated decisions.
- `live`: real orders; disabled by default and requires explicit user enablement.

Default mode: `paper` or `design`, never `live`.

## AI autonomy boundary

The AI may:

- analyze market state,
- rank strategies,
- output BUY / SELL / HOLD intent,
- propose position size,
- propose stop loss and take profit,
- review past decisions,
- update strategy weights through approved mechanisms.

The AI must not:

- bypass schema validation,
- bypass risk checks,
- change risk limits without approval,
- enable live trading,
- enable leverage or derivatives,
- move funds,
- withdraw funds,
- hide or delete logs.

## Acceptance condition

A phase is not complete until it has:

- tests,
- logs,
- a report,
- deterministic safety behavior,
- no secret leakage,
- and a clear pass/fail summary.
