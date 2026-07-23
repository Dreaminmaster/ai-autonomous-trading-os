from __future__ import annotations

import json
from pathlib import Path

import pytest

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_capture import canonical_json_bytes, sha256_bytes
from atos.c6a_source_authority_independent import verify_manifest_complete
from atos.c6a_source_authority_package import CANONICAL_OUTPUTS, package_gate_artifact


def _state(instrument: str) -> dict:
    swap = instrument.endswith("-SWAP")
    base = instrument.split("-")[0]
    required = [
        "inst_type",
        "base_ccy",
        "quote_ccy",
        "lot_sz",
        "min_sz",
        "tick_sz",
        "listing_state",
    ]
    if swap:
        required.extend(["settle_ccy", "ct_val", "ct_val_ccy"])
    return {
        "state_id": f"{instrument}-state",
        "instrument": instrument,
        "authority_mode": "EXACT_EFFECTIVE_STATE",
        "inst_type": "SWAP" if swap else "SPOT",
        "base_ccy": base,
        "quote_ccy": "USDT",
        "settle_ccy": "USDT" if swap else None,
        "ct_val_ccy": base if swap else None,
        "listing_state": "live",
        "effective_from": "2023-06-05T00:00:00Z",
        "effective_to": "2025-12-29T00:00:00Z",
        "open_ended": False,
        "lot_sz": "0.1" if swap else "0.00000001",
        "min_sz": "0.1" if swap else "0.00001",
        "tick_sz": "0.1",
        "ct_val": "0.01" if swap else None,
        "contradiction": False,
        "source_ids": ["source-1"],
        "derivation_rule_id": "TEST_EXACT_EFFECTIVE_STATE_V1",
        "field_source_ids": {field: ["source-1"] for field in required},
        "boundary_source_ids": {
            "effective_from": ["source-1"],
            "effective_to": ["source-1"],
        },
    }


def _coverage(states: list[dict]) -> list[dict]:
    return [
        {
            "instrument": state["instrument"],
            "state_id": state["state_id"],
            "authority_mode": state["authority_mode"],
            "interval_start": "2023-06-05T00:00:00+00:00",
            "interval_end_exclusive": "2025-12-29T00:00:00+00:00",
            "source_coverage_status": "PASS",
            "overlap_count": 0,
            "contradiction_count": 0,
            "uncovered_duration_seconds": 0,
            "required_fields_present": True,
            "modeled_timestamp_outside_authority": False,
        }
        for state in states
    ]


def _query_inventory() -> dict:
    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GATE",
        "design_authority_sha": "26a7604c34c610562643d7a732d35b39df84c94f",
        "authenticated": False,
        "economic_endpoints_forbidden": True,
        "authority_start": "2023-06-05T00:00:00Z",
        "authority_end_exclusive": "2025-12-29T00:00:00Z",
        "instruments": [
            "BTC-USDT",
            "ETH-USDT",
            "BTC-USDT-SWAP",
            "ETH-USDT-SWAP",
        ],
        "requests": [
            {
                "request_id": "catalog-1",
                "request_kind": "announcement_catalog",
                "method": "GET",
                "url": "https://www.okx.com/help/section/announcements/page/1",
                "expected_content_type": "text/html",
            }
        ],
    }


def _catalog(raw_sha256: str) -> dict:
    return {
        "pages": [
            {
                "page_number": 1,
                "declared_terminal_page": 1,
                "is_terminal_page": True,
                "requested_url": "https://www.okx.com/help/section/announcements/page/1",
                "retrieval_timestamp": "2025-12-28T00:00:00Z",
                "status_code": 200,
                "raw_path": "raw/source-1.bin",
                "raw_sha256": raw_sha256,
            }
        ],
        "items": [
            {
                "page_number": 1,
                "canonical_url": "https://www.okx.com/help/example-metadata-notice",
                "title": "Example metadata notice",
            }
        ],
        "terminal_page_proof": {"status": "PASS", "terminal_page": 1},
    }


