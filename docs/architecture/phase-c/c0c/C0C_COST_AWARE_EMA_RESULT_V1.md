# C0C Cost-Aware EMA Result V1

Status: `REJECTED`

This document freezes the authoritative outcome of the first preregistered Phase C strategy candidate. It records a valid negative economic result; it is not permission to weaken gates or reuse stale evidence.

## Authority

- Candidate: `c0c-cost-aware-ema-v1`
- Strategy: `C0CCostAwareEMA`
- PR: `#39`
- Candidate source SHA: `c93c548ed7d22c90fbc729dbb3022ee9e7c579c1`
- Merge commit on `main`: `ba9b02d63ae8fb67b99307191b9e58cd014d8dd6`
- Authoritative workflow: `C0C Cost-Aware EMA Development #7`
- Workflow run: `29472584256`
- Workflow/merge SHA: `8193609e8b96618b15f6493c8cc4359c73ce2b86`
- Artifact: `8365664976`
- Artifact digest: `sha256:8a88f7b2644406f84188a34184395b2c7d66a79c733b76db622c210591ad36c5`
- Post-run independent COMMENT review: `4710913931`

## Evidence integrity

The authoritative run completed every workflow step successfully. The retained evidence established:

- exact-run/source/workflow binding;
- six-cell data-boundary and coverage PASS;
- removal of 1,290 exchange API overshoot rows before any research read;
- zero post-boundary rows, gaps, or duplicates after sanitization;
- BTC/ETH/SOL recursive analysis PASS at startup `1499`;
- explicit no-lookahead proof;
- Freqtrade `2026.6`;
- three 200-epoch Hyperopt runs with seed `20260715`, optimization fee `0.00225`, minimum 30 training trades, and two workers;
- deterministic top-three shortlist reproduction for every fold;
- 27 validation backtests at expected, 1.5x, and 2x costs;
- per-trade fee binding;
- 580 structural, command, hash, shortlist, gate, and safety checks with zero errors.

Evidence integrity PASS does not imply economic PASS.

## Frozen economic decision

The preregistered rule required every development fold to select an eligible validation candidate before development-test could open.

| Fold | Decision | Selected candidate | Expected-cost validation | 1.5x-cost validation | Notes |
|---|---|---|---:|---:|---|
| 1 | `REJECTED` | none | best candidate `-2.5008%`, PF `0.1954` | `-2.9824%` | all three candidates failed positive-net, 1.5x-cost, and PF `>=1.10` gates |
| 2 | selected | `rank_01_epoch_114` | `+2.9201%`, PF `3.0094` | `+2.6679%` | 8 trades |
| 3 | selected | `rank_01_epoch_115` | `+2.9568%`, PF `2.2161` | `+2.7073%` | 9 trades |

Final state:

```text
status = REJECTED
development_economic_pass = false
development_test_opened = false
holdout_state = HOLDOUT_CLOSED
live = FORBIDDEN
```

## Diagnostic interpretation

The following is diagnostic guidance for the next preregistered candidate, not a retroactive change to C0C:

1. C0C was not rejected only because of fees. Fold 1 was already grossly weak at the expected cost, with low profit factor and no eligible candidate.
2. Performance was regime-dependent. The same general parameter region produced robust positive validation in folds 2 and 3 but failed in fold 1.
3. Fold 1 produced zero BTC trades and losses concentrated in ETH/SOL, especially SOL. This exposes broad-market regime and pair-breadth risk.
4. Validation samples were sparse. Selected folds had only 8-9 trades, so a next candidate must improve evidence breadth rather than optimize a handful of trades.
5. Retuning the same four EMA entry parameters on the same development history would be an overfitting response. The next stage must compare genuinely different, fixed strategy families before any new optimization.

## Consequences

- Do not rerun the rejected exact SHA.
- Do not lower economic thresholds.
- Do not open C0C development-test or holdout.
- Do not describe the candidate as profitable or passed.
- Preserve the implementation and evidence framework because they are reusable research infrastructure.
- Advance through a separately frozen strategy-family screen.

`HOLDOUT_CLOSED` / `LIVE FORBIDDEN`
