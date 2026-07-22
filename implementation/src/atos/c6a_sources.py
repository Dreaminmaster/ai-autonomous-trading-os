"""C6A public-source manifest validation.

Only unauthenticated OKX public/archive resources are permitted.  A manifest
binds every downloaded object to exact coverage and SHA-256 before research
read.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from atos.c6a_contract import (
    C6AError,
    ECONOMIC_BOUNDARY,
    SPOT_INSTRUMENTS,
    SWAP_INSTRUMENTS,
    parse_timestamp,
)
from atos.c6a_data import DOWNLOAD_START

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_KINDS = {
    "spot_trade_candles",
    "swap_trade_candles",
    "swap_mark_candles",
    "funding_history",
    "instrument_metadata",
}


def required_pairs() -> set[tuple[str, str]]:
    return {
        *(("spot_trade_candles", instrument) for instrument in SPOT_INSTRUMENTS),
        *(("swap_trade_candles", instrument) for instrument in SWAP_INSTRUMENTS),
        *(("swap_mark_candles", instrument) for instrument in SWAP_INSTRUMENTS),
        *(("funding_history", instrument) for instrument in SWAP_INSTRUMENTS),
        *(("instrument_metadata", instrument) for instrument in (*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS)),
    }


@dataclass(frozen=True)
class PublicSourceEntry:
    source_id: str
    kind: str
    instrument: str
    url: str
    sha256: str
    coverage_start: datetime
    coverage_end_exclusive: datetime
    content_type: str
    archive_member: str | None = None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "PublicSourceEntry":
        entry = cls(
            source_id=str(row.get("source_id", "")),
            kind=str(row.get("kind", "")),
            instrument=str(row.get("instrument", "")),
            url=str(row.get("url", "")),
            sha256=str(row.get("sha256", "")),
            coverage_start=parse_timestamp(row.get("coverage_start")),
            coverage_end_exclusive=parse_timestamp(row.get("coverage_end_exclusive")),
            content_type=str(row.get("content_type", "")),
            archive_member=(
                None if row.get("archive_member") in (None, "") else str(row["archive_member"])
            ),
        )
        entry.validate()
        return entry

    def validate(self) -> None:
        if not self.source_id or self.kind not in ALLOWED_KINDS:
            raise C6AError("invalid public source identity or kind")
        parsed = urlparse(self.url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            hostname == "okx.com" or hostname.endswith(".okx.com")
        ):
            raise C6AError("C6A source URL must be HTTPS on an OKX domain")
        if parsed.username or parsed.password or parsed.fragment:
            raise C6AError("C6A source URL contains prohibited credentials or fragment")
        if not SHA256_RE.fullmatch(self.sha256):
            raise C6AError("C6A source SHA-256 is invalid")
        if self.coverage_start < DOWNLOAD_START:
            raise C6AError("C6A source begins before the frozen download start")
        if self.coverage_end_exclusive > ECONOMIC_BOUNDARY:
            raise C6AError("C6A source reaches the closed economic boundary")
        if self.coverage_end_exclusive <= self.coverage_start:
            raise C6AError("C6A source coverage interval is invalid")
        expected_instruments = {
            "spot_trade_candles": set(SPOT_INSTRUMENTS),
            "swap_trade_candles": set(SWAP_INSTRUMENTS),
            "swap_mark_candles": set(SWAP_INSTRUMENTS),
            "funding_history": set(SWAP_INSTRUMENTS),
            "instrument_metadata": set((*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS)),
        }[self.kind]
        if self.instrument not in expected_instruments:
            raise C6AError(f"instrument is invalid for source kind {self.kind}")
        if not self.content_type:
            raise C6AError("C6A source content type is required")


def coverage_intervals(
    entries: Sequence[PublicSourceEntry], *, kind: str, instrument: str
) -> tuple[tuple[datetime, datetime], ...]:
    selected = sorted(
        (
            (entry.coverage_start, entry.coverage_end_exclusive)
            for entry in entries
            if entry.kind == kind and entry.instrument == instrument
        ),
        key=lambda value: value[0],
    )
    if not selected:
        raise C6AError(f"missing source coverage: {kind}/{instrument}")
    previous_end: datetime | None = None
    for start, end in selected:
        if previous_end is not None:
            if start < previous_end:
                raise C6AError(f"overlapping source coverage: {kind}/{instrument}")
            if start > previous_end:
                raise C6AError(
                    f"gap in source coverage: {kind}/{instrument} "
                    f"{previous_end.isoformat()} -> {start.isoformat()}"
                )
        previous_end = end
    return tuple(selected)


def require_complete_coverage(
    entries: Sequence[PublicSourceEntry],
    *,
    start: datetime = DOWNLOAD_START,
    end: datetime = ECONOMIC_BOUNDARY,
) -> dict[str, Any]:
    required_start = parse_timestamp(start)
    required_end = parse_timestamp(end)
    rows: list[dict[str, Any]] = []
    for kind, instrument in sorted(required_pairs()):
        intervals = coverage_intervals(entries, kind=kind, instrument=instrument)
        if intervals[0][0] != required_start or intervals[-1][1] != required_end:
            raise C6AError(
                f"incomplete source coverage: {kind}/{instrument} "
                f"{intervals[0][0].isoformat()}..{intervals[-1][1].isoformat()}"
            )
        rows.append(
            {
                "kind": kind,
                "instrument": instrument,
                "coverage_start": required_start.isoformat(),
                "coverage_end_exclusive": required_end.isoformat(),
                "object_count": len(intervals),
                "status": "PASS",
            }
        )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "pair_count": len(rows),
        "coverage_start": required_start.isoformat(),
        "coverage_end_exclusive": required_end.isoformat(),
        "pairs": rows,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "live": "FORBIDDEN",
    }


def validate_source_manifest(payload: Mapping[str, Any]) -> tuple[PublicSourceEntry, ...]:
    if payload.get("schema_version") != 1 or payload.get("stage") != "C6A":
        raise C6AError("C6A source manifest identity drift")
    if payload.get("authenticated") is not False:
        raise C6AError("C6A source manifest must explicitly forbid authentication")
    if payload.get("economic_boundary_exclusive") != "2025-12-29T00:00:00Z":
        raise C6AError("C6A source manifest boundary drift")
    rows = payload.get("sources")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise C6AError("C6A source manifest has no sources")
    entries = tuple(PublicSourceEntry.from_mapping(row) for row in rows)
    source_ids = [entry.source_id for entry in entries]
    if len(source_ids) != len(set(source_ids)):
        raise C6AError("duplicate C6A source ID")
    keys = [
        (entry.kind, entry.instrument, entry.coverage_start, entry.coverage_end_exclusive)
        for entry in entries
    ]
    if len(keys) != len(set(keys)):
        raise C6AError("duplicate C6A source coverage key")
    observed = {(entry.kind, entry.instrument) for entry in entries}
    missing = sorted(required_pairs() - observed)
    if missing:
        raise C6AError(f"C6A source manifest missing primitive pairs: {missing}")
    require_complete_coverage(entries)
    return entries
