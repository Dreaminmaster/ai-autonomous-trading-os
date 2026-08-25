from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from atos.c12a_research_program_guard import (
    C12A_CONFIG_PATH,
    CONTRACT_PATH,
    EXPECTED_FAMILYWISE_TRIALS,
    EXPECTED_PRIOR_TRIALS,
    REGISTRY_PATH,
    C12AResearchProgramGuardError,
    bonferroni_adjusted_psr,
    validate_c12a_config,
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


def test_repository_history_and_c12a_design_are_frozen() -> None:
    report = verify_repository_authority()
    assert report["status"] == "PASS"
    assert report["prior_observed_economic_trial_count"] == EXPECTED_PRIOR_TRIALS
    assert report["familywise_trial_count"] == EXPECTED_FAMILYWISE_TRIALS
    assert report["prospective_candidate_count"] == 1
    assert report["authority_count"] == 13
    assert report["historical_data_status"] == "HISTORICAL_DEVELOPMENT_ONLY"
    assert report["paper_state"] == "PAPER_CLOSED"
    assert report["shadow_state"] == "SHADOW_CLOSED"
    assert report["live_state"] == "LIVE_FORBIDDEN"


def test_registry_records_c11a_as_one_closed_economic_trial() -> None:
    registry = _object(REGISTRY_PATH)
    stages = registry["stages"]
    assert isinstance(stages, list)
    counts = {
        str(row["stage"]): int(row["observed_economic_trials"])
        for row in stages
        if isinstance(row, dict)
    }
    results = {
        str(row["stage"]): str(row["result"]) for row in stages if isinstance(row, dict)
    }
    assert counts["C10A"] == 0
    assert counts["C11A"] == 1
    assert results["C11A"] == "ECONOMIC_FAIL"
    assert sum(counts.values()) == 627
    assert registry["prospective_stage"] == "C12A"
    assert registry["familywise_trial_count"] == 628


def test_bonferroni_boundary_is_exact_and_fail_closed() -> None:
    threshold = Decimal(1) - Decimal("0.05") / Decimal(628)
    assert bonferroni_adjusted_psr(threshold) >= Decimal("0.95")
    assert bonferroni_adjusted_psr(threshold) - Decimal("0.95") < Decimal("1e-25")
    assert bonferroni_adjusted_psr(Decimal("0.95")) == Decimal(0)
    with pytest.raises(C12AResearchProgramGuardError, match="trial-count drift"):
        bonferroni_adjusted_psr(threshold, trial_count=627)
    with pytest.raises(C12AResearchProgramGuardError, match=r"\[0, 1\]"):
        bonferroni_adjusted_psr(Decimal("1.01"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["stages"].pop(), "stage inventory"),
        (
            lambda payload: payload["stages"][-1].update(
                {"observed_economic_trials": 0}
            ),
            "trial/result history",
        ),
        (
            lambda payload: payload["stages"][-1].update({"result": "ECONOMIC_PASS"}),
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
    with pytest.raises(C12AResearchProgramGuardError, match=message):
        validate_registry(registry)


def test_registry_hashes_all_authorities_and_rejects_tamper(tmp_path: Path) -> None:
    registry = _object(REGISTRY_PATH)
    _write_authority_markers(tmp_path, registry)
    authorities = validate_registry(registry, authority_root=tmp_path)
    assert len(authorities) == 13
    assert authorities[-1]["stage"] == "C11A"
    assert len(str(authorities[-1]["sha256"])) == 64

    stages = registry["stages"]
    assert isinstance(stages, list) and isinstance(stages[-1], dict)
    path = tmp_path / str(stages[-1]["authority_path"])
    path.write_text("C11A RESULT REMOVED", encoding="utf-8")
    with pytest.raises(C12AResearchProgramGuardError, match="marker mismatch"):
        validate_registry(registry, authority_root=tmp_path)


def test_registry_rejects_authority_path_escape(tmp_path: Path) -> None:
    registry = copy.deepcopy(_object(REGISTRY_PATH))
    stages = registry["stages"]
    assert isinstance(stages, list) and isinstance(stages[0], dict)
    stages[0]["authority_path"] = "../escape.md"
    with pytest.raises(C12AResearchProgramGuardError, match="escapes"):
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
            lambda payload: payload.update({"signal_lead_days": 21}),
            "frozen field drift",
        ),
        (
            lambda payload: payload.update(
                {"basis_definition": "CONVENTIONAL_SPOT_NORMALIZED"}
            ),
            "frozen field drift",
        ),
        (
            lambda payload: payload["quarterly_contracts"][0].update(
                {"btc": "BTC-USDT-SWAP"}
            ),
            "quarterly-contract drift",
        ),
        (
            lambda payload: payload["windows"][0].update(
                {"start": "2024-01-08T00:00:00Z"}
            ),
            "config-window drift",
        ),
        (
            lambda payload: payload.update({"entry_basis_threshold": "0.0100"}),
            "portfolio/accounting drift",
        ),
        (
            lambda payload: payload.update({"sizing_cost_rate": "0.00225"}),
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
    config = copy.deepcopy(_object(C12A_CONFIG_PATH))
    registry = _object(REGISTRY_PATH)
    assert callable(mutation)
    mutation(config)
    with pytest.raises(C12AResearchProgramGuardError, match=message):
        validate_c12a_config(config, registry)


def test_c12a_is_structurally_distinct_from_prior_perpetual_carry() -> None:
    c12a = _object(C12A_CONFIG_PATH)
    c9a_path = C12A_CONFIG_PATH.with_name("c9a_continuous_notional_funding_carry.json")
    c9a = _object(c9a_path)
    assert c12a["candidate_id"] != c9a["candidate_id"]
    assert c12a["comparators"] != c9a["comparators"]
    assert c12a["futures_source"] == "OKX_OFFICIAL_MONTHLY_FUTURES_CHAIN_TRADES"
    assert "funding" not in str(c12a["entry_rule"]).lower()
    assert all("SWAP" not in row for row in c12a["quarterly_contracts"])


def test_contract_is_design_only_and_discloses_feasibility_probe() -> None:
    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    assert "Historical economic result: `NOT_RUN`" in contract
    assert "C12A is prospective economic trial `628`" in contract
    assert "Pre-design source-feasibility probe" in contract
    assert "No C12A entry basis, return, PnL, Sharpe, PSR, comparator" in contract
    assert "module=2" in contract and "`confirm=0`" in contract
    assert "No relatively best ineligible result" in contract
    assert "`HISTORICAL_DEVELOPMENT_ONLY`" in contract
    assert "`PAPER_CLOSED`" in contract
    assert "`SHADOW_CLOSED`" in contract
    assert "`LIVE_FORBIDDEN`" in contract
