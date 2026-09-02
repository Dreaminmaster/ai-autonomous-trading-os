# Shadow Soak Evidence V1

## Outcome

ATOS can now turn one completed public-data Shadow supervisor session into an
exclusive, tamper-evident evidence package. The evaluator opens both SQLite
sources in read-only/query-only mode, binds the package to an exact
implementation commit, cross-checks the health snapshot, audit ledger, and
canonical lifecycle database, and independently recomputes simulated economics
from public mark prices and simulated fills.

This control evaluates operational evidence only. `SOAK_PASS` leads to
`INDEPENDENT_REVIEW`; it never authorizes or activates Live trading.

## Frozen production thresholds

- minimum observation duration: 604800 seconds (7 days);
- minimum completed cycles: 20160;
- minimum simulated fills: 30;
- maximum classified failure rate: 1%;
- maximum heartbeat gap: 180 seconds;
- maximum marked-equity drawdown: 10%;
- net simulated PnL after fees and slippage must be positive.

Any missing, malformed, overlapping, inconsistent, unsafe, or insufficient
source fails closed to `SOAK_FAIL / HOLD`.

## Evidence and custody

- health is re-read after database assessment and must remain byte-identical;
- runtime migrations must match the exact in-code migration plan;
- session closure, cycle counts, intent/risk counts, execution states, and
  simulated order/fill relationships are cross-checked;
- supervisor heartbeats must be contiguous and time-ordered;
- every accepted market snapshot must be official OKX public data;
- simulated fills are repriced from the matching public mark, fee, slippage,
  side, and final public marks to recompute net PnL and marked-equity drawdown;
- canonical ledger rows and runtime snapshots receive SHA-256 custody hashes;
- package output is no-overwrite and recursively covered by a SHA-256 manifest.

## Safety boundary

- no account or private API client is constructed;
- source databases are never mutated;
- only `okx_shadow / simulated` order and fill scope is accepted;
- Paper and external execution side effects are false;
- automatic activation is false;
- `authorizes_live=false` and Live is `FORBIDDEN` in both report and manifest.

## Validation

Base commit: `bad747faf6ac3015d45cbfe62ba8ff3037345fab`.

- full pytest: `1656 passed, 7 skipped`;
- focused Shadow evidence/supervisor/runtime/recovery tests: `48 passed`;
- changed-file Ruff check and format check: passed;
- all 27 implementation configuration JSON files parsed successfully;
- all 6 workflow YAML files parsed successfully;
- repository secret scan: no secret leakage detected;
- non-authoritative official OKX public-data smoke: one BTC-USDT supervisor
  cycle reached `STOPPED / BOUNDED_COMPLETE`, the evidence gate returned
  `SOAK_PASS` under smoke-only zero-duration/zero-fill thresholds, one
  simulated Shadow fill was independently reconciled, and account access,
  external execution, and Live authorization were all false;
- smoke evidence SHA-256:
  `b577440485a1833d23c87949fb94488958824339eb405d2452bc47215dfc0d4b`.

The temporary smoke directory was removed after verification. No workflow was
added or changed and no authoritative historical run was triggered.
