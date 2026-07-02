# Product Completion Checklist

This file defines what is still needed before the repository becomes a complete autonomous trading OS product.

## Current repository status

Already present:

- system specification documents
- JSON schemas
- config examples
- runnable implementation directory
- core state and models
- strategy candidate layer
- mock decision layer
- provider layer foundation
- deterministic risk engine
- simulated execution engine
- ledger store
- public market data adapter foundation
- historical timeline replay foundation
- review layer foundation
- CLI commands
- basic tests

Current state: runnable scaffold, not complete product.

## Architecture rule

Harness is the setup and operator assistant. The trading OS must have its own runtime brain.

Runtime flow:

```text
operator or scheduler
  -> market data adapter
  -> feature builder
  -> strategy pool
  -> provider manager
  -> decision layer
  -> trade intent validation
  -> deterministic risk engine
  -> executor
  -> ledger database
  -> review layer
  -> dashboard
```

## 1. Source architecture cleanup

Target:

```text
implementation/src/atos/
  cli/
  config/
  data/
  features/
  strategies/
  providers/
  decision/
  risk/
  execution/
  ledger/
  replay/
  review/
  dashboard/
  governance/
```

Done when:

- package imports work cleanly
- command line entrypoint works after install
- no manual path hacks are needed
- tests run from repository root

## 2. Provider manager

Needed:

- base provider interface
- mock provider
- DeepSeek provider
- Anges provider
- provider selection manager
- manual provider preference parser
- JSON output enforcement

Done when:

- default provider works
- configured provider can be selected
- provider failure produces HOLD for decision tasks
- autonomous runtime can call provider without Harness chat

## 3. Public market data

Needed:

- ticker
- candles
- orderbook
- trades
- funding rate
- open interest
- instrument metadata
- local cache
- freshness checks
- data quality checks

Done when:

- BTC-USDT ticker, candles, and orderbook can be fetched
- stale data is rejected
- OKX fields are normalized into internal models
- public data does not need account credentials

## 4. Account read-only adapter

Needed:

- balance snapshots
- position snapshots
- past orders
- past fills
- account status
- permission status when available

Done when:

- read-only inspection works
- no execution action is exposed through this adapter
- account snapshots are written without private credential material

## 5. Execution layer

Needed:

- simulated executor complete
- shadow executor
- guarded exchange executor
- order manager
- position manager
- reconciliation
- idempotency keys
- partial fill handling
- fee handling
- slippage model

Done when:

- simulated mode can run continuously
- shadow mode uses live market data with simulated orders
- guarded exchange path is off by default
- reconciliation mismatch pauses new actions
- duplicate order id is blocked

## 6. Strategy pool

Needed:

- trend following
- mean reversion
- breakout
- range/grid
- volatility breakout
- funding/basis
- orderbook imbalance
- momentum reversal
- AI discretionary
- on-chain interface
- news/sentiment interface

Done when:

- each strategy outputs StrategyCandidate
- no strategy executes directly
- strategies can be enabled or disabled through config
- strategy candidates include risk notes and regime tags

## 7. Historical timeline replay and backtest

Needed:

- historical data loader
- chronological replay
- backtest runner
- fee model
- slippage model
- metrics
- walk-forward evaluation
- out-of-sample split
- Monte Carlo analysis
- anti-lookahead checks

Done when:

- at time T, only data available at T is visible
- strategy and decision layers run through historical frames
- report includes PnL, drawdown, win rate, fees, and turnover
- strategy promotion requires validation evidence

## 8. Review and strategy evolution

Needed:

- per-trade review
- daily review
- weekly review
- monthly review
- strategy score table
- strategy weight manager
- lesson memory
- candidate strategy queue

Done when:

- review reads actual ledger data
- strategy scores update with bounded changes
- weak strategies can be paused
- AI can propose improvements but cannot directly change risk policy

## 9. Database schema

Needed tables:

- market_candles
- market_snapshots
- strategy_candidates
- trade_intents
- risk_decisions
- orders
- fills
- positions
- account_snapshots
- provider_calls
- reviews
- strategy_scores
- incidents
- config_versions

Done when:

- migrations are versioned
- no private credentials are stored
- every decision can be reconstructed
- dashboard can query system state from database

## 10. Dashboard UI

Needed views:

- system status
- mode status
- provider status
- market status
- strategy candidates
- trade intents
- risk decisions
- simulated/execution records
- positions
- PnL curve
- review reports
- strategy weights
- incidents
- emergency stop state

Done when:

- local web dashboard runs
- read-only by default
- control actions require explicit confirmation
- no private credential values are displayed

## 11. Automation runtime

Needed:

- scheduler
- run loop
- market polling
- decision cadence
- retry policy
- provider failure handling
- pause and resume
- incident handling

Done when:

- system can run simulated loop without Harness
- every loop writes ledger records
- data/provider/risk failure becomes HOLD or pause

## 12. Tests and CI

Needed tests:

- schema validation
- provider fallback
- risk engine
- simulated executor
- ledger
- market adapter mock
- historical replay
- anti-lookahead
- review scoring
- dashboard smoke
- no credential leakage
- guarded execution off by default

Done when:

- local pytest passes
- CI runs tests
- tests require no real account credentials
- safety checks fail if guarded execution is enabled by default

## Final product definition

The project is complete when it can:

1. install locally
2. run simulated mode continuously
3. fetch public market data
4. inspect account state in read-only mode
5. call configured AI providers without per-trade Harness involvement
6. produce structured trade intents
7. pass every intent through deterministic risk checks
8. record all decisions and results
9. replay historical data
10. review outcomes and update strategy scores
11. show state in a dashboard
12. pass tests and safety gates
13. keep guarded exchange execution off until local configuration explicitly enables it
