#!/usr/bin/env python3
"""Independent exact-contract and full retained-range guard for C3A.

This guard is deliberately separate from the research engine.  It freezes the
complete semantic configuration and proves that every retained public candle
from the preregistered download start through the exclusive C3A boundary is
present exactly once, strictly ordered, and shared by BTC, ETH, and SOL.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.profitability_diagnostics import discover_candle_file, load_candles


IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
CONFIG_PATH = IMPL / "config/c3a_residual_mean_reversion.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RUNTIME = IMPL / "freqtrade_data/c3a_runtime"
REPORT_PATH = RUNTIME / "c3a_contract_guard.json"
PAIR_ORDER = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
DOWNLOAD_START = datetime(2023, 9, 1, tzinfo=UTC)
FIRST_SCREEN = datetime(2024, 1, 1, tzinfo=UTC)
BOUNDARY = datetime(2024, 10, 1, tzinfo=UTC)
STEP = timedelta(hours=4)
EXPECTED_CONFIG_CANONICAL_SHA256 = "d279da6e12edb0080c18f512cb8f81738de5c43eeb3ba2c00e6c678132074192"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class C3AContractGuardError(RuntimeError):
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
        raise C3AContractGuardError(f"invalid candle timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C3AContractGuardError(f"unable to hash {path}: {exc}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def exact_source_sha() -> str:
    value = os.environ.get("C3A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C3AContractGuardError("C3A_SOURCE_SHA must be an exact lowercase 40-character SHA")
    return value


def load_and_verify_config() -> dict[str, Any]:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C3AContractGuardError(f"invalid C3A config: {exc}") from exc
    if not isinstance(payload, dict):
        raise C3AContractGuardError("C3A config must be an object")
    digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    if digest != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C3AContractGuardError(
            "C3A semantic configuration drift: "
            f"expected {EXPECTED_CONFIG_CANONICAL_SHA256}, got {digest}"
        )
    if payload.get("live") != "FORBIDDEN":
        raise C3AContractGuardError("C3A live safety state drift")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C3AContractGuardError("C3A holdout safety state drift")
    if payload.get("confirmation_opened") is not False:
        raise C3AContractGuardError("C3B must remain closed")
    return payload


def _expected_timestamps() -> list[datetime]:
    count = int((BOUNDARY - DOWNLOAD_START) / STEP)
    return [DOWNLOAD_START + index * STEP for index in range(count)]


def verify_rows(
    rows: Sequence[Mapping[str, Any]],
    pair: str,
    *,
    allow_post_boundary_overshoot: bool,
) -> dict[str, Any]:
    if pair not in PAIR_ORDER:
        raise C3AContractGuardError(f"unexpected pair: {pair}")
    if not rows:
        raise C3AContractGuardError(f"no candles for {pair}")
    dates = [_timestamp(row.get("date")) for row in rows]
    if dates != sorted(dates):
        raise C3AContractGuardError(f"unordered candles for {pair}")
    if len(set(dates)) != len(dates):
        raise C3AContractGuardError(f"duplicate candles for {pair}")

    retained = [date for date in dates if date < BOUNDARY]
    expected = _expected_timestamps()
    if retained != expected:
        missing = sorted(set(expected) - set(retained))
        unexpected = sorted(set(retained) - set(expected))
        detail = []
        if missing:
            detail.append(f"first_missing={missing[0].isoformat()}")
        if unexpected:
            detail.append(f"first_unexpected={unexpected[0].isoformat()}")
        raise C3AContractGuardError(
            f"{pair} full retained four-hour sequence mismatch"
            + (": " + ", ".join(detail) if detail else "")
        )
    if not allow_post_boundary_overshoot and len(dates) != len(retained):
        raise C3AContractGuardError(f"post-boundary candle remains for {pair}")
    if not allow_post_boundary_overshoot and dates[-1] != BOUNDARY - STEP:
        raise C3AContractGuardError(f"{pair} does not end at the sealed boundary")

    startup_bars = sum(date < FIRST_SCREEN for date in retained)
    if startup_bars < 450:
        raise C3AContractGuardError(f"{pair} has only {startup_bars} startup bars")
    timestamp_digest = hashlib.sha256(
        "\n".join(date.isoformat() for date in retained).encode("utf-8")
    ).hexdigest()
    return {
        "pair": pair,
        "rows_observed": len(rows),
        "retained_rows": len(retained),
        "post_boundary_rows": len(dates) - len(retained),
        "retained_earliest": retained[0].isoformat(),
        "retained_latest": retained[-1].isoformat(),
        "startup_bars": startup_bars,
        "retained_timestamp_sha256": timestamp_digest,
        "status": "PASS",
    }


def build_report(mode: str, source_sha: str) -> dict[str, Any]:
    config = load_and_verify_config()
    allow_overshoot = mode == "precheck"
    cells: list[dict[str, Any]] = []
    for pair in PAIR_ORDER:
        path = discover_candle_file(DATA_DIR, pair, "4h")
        cell = verify_rows(load_candles(path), pair, allow_post_boundary_overshoot=allow_overshoot)
        cell["path"] = str(path.relative_to(IMPL))
        cell["sha256"] = _sha256_file(path)
        cells.append(cell)
    sequence_hashes = {cell["retained_timestamp_sha256"] for cell in cells}
    if len(sequence_hashes) != 1:
        raise C3AContractGuardError("BTC/ETH/SOL retained timestamp sequences differ")
    return {
        "schema_version": 1,
        "stage": "C3A",
        "mode": mode,
        "status": "PASS",
        "source_head_sha": source_sha,
        "config_canonical_sha256": EXPECTED_CONFIG_CANONICAL_SHA256,
        "download_start": DOWNLOAD_START.isoformat(),
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
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
            "stage": "C3A",
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
    print(f"C3A contract guard {args.mode} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
