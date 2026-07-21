#!/usr/bin/env python3
"""Download only the public OKX series preregistered for C5A.

This script has no credential, account, order, position, or private-API path.
It writes raw public responses for the boundary guard to seal before research.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

IMPL = Path(__file__).resolve().parents[1]
CONFIG_PATH = IMPL / "config/c5a_derivatives_crowding_regime.json"
RAW_ROOT = IMPL / "freqtrade_data/c5a_public_input/raw"
API_ROOT = "https://www.okx.com"
STEP = timedelta(hours=4)


class C5ADownloadError(RuntimeError):
    pass


def _timestamp_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    parsed = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return int(parsed.timestamp() * 1000)


def _iso(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC).isoformat()


def _request(path: str, params: Mapping[str, Any], *, attempts: int = 5) -> list[list[str]]:
    url = API_ROOT + path + "?" + urllib.parse.urlencode(params)
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "ai-autonomous-trading-os-c5a-public-research/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, Mapping) or str(payload.get("code")) != "0":
                raise C5ADownloadError(f"OKX public API error: {payload!r}")
            data = payload.get("data")
            if not isinstance(data, list):
                raise C5ADownloadError("OKX public API data is not a list")
            return data
        except Exception as exc:  # network retry boundary
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise C5ADownloadError(f"OKX public request failed: {last}") from last


def _normalize_trade(row: list[str], *, include_ohlc: bool) -> dict[str, Any]:
    if len(row) < 9:
        raise C5ADownloadError(f"unexpected OKX candle row: {row!r}")
    if str(row[8]) != "1":
        raise C5ADownloadError("incomplete candle returned by history endpoint")
    output: dict[str, Any] = {
        "date": _iso(int(row[0])),
        "quote_volume": float(row[7]),
    }
    if include_ohlc:
        output.update(
            {
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
            }
        )
    return output


def _normalize_mark(row: list[str]) -> dict[str, Any]:
    if len(row) < 6:
        raise C5ADownloadError(f"unexpected OKX mark candle row: {row!r}")
    if str(row[5]) != "1":
        raise C5ADownloadError("incomplete mark candle returned by history endpoint")
    return {"date": _iso(int(row[0])), "close": float(row[4])}


def download_series(
    *,
    endpoint: str,
    instrument: str,
    start_ms: int,
    boundary_ms: int,
    include_ohlc: bool = False,
    mark: bool = False,
) -> list[dict[str, Any]]:
    # Start one completed interval beyond the exclusive boundary so an API
    # boundary row, if returned, is retained in raw evidence and removed later.
    cursor = boundary_ms + int(STEP.total_seconds() * 1000)
    by_timestamp: dict[int, dict[str, Any]] = {}
    previous_oldest: int | None = None
    while True:
        page = _request(
            endpoint,
            {"instId": instrument, "bar": "4H", "after": str(cursor), "limit": "100"},
        )
        if not page:
            break
        timestamps = [int(row[0]) for row in page]
        if len(set(timestamps)) != len(timestamps):
            raise C5ADownloadError(f"duplicate timestamp within page: {instrument}")
        for row in page:
            timestamp = int(row[0])
            normalized = _normalize_mark(row) if mark else _normalize_trade(
                row, include_ohlc=include_ohlc
            )
            existing = by_timestamp.get(timestamp)
            if existing is not None and existing != normalized:
                raise C5ADownloadError(f"conflicting duplicate candle: {instrument}")
            by_timestamp[timestamp] = normalized
        oldest = min(timestamps)
        if previous_oldest is not None and oldest >= previous_oldest:
            raise C5ADownloadError(f"pagination made no backward progress: {instrument}")
        previous_oldest = oldest
        if oldest <= start_ms:
            break
        cursor = oldest
        time.sleep(0.12)
    retained = [
        row
        for timestamp, row in sorted(by_timestamp.items())
        if timestamp >= start_ms
    ]
    if not retained:
        raise C5ADownloadError(f"no public data downloaded: {instrument}")
    return retained


def _write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sleep", type=float, default=0.0)
    args = parser.parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    start_ms = _timestamp_ms(config["download_start"])
    boundary_ms = _timestamp_ms(config["economic_boundary_exclusive"])
    for spot in config["spot_instruments"]:
        rows = download_series(
            endpoint="/api/v5/market/history-candles",
            instrument=spot,
            start_ms=start_ms,
            boundary_ms=boundary_ms,
            include_ohlc=True,
        )
        _write(RAW_ROOT / "spot" / f"{spot}.json", rows)
        if args.sleep:
            time.sleep(args.sleep)
    for swap in config["swap_instruments"]:
        rows = download_series(
            endpoint="/api/v5/market/history-candles",
            instrument=swap,
            start_ms=start_ms,
            boundary_ms=boundary_ms,
            include_ohlc=False,
        )
        _write(RAW_ROOT / "swap" / f"{swap}.json", rows)
        if args.sleep:
            time.sleep(args.sleep)
        rows = download_series(
            endpoint="/api/v5/market/history-mark-price-candles",
            instrument=swap,
            start_ms=start_ms,
            boundary_ms=boundary_ms,
            mark=True,
        )
        _write(RAW_ROOT / "mark" / f"{swap}.json", rows)
        if args.sleep:
            time.sleep(args.sleep)
    print("C5A public download complete: 3 spot + 3 swap-volume + 3 mark-price series")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
