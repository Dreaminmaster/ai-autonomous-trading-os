from __future__ import annotations

import math

from atos.c7a_independent import INSTRUMENTS, review_decision_evidence


def test_reviewer_matches_beta_rejection_and_detects_funding_sum_tamper() -> None:
    independent = [
        0.0002 * math.sin(index / 13) + 0.0001 * math.cos(index / 7)
        for index in range(672)
    ]
    dependent = [2.5 * value for value in independent]
    daily = {
        INSTRUMENTS[0]: [0.0004] * 28,
        INSTRUMENTS[1]: [0.00005] * 28,
    }
    sums = {instrument: sum(values) for instrument, values in daily.items()}
    decision = {
        "eligible": False,
        "reason": "BETA_OUT_OF_RANGE",
        "high_funding_instrument": INSTRUMENTS[0],
        "low_funding_instrument": INSTRUMENTS[1],
        "funding_sums_28d": sums,
        "beta": 2.5,
        "r_squared": 1.0,
        "long_weight": 0.0,
        "short_weight": 0.0,
        "projected_carry_28d": 0.0,
        "positive_daily_spreads": 0,
        "target_weights": {instrument: 0.0 for instrument in INSTRUMENTS},
    }
    evidence = {
        "decision": decision,
        "mark_returns": {
            INSTRUMENTS[0]: independent,
            INSTRUMENTS[1]: dependent,
        },
        "funding_daily_sums": daily,
        "execution_metadata": {
            "stage": "C7A",
            "source_kind": "SYNTHETIC",
            "contains_real_market_rows": False,
            "network_access": False,
            "economic_run": False,
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live_state": "LIVE_FORBIDDEN",
        },
    }
    assert review_decision_evidence(evidence)["status"] == "PASS"

    decision["funding_sums_28d"][INSTRUMENTS[0]] += 1.0
    review = review_decision_evidence(evidence)
    assert review["status"] == "FAIL"
    assert f"decision funding-sum mismatch: {INSTRUMENTS[0]}" in review["errors"]
