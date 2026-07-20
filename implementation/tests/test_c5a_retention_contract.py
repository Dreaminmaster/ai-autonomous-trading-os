from __future__ import annotations

import pytest

from atos.c5a_derivatives_crowding import run_screen
from scripts import c5a_retention_evidence as retention
from test_c5a_derivatives_crowding import config, datasets


def _payload() -> tuple[dict, dict]:
    screen = run_screen(datasets(), config())
    payload = retention.build_payload(
        screen["policy_rows"],
        screen["policy_aggregates"],
        source_sha="1" * 40,
        merge_sha="2" * 40,
    )
    return screen, payload


def test_weekly_accounting_retains_all_normative_fields() -> None:
    _, payload = _payload()
    rows = payload["weekly_accounting"]
    assert payload["weekly_accounting_row_count"] == 156
    assert len(rows) == 156
    required = {
        "start_reference_equity",
        "monday_pre_trade_open_equity",
        "boundary_gap_pnl",
        "monday_fee",
        "monday_post_trade_equity",
        "final_sunday_post_close_equity",
        "net_pnl",
        "net_return",
    }
    for row in rows:
        assert required.issubset(row)
        assert row["monday_post_trade_equity"] == pytest.approx(
            row["monday_pre_trade_open_equity"] - row["monday_fee"], abs=1e-9
        )
        assert row["net_pnl"] == pytest.approx(
            row["final_sunday_post_close_equity"] - row["start_reference_equity"],
            abs=1e-9,
        )


def test_concentration_retains_numerators_denominators_and_exact_shares() -> None:
    screen, payload = _payload()
    rows = {
        (row["policy_id"], row["cost_label"]): row
        for row in payload["concentration"]
    }
    assert payload["concentration_row_count"] == 6
    for aggregate in screen["policy_aggregates"]:
        retained = rows[(aggregate["policy_id"], aggregate["cost_label"])]
        mapping = {
            "positive_half_pnl": "maximum_positive_half_pnl_share",
            "positive_asset_pnl": "maximum_positive_asset_pnl_share",
            "positive_single_week_pnl": "maximum_positive_week_pnl_share",
            "positive_top_three_week_pnl": "maximum_top_three_positive_week_pnl_share",
        }
        for retained_key, aggregate_key in mapping.items():
            detail = retained[retained_key]
            assert {"numerator", "denominator", "share"}.issubset(detail)
            assert detail["share"] == pytest.approx(aggregate[aggregate_key], abs=1e-12)


def test_incremental_differences_are_unrounded_and_claim_boundary_is_explicit() -> None:
    screen, payload = _payload()
    by_key = {
        (row["policy_id"], row["cost_label"]): row
        for row in screen["policy_aggregates"]
    }
    candidate = by_key[("C5ADerivativesCrowdingFilteredRiskBalance", "1.0x")]
    ablation = by_key[("C5APriceOnlyRiskBalanceAblation", "1.0x")]
    incremental = payload["incremental_information"]
    assert incremental["aggregate_sharpe_4h"]["candidate_minus_ablation"] == pytest.approx(
        candidate["aggregate_sharpe_4h"] - ablation["aggregate_sharpe_4h"], abs=1e-12
    )
    assert incremental["maximum_half_drawdown"]["candidate_minus_ablation"] == pytest.approx(
        candidate["maximum_half_drawdown"] - ablation["maximum_half_drawdown"], abs=1e-12
    )
    assert incremental["annualized_one_way_turnover"]["candidate_minus_ablation"] == pytest.approx(
        candidate["annualized_one_way_turnover"] - ablation["annualized_one_way_turnover"], abs=1e-12
    )
    assert payload["within_stage_dsr_used"] is False
    assert payload["weekly_statistic"] == "PSR_NOT_DSR"
    assert payload["program_level_sequential_history_corrected"] is False
