# 04 Deterministic Risk Layer

## Purpose

The Risk Layer is the non-negotiable safety gate between AI intent and execution.

The AI can propose. The risk manager approves or rejects.

## Core principle

```text
No valid risk approval -> no order.
```

The risk manager must be deterministic Python code, not an LLM judgment.

## Risk decision states

- `APPROVED`
- `REJECTED`
- `MODIFIED`
- `PAUSED`
- `KILL_SWITCH_ACTIVE`

`MODIFIED` may reduce size or convert action to HOLD, but it must be logged.

## Required risk checks

### Mode check

Allowed execution by mode:

| Mode | Real orders | Notes |
| --- | --- | --- |
| design | no | docs/planning only |
| backtest | no | historical replay only |
| paper | no | simulated orders only |
| shadow | no | live data, simulated orders |
| live | yes | disabled by default |

### Permission check

Reject if the action requires permissions not explicitly enabled.

Forbidden by default:

- withdrawals
- internal transfers
- leverage changes
- futures/swaps/options
- non-whitelisted symbols
- market type not explicitly allowed

### Symbol whitelist

Only configured symbols can be traded.

Example first whitelist:

- BTC-USDT
- ETH-USDT

### Position size

Reject or reduce if:

- position size exceeds `max_position_pct_per_trade`,
- notional exceeds `max_notional_per_trade`,
- portfolio exposure exceeds `max_total_exposure_pct`,
- symbol exposure exceeds `max_symbol_exposure_pct`.

### Loss limits

Reject if any limit is breached:

- daily realized loss
- daily unrealized loss
- total drawdown
- rolling 7-day drawdown
- consecutive losing trades

### Frequency limits

Reject if:

- too many trades per hour,
- too many trades per day,
- same symbol traded too frequently,
- duplicate intent detected.

### Liquidity and slippage

Reject if:

- orderbook depth insufficient,
- estimated slippage too high,
- spread too wide,
- market data stale,
- volatility shock detected.

### AI output quality

Reject if:

- schema invalid,
- confidence below threshold,
- thesis missing,
- evidence missing,
- no stop loss for risk-taking trade,
- no invalidation condition,
- selected strategy is paused,
- action contradicts portfolio state.

## Kill switch

Kill switch must stop new orders immediately.

Triggers:

- manual kill switch file/flag,
- max drawdown breach,
- daily loss breach,
- repeated API errors,
- reconciliation mismatch,
- suspicious order duplication,
- missing account snapshot,
- secret leakage detected,
- live mode misconfiguration.

When kill switch is active:

- no new orders,
- optionally close positions only if explicitly configured,
- write emergency report,
- require manual reset.

## Risk result object

The risk manager should output JSON matching `schemas/risk_decision.schema.json`.

Example:

```json
{
  "decision": "REJECTED",
  "reasons": ["position_size_exceeds_limit"],
  "modified_trade_intent": null,
  "risk_score": 0.91,
  "checks": {
    "schema_valid": true,
    "symbol_allowed": true,
    "size_allowed": false,
    "mode_allowed": true,
    "kill_switch_active": false
  }
}
```

## Risk cannot be changed by AI

The AI may propose risk policy changes in a review document, but it cannot apply them automatically.

Risk policy changes require:

1. written proposal,
2. backtest evidence,
3. paper trading evidence,
4. explicit human approval,
5. versioned config update.
