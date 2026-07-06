<!-- SUPERSEDED BY B1_DESIGN_BUNDLE_V3.md — DO NOT IMPLEMENT -->
# Phase B — Runtime State & Safety Kernel: Design Documents Index

**Date**: 2026-07-06  
**HEAD**: `2f5054a`  
**Status**: DESIGN ONLY — 0 code changes, 0 commits, 0 pushes  
**Live**: FORBIDDEN

---

## Sub-phase B1 — Runtime State Contract Design

All 6 design documents delivered. No implementation yet.

| # | Document | Description | Path |
|---|----------|-------------|------|
| 1 | Architecture Discovery Corrections | 6 corrections to Phase A report: provider failure safety, exposure limits, runtime binding, live gate, position persistence, kill switch | `ARCHITECTURE_DISCOVERY_CORRECTIONS.md` |
| 2 | Runtime State Model | 11 domain entities with full field definitions: RuntimeSession, RuntimeCycle, MarketSnapshot, AccountSnapshot, ExecutionIntent, OrderState, FillState, PositionState, RiskRuntimeState, RecoveryState, Cycle Journal Stages | `RUNTIME_STATE_MODEL.md` |
| 3 | Runtime State Authority | Authoritative source rules per entity + read/write access matrix for all modules | `RUNTIME_STATE_AUTHORITY.md` |
| 4 | Recovery Contract | Startup state machine (STARTING → RECOVERING → READY), recovery triggers, guarantees, operator commands | `RECOVERY_CONTRACT.md` |
| 5 | Idempotency Contract | Key structure: session+symbol+action+timestamp_bucket+intent_hash, DB UNIQUE constraint, crash scenarios, guarantees | `IDEMPOTENCY_CONTRACT.md` |
| 6 | Crash Matrix | 6 SIGKILL scenarios (after MARKET_ACCEPTED, PROVIDER_DECIDED, RISK_DECIDED, EXECUTION_INTENT_CREATED, EXECUTED, RECONCILED) with assertions and verification table | `CRASH_MATRIX.md` |

### Direct Links

- [ARCHITECTURE_DISCOVERY_CORRECTIONS.md](minis://shared/ARCHITECTURE_DISCOVERY_CORRECTIONS.md)
- [RUNTIME_STATE_MODEL.md](minis://shared/RUNTIME_STATE_MODEL.md)
- [RUNTIME_STATE_AUTHORITY.md](minis://shared/RUNTIME_STATE_AUTHORITY.md)
- [RECOVERY_CONTRACT.md](minis://shared/RECOVERY_CONTRACT.md)
- [IDEMPOTENCY_CONTRACT.md](minis://shared/IDEMPOTENCY_CONTRACT.md)
- [CRASH_MATRIX.md](minis://shared/CRASH_MATRIX.md)

---

## Files Planned for Implementation

| Phase | Files | Description |
|-------|-------|-------------|
| B4 | `db_migrations.py` | Add tables: sessions, cycles, market_snapshots, account_snapshots, execution_intents, orders, fills, positions, risk_runtime_state, recoveries |
| B4 | `state_service.py` | Cycle journal write/read methods |
| B5 | `execution.py` | Idempotency key generation + DB check |
| B6 | `risk.py` | `export_state()` / `restore_state()` |
| B7 | `state_service.py` | Recovery state machine logic |
| B8 | `providers/base.py` | Provider failure → HOLD enforcement |
| B9 | `runtime.py` | Replace `equity_usdt=1000.0` with AccountSnapshot |
| B10 | `execution.py` | Persistent order/fill/position lifecycle |
| B11 | `reconciliation.py` | New module: order→fill→position→ledger consistency |

---

## Acceptance Criteria

| ID | Criteria |
|----|----------|
| AC1 | All 11 state entities have corresponding DB tables |
| AC2 | Crash Matrix: all 6 scenarios pass |
| AC3 | No duplicate execution under idempotency key |
| AC4 | Restart recovers risk state (daily count, cooldown, drawdown) |
| AC5 | Provider error → HOLD (not fallback-to-Mock BUY) |
| AC6 | Stale market/account → HOLD (not 1000.0 default) |
| AC7 | Reconciliation detects mismatch → PAUSED |

---

## Test Plan

| Suite | Count | Type |
|-------|-------|------|
| State model serialization | 11 | Unit |
| DB migrations forward/backward | 4 | Integration |
| Cycle journal stage transitions | 12 | Unit |
| Idempotency key uniqueness | 4 | Unit |
| Crash matrix | 6 | Integration (subprocess SIGKILL) |
| Recovery state machine | 5 | Unit |
| Provider HOLD contract | 3 | Unit |
| Freshness fail-closed | 4 | Unit |
| Paper execution persistence | 5 | Integration |
| Reconciliation | 5 | Integration |

---

## Decision

```
DESIGN READY: YES
IMPLEMENTATION READY: YES
LIVE: FORBIDDEN
```
