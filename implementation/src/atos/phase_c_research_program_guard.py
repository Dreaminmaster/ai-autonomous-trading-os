"""Fail-closed Phase C research-history and C10A contract guard.

This module performs no network, account, order, Paper, Shadow, or Live work.
It validates the declared lower-bound trial history before C10A may access
historical market data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = ROOT / "implementation/config/phase_c_research_program_registry_v1.json"
C10A_CONFIG_PATH = ROOT / "implementation/config/c10a_cross_sectional_residual_momentum.json"

EXPECTED_REGISTRY_SHA256 = (
    "6f3499eabddc17e49527f9d47ef0cfae393ad47c3e398b95781db5981d4473a2"
)
EXPECTED_C10A_CONFIG_SHA256 = (
    "03843f32818240f8221203ce40379958b58da7aabf03686b42ca0d07a9eeeee1"
)

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
    "RawReturnMomentumComparator",
    "AlwaysLongSelectedUniverseComparator",
)


class PhaseCResearchProgramGuardError(RuntimeError):
    """Raised when program history or the frozen C10A contract drifts."""


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise PhaseCResearchProgramGuardError(
            f"unable to hash authority {path}: {exc}"
        ) from exc


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PhaseCResearchProgramGuardError(f"invalid JSON authority {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PhaseCResearchProgramGuardError(f"JSON authority must be an object: {path}")
    return payload


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise PhaseCResearchProgramGuardError(f"{label} must be decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PhaseCResearchProgramGuardError(f"{label} must be decimal") from exc
    if not parsed.is_finite():
        raise PhaseCResearchProgramGuardError(f"{label} must be finite")
    return parsed


def _window_tuples(value: object, label: str) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(value, list):
        raise PhaseCResearchProgramGuardError(f"{label} must be a list")
    rows: list[tuple[str, str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise PhaseCResearchProgramGuardError(f"{label} rows must be objects")
        row = (item.get("id"), item.get("start"), item.get("end"))
        if not all(isinstance(part, str) for part in row):
            raise PhaseCResearchProgramGuardError(f"{label} row fields must be strings")
        rows.append(row)  # type: ignore[arg-type]
    return tuple(rows)


def bonferroni_adjusted_psr(
    psr: Decimal | str | float,
    *,
    trial_count: int = EXPECTED_FAMILYWISE_TRIALS,
) -> Decimal:
    """Return the frozen lower-bound family-wise PSR adjustment."""

    probability = _decimal(psr, "psr")
    if probability < 0 or probability > 1:
        raise PhaseCResearchProgramGuardError("psr must be in [0, 1]")
    if trial_count != EXPECTED_FAMILYWISE_TRIALS:
        raise PhaseCResearchProgramGuardError("family-wise trial-count drift")
    adjusted = Decimal(1) - Decimal(trial_count) * (Decimal(1) - probability)
    return max(Decimal(0), adjusted)


def validate_registry(
    registry: Mapping[str, Any],
    *,
    authority_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Validate exact stage history and optionally hash its source authorities."""

    if registry.get("schema_version") != 1:
        raise PhaseCResearchProgramGuardError("program registry schema drift")
    if registry.get("program") != "PHASE_C_PROFITABILITY_RESEARCH":
        raise PhaseCResearchProgramGuardError("program registry identity drift")
    if registry.get("history_semantics") != "DECLARED_OBSERVED_TRIAL_LOWER_BOUND":
        raise PhaseCResearchProgramGuardError("program history semantics drift")
    if registry.get("untracked_human_discretion_fully_corrected") is not False:
        raise PhaseCResearchProgramGuardError("untracked discretion cannot claim correction")

    stages = registry.get("stages")
    if not isinstance(stages, list) or len(stages) != len(EXPECTED_STAGE_TRIALS):
        raise PhaseCResearchProgramGuardError("program stage inventory drift")
    observed: list[tuple[str, int, str]] = []
    authorities: list[dict[str, Any]] = []
    paths: set[str] = set()
    resolved_root = authority_root.resolve() if authority_root is not None else None

    for row in stages:
        if not isinstance(row, Mapping):
            raise PhaseCResearchProgramGuardError("program stage row must be an object")
        count = row.get("observed_economic_trials")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise PhaseCResearchProgramGuardError("observed trial count must be non-negative int")
        observed.append((row.get("stage"), count, row.get("result")))  # type: ignore[arg-type]

        relative = row.get("authority_path")
        markers = row.get("authority_markers")
        if not isinstance(relative, str) or relative in paths:
            raise PhaseCResearchProgramGuardError("authority path missing or duplicated")
        if not isinstance(markers, list) or not markers or not all(
            isinstance(marker, str) and marker for marker in markers
        ):
            raise PhaseCResearchProgramGuardError("authority markers missing")
        paths.add(relative)

        if resolved_root is not None:
            path = (resolved_root / relative).resolve()
            if not path.is_relative_to(resolved_root):
                raise PhaseCResearchProgramGuardError("authority path escapes repository root")
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise PhaseCResearchProgramGuardError(
                    f"unable to read program authority {relative}: {exc}"
                ) from exc
            missing = [marker for marker in markers if marker not in text]
            if missing:
                raise PhaseCResearchProgramGuardError(
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
        raise PhaseCResearchProgramGuardError("program stage trial/result history drift")
    total = sum(count for _, count, _ in observed)
    if total != EXPECTED_PRIOR_TRIALS:
        raise PhaseCResearchProgramGuardError("computed prior trial-count drift")
    if registry.get("prior_observed_economic_trial_count") != total:
        raise PhaseCResearchProgramGuardError("declared prior trial-count drift")
    if registry.get("prospective_stage") != "C10A":
        raise PhaseCResearchProgramGuardError("prospective stage drift")
    if registry.get("prospective_candidate_count") != 1:
        raise PhaseCResearchProgramGuardError("C10A candidate-count drift")
    if registry.get("familywise_trial_count") != EXPECTED_FAMILYWISE_TRIALS:
        raise PhaseCResearchProgramGuardError("family-wise trial-count drift")
    if registry.get("familywise_trial_count") != total + 1:
        raise PhaseCResearchProgramGuardError("family-wise count does not include C10A")
    if _decimal(registry.get("familywise_alpha"), "familywise alpha") != Decimal("0.05"):
        raise PhaseCResearchProgramGuardError("family-wise alpha drift")

    exposure = registry.get("exposed_economic_interval_union")
    if exposure != {
        "start_inclusive": "2023-07-03T00:00:00Z",
        "end_exclusive": "2026-06-29T00:00:00Z",
        "status": "HISTORICAL_DEVELOPMENT_ONLY",
    }:
        raise PhaseCResearchProgramGuardError("historical exposure registry drift")
    if _window_tuples(registry.get("c10a_windows"), "registry windows") != EXPECTED_WINDOWS:
        raise PhaseCResearchProgramGuardError("C10A registered-window drift")
    if registry.get("promotion_state") != "RESEARCH_ONLY":
        raise PhaseCResearchProgramGuardError("historical research cannot self-promote")
    if registry.get("paper_state") != "PAPER_CLOSED":
        raise PhaseCResearchProgramGuardError("Paper state drift")
    if registry.get("shadow_state") != "SHADOW_CLOSED":
        raise PhaseCResearchProgramGuardError("Shadow state drift")
    if registry.get("live_state") != "LIVE_FORBIDDEN":
        raise PhaseCResearchProgramGuardError("Live state drift")
    return authorities


def validate_c10a_config(
    config: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> None:
    """Validate the frozen C10A design against the program registry."""

    if config.get("schema_version") != 1 or config.get("stage") != "C10A":
        raise PhaseCResearchProgramGuardError("C10A config identity drift")
    if config.get("change_type") != "DESIGN_AND_PROGRAM_GUARD":
        raise PhaseCResearchProgramGuardError("C10A change type drift")
    if config.get("design_base_sha") != "7c799ea993787ff2d5298cc15450d1fac4e4e8b4":
        raise PhaseCResearchProgramGuardError("C10A design base drift")
    if tuple(config.get("candidate_pool", ())) != EXPECTED_CANDIDATE_POOL:
        raise PhaseCResearchProgramGuardError("C10A candidate-pool drift")
    if tuple(config.get("comparators", ())) != EXPECTED_COMPARATORS:
        raise PhaseCResearchProgramGuardError("C10A comparator drift")
    if config.get("candidate_id") != "C10ACrossSectionalResidualMomentum":
        raise PhaseCResearchProgramGuardError("C10A candidate identity drift")
    if config.get("selected_universe_size") != 8:
        raise PhaseCResearchProgramGuardError("C10A selected-universe drift")
    if config.get("formation_start") != "2023-07-03T00:00:00Z":
        raise PhaseCResearchProgramGuardError("C10A formation start drift")
    if config.get("formation_end_exclusive") != "2024-01-01T00:00:00Z":
        raise PhaseCResearchProgramGuardError("C10A formation end drift")
    if config.get("mark_warmup_start") != "2023-10-08T22:00:00Z":
        raise PhaseCResearchProgramGuardError("C10A mark warm-up drift")
    if config.get("scored_start") != EXPECTED_WINDOWS[0][1]:
        raise PhaseCResearchProgramGuardError("C10A scored start drift")
    if config.get("scored_end_exclusive") != EXPECTED_WINDOWS[-1][2]:
        raise PhaseCResearchProgramGuardError("C10A scored end drift")
    if _window_tuples(config.get("windows"), "config windows") != EXPECTED_WINDOWS:
        raise PhaseCResearchProgramGuardError("C10A config-window drift")
    if _window_tuples(registry.get("c10a_windows"), "registry windows") != EXPECTED_WINDOWS:
        raise PhaseCResearchProgramGuardError("C10A registry-window drift")

    fixed = {
        "timeframe": "1H",
        "decision_schedule": "MONDAY_00_UTC",
        "btc_beta_benchmark_instrument": "BTC-USDT-SWAP",
        "btc_beta_weekly_return_clock": (
            "ARITHMETIC_MARK_CLOSE_T_MINUS_1H_TO_NEXT_T_MINUS_1H"
        ),
        "signal_candle_lag_hours": 2,
        "beta_lookback_returns": 2016,
        "residual_score_returns": 672,
        "factor": "LEAVE_ONE_OUT_EQUAL_WEIGHT_LOG_RETURN",
        "score": "SUM_28D_OLS_RESIDUALS",
        "long_count": 2,
        "short_count": 2,
    }
    for key, expected in fixed.items():
        if config.get(key) != expected:
            raise PhaseCResearchProgramGuardError(f"C10A frozen field drift: {key}")

    gross = _decimal(config.get("gross_notional"), "gross notional")
    long_gross = _decimal(config.get("long_gross_notional"), "long gross")
    short_gross = _decimal(config.get("short_gross_notional"), "short gross")
    per_position = _decimal(config.get("per_position_abs_notional"), "position notional")
    if (gross, long_gross, short_gross, per_position) != (
        Decimal("0.50"),
        Decimal("0.25"),
        Decimal("0.25"),
        Decimal("0.125"),
    ):
        raise PhaseCResearchProgramGuardError("C10A portfolio weight drift")
    if long_gross + short_gross != gross:
        raise PhaseCResearchProgramGuardError("C10A gross-notional identity failure")
    if per_position * Decimal(2) != long_gross or per_position * Decimal(2) != short_gross:
        raise PhaseCResearchProgramGuardError("C10A per-position identity failure")

    if config.get("cost_rates") != {
        "1.0x": "0.0015",
        "1.5x": "0.00225",
        "2.0x": "0.0030",
    }:
        raise PhaseCResearchProgramGuardError("C10A cost schedule drift")
    gates = config.get("gates")
    if not isinstance(gates, Mapping):
        raise PhaseCResearchProgramGuardError("C10A gates missing")
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
        "minimum_return_delta_vs_raw_momentum_exclusive": "0",
        "minimum_sharpe_delta_vs_raw_momentum": "0.10",
        "require_drawdown_no_worse_than_raw_momentum": True,
        "require_turnover_no_greater_than_raw_momentum": True,
        "maximum_equity_buffer_breaches": 0,
        "required_decisions": 130,
        "required_nonflat_instrument_directions": 520,
    }
    if dict(gates) != expected_gates:
        raise PhaseCResearchProgramGuardError("C10A economic-gate drift")
    if gates["declared_program_familywise_trial_count"] != registry.get("familywise_trial_count"):
        raise PhaseCResearchProgramGuardError("C10A/program correction-count mismatch")

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
            raise PhaseCResearchProgramGuardError(f"C10A safety-state drift: {key}")


def verify_repository_authority(root: Path = ROOT) -> dict[str, Any]:
    """Load, hash, and validate the exact frozen repository authorities."""

    registry_path = root / REGISTRY_PATH.relative_to(ROOT)
    config_path = root / C10A_CONFIG_PATH.relative_to(ROOT)
    registry_sha = _sha256(registry_path)
    config_sha = _sha256(config_path)
    if registry_sha != EXPECTED_REGISTRY_SHA256:
        raise PhaseCResearchProgramGuardError("program registry file hash drift")
    if config_sha != EXPECTED_C10A_CONFIG_SHA256:
        raise PhaseCResearchProgramGuardError("C10A config file hash drift")
    registry = _load_object(registry_path)
    config = _load_object(config_path)
    authorities = validate_registry(registry, authority_root=root)
    validate_c10a_config(config, registry)
    return {
        "schema_version": 1,
        "stage": "C10A_PROGRAM_GUARD",
        "status": "PASS",
        "registry_sha256": registry_sha,
        "config_sha256": config_sha,
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
    "C10A_CONFIG_PATH",
    "EXPECTED_C10A_CONFIG_SHA256",
    "EXPECTED_FAMILYWISE_TRIALS",
    "EXPECTED_PRIOR_TRIALS",
    "EXPECTED_REGISTRY_SHA256",
    "REGISTRY_PATH",
    "PhaseCResearchProgramGuardError",
    "bonferroni_adjusted_psr",
    "validate_c10a_config",
    "validate_registry",
    "verify_repository_authority",
]
