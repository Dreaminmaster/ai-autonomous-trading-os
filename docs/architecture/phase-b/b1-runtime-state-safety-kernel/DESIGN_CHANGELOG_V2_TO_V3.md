# B1 Design Changelog — V2 to V3

**Date**: 2026-07-06  
**Version**: V2 (previous batch) → V3 (this batch)

---

## Status of Previous Documents

| Document | Status | Reason |
|----------|--------|--------|
| `ARCHITECTURE_DISCOVERY_CORRECTIONS.md` | **SUPERSEDED** | Corrections merged into V3 Bundle |
| `RUNTIME_STATE_MODEL.md` | **SUPERSEDED** | Model revised (see changes below) |
| `RUNTIME_STATE_AUTHORITY.md` | **SUPERSEDED** | Authority revised: clock, mode-specific, no dual authority |
| `RECOVERY_CONTRACT.md` | **SUPERSEDED** | Recovery revised: missing-risk-state fail-closed, order lifecycle fix |
| `IDEMPOTENCY_CONTRACT.md` | **SUPERSEDED** | Idempotency revised: execution_intent_id based, not content-equivalent |
| `CRASH_MATRIX.md` | **SUPERSEDED** | Extended from 6 to 10 scenarios with dispatch semantics |
| `B1_DELIVERY_REPORT.md` | **SUPERSEDED** | Replaced by V3 Index |
| `B1_DESIGN_DELIVERY_INDEX.md` | **SUPERSEDED** | Replaced by V3 Index |

## Key Changes V2 → V3

| # | Area | V2 (old) | V3 (new) |
|---|------|----------|----------|
| P0 | Idempotency key | Content-equivalent intent hash + timestamp bucket → same key = false dedup | execution_intent_id per logical execution, key = account_scope + execution_intent_id |
| P1 | Guarantee level | "Exactly-once" via DB UNIQUE | Local: at-most-once dispatch registration. External: effectively-once with client_order_id + venue lookup + reconciliation |
| P2 | Dispatch model | PREPARED → DISPATCHING → ACKNOWLEDGED (dual-write window) | New DispatchAttempt with attempt_no, client_order_id, 5-phase crash coverage |
| P3 | Commit timing | Unspecified | 5 crash points specified: after-PREPARED, after-DISPATCHING-commit, during-network, venue-accepted-response-lost, response-received-before-ACK |
| P4 | Order lifecycle | PENDING → cancel → REJECTED (incorrect) | NEW → PENDING_SUBMIT → OPEN → PARTIALLY_FILLED → FILLED → CANCEL_REQUESTED → CANCEL_PENDING → CANCELLED → REJECTED (venue only) → EXPIRED → UNKNOWN |
| P5 | Missing risk state | Initialize fresh from scratch | Reconstruct from cycles/orders/fills/ledger. If uncertain: PAUSED_RECOVERY_REQUIRED. Never silently zero. |
| P6 | Crash matrix | 6 scenarios | 10 scenarios (CM1-CM10) |
| P7 | Intent mutability | ExecutionIntent = both immutable and mutable | TradeIntent (immutable decision payload) + ExecutionState (mutable lifecycle) |
| P8 | Authority | Single authority table | Mode-specific: Paper (local fills/ledger), Live (venue + local log + reconciliation). No dual authority. |
| P9 | Clock contract | Unspecified | observed_at (exchange), fetched_at (local UTC), monotonic elapsed, restart skew check |
| P10 | Position accounting | Unspecified | Average cost basis for V1. FIFO on roadmap. |
| P11 | DB precision | REAL | TEXT-encoded Decimal (string) for price/qty/notional/fee/pnl. Fixed-scale INTEGER rejected. |
| P12 | Document authority | Old reports still active | SUPERSEDED markers. V3 Bundle = sole authority. |
