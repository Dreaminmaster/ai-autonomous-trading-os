#!/usr/bin/env python3
"""Deterministically capture historical OKX public candle series.

This module supports only the two frozen unauthenticated market endpoints used
for C6A trade and mark candles.  It pages backward from the exclusive economic
boundary, retains every request URL and raw-response SHA-256, rejects conflicting
or incomplete rows, and publishes one exact hourly JSONL object per series.
No account, order, private, current-state, or funding endpoint is accepted.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from atos.c6a_contract import C6AError, parse_timestamp
from atos.c6a_data import validate_mark_candles, validate_trade_candles
from atos.c6a_evidence import sha256_file
from scripts.c6a_prepare_public_data import normalize_candle

TRADE_ENDPOINT = "https://www.okx.com/api/v5/market/history-candles"
MARK_ENDPOINT = "https://www.okx.com/api/v5/market/history-mark-price-candles"
ALLOWED_ENDPOINTS = {TRADE_ENDPOINT, MARK_ENDPOINT}
MAX_PAGES = 1000


class C6APublicApiCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandleApiPlan:
    source_id: str
    kind: str
    instrument: str
    endpoint: str
    start: datetime
    end_exclusive: datetime
    bar: str = "1H"
    limit: int = 100

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "CandleApiPlan":
        result = cls(
            source_id=str(row.get("source_id", "")),
            kind=str(row.get("kind", "")),
            instrument=str(row.get("instrument", "")),
            endpoint=str(row.get("endpoint", "")),
            start=parse_timestamp(row.get("coverage_start")),
            end_exclusive=parse_timestamp(row.get("coverage_end_exclusive")),
            bar=str(row.get("bar", "1H")),
            limit=int(row.get("limit", 100)),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if not self.source_id or self.kind not in {
            "spot_trade_candles",
            "swap_trade_candles",
            "swap_mark_candles",
        }:
            raise C6APublicApiCaptureError("invalid C6A candle API source identity")
        expected_endpoint = (
            MARK_ENDPOINT if self.kind == "swap_mark_candles" else TRADE_ENDPOINT
        )
        if self.endpoint != expected_endpoint or self.endpoint not in ALLOWED_ENDPOINTS:
            raise C6APublicApiCaptureError(
                f"invalid endpoint for C6A candle kind {self.kind}"
            )
        if self.bar != "1H" or not 1 <= self.limit <= 100:
            raise C6APublicApiCaptureError("C6A candle API bar/limit drift")
        if self.end_exclusive <= self.start:
            raise C6APublicApiCaptureError("C6A candle API coverage is invalid")

    @property
    def mark(self) -> bool:
        return self.kind == "swap_mark_candles"


def _milliseconds(timestamp: datetime) -> int:
    return int(timestamp.timestamp() * 1000)


def request_url(plan: CandleApiPlan, *, after: int) -> str:
    query = urllib.parse.urlencode(
        {
            "instId": plan.instrument,
            "after": str(after),
            "bar": plan.bar,
            "limit": str(plan.limit),
        }
    )
    return f"{plan.endpoint}?{query}"


def _open(url: str):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ai-autonomous-trading-os-c6a-public-api/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )
    return urllib.request.urlopen(request, timeout=120)  # noqa: S310 - exact allowed endpoints


def _parse_response(raw: bytes, *, url: str) -> list[Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise C6APublicApiCaptureError(
            f"invalid OKX public API response for {url}: {exc}"
        ) from exc
    if not isinstance(payload, Mapping) or str(payload.get("code")) != "0":
        raise C6APublicApiCaptureError(
            f"OKX public API returned non-success payload for {url}"
        )
    data = payload.get("data")
    if not isinstance(data, list):
        raise C6APublicApiCaptureError(
            f"OKX public API data is not a list for {url}"
        )
    return data


def capture_series(
    plan: CandleApiPlan,
    *,
    destination: Path,
    opener: Callable[[str], Any] = _open,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    plan.validate()
    if destination.exists():
        raise C6APublicApiCaptureError(
            f"refusing to overwrite C6A public API series: {destination}"
        )
    start_ms = _milliseconds(plan.start)
    cursor = _milliseconds(plan.end_exclusive)
    rows_by_timestamp: dict[int, dict[str, Any]] = {}
    pages: list[dict[str, Any]] = []
    for page_number in range(1, MAX_PAGES + 1):
        url = request_url(plan, after=cursor)
        try:
            with opener(url) as response:
                raw = response.read()
        except Exception as exc:
            raise C6APublicApiCaptureError(
                f"unable to read OKX public API page {page_number}: {exc}"
            ) from exc
        if not raw:
            raise C6APublicApiCaptureError(
                f"empty OKX public API response at page {page_number}"
            )
        data = _parse_response(raw, url=url)
        if not data:
            raise C6APublicApiCaptureError(
                f"OKX public API exhausted before frozen start at page {page_number}"
            )
        normalized_page: list[tuple[int, dict[str, Any]]] = []
        for raw_row in data:
            normalized = normalize_candle(raw_row, mark=plan.mark)
            timestamp = _milliseconds(parse_timestamp(normalized["timestamp"]))
            normalized_page.append((timestamp, normalized))
            if timestamp >= _milliseconds(plan.end_exclusive):
                continue
            if timestamp < start_ms:
                continue
            existing = rows_by_timestamp.get(timestamp)
            if existing is not None and existing != normalized:
                raise C6APublicApiCaptureError(
                    f"conflicting duplicate public candle: {timestamp}"
                )
            rows_by_timestamp[timestamp] = normalized
        page_timestamps = [timestamp for timestamp, _ in normalized_page]
        if not page_timestamps:
            raise C6APublicApiCaptureError(
                f"OKX public API page contains no timestamped rows: {page_number}"
            )
        minimum = min(page_timestamps)
        maximum = max(page_timestamps)
        if minimum >= cursor:
            raise C6APublicApiCaptureError(
                f"OKX public API pagination did not advance at page {page_number}"
            )
        pages.append(
            {
                "page": page_number,
                "request_url": url,
                "response_size": len(raw),
                "response_sha256": hashlib.sha256(raw).hexdigest(),
                "row_count": len(data),
                "minimum_timestamp": minimum,
                "maximum_timestamp": maximum,
            }
        )
        cursor = minimum
        if minimum <= start_ms:
            break
        sleep(0.11)
    else:
        raise C6APublicApiCaptureError("C6A public API exceeded maximum page count")

    canonical = [rows_by_timestamp[key] for key in sorted(rows_by_timestamp)]
    try:
        validated = (
            validate_mark_candles(
                canonical,
                instrument=plan.instrument,
                start=plan.start,
                end=plan.end_exclusive,
            )
            if plan.mark
            else validate_trade_candles(
                canonical,
                instrument=plan.instrument,
                start=plan.start,
                end=plan.end_exclusive,
            )
        )
    except C6AError as exc:
        raise C6APublicApiCaptureError(str(exc)) from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in canonical:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    temporary.replace(destination)
    return {
        "source_id": plan.source_id,
        "kind": plan.kind,
        "instrument": plan.instrument,
        "url": plan.endpoint,
        "path": str(destination),
        "size": destination.stat().st_size,
        "sha256": sha256_file(destination),
        "coverage_start": plan.start.isoformat(),
        "coverage_end_exclusive": plan.end_exclusive.isoformat(),
        "content_type": "application/x-ndjson",
        "row_count": len(validated),
        "page_count": len(pages),
        "pages": pages,
        "authenticated": False,
        "status": "PASS",
    }
