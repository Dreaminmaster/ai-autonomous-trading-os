# B1 Design Bundle V3 — Complete Runtime State & Safety Kernel

**Version**: V3  
**Date**: 2026-07-06  
**Status**: DESIGN ONLY — 0 code changes, 0 commits, 0 pushes  
**Live**: FORBIDDEN

---

## 1. State Entity Definitions

### 1.1 TradeIntent (IMMUTABLE)
AI + Risk produces this. Never changes after creation.

| Field | Type | Description |
|-------|------|-------------|
| trade_intent_id | TEXT(UUID) | Immutable identifier |
| symbol | TEXT | e.g. "BTC/USDT" |
| action | TEXT | BUY / SELL / HOLD |
| confidence | TEXT | Decimal-encoded float |
| thesis | TEXT | Human-readable reason |
| evidence | TEXT | Supporting data (JSON) |
| position_size_pct | TEXT | Percent of equity |
| stop_loss_pct | TEXT | Stop loss percent |
| take_profit_pct | TEXT | Take profit percent |
| invalidation_conditions | TEXT | JSON array |
| selected_strategy_ids | TEXT | JSON array |
| created_at | TEXT | ISO-8601 UTC |

### 1.2 ExecutionIntent (IMMUTABLE identity + payload)
One per logical execution. Persisted BEFORE any network side effect.

| Field | Type | Description |
|-------|------|-------------|
| execution_intent_id | TEXT(UUID) | Unique per logical execution |
| trade_intent_id | TEXT(UUID) | FK to TradeIntent |
| risk_decision_id | TEXT(UUID) | FK to RiskDecision |
| cycle_id | TEXT(UUID) | FK to RuntimeCycle |
| symbol | TEXT | |
| action | TEXT | BUY / SELL |
| notional | TEXT | Decimal-encoded |
| normalized_intent_hash | TEXT | SHA256 for audit/dedup suspicion only |
| created_at | TEXT | ISO-8601 UTC |

### 1.3 ExecutionState (MUTABLE lifecycle)
Tracks where the execution is in its lifecycle. Separate from the immutable intent.

| Field | Type | Description |
|-------|------|-------------|
| execution_intent_id | TEXT(UUID) | FK to ExecutionIntent |
| status | TEXT | PREPARED / DISPATCH_COMMITTED / DISPATCHED / ACKNOWLEDGED / AMBIGUOUS / FILLED / TERMINAL |
| last_attempt_id | TEXT(UUID) | FK to latest DispatchAttempt |
| retry_count | INTEGER | Number of retries |
| state_started_at | TEXT | When current status began |
| updated_at | TEXT | Last update |

### 1.4 DispatchAttempt
Every attempt to send an order to the venue. Persisted and COMMITTED before network call.

| Field | Type | Description |
|-------|------|-------------|
| attempt_id | TEXT(UUID) | Unique attempt |
| execution_intent_id | TEXT(UUID) | FK to ExecutionIntent |
| client_order_id | TEXT | Stable external order identifier |
| venue | TEXT | e.g. "okx_paper" / "okx_live" |
| account_scope | TEXT | e.g. "spot_btc" |
| status | TEXT | PENDING_SUBMIT / SUBMITTED / ACCEPTED / REJECTED / TIMEOUT / AMBIGUOUS |
| attempt_no | INTEGER | 1-based |
| created_at | TEXT | |
| dispatch_started_at | TEXT | |
| response_received_at | TEXT | NULL if timeout |
| error_class | TEXT | NetworkError / Timeout / RateLimit / etc |

### 1.5 OrderState
Exchange-level order lifecycle.

| Field | Type | Description |
|-------|------|-------------|
| order_id | TEXT | Venue-generated ID |
| client_order_id | TEXT | Our stable client ID |
| execution_intent_id | TEXT(UUID) | FK to ExecutionIntent |
| symbol | TEXT | |
| side | TEXT | BUY / SELL |
| quantity | TEXT | Decimal-encoded |
| price | TEXT | Decimal-encoded (0 = market) |
| order_type | TEXT | MARKET / LIMIT |
| status | TEXT | NEW / PENDING_SUBMIT / OPEN / PARTIALLY_FILLED / FILLED / CANCEL_REQUESTED / CANCEL_PENDING / CANCELLED / REJECTED / EXPIRED / UNKNOWN |
| created_at | TEXT | |
| updated_at | TEXT | |

