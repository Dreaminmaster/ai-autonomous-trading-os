from __future__ import annotations

import json
from pathlib import Path

import atos.c6a_source_authority_attempt_review as attempt_review


def _write_attempt_log(root: Path, events: list[dict]) -> None:
    path = root / "diagnostics" / "attempt_log.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"events": events}), encoding="utf-8")


def _archive_event() -> dict:
    return {
        "timestamp": "2026-07-23T09:31:39+00:00",
        "stage": "archive_index",
        "request_id": "archive-btc-usdt-spot-instruments",
        "request_kind": "archive_lookup",
        "url": "https://web.archive.org/cdx/search/cdx?url=official",
        "failure_code": "FAIL_ARCHIVE_DECODING_OR_PROVENANCE",
        "error_type": "SourceAuthorityError",
        "error": "Wayback CDX response is empty",
    }


def test_attempt_diagnostics_recomputes_archive_failure_without_trusting_code(
    tmp_path: Path,
) -> None:
    _write_attempt_log(tmp_path, [_archive_event()])
    review = attempt_review.review_attempt_diagnostics(tmp_path)
    assert review["status"] == "PASS"
    assert review["event_count"] == 1
    assert review["recomputed_failures"] == ["FAIL_ARCHIVE_DECODING_OR_PROVENANCE"]
    assert review["errors"] == []


def test_attempt_diagnostics_recomputes_structured_catalog_deduplication(
    tmp_path: Path,
) -> None:
    _write_attempt_log(
        tmp_path,
        [
            {
                "stage": "announcement_catalog_deduplication",
                "failure_code": "FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE",
                "duplicate_urls": ["https://www.okx.com/en-us/help/example"],
            }
        ],
    )
    review = attempt_review.review_attempt_diagnostics(tmp_path)
    assert review["status"] == "PASS"
    assert review["recomputed_failures"] == ["FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE"]
    assert review["errors"] == []


def test_attempt_diagnostics_rejects_producer_failure_code_drift(tmp_path: Path) -> None:
    event = _archive_event()
    event["failure_code"] = "FAIL_REQUIRED_FIELD_MISSING"
    _write_attempt_log(tmp_path, [event])
    review = attempt_review.review_attempt_diagnostics(tmp_path)
    assert review["status"] == "FAIL"
    assert review["recomputed_failures"] == ["FAIL_ARCHIVE_DECODING_OR_PROVENANCE"]
    assert any("failure mismatch" in error for error in review["errors"])


def test_package_review_reconciles_retained_archive_failure(monkeypatch, tmp_path: Path) -> None:
    _write_attempt_log(tmp_path, [_archive_event()])
    recorded = {
        "FAIL_ARCHIVE_DECODING_OR_PROVENANCE",
        "FAIL_REQUIRED_FIELD_MISSING",
        "FAIL_UNCOVERED_INTERVAL",
        "FAIL_TRANSITION_WINDOW_UNPROVEN",
    }

    def base_review(*args, **kwargs):
        return {
            "schema_version": 1,
            "stage": "C6A_SOURCE_AUTHORITY_GATE_INDEPENDENT_PACKAGE_REVIEW",
            "status": "FAIL",
            "gate_status_recomputed": "FAIL",
            "gate_result_recomputed": "FAIL_REQUIRED_FIELD_MISSING",
            "recorded_failures": sorted(recorded),
            "recomputed_failures": sorted(recorded - {"FAIL_ARCHIVE_DECODING_OR_PROVENANCE"}),
            "errors": [
                "recorded failure set mismatch: recorded=['x'] recomputed=['y']",
                "recomputed primary failure does not match recorded primary failure",
            ],
            "implementation_authorized": False,
            "economic_data_access_authorized": False,
            "live_state": "LIVE_FORBIDDEN",
        }

    monkeypatch.setattr(attempt_review.independent, "review_package", base_review)
    result = attempt_review.review_package_with_attempt_diagnostics(
        tmp_path,
        query_inventory={},
        source_inventory={},
        announcement_catalog={},
        metadata_states=[],
        transition_proofs=[],
        coverage_matrix=[],
        failures=sorted(recorded),
        gate_result={},
        preliminary_manifest={},
    )
    assert result["status"] == "PASS"
    assert result["gate_status_recomputed"] == "FAIL"
    assert result["gate_result_recomputed"] == "FAIL_ARCHIVE_DECODING_OR_PROVENANCE"
    assert result["recorded_failures"] == result["recomputed_failures"]
    assert result["errors"] == []
    assert result["attempt_diagnostics_review"]["status"] == "PASS"
