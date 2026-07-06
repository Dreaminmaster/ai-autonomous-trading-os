# Unresolved Decisions — B1.2 Design

**Date**: 2026-07-06  
**Status**: Deferred to later phases

---

| ID | Decision | Options | Current Default | Deferred To | Reason |
|----|----------|---------|-----------------|-------------|--------|
| D1 | Position accounting method | Average cost / FIFO / LIFO | **Average cost (V1 default)** | Phase B5 | FIFO needs per-lot tracking; unnecessary for initial paper runtime |
| D2 | Partial fill timeout policy | Auto-cancel after N seconds / Keep open / Operator decides | **Keep open (paper only)** | Phase B10 | Paper execution has no real latency; live needs exchange-specific policy |
| D3 | Max open positions per symbol | 1 / N / Unlimited | **1 (current behavior)** | Phase B6 | Risk gate enforcement needs position count |
| D4 | Fee allocation on partial fills | Proportional by qty / First fill pays all / Weighted | **Proportional** | Phase B10 | Standard industry practice; needs verification with OKX |
| D5 | Live enable protocol | Single flag / Multi-signature / Operator approval chain | **Multi-signature (deferred)** | Phase B10 | Current: guarded executor is hardcoded False; live needs explicit enable |
