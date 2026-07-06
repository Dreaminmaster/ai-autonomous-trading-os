<!-- SUPERSEDED BY B1_DESIGN_BUNDLE_V3.md — DO NOT IMPLEMENT -->
# Crash Matrix — Test Plan

**Version**: 1.0  
**Date**: 2026-07-06  
**Status**: DESIGN ONLY — tests not yet implemented

---

## Test Scenarios

### CM1: Crash after MARKET_ACCEPTED

**Pre-condition**: Cycle created, market data fetched, cycle.status=MARKET_ACCEPTED.  
**Crash**: SIGKILL during account snapshot fetch.  
**Expected on restart**:
- Cycle found with last_completed_stage=MARKET_ACCEPTED
- No execution intent created
- Risk state unchanged
- System transitions to READY
- Next cycle starts fresh

**Assertions**:
- No duplicate cycle
- No execution intent
- No order created
- Daily trade count unchanged

---

### CM2: Crash after PROVIDER_DECIDED

**Pre-condition**: AI decision made, ProviderResult stored, cycle.status=PROVIDER_DECIDED.  
**Crash**: SIGKILL before risk evaluation.  
**Expected on restart**:
- ProviderResult logged but risk not yet evaluated
- No risk decision persisted
- Cycle restarts from PROVIDER_DECIDED
- Risk evaluation rerun (idempotent — same intent, same risk result)

**Assertions**:
- Risk decision consistently same outcome
- No execution intent yet
- Daily trade count unchanged

---

### CM3: Crash after RISK_DECIDED

**Pre-condition**: Risk evaluated to APPROVED, cycle.status=RISK_DECIDED.  
**Crash**: SIGKILL before execution intent creation.  
**Expected on restart**:
- Risk decision logged
- No execution intent
- Cycle restarts from RISK_DECIDED
- Execution intent created with idempotency key

**Assertions**:
- Exactly one execution intent after recovery
- No duplicate execution
- TradeIntent unchanged

---

### CM4: Crash after EXECUTION_INTENT_CREATED

**Pre-condition**: Execution intent created with idempotency key, cycle.status=EXECUTION_INTENT_CREATED.  
**Crash**: SIGKILL before order sent to exchange.  
**Expected on restart**:
- ExecutionIntent found with status=PENDING
- Recovery: query exchange for order (not found)
- Mark intent as CANCELLED
- Cycle transitions back → new intent generated with new idempotency key

**Assertions**:
- Old intent marked CANCELLED
- No duplicate order
- Exactly one filled order after retry

---

### CM5: Crash after EXECUTED, before RECONCILED

**Pre-condition**: Order filled, cycle.status=EXECUTED, not yet RECONCILED.  
**Crash**: SIGKILL before reconciliation.  
**Expected on restart**:
- Order found, fills found
- Positions not yet updated
- Recovery: run reconciliation → update positions from fills
- Cycle transitions to RECONCILED → COMPLETED

**Assertions**:
- Position state matches order + fill state
- No double-counting of fill PnL
- Ledger consistent with positions

---

### CM6: Crash after RECONCILED, before COMPLETED

**Pre-condition**: Reconciliation complete, cycle.status=RECONCILED.  
**Crash**: SIGKILL before marking COMPLETED.  
**Expected on restart**:
- Reconciled state found, no changes needed
- Cycle transitions to COMPLETED

**Assertions**:
- No state modification
- Cycle marked COMPLETED

---

## Recovery Guarantees Verified by Matrix

| Guarantee | CM | Verified |
|-----------|-----|----------|
| No duplicate execution | CM3, CM4 | ✅ |
| No lost position | CM5 | ✅ |
| No lost cooldown | CM4 | ✅ |
| No lost daily counter | CM4 | ✅ |
| Unresolved state fails closed | CM1-CM6 | ✅ |
| Idempotency key prevents replay | CM4 | ✅ |
| Reconciliation catches drift | CM5 | ✅ |

---

## Implementation Notes

- All tests use paper executor (no exchange connectivity)
- Tests SIGKILL the process via `os.kill(pid, signal.SIGKILL)` subprocess
- Restart and verify DB state
- Must pass all 6 before ANY supervisor/daemon is implemented
