# C5A Program Holdout Reclassification V1

## 1. Normative status

This document is a normative governance clarification for C5A.

It does not open C5B, authorize implementation, inspect market data, or change any C5A candidate rule. It explains why the fresh period is prospectively reclassified after prior candidates were frozen as rejected.

## 2. Prior authority

The prior research stages are frozen negative results:

- C0C: `REJECTED`; development test and its reserved holdout were never opened;
- C1A: `REJECTED`; confirmation remained closed;
- C2A: `REJECTED`; confirmation remained closed;
- C3A: `REJECTED`; confirmation remained closed;
- C4A: `REJECTED`; confirmation remained closed.

No prior rejected candidate may be revived, retuned, or evaluated on the C5A/C5B periods.

## 3. Why reclassification is necessary

The repeated 2024 Phase C screen has already informed multiple structural hypotheses. Continuing to select another strategy on that same economic interval would increase program-level selection bias.

C0C reserved `2025-07-01` through `2026-07-01` as a one-time holdout, but C0C failed before the gate that could open that holdout. The reservation therefore never produced an observation and no surviving C0C candidate exists to confirm.

This C5A design prospectively retires that unused reservation for C0C and creates a new split for a different, single-candidate thesis before any C5A market-data access.

## 4. Exact reclassification

### 4.1 Unused boundary gap

The interval:

```text
2025-07-01T00:00:00Z
through
2025-07-07T00:00:00Z
```

is not part of C5A economic performance. It may be retained only as prior-history context needed to calculate the first decision's completed lookback values.

### 4.2 C5A fresh development screen

```text
2025-07-07T00:00:00Z
through
2026-01-05T00:00:00Z exclusive
```

This interval becomes development data only for the exact C5A candidate and its non-selectable ablation after this design is merged.

Once any C5A implementation reads this interval, it can never again be described as an untouched holdout for C0C or another earlier stage.

### 4.3 C5B reserved confirmation

```text
2026-01-05T00:00:00Z
through
2026-07-06T00:00:00Z exclusive
```

This interval remains statistically and economically closed during C5A.

The extension from `2026-07-01` to the clean Monday boundary `2026-07-06` is newly reserved by this contract and must also remain unread by C5A.

## 5. Preconditions before implementation

Before any C5A data acquisition, implementation evidence must verify from frozen repository authority that:

- C0C did not open development test or holdout;
- C1B, C2B, C3B, and C4B remained closed;
- no earlier authoritative result selected a policy for confirmation;
- C5A is the only stage authorized to consume the reclassified development interval;
- the exclusive C5B boundary is encoded in every data guard and evidence surface.

Failure to verify those conditions blocks C5A market-data access.

## 6. Program-level claim boundary

The reclassification creates a fresh test for one preregistered C5A candidate; it does not erase the broader research history.

A C5A pass must still be described as:

- one candidate;
- one exchange's public data;
- three spot assets;
- one fresh 26-week development interval;
- a separately unopened 26-week confirmation interval;
- subject to future C5B confirmation before paper or shadow eligibility.

A C5A rejection ends this exact thesis. It does not authorize another candidate to reuse the same C5A interval as fresh data.

## 7. Safety state

`C5A_DESIGN_ONLY`

`C5A_DATA_UNREAD`

`C5B_CLOSED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
