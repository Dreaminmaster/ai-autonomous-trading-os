#!/usr/bin/env python3
"""Verify frozen program authority before any C6A public-market access."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c6a_contract import (
    EXPECTED_CONFIG_CANONICAL_SHA256,
    REQUIRED_DESIGN_MAIN_SHA,
    canonical_sha256,
    validate_config,
)

IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
CONFIG_PATH = IMPL / "config/c6a_market_neutral_funding_carry.json"
REPORT_PATH = IMPL / "freqtrade_data/c6a_runtime/c6a_program_guard.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

PRIOR_AUTHORITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "docs/architecture/phase-c/c0c/C0C_COST_AWARE_EMA_RESULT_V1.md",
        ("Status: `REJECTED`", "holdout_state = HOLDOUT_CLOSED", "live = FORBIDDEN"),
    ),
    (
        "docs/architecture/phase-c/c1a-family-screen/C1A_STRATEGY_FAMILY_SCREEN_RESULT_V1.md",
        ("- Economic result: `REJECTED`", "- Selected family: `null`", "- Holdout state: `HOLDOUT_CLOSED`"),
    ),
    (
        "docs/architecture/phase-c/c2a-low-turnover-allocation/C2A_LOW_TURNOVER_ALLOCATION_RESULT_V1.md",
        ("- Economic result: `REJECTED`", "- Selected policy: `null`", "- C2B confirmation: `CLOSED`"),
    ),
    (
        "docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_RESIDUAL_MEAN_REVERSION_RESULT_V1.md",
        ("- Economic result: `REJECTED`", "- Selected policy: `null`", "- C3B confirmation: `CLOSED`"),
    ),
    (
        "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_LARGE_LIQUID_CROSS_SECTIONAL_MOMENTUM_RESULT_V1.md",
        ("- Economic result: `REJECTED`", "- Selected policy: `null`", "- Live execution: `FORBIDDEN`"),
    ),
    (
        "docs/architecture/phase-c/c5a-derivatives-crowding-regime/C5A_DERIVATIVES_CROWDING_REGIME_RESULT_V1.md",
        ("- Economic result: `REJECTED`", "- Selected policy: `null`", "- C5B confirmation: `CLOSED`", "- Live execution: `FORBIDDEN`"),
    ),
)

DESIGN_AUTHORITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "docs/architecture/phase-c/c6a-market-neutral-funding-carry/C6A_MARKET_NEUTRAL_FUNDING_CARRY_CONTRACT_V1.md",
        ("C6AMarketNeutralFundingCarry", "C6A_DESIGN_ONLY", "C6A_ECONOMIC_RESULT_NOT_RUN", "C5B_CLOSED_AND_UNTOUCHED", "LIVE_FORBIDDEN"),
    ),
    (
        "docs/architecture/phase-c/c6a-market-neutral-funding-carry/C6A_ACCOUNTING_MARGIN_AND_STATISTICS_ADDENDUM_V1.md",
        ("PSR_NOT_DSR", "program_level_sequential_history_corrected = false", "C6B_CLOSED", "LIVE_FORBIDDEN"),
    ),
    (
        "docs/architecture/phase-c/c6a-market-neutral-funding-carry/C6A_FUNDING_INTERVAL_AND_HISTORY_CLARIFICATION_V1.md",
        ("no fixed set of interval lengths", "fundingTime", "realizedRate", "C5B_CLOSED_AND_UNTOUCHED"),
    ),
    (
        "docs/architecture/phase-c/c6a-market-neutral-funding-carry/C6A_TERMINAL_AND_METADATA_CLARIFICATION_V1.md",
        ("terminal_time = exclusive_window_end - 1 hour", "effective_from <= transaction_time", "must not be silently projected backward", "LIVE_FORBIDDEN"),
    ),
)


class C6AProgramGuardError(RuntimeError):
    pass


def _exact_sha() -> str:
    value = os.environ.get("C6A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C6AProgramGuardError(
            "C6A_SOURCE_SHA must be an exact lowercase 40-character SHA"
        )
    return value


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C6AProgramGuardError(f"unable to hash {path}: {exc}") from exc


def _require_markers(text: str, markers: Sequence[str], label: str) -> None:
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise C6AProgramGuardError(f"{label} authority marker mismatch: {missing}")


def verify_authorities(root: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    validate_config(config)
    if canonical_sha256(config) != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C6AProgramGuardError("C6A semantic configuration hash mismatch")
    if config.get("required_design_main_sha") != REQUIRED_DESIGN_MAIN_SHA:
        raise C6AProgramGuardError("C6A design authority SHA mismatch")
    files: list[dict[str, Any]] = []
    for kind, authorities in (("PRIOR_RESULT", PRIOR_AUTHORITIES), ("C6A_DESIGN", DESIGN_AUTHORITIES)):
        for relative, markers in authorities:
            path = root / relative
            if not path.is_file():
                raise C6AProgramGuardError(f"required program authority missing: {relative}")
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                raise C6AProgramGuardError(f"unable to read {relative}: {exc}") from exc
            _require_markers(text, markers, relative)
            files.append(
                {
                    "kind": kind,
                    "path": relative,
                    "sha256": _sha256(path),
                    "marker_count": len(markers),
                    "status": "PASS",
                }
            )
    if len(files) != 10:
        raise C6AProgramGuardError("C6A authority file-count mismatch")
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "required_design_main_sha": REQUIRED_DESIGN_MAIN_SHA,
        "config_canonical_sha256": EXPECTED_CONFIG_CANONICAL_SHA256,
        "prior_rejected_stage_count": 6,
        "prior_selected_policies": [],
        "prior_confirmation_stages_opened": [],
        "authority_file_count": len(files),
        "authorities": files,
        "economic_boundary_exclusive": config["economic_boundary_exclusive"],
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    source_sha = _exact_sha()
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6AProgramGuardError(f"invalid C6A config: {exc}") from exc
    if not isinstance(config, Mapping):
        raise C6AProgramGuardError("C6A config must be an object")
    payload = verify_authorities(ROOT, config)
    payload["source_head_sha"] = source_sha
    _write(REPORT_PATH, payload)
    print(
        "C6A program guard PASS: six prior rejections / exact design authority / "
        "C5B and all execution states closed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
