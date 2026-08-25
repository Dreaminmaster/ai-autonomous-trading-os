from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from atos.c7a_historical_capture import CaptureRecord
from atos.c12a_contract import WINDOWS, contract_decisions, iso_z
from atos.c12a_historical_capture import (
    C12ACapturePackage,
    build_futures_manifest_request,
    capture_plan,
)
from atos.c12a_historical_evidence import (
    C12AEvidencePackage,
    C12AHistoricalEvidenceError,
    build_h1_h5_evidence_package,
    verify_evidence_package,
)
from atos.c12a_historical_run_guard import (
    C12AHistoricalRunGuardError,
    validate_checkout_binding,
    verify_checkout_binding,
)
from scripts.c12a_h1_h5_artifact_manifest import (
    C12AArtifactManifestError,
    seal_authority_artifact,
)
from scripts.c12a_h1_h5_evaluate import classification_exit_code

SHA = "a" * 40


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def test_checkout_binding_requires_exact_clean_sha(tmp_path: Path) -> None:
    responses = iter((_completed(f"{SHA}\n"), _completed("")))

    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return next(responses)

    binding = verify_checkout_binding(SHA, repository_root=tmp_path, runner=runner)
    assert validate_checkout_binding(binding, implementation_sha=SHA) == binding
    dirty = iter((_completed(f"{SHA}\n"), _completed(" M tracked.py\n")))
    with pytest.raises(C12AHistoricalRunGuardError, match="exact clean"):
        verify_checkout_binding(
            SHA,
            repository_root=tmp_path,
            runner=lambda *_args, **_kwargs: next(dirty),
        )


