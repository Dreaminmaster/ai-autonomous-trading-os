from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from atos.c0b_export import (
    C0BExportDiscoveryError,
    discover_authoritative_export,
)


STRATEGIES = ["C0BEMATrend", "C0BDonchianBreakout", "C0BMeanReversion"]


def _payload(strategies=STRATEGIES):
    return {
        "strategy": {
            name: {
                "trades": [],
                "results_per_pair": [],
            }
            for name in strategies
        }
    }


def _write_zip(path: Path, strategies=STRATEGIES) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("backtest-result.json", json.dumps(_payload(strategies)))
        archive.writestr("backtest-result.meta.json", json.dumps({"metadata": True}))


def test_discovers_unique_timestamped_zip(tmp_path: Path) -> None:
    expected = tmp_path / "backtest-result-2026-07-14_15-00-00.zip"
    _write_zip(expected)
    (tmp_path / "backtest-result-2026-07-14_15-00-00.meta.json").write_text("{}")

    assert discover_authoritative_export(tmp_path, STRATEGIES) == expected


def test_direct_json_is_supported_for_legacy_exports(tmp_path: Path) -> None:
    expected = tmp_path / "backtest-result.json"
    expected.write_text(json.dumps(_payload()), encoding="utf-8")

    assert discover_authoritative_export(tmp_path, STRATEGIES) == expected


def test_missing_authoritative_export_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "backtest-result.meta.json").write_text("{}", encoding="utf-8")

    with pytest.raises(C0BExportDiscoveryError, match="expected one authoritative"):
        discover_authoritative_export(tmp_path, STRATEGIES)


def test_multiple_authoritative_exports_fail_closed(tmp_path: Path) -> None:
    _write_zip(tmp_path / "first.zip")
    _write_zip(tmp_path / "second.zip")

    with pytest.raises(C0BExportDiscoveryError, match="found"):
        discover_authoritative_export(tmp_path, STRATEGIES)


def test_strategy_set_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_zip(tmp_path / "wrong.zip", ["C0BEMATrend"])

    with pytest.raises(C0BExportDiscoveryError, match="strategy set"):
        discover_authoritative_export(tmp_path, STRATEGIES)


def test_duplicate_expected_strategy_names_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(C0BExportDiscoveryError, match="duplicates"):
        discover_authoritative_export(tmp_path, ["C0BEMATrend", "C0BEMATrend"])
