from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from atos.phase_c_research_program_guard import (
    C10A_CONFIG_PATH,
    EXPECTED_FAMILYWISE_TRIALS,
    EXPECTED_PRIOR_TRIALS,
    REGISTRY_PATH,
    ROOT,
    PhaseCResearchProgramGuardError,
    bonferroni_adjusted_psr,
    validate_c10a_config,
    validate_registry,
    verify_repository_authority,
)


def _object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _authorities(root: Path, registry: dict[str, object]) -> None:
    stages = registry["stages"]
    assert isinstance(stages, list)
    for row in stages:
        assert isinstance(row, dict)
        path = root / str(row["authority_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        markers = row["authority_markers"]
        assert isinstance(markers, list)
        path.write_text("\n".join(str(marker) for marker in markers), encoding="utf-8")


def test_repository_program_history_and_c10a_design_are_frozen() -> None:
    report = verify_repository_authority()
    assert report["status"] == "PASS"
    assert report["prior_observed_economic_trial_count"] == EXPECTED_PRIOR_TRIALS
    assert report["prospective_candidate_count"] == 1
    assert report["familywise_trial_count"] == EXPECTED_FAMILYWISE_TRIALS
    assert report["authority_count"] == 11
    assert report["historical_data_status"] == "HISTORICAL_DEVELOPMENT_ONLY"
    assert report["paper_state"] == "PAPER_CLOSED"
    assert report["shadow_state"] == "SHADOW_CLOSED"
    assert report["live_state"] == "LIVE_FORBIDDEN"


def test_program_trial_count_includes_every_declared_observation() -> None:
    registry = _object(REGISTRY_PATH)
    stages = registry["stages"]
    assert isinstance(stages, list)
    counts = {
        str(row["stage"]): int(row["observed_economic_trials"])
        for row in stages
        if isinstance(row, dict)
    }
    assert counts == {
        "C0B": 9,
        "C0C": 600,
        "C1A": 3,
        "C2A": 3,
        "C3A": 3,
        "C4A": 3,
        "C5A": 2,
        "C6A": 0,
        "C7A": 1,
        "C8A": 1,
        "C9A": 1,
    }
    assert sum(counts.values()) == 626
    assert registry["familywise_trial_count"] == 627


def test_bonferroni_probability_boundary_is_exact_and_fail_closed() -> None:
    required_raw_psr = Decimal(1) - Decimal("0.05") / Decimal(627)
    assert bonferroni_adjusted_psr(required_raw_psr) >= Decimal("0.95")
    assert bonferroni_adjusted_psr(required_raw_psr) - Decimal("0.95") < Decimal("1e-25")
    assert bonferroni_adjusted_psr(Decimal("0.95")) == Decimal(0)
    with pytest.raises(PhaseCResearchProgramGuardError, match="trial-count drift"):
        bonferroni_adjusted_psr(required_raw_psr, trial_count=626)
    with pytest.raises(PhaseCResearchProgramGuardError, match=r"\[0, 1\]"):
        bonferroni_adjusted_psr(Decimal("1.01"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload["stages"].pop(), "stage inventory"),
        (
            lambda payload: payload["stages"][1].update(
                {"observed_economic_trials": 599}
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
            lambda payload: payload.update({"familywise_trial_count": 626}),
            "family-wise trial-count",
        ),
        (
            lambda payload: payload.update({"promotion_state": "SHADOW_READY"}),
            "cannot self-promote",
        ),
    ],
)
def test_registry_rejects_history_removal_or_promotion(
    mutation: object, message: str
) -> None:
    registry = copy.deepcopy(_object(REGISTRY_PATH))
    assert callable(mutation)
    mutation(registry)
    with pytest.raises(PhaseCResearchProgramGuardError, match=message):
        validate_registry(registry)


def test_registry_hashes_exact_authority_markers_and_rejects_tamper(
    tmp_path: Path,
) -> None:
    registry = _object(REGISTRY_PATH)
    _authorities(tmp_path, registry)
    authorities = validate_registry(registry, authority_root=tmp_path)
    assert len(authorities) == 11
    first = authorities[0]
    assert first["stage"] == "C0B"
    assert len(str(first["sha256"])) == 64

    stages = registry["stages"]
    assert isinstance(stages, list) and isinstance(stages[0], dict)
    path = tmp_path / str(stages[0]["authority_path"])
    path.write_text("NO LONGER AUTHORITATIVE", encoding="utf-8")
    with pytest.raises(PhaseCResearchProgramGuardError, match="marker mismatch"):
        validate_registry(registry, authority_root=tmp_path)


def test_registry_rejects_authority_path_escape(tmp_path: Path) -> None:
    registry = copy.deepcopy(_object(REGISTRY_PATH))
    stages = registry["stages"]
    assert isinstance(stages, list) and isinstance(stages[0], dict)
    stages[0]["authority_path"] = "../escape.md"
    with pytest.raises(PhaseCResearchProgramGuardError, match="escapes"):
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
            lambda payload: payload["windows"][0].update(
                {"start": "2024-01-08T00:00:00Z"}
            ),
            "config-window drift",
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
        (
            lambda payload: payload.update(
                {"btc_beta_benchmark_instrument": "ETH-USDT-SWAP"}
            ),
            "frozen field drift",
        ),
    ],
)
def test_c10a_config_rejects_comparator_window_gate_or_safety_drift(
    mutation: object, message: str
) -> None:
    config = copy.deepcopy(_object(C10A_CONFIG_PATH))
    registry = _object(REGISTRY_PATH)
    assert callable(mutation)
    mutation(config)
    with pytest.raises(PhaseCResearchProgramGuardError, match=message):
        validate_c10a_config(config, registry)


def test_c10a_contract_is_design_only_and_does_not_claim_profit() -> None:
    contract = (
        ROOT
        / "docs/architecture/phase-c/c10a-cross-sectional-residual-momentum/"
        "C10A_CROSS_SECTIONAL_RESIDUAL_MOMENTUM_CONTRACT_V1.md"
    ).read_text(encoding="utf-8")
    assert "Historical economic result: `NOT_RUN`" in contract
    assert "declared lower bound of `626` observed economic" in contract
    assert "C10A is prospective trial `627`" in contract
    assert "`HISTORICAL_DEVELOPMENT_ONLY`" in contract
    assert "`PAPER_CLOSED`" in contract
    assert "`SHADOW_CLOSED`" in contract
    assert "`LIVE_FORBIDDEN`" in contract
    assert "No relatively best ineligible result" in contract
    assert "`BTC-USDT-SWAP` benchmark mark candles are always retained" in contract