### 1.6 FillState
Each fill from exchange.

| Field | Type | Description |
|-------|------|-------------|
| fill_id | TEXT(UUID) | |
| order_id | TEXT | FK to OrderState |
| quantity | TEXT | Decimal |
| price | TEXT | Decimal |
| fee | TEXT | Decimal |
| fee_currency | TEXT | |
| timestamp | TEXT | ISO-8601 |

### 1.7 PositionState
Net position, average cost method (V1).

| Field | Type | Description |
|-------|------|-------------|
| position_id | TEXT(UUID) | |
| symbol | TEXT | |
| side | TEXT | LONG / SHORT |
| quantity | TEXT | Decimal — net quantity |
| avg_entry_price | TEXT | Decimal — average cost |
| realized_pnl | TEXT | Decimal |
| unrealized_pnl | TEXT | Decimal |
| status | TEXT | OPEN / CLOSED |
| opened_at | TEXT | |
| closed_at | TEXT | |

**Accounting method**: Average cost for V1. Partial close: reduce quantity proportionally, realized PnL = (exit_price - avg_entry_price) × closed_qty. Remaining basis = avg_entry_price unchanged.

### 1.8 PositionAccountingDetail (audit trail)
Event log for every position mutation.

| Field | Type | Description |
|-------|------|-------------|
| event_id | TEXT(UUID) | |
| position_id | TEXT(UUID) | FK |
| event_type | TEXT | OPEN / INCREASE / REDUCE / CLOSE |
| delta_qty | TEXT | Signed quantity change |
| price | TEXT | Fill price |
| fee | TEXT | Fee allocated |
| realized_pnl | TEXT | PnL from this event |
| timestamp | TEXT | |

### 1.9 RiskRuntimeState
Persisted risk engine state. Never silently initialized.

| Field | Type | Description |
|-------|------|-------------|
| state_id | TEXT(UUID) | |
| session_id | TEXT(UUID) | FK |
| daily_trade_counts | TEXT | JSON: {"YYYY-MM-DD": count} |
| recent_signals | TEXT | JSON: [{symbol, strategy_ids, timestamp}] |
| current_drawdown_pct | TEXT | Decimal |
| peak_equity | TEXT | Decimal |
| emergency_stop | INTEGER | 0 or 1 |
| kill_switch_latched | INTEGER | 0 or 1 |
| updated_at | TEXT | |

**Recovery**: When state is missing on startup:
1. Reconstruct from persisted cycles, orders, fills, ledger
2. If complete → restore
3. If uncertain → PAUSED_RECOVERY_REQUIRED, HOLD

### 1.10 RuntimeSession
One autonomous runtime session.

| Field | Type | Description |
|-------|------|-------------|
| session_id | TEXT(UUID) | |
| started_at | TEXT | |
| mode | TEXT | paper / shadow / guarded |
| status | TEXT | STARTING / RECOVERING / READY / RUNNING / PAUSED |
| stopped_at | TEXT | |
| stop_reason | TEXT | |

### 1.11 RuntimeCycle
One decision cycle.

| Field | Type | Description |
|-------|------|-------------|
| cycle_id | TEXT(UUID) | |
| session_id | TEXT(UUID) | FK |
| symbol | TEXT | |
| started_at | TEXT | |
| completed_at | TEXT | |
| status | TEXT | CREATED → MARKET_ACCEPTED → ACCOUNT_ACCEPTED → CANDIDATES_READY → PROVIDER_DECIDED → RISK_DECIDED → EXECUTION_INTENT_CREATED → EXECUTED → RECONCILED → COMPLETED |
| last_completed_stage | TEXT | Furthest stage reached |
| last_error | TEXT | |

### 1.12 MarketSnapshot
| Field | Type | Description |
|-------|------|-------------|
| snapshot_id | TEXT(UUID) | |
| symbol | TEXT | |
| observed_at | TEXT | Exchange timestamp |
| fetched_at | TEXT | Local UTC when received |
| data_json | TEXT | Raw candles |
| freshness_status | TEXT | FRESH / STALE_WARNING / STALE_CRITICAL |
| source | TEXT | "okx_public" |

