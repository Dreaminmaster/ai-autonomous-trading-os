# 05 Execution Layer

## Purpose

The Execution Layer turns approved risk decisions into simulated or real exchange actions.

It must be mode-aware.

## Executors

### Paper executor

Used in `paper` and `backtest` mode.

Responsibilities:

- simulate orders,
- apply fees,
- apply slippage,
- update simulated positions,
- write ledger records,
- produce fill reports.

### Shadow executor

Used in `shadow` mode.

Responsibilities:

- read live market data,
- generate live-time decisions,
- simulate what would have happened,
- compare decisions to real market evolution,
- never submit orders.

### OKX live executor

Used only in `live` mode.

Responsibilities:

- submit orders only after risk approval,
- handle order status,
- reconcile fills,
- detect mismatches,
- enforce idempotency keys,
- write audit logs.

Live executor must be disabled by default.

## Order lifecycle

```text
trade_intent
  -> schema validation
  -> risk_decision
  -> order_request
  -> execution_result
  -> ledger_update
  -> reconciliation
  -> review queue
```

## Idempotency

Every order request must include a unique client order ID.

Recommended format:

```text
{mode}-{strategy_id}-{symbol}-{timestamp}-{hash}
```

Duplicate client order IDs must be rejected.

## Position manager

The position manager must track:

- current position size,
- average entry price,
- unrealized PnL,
- realized PnL,
- stop loss,
- take profit,
- max holding time,
- strategy attribution,
- AI thesis ID.

## Stop loss / take profit manager

For paper trading, it simulates exits.

For live trading, it may place protective orders only if explicitly enabled and supported by risk policy.

Rules:

- No trade without exit plan.
- Stop loss must be present for risk-taking trades.
- Exit rules must be logged at entry time.
- AI cannot remove stop loss after entry unless risk manager approves.

## Reconciliation

The system must reconcile:

- local ledger,
- exchange order status,
- account balances,
- positions,
- fees,
- fills.

If reconciliation fails:

- stop new orders,
- activate risk pause,
- write incident report.

## Live execution restrictions

Default restrictions:

- spot only,
- no margin,
- no futures/swaps/options,
- no withdrawals,
- no transfers,
- no auto-leverage,
- whitelist symbols only,
- small position size.

## API secret handling

The executor must read credentials from environment variables or secure local storage.

Never store secrets in:

- code,
- Git,
- logs,
- reports,
- database rows,
- prompts,
- error stack traces.

## Failure behavior

On any exception or unclear state:

- stop new orders,
- log error,
- reconcile state,
- default to HOLD.
