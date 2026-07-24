# C7A mark-return alignment clarification V1

## Authority

This clarification is normative and takes precedence over any ambiguous reading of the prospective-start and beta-input language in `C7A_BETA_NEUTRAL_FUNDING_DISPERSION_CONTRACT_V1.md`.

## Exact prospective starts

- mark-price seed candle start: `2026-07-26T23:00:00Z`
- funding and trade-candle prospective start: `2026-07-27T00:00:00Z`
- first scored decision: `2026-08-24T00:00:00Z`

The one seed candle exists only to compute the first close-to-close mark return. It is preregistered before collection and does not reopen C5B or any earlier historical interval.

## Exact return construction

For a decision at time `t`, retain exactly `673` consecutive completed one-hour mark candle closes for each asset, from the candle timestamped `t - 28 days - 1 hour` through the candle timestamped `t - 1 hour`, inclusive.

Construct exactly `672` close-to-close log returns:

```text
r_i(k) = log(mark_close_i(k) / mark_close_i(k - 1))
```

The return timestamps are the later close timestamps and must cover exactly `[t - 28 days, t)` with no gap, duplicate, interpolation, open-to-close substitution, or boundary reuse.

The beta validity condition is therefore:

- exactly `673` consecutive mark closes per asset;
- exactly `672` aligned close-to-close returns per asset;
- all remaining beta and `R^2` conditions from the main contract unchanged.

## Comparator alignment

`AlwaysOnFundingRankComparator` and `EqualNotionalFundingRankComparator` use the same exact data-integrity and beta-validity checks as the selectable candidate. When those checks fail, the comparator holds cash for that decision rather than inventing or carrying forward a beta.

## Boundary

No real C7A row, seed candle, partial performance, or network execution is authorized by this clarification. It corrects only the frozen design semantics.

`C7A_DESIGN_ALIGNMENT_CLARIFIED` / `673_CLOSES_672_RETURNS` / `NO_REAL_DATA_AUTHORIZED` / `LIVE_FORBIDDEN`
