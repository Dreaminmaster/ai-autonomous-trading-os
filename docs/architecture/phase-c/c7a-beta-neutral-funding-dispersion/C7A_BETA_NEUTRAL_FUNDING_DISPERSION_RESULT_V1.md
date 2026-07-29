# C7A Beta-Neutral Funding Dispersion — Authoritative Result V1

## 1. Final classification

C7A completed with valid official-public source custody, a complete historical replay, and an independent source-level recomputation. Its economic result is negative.

- Stage: `C7A_H1_H5_FINAL_CLASSIFICATION`
- Classification: `ECONOMIC_FAIL`
- Selected policy: `null`
- Data custody: `PASS`
- Independent recomputation: `PASS`
- Retuning: `NOT_AUTHORIZED`
- Rerun after economic inspection: `NOT_AUTHORIZED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This is not a data or program failure. The frozen candidate failed its preregistered economic conditions on valid real data. C7A must not be modified, reclassified, or rerun in response to the observed result.

## 2. Exact implementation and run authority

- Repository: `Dreaminmaster/ai-autonomous-trading-os`
- Implementation commit: `5d017cd7931ddb2b71cfdf31d87698f4358b6cf1`
- Authoritative workflow run: `30444031200`, attempt `1`
- Authoritative run identifier in evidence: `github-30444031200-1`
- C7A job: `90550292188`
- Workflow URL: <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/30444031200>

The checkout evidence bound both the requested implementation SHA and observed repository head to `5d017cd7931ddb2b71cfdf31d87698f4358b6cf1`, with a clean tracked worktree.

The C7A job conclusion is `failure` because the frozen evaluator returned a non-zero exit for `ECONOMIC_FAIL`. The public capture step succeeded, the evidence upload succeeded, and the failure must not be described as an infrastructure error.

The same workflow dispatch also completed the ordinary product gates:

| Job | Job ID | Conclusion |
|---|---:|---|
| ATOS tests | `90549888743` | `SUCCESS` |
| Freqtrade | `90549888699` | `SUCCESS` |
| Validation summary | `90566751122` | `SUCCESS` |
| C7A H1–H5 economic gate | `90550292188` | `ECONOMIC_FAIL` |

## 3. Immutable artifact evidence

The authoritative C7A artifact is:

- Artifact ID: `8720825035`
- Name: `c7a-h1-h5-5d017cd7931ddb2b71cfdf31d87698f4358b6cf1-1`
- ZIP digest: `sha256:6f62bb79edb8bc7b19ed04f5be294e0c6b3a6cc3a452dddbfe6a42ba11d86df4`
- Created: `2026-07-29T10:39:10Z`
- Scheduled expiry: `2026-10-27T10:32:00Z`

Independent local verification of the downloaded archive established:

- capture manifest: `678 / 678` retained files matched size and SHA-256;
- evidence manifest: `14 / 14` retained files matched size and SHA-256;
- capture manifest file SHA-256: `5a7e8ec011f711b35afe9e2ce4e1daa129db731590ac9bf1618f2e6fa11fa8ec`;
- evidence manifest file SHA-256: `0b8cbae9ab6539e19446444ac471bb088f1cdfd2125bce74a1f6f1c3fd612b8f`;
- capture source kind: `OFFICIAL_PUBLIC_OKX`;
- authenticated requests: `false`;
- account data: `false`;
- order data: `false`;
- paper side effects: `false`;
- shadow side effects: `false`.

Related successful artifacts from the same dispatch are retained separately:

| Artifact | ID | Digest |
|---|---:|---|
| `atos-validation` | `8720686405` | `sha256:1dca87b9993b3584e14d623e52d8e3343feb0686d74a7c95422e0bced7a4613a` |
| `freqtrade-validation` | `8722729977` | `sha256:81513654149fc68e58fc4093e763e2953c9f151d464e4feb98e00f822f6233e3` |
| `validation-summary` | `8722752496` | `sha256:227ef787692a5c460614a8b66efd813ea08dd65bf01af8fdd309c46e0d810128` |

## 4. Frozen historical windows

All five preregistered windows were evaluated without best-window selection:

| Window | Start inclusive | End exclusive | Frozen decision |
|---|---|---|---|
| `H1` | `2024-01-01T00:00:00Z` | `2024-07-01T00:00:00Z` | `REJECTED` |
| `H2` | `2024-07-01T00:00:00Z` | `2024-12-30T00:00:00Z` | `REJECTED` |
| `H3` | `2024-12-30T00:00:00Z` | `2025-06-30T00:00:00Z` | `REJECTED` |
| `H4` | `2025-06-30T00:00:00Z` | `2025-12-29T00:00:00Z` | `REJECTED` |
| `H5` | `2025-12-29T00:00:00Z` | `2026-06-29T00:00:00Z` | `REJECTED` |

Every window retained a producer result and a physically separate independent review. Each independent review reported `status=PASS`, `errors=[]`, and `primitive_source_recompute_performed=true` with a passing recomputation.

## 5. Economic result

The candidate evaluated `130` weekly decisions and opened no position:

| Fail-closed reason | Count |
|---|---:|
| `PROJECTED_CARRY_BELOW_MINIMUM` | `109` |
| `BETA_OUT_OF_RANGE` | `12` |
| `R_SQUARED_BELOW_MINIMUM` | `9` |

The highest observed frozen candidate `projected_carry_28d` was `0.0011858001187479272`, below the preregistered strict threshold `0.00225`. Consequently:

- active weeks: `0`;
- candidate pooled net return at `1.0x`, `1.5x`, and `2.0x` costs: `0.0`;
- selected window count: `0`;
- all five unchanged window gates: failed;
- overall verdict: `ECONOMIC_FAIL`.

The predeclared always-on funding-rank comparator produced the following window returns:

| Window | Comparator net return |
|---|---:|
| `H1` | `-0.04788879677380786` |
| `H2` | `0.012644227385819162` |
| `H3` | `0.03235392900299838` |
| `H4` | `0.04108315560226483` |
| `H5` | `-0.009430460130966045` |

Its pooled return was `0.026463641471346167`, but it was negative in `H1` and `H5`. It was a comparator, not an eligible candidate. Promoting it after observing these results would be a prohibited post-hoc strategy change.

## 6. Interpretation and closed actions

C7A did what the safety contract required: it stayed in cash when the frozen carry, beta, or fit conditions did not qualify. That behavior is deterministic and safe, but it supplies no positive-expectation evidence.

The result does not establish that funding dispersion can never work. It rejects only the exact C7A hypothesis, instruments, schedule, feature lookbacks, thresholds, sizing, costs, and gates on H1–H5.

The following actions are closed:

1. lowering `minimum_projected_carry_28d` after seeing H1–H5;
2. weakening beta, fit, activity, concentration, stability, cost, or comparator gates;
3. promoting the always-on comparator;
4. selecting only positive windows;
5. rerunning C7A with modified constants on the same frozen windows;
6. opening C7B, Paper, or Shadow for C7A;
7. using private account APIs, order APIs, or live execution.

Any next research candidate must be a separately preregistered, structurally distinct hypothesis with its own fixed data boundary and explicit multiple-testing accounting. It may use the C7A result only as a disclosed prior observation, never as hidden evidence that a replacement should pass.

## 7. Final state

`C7A_H1_H5_COMPLETE`

`C7A_ECONOMIC_FAIL`

`SELECTED_POLICY_NULL`

`RETUNING_NOT_AUTHORIZED`

`RERUN_AFTER_INSPECTION_NOT_AUTHORIZED`

`C7B_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
