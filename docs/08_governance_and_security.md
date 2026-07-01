# 08 Governance and Security Layer

## Purpose

Governance controls prevent the system from becoming an unsafe autonomous financial actor.

## API permission policy

OKX keys must be separated by purpose.

Recommended phases:

1. Read-only key for market/account inspection.
2. Paper trading with no exchange trading key.
3. Shadow mode with read-only key.
4. Tiny live spot sub-account with trade-only key.
5. Larger live modes only after documented evidence.

Hard requirements:

- no withdrawal permission,
- no fund transfer permission by default,
- IP whitelist when possible,
- sub-account for live trading,
- separate live/paper configs,
- rotate keys after incidents,
- never commit secrets.

## Secrets policy

Secrets may be stored only in:

- environment variables,
- local `.env` outside Git,
- OS keychain,
- secure secret manager.

Forbidden:

- source code,
- GitHub,
- README,
- test fixtures,
- logs,
- reports,
- prompts,
- database content,
- screenshots.

## Config versioning

All risk and execution configs should be versioned.

Config changes should produce:

- old hash,
- new hash,
- reason,
- requester,
- approval state,
- effective timestamp.

## Mode switch policy

Moving between modes requires checks.

### design -> backtest

Requires:

- schemas defined,
- risk policy draft,
- data source plan.

### backtest -> paper

Requires:

- backtest engine passes tests,
- risk manager passes tests,
- strategy candidates implemented,
- realistic fees/slippage configured.

### paper -> shadow

Requires:

- paper trading stability report,
- no secret leakage,
- read-only OKX adapter working.

### shadow -> live

Requires:

- explicit human approval,
- sub-account,
- trade-only API key,
- no withdrawal permission,
- kill switch tested,
- reconciliation tested,
- tiny capital limit.

## Audit requirements

Every decision needs an audit trail.

Minimum audit record:

- timestamp,
- mode,
- model/provider,
- prompt template version,
- input data hash,
- output JSON hash,
- schema result,
- risk result,
- execution result,
- ledger result,
- review status.

Audit logs should be append-only where possible.

## Human approval gates

Human approval is required for:

- live mode,
- increasing capital limit,
- enabling derivatives,
- enabling leverage,
- changing max loss limits,
- changing API permissions,
- deleting logs,
- disabling kill switch,
- promoting a new strategy to live.

## Incident response

Incident triggers:

- unexpected live order,
- reconciliation mismatch,
- max loss breach,
- duplicate order,
- API error loop,
- stale market data,
- model output corruption,
- key exposure suspicion.

Incident actions:

1. pause new orders,
2. preserve logs,
3. snapshot account state,
4. write incident report,
5. require manual reset.

## Model/provider governance

Provider changes must be logged.

For high-risk decisions, if the preferred high-quality model is unavailable:

- do not silently downgrade,
- default to HOLD or paper-only,
- write provider incident note.

## Public repository warning

This repository is public. Do not add:

- API keys,
- account IDs,
- private strategy parameters you do not want public,
- real balances,
- private trade history,
- seed phrases,
- exchange screenshots containing secrets.
