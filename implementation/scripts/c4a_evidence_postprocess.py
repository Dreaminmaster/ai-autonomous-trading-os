#!/usr/bin/env python3
"""Complete C4A evidence views before independent finalization.

The economic engine remains unchanged.  This step converts retained primitive
outputs into the exact universe-row and fully specified rebalance-ledger
artifacts required by the frozen design, then rebuilds the initial manifest.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

try:
    import scripts.c4a_evidence as evidence
except ModuleNotFoundError:  # pragma: no cover
    import c4a_evidence as evidence  # type: ignore

RESULTS = evidence.RESULTS


class C4AEvidencePostprocessError(RuntimeError):
    pass


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise C4AEvidencePostprocessError(f"unable to read JSONL {path}: {exc}") from exc
    rows = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise C4AEvidencePostprocessError(
                f"invalid JSONL {path}:{line_number}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise C4AEvidencePostprocessError(f"JSONL row is not an object: {path}:{line_number}")
        rows.append(payload)
    return rows


def _market_prices() -> dict[str, dict[str, dict[str, float]]]:
    output: dict[str, dict[str, dict[str, float]]] = {}
    config = evidence.read_json(evidence.CONFIG_PATH)
    pairs = config.get("candidate_pairs") if isinstance(config, Mapping) else None
    if not isinstance(pairs, list) or len(pairs) != 12:
        raise C4AEvidencePostprocessError("invalid candidate-pair configuration")
    for pair in pairs:
        rows = evidence.read_json(
            RESULTS / "input_candles" / f"{str(pair).replace('/', '_')}_4h.json"
        )
        if not isinstance(rows, list) or len(rows) != 2376:
            raise C4AEvidencePostprocessError(f"invalid retained market for {pair}")
        indexed: dict[str, dict[str, float]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise C4AEvidencePostprocessError(f"non-object candle for {pair}")
            stamp = str(row.get("date"))
            indexed[stamp] = {
                "open": float(row["open"]),
                "close": float(row["close"]),
            }
        if len(indexed) != 2376:
            raise C4AEvidencePostprocessError(f"duplicate retained timestamps for {pair}")
        output[str(pair)] = indexed
    return output


def _lookup_price(
    market: Mapping[str, Mapping[str, Mapping[str, float]]],
    pair: str,
    timestamp: str,
    field: str,
) -> float:
    variants = (timestamp, timestamp.replace("+00:00", "Z"), timestamp.replace("Z", "+00:00"))
    for variant in variants:
        row = market[pair].get(variant)
        if row is not None:
            value = float(row[field])
            if value <= 0:
                raise C4AEvidencePostprocessError(f"non-positive {field} price for {pair}")
            return value
    raise C4AEvidencePostprocessError(f"missing {field} price for {pair} at {timestamp}")


def build_rebalance_ledger(
    policy_rows: list[Mapping[str, Any]],
    market: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> list[dict[str, Any]]:
    ledger: list[dict[str, Any]] = []
    for cell in policy_rows:
        policy = str(cell["policy_id"])
        window = str(cell["window_id"])
        cost = str(cell["cost_label"])
        fee_rate = float(cell["fee_rate"])
        selected_pairs = [str(pair) for pair in cell["selected_pairs"]]
        quantities = {pair: 0.0 for pair in selected_pairs}
        cell_rows = 0
        for sequence, event in enumerate(cell["events"]):
            kind = str(event.get("kind"))
            if kind not in {"SCHEDULED_REBALANCE", "FORCED_CASH", "TERMINAL_LIQUIDATION"}:
                continue
            timestamp = str(event["time"])
            price_field = "close" if kind == "TERMINAL_LIQUIDATION" else "open"
            prices = {
                pair: _lookup_price(market, pair, timestamp, price_field)
                for pair in selected_pairs
            }
            quantities_before = dict(quantities)
            current_values = {
                pair: quantities_before[pair] * prices[pair]
                for pair in selected_pairs
            }
            equity_before = float(event["equity_before"])
            target_weights = (
                {}
                if kind == "TERMINAL_LIQUIDATION"
                else {str(pair): float(weight) for pair, weight in event["target_weights"].items()}
            )
            if kind == "TERMINAL_LIQUIDATION":
                target_values = {pair: 0.0 for pair in selected_pairs}
                trade_deltas = {pair: -current_values[pair] for pair in selected_pairs}
                fees = {pair: fee_rate * abs(trade_deltas[pair]) for pair in selected_pairs}
                total_fee = sum(fees.values())
                equity_after = equity_before - total_fee
                cash = equity_after
                iterations = None
                residual = 0.0
            else:
                target_values = {
                    pair: current_values[pair] + float(event["trade_deltas"][pair])
                    for pair in selected_pairs
                }
                trade_deltas = {
                    pair: target_values[pair] - current_values[pair]
                    for pair in selected_pairs
                }
                fees = {pair: float(event["fees"][pair]) for pair in selected_pairs}
                total_fee = float(event["total_fee"])
                equity_after = float(event["equity_after"])
                cash = float(event["cash"])
                iterations = int(event["iterations"])
                residual = equity_before - total_fee - equity_after
            quantities_after = {
                pair: target_values[pair] / prices[pair] if target_values[pair] > 0 else 0.0
                for pair in selected_pairs
            }
            if abs(sum(fees.values()) - total_fee) > 1e-9:
                raise C4AEvidencePostprocessError("rebalance fee reconciliation failure")
            if abs(equity_before - total_fee - equity_after) > 1e-9:
                raise C4AEvidencePostprocessError("rebalance equity reconciliation failure")
            if abs(equity_after - sum(target_values.values()) - cash) > 1e-9:
                raise C4AEvidencePostprocessError("rebalance cash reconciliation failure")
            quantities = quantities_after
            ledger.append(
                {
                    "schema_version": 1,
                    "stage": "C4A",
                    "policy_id": policy,
                    "window_id": window,
                    "cost_label": cost,
                    "cell_sequence": cell_rows,
                    "source_event_sequence": sequence,
                    "kind": kind,
                    "time": timestamp,
                    "price_field": price_field,
                    "fee_rate": fee_rate,
                    "prices": prices,
                    "quantities_before": quantities_before,
                    "current_values": current_values,
                    "target_weights": target_weights,
                    "target_values": target_values,
                    "trade_deltas": trade_deltas,
                    "fees": fees,
                    "total_fee": total_fee,
                    "equity_before": equity_before,
                    "equity_after": equity_after,
                    "cash_after": cash,
                    "quantities_after": quantities_after,
                    "solver_iterations": iterations,
                    "solver_residual": residual,
                    "boundary_gap_pnl": float(event.get("boundary_gap_pnl", 0.0)),
                    "confirmation_opened": False,
                    "holdout_state": "HOLDOUT_CLOSED",
                    "live": "FORBIDDEN",
                }
            )
            cell_rows += 1
        if any(value != 0.0 for value in quantities.values()):
            raise C4AEvidencePostprocessError(
                f"rebalance ledger does not end in cash: {policy}/{window}/{cost}"
            )
    return ledger


def main() -> int:
    source_sha = evidence.exact_sha("C4A_SOURCE_SHA")
    merge_ref_sha = evidence.exact_sha("C4A_MERGE_REF_SHA")
    candidates = evidence.read_json(RESULTS / "candidate_universe.json")
    selected_pairs = evidence.read_json(RESULTS / "selected_universe.json")
    if not isinstance(candidates, list) or len(candidates) != 12:
        raise C4AEvidencePostprocessError("candidate universe must contain twelve rows")
    if not isinstance(selected_pairs, list) or len(selected_pairs) != 8:
        raise C4AEvidencePostprocessError("selected universe must initially contain eight pair ids")
    enriched_candidates = []
    for item in candidates:
        if not isinstance(item, Mapping):
            raise C4AEvidencePostprocessError("candidate universe row must be an object")
        row = dict(item)
        row["formation_row_count"] = 732
        enriched_candidates.append(row)
    selected_set = {str(pair) for pair in selected_pairs}
    selected_rows = [row for row in enriched_candidates if row.get("selected") is True]
    if len(selected_rows) != 8 or {str(row["pair"]) for row in selected_rows} != selected_set:
        raise C4AEvidencePostprocessError("selected universe rows do not match selected pair ids")
    if [int(row["rank"]) for row in selected_rows] != list(range(1, 9)):
        raise C4AEvidencePostprocessError("selected universe rank sequence mismatch")
    evidence.write_json(RESULTS / "candidate_universe.json", enriched_candidates)
    evidence.write_json(RESULTS / "selected_universe.json", selected_rows)
    evidence.write_json(
        RESULTS / "universe_hashes.json",
        {
            "schema_version": 1,
            "stage": "C4A",
            "candidate_count": 12,
            "selected_count": 8,
            "candidate_universe_canonical_sha256": canonical_sha256(enriched_candidates),
            "selected_universe_canonical_sha256": canonical_sha256(selected_rows),
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        },
    )

    policy_rows = evidence.read_json(RESULTS / "policy_rows.json")
    if not isinstance(policy_rows, list) or len(policy_rows) != 27:
        raise C4AEvidencePostprocessError("policy-row count mismatch")
    ledger = build_rebalance_ledger(policy_rows, _market_prices())
    evidence.write_jsonl(RESULTS / "rebalance_ledger.jsonl", ledger)

    summary = evidence.read_json(RESULTS / "run_summary.json")
    if not isinstance(summary, dict):
        raise C4AEvidencePostprocessError("run summary must be an object")
    summary["rebalance_ledger_entry_count"] = len(ledger)
    summary["universe_hashes_present"] = True
    summary["evidence_postprocess_status"] = "PASS"
    evidence.write_json(RESULTS / "run_summary.json", summary)

    evidence.write_json(
        RESULTS / "manifest.json",
        evidence.build_manifest(source_sha, merge_ref_sha),
    )
    print(
        f"C4A evidence postprocess PASS: 12 candidate rows / 8 selected rows / "
        f"{len(ledger)} complete rebalance-ledger entries"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
