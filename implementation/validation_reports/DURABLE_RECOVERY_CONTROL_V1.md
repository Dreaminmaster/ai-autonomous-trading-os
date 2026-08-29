# Durable Recovery Control V1

## Outcome

ATOS now provides an explicit, token-bound recovery controller for incomplete
Paper and Shadow simulation state. Inspection is read-only. Mutation requires
the exact SHA-256 token for the current durable snapshot plus an operator
reason, and is committed atomically with a durable recovery record.

## Allowed resolutions

- complete a cycle whose deterministic simulated fill or terminal rejection is
  already authoritative;
- abandon a `DISPATCH_COMMITTED` / `PRE_DISPATCH_PROVEN` simulated attempt only
  when no dispatch timestamp, order, or fill exists.

All other states remain `RECOVERY_REQUIRED`. The controller performs no network
reconciliation, has no account or private API dependency, and exposes no Live
mode.

## Verification

- full pytest: `1631 passed, 7 skipped`;
- inspection produces no state mutation;
- stale or incorrect confirmation tokens roll back with zero mutation;
- confirmed recovery atomically terminalizes the pre-dispatch simulation,
  completes and journals the cycle, and records a resolved recovery state;
- unsupported `PREPARED` state remains locked;
- Live is rejected before database access;
- Ruff, all workflow YAML, and the secret scan passed locally; GitHub evidence
  is recorded by the pull request validation workflow.
