"""Fail-closed Phase C history and C12A design-authority guard.

This module performs no network, account, order, Paper, Shadow, or Live work.
It validates immutable local authorities before C12A implementation or
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
REGISTRY_PATH = ROOT / "implementation/config/phase_c_research_program_registry_v3.json"
C12A_CONFIG_PATH = ROOT / "implementation/config/c12a_fixed_maturity_basis_carry.json"
CONTRACT_PATH = (
    ROOT
    / "docs/architecture/phase-c/c12a-fixed-maturity-basis-carry/"
    "C12A_FIXED_MATURITY_BASIS_CARRY_CONTRACT_V1.md"
)

EXPECTED_REGISTRY_SHA256 = "aa7924ac272040de80da65620a6f1811477b77296f6b27f0fbd57efee99b831b"
EXPECTED_C12A_CONFIG_SHA256 = "20eccef80af54aab17e768fcdec47da69e5f999737d97147c61c436f11549cda"
EXPECTED_CONTRACT_SHA256 = "76833ed0b270cfb0ff8f5ba27d36621e53b0bed6d57dec82805f607201716c81"
EXPECTED_DESIGN_BASE_SHA = "2b561e86cb0f708559e0821db1ba9bf0210b817c"

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
)
EXPECTED_PRIOR_TRIALS = 627
EXPECTED_FAMILYWISE_TRIALS = 628

EXPECTED_WINDOWS = (
    ("H1", "2024-01-01T00:00:00Z", "2024-07-01T00:00:00Z"),
    ("H2", "2024-07-01T00:00:00Z", "2024-12-30T00:00:00Z"),
    ("H3", "2024-12-30T00:00:00Z", "2025-06-30T00:00:00Z"),
    ("H4", "2025-06-30T00:00:00Z", "2025-12-29T00:00:00Z"),
    ("H5", "2025-12-29T00:00:00Z", "2026-06-29T00:00:00Z"),
)
EXPECTED_CONTRACTS = (
    ("2024-03-29T08:00:00Z", "BTC-USDT-240329", "ETH-USDT-240329"),
    ("2024-06-28T08:00:00Z", "BTC-USDT-240628", "ETH-USDT-240628"),
    ("2024-09-27T08:00:00Z", "BTC-USDT-240927", "ETH-USDT-240927"),
    ("2024-12-27T08:00:00Z", "BTC-USDT-241227", "ETH-USDT-241227"),
    ("2025-03-28T08:00:00Z", "BTC-USDT-250328", "ETH-USDT-250328"),
    ("2025-06-27T08:00:00Z", "BTC-USDT-250627", "ETH-USDT-250627"),
    ("2025-09-26T08:00:00Z", "BTC-USDT-250926", "ETH-USDT-250926"),
    ("2025-12-26T08:00:00Z", "BTC-USDT-251226", "ETH-USDT-251226"),
    ("2026-03-27T08:00:00Z", "BTC-USDT-260327", "ETH-USDT-260327"),
    ("2026-06-26T08:00:00Z", "BTC-USDT-260626", "ETH-USDT-260626"),
)
EXPECTED_COMPARATORS = (
    "CashComparator",
    "AlwaysEnterQuarterlyBasisComparator",
    "SpotOnlyQuarterlyHoldComparator",
)
EXPECTED_ARCHIVE_MONTHS = (
    "2024-03",
    "2024-05",
    "2024-06",
    "2024-08",
    "2024-09",
    "2024-11",
    "2024-12",
    "2025-02",
    "2025-03",
    "2025-05",
    "2025-06",
    "2025-08",
    "2025-09",
    "2025-11",
    "2025-12",
    "2026-02",
    "2026-03",
    "2026-05",
    "2026-06",
)


class C12AResearchProgramGuardError(RuntimeError):
    """Raised when C12A history, design, or safety authority drifts."""


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C12AResearchProgramGuardError(f"unable to hash authority {path}: {exc}") from exc


def _load_object(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise C12AResearchProgramGuardError(
                    f"duplicate JSON authority key {key!r}: {path}"
                )
            output[key] = value
        return output

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise C12AResearchProgramGuardError(f"invalid JSON authority {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise C12AResearchProgramGuardError(f"JSON authority must be an object: {path}")
    return payload


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise C12AResearchProgramGuardError(f"{label} must be decimal")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise C12AResearchProgramGuardError(f"{label} must be decimal") from exc
    if not parsed.is_finite():
        raise C12AResearchProgramGuardError(f"{label} must be finite")
    return parsed


def _window_tuples(value: object, label: str) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(value, list):
        raise C12AResearchProgramGuardError(f"{label} must be a list")
    rows: list[tuple[str, str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise C12AResearchProgramGuardError(f"{label} rows must be objects")
        row = (item.get("id"), item.get("start"), item.get("end"))
        if not all(isinstance(part, str) for part in row):
            raise C12AResearchProgramGuardError(f"{label} row fields must be strings")
        rows.append(row)  # type: ignore[arg-type]
    return tuple(rows)


def _contract_tuples(value: object) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(value, list):
        raise C12AResearchProgramGuardError("quarterly contracts must be a list")
    rows: list[tuple[str, str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise C12AResearchProgramGuardError("quarterly contract rows must be objects")
        row = (item.get("expiry"), item.get("btc"), item.get("eth"))
        if not all(isinstance(part, str) for part in row):
            raise C12AResearchProgramGuardError("quarterly contract fields must be strings")
        if set(item) != {"expiry", "btc", "eth"}:
            raise C12AResearchProgramGuardError("quarterly contract field drift")
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
        raise C12AResearchProgramGuardError("psr must be in [0, 1]")
    if trial_count != EXPECTED_FAMILYWISE_TRIALS:
        raise C12AResearchProgramGuardError("family-wise trial-count drift")
    return max(Decimal(0), Decimal(1) - Decimal(trial_count) * (Decimal(1) - probability))


def validate_registry(
    registry: Mapping[str, Any],
    *,
    authority_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Validate exact prior-stage history and optionally hash authorities."""

    if registry.get("schema_version") != 3:
        raise C12AResearchProgramGuardError("program registry schema drift")
    if registry.get("program") != "PHASE_C_PROFITABILITY_RESEARCH":
        raise C12AResearchProgramGuardError("program registry identity drift")
    if registry.get("history_semantics") != "DECLARED_OBSERVED_TRIAL_LOWER_BOUND":
        raise C12AResearchProgramGuardError("program history semantics drift")
    if registry.get("untracked_human_discretion_fully_corrected") is not False:
        raise C12AResearchProgramGuardError("untracked discretion cannot claim correction")

    stages = registry.get("stages")
    if not isinstance(stages, list) or len(stages) != len(EXPECTED_STAGE_TRIALS):
        raise C12AResearchProgramGuardError("program stage inventory drift")
    observed: list[tuple[str, int, str]] = []
    authorities: list[dict[str, Any]] = []
    paths: set[str] = set()
    resolved_root = authority_root.resolve() if authority_root is not None else None
    for row in stages:
        if not isinstance(row, Mapping):
            raise C12AResearchProgramGuardError("program stage row must be an object")
        count = row.get("observed_economic_trials")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise C12AResearchProgramGuardError("observed trial count must be non-negative int")
        observed.append((row.get("stage"), count, row.get("result")))  # type: ignore[arg-type]
        relative = row.get("authority_path")
        markers = row.get("authority_markers")
        if not isinstance(relative, str) or relative in paths:
            raise C12AResearchProgramGuardError("authority path missing or duplicated")
        if not isinstance(markers, list) or not markers or not all(
            isinstance(marker, str) and marker for marker in markers
        ):
            raise C12AResearchProgramGuardError("authority markers missing")
        paths.add(relative)
        if resolved_root is not None:
            path = (resolved_root / relative).resolve()
            if not path.is_relative_to(resolved_root):
                raise C12AResearchProgramGuardError("authority path escapes repository root")
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise C12AResearchProgramGuardError(
                    f"unable to read program authority {relative}: {exc}"
                ) from exc
            missing = [marker for marker in markers if marker not in text]
            if missing:
                raise C12AResearchProgramGuardError(
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
        raise C12AResearchProgramGuardError("program stage trial/result history drift")
    total = sum(count for _, count, _ in observed)
    if total != EXPECTED_PRIOR_TRIALS:
        raise C12AResearchProgramGuardError("computed prior trial-count drift")
    if registry.get("prior_observed_economic_trial_count") != total:
        raise C12AResearchProgramGuardError("declared prior trial-count drift")
    if registry.get("prospective_stage") != "C12A":
        raise C12AResearchProgramGuardError("prospective stage drift")
    if registry.get("prospective_candidate_count") != 1:
        raise C12AResearchProgramGuardError("C12A candidate-count drift")
    if registry.get("familywise_trial_count") != total + 1:
        raise C12AResearchProgramGuardError("family-wise trial-count drift")
    if registry.get("familywise_trial_count") != EXPECTED_FAMILYWISE_TRIALS:
        raise C12AResearchProgramGuardError("family-wise trial-count drift")
    if _decimal(registry.get("familywise_alpha"), "familywise alpha") != Decimal("0.05"):
        raise C12AResearchProgramGuardError("family-wise alpha drift")
    if registry.get("exposed_economic_interval_union") != {
        "start_inclusive": "2023-07-03T00:00:00Z",
        "end_exclusive": "2026-06-29T00:00:00Z",
        "status": "HISTORICAL_DEVELOPMENT_ONLY",
    }:
        raise C12AResearchProgramGuardError("historical exposure registry drift")
    if _window_tuples(registry.get("c12a_windows"), "registry windows") != EXPECTED_WINDOWS:
        raise C12AResearchProgramGuardError("C12A registered-window drift")
    safety = {
        "promotion_state": "RESEARCH_ONLY",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    for key, expected in safety.items():
        if registry.get(key) != expected:
            raise C12AResearchProgramGuardError(f"program safety-state drift: {key}")
    return authorities


def validate_c12a_config(config: Mapping[str, Any], registry: Mapping[str, Any]) -> None:
    """Validate every frozen C12A design and safety field."""

    if config.get("schema_version") != 1 or config.get("stage") != "C12A":
        raise C12AResearchProgramGuardError("C12A config identity drift")
    if config.get("change_type") != "DESIGN_AND_PROGRAM_GUARD":
        raise C12AResearchProgramGuardError("C12A change type drift")
    if config.get("design_base_sha") != EXPECTED_DESIGN_BASE_SHA:
        raise C12AResearchProgramGuardError("C12A design base drift")
    if config.get("contract_path") != str(CONTRACT_PATH.relative_to(ROOT)):
        raise C12AResearchProgramGuardError("C12A contract path drift")
    if config.get("program_registry_path") != str(REGISTRY_PATH.relative_to(ROOT)):
        raise C12AResearchProgramGuardError("C12A registry path drift")
    if config.get("candidate_id") != "C12AFixedMaturityBasisCarry":
        raise C12AResearchProgramGuardError("C12A candidate identity drift")
    if tuple(config.get("comparators", ())) != EXPECTED_COMPARATORS:
        raise C12AResearchProgramGuardError("C12A comparator drift")
    if tuple(config.get("spot_instruments", ())) != ("BTC-USDT", "ETH-USDT"):
        raise C12AResearchProgramGuardError("C12A spot-instrument drift")
    if tuple(config.get("futures_families", ())) != ("BTC-USDT", "ETH-USDT"):
        raise C12AResearchProgramGuardError("C12A futures-family drift")
    if tuple(config.get("required_archive_months", ())) != EXPECTED_ARCHIVE_MONTHS:
        raise C12AResearchProgramGuardError("C12A archive-month drift")
    if _contract_tuples(config.get("quarterly_contracts")) != EXPECTED_CONTRACTS:
        raise C12AResearchProgramGuardError("C12A quarterly-contract drift")
    if _window_tuples(config.get("windows"), "config windows") != EXPECTED_WINDOWS:
        raise C12AResearchProgramGuardError("C12A config-window drift")
    if _window_tuples(registry.get("c12a_windows"), "registry windows") != EXPECTED_WINDOWS:
        raise C12AResearchProgramGuardError("C12A registry-window drift")

    fixed: dict[str, object] = {
        "scored_start": EXPECTED_WINDOWS[0][1],
        "scored_end_exclusive": EXPECTED_WINDOWS[-1][2],
        "spot_capture_start": "2023-12-31T23:00:00Z",
        "spot_timeframe": "1H",
        "futures_source": "OKX_OFFICIAL_MONTHLY_FUTURES_CHAIN_TRADES",
        "archive_calendar_timezone": "UTC+08:00",
        "signal_lead_days": 28,
        "signal_time_before_entry_hours": 1,
        "entry_time_utc": "08:00:00",
        "exit_before_expiry_hours": 1,
        "execution_trade_max_delay_seconds": 60,
        "rank_or_selection": "NONE_FIXED_TWO_ASSET_SLEEVES",
        "basis_definition": (
            "(FUTURES_MARK_MINUS_SPOT_CLOSE)_DIVIDED_BY_"
            "(FUTURES_MARK_PLUS_SPOT_CLOSE)"
        ),
        "entry_rule": "POSITIVE_BASIS_STRICTLY_EXCEEDS_2X_COMPLETE_ROUND_TRIP_COST",
        "base_quantity_hedge": "EXACT_EQUAL_SPOT_LONG_FUTURES_SHORT",
    }
    for key, expected in fixed.items():
        if config.get(key) != expected:
            raise C12AResearchProgramGuardError(f"C12A frozen field drift: {key}")

    portfolio = (
        _decimal(config.get("starting_equity"), "starting equity"),
        _decimal(config.get("per_asset_sleeve_equity"), "asset sleeve"),
        _decimal(config.get("maximum_initial_gross_notional"), "maximum gross"),
        _decimal(
            config.get("minimum_margin_equity_to_futures_notional"),
            "minimum margin buffer",
        ),
        _decimal(config.get("reconciliation_tolerance"), "reconciliation tolerance"),
        _decimal(config.get("entry_basis_threshold"), "entry basis threshold"),
    )
    if portfolio != (
        Decimal(1000),
        Decimal("0.50"),
        Decimal("1.00"),
        Decimal("0.25"),
        Decimal("1e-10"),
        Decimal("0.0120"),
    ):
        raise C12AResearchProgramGuardError("C12A portfolio/accounting drift")
    if config.get("one_side_all_in_cost_rates") != {
        "1.0x": "0.0015",
        "1.5x": "0.00225",
        "2.0x": "0.0030",
    }:
        raise C12AResearchProgramGuardError("C12A cost schedule drift")

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
        "maximum_abs_btc_beta": "0.10",
        "maximum_annualized_one_way_turnover": "6.0",
        "minimum_active_asset_contracts": 10,
        "minimum_active_asset_contracts_per_window": 1,
        "minimum_positive_asset_contributions": 2,
        "maximum_positive_asset_pnl_share": "0.70",
        "maximum_positive_window_pnl_share": "0.35",
        "maximum_positive_contract_pnl_share": "0.25",
        "maximum_positive_week_pnl_share": "0.25",
        "maximum_top_three_positive_week_pnl_share": "0.50",
        "minimum_return_delta_vs_always_enter": "0",
        "minimum_sharpe_delta_vs_always_enter": "0",
        "require_drawdown_no_worse_than_always_enter": True,
        "require_turnover_no_greater_than_always_enter": True,
        "maximum_margin_buffer_breaches": 0,
        "maximum_base_hedge_mismatches": 0,
        "required_contract_decisions": 20,
        "required_weekly_return_buckets": 130,
    }
    gates = config.get("gates")
    if not isinstance(gates, Mapping) or dict(gates) != expected_gates:
        raise C12AResearchProgramGuardError("C12A economic-gate drift")
    if gates["declared_program_familywise_trial_count"] != registry.get(
        "familywise_trial_count"
    ):
        raise C12AResearchProgramGuardError("C12A/program correction-count mismatch")

    safety: dict[str, object] = {
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
            raise C12AResearchProgramGuardError(f"C12A safety-state drift: {key}")


def verify_repository_authority(root: Path = ROOT) -> dict[str, Any]:
    """Hash and validate the exact frozen C12A repository authorities."""

    registry_path = root / REGISTRY_PATH.relative_to(ROOT)
    config_path = root / C12A_CONFIG_PATH.relative_to(ROOT)
    contract_path = root / CONTRACT_PATH.relative_to(ROOT)
    registry_sha = _sha256(registry_path)
    config_sha = _sha256(config_path)
    contract_sha = _sha256(contract_path)
    if registry_sha != EXPECTED_REGISTRY_SHA256:
        raise C12AResearchProgramGuardError("program registry file hash drift")
    if config_sha != EXPECTED_C12A_CONFIG_SHA256:
        raise C12AResearchProgramGuardError("C12A config file hash drift")
    if contract_sha != EXPECTED_CONTRACT_SHA256:
        raise C12AResearchProgramGuardError("C12A contract file hash drift")
    registry = _load_object(registry_path)
    config = _load_object(config_path)
    authorities = validate_registry(registry, authority_root=root)
    validate_c12a_config(config, registry)
    contract = contract_path.read_text(encoding="utf-8")
    required_contract_markers = (
        "Historical economic result: `NOT_RUN`",
        "C12A is prospective economic trial `628`",
        "No C12A entry basis, return, PnL, Sharpe, PSR, comparator",
        "`C12A_DESIGN_FROZEN`",
        "`HISTORICAL_DEVELOPMENT_ONLY`",
        "`PAPER_CLOSED`",
        "`SHADOW_CLOSED`",
        "`LIVE_FORBIDDEN`",
    )
    if any(marker not in contract for marker in required_contract_markers):
        raise C12AResearchProgramGuardError("C12A contract marker drift")
    return {
        "schema_version": 1,
        "stage": "C12A_PROGRAM_GUARD",
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
    "C12A_CONFIG_PATH",
    "CONTRACT_PATH",
    "EXPECTED_C12A_CONFIG_SHA256",
    "EXPECTED_CONTRACT_SHA256",
    "EXPECTED_DESIGN_BASE_SHA",
    "EXPECTED_FAMILYWISE_TRIALS",
    "EXPECTED_PRIOR_TRIALS",
    "EXPECTED_REGISTRY_SHA256",
    "REGISTRY_PATH",
    "ROOT",
    "C12AResearchProgramGuardError",
    "bonferroni_adjusted_psr",
    "validate_c12a_config",
    "validate_registry",
    "verify_repository_authority",
]
