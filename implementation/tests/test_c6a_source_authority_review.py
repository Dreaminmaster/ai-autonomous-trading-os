from __future__ import annotations

import inspect

import pytest

import atos.c6a_source_authority_review as review


def _complete_states() -> list[dict]:
    rows: list[dict] = []
    for instrument in review.INSTRUMENTS:
        swap = instrument.endswith("-SWAP")
        rows.append(
            {
                "state_id": f"{instrument}-state",
                "instrument": instrument,
                "authority_mode": "EXACT_EFFECTIVE_STATE",
                "effective_from": review.AUTHORITY_START_TEXT,
                "effective_to": review.AUTHORITY_END_TEXT,
                "open_ended": False,
                "lot_sz": "0.1" if swap else "0.00000001",
                "min_sz": "0.1" if swap else "0.00001",
                "tick_sz": "0.1",
                "ct_val": "0.01" if swap else None,
                "settle_ccy": "USDT" if swap else None,
                "ct_val_ccy": instrument.split("-")[0] if swap else None,
                "contradiction": False,
            }
        )
    return rows


def _transition_proof() -> dict:
    return {
        "instrument": "ETH-USDT-SWAP",
        "window_start": "2024-04-18T06:00:00Z",
        "window_end_exclusive": "2024-04-18T08:00:00Z",
        "old_lot": "1",
        "new_lot": "0.1",
        "old_min": "1",
        "new_min": "0.1",
        "transition_lot": "1",
        "transition_min": "1",
        "boundary_cases": [
            {
                "quantity": "0",
                "admitted_by_intersection": True,
                "valid_old": True,
                "valid_new": True,
            },
            {
                "quantity": "0.1",
                "admitted_by_intersection": False,
                "valid_old": False,
                "valid_new": True,
            },
            {
                "quantity": "1",
                "admitted_by_intersection": True,
                "valid_old": True,
                "valid_new": True,
            },
            {
                "quantity": "2",
                "admitted_by_intersection": True,
                "valid_old": True,
                "valid_new": True,
            },
        ],
    }


def test_independent_module_does_not_import_production_gate() -> None:
    source = inspect.getsource(review)
    assert "import atos.c6a_source_authority" not in source
    assert "from atos.c6a_source_authority" not in source


def test_independent_transition_recomputation_passes_exact_intersection() -> None:
    assert review.recompute_transition(_transition_proof()) == []


def test_independent_transition_recomputation_catches_permissive_union() -> None:
    proof = _transition_proof()
    proof["transition_lot"] = "0.1"
    proof["transition_min"] = "0.1"
    errors = review.recompute_transition(proof)
    assert "transition lot mismatch" in errors
    assert "transition minimum mismatch" in errors


def test_independent_coverage_detects_gap() -> None:
    states = _complete_states()
    states = [row for row in states if row["instrument"] != "BTC-USDT"]
    states.extend(
        [
            {
                **_complete_states()[0],
                "state_id": "btc-a",
                "effective_to": "2024-01-01T00:00:00Z",
            },
            {
                **_complete_states()[0],
                "state_id": "btc-b",
                "effective_from": "2024-01-02T00:00:00Z",
            },
        ]
    )
    _, errors = review.recompute_coverage(states)
    assert any("gap for BTC-USDT" in error for error in errors)


def test_review_payload_refuses_authorization_and_gate_mismatch() -> None:
    payload = {
        "metadata_states": _complete_states(),
        "transition_proofs": [_transition_proof()],
        "failures": ["FAIL_UNCOVERED_INTERVAL"],
        "gate_result": {
            "status": "PASS",
            "result": "PASS",
            "implementation_authorized": True,
            "economic_data_access_authorized": True,
        },
    }
    result = review.review_payload(payload)
    assert result["status"] == "FAIL"
    assert "gate result does not match frozen failure priority" in result["errors"]
    assert "gate result improperly authorizes implementation" in result["errors"]
    assert "gate result improperly authorizes economic access" in result["errors"]
    assert result["implementation_authorized"] is False
    assert result["economic_data_access_authorized"] is False
    assert result["live_state"] == "LIVE_FORBIDDEN"


def test_failure_priority_rejects_unknown_code() -> None:
    with pytest.raises(ValueError, match="unknown failure code"):
        review.choose_primary_failure(["FAIL_NOT_FROZEN"])