def _prepare_retained_source(output: Path) -> dict:
    raw = b'{"official":"raw"}\n'
    decoded = b'{"official":"decoded"}\n'
    (output / "raw").mkdir(parents=True)
    (output / "decoded").mkdir(parents=True)
    (output / "raw/source-1.bin").write_bytes(raw)
    (output / "decoded/source-1.json").write_bytes(decoded)
    return {
        "sources": [
            {
                "source_id": "source-1",
                "authority_class": "EXACT_ARCHIVED_OFFICIAL_OKX_RESPONSE",
                "canonical_official_url": "https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT",
                "retrieval_url": "https://web.archive.org/web/20240101000000id_/https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT",
                "raw_path": "raw/source-1.bin",
                "raw_size": len(raw),
                "raw_sha256": sha256_bytes(raw),
                "decoded_path": "decoded/source-1.json",
                "decoded_size": len(decoded),
                "decoded_sha256": sha256_bytes(decoded),
                "parser_version": "c6a-test-source-v1",
                "eligible": True,
                "rejection_reason": None,
            }
        ]
    }


def test_failed_gate_package_retains_source_bytes_and_is_independently_verified(tmp_path: Path) -> None:
    output = tmp_path / "artifact"
    sources = _prepare_retained_source(output)
    states = [
        _state(instrument)
        for instrument in ("BTC-USDT", "ETH-USDT", "BTC-USDT-SWAP", "ETH-USDT-SWAP")
    ]
    query = _query_inventory()
    decision = {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GATE",
        "source_commit_sha": "a" * 40,
        "pr_merge_ref": "refs/pull/61/merge@deadbeef",
        "query_inventory_sha256": sha256_bytes(canonical_json_bytes(query)),
        "status": "FAIL",
        "result": "FAIL_TRANSITION_WINDOW_UNPROVEN",
        "authoritative": False,
        "integrity_state": "PENDING_PACKAGE_AND_INDEPENDENT_REVIEW",
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "unsupported_projection_count": 0,
        "forbidden_access_count": 0,
        "newly_discovered_transition_count": 0,
        "live_state": "LIVE_FORBIDDEN",
    }
    summary = package_gate_artifact(
        output,
        query_inventory=query,
        source_inventory=sources,
        announcement_catalog=_catalog(sources["sources"][0]["raw_sha256"]),
        metadata_states=states,
        transition_proofs=[],
        coverage_matrix=_coverage(states),
        gate_result=decision,
        failures=["FAIL_TRANSITION_WINDOW_UNPROVEN"],
    )
    assert summary["gate_status"] == "FAIL"
    assert summary["gate_result"] == "FAIL_TRANSITION_WINDOW_UNPROVEN"
    assert summary["independent_review_status"] == "PASS"
    assert summary["manifest_status"] == "PASS"
    assert summary["retained_noncanonical_file_count"] == 2
    assert summary["implementation_authorized"] is False
    assert summary["economic_data_access_authorized"] is False
    assert (output / "raw/source-1.bin").is_file()
    assert (output / "decoded/source-1.json").is_file()
    assert set(CANONICAL_OUTPUTS).issubset({path.name for path in output.iterdir()})

    final_decision = json.loads((output / "gate_result.json").read_text())
    independent = json.loads((output / "independent_review.json").read_text())
    assert final_decision["authoritative"] is True
    assert final_decision["independent_review_status"] == "PASS"
    assert final_decision["implementation_authorized"] is False
    assert independent["status"] == "PASS"
    assert independent["gate_status_recomputed"] == "FAIL"
    assert independent["gate_result_recomputed"] == "FAIL_TRANSITION_WINDOW_UNPROVEN"
    manifest = json.loads((output / "manifest.json").read_text())
    manifest_paths = {row["path"] for row in manifest["files"]}
    assert "raw/source-1.bin" in manifest_paths
    assert "decoded/source-1.json" in manifest_paths
    assert "independent_review.json" in manifest_paths
    assert "manifest.json" not in manifest_paths
    assert verify_manifest_complete(output, manifest) == []


def test_package_refuses_existing_canonical_output_but_allows_retained_inputs(tmp_path: Path) -> None:
    output = tmp_path / "artifact"
    output.mkdir()
    (output / "raw.bin").write_bytes(b"retained")
    (output / "gate_result.json").write_text("{}")
    with pytest.raises(SourceAuthorityError, match="will not be overwritten"):
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
