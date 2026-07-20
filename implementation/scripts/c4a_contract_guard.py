#!/usr/bin/env python3
"""Independent exact-contract and full retained-range guard for C4A."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c4a_cross_sectional_runtime import CANDIDATE_PAIRS, validate_config
from atos.profitability_diagnostics import discover_candle_file, load_candles

IMPL = Path(__file__).resolve().parents[1]
CONFIG_PATH = IMPL / "config/c4a_large_liquid_cross_sectional_momentum.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RUNTIME = IMPL / "freqtrade_data/c4a_runtime"
REPORT_PATH = RUNTIME / "c4a_contract_guard.json"
DOWNLOAD_START = datetime(2023, 9, 1, tzinfo=UTC)
FORMATION_END = datetime(2024, 1, 1, tzinfo=UTC)
BOUNDARY = datetime(2024, 10, 1, tzinfo=UTC)
STEP = timedelta(hours=4)
EXPECTED_RETAINED_ROWS = 2376
EXPECTED_FORMATION_ROWS = 732
EXPECTED_SCREEN_ROWS = 1644
EXPECTED_CONFIG_CANONICAL_SHA256 = "14e7b96d1167afad6b23c1bc6302e7f9b86ad291f956944ba8f546908402fa92"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class C4AContractGuardError(RuntimeError):
    pass


def _timestamp(value: Any) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        raw = float(value)
        parsed = datetime.fromtimestamp(raw / (1000 if raw > 10_000_000_000 else 1), tz=UTC)
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise C4AContractGuardError(f"invalid candle timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C4AContractGuardError(f"unable to hash {path}: {exc}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def exact_source_sha() -> str:
    value = os.environ.get("C4A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C4AContractGuardError("C4A_SOURCE_SHA must be an exact lowercase 40-character SHA")
    return value


def load_and_verify_config() -> dict[str, Any]:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C4AContractGuardError(f"invalid C4A config: {exc}") from exc
    if not isinstance(payload, dict):
        raise C4AContractGuardError("C4A config must be an object")
    digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    if digest != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C4AContractGuardError(
            "C4A semantic configuration drift: "
            f"expected {EXPECTED_CONFIG_CANONICAL_SHA256}, got {digest}"
        )
    validate_config(payload)
    if payload.get("live") != "FORBIDDEN":
        raise C4AContractGuardError("C4A live safety state drift")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C4AContractGuardError("C4A holdout safety state drift")
    if payload.get("confirmation_opened") is not False:
        raise C4AContractGuardError("C4B must remain closed")
    return payload


def expected_timestamps() -> list[datetime]:
    count = int((BOUNDARY - DOWNLOAD_START) / STEP)
    values = [DOWNLOAD_START + index * STEP for index in range(count)]
    if len(values) != EXPECTED_RETAINED_ROWS or values[-1] != BOUNDARY - STEP:
        raise C4AContractGuardError("internal expected grid mismatch")
    return values


def _number(row: Mapping[str, Any], key: str, pair: str) -> float:
    try:
        value = float(row.get(key))
    except (TypeError, ValueError) as exc:
        raise C4AContractGuardError(f"{pair} invalid {key}") from exc
    if not math.isfinite(value) or value <= 0:
        raise C4AContractGuardError(f"{pair} non-positive/non-finite {key}")
    return value


def verify_rows(
    rows: Sequence[Mapping[str, Any]],
    pair: str,
    *,
    allow_post_boundary_overshoot: bool,
) -> dict[str, Any]:
    if pair not in CANDIDATE_PAIRS:
        raise C4AContractGuardError(f"unexpected pair: {pair}")
    if not rows:
        raise C4AContractGuardError(f"no candles for {pair}")
    dates = [_timestamp(row.get("date")) for row in rows]
    if dates != sorted(dates):
        raise C4AContractGuardError(f"unordered candles for {pair}")
    if len(set(dates)) != len(dates):
        raise C4AContractGuardError(f"duplicate candles for {pair}")
    retained_rows = [dict(row) for row, when in zip(rows, dates, strict=True) if when < BOUNDARY]
    retained_dates = [when for when in dates if when < BOUNDARY]
    expected = expected_timestamps()
    if retained_dates != expected:
        missing = sorted(set(expected) - set(retained_dates))
        unexpected = sorted(set(retained_dates) - set(expected))
        details: list[str] = []
        if missing:
            details.append(f"first_missing={missing[0].isoformat()}")
        if unexpected:
            details.append(f"first_unexpected={unexpected[0].isoformat()}")
        raise C4AContractGuardError(
            f"{pair} full retained four-hour sequence mismatch"
            + (": " + ", ".join(details) if details else "")
        )
    if not allow_post_boundary_overshoot and len(dates) != len(retained_dates):
        raise C4AContractGuardError(f"post-boundary candle remains for {pair}")
    for row in retained_rows:
        open_price = _number(row, "open", pair)
        high = _number(row, "high", pair)
        low = _number(row, "low", pair)
        close = _number(row, "close", pair)
        _number(row, "volume", pair)
        if low > high or not (low <= open_price <= high) or not (low <= close <= high):
            raise C4AContractGuardError(f"{pair} invalid OHLC geometry")
    formation_rows = sum(when < FORMATION_END for when in retained_dates)
    screen_rows = len(retained_dates) - formation_rows
    if formation_rows != EXPECTED_FORMATION_ROWS or screen_rows != EXPECTED_SCREEN_ROWS:
        raise C4AContractGuardError(f"{pair} formation/screen row count mismatch")
    timestamp_digest = hashlib.sha256(
        "\n".join(value.isoformat() for value in retained_dates).encode("utf-8")
    ).hexdigest()
    return {
        "pair": pair,
        "rows_observed": len(rows),
        "retained_rows": len(retained_dates),
        "post_boundary_rows": len(dates) - len(retained_dates),
        "formation_rows": formation_rows,
        "screen_rows": screen_rows,
        "retained_earliest": retained_dates[0].isoformat(),
        "retained_latest": retained_dates[-1].isoformat(),
        "retained_timestamp_sha256": timestamp_digest,
        "status": "PASS",
    }


def build_report(mode: str, source_sha: str) -> dict[str, Any]:
    config = load_and_verify_config()
    allow_overshoot = mode == "precheck"
    cells: list[dict[str, Any]] = []
    for pair in CANDIDATE_PAIRS:
        path = discover_candle_file(DATA_DIR, pair, "4h")
        cell = verify_rows(
            load_candles(path),
            pair,
            allow_post_boundary_overshoot=allow_overshoot,
        )
        cell["path"] = str(path.relative_to(IMPL))
        cell["sha256"] = _sha256_file(path)
        cells.append(cell)
    if len(cells) != 12:
        raise C4AContractGuardError("contract guard must contain twelve cells")
    sequence_hashes = {cell["retained_timestamp_sha256"] for cell in cells}
    if len(sequence_hashes) != 1:
        raise C4AContractGuardError("candidate retained timestamp sequences differ")
    return {
        "schema_version": 1,
        "stage": "C4A",
        "mode": mode,
        "status": "PASS",
        "source_head_sha": source_sha,
        "config_canonical_sha256": EXPECTED_CONFIG_CANONICAL_SHA256,
        "download_start": DOWNLOAD_START.isoformat(),
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "retained_rows_per_pair": EXPECTED_RETAINED_ROWS,
        "retained_timestamp_sha256": next(iter(sequence_hashes)),
        "cells": sorted(cells, key=lambda item: item["pair"]),
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "config_stage": config["stage"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("config", "precheck", "postcheck"))
    args = parser.parse_args()
    source_sha = exact_source_sha()
    if args.mode == "config":
        load_and_verify_config()
        payload = {
            "schema_version": 1,
            "stage": "C4A",
            "mode": "config",
            "status": "PASS",
            "source_head_sha": source_sha,
            "config_canonical_sha256": EXPECTED_CONFIG_CANONICAL_SHA256,
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        }
    else:
        payload = build_report(args.mode, source_sha)
    _write_json(REPORT_PATH, payload)
    print(f"C4A contract guard {args.mode} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
