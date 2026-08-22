"""Fail-closed Phase C history and C11A design authority guard.

This module performs no network, account, order, Paper, Shadow, or Live work.
It validates immutable local design authorities before C11A implementation or
historical-data access may be considered.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "implementation/config/phase_c_research_program_registry_v2.json"
C11A_CONFIG_PATH = (
    ROOT / "implementation/config/c11a_cross_sectional_idiosyncratic_volatility.json"
)
CONTRACT_PATH = (
    ROOT
    / "docs/architecture/phase-c/c11a-cross-sectional-idiosyncratic-volatility/"
    "C11A_CROSS_SECTIONAL_IDIOSYNCRATIC_VOLATILITY_CONTRACT_V1.md"
)

EXPECTED_REGISTRY_SHA256 = "02485320e066e5414978690ed0d5bce4984c7ff6ee0f224d5df8ade3ee423333"
EXPECTED_C11A_CONFIG_SHA256 = "7010b3edd71539ee017e47a45c4a5c9f8a1da0d3e0fce91b0269b768f30a6cc9"
EXPECTED_CONTRACT_SHA256 = "7c3e464f9cb7d0fde0d5e23e2d505993d9e8a13f8122438391db089593463f6d"
EXPECTED_DESIGN_BASE_SHA = "4fea1df7e7def3323199c278555f5b9308da50a9"

EXPECTED_STAGE_TRIALS = (
    ("C0B", 9, "NO_SURVIVOR"),
    ("C0C", 600, "REJECTED"),
    ("C1A", 3, "REJECTED"),
    ("C2A", 3, "REJECTED"),
    ("C3A", 3, "REJECTED"),
    ("C4A", 3, "REJECTED"),
    ("C5A", 2, "REJECTED"),
    ("C6A", 0, "DATA_AUTHORITY_FAILURE_ECONOMICS_NOT_RUN"),
    ("C7A", 1, "ECONOMIC_FAIL"),
    ("C8A", 1, "ECONOMIC_FAIL"),
    ("C9A", 1, "ECONOMIC_FAIL"),
    ("C10A", 0, "PROGRAM_FAILURE_ECONOMICS_NOT_RUN"),
)
EXPECTED_PRIOR_TRIALS = 626
EXPECTED_FAMILYWISE_TRIALS = 627

EXPECTED_WINDOWS = (
    ("H1", "2024-01-01T00:00:00Z", "2024-07-01T00:00:00Z"),
    ("H2", "2024-07-01T00:00:00Z", "2024-12-30T00:00:00Z"),
    ("H3", "2024-12-30T00:00:00Z", "2025-06-30T00:00:00Z"),
    ("H4", "2025-06-30T00:00:00Z", "2025-12-29T00:00:00Z"),
    ("H5", "2025-12-29T00:00:00Z", "2026-06-29T00:00:00Z"),
)
EXPECTED_CANDIDATE_POOL = (
    "ADA-USDT-SWAP",
    "AVAX-USDT-SWAP",
    "BCH-USDT-SWAP",
    "BTC-USDT-SWAP",
    "DOGE-USDT-SWAP",
    "DOT-USDT-SWAP",
    "ETH-USDT-SWAP",
    "LINK-USDT-SWAP",
    "LTC-USDT-SWAP",
    "SOL-USDT-SWAP",
    "TRX-USDT-SWAP",
    "XRP-USDT-SWAP",
)
EXPECTED_COMPARATORS = (
    "CashComparator",
    "TotalVolatilityComparator",
    "AlwaysLongSelectedUniverseComparator",
)


class C11AResearchProgramGuardError(RuntimeError):
    """Raised when C11A history, design, or safety authority drifts."""


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C11AResearchProgramGuardError(f"unable to hash authority {path}: {exc}") from exc


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C11AResearchProgramGuardError(f"invalid JSON authority {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise C11AResearchProgramGuardError(f"JSON authority must be an object: {path}")
    return payload


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise C11AResearchProgramGuardError(f"{label} must be decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise C11AResearchProgramGuardError(f"{label} must be decimal") from exc
    if not parsed.is_finite():
        raise C11AResearchProgramGuardError(f"{label} must be finite")
    return parsed


def _window_tuples(value: object, label: str) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(value, list):
        raise C11AResearchProgramGuardError(f"{label} must be a list")
    rows: list[tuple[str, str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise C11AResearchProgramGuardError(f"{label} rows must be objects")
        row = (item.get("id"), item.get("start"), item.get("end"))
        if not all(isinstance(part, str) for part in row):
            raise C11AResearchProgramGuardError(f"{label} row fields must be strings")
        rows.append(row)  # type: ignore[arg-type]
    return tuple(rows)


def bonferroni_adjusted_psr(
    psr: Decimal | str | float,
    *,
    trial_count: int = EXPECTED_FAMILYWISE_TRIALS,
) -> Decimal:
    """Return the exact frozen lower-bound family-wise PSR adjustment."""

    probability = _decimal(psr, "psr")
    if probability < 0 or probability > 1:
        raise C11AResearchProgramGuardError("psr must be in [0, 1]")
    if trial_count != EXPECTED_FAMILYWISE_TRIALS:
        raise C11AResearchProgramGuardError("family-wise trial-count drift")
    return max(Decimal(0), Decimal(1) - Decimal(trial_count) * (Decimal(1) - probability))


def validate_registry(
    registry: Mapping[str, Any],
    *,
    authority_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Validate exact prior-stage history and optionally hash its authorities."""

    if registry.get("schema_version") != 2:
        raise C11AResearchProgramGuardError("program registry schema drift")
    if registry.get("program") != "PHASE_C_PROFITABILITY_RESEARCH":
        raise C11AResearchProgramGuardError("program registry identity drift")
    if registry.get("history_semantics") != "DECLARED_OBSERVED_TRIAL_LOWER_BOUND":
        raise C11AResearchProgramGuardError("program history semantics drift")
    if registry.get("untracked_human_discretion_fully_corrected") is not False:
        raise C11AResearchProgramGuardError("untracked discretion cannot claim correction")

    stages = registry.get("stages")
    if not isinstance(stages, list) or len(stages) != len(EXPECTED_STAGE_TRIALS):
        raise C11AResearchProgramGuardError("program stage inventory drift")
    observed: list[tuple[str, int, str]] = []
    authorities: list[dict[str, Any]] = []
    paths: set[str] = set()
    resolved_root = authority_root.resolve() if authority_root is not None else None
    for row in stages:
        if not isinstance(row, Mapping):
            raise C11AResearchProgramGuardError("program stage row must be an object")
        count = row.get("observed_economic_trials")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise C11AResearchProgramGuardError("observed trial count must be non-negative int")
        observed.append((row.get("stage"), count, row.get("result")))  # type: ignore[arg-type]
        relative = row.get("authority_path")
        markers = row.get("authority_markers")
        if not isinstance(relative, str) or relative in paths:
            raise C11AResearchProgramGuardError("authority path missing or duplicated")
        if not isinstance(markers, list) or not markers or not all(
            isinstance(marker, str) and marker for marker in markers
        ):
            raise C11AResearchProgramGuardError("authority markers missing")
        paths.add(relative)
        if resolved_root is not None:
            path = (resolved_root / relative).resolve()
            if not path.is_relative_to(resolved_root):
                raise C11AResearchProgramGuardError("authority path escapes repository root")
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise C11AResearchProgramGuardError(
                    f"unable to read program authority {relative}: {exc}"
                ) from exc
            missing = [marker for marker in markers if marker not in text]
            if missing:
                raise C11AResearchProgramGuardError(
                    f"program authority marker mismatch for {relative}: {missing}"
                )
            authorities.append(
                {
                    "stage": row["stage"],
                    "path": relative,
                    "sha256": _sha256(path),
                    "marker_count": len(markers),
                    "status": "PASS",
                }
            )

    if tuple(observed) != EXPECTED_STAGE_TRIALS:
        raise C11AResearchProgramGuardError("program stage trial/result history drift")
    total = sum(count for _, count, _ in observed)
    if total != EXPECTED_PRIOR_TRIALS:
        raise C11AResearchProgramGuardError("computed prior trial-count drift")
    if registry.get("prior_observed_economic_trial_count") != total:
        raise C11AResearchProgramGuardError("declared prior trial-count drift")
    if registry.get("prospective_stage") != "C11A":
        raise C11AResearchProgramGuardError("prospective stage drift")
    if registry.get("prospective_candidate_count") != 1:
        raise C11AResearchProgramGuardError("C11A candidate-count drift")
    if registry.get("familywise_trial_count") != EXPECTED_FAMILYWISE_TRIALS:
        raise C11AResearchProgramGuardError("family-wise trial-count drift")
    if registry.get("familywise_trial_count") != total + 1:
        raise C11AResearchProgramGuardError("family-wise count does not include C11A")
    if _decimal(registry.get("familywise_alpha"), "familywise alpha") != Decimal("0.05"):
        raise C11AResearchProgramGuardError("family-wise alpha drift")
    if registry.get("exposed_economic_interval_union") != {
        "start_inclusive": "2023-07-03T00:00:00Z",
        "end_exclusive": "2026-06-29T00:00:00Z",
        "status": "HISTORICAL_DEVELOPMENT_ONLY",
    }:
        raise C11AResearchProgramGuardError("historical exposure registry drift")
    if _window_tuples(registry.get("c11a_windows"), "registry windows") != EXPECTED_WINDOWS:
        raise C11AResearchProgramGuardError("C11A registered-window drift")
    if registry.get("promotion_state") != "RESEARCH_ONLY":
        raise C11AResearchProgramGuardError("historical research cannot self-promote")
    if registry.get("paper_state") != "PAPER_CLOSED":
        raise C11AResearchProgramGuardError("Paper state drift")
    if registry.get("shadow_state") != "SHADOW_CLOSED":
        raise C11AResearchProgramGuardError("Shadow state drift")
    if registry.get("live_state") != "LIVE_FORBIDDEN":
        raise C11AResearchProgramGuardError("Live state drift")
    return authorities


