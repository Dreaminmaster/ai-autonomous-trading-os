from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from atos.c3a_residual_reversion import prepare_market, run_screen
import scripts.c3a_reference_recompute as reference
import scripts.finalize_c3a_evidence as finalizer


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "implementation/config/c3a_residual_mean_reversion.json"


def synthetic_candles() -> dict[str, list[dict]]:
    dates = pd.date_range(
        "2023-09-01T00:00:00Z",
        "2024-09-30T20:00:00Z",
        freq="4h",
        tz="UTC",
    )
    pairs = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    prices = {"BTC/USDT": 100.0, "ETH/USDT": 80.0, "SOL/USDT": 40.0}
    result = {pair: [] for pair in pairs}
    for index, timestamp in enumerate(dates):
        btc_return = 0.0002 + 0.0017 * math.sin(index / 11.0)
        values = {
            "BTC/USDT": btc_return,
            "ETH/USDT": 1.08 * btc_return + 0.0014 * math.sin(index / 5.0),
            "SOL/USDT": 1.35 * btc_return + 0.0020 * math.cos(index / 8.0),
        }
        if timestamp in {
            pd.Timestamp("2024-01-10T00:00:00Z"),
            pd.Timestamp("2024-04-12T08:00:00Z"),
            pd.Timestamp("2024-07-15T16:00:00Z"),
        }:
            values["ETH/USDT"] -= 0.14
        if timestamp in {
            pd.Timestamp("2024-02-14T12:00:00Z"),
            pd.Timestamp("2024-05-20T04:00:00Z"),
            pd.Timestamp("2024-08-18T20:00:00Z"),
        }:
            values["SOL/USDT"] -= 0.18
        for pair in pairs:
            open_price = prices[pair]
            close_price = open_price * math.exp(values[pair])
            result[pair].append({
                "date": timestamp.isoformat(),
                "open": open_price,
                "high": max(open_price, close_price) * 1.001,
                "low": min(open_price, close_price) * 0.999,
                "close": close_price,
                "volume": 1000.0 + index,
            })
            prices[pair] = close_price
    return result


def test_independent_reference_matches_complete_authoritative_screen() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    candles = synthetic_candles()
    authoritative = run_screen(prepare_market(candles), config)
    independent = reference.reference_run_screen(reference.reference_prepare_market(candles), config)
    checks: list[str] = []
    finalizer.require_equal("complete_screen", authoritative, independent, checks)
    assert checks == ["complete_screen:INDEPENDENT_MATCH"]
