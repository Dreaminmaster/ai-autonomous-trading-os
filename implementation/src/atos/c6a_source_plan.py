"""Frozen first-capture plan for official public C6A objects.

A plan contains exact official OKX HTTPS resources and coverage but deliberately
contains no pre-observed content hash.  The guarded first-capture step records
the object bytes once, computes SHA-256, and emits the immutable source manifest
consumed by all later stages.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlparse

from atos.c6a_contract import (
    C6AError,
    ECONOMIC_BOUNDARY,
    SPOT_INSTRUMENTS,
    SWAP_INSTRUMENTS,
    parse_timestamp,
)
from atos.c6a_data import DOWNLOAD_START
from atos.c6a_sources import ALLOWED_KINDS, required_pairs

PROHIBITED_QUERY_KEYS = {
    "apikey",
    "api_key",
    "secret",
    "passphrase",
    "signature",
    "sign",
    "token",
    "authorization",
}


@dataclass(frozen=True)
class PublicSourcePlanEntry:
    source_id: str
    kind: str
    instrument: str
    url: str
    coverage_start: datetime
    coverage_end_exclusive: datetime
    content_type: str
    archive_member: str | None = None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "PublicSourcePlanEntry":
        result = cls(
            source_id=str(row.get("source_id", "")),
            kind=str(row.get("kind", "")),
            instrument=str(row.get("instrument", "")),
            url=str(row.get("url", "")),
            coverage_start=parse_timestamp(row.get("coverage_start")),
            coverage_end_exclusive=parse_timestamp(row.get("coverage_end_exclusive")),
            content_type=str(row.get("content_type", "")),
            archive_member=(
                None
                if row.get("archive_member") in (None, "")
                else str(row.get("archive_member"))
            ),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if not self.source_id or self.kind not in ALLOWED_KINDS:
            raise C6AError("invalid C6A public source-plan identity or kind")
        parsed = urlparse(self.url)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            hostname == "okx.com" or hostname.endswith(".okx.com")
        ):
            raise C6AError("C6A source-plan URL must be HTTPS on an OKX domain")
        if parsed.username or parsed.password or parsed.fragment:
            raise C6AError("C6A source-plan URL contains credentials or a fragment")
        query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        if query_keys & PROHIBITED_QUERY_KEYS:
            raise C6AError("C6A source-plan URL contains a prohibited credential query")
        if self.coverage_start < DOWNLOAD_START:
            raise C6AError("C6A source plan begins before the frozen download start")
        if self.coverage_end_exclusive > ECONOMIC_BOUNDARY:
            raise C6AError("C6A source plan reaches the closed economic boundary")
        if self.coverage_end_exclusive <= self.coverage_start:
            raise C6AError("C6A source-plan coverage interval is invalid")
        expected = {
            "spot_trade_candles": set(SPOT_INSTRUMENTS),
            "swap_trade_candles": set(SWAP_INSTRUMENTS),
            "swap_mark_candles": set(SWAP_INSTRUMENTS),
            "funding_history": set(SWAP_INSTRUMENTS),
            "instrument_metadata": set((*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS)),
        }[self.kind]
        if self.instrument not in expected:
            raise C6AError(
                f"instrument is invalid for C6A source-plan kind {self.kind}"
            )
        if not self.content_type:
            raise C6AError("C6A source-plan content type is required")

    def manifest_fields(self, *, sha256: str) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "kind": self.kind,
            "instrument": self.instrument,
            "url": self.url,
            "sha256": sha256,
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end_exclusive": self.coverage_end_exclusive.isoformat(),
            "content_type": self.content_type,
            "archive_member": self.archive_member,
        }


def validate_source_plan(payload: Mapping[str, Any]) -> tuple[PublicSourcePlanEntry, ...]:
    if payload.get("schema_version") != 1 or payload.get("stage") != "C6A":
        raise C6AError("C6A source-plan identity drift")
    if payload.get("authenticated") is not False:
        raise C6AError("C6A source plan must explicitly forbid authentication")
    if payload.get("economic_boundary_exclusive") != "2025-12-29T00:00:00Z":
        raise C6AError("C6A source-plan boundary drift")
    rows = payload.get("sources")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise C6AError("C6A source plan has no sources")
    entries = tuple(PublicSourcePlanEntry.from_mapping(row) for row in rows)
    source_ids = [row.source_id for row in entries]
    if len(source_ids) != len(set(source_ids)):
        raise C6AError("duplicate C6A source-plan ID")
    keys = [
        (row.kind, row.instrument, row.coverage_start, row.coverage_end_exclusive)
        for row in entries
    ]
    if len(keys) != len(set(keys)):
        raise C6AError("duplicate C6A source-plan coverage key")
    observed = {(row.kind, row.instrument) for row in entries}
    missing = sorted(required_pairs() - observed)
    if missing:
        raise C6AError(f"C6A source plan missing primitive pairs: {missing}")
    for kind, instrument in sorted(required_pairs()):
        intervals = sorted(
            (
                (row.coverage_start, row.coverage_end_exclusive)
                for row in entries
                if row.kind == kind and row.instrument == instrument
            ),
            key=lambda value: value[0],
        )
        if intervals[0][0] != DOWNLOAD_START or intervals[-1][1] != ECONOMIC_BOUNDARY:
            raise C6AError(f"incomplete C6A source-plan coverage: {kind}/{instrument}")
        previous_end = intervals[0][0]
        for start, end in intervals:
            if start != previous_end:
                relation = "overlap" if start < previous_end else "gap"
                raise C6AError(
                    f"{relation} in C6A source-plan coverage: {kind}/{instrument}"
                )
            previous_end = end
    return entries
