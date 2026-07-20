from atos.c4a_cross_sectional_runtime import solve_post_cost_equity
from scripts import c4a_evidence_postprocess
from scripts import c4a_finalizer_extensions
from scripts import run_c4a_finalization


def test_c4a_postprocess_modules_import() -> None:
    assert c4a_evidence_postprocess.RESULTS == c4a_finalizer_extensions.RESULTS
    assert callable(run_c4a_finalization.main)


def test_complete_rebalance_ledger_reconciles_entry_and_terminal_exit() -> None:
    pairs = ["BTC/USDT", "ETH/USDT"]
    entry = solve_post_cost_equity(
        equity_before=1000.0,
        current_values={pair: 0.0 for pair in pairs},
        target_weights={pair: 0.45 for pair in pairs},
        fee_rate=0.0015,
    )
    entry_prices = {"BTC/USDT": 100.0, "ETH/USDT": 50.0}
    quantities = {
        pair: entry["target_values"][pair] / entry_prices[pair]
        for pair in pairs
    }
    close_prices = {"BTC/USDT": 110.0, "ETH/USDT": 45.0}
    terminal_values = {
        pair: quantities[pair] * close_prices[pair]
        for pair in pairs
    }
    terminal_equity = entry["cash"] + sum(terminal_values.values())
    terminal = solve_post_cost_equity(
        equity_before=terminal_equity,
        current_values=terminal_values,
        target_weights={},
        fee_rate=0.0015,
    )
    start = "2024-01-01T00:00:00+00:00"
    end = "2024-03-31T20:00:00+00:00"
    policy_rows = [
        {
            "policy_id": "C4AWeeklyReturnTopTwo",
            "window_id": "S1",
            "cost_label": "1.0x",
            "fee_rate": 0.0015,
            "selected_pairs": pairs,
            "events": [
                {
                    "kind": "SCHEDULED_REBALANCE",
                    "time": start,
                    "target_weights": {pair: 0.45 for pair in pairs},
                    "equity_before": 1000.0,
                    "equity_after": entry["equity_after"],
                    "trade_deltas": entry["trade_deltas"],
                    "fees": entry["fees"],
                    "total_fee": entry["total_fee"],
                    "cash": entry["cash"],
                    "iterations": entry["iterations"],
                    "boundary_gap_pnl": 0.0,
                },
                {
                    "kind": "TERMINAL_LIQUIDATION",
                    "time": end,
                    "equity_before": terminal_equity,
                    "equity_after": terminal["equity_after"],
                    "fees": terminal["fees"],
                    "total_fee": terminal["total_fee"],
                },
            ],
        }
    ]
    market = {
        "BTC/USDT": {
            start: {"open": 100.0, "close": 100.0},
            end: {"open": 110.0, "close": 110.0},
        },
        "ETH/USDT": {
            start: {"open": 50.0, "close": 50.0},
            end: {"open": 45.0, "close": 45.0},
        },
    }
    ledger = c4a_evidence_postprocess.build_rebalance_ledger(policy_rows, market)
    assert len(ledger) == 2
    assert ledger[0]["solver_iterations"] == entry["iterations"]
    assert ledger[1]["kind"] == "TERMINAL_LIQUIDATION"
    assert all(value == 0.0 for value in ledger[1]["quantities_after"].values())
    assert abs(ledger[1]["equity_after"] - terminal["equity_after"]) < 1e-9
