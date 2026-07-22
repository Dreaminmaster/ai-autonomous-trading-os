from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from atos.c6a_comparators import simulate_cash_window, simulate_spot_buy_hold_window
from atos.c6a_contract import MetadataRecord
from atos.c6a_data import C6AMarket, validate_mark_candles, validate_trade_candles

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def market(start: datetime, end: datetime) -> C6AMarket:
    count = int((end - start).total_seconds() // 3600)
    rows = []
    for index in range(count):
        price = Decimal("100") + Decimal(index) / Decimal("10000")
        rows.append(
            {
                "timestamp": (start + timedelta(hours=index)).isoformat(),
                "open": str(price),
                "high": str(price),
                "low": str(price),
                "close": str(price),
                "quote_volume": "1",
            }
        )
    marks = [{key: value for key, value in row.items() if key != "quote_volume"} for row in rows]
    return C6AMarket(
        spot={
            instrument: validate_trade_candles(rows, instrument=instrument, start=start, end=end)
            for instrument in ("BTC-USDT", "ETH-USDT")
        },
        swap={
            instrument: validate_trade_candles(rows, instrument=instrument, start=start, end=end)
            for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
        },
        mark={
            instrument: validate_mark_candles(marks, instrument=instrument, start=start, end=end)
            for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
        },
    )


def metadata(start: datetime) -> tuple[MetadataRecord, ...]:
    rows = []
    for instrument in ("BTC-USDT", "ETH-USDT"):
        rows.append(
            MetadataRecord.from_mapping(
                {
                    "instId": instrument,
                    "instType": "SPOT",
                    "baseCcy": instrument.split("-")[0],
                    "quoteCcy": "USDT",
                    "settleCcy": "",
                    "ctVal": "",
                    "ctValCcy": "",
                    "lotSz": "0.001",
                    "minSz": "0.001",
                    "tickSz": "0.001",
                    "effective_from": start.isoformat(),
                    "source": "synthetic public fixture",
                    "source_sha256": "a" * 64,
                }
            )
        )
    return tuple(rows)


def test_cash_comparator_is_exactly_zero_and_inactive() -> None:
    payload = config()
    result = simulate_cash_window(
        window=payload["windows"][0], cost_label="1.0x", config=payload
    )
    assert result["final_equity"] == "1000"
    assert result["net_return"] == "0"
    assert len(result["weekly_buckets"]) == 26
    assert result["active_week_count"] == 0
    assert result["live"] == "FORBIDDEN"


def test_spot_buy_hold_is_descriptive_and_terminally_liquidated() -> None:
    payload = config()
    start = datetime(2023, 7, 3, tzinfo=UTC)
    end = datetime(2024, 1, 1, tzinfo=UTC)
    result = simulate_spot_buy_hold_window(
        market(start, end),
        metadata(start),
        window=payload["windows"][0],
        cost_label="1.0x",
        config=payload,
    )
    assert result["policy_id"] == "SpotBuyAndHoldComparator"
    assert len(result["weekly_buckets"]) == 26
    assert result["active_week_count"] == 26
    assert Decimal(result["final_equity"]) > Decimal("1000")
    assert result["events"][-1]["time"] == "2023-12-31T23:00:00+00:00"
    total_contribution = sum(
        (Decimal(value) for value in result["asset_contributions"].values()),
        Decimal("0"),
    )
    assert total_contribution == Decimal(result["final_equity"]) - Decimal("1000")