def validate_c11a_config(config: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    """Validate every frozen C11A design and safety field."""

    if config.get("schema_version") != 1 or config.get("stage") != "C11A":
        raise C11AResearchProgramGuardError("C11A config identity drift")
    if config.get("change_type") != "DESIGN_AND_PROGRAM_GUARD":
        raise C11AResearchProgramGuardError("C11A change type drift")
    if config.get("design_base_sha") != EXPECTED_DESIGN_BASE_SHA:
        raise C11AResearchProgramGuardError("C11A design base drift")
    if config.get("contract_path") != str(CONTRACT_PATH.relative_to(ROOT)):
        raise C11AResearchProgramGuardError("C11A contract path drift")
    if config.get("program_registry_path") != str(REGISTRY_PATH.relative_to(ROOT)):
        raise C11AResearchProgramGuardError("C11A registry path drift")
    if config.get("candidate_id") != "C11ACrossSectionalIdiosyncraticVolatility":
        raise C11AResearchProgramGuardError("C11A candidate identity drift")
    if tuple(config.get("candidate_pool", ())) != EXPECTED_CANDIDATE_POOL:
        raise C11AResearchProgramGuardError("C11A candidate-pool drift")
    if tuple(config.get("comparators", ())) != EXPECTED_COMPARATORS:
        raise C11AResearchProgramGuardError("C11A comparator drift")
    if config.get("selected_universe_size") != 8:
        raise C11AResearchProgramGuardError("C11A selected-universe drift")
    if config.get("formation_start") != "2023-07-03T00:00:00Z":
        raise C11AResearchProgramGuardError("C11A formation start drift")
    if config.get("formation_end_exclusive") != "2024-01-01T00:00:00Z":
        raise C11AResearchProgramGuardError("C11A formation end drift")
    if config.get("mark_warmup_start") != "2023-12-03T22:00:00Z":
        raise C11AResearchProgramGuardError("C11A mark warm-up drift")
    if config.get("scored_start") != EXPECTED_WINDOWS[0][1]:
        raise C11AResearchProgramGuardError("C11A scored start drift")
    if config.get("scored_end_exclusive") != EXPECTED_WINDOWS[-1][2]:
        raise C11AResearchProgramGuardError("C11A scored end drift")
    if _window_tuples(config.get("windows"), "config windows") != EXPECTED_WINDOWS:
        raise C11AResearchProgramGuardError("C11A config-window drift")
    if _window_tuples(registry.get("c11a_windows"), "registry windows") != EXPECTED_WINDOWS:
        raise C11AResearchProgramGuardError("C11A registry-window drift")

    fixed: dict[str, object] = {
        "timeframe": "1H",
        "decision_schedule": "MONDAY_00_UTC",
        "btc_beta_benchmark_instrument": "BTC-USDT-SWAP",
        "btc_beta_weekly_return_clock": (
            "ARITHMETIC_MARK_CLOSE_T_MINUS_1H_TO_NEXT_T_MINUS_1H"
        ),
        "signal_candle_lag_hours": 2,
        "regression_lookback_returns": 672,
        "factor": "LEAVE_ONE_OUT_EQUAL_WEIGHT_LOG_RETURN",
        "score": "SAMPLE_STANDARD_DEVIATION_28D_OLS_RESIDUALS_DDOF_1",
        "rank_direction": "LONG_HIGH_SHORT_LOW",
        "long_count": 2,
        "short_count": 2,
    }
    for key, expected in fixed.items():
        if config.get(key) != expected:
            raise C11AResearchProgramGuardError(f"C11A frozen field drift: {key}")

    values = (
        _decimal(config.get("gross_notional"), "gross notional"),
        _decimal(config.get("long_gross_notional"), "long gross"),
        _decimal(config.get("short_gross_notional"), "short gross"),
        _decimal(config.get("per_position_abs_notional"), "position notional"),
        _decimal(config.get("starting_equity"), "starting equity"),
        _decimal(config.get("minimum_equity_to_gross_notional"), "equity buffer"),
        _decimal(config.get("reconciliation_tolerance"), "reconciliation tolerance"),
    )
    if values != (
        Decimal("0.50"),
        Decimal("0.25"),
        Decimal("0.25"),
        Decimal("0.125"),
        Decimal(1000),
        Decimal("1.25"),
        Decimal("1e-10"),
    ):
        raise C11AResearchProgramGuardError("C11A portfolio/accounting drift")
    if config.get("cost_rates") != {
        "1.0x": "0.0015",
        "1.5x": "0.00225",
        "2.0x": "0.0030",
    }:
        raise C11AResearchProgramGuardError("C11A cost schedule drift")

    gates = config.get("gates")
    expected_gates: dict[str, object] = {
        "minimum_positive_windows": 5,
        "minimum_aggregate_return_1_0x_exclusive": "0",
        "minimum_aggregate_return_1_5x_exclusive": "0",
        "minimum_aggregate_return_2_0x": "0",
        "minimum_annualized_weekly_sharpe": "1.00",
        "minimum_weekly_psr": "0.95",
        "declared_program_familywise_trial_count": EXPECTED_FAMILYWISE_TRIALS,
        "minimum_bonferroni_adjusted_psr": "0.95",
        "maximum_window_drawdown": "0.15",
        "maximum_abs_btc_beta": "0.20",
        "maximum_annualized_one_way_turnover": "18.0",
        "minimum_positive_instrument_contributions": 6,
        "maximum_positive_instrument_pnl_share": "0.35",
        "maximum_positive_window_pnl_share": "0.40",
        "maximum_positive_week_pnl_share": "0.15",
        "maximum_top_three_positive_week_pnl_share": "0.35",
        "minimum_return_delta_vs_total_volatility_exclusive": "0",
        "minimum_sharpe_delta_vs_total_volatility": "0.10",
        "require_drawdown_no_worse_than_total_volatility": True,
        "require_turnover_no_greater_than_total_volatility": True,
        "maximum_equity_buffer_breaches": 0,
        "required_decisions": 130,
        "required_nonflat_instrument_directions": 520,
    }
    if not isinstance(gates, Mapping) or dict(gates) != expected_gates:
        raise C11AResearchProgramGuardError("C11A economic-gate drift")
    if gates["declared_program_familywise_trial_count"] != registry.get(
        "familywise_trial_count"
    ):
        raise C11AResearchProgramGuardError("C11A/program correction-count mismatch")

    safety = {
        "historical_data_status": "HISTORICAL_DEVELOPMENT_ONLY",
        "execution_feasibility_established": False,
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    for key, expected in safety.items():
        if config.get(key) != expected:
            raise C11AResearchProgramGuardError(f"C11A safety-state drift: {key}")


def verify_repository_authority(root: Path = ROOT) -> dict[str, Any]:
    """Hash and validate the exact frozen C11A repository authorities."""

    registry_path = root / REGISTRY_PATH.relative_to(ROOT)
    config_path = root / C11A_CONFIG_PATH.relative_to(ROOT)
    contract_path = root / CONTRACT_PATH.relative_to(ROOT)
    registry_sha = _sha256(registry_path)
    config_sha = _sha256(config_path)
    contract_sha = _sha256(contract_path)
    if registry_sha != EXPECTED_REGISTRY_SHA256:
        raise C11AResearchProgramGuardError("program registry file hash drift")
    if config_sha != EXPECTED_C11A_CONFIG_SHA256:
        raise C11AResearchProgramGuardError("C11A config file hash drift")
    if contract_sha != EXPECTED_CONTRACT_SHA256:
        raise C11AResearchProgramGuardError("C11A contract file hash drift")
    registry = _load_object(registry_path)
    config = _load_object(config_path)
    authorities = validate_registry(registry, authority_root=root)
    validate_c11a_config(config, registry)
    contract = contract_path.read_text(encoding="utf-8")
    required_contract_markers = (
        "Historical economic result: `NOT_RUN`",
        "C11A is prospective economic trial `627`",
        "`C11A_DESIGN_FROZEN`",
        "`HISTORICAL_DEVELOPMENT_ONLY`",
        "`PAPER_CLOSED`",
        "`SHADOW_CLOSED`",
        "`LIVE_FORBIDDEN`",
    )
    if any(marker not in contract for marker in required_contract_markers):
        raise C11AResearchProgramGuardError("C11A contract marker drift")
    return {
        "schema_version": 1,
        "stage": "C11A_PROGRAM_GUARD",
        "status": "PASS",
        "registry_sha256": registry_sha,
        "config_sha256": config_sha,
        "contract_sha256": contract_sha,
        "prior_observed_economic_trial_count": EXPECTED_PRIOR_TRIALS,
        "prospective_candidate_count": 1,
        "familywise_trial_count": EXPECTED_FAMILYWISE_TRIALS,
        "authority_count": len(authorities),
        "authorities": authorities,
        "historical_data_status": "HISTORICAL_DEVELOPMENT_ONLY",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }


__all__ = [
    "C11A_CONFIG_PATH",
    "CONTRACT_PATH",
    "EXPECTED_C11A_CONFIG_SHA256",
    "EXPECTED_CONTRACT_SHA256",
    "EXPECTED_DESIGN_BASE_SHA",
    "EXPECTED_FAMILYWISE_TRIALS",
    "EXPECTED_PRIOR_TRIALS",
    "EXPECTED_REGISTRY_SHA256",
    "REGISTRY_PATH",
    "ROOT",
    "C11AResearchProgramGuardError",
    "bonferroni_adjusted_psr",
    "validate_c11a_config",
    "validate_registry",
    "verify_repository_authority",
]
