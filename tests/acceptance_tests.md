# Acceptance Tests

## General

- [ ] Repository can be cloned by Harness.
- [ ] Harness reads AGENTS.md before implementation.
- [ ] No API key is present in repository files.
- [ ] Default mode is not live.
- [ ] Live execution is disabled by default.

## AI decision tests

- [ ] Valid AI JSON passes schema validation.
- [ ] Invalid AI JSON becomes HOLD.
- [ ] Missing thesis becomes HOLD.
- [ ] Missing stop loss for BUY/SELL becomes rejected.
- [ ] Low confidence trade becomes HOLD or rejected.

## Risk tests

- [ ] Non-whitelisted symbol is rejected.
- [ ] Position size above limit is rejected or reduced.
- [ ] Daily loss breach pauses trading.
- [ ] Kill switch blocks new orders.
- [ ] Duplicate order ID is rejected.
- [ ] Stale market data is rejected.

## Paper execution tests

- [ ] Paper order does not call OKX order API.
- [ ] Fees are applied.
- [ ] Slippage is applied.
- [ ] Position is updated after simulated fill.
- [ ] Ledger records trade intent, risk decision, and execution result.

## Evaluation tests

- [ ] Backtest processes data chronologically.
- [ ] Future data is unavailable at simulated time T.
- [ ] Walk-forward split separates train and test windows.
- [ ] Fee/slippage stress changes results.
- [ ] Strategy with poor out-of-sample performance is not promoted.

## Review tests

- [ ] Daily review identifies winning and losing strategies.
- [ ] Review output does not directly change risk policy.
- [ ] Strategy weight changes are bounded.
- [ ] Paused strategies are not selected by AI trader.

## Governance tests

- [ ] Attempt to enable live mode requires explicit approval.
- [ ] Attempt to enable withdrawal permission fails policy check.
- [ ] Secret printed in log triggers failure.
- [ ] Provider unavailable in high-risk task defaults to HOLD.
