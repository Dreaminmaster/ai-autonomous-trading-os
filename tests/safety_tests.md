# Safety Tests

These tests must pass before any live mode work.

## Secret safety

- [ ] Scan repository for patterns resembling API keys.
- [ ] Ensure `.env` is gitignored in implementation repo.
- [ ] Ensure logs redact secrets.
- [ ] Ensure exception traces do not include API keys.

## OKX permission safety

- [ ] Reject API key policy that includes withdrawal permission.
- [ ] Reject API key policy that includes transfer permission unless separately approved.
- [ ] Reject live mode if account is not configured as a small isolated sub-account.
- [ ] Reject live mode if IP whitelist is required but missing.

## LLM safety

- [ ] LLM cannot call execution adapter directly.
- [ ] LLM cannot change risk config.
- [ ] LLM cannot enable live mode.
- [ ] LLM cannot remove kill switch.
- [ ] LLM cannot delete audit logs.

## Trading safety

- [ ] Missing stop loss rejects risk-taking trade.
- [ ] Oversized trade rejected.
- [ ] Overtrading rejected.
- [ ] Consecutive loss limit pauses trading.
- [ ] Max drawdown breach triggers kill switch.
- [ ] Reconciliation mismatch pauses trading.

## Failure defaults

Every ambiguous failure defaults to no new trade:

- [ ] Provider unavailable -> HOLD.
- [ ] Data stale -> HOLD.
- [ ] Schema invalid -> HOLD.
- [ ] Risk manager exception -> PAUSE.
- [ ] Ledger write failure -> PAUSE.
- [ ] OKX status unclear -> PAUSE and reconcile.
