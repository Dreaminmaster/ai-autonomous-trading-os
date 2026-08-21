from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import atos.c9a_historical_evidence as evidence_module
import pytest
import scripts.c9a_w1_w5_evaluate as evaluate_script
import yaml
from atos.c7a_historical_capture import CaptureRecord, fetch_raw_strict
from atos.c9a_contract import ALL_TRADE_INSTRUMENTS, SWAP_INSTRUMENTS
from atos.c9a_historical_capture import (
    C9ACapturePackage,
    build_trade_candle_request,
)
from atos.c9a_historical_evidence import (
    C9AEvidencePackage,
    C9AHistoricalDataEvidenceError,
    C9AHistoricalEvidenceError,
    verify_capture_package,
)
from atos.c9a_historical_run_guard import (
    C9AHistoricalRunGuardError,
    validate_checkout_binding,
    verify_checkout_binding,
)
from atos.c9a_historical_schedule import w1_w5_capture_plan

SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[2]


def _record(raw: bytes) -> CaptureRecord:
    request = build_trade_candle_request("BTC-USDT", after_ms=1_704_067_200_000)
    return CaptureRecord(
        request_id=request.request_id,
        source_family=request.source_family,
        requested_url=request.url,
        final_url=request.url,
        collected_at="2026-08-21T00:00:00Z",
        media_type="application/json",
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        relative_path="",
    )


def _binding() -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": "C9A_HISTORICAL_CHECKOUT_BINDING",
        "implementation_sha": SHA,
        "observed_head_sha": SHA,
        "tracked_worktree_clean": True,
    }


def _capture(tmp_path: Path) -> Path:
    root = tmp_path / "capture"
    package = C9ACapturePackage(root)
    package.write_json("checkout_binding.json", _binding())
    raw = b'{"code":"0","data":[]}'
    package.retain_raw(raw, _record(raw))
    plan = w1_w5_capture_plan()
    for instrument in ALL_TRADE_INSTRUMENTS:
        package.retain_normalized_series(
            series_type="trades",
            instrument=instrument,
            start_inclusive=str(plan["trade_start_inclusive"]),
            end_exclusive=str(plan["trade_end_exclusive"]),
            rows=(
                {"timestamp": plan["trade_start_inclusive"], "open": "1", "close": "1"},
            ),
        )
    for instrument in SWAP_INSTRUMENTS:
        package.retain_normalized_series(
            series_type="marks",
            instrument=instrument,
            start_inclusive=str(plan["mark_start_inclusive"]),
            end_exclusive=str(plan["mark_end_exclusive"]),
            rows=({"timestamp": plan["mark_start_inclusive"], "close": "1"},),
        )
        package.retain_normalized_series(
            series_type="funding",
            instrument=instrument,
            start_inclusive=str(plan["funding_start_inclusive"]),
            end_exclusive=str(plan["funding_end_exclusive"]),
            rows=(
                {"funding_time": plan["funding_start_inclusive"], "realized_rate": "0"},
            ),
        )
    package.finalize(implementation_sha=SHA, capture_plan=plan)
    return root


def test_capture_manifest_is_recursive_bound_and_tamper_evident(tmp_path: Path) -> None:
    root = _capture(tmp_path)
    verified = verify_capture_package(root, implementation_sha=SHA)
    assert verified["capture_file_count"] > 10
    assert verified["implementation_sha"] == SHA
    target = root / "normalized" / "trades" / "BTC-USDT.json"
    target.write_text("[]\n", encoding="utf-8")
    with pytest.raises(C9AHistoricalDataEvidenceError, match="hash mismatch"):
        verify_capture_package(root, implementation_sha=SHA)


def test_evidence_writer_is_atomic_no_overwrite_and_no_escape(tmp_path: Path) -> None:
    package = C9AEvidencePackage(tmp_path / "evidence")
    package.write_json("final.json", {"classification": "ECONOMIC_FAIL"})
    with pytest.raises(C9AHistoricalEvidenceError, match="already exists"):
        package.write_json("final.json", {})
    with pytest.raises(C9AHistoricalEvidenceError, match="escapes"):
        package.write_json("../escape.json", {})
    manifest = package.finalize(implementation_sha=SHA)
    assert manifest["stage"] == "C9A_W1_W5_HISTORICAL_EVIDENCE_PACKAGE"
    assert manifest["live_state"] == "LIVE_FORBIDDEN"


def test_evidence_builder_preserves_valid_economic_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _capture(tmp_path)
    monkeypatch.setattr(
        evidence_module,
        "evaluate_historical_window",
        lambda **kwargs: {"window_id": kwargs["window_id"]},
    )
    monkeypatch.setattr(
        evidence_module,
        "review_historical_window",
        lambda *_args, **_kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(
        evidence_module,
        "summarize_w1_w5",
        lambda _windows: {"overall_economic_verdict": "ECONOMIC_FAIL"},
    )
    monkeypatch.setattr(
        evidence_module,
        "review_pooled_summary",
        lambda *_args: {"status": "PASS"},
    )
    final, manifest = evidence_module.build_w1_w5_evidence_package(
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
    assert manifest["file_count"] >= 15
    authority = json.loads(
        (tmp_path / "evidence" / "authority_hashes.json").read_text(encoding="utf-8")
    )
    paths = {row["path"] for row in authority["source_inventory"]}
    assert {
        "implementation/src/atos/c7a_okx_public_data.py",
        "implementation/src/atos/c7a_historical_capture.py",
        "implementation/src/atos/c8a_historical_capture.py",
    } <= paths


def test_only_economic_classifications_receive_accepted_exit_codes() -> None:
    assert evaluate_script.classification_exit_code("ECONOMIC_PASS") == 0
    assert evaluate_script.classification_exit_code("ECONOMIC_FAIL") == 1
    with pytest.raises(C9AHistoricalEvidenceError, match="recomputation failed"):
        evaluate_script.classification_exit_code("PROGRAM_FAILURE")


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
    with pytest.raises(C9AHistoricalRunGuardError):
        validate_checkout_binding(
            {**_binding(), "tracked_worktree_clean": False},
            implementation_sha=SHA,
        )


def test_shared_transport_extension_is_explicit_and_default_safe() -> None:
    parameter = inspect.signature(fetch_raw_strict).parameters["trade_instruments"]
    assert tuple(parameter.default) == ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
    assert "request_validator" not in inspect.signature(fetch_raw_strict).parameters


def test_one_shot_workflow_is_manual_main_only_and_public_read_only() -> None:
    path = ROOT / ".github" / "workflows" / "freqtrade-validation.yml"
    text = path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    dispatch = parsed[True]["workflow_dispatch"]
    assert dispatch["inputs"]["c9a_w1_w5_authoritative"]["type"] == "boolean"
    job = parsed["jobs"]["c9a-w1-w5-authoritative"]
    assert "github.ref == 'refs/heads/main'" in job["if"]
    assert job["permissions"] == {"contents": "read"}
    assert "persist-credentials: false" in text
    assert "scripts/c9a_w1_w5_capture.py" in text
    assert "scripts/c9a_w1_w5_evaluate.py" in text
    assert "api/v5/trade/order" not in text
    assert "${{ secrets." not in text


def test_independent_module_does_not_import_production_engine() -> None:
    source = (
        ROOT / "implementation" / "src" / "atos" / "c9a_historical_independent.py"
    ).read_text(encoding="utf-8")
    assert "from atos.c9a_historical_replay" not in source
    assert "from atos.c9a_historical_ledger" not in source
    assert "from atos.c9a_policy" not in source