def test_evidence_manifest_recomputes_every_digest_and_rejects_tamper(
    tmp_path: Path,
) -> None:
    root = tmp_path / "evidence"
    package = C12AEvidencePackage(root)
    package.write_json("nested/result.json", {"classification": "ECONOMIC_FAIL"})
    manifest = package.finalize(implementation_sha=SHA)
    review = verify_evidence_package(root, implementation_sha=SHA)
    assert review["verified_file_count"] == manifest["file_count"] == 1
    assert review["live_state"] == "LIVE_FORBIDDEN"
    (root / "nested" / "result.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(C12AHistoricalEvidenceError, match="hash mismatch"):
        verify_evidence_package(root, implementation_sha=SHA)


def test_outer_artifact_seals_complete_inventory_exactly_once(tmp_path: Path) -> None:
    root = tmp_path / "authority"
    root.mkdir()
    (root / "capture.log").write_text("public-only\n", encoding="utf-8")
    manifest = seal_authority_artifact(
        root, implementation_sha=SHA, authoritative_run_id="12345"
    )
    assert manifest["stage"] == "C12A_H1_H5_OUTER_AUTHORITY_ARTIFACT"
    assert manifest["file_count"] == 1
    row = manifest["files"][0]
    assert (
        row["sha256"] == hashlib.sha256((root / "capture.log").read_bytes()).hexdigest()
    )
    assert json.loads((root / "artifact_manifest.json").read_text()) == manifest
    with pytest.raises(C12AArtifactManifestError, match="already sealed"):
        seal_authority_artifact(
            root, implementation_sha=SHA, authoritative_run_id="12345"
        )


def test_economic_failure_is_valid_nonzero_exit() -> None:
    assert classification_exit_code("ECONOMIC_PASS") == 0
    assert classification_exit_code("ECONOMIC_FAIL") == 1
    with pytest.raises(C12AHistoricalEvidenceError):
        classification_exit_code("PROGRAM_FAILURE")


def _synthetic_capture(root: Path) -> None:
    package = C12ACapturePackage(root)
    binding = {
        "schema_version": 1,
        "stage": "C12A_HISTORICAL_CHECKOUT_BINDING",
        "implementation_sha": SHA,
        "observed_head_sha": SHA,
        "tracked_worktree_clean": True,
    }
    package.write_json("checkout_binding.json", binding)
    request = build_futures_manifest_request(family="BTC-USDT", month="2024-03")
    raw = b'{"code":"0","data":[]}\n'
    package.retain_raw(
        raw,
        CaptureRecord(
            request_id=request.request_id,
            source_family=request.source_family,
            requested_url=request.url,
            final_url=request.url,
            collected_at="2026-08-22T00:00:00Z",
            media_type="application/json",
            size=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            relative_path="",
        ),
    )
    decisions = contract_decisions()
    spot_stamps = {instrument: set() for instrument in ("BTC-USDT", "ETH-USDT")}
    for decision in decisions:
        current = decision.signal_cutoff - timedelta(hours=1)
        while current <= decision.exit_timestamp:
            spot_stamps[decision.spot_instrument].add(current)
            current += timedelta(hours=1)
    for window in WINDOWS:
        for index in range(27):
            spot_stamps["BTC-USDT"].add(
                window.start + index * timedelta(days=7) - timedelta(hours=1)
            )

    def spot_price(stamp: datetime, *, asset_offset: int) -> Decimal:
        hour = int(stamp.timestamp() // 3600)
        return Decimal(100 + asset_offset) + Decimal(hour % 17) / Decimal(10)

    spot_rows: dict[str, list[dict[str, str]]] = {}
    for instrument, stamps in spot_stamps.items():
        offset = 0 if instrument.startswith("BTC") else 20
        spot_rows[instrument] = [
            {
                "instrument": instrument,
                "timestamp": iso_z(stamp),
                "open": str(spot_price(stamp, asset_offset=offset)),
                "close": str(spot_price(stamp, asset_offset=offset)),
            }
            for stamp in sorted(stamps)
        ]
        package.retain_normalized_series(
            series_type="trades",
            instrument=instrument,
            start_inclusive=str(capture_plan()["spot_start_inclusive"]),
            end_exclusive=str(capture_plan()["spot_end_exclusive"]),
            rows=spot_rows[instrument],
        )
    for decision in decisions:
        rows = []
        current = decision.signal_cutoff - timedelta(hours=1)
        trade_id = 1
        offset = 0 if decision.asset == "BTC" else 20
        while current <= decision.exit_timestamp:
            price = spot_price(current, asset_offset=offset) + Decimal(6)
            rows.append(
                {
                    "instrument": decision.futures_instrument,
                    "trade_id": str(trade_id),
                    "side": "buy",
                    "price": str(price),
                    "size": "1",
                    "timestamp": iso_z(current),
                }
            )
            current += timedelta(hours=1)
            trade_id += 1
        package.retain_normalized_series(
            series_type="trades",
            instrument=decision.futures_instrument,
            start_inclusive=iso_z(decision.signal_cutoff - timedelta(hours=1)),
            end_exclusive=iso_z(decision.exit_timestamp + timedelta(hours=1)),
            rows=rows,
        )
    package.finalize(implementation_sha=SHA, frozen_capture_plan=capture_plan())


def test_end_to_end_evidence_recomputes_from_primitive_rows(tmp_path: Path) -> None:
    capture = tmp_path / "capture"
    evidence = tmp_path / "evidence"
    _synthetic_capture(capture)
    binding = {
        "schema_version": 1,
        "stage": "C12A_HISTORICAL_CHECKOUT_BINDING",
        "implementation_sha": SHA,
        "observed_head_sha": SHA,
        "tracked_worktree_clean": True,
    }
    final, manifest = build_h1_h5_evidence_package(
        evidence,
        capture_root=capture,
        repository_root=Path(__file__).parents[2],
        implementation_sha=SHA,
        authoritative_run_id="synthetic-test",
        evaluation_checkout_binding=binding,
        evaluated_at=datetime(2026, 8, 22, tzinfo=UTC),
    )
    assert final["classification"] in {"ECONOMIC_PASS", "ECONOMIC_FAIL"}
    assert final["data_custody_passed"] is True
    assert final["independent_recompute_passed"] is True
    assert final["authoritative_rerun_authorized"] is False
    assert manifest["file_count"] == 17
    assert (
        verify_evidence_package(evidence, implementation_sha=SHA)["verified_file_count"]
        == 17
    )


def test_one_shot_authority_workflow_is_explicit_main_only_and_fail_closed() -> None:
    workflow = (
        Path(__file__).parents[2] / ".github" / "workflows" / "freqtrade-validation.yml"
    )
    text = workflow.read_text(encoding="utf-8")
    assert text.count("c12a_h1_h5_authoritative:") == 1
    assert text.count("c12a-h1-h5-authoritative:") == 1
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "cancel-in-progress: false" in text
    assert 'if [ "${status}" -gt 1 ]; then exit "${status}"; fi' in text
    assert "implementation/c12a_authority" in text
    assert "c12a_h1_h5_capture.py" in text
    assert "c12a_h1_h5_evaluate.py" in text
    assert "Account/private/order/Paper/Shadow/Live side effects: `NONE`" in text
