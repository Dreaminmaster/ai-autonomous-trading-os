# 03 AI Decision Layer

## Purpose

The AI Decision Layer is where autonomy lives.

The AI may:

- analyze the current market,
- compare strategy candidates,
- decide BUY / SELL / HOLD,
- choose a symbol from a whitelist,
- propose position size,
- propose stop loss and take profit,
- choose a maximum holding time,
- explain its thesis,
- reference past lessons.

The AI must not directly execute orders.

## Inputs to the AI trader

The AI should receive a compact decision packet:

```json
{
  "mode": "paper",
  "timestamp": "2026-07-02T12:00:00Z",
  "portfolio_state": {},
  "risk_limits": {},
  "market_state": {},
  "strategy_candidates": [],
  "recent_trade_lessons": [],
  "paused_strategies": [],
  "allowed_symbols": ["BTC-USDT", "ETH-USDT"],
  "forbidden_actions": ["WITHDRAW", "TRANSFER", "ENABLE_LEVERAGE"]
}
```

## Output format

The AI must output only valid JSON matching `schemas/trade_intent.schema.json`.

Allowed actions:

- `BUY`
- `SELL`
- `REDUCE`
- `CLOSE`
- `HOLD`

If unsure, output `HOLD`.

## Required fields

- action
- symbol
- market_type
- confidence
- thesis
- evidence
- selected_strategy_ids
- position_size_pct
- stop_loss_pct
- take_profit_pct
- max_holding_minutes
- invalidation_conditions
- risk_notes

## Decision discipline

The AI must explicitly answer:

1. What market regime is this?
2. Which strategy candidates are relevant?
3. Why is this trade better than HOLD?
4. What would prove the thesis wrong?
5. What is the exit plan?
6. What is the worst-case loss if stop loss hits?
7. Does this decision conflict with recent lessons?

## Counter-argument agent

For high-impact decisions, a second AI reviewer can criticize the decision before risk approval.

The counter-argument agent should check:

- Is the thesis data-supported?
- Is confidence too high?
- Is the trade chasing a move?
- Is funding overheated?
- Is liquidity sufficient?
- Is stop loss too tight or too wide?
- Does recent performance suggest pausing this strategy?

## Model/provider policy

The system may use multiple model providers, but provider choice must be logged.

Minimum log fields:

- provider
- model
- prompt template version
- output schema version
- raw output hash
- validation result

If the selected model is unavailable, high-risk trading decisions must default to HOLD rather than silently downgrade to a weak model.

## AI memory use

The AI can use past lessons, but memory must be point-in-time in backtests.

Forbidden:

- using future reviews during historical replay,
- using full-period strategy statistics at the start of a backtest,
- using model knowledge of historical events as if it were available at the time.

## Failure behavior

Default to HOLD when:

- JSON invalid,
- schema validation fails,
- confidence below threshold,
- data incomplete,
- risk packet missing,
- provider unavailable,
- model output contradicts itself,
- decision lacks an exit plan.
