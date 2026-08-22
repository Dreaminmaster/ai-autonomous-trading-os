from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import atos.c11a_historical_evidence as evidence_module
import scripts.c11a_h1_h5_evaluate as evaluate_script
from atos.c7a_historical_capture import CaptureRecord
from atos.c7a_okx_public_data import build_trade_candle_request
from atos.c11a_contract import BTC_BETA_BENCHMARK, CANDIDATE_POOL, capture_plan
from atos.c11a_historical_capture import C11ACapturePackage, select_formation_universe
from atos.c11a_historical_evidence import (
    C11AEvidencePackage,
    C11AHistoricalDataEvidenceError,
    C11AHistoricalEvidenceError,
    verify_capture_package,
    verify_evidence_package,
)
from atos.c11a_historical_run_guard import (
    C11AHistoricalRunGuardError,
    validate_checkout_binding,
    verify_checkout_binding,
)
from scripts.c11a_h1_h5_artifact_manifest import (
    C11AArtifactManifestError,
    seal_authority_artifact,
)

SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[2]


def _binding() -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": "C11A_HISTORICAL_CHECKOUT_BINDING",
        "implementation_sha": SHA,
        "observed_head_sha": SHA,
        "tracked_worktree_clean": True,
    }


def _formation() -> dict[str, tuple[dict[str, str], ...]]:
    return {
        instrument: (
            {
                "timestamp": "2023-07-03T00:00:00Z",
                "open": "1",
                "high": "1",
                "low": "1",
                "close": "1",
                "volume_contract": "1",
                "volume_base": "1",
                "volume_quote": str(index + 1),
                "confirm": "1",
            },
        )
        for index, instrument in enumerate(CANDIDATE_POOL)
    }


def _capture(tmp_path: Path) -> Path:
    root = tmp_path / "capture"
    package = C11ACapturePackage(root)
    package.write_json("checkout_binding.json", _binding())
    request = build_trade_candle_request(
        "BTC-USDT-SWAP",
        after_ms=1_704_067_200_000,
        allowed_instruments=CANDIDATE_POOL,
    )
    raw = b'{"code":"0","data":[]}'
    package.retain_raw(
        raw,
        CaptureRecord(
            request_id=request.request_id,
            source_family=request.source_family,
            requested_url=request.url,
            final_url=request.url,
            collected_at="2026-08-21T00:00:00Z",
            media_type="application/json",
            size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            relative_path="",
        ),
    )
    plan = capture_plan()
    formation = _formation()
    for instrument, rows in formation.items():
        package.retain_c11a_series(
            series_type="formation_trades",
            instrument=instrument,
            start_inclusive=str(plan["formation_trade_start_inclusive"]),
            end_exclusive=str(plan["formation_trade_end_exclusive"]),
            rows=rows,
        )
    selected = package.freeze_universe(select_formation_universe(formation))
    for instrument in selected:
        package.retain_c11a_series(
            series_type="trades",
            instrument=instrument,
            start_inclusive=str(plan["selected_trade_start_inclusive"]),
            end_exclusive=str(plan["selected_trade_end_exclusive"]),
            rows=({"timestamp": plan["selected_trade_start_inclusive"], "open": "1"},),
        )
        package.retain_c11a_series(
            series_type="funding",
            instrument=instrument,
            start_inclusive=str(plan["funding_start_inclusive"]),
            end_exclusive=str(plan["funding_end_exclusive"]),
            rows=(
                {"funding_time": plan["funding_start_inclusive"], "realized_rate": "0"},
            ),
        )
    for instrument in {*selected, BTC_BETA_BENCHMARK}:
        package.retain_c11a_series(
            series_type="marks",
            instrument=instrument,
            start_inclusive=str(plan["mark_start_inclusive"]),
            end_exclusive=str(plan["mark_end_exclusive"]),
            rows=({"timestamp": plan["mark_start_inclusive"], "close": "1"},),
        )
    package.finalize(implementation_sha=SHA, capture_plan_value=plan)
    return root


def test_capture_manifest_is_recursive_bound_and_tamper_evident(tmp_path: Path) -> None:
    root = _capture(tmp_path)
    verified = verify_capture_package(root, implementation_sha=SHA)
    assert verified["capture_file_count"] > 30
    assert len(verified["selected_universe"]) == 8
    target = root / "normalized" / "marks" / "BTC-USDT-SWAP.json"
    target.write_text("[]\n", encoding="utf-8")
    with pytest.raises(C11AHistoricalDataEvidenceError, match="hash mismatch"):
        verify_capture_package(root, implementation_sha=SHA)


