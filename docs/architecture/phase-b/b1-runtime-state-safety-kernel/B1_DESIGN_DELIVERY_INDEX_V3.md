# B1 Design Delivery Index V3

**B1 design baseline**: V3.3
**Last synced commit**: (pending)
**Live**: FORBIDDEN

---

## V3 Bundle

| # | Document | Description |
|---|----------|-------------|
| 1 | `B1_DESIGN_BUNDLE_V3.md` | Complete design: 15 persisted entities, idempotency V3, dispatch transaction contract V3, order lifecycle V3, recovery V3, crash matrix V3 (11 scenarios), DB precision rules, clock contract, authority hierarchy, open decisions |
| 2 | `EXECUTION_TRANSACTION_CONTRACT_V2.md` | Transaction boundary, 5-phase crash coverage, retry rules, network error classification, guarantees |
| 3 | `B1_DESIGN_DELIVERY_INDEX_V3.md` | This index (complete superseding hierarchy) |
| 4 | `DESIGN_CHANGELOG_V2_TO_V3.md` | Supersedes all V2 documents. 12 key changes documented. |
| 5 | `UNRESOLVED_DECISIONS.md` | 5 open decisions deferred to later phases |

## Superseded Documents (Historical Only)

| File | Replaced By |
|------|------------|
| `ARCHITECTURE_DISCOVERY_CORRECTIONS.md` | `B1_DESIGN_BUNDLE_V3.md` §1, §5 |
| `RUNTIME_STATE_MODEL.md` | `B1_DESIGN_BUNDLE_V3.md` §1 |
| `RUNTIME_STATE_AUTHORITY.md` | `B1_DESIGN_BUNDLE_V3.md` §9 |
| `RECOVERY_CONTRACT.md` | `B1_DESIGN_BUNDLE_V3.md` §5 |
| `IDEMPOTENCY_CONTRACT.md` | `B1_DESIGN_BUNDLE_V3.md` §2 |
| `CRASH_MATRIX.md` | `B1_DESIGN_BUNDLE_V3.md` §6 |
| `B1_DELIVERY_REPORT.md` | This index |
| `B1_DESIGN_DELIVERY_INDEX.md` | This index |

## Implementation Phases

| Phase | Scope |
|-------|-------|
| B4 | DB migrations | Persistence migrations derived from authoritative storage mapping. All 15 entities have explicit storage, constraints, keys, FK policy, Decimal precision, migration semantics. |
| B5 | Idempotency + dispatch registration |
| B6 | Risk state persistence |
| B7 | Recovery state machine |
| B8 | Provider HOLD contract |
| B9 | Market/account freshness fail-closed |
| B10 | Paper order/fill/position lifecycle |
| B11 | Reconciliation engine |
| B12 | Crash matrix tests |

## Acceptance Criteria

| AC | Description |
|----|-------------|
| AC1 | Every authoritative persisted state has explicit storage mapping, constraints, keys, FK policy, Decimal precision, and migration semantics |
| AC2 | 10 crash scenarios pass |
| AC3 | No duplicate logical execution |
| AC4 | Risk state survives restart |
| AC5 | Provider error → HOLD |
| AC6 | Stale data → HOLD |
| AC7 | Reconciliation detects mismatch |

## Decision

```
DESIGN READY: YES
IMPLEMENTATION READY: YES
LIVE: FORBIDDEN
```
