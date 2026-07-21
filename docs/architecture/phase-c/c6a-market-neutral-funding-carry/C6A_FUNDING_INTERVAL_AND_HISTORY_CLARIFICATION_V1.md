# C6A Funding Interval and History Clarification V1

## 1. Normative purpose

This clarification is normative and supersedes any narrower interpretation in the C6A contract.

The sentence in Section 3 of `C6A_MARKET_NEUTRAL_FUNDING_CARRY_CONTRACT_V1.md` that mentions 1-, 2-, 4-, and 8-hour funding intervals describes the current standard set and is not an exhaustive historical enumeration.

OKX documentation also records historical use or possible use of 6-hour funding intervals. Therefore:

- no fixed set of interval lengths is authoritative for C6A;
- the ordered sequence of retained `fundingTime` values and each record's `realizedRate` are authoritative;
- every interval is derived from consecutive actual settlement timestamps;
- no settlement count, annualization multiplier, expected daily count, or missing-record decision may assume 3 settlements per day or any fixed interval;
- 1-, 2-, 4-, 6-, 8-hour, or other observed schedules are accepted only when exact public records are continuous and internally consistent;
- unexplained gaps, duplicate settlements, contradictory rates, or an interval that cannot be reconciled to the public archive fail closed.

## 2. Historical-source authority

`GET /api/v5/public/funding-rate-history` currently returns at most three months of history. It cannot be used as the sole source for the C6A development interval.

For C6A:

1. OKX downloadable historical funding-rate files are the primary source for the full development interval;
2. the public funding-rate-history endpoint may be used only for available overlap verification and schema checks;
3. overlap records must agree exactly on instrument, settlement timestamp, and realized rate after canonical decimal normalization;
4. disagreement fails before economic evaluation;
5. no private endpoint or account data may fill a public-history gap.

## 3. Funding signal and accounting consequence

The existing formulas remain unchanged:

```text
funding_sum_28d = sum(actual realizedRate records in the exact lookback)
positive_funding_share_28d = positive actual settlements / all actual settlements
```

Each actual settlement contributes once. Variable frequency changes the observed number of settlements but does not authorize rescaling, interpolation, or synthetic settlements.

Funding PnL also remains:

```text
funding_pnl = actual short position value * actual realizedRate
```

at each exact retained settlement timestamp.

## 4. Claim boundary

This clarification adds no candidate, parameter, data access, implementation, or economic result. It exists only to prevent a historically incorrect fixed-frequency assumption.

`C6A_DESIGN_ONLY`

`C6A_ECONOMIC_RESULT_NOT_RUN`

`C6B_CLOSED`

`C5B_CLOSED_AND_UNTOUCHED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
