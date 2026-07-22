from __future__ import annotations

from atos.c6a_source_authority import (
    AUTHORITY_END_TEXT,
    AUTHORITY_START_TEXT,
    MetadataState,
    SourceObject,
)
from atos.c6a_source_authority_gate import GateSnapshot, evaluate_gate_snapshot


def _source() -> SourceObject:
    return SourceObject.from_mapping(
        {
            "source_id": "official-1",
            "authority_class": "DIRECT_OFFICIAL_OKX_RESPONSE",
            "canonical_official_url": "https://www.okx.com/api/v5/public/instruments?instType=SWAP",
            "retrieval_url": "https://www.okx.com/api/v5/public/instruments?instType=SWAP",
            "raw_sha256": "1" * 64,
            "decoded_sha256": "1" * 64,
            "raw_size": 100,
            "decoded_size": 100,
            "parser_version": "c6a-source-authority-v1",
            "eligible": True,
            "rejection_reason": None,
        }
    )


def _state(
    *,
    state_id: str,
    instrument: str,
    start: str,
    end: str,
    lot: str,
    minimum: str,
    mode: str = "EXACT_EFFECTIVE_STATE",
    base_ccy: str | None = None,
) -> MetadataState:
    swap = instrument.endswith("-SWAP")
    expected_base = instrument.split("-")[0]
    return MetadataState.from_mapping(
        {
            "state_id": state_id,
            "instrument": instrument,
            "authority_mode": mode,
            "inst_type": "SWAP" if swap else "SPOT",
            "base_ccy": base_ccy or expected_base,
            "quote_ccy": "USDT",
            "settle_ccy": "USDT" if swap else None,
            "ct_val": "0.01" if swap else None,
            "ct_val_ccy": expected_base if swap else None,
            "lot_sz": lot,
            "min_sz": minimum,
            "tick_sz": "0.1",
            "listing_state": "live",
            "effective_from": start,
            "effective_to": end,
            "open_ended": False,
            "source_ids": [f"source-{state_id}"],
            "contradiction": False,
        }
    )


def _full_states() -> tuple[MetadataState, ...]:
    states = [
        _state(
            state_id="btc-spot",
            instrument="BTC-USDT",
            start=AUTHORITY_START_TEXT,
            end=AUTHORITY_END_TEXT,
            lot="0.00000001",
            minimum="0.00001",
        ),
        _state(
            state_id="eth-spot",
            instrument="ETH-USDT",
            start=AUTHORITY_START_TEXT,
            end=AUTHORITY_END_TEXT,
            lot="0.00000001",
            minimum="0.0001",
        ),
        _state(
            state_id="eth-old-1",
            instrument="ETH-USDT-SWAP",
            start=AUTHORITY_START_TEXT,
            end="2024-04-18T06:00:00Z",
            lot="1",
            minimum="1",
        ),
        _state(
            state_id="eth-transition-1",
            instrument="ETH-USDT-SWAP",
            start="2024-04-18T06:00:00Z",
            end="2024-04-18T08:00:00Z",
            lot="1",
            minimum="1",
            mode="TRANSITION_SAFE_INTERSECTION",
        ),
        _state(
            state_id="eth-old-2",
            instrument="ETH-USDT-SWAP",
            start="2024-04-18T08:00:00Z",
            end="2025-01-09T06:00:00Z",
            lot="0.1",
            minimum="0.1",
        ),
        _state(
            state_id="eth-transition-2",
            instrument="ETH-USDT-SWAP",
            start="2025-01-09T06:00:00Z",
            end="2025-01-09T10:00:00Z",
            lot="0.1",
            minimum="0.1",
            mode="TRANSITION_SAFE_INTERSECTION",
        ),
        _state(
            state_id="eth-new",
            instrument="ETH-USDT-SWAP",
            start="2025-01-09T10:00:00Z",
            end=AUTHORITY_END_TEXT,
            lot="0.01",
            minimum="0.01",
        ),
        _state(
            state_id="btc-old-1",
            instrument="BTC-USDT-SWAP",
            start=AUTHORITY_START_TEXT,
            end="2024-04-25T06:00:00Z",
            lot="1",
            minimum="1",
        ),
        _state(
            state_id="btc-transition-1",
            instrument="BTC-USDT-SWAP",
            start="2024-04-25T06:00:00Z",
            end="2024-04-25T08:00:00Z",
            lot="1",
            minimum="1",
            mode="TRANSITION_SAFE_INTERSECTION",
        ),
        _state(
            state_id="btc-old-2",
            instrument="BTC-USDT-SWAP",
            start="2024-04-25T08:00:00Z",
            end="2025-01-22T06:00:00Z",
            lot="0.1",
            minimum="0.1",
        ),
        _state(
            state_id="btc-transition-2",
            instrument="BTC-USDT-SWAP",
            start="2025-01-22T06:00:00Z",
            end="2025-01-22T08:00:00Z",
            lot="0.1",
            minimum="0.1",
            mode="TRANSITION_SAFE_INTERSECTION",
        ),
        _state(
            state_id="btc-new",
            instrument="BTC-USDT-SWAP",
            start="2025-01-22T08:00:00Z",
            end=AUTHORITY_END_TEXT,
            lot="0.01",
            minimum="0.01",
        ),
    ]
    return tuple(states)


