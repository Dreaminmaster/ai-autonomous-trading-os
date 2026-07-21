#!/usr/bin/env python3
"""Verify frozen prior-stage authority before any C5A market-data access."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c5a_derivatives_crowding import (
    EXPECTED_CONFIG_CANONICAL_SHA256,
    canonical_sha256,
    validate_config,
)

IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
CONFIG_PATH = IMPL / "config/c5a_derivatives_crowding_regime.json"
REPORT_PATH = IMPL / "freqtrade_data/c5a_runtime/c5a_program_guard.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

AUTHORITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "docs/architecture/phase-c/c0c/C0C_COST_AWARE_EMA_RESULT_V1.md",
        (
            "Status: `REJECTED`",
            "development_economic_pass = false",
            "development_test_opened = false",
            "holdout_state = HOLDOUT_CLOSED",
            "live = FORBIDDEN",
        ),
    ),
    (
        "docs/architecture/phase-c/c1a-family-screen/C1A_STRATEGY_FAMILY_SCREEN_RESULT_V1.md",
        (
            "- Economic result: `REJECTED`",
            "- Selected family: `null`",
            "- Confirmation opened: `false`",
            "- No C1B confirmation window or holdout timerange was executed.",
            "- Holdout state: `HOLDOUT_CLOSED`",
            "- Live: `FORBIDDEN`",
        ),
    ),
    (
        "docs/architecture/phase-c/c2a-low-turnover-allocation/C2A_LOW_TURNOVER_ALLOCATION_RESULT_V1.md",
        (
            "- Economic result: `REJECTED`",
            "- Selected policy: `null`",
            "- Confirmation opened: `false`",
            "- C2B confirmation: `CLOSED`",
            "- Holdout state: `HOLDOUT_CLOSED`",
            "- Live: `FORBIDDEN`",
        ),
    ),
    (
        "docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_RESIDUAL_MEAN_REVERSION_RESULT_V1.md",
        (
            "- Economic result: `REJECTED`",
            "- Selected policy: `null`",
            "- Confirmation opened: `false`",
            "- C3B confirmation: `CLOSED`",
            "- Holdout state: `HOLDOUT_CLOSED`",
            "- Live: `FORBIDDEN`",
        ),
    ),
    (
        "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_LARGE_LIQUID_CROSS_SECTIONAL_MOMENTUM_RESULT_V1.md",
        (
            "- Economic result: `REJECTED`",
            "- Selected policy: `null`",
            "- C4B confirmation: `CLOSED`",
            "- Holdout: `CLOSED`",
            "- Paper execution: `CLOSED`",
            "- Shadow execution: `CLOSED`",
            "- Live execution: `FORBIDDEN`",
        ),
    ),
    (
        "docs/architecture/phase-c/c5a-derivatives-crowding-regime/C5A_PROGRAM_HOLDOUT_RECLASSIFICATION_V1.md",
        (
            "C0C: `REJECTED`; development test and its reserved holdout were never opened",
            "C5A is the only stage authorized to consume the reclassified development interval",
            "`C5A_DATA_UNREAD`",
            "`C5B_CLOSED`",
            "`HOLDOUT_CLOSED`",
            "`LIVE_FORBIDDEN`",
        ),
    ),
)


class C5AProgramGuardError(RuntimeError):
    pass


def _exact_sha() -> str:
    value = os.environ.get("C5A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C5AProgramGuardError(
            "C5A_SOURCE_SHA must be an exact lowercase 40-character SHA"
        )
    return value


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C5AProgramGuardError(f"unable to hash {path}: {exc}") from exc


def _require_markers(text: str, markers: Sequence[str], label: str) -> None:
    missing = [marker for marker in markers if marker not in text]
    if missing:
        raise C5AProgramGuardError(
            f"{label} authority marker mismatch: {missing}"
        )


def verify_authorities(root: Path, config: Mapping[str, Any]) -> dict[str, Any]:
    validate_config(config)
    if canonical_sha256(config) != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C5AProgramGuardError("C5A semantic config hash mismatch")
    reserved = config.get("reserved_confirmation")
    if not isinstance(reserved, Mapping) or reserved != {
        "id": "C5B",
        "start": "2026-01-05T00:00:00Z",
        "end": "2026-07-06T00:00:00Z",
    }:
        raise C5AProgramGuardError("C5B reserved-confirmation boundary drift")
    if config.get("economic_boundary_exclusive") != reserved["start"]:
        raise C5AProgramGuardError("C5A/C5B boundary mismatch")
    if config.get("confirmation_opened") is not False:
        raise C5AProgramGuardError("C5B unexpectedly opened")

    files: list[dict[str, Any]] = []
    for relative, markers in AUTHORITIES:
        path = root / relative
        if not path.is_file():
            raise C5AProgramGuardError(f"required program authority missing: {relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise C5AProgramGuardError(f"unable to read {relative}: {exc}") from exc
        _require_markers(text, markers, relative)
        files.append(
            {
                "path": relative,
                "sha256": _sha256(path),
                "marker_count": len(markers),
                "status": "PASS",
            }
        )
    if len(files) != 6:
        raise C5AProgramGuardError("program authority file-count mismatch")
    return {
        "schema_version": 1,
        "stage": "C5A",
        "status": "PASS",
        "config_canonical_sha256": EXPECTED_CONFIG_CANONICAL_SHA256,
        "prior_stage_result_count": 5,
        "authority_file_count": len(files),
        "authorities": files,
        "c0c_development_test_opened": False,
        "prior_confirmation_stages_opened": [],
        "prior_selected_policies": [],
        "c5a_development_start": "2025-07-07T00:00:00Z",
        "c5b_boundary_exclusive": "2026-01-05T00:00:00Z",
        "c5b_reserved_end": "2026-07-06T00:00:00Z",
        "confirmation_opened": False,
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
        raise C5AProgramGuardError(f"invalid C5A config: {exc}") from exc
    if not isinstance(config, Mapping):
        raise C5AProgramGuardError("C5A config must be an object")
    payload = verify_authorities(ROOT, config)
    payload["source_head_sha"] = source_sha
    _write(REPORT_PATH, payload)
    print(
        "C5A program guard PASS: five prior rejections / no opened confirmation / "
        "C5B boundary closed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