def test_capture_record_to_raw_chain_is_independently_recomputed(tmp_path: Path) -> None:
    root = _capture(tmp_path)
    index_path = root / "capture_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["records"][0]["sha256"] = "0" * 64
    index_path.write_text(
        json.dumps(index, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for row in manifest["files"]:
        if row["path"] == "capture_index.json":
            data = index_path.read_bytes()
            row["size"] = len(data)
            row["sha256"] = hashlib.sha256(data).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(C11AHistoricalDataEvidenceError, match="record/raw digest"):
        verify_capture_package(root, implementation_sha=SHA)


def test_evidence_writer_is_atomic_no_overwrite_and_no_escape(tmp_path: Path) -> None:
    package = C11AEvidencePackage(tmp_path / "evidence")
    package.write_json("final.json", {"classification": "ECONOMIC_FAIL"})
    with pytest.raises(C11AHistoricalEvidenceError, match="already exists"):
        package.write_json("final.json", {})
    with pytest.raises(C11AHistoricalEvidenceError, match="escapes"):
        package.write_json("../escape.json", {})
    manifest = package.finalize(implementation_sha=SHA)
    assert manifest["stage"] == "C11A_H1_H5_HISTORICAL_EVIDENCE_PACKAGE"
    assert manifest["live_state"] == "LIVE_FORBIDDEN"
    assert (
        verify_evidence_package(tmp_path / "evidence", implementation_sha=SHA)[
            "verified_file_count"
        ]
        == 1
    )
    (tmp_path / "evidence" / "final.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(C11AHistoricalEvidenceError, match="hash mismatch"):
        verify_evidence_package(tmp_path / "evidence", implementation_sha=SHA)


def test_outer_authority_artifact_seals_logs_environment_and_evidence(
    tmp_path: Path,
) -> None:
    root = tmp_path / "authority"
    (root / "evidence").mkdir(parents=True)
    (root / "capture.log").write_text("capture\n", encoding="utf-8")
    (root / "python_environment.txt").write_text("pytest==8\n", encoding="utf-8")
    (root / "evidence" / "final_classification.json").write_text(
        '{"classification":"ECONOMIC_FAIL"}\n', encoding="utf-8"
    )

    manifest = seal_authority_artifact(
        root,
        implementation_sha=SHA,
        authoritative_run_id="123456",
    )

    assert manifest["file_count"] == 3
    assert {row["path"] for row in manifest["files"]} == {
        "capture.log",
        "evidence/final_classification.json",
        "python_environment.txt",
    }
    assert manifest["live_state"] == "LIVE_FORBIDDEN"
    for row in manifest["files"]:
        data = (root / row["path"]).read_bytes()
        assert row["size"] == len(data)
        assert row["sha256"] == hashlib.sha256(data).hexdigest()
    with pytest.raises(C11AArtifactManifestError, match="already sealed"):
        seal_authority_artifact(
            root,
            implementation_sha=SHA,
            authoritative_run_id="123456",
        )


def test_evidence_builder_preserves_valid_economic_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _capture(tmp_path)
    monkeypatch.setattr(
        evidence_module,
        "review_formation_universe",
        lambda *_args: {"status": "PASS"},
    )
    monkeypatch.setattr(
        evidence_module,
        "evaluate_historical_window_matrix",
        lambda window, **_kwargs: {"window": {"window_id": window.window_id}},
    )
    monkeypatch.setattr(
        evidence_module,
        "review_historical_window",
        lambda *_args, **_kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(
        evidence_module,
        "summarize_h1_h5",
        lambda _windows: {"overall_economic_verdict": "ECONOMIC_FAIL"},
    )
    monkeypatch.setattr(
        evidence_module,
        "review_pooled_summary",
        lambda *_args: {"status": "PASS"},
    )
    final, manifest = evidence_module.build_h1_h5_evidence_package(
        tmp_path / "evidence",
        capture_root=capture,
        repository_root=ROOT,
        implementation_sha=SHA,
        authoritative_run_id="synthetic-wiring-test",
        evaluation_checkout_binding=_binding(),
    )
    assert final["classification"] == "ECONOMIC_FAIL"
    assert final["status"] == "FAIL"
    assert final["independent_recompute_passed"] is True
    assert final["shadow_eligible"] is False
    assert manifest["file_count"] >= 16


def test_checkout_binding_requires_exact_clean_sha(tmp_path: Path) -> None:
    assert validate_checkout_binding(_binding(), implementation_sha=SHA) == _binding()

    class Result:
        def __init__(self, stdout: str):
            self.stdout = stdout

    results = iter((Result(SHA + "\n"), Result("")))
    assert (
        verify_checkout_binding(
            SHA,
            repository_root=tmp_path,
            runner=lambda *_args, **_kwargs: next(results),
        )
        == _binding()
    )
    with pytest.raises(C11AHistoricalRunGuardError):
        validate_checkout_binding(
            {**_binding(), "tracked_worktree_clean": False},
            implementation_sha=SHA,
        )


def test_economic_fail_is_expected_but_program_failure_is_not() -> None:
    assert evaluate_script.classification_exit_code("ECONOMIC_PASS") == 0
    assert evaluate_script.classification_exit_code("ECONOMIC_FAIL") == 1
    with pytest.raises(C11AHistoricalEvidenceError, match="recomputation failed"):
        evaluate_script.classification_exit_code("PROGRAM_FAILURE")


def test_one_shot_authority_workflow_is_explicit_main_only_and_fail_closed() -> None:
    text = (ROOT / ".github" / "workflows" / "freqtrade-validation.yml").read_text(
        encoding="utf-8"
    )
    assert text.count("c11a_h1_h5_authoritative:") == 1
    assert text.count("c11a-h1-h5-authoritative:") == 1
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "cancel-in-progress: false" in text
    assert "if [ \"${status}\" -gt 1 ]; then exit \"${status}\"; fi" in text
    assert "implementation/c11a_authority" in text
