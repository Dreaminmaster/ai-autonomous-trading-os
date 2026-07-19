from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

IMPL = Path(__file__).resolve().parents[1]


def _load_module(name: str, relative: str):
    path = IMPL / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = _load_module("c4a_contract_guard_test", "scripts/c4a_contract_guard.py")
data_guard = _load_module("c4a_data_guard_test", "scripts/c4a_data_guard.py")


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, timestamp in enumerate(contract.expected_timestamps()):
        price = 100.0 + index / 1000.0
        rows.append(
            {
                "date": timestamp.isoformat(),
                "open": price,
                "high": price + 1.0,
                "low": price - 1.0,
                "close": price + 0.25,
                "volume": 1000.0 + index,
            }
        )
    return rows


def test_config_canonical_hash_and_safety_are_frozen() -> None:
    config = contract.load_and_verify_config()
    assert config["stage"] == "C4A"
    assert contract.EXPECTED_CONFIG_CANONICAL_SHA256 == (
        "14e7b96d1167afad6b23c1bc6302e7f9b86ad291f956944ba8f546908402fa92"
    )
    assert config["confirmation_opened"] is False
    assert config["holdout_state"] == "HOLDOUT_CLOSED"
    assert config["live"] == "FORBIDDEN"


def test_contract_guard_accepts_exact_grid_and_counts() -> None:
    report = contract.verify_rows(
        _rows(),
        "BTC/USDT",
        allow_post_boundary_overshoot=False,
    )
    assert report["retained_rows"] == 2376
    assert report["formation_rows"] == 732
    assert report["screen_rows"] == 1644
    assert report["post_boundary_rows"] == 0


def test_contract_precheck_allows_only_post_boundary_overshoot() -> None:
    rows = _rows()
    rows.append(
        {
            "date": "2024-10-01T00:00:00+00:00",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        }
    )
    report = contract.verify_rows(
        rows,
        "ETH/USDT",
        allow_post_boundary_overshoot=True,
    )
    assert report["post_boundary_rows"] == 1
    with pytest.raises(contract.C4AContractGuardError, match="post-boundary"):
        contract.verify_rows(
            rows,
            "ETH/USDT",
            allow_post_boundary_overshoot=False,
        )


def test_unordered_duplicate_missing_and_invalid_ohlc_fail_closed() -> None:
    rows = _rows()
    unordered = rows.copy()
    unordered[10], unordered[11] = unordered[11], unordered[10]
    with pytest.raises(contract.C4AContractGuardError, match="unordered"):
        contract.verify_rows(unordered, "SOL/USDT", allow_post_boundary_overshoot=False)

    duplicate = rows.copy()
    duplicate[11] = dict(duplicate[10])
    with pytest.raises(contract.C4AContractGuardError, match="duplicate"):
        contract.verify_rows(duplicate, "SOL/USDT", allow_post_boundary_overshoot=False)

    missing = rows[:-1]
    with pytest.raises(contract.C4AContractGuardError, match="sequence mismatch"):
        contract.verify_rows(missing, "SOL/USDT", allow_post_boundary_overshoot=False)

    invalid = _rows()
    invalid[0] = dict(invalid[0], high=90.0)
    with pytest.raises(contract.C4AContractGuardError, match="OHLC"):
        contract.verify_rows(invalid, "SOL/USDT", allow_post_boundary_overshoot=False)


def test_data_guard_exact_coverage_matches_contract_grid() -> None:
    report = data_guard.validate_rows(_rows(), "XRP/USDT")
    assert report["rows"] == 2376
    assert report["formation_rows"] == 732
    assert report["screen_rows"] == 1644
    assert report["gaps"] == 0
    assert report["duplicates"] == 0


def test_config_file_is_valid_json_object() -> None:
    payload = json.loads(
        (IMPL / "config/c4a_large_liquid_cross_sectional_momentum.json").read_text(
            encoding="utf-8"
        )
    )
    assert isinstance(payload, dict)
    assert payload["candidate_pairs"] == list(contract.CANDIDATE_PAIRS)
