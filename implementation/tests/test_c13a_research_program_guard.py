from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from atos.c13a_research_program_guard import (
    C13A_CONFIG_PATH,
    CONTRACT_PATH,
    EXPECTED_FAMILYWISE_TRIALS,
    EXPECTED_PRIOR_TRIALS,
    REGISTRY_PATH,
    C13AResearchProgramGuardError,
    bonferroni_adjusted_psr,
    validate_c13a_config,
    validate_registry,
    verify_repository_authority,
)


def _object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_authority_markers(root: Path, registry: dict[str, object]) -> None:
    stages = registry["stages"]
    assert isinstance(stages, list)
    for row in stages:
        assert isinstance(row, dict)
        path = root / str(row["authority_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        markers = row["authority_markers"]
        assert isinstance(markers, list)
        path.write_text("\n".join(str(marker) for marker in markers), encoding="utf-8")


def test_repository_history_and_c13a_design_are_frozen() -> None:
    report = verify_repository_authority()
    assert report["status"] == "PASS"
    assert report["prior_observed_economic_trial_count"] == EXPECTED_PRIOR_TRIALS
    assert report["familywise_trial_count"] == EXPECTED_FAMILYWISE_TRIALS
    assert report["prospective_candidate_count"] == 1
    assert report["authority_count"] == 14
    assert report["historical_data_status"] == "HISTORICAL_DEVELOPMENT_ONLY"
    assert report["paper_state"] == "PAPER_CLOSED"
    assert report["shadow_state"] == "SHADOW_CLOSED"
    assert report["live_state"] == "LIVE_FORBIDDEN"


def test_registry_records_c12a_as_zero_trial_data_failure() -> None:
    registry = _object(REGISTRY_PATH)
    stages = registry["stages"]
    assert isinstance(stages, list)
    counts = {
        str(row["stage"]): int(row["observed_economic_trials"])
        for row in stages
        if isinstance(row, dict)
    }
    results = {
        str(row["stage"]): str(row["result"])
        for row in stages
        if isinstance(row, dict)
    }
    assert counts["C10A"] == 0
    assert counts["C11A"] == 1
    assert counts["C12A"] == 0
    assert results["C12A"] == "DATA_FAILURE_ECONOMICS_NOT_RUN"
    assert sum(counts.values()) == 627
    assert registry["prospective_stage"] == "C13A"
    assert registry["familywise_trial_count"] == 628


def test_bonferroni_boundary_is_exact_and_fail_closed() -> None:
    threshold = Decimal(1) - Decimal("0.05") / Decimal(628)
    assert bonferroni_adjusted_psr(threshold) >= Decimal("0.95")
    assert bonferroni_adjusted_psr(threshold) - Decimal("0.95") < Decimal("1e-25")
    assert bonferroni_adjusted_psr(Decimal("0.95")) == Decimal(0)
    with pytest.raises(C13AResearchProgramGuardError, match="trial-count drift"):
        bonferroni_adjusted_psr(threshold, trial_count=627)
    with pytest.raises(C13AResearchProgramGuardError, match=r"\[0, 1\]"):
        bonferroni_adjusted_psr(Decimal("1.01"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["stages"].pop(), "stage inventory"),
        (
            lambda payload: payload["stages"][-1].update(
                {"observed_economic_trials": 1}
            ),
            "trial/result history",
        ),
        (
            lambda payload: payload["stages"][-1].update(
                {"result": "ECONOMIC_FAIL"}
            ),
            "trial/result history",
        ),
        (
            lambda payload: payload.update(
                {"untracked_human_discretion_fully_corrected": True}
            ),
            "untracked discretion",
        ),
        (
            lambda payload: payload.update({"familywise_trial_count": 627}),
            "family-wise trial-count",
        ),
        (
            lambda payload: payload.update({"promotion_state": "SHADOW_READY"}),
            "safety-state drift",
        ),
    ],
)
def test_registry_rejects_history_rewrite_or_promotion(
    mutation: object, message: str
) -> None:
    registry = copy.deepcopy(_object(REGISTRY_PATH))
    assert callable(mutation)
    mutation(registry)
    with pytest.raises(C13AResearchProgramGuardError, match=message):
        validate_registry(registry)


def test_registry_hashes_all_authorities_and_rejects_tamper(tmp_path: Path) -> None:
    registry = _object(REGISTRY_PATH)
    _write_authority_markers(tmp_path, registry)
    authorities = validate_registry(registry, authority_root=tmp_path)
    assert len(authorities) == 14
    assert authorities[-1]["stage"] == "C12A"
    assert len(str(authorities[-1]["sha256"])) == 64

    stages = registry["stages"]
    assert isinstance(stages, list) and isinstance(stages[-1], dict)
    path = tmp_path / str(stages[-1]["authority_path"])
    path.write_text("C12A RESULT REMOVED", encoding="utf-8")
    with pytest.raises(C13AResearchProgramGuardError, match="marker mismatch"):
        validate_registry(registry, authority_root=tmp_path)


def test_registry_rejects_authority_path_escape(tmp_path: Path) -> None:
    registry = copy.deepcopy(_object(REGISTRY_PATH))
    stages = registry["stages"]
    assert isinstance(stages, list) and isinstance(stages[0], dict)
    stages[0]["authority_path"] = "../escape.md"
    with pytest.raises(C13AResearchProgramGuardError, match="escapes"):
        validate_registry(registry, authority_root=tmp_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload["comparators"].__setitem__(
                1, "RenamedWinningComparator"
            ),
            "comparator drift",
        ),
        (
            lambda payload: payload.update({"signal_lookback_complete_days": 14}),
            "frozen field drift",
        ),
        (
            lambda payload: payload.update({"signal_execution_lag_hours": 1}),
            "frozen field drift",
        ),
        (
            lambda payload: payload.update(
                {"score": "SAMPLE_STANDARD_DEVIATION_7D"}
            ),
            "frozen field drift",
        ),
        (
            lambda payload: payload["instruments"].pop(),
            "instrument drift",
        ),
        (
            lambda payload: payload["windows"][0].update(
                {"start": "2024-01-08T00:00:00Z"}
            ),
            "config-window drift",
        ),
        (
            lambda payload: payload.update({"gross_notional": "1.00"}),
            "portfolio/accounting drift",
        ),
        (
            lambda payload: payload["gates"].update(
                {"declared_program_familywise_trial_count": 1}
            ),
            "economic-gate drift",
        ),
        (
            lambda payload: payload.update({"shadow_state": "SHADOW_OPEN"}),
            "safety-state drift",
        ),
        (
            lambda payload: payload.update({"authenticated": True}),
            "safety-state drift",
        ),
    ],
)
def test_config_rejects_signal_contract_gate_or_safety_drift(
    mutation: object, message: str
) -> None:
    config = copy.deepcopy(_object(C13A_CONFIG_PATH))
    registry = _object(REGISTRY_PATH)
    assert callable(mutation)
    mutation(config)
    with pytest.raises(C13AResearchProgramGuardError, match=message):
        validate_c13a_config(config, registry)


