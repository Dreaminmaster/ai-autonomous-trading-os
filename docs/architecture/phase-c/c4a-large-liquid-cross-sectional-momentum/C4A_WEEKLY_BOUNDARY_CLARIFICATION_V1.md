# C4A Weekly Boundary Clarification V1

## 1. Status and precedence

- Stage: `C4A`
- Parent contract: `C4A_LARGE_LIQUID_CROSS_SECTIONAL_MOMENTUM_CONTRACT_V1.md`
- Parent addendum: `C4A_UNIVERSE_AND_MULTIPLE_TESTING_ADDENDUM_V1.md`
- Required base SHA: `72f35dd715874dc2e7c355511675dec29642b430`
- Clarification status: `DESIGN_ONLY`
- C4B: `CLOSED`
- Holdout: `HOLDOUT_CLOSED`
- Live: `FORBIDDEN`

This clarification is normative and controls where it differs from the parent addendum. It prevents a weekly DSR observation from reading the next independent window's opening candle and prevents a one-day terminal-stub entry in S3.

## 2. Full-week economic mark

OKX four-hour candle timestamps identify candle opens. The candle timestamped Sunday `20:00 UTC` closes at Monday `00:00 UTC`.

A full C4A weekly return observation therefore uses:

- starting equity: immediately after the scheduled Monday `00:00 UTC` rebalance;
- ending equity: marked at the close of the Sunday `20:00 UTC` candle;
- exactly `42` completed four-hour candles;
- no next-Monday candle open.

Frozen equation:

`weekly_net_return = equity_at_sunday_20_close / equity_after_monday_00_rebalance - 1`

The next Monday rebalance and its fee belong to the next economic week, not the prior weekly observation.

This convention avoids reading a timestamp at or beyond an independent window's exclusive boundary.

## 3. Final full weeks in S1 and S2

For S1:

- final scheduled risk decision: `2024-03-25T00:00:00Z`;
- final full-week ending mark: close of candle `2024-03-31T20:00:00Z`;
- S1 terminal liquidation occurs at that same final close and pays the applicable cost;
- the final S1 weekly DSR return includes that terminal liquidation cost;
- no `2024-04-01T00:00:00Z` price is read by the S1 economic cell.

For S2:

- final scheduled risk decision: `2024-06-24T00:00:00Z`;
- final full-week ending mark: close of candle `2024-06-30T20:00:00Z`;
- S2 terminal liquidation occurs at that same final close and pays the applicable cost;
- the final S2 weekly DSR return includes that terminal liquidation cost;
- no `2024-07-01T00:00:00Z` price is read by the S2 economic cell.

S2 and S3 still begin independently with `1000 USDT` at their own first window opens.

## 4. S3 terminal stub

S3 contains thirteen full Monday-to-Sunday weeks plus a final one-day stub beginning `2024-09-30T00:00:00Z`.

At the scheduled decision for `2024-09-30T00:00:00Z`:

- the target is forcibly `100%` cash for every policy;
- any existing position is liquidated at that open and pays the applicable cost;
- no new position may be opened;
- the prior Sunday signal may be retained for audit but cannot authorize risk because fewer than `42` economic candles remain before the exclusive boundary;
- the portfolio remains cash through the final `2024-09-30T20:00:00Z` candle close.

The final one-day stub:

- contributes its actual economic PnL, including the forced liquidation cost, to aggregate return, drawdown, turnover, contribution, and exposure metrics;
- is excluded from the DSR weekly sample because it is not a full 42-candle week.

## 5. Exact DSR sample counts

The full-week DSR sample remains exactly:

- S1: `13` observations;
- S2: `13` observations;
- S3: `13` observations;
- total: `39` observations per policy.

Each observation is formed entirely from timestamps inside its independent economic window.

## 6. Scheduled decision counts

The audit schedule still retains:

- S1: `13` scheduled risk decisions;
- S2: `13` scheduled risk decisions;
- S3: `14` scheduled decisions, of which the final decision is forced cash;
- total: `40` decision records.

Activity metrics distinguish:

- `scheduled_decision_count`: every one of the 40 audit decisions;
- `scheduled_active_rebalance_count`: decisions whose frozen target after the boundary rule has nonzero asset weight;
- `traded_rebalance_count`: decisions with strictly positive traded notional.

The eligibility gate named “scheduled active rebalances” uses `scheduled_active_rebalance_count`, not total decision records and not traded-rebalance count.

## 7. Required tests

Implementation tests must prove:

- weekly returns end at the Sunday `20:00 UTC` candle close;
- S1 does not read the `2024-04-01T00:00:00Z` open;
- S2 does not read the `2024-07-01T00:00:00Z` open;
- the final S1 and S2 weekly DSR observations include terminal liquidation costs;
- the `2024-09-30T00:00:00Z` S3 decision is forced cash for all policies;
- the S3 stub is excluded from all 39-value DSR arrays but included in ordinary economic metrics;
- the 40 decision records and 39 DSR observations are exact;
- no C4B or holdout timestamp is read.

`C4A_DESIGN_ONLY` / `C4B_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