**Authority**: Persisted to SQLite. TTL cache is derived cache only, not authority.

### 1.13 AccountSnapshot
| Field | Type | Description |
|-------|------|-------------|
| snapshot_id | TEXT(UUID) | |
| fetched_at | TEXT | Local UTC |
| equity | TEXT | Decimal |
| available_balance | TEXT | Decimal |
| positions_json | TEXT | JSON |
| source | TEXT | |
| freshness_status | TEXT | FRESH / STALE_WARNING / STALE_CRITICAL |

### 1.14 RecoveryState
Post-crash reconciliation state.

| Field | Type | Description |
|-------|------|-------------|
| recovery_id | TEXT(UUID) | |
| session_id | TEXT(UUID) | FK |
| status | TEXT | PENDING / IN_PROGRESS / RESOLVED / FAILED |
| unresolved_items | TEXT | JSON |
| started_at | TEXT | |
| recovered_at | TEXT | |

---

## 2. Idempotency Contract (V3)

### Key Structure
```
{account_scope}:{execution_intent_id}
```

### Rules
1. Every new logical execution generates a new `execution_intent_id` (UUID).
2. `execution_intent_id` is persisted as part of `ExecutionIntent` BEFORE any network side effect.
3. Restart discovers the same `execution_intent_id` and retries with the same ID.
4. Content-equivalent intents (same symbol/action/confidence) that are DIFFERENT logical executions MUST have different IDs.
5. `normalized_intent_hash` is for audit/dedup suspicion only — never used as a business key.

### Guarantees
- **Local**: at-most-once logical dispatch registration (UNIQUE on execution_intent_id).
- **External**: effectively-once when client_order_id + venue lookup + reconciliation are available.
- **Ambiguous**: fail closed. No blind redispatch. PAUSED.

---

## 3. Dispatch Transaction Contract (V3)

### Dispatch Phases

| Phase | DB State | Network | Crash Point |
|-------|----------|---------|-------------|
| 1. PREPARE | ExecutionIntent INSERTED, ExecutionState=PREPARED | None | CM7 |
| 2. DISPATCH | DispatchAttempt INSERTED + COMMITTED. ExecutionState=DISPATCH_COMMITTED | None | CM8 |
| 3. NETWORK CALL | — | Order sent to venue | CM9 |
| 4. RESPONSE | ExecutionState=DISPATCHED or AMBIGUOUS | — | CM10 |
| 5. ACK | ExecutionState=ACKNOWLEDGED or AMBIGUOUS | — | CM5 |

### Commit Timing Rule
```
DB INSERT DispatchAttempt → COMMIT → THEN network call
```
Not: network call during DB transaction.

### Ambiguous Response Handling
1. Query venue by `client_order_id`
2. If found → update OrderState + reconcile
3. If not found AND timeout → mark AMBIGUOUS. PAUSE. No redispatch.

---

## 4. Order Lifecycle (V3)

### States
```
NEW
  ↓
PENDING_SUBMIT (DispatchAttempt committed, not yet sent)
  ↓
OPEN (venue accepted, order visible)
  ↓
PARTIALLY_FILLED (partial fill)
  ↓
FILLED (complete fill)
  ↓
CANCELLED / REJECTED / EXPIRED (terminal)
```

### Cancel Flow
```
query venue → request cancel → re-query → only exchange-confirmed terminal state
```

### REJECTED
Only set when venue rejects the order. Never set for "we don't know what happened."

### UNKNOWN
Used when venue state is indeterminate. Triggers PAUSED_RECOVERY_REQUIRED.

---

## 5. Recovery Contract (V3)

### Startup State Machine
```
STARTING
  → load last session
  → RECOVERING
    → scan for unresolved ExecutionIntents
    → scan for pending DispatchAttempts
    → query venue for unknown orders
    → reconcile positions from fills
    → if all clear: READY
    → if any unresolved: PAUSED_RECOVERY_REQUIRED
```

### Risk State Recovery
1. Attempt reconstruction from: persisted cycles, orders, fills, ledger
2. If complete → restore RiskRuntimeState
3. If uncertain → PAUSED_RECOVERY_REQUIRED, HOLD
4. NEVER silently initialize to zeros

### Provider Failure Contract
```
Provider timeout/error → HOLD (not fallback-to-Mock BUY)
MockProvider used ONLY in backtest/research mode.
Runtime mode: provider error = cycle aborted, no execution.
```

