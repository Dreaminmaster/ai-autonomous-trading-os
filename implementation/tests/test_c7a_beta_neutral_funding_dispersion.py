from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from atos.c7a_contract import (
    C7AError,
    FIRST_SCORED_DECISION,
    INSTRUMENTS,
    aligned_mark_returns,
    assert_synthetic_only,
    funding_daily_sums,
    scored_decision_times,
    validate_config,
)
from atos.c7a_funding_dispersion import (
    apply_hourly_accounting,
    compute_decision,
    estimate_ols_beta,
    round_trip_cost_fraction,
    should_resize,
    target_turnover,
)
from atos.c7a_independent import review_decision_evidence


def config() -> dict:
    return json.loads(
        (
            Path(__file__).parents[1]
            / "config"
            / "c7a_beta_neutral_funding_dispersion.json"
        ).read_text()
    )


def mark_rows(*, beta_to_base: float = 1.0) -> dict[str, list[dict[str, object]]]:
    start = FIRST_SCORED_DECISION - timedelta(hours=673)
    base_returns = [
        0.0002 * math.sin(index / 13) + 0.0001 * math.cos(index / 7)
        for index in range(672)
    ]
    btc = [100.0]
    eth = [50.0]
    for value in base_returns:
        btc.append(btc[-1] * math.exp(value))
        eth.append(eth[-1] * math.exp(beta_to_base * value))
    times = [start + timedelta(hours=index) for index in range(673)]
    return {
        INSTRUMENTS[0]: [
            {"timestamp": time.isoformat(), "close": close}
            for time, close in zip(times, btc, strict=True)
        ],
        INSTRUMENTS[1]: [
            {"timestamp": time.isoformat(), "close": close}
            for time, close in zip(times, eth, strict=True)
        ],
    }


def funding_rows(
    *, btc_daily: float, eth_daily: float
) -> dict[str, list[dict[str, object]]]:
    start = FIRST_SCORED_DECISION - timedelta(days=28)
    output = {instrument: [] for instrument in INSTRUMENTS}
    for day in range(28):
        current = start + timedelta(days=day, hours=8)
        output[INSTRUMENTS[0]].append(
            {"funding_time": current.isoformat(), "realized_rate": btc_daily}
        )
        output[INSTRUMENTS[1]].append(
            {"funding_time": current.isoformat(), "realized_rate": eth_daily}
        )
    return output


def test_config_and_synthetic_boundary() -> None:
    validate_config(config())
    assert_synthetic_only(
        {
            "stage": "C7A",
            "source_kind": "SYNTHETIC",
            "contains_real_market_rows": False,
            "network_access": False,
            "economic_run": False,
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live_state": "LIVE_FORBIDDEN",
        }
    )
    with pytest.raises(C7AError, match="synthetic-only"):
        assert_synthetic_only(
            {
                "stage": "C7A",
                "source_kind": "OKX",
                "contains_real_market_rows": True,
                "network_access": True,
                "economic_run": False,
                "paper_state": "PAPER_CLOSED",
                "shadow_state": "SHADOW_CLOSED",
                "live_state": "LIVE_FORBIDDEN",
            }
        )


def test_exact_prospective_grid_and_673_close_alignment() -> None:
    decisions = scored_decision_times()
    assert len(decisions) == 26
    assert decisions[0] == datetime(2026, 8, 24, tzinfo=UTC)
    assert decisions[-1] == datetime(2027, 2, 15, tzinfo=UTC)
    rows = mark_rows()[INSTRUMENTS[0]]
    returns = aligned_mark_returns(
        rows, decision_time=FIRST_SCORED_DECISION, label="btc"
    )
    assert len(returns) == 672
    with pytest.raises(C7AError, match="673-close"):
        aligned_mark_returns(
            rows[1:], decision_time=FIRST_SCORED_DECISION, label="btc"
        )


def test_ols_beta_with_intercept() -> None:
    independent = [float(index) for index in range(1, 20)]
    dependent = [0.3 + 1.25 * value for value in independent]
    result = estimate_ols_beta(dependent, independent)
    assert result.alpha == pytest.approx(0.3)
    assert result.beta == pytest.approx(1.25)
    assert result.r_squared == pytest.approx(1.0)


