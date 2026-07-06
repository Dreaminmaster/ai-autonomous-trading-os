<!-- SUPERSEDED BY B1_DESIGN_BUNDLE_V3.md — DO NOT IMPLEMENT -->
# Runtime State Model — Design Document

**Version**: 1.0  
**Date**: 2026-07-06  
**Status**: DESIGN ONLY — no implementation  

---

## State Model Core Entities

### RuntimeSession
Immutable record for one autonomous runtime session.

| Field | Type | Description |
|-------|------|-------------|
| session_id | UUID | Unique session identifier |
| started_at | ISO-8601 | When the session began |
| mode | enum | `paper` / `shadow` / `guarded` |
| status | enum | `STARTING` / `RECOVERING` / `READY` / `RUNNING` / `PAUSED` / `STOPPED` |
| stopped_at | ISO-8601? | When stopped (null if running) |
| stop_reason | str? | Reason for stop |

### RuntimeCycle
One autonomous decision cycle (one candle / one symbol).

| Field | Type | Description |
|-------|------|-------------|
| cycle_id | UUID | Unique cycle identifier |
| session_id | UUID | FK to RuntimeSession |
| symbol | str | e.g. "BTC/USDT" |
| started_at | ISO-8601 | Cycle start |
| completed_at | ISO-8601? | Cycle end (null if incomplete) |
| status | enum | `CREATED` / `MARKET_ACCEPTED` / `ACCOUNT_ACCEPTED` / `CANDIDATES_READY` / `PROVIDER_DECIDED` / `RISK_DECIDED` / `EXECUTION_INTENT_CREATED` / `EXECUTED` / `RECONCILED` / `COMPLETED` |
| last_completed_stage | enum | Furthest stage reached |
| last_error | str? | Error message if failed |

### MarketSnapshot
Cached market data for one symbol.

| Field | Type | Description |
|-------|------|-------------|
| snapshot_id | UUID | Unique snapshot |
| symbol | str | e.g. "BTC/USDT" |
| candle_ts | ISO-8601 | Candle timestamp |
| fetched_at | ISO-8601 | When fetched from exchange |
| data_json | JSON | Raw candle data |
| freshness_status | enum | `FRESH` / `STALE_WARNING` / `STALE_CRITICAL` |
| source | str | `"okx_public"` or provider name |

### AccountSnapshot
Account state from exchange (read-only).

| Field | Type | Description |
|-------|------|-------------|
| snapshot_id | UUID | Unique snapshot |
| fetched_at | ISO-8601 | When fetched |
| equity | float | Total equity in USDT |
| available_balance | float | Available balance |
| positions_json | JSON | Active positions |
| source | str | `"okx_readonly"` |
| freshness_status | enum | `FRESH` / `STALE_WARNING` / `STALE_CRITICAL` |

### ExecutionIntent (immutable)
The final decision after risk approval, before execution.

| Field | Type | Description |
|-------|------|-------------|
| execution_intent_id | UUID | Unique intent |
| cycle_id | UUID | FK to RuntimeCycle |
| trade_intent_id | str | From AI decision |
| risk_decision_id | str | From risk engine |
| idempotency_key | str | UNIQUE — `{session_id[:8]}_{symbol}_{action}_{timestamp_bucket}_{intent_hash[:8]}` |
| status | enum | `PENDING` / `SENT` / `ACKNOWLEDGED` / `FILLED` / `CANCELLED` / `REJECTED` / `EXPIRED` |
| symbol | str | |
| action | enum | `BUY` / `SELL` / `HOLD` |
| notional | float | Order notional in USDT |
| created_at | ISO-8601 | Intent creation time |
| sent_at | ISO-8601? | When sent to exchange |

### OrderState
State tracked from exchange or paper simulation.

| Field | Type | Description |
|-------|------|-------------|
| order_id | str | Exchange-generated order ID |
| client_order_id | str | Our idempotency key |
| execution_intent_id | UUID | FK |
| symbol | str | |
| side | enum | `BUY` / `SELL` |
| quantity | float | Order quantity |
| price | float | Order price (0 for market) |
| order_type | enum | `MARKET` / `LIMIT` |
| status | enum | `PENDING` / `OPEN` / `PARTIALLY_FILLED` / `FILLED` / `CANCELLED` / `REJECTED` / `EXPIRED` |
| created_at | ISO-8601 | |
| updated_at | ISO-8601 | |

### FillState
Partial or full fill.

| Field | Type | Description |
|-------|------|-------------|
| fill_id | UUID | Unique fill |
| order_id | str | FK to OrderState |
| quantity | float | Fill quantity |
| price | float | Fill price |
| fee | float | Fee paid |
| fee_currency | str | |
| timestamp | ISO-8601 | |

### PositionState
Net position for a symbol.

| Field | Type | Description |
|-------|------|-------------|
| position_id | UUID | Unique position |
| symbol | str | |
| side | enum | `LONG` / `SHORT` |
| quantity | float | Net quantity |
| avg_entry_price | float | Average entry price |
| realized_pnl | float | Closed PnL |
| unrealized_pnl | float | Current unrealized |
| status | enum | `OPEN` / `CLOSED` |
| opened_at | ISO-8601 | |
| closed_at | ISO-8601? | |

### RiskRuntimeState
Persisted risk engine state.

| Field | Type | Description |
|-------|------|-------------|
| state_id | UUID | |
| session_id | UUID | FK |
| daily_trade_counts | JSON | `{"2025-01-01": 5, "2025-01-02": 12, ...}` |
| recent_signals | JSON | `[{"symbol": "...", "strategy_ids": [...], "timestamp": ...}]` |
| current_drawdown_pct | float | Current drawdown |
| peak_equity | float | Peak equity in this session |
| emergency_stop | bool | True if emergency stop activated |
| kill_switch_latched | bool | True if kill switch is active |
| updated_at | ISO-8601 | |

### RecoveryState
Post-crash reconciliation state.

| Field | Type | Description |
|-------|------|-------------|
| recovery_id | UUID | |
| session_id | UUID | FK |
| status | enum | `PENDING` / `IN_PROGRESS` / `RESOLVED` / `FAILED` |
| unresolved_items | JSON | `[{"type": "pending_execution", "id": "..."}, {"type": "position_mismatch", "detail": "..."}]` |
| started_at | ISO-8601 | |
| recovered_at | ISO-8601? | |