### Freshness Contract
```
MarketSnapshot stale (> TTL) → HOLD
AccountSnapshot missing → HOLD
AccountSnapshot stale → HOLD
Equity unknown → HOLD (no 1000.0 default)
```

---

## 6. Crash Matrix (V3 — 10 scenarios)

### Previously defined (CM1-CM6)
SIGKILL after: MARKET_ACCEPTED, PROVIDER_DECIDED, RISK_DECIDED, EXECUTION_INTENT_CREATED, EXECUTED-before-RECONCILED, RECONCILED-before-COMPLETED.

### New (CM7-CM10)

**CM7: Crash after PREPARED commit, before DISPATCH**
- Persisted: ExecutionIntent + ExecutionState=PREPARED
- External: Nothing sent
- Recovery: Discover intent. Clear to proceed. Attempt dispatch.
- Assert: No duplicate. Exactly one DispatchAttempt created.

**CM8: Crash after DISPATCH_COMMITTED, before network call**
- Persisted: ExecutionIntent + DispatchAttempt + ExecutionState=DISPATCH_COMMITTED
- External: Nothing sent
- Recovery: Query venue (finds nothing). Mark Attempt=TIMEOUT. Retry or abandon.
- Assert: No duplicate. New attempt has new attempt_id. No blind dispatch.

**CM9: Venue may have accepted, response lost/timeout**
- Persisted: DispatchAttempt (SUBMITTED status)
- External: Order may exist at venue
- Recovery: Query venue by client_order_id. If found → reconcile. If not → mark AMBIGUOUS. PAUSE.
- Assert: AMBIGUOUS state persisted. No blind redispatch. No cancel without evidence.

**CM10: After PARTIALLY_FILLED, before local persistence**
- Persisted: Previous fill state committed
- External: Partial fill booked at venue
- Recovery: Query venue. Get latest fills. Reconcile to PositionState.
- Assert: No fill duplication. Position reflects venue reality.

---

## 7. Database Precision Rules

| Field | Type | Example |
|-------|------|---------|
| price | TEXT (Decimal) | "97123.45" |
| quantity | TEXT (Decimal) | "0.00123456" |
| notional | TEXT (Decimal) | "119.8765" |
| fee | TEXT (Decimal) | "0.011988" |
| pnl | TEXT (Decimal) | "-16.1234" |

**Rejected**: REAL (floating point drift), fixed-scale INTEGER (lost precision on BTC sub-satoshi).

---

## 8. Clock Contract

| Concept | Source | Behavior |
|---------|--------|----------|
| observed_at | Exchange timestamp from candle/order | Source of truth for market timing |
| fetched_at | Local UTC when data arrived | Latency measurement |
| Monotonic elapsed | `time.monotonic()` in process | Timeout calculations, never wall-clock |
| Restart | Persisted UTC + skew validation | If local clock drifted > 60s → WARN, HOLD |
| decision_ts | `observed_at` or `fetched_at` | Already implemented in `time_context.py` |

---

## 9. Authority Hierarchy (Mode-Specific)

### Paper Mode
| Entity | Authority |
|--------|-----------|
| Market | Latest accepted MarketSnapshot in DB |
| Account | Latest AccountSnapshot in DB |
| Position | Local fills/ledger computation |
| Order | PaperExecutor.State DB records |
| Risk | RiskRuntimeState in DB |

### Shadow / Live Mode
| Entity | Authority |
|--------|-----------|
| Market | Latest accepted MarketSnapshot in DB |
| Account | Latest AccountSnapshot in DB |
| Position | Venue observed state + local event log + reconciliation. Discrepancy → PAUSE. |
| Order | Venue order state via query. |
| Risk | RiskRuntimeState in DB, reconstructed if needed. |

---

## 10. Open Decisions (deferred)

| ID | Decision | Deferred To |
|----|----------|------------|
| D1 | FIFO vs LIFO vs avg cost for multi-position same symbol | Phase B5 |
| D2 | Partial fill timeout policy | Phase B10 |
| D3 | Max open positions limit per symbol | Phase B6 |
| D4 | Fee allocation method on partial fills | Phase B10 |
| D5 | Live enable multi-signature protocol | Phase B10 |
