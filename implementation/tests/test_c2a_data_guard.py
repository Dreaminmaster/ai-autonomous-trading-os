from __future__ import annotations

import csv
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "implementation/scripts/c2a_data_guard.py"


def module():
    spec = importlib.util.spec_from_file_location("c2a_data_guard_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def row(when: datetime, price: float = 100.0) -> dict:
    return {
        "date": when.isoformat(),
        "open": price,
        "high": price + 1,
        "low": price - 1,
        "close": price + 0.5,
        "volume": 1000.0,
    }


def required_rows() -> list[dict]:
    start = datetime(2024, 1, 1, tzinfo=UTC) - timedelta(days=220)
    end = datetime(2024, 10, 1, tzinfo=UTC) - timedelta(days=1)
    count = (end - start).days + 1
    return [row(start + timedelta(days=index), 100.0 + index) for index in range(count)]


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_config_is_frozen_and_safe() -> None:
    loaded = module()
    config = loaded.load_config()
    assert config["stage"] == "C2A"
    assert config["download_timerange"] == "20230501-20241001"
    assert config["startup_history_candles"] == 220
    assert config["confirmation_opened"] is False
    assert config["holdout_state"] == "HOLDOUT_CLOSED"
    assert config["live"] == "FORBIDDEN"


def test_validate_rows_requires_complete_220_day_startup_and_screen() -> None:
    loaded = module()
    report = loaded.validate_rows(required_rows(), "BTC/USDT", 220)
    assert report["status"] == "PASS"
    assert report["required_rows"] == len(required_rows())
    assert report["required_earliest"].startswith("2023-05-26")
    assert report["required_latest"].startswith("2024-09-30")


def test_validate_rows_fails_closed_on_gap_or_duplicate() -> None:
    loaded = module()
    rows = required_rows()
    with pytest.raises(loaded.C2ADataGuardError, match="daily coverage mismatch|daily gap"):
        loaded.validate_rows(rows[:100] + rows[101:], "ETH/USDT", 220)
    duplicated = rows + [dict(rows[-1])]
    with pytest.raises(loaded.C2ADataGuardError, match="duplicate"):
        loaded.validate_rows(duplicated, "SOL/USDT", 220)


def test_sanitize_removes_boundary_overshoot(tmp_path: Path) -> None:
    loaded = module()
    path = tmp_path / "BTC_USDT-1d.csv"
    rows = required_rows()
    rows.extend(
        [
            row(datetime(2024, 10, 1, tzinfo=UTC), 999.0),
            row(datetime(2024, 10, 2, tzinfo=UTC), 1000.0),
        ]
    )
    write_csv(path, rows)
    report = loaded.sanitize_file(path, "BTC/USDT")
    assert report["status"] == "PASS"
    assert report["removed_rows"] == 2
    assert report["post_boundary_rows"] == 0
    assert report["retained_latest"].startswith("2024-09-30")


def test_boundary_report_requires_exact_three_daily_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = module()
    config = loaded.load_config()
    monkeypatch.setattr(
        loaded,
        "sanitize_file",
        lambda path, pair: {
            "pair": pair,
            "timeframe": "1d",
            "post_boundary_rows": 0,
            "retained_latest": "2024-09-30T00:00:00+00:00",
            "status": "PASS",
        },
    )
    monkeypatch.setattr(loaded, "discover_candle_file", lambda *args: Path("dummy.csv"))
    report = loaded.build_boundary_report(config, "a" * 40)
    assert report["status"] == "PASS"
    assert len(report["cells"]) == 3
    assert report["source_head_sha"] == "a" * 40
    loaded.validate_boundary_report(report, "a" * 40)
