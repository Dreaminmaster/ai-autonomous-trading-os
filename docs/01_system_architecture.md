# 01 System Architecture

## High-level architecture

```text
+------------------+
|   Data Layer     |
+---------+--------+
          |
          v
+------------------+      +------------------+
|  Feature Builder | ---> |  Memory Layer    |
+---------+--------+      +------------------+
          |
          v
+------------------+
| Strategy Layer   |
+---------+--------+
          |
          v
+------------------+      +------------------+
| AI Decision Layer| ---> | Counter-Argument |
+---------+--------+      | / Risk Reviewer  |
          |               +------------------+
          v
+------------------+
| JSON Validation  |
+---------+--------+
          |
          v
+------------------+
| Risk Layer       |
+---------+--------+
          |
          v
+------------------+
| Execution Layer  |
+---------+--------+
          |
          v
+------------------+
| Ledger / Audit   |
+---------+--------+
          |
          v
+------------------+
| Review Layer     |
+---------+--------+
          |
          v
+------------------+
| Strategy Weights |
+------------------+
```

## Data Layer

Sources:

- OKX tickers
- OHLCV candles
- orderbook snapshots
- public trades
- funding rates
- open interest
- account balances, read-only
- historical orders, read-only
- volatility estimates
- optional on-chain data
- optional social/news sentiment

Data must be timestamped and point-in-time.

## Memory Layer

The system needs two forms of memory:

1. **Operational memory**: positions, orders, balances, strategy weights, risk state.
2. **Learning memory**: trade thesis, result, review, lessons, regime performance.

Memory must not create future leakage in backtests.

## Strategy Layer

Strategies are pluggable modules. Each strategy emits a candidate signal, not a direct order.

Candidate signal fields:

- symbol
- side
- timeframe
- signal strength
- entry condition
- exit condition
- risk estimate
- feature evidence
- confidence estimate

## AI Decision Layer

The AI receives:

- current market state,
- strategy candidates,
- recent memory,
- risk limits,
- portfolio state,
- relevant review lessons.

It emits `trade_intent` JSON only.

## Risk Layer

The risk layer is deterministic Python. It has absolute veto power.

It checks:

- mode,
- schema validity,
- permissions,
- symbol whitelist,
- max position size,
- max single trade risk,
- max daily loss,
- max drawdown,
- consecutive loss pause,
- slippage and liquidity,
- duplicate order protection,
- leverage/derivatives restrictions,
- kill switch.

## Execution Layer

Executors:

- paper executor
- shadow executor
- OKX live executor, disabled by default

Execution must never happen without a risk decision of `APPROVED`.

## Ledger / Audit Layer

Every decision must be recorded:

- raw inputs hash
- AI prompt version
- model/provider used
- strategy candidates
- trade intent
- schema validation result
- risk decision
- order request
- execution result
- final PnL
- review outcome

## Review Layer

The review layer updates strategy diagnostics but cannot silently override risk policies.

It produces:

- daily review
- weekly review
- monthly review
- strategy score updates
- candidate strategy proposals
- paused strategy list

## Governance Layer

Governance controls:

- mode switch policy
- API permission policy
- secret management
- kill switch
- audit immutability
- live trading approval gates
- model/provider control
- configuration versioning
