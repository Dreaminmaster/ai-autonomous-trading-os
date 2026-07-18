# C3A Cooldown Clarification V1

## Authority

This clarification is normative and forms part of the preregistered C3A design together with:

- `C3A_RESIDUAL_MEAN_REVERSION_CONTRACT_V1.md`
- `C3A_EXECUTION_ACCOUNTING_ADDENDUM_V1.md`

It resolves only the wording of the six-bar cooldown. It changes no policy parameter, cost, gate, ranking rule, research window, or safety state.

## Exact cooldown indexing

If an exit executes at the open of bar `k`:

- bars `k` through `k+5` are the six cooldown bars;
- signals evaluated at closes `k` through `k+4` are ignored;
- the close of bar `k+5` completes the sixth cooldown bar;
- a qualifying signal evaluated at close `k+5` may execute at open `k+6`.

This clarification controls over the sentence in section 6 of `C3A_EXECUTION_ACCOUNTING_ADDENDUM_V1.md` that states signals at all six cooldown-bar closes are ignored.

`C3B_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
