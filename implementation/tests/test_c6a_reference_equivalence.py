from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from atos.c6a_contract import FundingRecord, MetadataRecord
from atos.c6a_data import C6AMarket, validate_mark_candles, validate_trade_candles
from atos.c6a_simulation import simulate_policy_window
from scripts.c6a_reference_recompute import recompute_window

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def market(start: datetime, end: datetime) -> C6AMarket:
    count = int((end - start).total_seconds() // 3600)
    trade_rows = [
        {
            "timestamp": (start + timedelta(hours=index)).isoformat(),
            "open": "100",
            "high": "100",
            "low": "100",
            "close": "100",
            "quote_volume": "1000",
        }
        for index in range(count)
    ]
    mark_rows = [
        {key: value for key, value in row.items() if key != "quote_volume"}
        for row in trade_rows
    ]
    result = C6AMarket(
        spot={
            instrument: validate_trade_candles(
                trade_rows, instrument=instrument, start=start, end=end
            )
            for instrument in ("BTC-USDT", "ETH-USDT")
        },
        swap={
            instrument: validate_trade_candles(
                trade_rows, instrument=instrument, start=start, end=end
            )
            for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
        },
        mark={
            instrument: validate_mark_candles(
                mark_rows, instrument=instrument, start=start, end=end
            )
            for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
        },
    )
    result.validate_alignment()
    return result


def funding(start: datetime, end: datetime, rate: str) -> tuple[FundingRecord, ...]:
    rows = []
    for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP"):
        current = start
        while current < end:
            rows.append(FundingRecord(instrument, current, Decimal(rate)))
            current += timedelta(hours=8)
    return tuple(sorted(rows, key=lambda row: (row.instrument, row.funding_time)))


def metadata(start: datetime) -> tuple[MetadataRecord, ...]:
    rows = []
    for base in ("BTC", "ETH"):
        rows.append(
            MetadataRecord.from_mapping(
                {
                    "instId": f"{base}-USDT",
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
                    "source": "synthetic public fixture",
                    "source_sha256": "a" * 64,
                }
            )
        )
        rows.append(
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
                    "source": "synthetic public fixture",
                    "source_sha256": "b" * 64,
                }
            )
        )
    return tuple(rows)


def assert_equivalent(production: dict, reference: dict) -> None:
    assert Decimal(production["final_equity"]) == reference["final_equity"]
    assert Decimal(production["net_return"]) == reference["net_return"]
    assert Decimal(production["maximum_drawdown"]) == reference["maximum_drawdown"]
    assert Decimal(production["annualized_one_way_turnover"]) == reference[
        "annualized_one_way_turnover"
    ]
    assert production["active_week_count"] == reference["active_week_count"]
    assert production["active_funding_settlements"] == reference[
        "active_funding_settlements"
    ]
    assert production["collateral_buffer_breaches"] == reference[
        "collateral_buffer_breaches"
    ]
    assert production["hedge_breaches"] == reference["hedge_breaches"]
    for asset, value in reference["asset_contributions"].items():
        assert Decimal(production["asset_contributions"][asset]) == value
    assert len(production["weekly_buckets"]) == len(reference["weekly"]) == 26
    for production_week, reference_week in zip(
        production["weekly_buckets"], reference["weekly"], strict=True
    ):
        assert Decimal(production_week["weekly_pnl"]) == reference_week["pnl"]
        assert Decimal(production_week["weekly_return"]) == reference_week["return"]
        assert production_week["active"] == reference_week["active"]
        assert production_week["risk_exit"] == reference_week["risk_exit"]
    assert len(production["decisions"]) == len(reference["decisions"]) == 26
    for production_decision, reference_decision in zip(
        production["decisions"], reference["decisions"], strict=True
    ):
        assert production_decision["time"] == reference_decision["time"].isoformat()
        assert tuple(production_decision["eligible_assets"]) == reference_decision[
            "eligible_assets"
        ]
        assert Decimal(production_decision["target_scale"]) == reference_decision["scale"]
        for production_target in production_decision["targets"]:
            spot = production_target["spot_instrument"]
            reference_target = reference_decision["targets"][spot]
            assert production_target["action"] == reference_target["action"]
            assert Decimal(production_target["spot_quantity"]) == reference_target[
                "spot_quantity"
            ]
            assert Decimal(
                production_target["perpetual_base_quantity"]
            ) == reference_target["swap_quantity"]
            assert Decimal(production_target["dedicated_collateral"]) == reference_target[
                "collateral"
            ]
            assert Decimal(production_target["hedge_error"]) == reference_target[
                "hedge_error"
            ]


def test_reference_matches_candidate_and_always_on_on_frozen_window() -> None:
    payload = config()
    window = payload["windows"][0]
    start = datetime(2023, 6, 5, tzinfo=UTC)
    end = datetime(2024, 1, 1, tzinfo=UTC)
    primitive_market = market(start, end)
    primitive_funding = funding(start, end, "0.00012")
    primitive_metadata = metadata(start)
    for policy_id in (
        "C6AMarketNeutralFundingCarry",
        "AlwaysOnDeltaNeutralComparator",
    ):
        production = simulate_policy_window(
            primitive_market,
            primitive_funding,
            primitive_metadata,
            policy_id=policy_id,
            window=window,
            cost_label="1.0x",
            config=payload,
        )
        reference = recompute_window(
            primitive_market,
            primitive_funding,
            primitive_metadata,
            policy_id=policy_id,
            window=window,
            cost_label="1.0x",
            config=payload,
        )
        assert_equivalent(production, reference)
