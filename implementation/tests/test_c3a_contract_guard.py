from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

import scripts.c3a_contract_guard as guard


START = datetime(2023, 9, 1, tzinfo=UTC)
END = datetime(2024, 10, 1, tzinfo=UTC)
STEP = timedelta(hours=4)


def full_rows() -> list[dict]:
    rows: list[dict] = []
    current = START
    while current < END:
        rows.append({"date": current.isoformat(), "open": 100.0, "close": 101.0})
        current += STEP
    return rows


def test_exact_semantic_config_is_frozen() -> None:
    payload = guard.load_and_verify_config()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert guard.hashlib.sha256(canonical.encode("utf-8")).hexdigest() == guard.EXPECTED_CONFIG_CANONICAL_SHA256
    assert payload["confirmation_opened"] is False
    assert payload["holdout_state"] == "HOLDOUT_CLOSED"
    assert payload["live"] == "FORBIDDEN"


def test_full_download_range_is_required_not_only_minimum_startup() -> None:
    payload = full_rows()
    report = guard.verify_rows(payload, "BTC/USDT", allow_post_boundary_overshoot=False)
    assert report["retained_earliest"] == START.isoformat()
    assert report["retained_latest"] == (END - STEP).isoformat()
    assert report["startup_bars"] >= 450

    # This omission is before the old 450-bar minimum boundary and must still fail.
    del payload[25]
    with pytest.raises(guard.C3AContractGuardError, match="full retained four-hour sequence mismatch"):
        guard.verify_rows(payload, "BTC/USDT", allow_post_boundary_overshoot=False)


def test_unordered_input_is_rejected_instead_of_silently_sorted() -> None:
    payload = full_rows()
    payload[10], payload[11] = payload[11], payload[10]
    with pytest.raises(guard.C3AContractGuardError, match="unordered"):
        guard.verify_rows(payload, "ETH/USDT", allow_post_boundary_overshoot=True)


def test_precheck_allows_api_overshoot_but_postcheck_rejects_it() -> None:
    payload = full_rows()
    payload.append({"date": END.isoformat(), "open": 100.0, "close": 101.0})
    pre = guard.verify_rows(payload, "SOL/USDT", allow_post_boundary_overshoot=True)
    assert pre["post_boundary_rows"] == 1
    with pytest.raises(guard.C3AContractGuardError, match="post-boundary"):
        guard.verify_rows(payload, "SOL/USDT", allow_post_boundary_overshoot=False)
