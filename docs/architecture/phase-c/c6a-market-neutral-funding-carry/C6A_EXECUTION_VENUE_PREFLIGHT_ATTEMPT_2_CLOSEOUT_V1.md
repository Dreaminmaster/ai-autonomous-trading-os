# C6A execution-venue preflight attempt 2 closeout

## Frozen evidence

The user returned the attempt-2 archive, uploaded as `-c6a-execution-venue-preflight-2.zip`, with independently recomputed SHA-256:

`2985f99e68ded3aed7a938cfdccee9eac4754b82102f4955233fd330f4f3f021`

Archive size is `6621` bytes. It contains eight JSON files: seven files under `c6a-execution-venue-preflight-2/` and the adjacent `.c6a-execution-venue-preflight-2.invocation-started.json` marker. There are no duplicate paths, path-traversal entries, or symbolic links.

The inner manifest declares six non-manifest output files. Independent recomputation confirms exact path, byte-size, and SHA-256 agreement for all six entries, with no extra or missing output files.

Frozen implementation identity:

- implementation/source SHA: `ead9251a97d077beea5a647370f5a38e97906d49`
- validated remediation merge ref: `refs/pull/90/merge@68594e4eb24f5dca27d7116b85f2d5b7cae24720`
- execution mode: `LOCAL_USER_CONTROLLED`
- venue label: `openminis-local-user-controlled-direct-attempt-2`
- invocation ID: `24ec7fea9df34f60900fbb43465e6264`
- invocation started at: `2026-07-24T12:37:42.282500+00:00`

## Invocation and venue integrity

The adjacent marker and packaged `invocation_record.json` are byte-for-byte identical. Their SHA-256 is:

`0c22f5d980d4768195f3f91ca29ffbe2b4dbcd205d47c63f6e582c796735639e`

That digest and invocation ID match `venue_attestation.json`. The attestation records:

- no proxy environment keys;
- no cookie or authorization environment keys;
- `GITHUB_ACTIONS=false`;
- Python `3.12.13` / CPython;
- Linux `aarch64`, release `4.20.69-ish`.

The retained evidence therefore describes an OpenMinis-controlled Linux venue, not a macOS execution. The authorization permitted `LOCAL_USER_CONTROLLED`; the platform observation is retained so it is not later mistaken for proof about a Mac venue.

The package contains one durable invocation record. Because a rejected later process start would fail before creating a new retained record, the archive cannot independently prove the total number of CLI process launches. It does prove one consumed invocation identity and provides no evidence of a second network matrix execution.

## Independent findings

The frozen eight-candidate matrix is complete. Every candidate records:

- `execution_status=FAIL`;
- `scope_status=NOT_EVALUATED`;
- `failure_code=FAIL_SOURCE_SCOPE_PROBE_EXECUTION`;
- no final URL;
- no retained response bytes.

Transport observations are:

- six `Broken pipe` failures;
- two `Connection reset by peer` failures.

`probe_result.json` correctly records:

- status: `ERROR`;
- result: `FAIL_SOURCE_SCOPE_PROBE_EXECUTION`;
- completed candidates: `0`;
- failed candidates: `8`.

The physically separate probe review returns `PASS` and recomputes the same execution-failure result. The venue review also returns `PASS` and recomputes:

`REJECTED_EXECUTION_FAILURE`

This confirms that the attempt-1 semantic defect was remediated: transport failure is no longer accepted as a GLOBAL source-scope decision.

The exact runner implementation returns exit `3` for this retained state. The actual shell exit code was not stored inside the archive, so the package proves the result state and deterministic expected exit behavior, not an independently observed process exit value.

## Accepted classification

- `VENUE_PREFLIGHT_ATTEMPT_2_PACKAGE_INTEGRITY_VERIFIED`
- `VENUE_PREFLIGHT_ATTEMPT_2_DURABLE_INVOCATION_BINDING_VERIFIED`
- `VENUE_PREFLIGHT_ATTEMPT_2_TRANSPORT_FAILURE_CONFIRMED`
- `VENUE_PREFLIGHT_EXECUTION_SEMANTICS_REMEDIATION_VERIFIED`
- `VENUE_PREFLIGHT_ATTEMPT_2_NO_SCOPE_DECISION`
- `GLOBAL_SCOPE_AVAILABLE_NOT_PROVEN`
- `GLOBAL_SCOPE_UNAVAILABLE_NOT_PROVEN`
- `SOURCE_AUTHORITY_GATE_NOT_PASSED`
- `ATTEMPT_2_CLOSED_NO_RERUN`
- `THIRD_FULL_CAPTURE_NOT_AUTHORIZED`
- `ECONOMIC_IMPLEMENTATION_NOT_AUTHORIZED`
- `PAPER_CLOSED`
- `SHADOW_CLOSED`
- `LIVE_FORBIDDEN`

## Next boundary

Attempt 2 is consumed and must not be rerun. Repeating the same implementation in the same venue is not admissible.

The next admissible work is planning and implementation review for a materially different evidence route or genuinely different execution venue. Any future network execution requires a new exact-SHA implementation review and a separate one-shot authorization. This closeout itself authorizes no new probe, article expansion, full source-authority capture, economic data access, economic implementation, paper, shadow, private API, or live work.
