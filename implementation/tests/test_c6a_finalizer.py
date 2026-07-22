from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import c6a_finalizer as finalizer
from scripts.c6a_reference_comparators import reference_cash_window

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def production_cash(reference: dict) -> dict:
    return {
        "policy_id": reference["policy_id"],
        "window_id": reference["window_id"],
        "cost_label": reference["cost_label"],
        "starting_equity": str(reference["starting_equity"]),
        "final_equity": str(reference["final_equity"]),
        "net_return": str(reference["net_return"]),
        "maximum_drawdown": str(reference["maximum_drawdown"]),
        "annualized_one_way_turnover": str(reference["annualized_one_way_turnover"]),
        "active_week_count": reference["active_week_count"],
        "active_funding_settlements": reference["active_funding_settlements"],
        "collateral_buffer_breaches": reference["collateral_buffer_breaches"],
        "hedge_breaches": reference["hedge_breaches"],
        "asset_contributions": {
            key: str(value) for key, value in reference["asset_contributions"].items()
        },
        "components": {
            key: str(value) for key, value in reference["components"].items()
        },
        "weekly_buckets": [
            {
                "weekly_pnl": str(row["pnl"]),
                "weekly_return": str(row["return"]),
                "active": row["active"],
                "risk_exit": row["risk_exit"],
                "reconciliation_residual": "0",
            }
            for row in reference["weekly"]
        ],
    }


def test_compare_cell_accepts_exact_cash_recomputation() -> None:
    payload = config()
    reference = reference_cash_window(
        window=payload["windows"][0], cost_label="1.0x", config=payload
    )
    report = finalizer.compare_cell(
        production_cash(reference), reference, label="CashComparator/1.0x/W1"
    )
    assert report == {
        "cell": "CashComparator/1.0x/W1",
        "status": "PASS",
        "weekly_rows": 26,
        "decision_rows": 0,
    }


def test_compare_cell_detects_economic_or_weekly_drift() -> None:
    payload = config()
    reference = reference_cash_window(
        window=payload["windows"][0], cost_label="1.0x", config=payload
    )
    production = production_cash(reference)
    production["final_equity"] = "1000.00000000001"
    with pytest.raises(finalizer.C6AFinalizerError, match="final_equity mismatch"):
        finalizer.compare_cell(production, reference, label="cash")

    production = production_cash(reference)
    production["weekly_buckets"][4]["weekly_pnl"] = "0.1"
    with pytest.raises(finalizer.C6AFinalizerError, match="week4.pnl mismatch"):
        finalizer.compare_cell(production, reference, label="cash")


def test_source_sha_is_exact_and_lowercase(monkeypatch) -> None:
    monkeypatch.delenv("C6A_SOURCE_SHA", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    with pytest.raises(finalizer.C6AFinalizerError, match="exact lowercase"):
        finalizer._exact_source_sha()
    monkeypatch.setenv("C6A_SOURCE_SHA", "f" * 40)
    assert finalizer._exact_source_sha() == "f" * 40