def _proof(instrument: str, start: str, end: str, old_step: str, new_step: str) -> dict:
    transition_lot = old_step
    transition_min = old_step
    return {
        "instrument": instrument,
        "window_start": start,
        "window_end_exclusive": end,
        "old_state_id": f"{instrument}-{start}-old",
        "new_state_id": f"{instrument}-{end}-new",
        "old_lot": old_step,
        "new_lot": new_step,
        "old_min": old_step,
        "new_min": new_step,
        "transition_lot": transition_lot,
        "transition_min": transition_min,
        "boundary_cases": [
            {
                "quantity": "0",
                "admitted_by_intersection": True,
                "valid_old": True,
                "valid_new": True,
            },
            {
                "quantity": transition_min,
                "admitted_by_intersection": True,
                "valid_old": True,
                "valid_new": True,
            },
        ],
        "status": "PASS",
    }


def _proofs() -> tuple[dict, ...]:
    return (
        _proof(
            "ETH-USDT-SWAP",
            "2024-04-18T06:00:00Z",
            "2024-04-18T08:00:00Z",
            "1",
            "0.1",
        ),
        _proof(
            "BTC-USDT-SWAP",
            "2024-04-25T06:00:00Z",
            "2024-04-25T08:00:00Z",
            "1",
            "0.1",
        ),
        _proof(
            "ETH-USDT-SWAP",
            "2025-01-09T06:00:00Z",
            "2025-01-09T10:00:00Z",
            "0.1",
            "0.01",
        ),
        _proof(
            "BTC-USDT-SWAP",
            "2025-01-22T06:00:00Z",
            "2025-01-22T08:00:00Z",
            "0.1",
            "0.01",
        ),
    )


def _snapshot(**overrides) -> GateSnapshot:
    values = {
        "query_inventory_valid": True,
        "catalog_complete": True,
        "metadata_states": _full_states(),
        "transition_proofs": _proofs(),
        "source_objects": (_source(),),
        "source_failures": (),
        "forbidden_access_count": 0,
        "unsupported_projection_count": 0,
        "newly_discovered_transition_count": 0,
    }
    values.update(overrides)
    return GateSnapshot(**values)


def test_complete_snapshot_is_preliminary_and_non_authorizing() -> None:
    decision, coverage, failures = evaluate_gate_snapshot(
        _snapshot(),
        source_commit_sha="a" * 40,
        query_inventory_sha256="b" * 64,
    )
    assert failures == ()
    assert decision["status"] == "PASS"
    assert decision["result"] == "PASS"
    assert decision["authoritative"] is False
    assert decision["integrity_state"] == "PENDING_PACKAGE_AND_INDEPENDENT_REVIEW"
    assert decision["required_transition_count"] == 4
    assert decision["observed_transition_state_count"] == 4
    assert decision["observed_transition_proof_count"] == 4
    assert decision["implementation_authorized"] is False
    assert decision["economic_data_access_authorized"] is False
    assert len(coverage) == 12


def test_missing_frozen_transition_fails_before_economics() -> None:
    states = tuple(
        state for state in _full_states() if state.state_id != "eth-transition-1"
    )
    proofs = _proofs()[1:]
    decision, _, failures = evaluate_gate_snapshot(
        _snapshot(metadata_states=states, transition_proofs=proofs),
        source_commit_sha="a" * 40,
        query_inventory_sha256="b" * 64,
    )
    assert "FAIL_TRANSITION_WINDOW_UNPROVEN" in failures
    assert decision["status"] == "FAIL"
    assert decision["authoritative"] is False
    assert decision["implementation_authorized"] is False


def test_instrument_identity_drift_fails_closed() -> None:
    states = list(_full_states())
    states[0] = _state(
        state_id="btc-spot-wrong-base",
        instrument="BTC-USDT",
        start=AUTHORITY_START_TEXT,
        end=AUTHORITY_END_TEXT,
        lot="0.00000001",
        minimum="0.00001",
        base_ccy="ETH",
    )
    decision, coverage, failures = evaluate_gate_snapshot(
        _snapshot(metadata_states=tuple(states)),
        source_commit_sha="a" * 40,
        query_inventory_sha256="b" * 64,
    )
    assert "FAIL_REQUIRED_FIELD_MISSING" in failures
    assert coverage == ()
    assert decision["status"] == "FAIL"
    assert decision["authoritative"] is False
