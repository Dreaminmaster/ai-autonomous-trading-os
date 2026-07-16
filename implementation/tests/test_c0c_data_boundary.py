from __future__ import annotations

import csv
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "implementation" / "scripts" / "sanitize_c0c_data_boundary.py"
WORKFLOW = ROOT / ".github" / "workflows" / "c0c-cost-aware-ema.yml"
FINALIZER = ROOT / "implementation" / "scripts" / "finalize_c0c_manifest.py"
SPEC = importlib.util.spec_from_file_location("sanitize_c0c_data_boundary", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
boundary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boundary)


def _write_csv(path: Path) -> None:
    rows = [
        {"date": "2025-06-30T23:50:00+00:00", "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"},
        {"date": "2025-06-30T23:55:00+00:00", "open": "2", "high": "2", "low": "2", "close": "2", "volume": "2"},
        {"date": "2025-07-01T00:00:00+00:00", "open": "3", "high": "3", "low": "3", "close": "3", "volume": "3"},
        {"date": "2025-07-01T00:05:00+00:00", "open": "4", "high": "4", "low": "4", "close": "4", "volume": "4"},
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_sanitizer_removes_only_rows_at_or_after_holdout(tmp_path: Path) -> None:
    path = tmp_path / "BTC_USDT-5m.csv"
    _write_csv(path)
    result = boundary.sanitize_file(
        path,
        pair="BTC/USDT",
        timeframe="5m",
        holdout_start=datetime(2025, 7, 1, tzinfo=UTC),
    )
    assert result["status"] == "PASS"
    assert result["original_rows"] == 4
    assert result["retained_rows"] == 2
    assert result["removed_rows"] == 2
    assert result["first_removed"] == "2025-07-01T00:00:00+00:00"
    assert result["retained_latest"] == "2025-06-30T23:55:00+00:00"
    assert result["post_boundary_rows"] == 0
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["date"] for row in rows] == [
        "2025-06-30T23:50:00+00:00",
        "2025-06-30T23:55:00+00:00",
    ]


def test_sanitizer_is_idempotent_when_no_overshoot_remains(tmp_path: Path) -> None:
    path = tmp_path / "ETH_USDT-5m.csv"
    _write_csv(path)
    holdout = datetime(2025, 7, 1, tzinfo=UTC)
    boundary.sanitize_file(path, pair="ETH/USDT", timeframe="5m", holdout_start=holdout)
    result = boundary.sanitize_file(path, pair="ETH/USDT", timeframe="5m", holdout_start=holdout)
    assert result["removed_rows"] == 0
    assert result["retained_rows"] == 2
    assert result["post_boundary_rows"] == 0


def test_workflow_and_manifest_bind_boundary_sanitization() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    finalizer = FINALIZER.read_text(encoding="utf-8")
    assert "implementation/scripts/sanitize_c0c_data_boundary.py" in workflow
    assert "implementation/tests/test_c0c_data_boundary.py" in workflow
    assert "python scripts/sanitize_c0c_data_boundary.py" in workflow
    assert workflow.index("python scripts/sanitize_c0c_data_boundary.py") < workflow.index(
        "python scripts/verify_c0c_data_coverage.py"
    )
    assert "c0c_data_boundary.json" in finalizer
    assert 'payload["data_boundary"]' in finalizer
    assert "boundary source SHA does not match C0C_SOURCE_SHA" in finalizer