def test_eligible_decision_is_beta_neutral_and_carry_positive() -> None:
    decision = compute_decision(
        decision_time=FIRST_SCORED_DECISION,
        mark_rows=mark_rows(beta_to_base=1.0),
        funding_rows=funding_rows(btc_daily=0.0004, eth_daily=0.00005),
    )
    assert decision.eligible is True
    assert decision.high_funding_instrument == INSTRUMENTS[0]
    assert decision.low_funding_instrument == INSTRUMENTS[1]
    assert decision.beta == pytest.approx(1.0)
    assert decision.r_squared == pytest.approx(1.0)
    assert decision.long_weight == pytest.approx(0.25)
    assert decision.short_weight == pytest.approx(0.25)
    assert sum(abs(value) for value in decision.target_weights.values()) == pytest.approx(
        0.5
    )
    assert decision.projected_carry_28d > 0.00225
    assert decision.positive_daily_spreads == 28


def test_low_carry_decision_holds_cash() -> None:
    decision = compute_decision(
        decision_time=FIRST_SCORED_DECISION,
        mark_rows=mark_rows(),
        funding_rows=funding_rows(btc_daily=0.00008, eth_daily=0.00005),
    )
    assert decision.eligible is False
    assert decision.reason == "PROJECTED_CARRY_BELOW_MINIMUM"
    assert decision.target_weights == {
        instrument: 0.0 for instrument in INSTRUMENTS
    }


def test_missing_funding_day_fails_closed() -> None:
    funding = funding_rows(btc_daily=0.0004, eth_daily=0.00005)
    funding[INSTRUMENTS[0]].pop(3)
    with pytest.raises(C7AError, match="missing daily funding"):
        compute_decision(
            decision_time=FIRST_SCORED_DECISION,
            mark_rows=mark_rows(),
            funding_rows=funding,
        )


def test_cost_turnover_and_hourly_accounting() -> None:
    current = {instrument: 0.0 for instrument in INSTRUMENTS}
    target = {INSTRUMENTS[0]: -0.25, INSTRUMENTS[1]: 0.25}
    assert target_turnover(current, target) == pytest.approx(0.5)
    assert should_resize(current, target) is True
    assert round_trip_cost_fraction() == pytest.approx(0.0015)

    result = apply_hourly_accounting(
        equity=1000.0,
        signed_weights=target,
        simple_mark_returns={
            INSTRUMENTS[0]: 0.01,
            INSTRUMENTS[1]: 0.01,
        },
        funding_rates={
            INSTRUMENTS[0]: 0.001,
            INSTRUMENTS[1]: 0.0001,
        },
        traded_turnover=0.5,
    )
    assert result["price_pnl"] == pytest.approx(0.0)
    assert result["funding_pnl"] == pytest.approx(0.225)
    assert result["trading_cost"] == pytest.approx(0.75)
    assert result["ending_equity"] == pytest.approx(999.475)


def test_physically_separate_review_detects_tamper() -> None:
    marks = mark_rows()
    funding = funding_rows(btc_daily=0.0004, eth_daily=0.00005)
    decision = compute_decision(
        decision_time=FIRST_SCORED_DECISION,
        mark_rows=marks,
        funding_rows=funding,
    )
    retained_returns = {
        instrument: list(
            aligned_mark_returns(
                marks[instrument],
                decision_time=FIRST_SCORED_DECISION,
                label=instrument,
            )
        )
        for instrument in INSTRUMENTS
    }
    retained_daily = {
        instrument: list(
            funding_daily_sums(
                funding[instrument],
                decision_time=FIRST_SCORED_DECISION,
                label=instrument,
            )[1]
        )
        for instrument in INSTRUMENTS
    }
    evidence = {
        "decision": decision.as_dict(),
        "mark_returns": retained_returns,
        "funding_daily_sums": retained_daily,
    }
    assert review_decision_evidence(evidence)["status"] == "PASS"
    evidence["decision"]["projected_carry_28d"] = 999.0
    review = review_decision_evidence(evidence)
    assert review["status"] == "FAIL"
    assert "decision mismatch: projected_carry_28d" in review["errors"]
