from __future__ import annotations

import json
from pathlib import Path

import pytest

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_package import CANONICAL_OUTPUTS, package_gate_artifact
from atos.c6a_source_authority_review import verify_manifest


def _state(instrument: str) -> dict:
    swap = instrument.endswith("-SWAP")
    return {
        "state_id": f"{instrument}-state",
        "instrument": instrument,
        "authority_mode": "EXACT_EFFECTIVE_STATE",
        "effective_from": "2023-06-05T00:00:00Z",
        "effective_to": "2025-12-29T00:00:00Z",
        "open_ended": False,
        "lot_sz": "0.1" if swap else "0.00000001",
        "min_sz": "0.1" if swap else "0.00001",
        "tick_sz": "0.1",
        "ct_val": "0.01" if swap else None,
        "settle_ccy": "USDT" if swap else None,
        "ct_val_ccy": instrument.split("-")[0] if swap else None,
        "contradiction": False,
    }


def test_failed_gate_package_is_complete_deterministic_and_non_authorizing(tmp_path: Path) -> None:
    output = tmp_path / "artifact"
    states = [_state(instrument) for instrument in ("BTC-USDT", "ETH-USDT", "BTC-USDT-SWAP", "ETH-USDT-SWAP")]
    decision = {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GATE",
        "status": "FAIL",
        "result": "FAIL_TRANSITION_WINDOW_UNPROVEN",
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }
    summary = package_gate_artifact(
        output,
        query_inventory={"schema_version": 1, "stage": "C6A_SOURCE_AUTHORITY_GATE"},
        source_inventory={"sources": []},
        announcement_catalog={"pages": [], "items": []},
        metadata_states=states,
        transition_proofs=[],
        coverage_matrix=[],
        gate_result=decision,
        failures=["FAIL_TRANSITION_WINDOW_UNPROVEN"],
    )
    assert summary["gate_status"] == "FAIL"
    assert summary["manifest_status"] == "PASS"
    assert summary["implementation_authorized"] is False
    assert summary["economic_data_access_authorized"] is False
    assert {path.name for path in output.iterdir()} == set(CANONICAL_OUTPUTS)

    manifest = json.loads((output / "manifest.json").read_text())
    assert "independent_review.json" in {row["path"] for row in manifest["files"]}
    assert "manifest.json" not in {row["path"] for row in manifest["files"]}
    assert verify_manifest(output, manifest) == []


def test_package_refuses_nonempty_directory(tmp_path: Path) -> None:
    output = tmp_path / "artifact"
    output.mkdir()
    (output / "unexpected.txt").write_text("unexpected")
    with pytest.raises(SourceAuthorityError, match="must be empty"):
        package_gate_artifact(
            output,
            query_inventory={},
            source_inventory={},
            announcement_catalog={},
            metadata_states=[],
            transition_proofs=[],
            coverage_matrix=[],
            gate_result={},
            failures=[],
        )
