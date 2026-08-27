"""Fail-closed Phase C history and C14A design-authority guard.

This module performs no network, account, order, Paper, Shadow, or Live work.
It validates immutable local authorities before C14A implementation or
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
REGISTRY_PATH = ROOT / "implementation/config/phase_c_research_program_registry_v5.json"
C14A_CONFIG_PATH = ROOT / "implementation/config/c14a_cross_sectional_liquidity_risk.json"
CONTRACT_PATH = (
    ROOT / "docs/architecture/phase-c/c14a-cross-sectional-liquidity-risk/"
    "C14A_CROSS_SECTIONAL_LIQUIDITY_RISK_CONTRACT_V1.md"
)

EXPECTED_REGISTRY_SHA256 = "1fef3baae578524f2f00b76bdfcf26ba6b188ffb529dd6dd5c34b8c3029ac9a0"
EXPECTED_C14A_CONFIG_SHA256 = "489747d17a3367e1f4d56ba3844ab1dd0a6af548e48749cbd33bf4242a6c30f5"
EXPECTED_CONTRACT_SHA256 = "6e5f8fac55492721cb04f9bb8e18d18044d7f93343ee04e7fa1b5d46521a10f0"
EXPECTED_DESIGN_BASE_SHA = "9fad58a768517a63eedbe5a11a4cbad16e3dee7a"

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
    ("C11A", 1, "ECONOMIC_FAIL"),
    ("C12A", 0, "DATA_FAILURE_ECONOMICS_NOT_RUN"),
    ("C13A", 1, "ECONOMIC_FAIL"),
)
EXPECTED_PRIOR_TRIALS = 628
EXPECTED_FAMILYWISE_TRIALS = 629
EXPECTED_WINDOWS = (
    ("H1", "2024-01-01T00:00:00Z", "2024-07-01T00:00:00Z"),
    ("H2", "2024-07-01T00:00:00Z", "2024-12-30T00:00:00Z"),
    ("H3", "2024-12-30T00:00:00Z", "2025-06-30T00:00:00Z"),
    ("H4", "2025-06-30T00:00:00Z", "2025-12-29T00:00:00Z"),
    ("H5", "2025-12-29T00:00:00Z", "2026-06-29T00:00:00Z"),
)
EXPECTED_INSTRUMENTS = (
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "SOL-USDT-SWAP",
    "BCH-USDT-SWAP",
    "DOGE-USDT-SWAP",
    "XRP-USDT-SWAP",
    "LTC-USDT-SWAP",
    "LINK-USDT-SWAP",
)
EXPECTED_COMPARATORS = (
    "CashComparator",
    "MeanAbsoluteReturnRankComparator",
    "InverseQuoteVolumeRankComparator",
)


class C14AResearchProgramGuardError(RuntimeError):
    """Raised when C14A history, design, or safety authority drifts."""


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C14AResearchProgramGuardError(
            f"unable to hash authority {path}: {exc}"
        ) from exc


def _load_object(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise C14AResearchProgramGuardError(
                    f"duplicate JSON authority key {key!r}: {path}"
                )
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise C14AResearchProgramGuardError(
            f"invalid JSON authority {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise C14AResearchProgramGuardError(f"JSON authority must be object: {path}")
    return payload


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise C14AResearchProgramGuardError(f"{label} must be decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise C14AResearchProgramGuardError(f"{label} must be decimal") from exc
    if not parsed.is_finite():
        raise C14AResearchProgramGuardError(f"{label} must be finite")
    return parsed


def _window_tuples(value: object, label: str) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(value, list):
        raise C14AResearchProgramGuardError(f"{label} must be a list")
    rows: list[tuple[str, str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"id", "start", "end"}:
            raise C14AResearchProgramGuardError(f"{label} row drift")
        row = (item.get("id"), item.get("start"), item.get("end"))
        if not all(isinstance(part, str) for part in row):
            raise C14AResearchProgramGuardError(f"{label} fields must be strings")
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
        raise C14AResearchProgramGuardError("psr must be in [0, 1]")
    if trial_count != EXPECTED_FAMILYWISE_TRIALS:
        raise C14AResearchProgramGuardError("family-wise trial-count drift")
    return max(
        Decimal(0), Decimal(1) - Decimal(trial_count) * (Decimal(1) - probability)
    )


def validate_registry(
    registry: Mapping[str, Any],
    *,
    authority_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Validate exact prior-stage history and optionally hash authorities."""

    if registry.get("schema_version") != 5:
        raise C14AResearchProgramGuardError("program registry schema drift")
    if registry.get("program") != "PHASE_C_PROFITABILITY_RESEARCH":
        raise C14AResearchProgramGuardError("program registry identity drift")
    if registry.get("history_semantics") != "DECLARED_OBSERVED_TRIAL_LOWER_BOUND":
        raise C14AResearchProgramGuardError("program history semantics drift")
    if registry.get("untracked_human_discretion_fully_corrected") is not False:
        raise C14AResearchProgramGuardError(
            "untracked discretion cannot claim correction"
        )

    stages = registry.get("stages")
    if not isinstance(stages, list) or len(stages) != len(EXPECTED_STAGE_TRIALS):
        raise C14AResearchProgramGuardError("program stage inventory drift")
    observed: list[tuple[str, int, str]] = []
    authorities: list[dict[str, Any]] = []
    paths: set[str] = set()
    resolved_root = authority_root.resolve() if authority_root is not None else None
    for row in stages:
        if not isinstance(row, Mapping):
            raise C14AResearchProgramGuardError("program stage row must be object")
        count = row.get("observed_economic_trials")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise C14AResearchProgramGuardError(
                "observed trial count must be non-negative int"
            )
        observed.append((row.get("stage"), count, row.get("result")))  # type: ignore[arg-type]
        relative = row.get("authority_path")
        markers = row.get("authority_markers")
        if not isinstance(relative, str) or relative in paths:
            raise C14AResearchProgramGuardError("authority path missing or duplicated")
        if (
            not isinstance(markers, list)
            or not markers
            or not all(isinstance(marker, str) and marker for marker in markers)
        ):
            raise C14AResearchProgramGuardError("authority markers missing")
        paths.add(relative)
        if resolved_root is not None:
            path = (resolved_root / relative).resolve()
            if not path.is_relative_to(resolved_root):
                raise C14AResearchProgramGuardError("authority path escapes repository")
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise C14AResearchProgramGuardError(
                    f"unable to read program authority {relative}: {exc}"
                ) from exc
            missing = [marker for marker in markers if marker not in text]
            if missing:
                raise C14AResearchProgramGuardError(
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
        raise C14AResearchProgramGuardError("program stage trial/result history drift")
    total = sum(count for _, count, _ in observed)
    if total != EXPECTED_PRIOR_TRIALS:
        raise C14AResearchProgramGuardError("computed prior trial-count drift")
    if registry.get("prior_observed_economic_trial_count") != total:
        raise C14AResearchProgramGuardError("declared prior trial-count drift")
    if registry.get("prospective_stage") != "C14A":
        raise C14AResearchProgramGuardError("prospective stage drift")
    if registry.get("prospective_candidate_count") != 1:
        raise C14AResearchProgramGuardError("C14A candidate-count drift")
    if registry.get("familywise_trial_count") != EXPECTED_FAMILYWISE_TRIALS:
        raise C14AResearchProgramGuardError("family-wise trial-count drift")
    if registry.get("familywise_trial_count") != total + 1:
        raise C14AResearchProgramGuardError("family-wise count must include C14A")
    if _decimal(registry.get("familywise_alpha"), "familywise alpha") != Decimal(
        "0.05"
    ):
        raise C14AResearchProgramGuardError("family-wise alpha drift")
    if registry.get("exposed_economic_interval_union") != {
        "start_inclusive": "2023-07-03T00:00:00Z",
        "end_exclusive": "2026-06-29T00:00:00Z",
        "status": "HISTORICAL_DEVELOPMENT_ONLY",
    }:
        raise C14AResearchProgramGuardError("historical exposure registry drift")
    if _window_tuples(registry.get("c14a_windows"), "registry windows") != EXPECTED_WINDOWS:
        raise C14AResearchProgramGuardError("C14A registered-window drift")
    for key, expected in {
        "promotion_state": "RESEARCH_ONLY",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }.items():
        if registry.get(key) != expected:
            raise C14AResearchProgramGuardError(f"program safety-state drift: {key}")
    return authorities


def validate_c14a_config(config: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    """Validate every frozen C14A design and safety field."""

    if config.get("schema_version") != 1 or config.get("stage") != "C14A":
        raise C14AResearchProgramGuardError("C14A config identity drift")
    if config.get("change_type") != "DESIGN_AND_PROGRAM_GUARD":
        raise C14AResearchProgramGuardError("C14A change type drift")
    if config.get("design_base_sha") != EXPECTED_DESIGN_BASE_SHA:
        raise C14AResearchProgramGuardError("C14A design base drift")
    if config.get("contract_path") != str(CONTRACT_PATH.relative_to(ROOT)):
        raise C14AResearchProgramGuardError("C14A contract path drift")
    if config.get("program_registry_path") != str(REGISTRY_PATH.relative_to(ROOT)):
        raise C14AResearchProgramGuardError("C14A registry path drift")
    if config.get("candidate_id") != "C14ACrossSectionalAmihudLiquidityRisk":
        raise C14AResearchProgramGuardError("C14A candidate identity drift")
    if tuple(config.get("comparators", ())) != EXPECTED_COMPARATORS:
        raise C14AResearchProgramGuardError("C14A comparator drift")
    if tuple(config.get("instruments", ())) != EXPECTED_INSTRUMENTS:
        raise C14AResearchProgramGuardError("C14A instrument drift")
    if _window_tuples(config.get("windows"), "config windows") != EXPECTED_WINDOWS:
        raise C14AResearchProgramGuardError("C14A config-window drift")
    if _window_tuples(registry.get("c14a_windows"), "registry windows") != EXPECTED_WINDOWS:
        raise C14AResearchProgramGuardError("C14A registry-window drift")

    fixed: dict[str, object] = {
        "btc_beta_benchmark_instrument": "BTC-USDT-SWAP",
        "scored_start": EXPECTED_WINDOWS[0][1],
        "scored_end_exclusive": EXPECTED_WINDOWS[-1][2],
        "trade_capture_start": "2023-12-03T00:00:00Z",
        "mark_capture_start": "2023-12-31T23:00:00Z",
        "timeframe": "1H",
        "decision_and_execution_schedule": "MONDAY_00_UTC",
        "signal_cutoff_schedule": "SUNDAY_00_UTC",
        "signal_execution_lag_hours": 24,
        "signal_lookback_complete_days": 28,
        "daily_return_clock": "UTC_DAY_OPEN_TO_NEXT_UTC_DAY_OPEN_LOG_RETURN",
        "daily_quote_volume": "SUM_24_CONFIRMED_HOURLY_VOL_CCY_QUOTE",
        "score": "MEAN_DAILY_ABS_LOG_RETURN_DIVIDED_BY_DAILY_QUOTE_VOLUME_OVER_28D",
        "rank_direction": "LONG_HIGH_ILLIQUIDITY_SHORT_LOW_ILLIQUIDITY",
        "rank_tiebreak": "INSTRUMENT_ID_ASCENDING",
        "long_count": 2,
        "short_count": 2,
        "funding_timestamp_semantics": "ACTUAL_OKX_FUNDING_TIME_NO_SNAPPING",
        "exact_hour_event_order": "FUNDING_BEFORE_REBALANCE",
        "delayed_funding_event_order": "APPLY_TO_POSITION_CARRIED_AT_ACTUAL_TIMESTAMP",
    }
    for key, expected in fixed.items():
        if config.get(key) != expected:
            raise C14AResearchProgramGuardError(f"C14A frozen field drift: {key}")

    portfolio = (
        _decimal(config.get("gross_notional"), "gross notional"),
        _decimal(config.get("long_gross_notional"), "long gross"),
        _decimal(config.get("short_gross_notional"), "short gross"),
        _decimal(config.get("per_position_abs_notional"), "position notional"),
        _decimal(config.get("starting_equity"), "starting equity"),
        _decimal(config.get("minimum_equity_to_gross_notional"), "equity buffer"),
        _decimal(config.get("reconciliation_tolerance"), "reconciliation tolerance"),
    )
    if portfolio != (
        Decimal("0.50"),
        Decimal("0.25"),
        Decimal("0.25"),
        Decimal("0.125"),
        Decimal(1000),
        Decimal("1.25"),
        Decimal("1e-10"),
    ):
        raise C14AResearchProgramGuardError("C14A portfolio/accounting drift")
    if config.get("cost_rates") != {
        "1.0x": "0.0015",
        "1.5x": "0.00225",
        "2.0x": "0.0030",
    }:
        raise C14AResearchProgramGuardError("C14A cost schedule drift")

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
        "maximum_abs_btc_beta": "0.15",
        "maximum_annualized_one_way_turnover": "30.0",
        "minimum_positive_instrument_contributions": 6,
        "maximum_positive_instrument_pnl_share": "0.35",
        "maximum_positive_window_pnl_share": "0.35",
        "maximum_positive_week_pnl_share": "0.15",
        "maximum_top_three_positive_week_pnl_share": "0.35",
        "minimum_return_delta_vs_mean_absolute_return_exclusive": "0",
        "minimum_sharpe_delta_vs_mean_absolute_return": "0.10",
        "require_drawdown_no_worse_than_mean_absolute_return": True,
        "require_turnover_no_greater_than_mean_absolute_return": True,
        "minimum_return_delta_vs_inverse_quote_volume_exclusive": "0",
        "minimum_sharpe_delta_vs_inverse_quote_volume": "0.10",
        "require_drawdown_no_worse_than_inverse_quote_volume": True,
        "require_turnover_no_greater_than_inverse_quote_volume": True,
        "maximum_equity_buffer_breaches": 0,
        "required_decisions": 130,
        "required_nonflat_instrument_directions": 520,
    }
    gates = config.get("gates")
    if not isinstance(gates, Mapping) or dict(gates) != expected_gates:
        raise C14AResearchProgramGuardError("C14A economic-gate drift")
    if gates["declared_program_familywise_trial_count"] != registry.get(
        "familywise_trial_count"
    ):
        raise C14AResearchProgramGuardError("C14A/program correction-count mismatch")

    for key, expected in {
        "historical_data_status": "HISTORICAL_DEVELOPMENT_ONLY",
        "execution_feasibility_established": False,
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }.items():
        if config.get(key) != expected:
            raise C14AResearchProgramGuardError(f"C14A safety-state drift: {key}")


def verify_repository_authority(root: Path = ROOT) -> dict[str, Any]:
    """Hash and validate the exact frozen C14A repository authorities."""

    registry_path = root / REGISTRY_PATH.relative_to(ROOT)
    config_path = root / C14A_CONFIG_PATH.relative_to(ROOT)
    contract_path = root / CONTRACT_PATH.relative_to(ROOT)
    registry_sha = _sha256(registry_path)
    config_sha = _sha256(config_path)
    contract_sha = _sha256(contract_path)
    if registry_sha != EXPECTED_REGISTRY_SHA256:
        raise C14AResearchProgramGuardError("program registry file hash drift")
    if config_sha != EXPECTED_C14A_CONFIG_SHA256:
        raise C14AResearchProgramGuardError("C14A config file hash drift")
    if contract_sha != EXPECTED_CONTRACT_SHA256:
        raise C14AResearchProgramGuardError("C14A contract file hash drift")
    registry = _load_object(registry_path)
    config = _load_object(config_path)
    authorities = validate_registry(registry, authority_root=root)
    validate_c14a_config(config, registry)
    contract = contract_path.read_text(encoding="utf-8")
    required_markers = (
        "Historical economic result: `NOT_RUN`",
        "C14A is prospective economic trial `629`",
        "No C14A score, rank, trade, PnL, return, Sharpe, PSR, comparator",
        "`C14A_DESIGN_ONLY`",
        "`HISTORICAL_DEVELOPMENT_ONLY`",
        "`PAPER_CLOSED`",
        "`SHADOW_CLOSED`",
        "`LIVE_FORBIDDEN`",
    )
    if any(marker not in contract for marker in required_markers):
        raise C14AResearchProgramGuardError("C14A contract marker drift")
    return {
        "schema_version": 1,
        "stage": "C14A_PROGRAM_GUARD",
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
    "C14A_CONFIG_PATH",
    "CONTRACT_PATH",
    "EXPECTED_C14A_CONFIG_SHA256",
    "EXPECTED_CONTRACT_SHA256",
    "EXPECTED_DESIGN_BASE_SHA",
    "EXPECTED_FAMILYWISE_TRIALS",
    "EXPECTED_PRIOR_TRIALS",
    "EXPECTED_REGISTRY_SHA256",
    "REGISTRY_PATH",
    "ROOT",
    "C14AResearchProgramGuardError",
    "bonferroni_adjusted_psr",
    "validate_c14a_config",
    "validate_registry",
    "verify_repository_authority",
]
