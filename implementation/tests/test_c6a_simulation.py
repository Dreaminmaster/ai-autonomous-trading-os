from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from atos.c6a_contract import FundingRecord, MetadataRecord
from atos.c6a_data import C6AMarket, validate_mark_candles, validate_trade_candles
from atos.c6a_simulation import simulate_policy_window

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def candle_rows(start: datetime, end: datetime, *, price: str = "100") -> list[dict]:
    count = int((end - start).total_seconds() // 3600)
    return [
        {
            "timestamp": (start + timedelta(hours=index)).isoformat(),
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "quote_volume": "1000000",
        }
        for index in range(count)
    ]


def synthetic_market(start: datetime, end: datetime) -> C6AMarket:
    rows = candle_rows(start, end)
    spot = {
        instrument: validate_trade_candles(
            rows, instrument=instrument, start=start, end=end
        )
        for instrument in ("BTC-USDT", "ETH-USDT")
    }
    swap = {
        instrument: validate_trade_candles(
            rows, instrument=instrument, start=start, end=end
        )
        for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
    }
    mark_rows = [
        {key: value for key, value in row.items() if key != "quote_volume"}
        for row in rows
    ]
    mark = {
        instrument: validate_mark_candles(
            mark_rows, instrument=instrument, start=start, end=end
        )
        for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
    }
    result = C6AMarket(spot=spot, swap=swap, mark=mark)
    result.validate_alignment()
    return result


def funding_records(start: datetime, end: datetime, rate: str) -> tuple[FundingRecord, ...]:
    output = []
    for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP"):
        current = start
        while current < end:
            output.append(FundingRecord(instrument, current, Decimal(rate)))
            current += timedelta(hours=8)
    return tuple(sorted(output, key=lambda row: (row.instrument, row.funding_time)))


def metadata_records(start: datetime) -> tuple[MetadataRecord, ...]:
    output = []
    for instrument in ("BTC-USDT", "ETH-USDT"):
        base = instrument.split("-")[0]
        output.append(
            MetadataRecord.from_mapping(
                {
                    "instId": instrument,
                    "instType": "SPOT",
                    "baseCcy": base,
                    "quoteCcy": "USDT",
                    "settleCcy": "",
                    "ctVal": "",
                    "ctValCcy": "",
                    "lotSz": "0.1",
                    "minSz": "0.1",
                    "tickSz": "0.1",
                    "effective_from": start.isoformat(),
                    "source": "synthetic public test fixture",
                    "source_sha256": "a" * 64,
                }
            )
        )
        output.append(
            MetadataRecord.from_mapping(
                {
                    "instId": f"{base}-USDT-SWAP",
                    "instType": "SWAP",
                    "baseCcy": base,
                    "quoteCcy": "USDT",
                    "settleCcy": "USDT",
                    "ctVal": "0.1",
                    "ctValCcy": base,
                    "lotSz": "1",
                    "minSz": "1",
                    "tickSz": "0.1",
                    "effective_from": start.isoformat(),
                    "source": "synthetic public test fixture",
                    "source_sha256": "b" * 64,
                }
            )
        )
    return tuple(output)


def test_positive_actual_funding_produces_complete_independent_window_evidence() -> None:
    payload = config()
    window = payload["windows"][0]
    download_start = datetime(2023, 6, 5, tzinfo=UTC)
    end = datetime(2024, 1, 1, tzinfo=UTC)
    result = simulate_policy_window(
        synthetic_market(download_start, end),
        funding_records(download_start, end, "0.00012"),
        metadata_records(download_start),
        policy_id="C6AMarketNeutralFundingCarry",
        window=window,
        cost_label="1.0x",
        config=payload,
    )
    assert result["status"] == "PASS"
    assert Decimal(result["final_equity"]) > Decimal("1000")
    assert Decimal(result["net_return"]) > 0
    assert len(result["weekly_buckets"]) == 26
    assert len(result["decisions"]) == 26
    assert result["active_week_count"] == 26
    assert result["active_funding_settlements"] > 100
    assert result["collateral_buffer_breaches"] == 0
    assert result["hedge_breaches"] == 0
    assert all(Decimal(row["reconciliation_residual"]) == 0 for row in result["weekly_buckets"])
    terminal_events = [row for row in result["events"] if row["kind"] == "TERMINAL_LIQUIDATION"]
    assert len(terminal_events) == 2
    assert {row["time"] for row in terminal_events} == {"2023-12-31T23:00:00+00:00"}
    assert result["c5b_state"] == "C5B_CLOSED_AND_UNTOUCHED"
    assert result["live"] == "FORBIDDEN"


def test_negative_funding_candidate_stays_in_cash() -> None:
    payload = config()
    window = payload["windows"][0]
    download_start = datetime(2023, 6, 5, tzinfo=UTC)
    end = datetime(2024, 1, 1, tzinfo=UTC)
    result = simulate_policy_window(
        synthetic_market(download_start, end),
        funding_records(download_start, end, "-0.00012"),
        metadata_records(download_start),
        policy_id="C6AMarketNeutralFundingCarry",
        window=window,
        cost_label="1.0x",
        config=payload,
    )
    assert Decimal(result["final_equity"]) == Decimal("1000")
    assert result["active_week_count"] == 0
    assert result["active_funding_settlements"] == 0
    assert not [row for row in result["events"] if row["kind"] == "SCHEDULED_TRADE" and Decimal(row["normalized_one_way_turnover"]) > 0]
