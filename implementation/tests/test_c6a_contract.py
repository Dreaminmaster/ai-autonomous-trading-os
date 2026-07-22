from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from atos.c6a_contract import (
    C6AError,
    FundingRecord,
    MetadataRecord,
    candidate_eligible,
    decision_times,
    funding_signal,
    metadata_at,
    risk_exit_required,
    terminal_time,
    validate_config,
    validate_funding_records,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def test_frozen_config_and_window_grid() -> None:
    payload = config()
    validate_config(payload)
    assert [len(decision_times(window)) for window in payload["windows"]] == [26] * 5
    assert terminal_time(payload["windows"][0]) == datetime(2023, 12, 31, 23, tzinfo=UTC)
    assert terminal_time(payload["windows"][-1]) == datetime(2025, 12, 28, 23, tzinfo=UTC)


def test_any_config_drift_fails_closed() -> None:
    payload = copy.deepcopy(config())
    payload["maximum_entry_abs_basis"] = "0.0200001"
    with pytest.raises(C6AError, match="semantic configuration drift"):
        validate_config(payload)


def test_funding_records_allow_variable_intervals_without_rescaling() -> None:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    rows = []
    for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP"):
        for offset, rate in ((0, "0.0001"), (6, "0.0002"), (14, "-0.0001")):
            rows.append(
                {
                    "instId": instrument,
                    "fundingTime": int((base + timedelta(hours=offset)).timestamp() * 1000),
                    "realizedRate": rate,
                }
            )
    records = validate_funding_records(rows)
    btc = [row for row in records if row.instrument == "BTC-USDT-SWAP"]
    assert [row.funding_time - base for row in btc] == [
        timedelta(0),
        timedelta(hours=6),
        timedelta(hours=14),
    ]


def test_funding_history_duplicate_or_closed_boundary_fails() -> None:
    base = datetime(2025, 12, 28, 16, tzinfo=UTC)
    rows = [
        {"instId": "BTC-USDT-SWAP", "fundingTime": base.isoformat(), "realizedRate": "0.1"},
        {"instId": "BTC-USDT-SWAP", "fundingTime": base.isoformat(), "realizedRate": "0.1"},
        {"instId": "ETH-USDT-SWAP", "fundingTime": base.isoformat(), "realizedRate": "0.1"},
    ]
    with pytest.raises(C6AError, match="ordered and unique"):
        validate_funding_records(rows)

    rows[1]["fundingTime"] = datetime(2025, 12, 29, tzinfo=UTC).isoformat()
    with pytest.raises(C6AError):
        validate_funding_records(rows)


def test_signal_uses_only_actual_predecision_settlements() -> None:
    decision = datetime(2024, 2, 5, tzinfo=UTC)
    records = (
        FundingRecord("BTC-USDT-SWAP", decision - timedelta(days=27), Decimal("0.004")),
        FundingRecord("BTC-USDT-SWAP", decision - timedelta(days=14), Decimal("0.004")),
        FundingRecord("BTC-USDT-SWAP", decision - timedelta(hours=1), Decimal("0.004")),
        FundingRecord("BTC-USDT-SWAP", decision, Decimal("9")),
    )
    signal = funding_signal(records, instrument="BTC-USDT-SWAP", decision_time=decision)
    assert signal == {
        "settlement_count": 3,
        "positive_settlement_count": 3,
        "funding_sum_28d": Decimal("0.012"),
        "positive_funding_share_28d": Decimal("1"),
    }
    assert candidate_eligible(signal, basis="0.01", config=config()) is True
    assert candidate_eligible(signal, basis="0.021", config=config()) is False


def metadata(
    instrument: str,
    start: datetime,
    end: datetime | None,
    *,
    source_hash: str = "a" * 64,
) -> MetadataRecord:
    is_swap = instrument.endswith("SWAP")
    base = instrument.split("-")[0]
    return MetadataRecord.from_mapping(
        {
            "instId": instrument,
            "instType": "SWAP" if is_swap else "SPOT",
            "baseCcy": base,
            "quoteCcy": "USDT",
            "settleCcy": "USDT" if is_swap else "",
            "ctVal": "0.01" if is_swap else "",
            "ctValCcy": base if is_swap else "",
            "lotSz": "0.001",
            "minSz": "0.001",
            "tickSz": "0.1",
            "effective_from": start.isoformat(),
            "effective_to": None if end is None else end.isoformat(),
            "source": "public archive fixture",
            "source_sha256": source_hash,
        }
    )


def test_timestamp_effective_metadata_must_be_unique() -> None:
    start = datetime(2023, 1, 1, tzinfo=UTC)
    transition = datetime(2024, 1, 1, tzinfo=UTC)
    records = [
        metadata("BTC-USDT-SWAP", start, transition),
        metadata("BTC-USDT-SWAP", transition, None),
    ]
    assert metadata_at(records, "BTC-USDT-SWAP", transition).effective_from == transition
    with pytest.raises(C6AError, match="found 0"):
        metadata_at(records, "BTC-USDT-SWAP", start - timedelta(seconds=1))
    with pytest.raises(C6AError, match="found 2"):
        metadata_at(records + [metadata("BTC-USDT-SWAP", start, None)], "BTC-USDT-SWAP", transition)


def test_invalid_or_future_projected_metadata_fails_closed() -> None:
    with pytest.raises(C6AError, match="SHA-256"):
        metadata("BTC-USDT", datetime(2024, 1, 1, tzinfo=UTC), None, source_hash="bad")
    with pytest.raises(C6AError, match="base-denominated"):
        MetadataRecord.from_mapping(
            {
                "instId": "BTC-USDT-SWAP",
                "instType": "SWAP",
                "baseCcy": "BTC",
                "quoteCcy": "USDT",
                "settleCcy": "USDT",
                "ctVal": "0.01",
                "ctValCcy": "USDT",
                "lotSz": "1",
                "minSz": "1",
                "tickSz": "0.1",
                "effective_from": "2024-01-01T00:00:00Z",
                "source": "public",
                "source_sha256": "b" * 64,
            }
        )


def test_risk_exit_is_strictly_conservative() -> None:
    payload = config()
    assert risk_exit_required(basis="0.0501", collateral_buffer_ratio="2", config=payload)
    assert risk_exit_required(basis="0", collateral_buffer_ratio="1.2499", config=payload)
    assert not risk_exit_required(basis="0.05", collateral_buffer_ratio="1.25", config=payload)