def test_c13a_is_not_a_renamed_c11a_volatility_or_c3a_reversal() -> None:
    c13a = _object(C13A_CONFIG_PATH)
    c11a = _object(
        C13A_CONFIG_PATH.with_name("c11a_cross_sectional_idiosyncratic_volatility.json")
    )
    assert c13a["candidate_id"] != c11a["candidate_id"]
    assert c13a["score"] != c11a["score"]
    assert c13a["signal_lookback_complete_days"] == 7
    assert "VOLATILITY" not in str(c13a["score"])
    assert "OLS" not in str(c13a["score"])
    assert "TotalVolatilityRankComparator" in c13a["comparators"]
    assert "RawSevenDayReversalComparator" in c13a["comparators"]


def test_contract_is_design_only_and_discloses_distinct_mechanism() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    assert "Historical economic result: `NOT_RUN`" in contract
    assert "C13A is prospective economic trial `628`" in contract
    assert "No C13A score, rank, trade, PnL, return, Sharpe, PSR, comparator" in contract
    assert "Lottery-Like Demand in Cryptocurrency Markets" in contract
    assert "Funding is an unavoidable realized cash flow, never a feature" in contract
    assert "There is one candidate and no relatively best fallback" in contract
    assert "`HISTORICAL_DEVELOPMENT_ONLY`" in contract
    assert "`PAPER_CLOSED`" in contract
    assert "`SHADOW_CLOSED`" in contract
    assert "`LIVE_FORBIDDEN`" in contract
