# B1 — Runtime State & Safety Kernel

**Version**: V3
**Date**: 2026-07-06
**Status**: DESIGN ONLY — 0 production code changes
**Live**: FORBIDDEN

---

## AUTHORITATIVE DOCUMENTS

The documents in this directory are the **sole authority** for Phase B B1 design. All previous versions in `archive/` are superseded.

| # | Document | Description |
|---|----------|-------------|
| 1 | `B1_DESIGN_BUNDLE_V3.md` | Complete design: 14 state entities, idempotency V3, dispatch transaction contract V3, order lifecycle V3, recovery V3, crash matrix V3 (10 scenarios), DB precision rules, clock contract, authority hierarchy, open decisions |
| 2 | `EXECUTION_TRANSACTION_CONTRACT_V2.md` | Transaction boundary, 5-phase crash coverage, retry rules, network error classification, guarantees |
| 3 | `B1_DESIGN_DELIVERY_INDEX_V3.md` | Master index: active documents, superseded documents, implementation phases B4-B12, 6 acceptance criteria |
| 4 | `DESIGN_CHANGELOG_V2_TO_V3.md` | 12 key changes from V2 to V3 |
| 5 | `UNRESOLVED_DECISIONS.md` | 5 open decisions deferred to later phases |

## SUPERSEDED DOCUMENTS

All documents in `archive/` are **superseded** and marked `DO NOT IMPLEMENT`. They are retained for historical reference only.

| Document | Superseded By |
|----------|--------------|
| `archive/ARCHITECTURE_DISCOVERY_REPORT.md` | `B1_DESIGN_BUNDLE_V3.md` |
| `archive/ARCHITECTURE_DISCOVERY_CORRECTIONS.md` | `B1_DESIGN_BUNDLE_V3.md` §1, §5 |
| `archive/RUNTIME_STATE_MODEL.md` | `B1_DESIGN_BUNDLE_V3.md` §1 |
| `archive/RUNTIME_STATE_AUTHORITY.md` | `B1_DESIGN_BUNDLE_V3.md` §9 |
| `archive/RECOVERY_CONTRACT.md` | `B1_DESIGN_BUNDLE_V3.md` §5 |
| `archive/IDEMPOTENCY_CONTRACT.md` | `B1_DESIGN_BUNDLE_V3.md` §2 |
| `archive/CRASH_MATRIX.md` | `B1_DESIGN_BUNDLE_V3.md` §6 |
| `archive/B1_DELIVERY_REPORT.md` | `B1_DESIGN_DELIVERY_INDEX_V3.md` |
| `archive/B1_DESIGN_DELIVERY_INDEX.md` | `B1_DESIGN_DELIVERY_INDEX_V3.md` |

## Decision

```
DESIGN READY: YES
IMPLEMENTATION READY: YES
LIVE: FORBIDDEN
```
