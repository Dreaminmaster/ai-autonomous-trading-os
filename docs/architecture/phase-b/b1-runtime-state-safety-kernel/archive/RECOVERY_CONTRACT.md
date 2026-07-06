<!-- SUPERSEDED BY B1_DESIGN_BUNDLE_V3.md — DO NOT IMPLEMENT -->
# Recovery Contract — Design Document

**Version**: 1.0  
**Date**: 2026-07-06  
**Status**: DESIGN ONLY

---

## Startup State Machine

```
  STARTING
      ↓
  (check for incomplete session)
      ↓
  RECOVERING ──── (no incomplete data) ──→ READY
      │
      ├── unresolved execution intents
      ├── position mismatches
      ├── stale account snapshot
      ├── stale market snapshot
      └── DB corruption
                ↓
  PAUSED_RECOVERY_REQUIRED
      │
      ↓ (operator resolves)
  RECONCILING
      │
      ↓ (all clear)
  READY
```

## State Definitions

| State | Meaning | Allowed Transition |
|-------|---------|-------------------|
| STARTING | Bootstrap phase, loading config/DB | → RECOVERING |
| RECOVERING | Detecting previous session state | → READY or PAUSED_RECOVERY_REQUIRED |
| READY | Clean state, ready for new cycles | → RUNNING |
| RUNNING | Active decision loop | → PAUSED or STOPPED |
| RECONCILING | Post-recovery cleanup | → READY or PAUSED_RECOVERY_REQUIRED |
| PAUSED_RECOVERY_REQUIRED | Needs human intervention | → RECONCILING |
| PAUSED | Intentionally stopped (operator command) | → READY |
| STOPPED | Normal shutdown | → (process exit) |

## Recovery Triggers

| Trigger | Action |
|---------|--------|
| `ExecutionIntent.status = PENDING` found on startup | Cancel or query exchange, mark status |
| `OrderState.status = PENDING` found | Cancel on exchange, mark REJECTED |
| `PositionState` ≠ exchange reality | Reconcile from exchange fills |
| Last `AccountSnapshot` > 5 minutes old | Fetch fresh, HOLD until fresh |
| Last `MarketSnapshot` > 5 minutes old | Fetch fresh, HOLD until fresh |
| `RiskRuntimeState` missing or corrupted | Initialize fresh (memory-only → persisted) |
| DB corruption detected | PAUSED, prompt operator |

## Recovery Guarantees

1. **No decision loop before READY**: Any unresolved state → PAUSED.
2. **Idempotent intent replay**: Same idempotency_key → ALREADY_PROCESSED.
3. **Position integrity**: Recovery reconciles from exchange data, not memory.
4. **Risk state preserved**: Cooldown, daily counts, drawdown survive restart.
5. **Audit continuity**: Ledger events are append-only, never overwritten.

## Operator Commands During Recovery

| Command | Effect |
|---------|--------|
| `force_continue` | Skip unresolved items (with warning) → READY |
| `cancel_all` | Cancel all pending orders → READY |
| `reconcile` | Run full reconciliation → READY if clean |
| `reset_risk_state` | Clear daily counts + cooldown → READY |
| `stop` | Halt process |
