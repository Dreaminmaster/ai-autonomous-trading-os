"""Exact parsers for the five directly bound OKX transition notices.

The parser verifies the official page text against preregistered windows and
contract-step values.  It does not infer unchanged contract fields; those must
come from independently retained instrument-metadata responses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

from atos.c6a_source_authority import SourceAuthorityError


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


@dataclass(frozen=True)
class NoticeSpec:
    request_id: str
    instrument: str
    pair_text: str
    window_start: str
    window_end_exclusive: str
    old_step: str
    new_step: str
    title_terms: tuple[str, ...]
    publication_date: str
    final_authority: bool = True


NOTICE_SPECS = {
    "known-transition-eth-2024-04-18": NoticeSpec(
        request_id="known-transition-eth-2024-04-18",
        instrument="ETH-USDT-SWAP",
        pair_text="ETH/USDT",
        window_start="2024-04-18T06:00:00Z",
        window_end_exclusive="2024-04-18T08:00:00Z",
        old_step="1",
        new_step="0.1",
        title_terms=("adjust", "minimum order quantities", "futures"),
        publication_date="2024-04-12",
    ),
    "known-transition-btc-2024-04-25": NoticeSpec(
        request_id="known-transition-btc-2024-04-25",
        instrument="BTC-USDT-SWAP",
        pair_text="BTC/USDT",
        window_start="2024-04-25T06:00:00Z",
        window_end_exclusive="2024-04-25T08:00:00Z",
        old_step="1",
        new_step="0.1",
        title_terms=("adjust", "minimum order quantities", "futures"),
        publication_date="2024-04-19",
    ),
    "known-transition-eth-original-2024-12-18": NoticeSpec(
        request_id="known-transition-eth-original-2024-12-18",
        instrument="ETH-USDT-SWAP",
        pair_text="ETH/USDT",
        window_start="2024-12-18T06:00:00Z",
        window_end_exclusive="2024-12-18T08:00:00Z",
        old_step="0.1",
        new_step="0.01",
        title_terms=("adjust", "minimum order quantities", "ethusdt"),
        publication_date="2024-12-11",
        final_authority=False,
    ),
    "known-transition-eth-postponed-2025-01-09": NoticeSpec(
        request_id="known-transition-eth-postponed-2025-01-09",
        instrument="ETH-USDT-SWAP",
        pair_text="ETH/USDT",
        window_start="2025-01-09T06:00:00Z",
        window_end_exclusive="2025-01-09T10:00:00Z",
        old_step="0.1",
        new_step="0.01",
        title_terms=("postpone", "minimum order quantities", "ethusdt"),
        publication_date="2024-12-16",
    ),
    "known-transition-btc-2025-01-22": NoticeSpec(
        request_id="known-transition-btc-2025-01-22",
        instrument="BTC-USDT-SWAP",
        pair_text="BTC/USDT",
        window_start="2025-01-22T06:00:00Z",
        window_end_exclusive="2025-01-22T08:00:00Z",
        old_step="0.1",
        new_step="0.01",
        title_terms=("adjust", "minimum order quantities", "spots and futures"),
        publication_date="2025-01-17",
    ),
}


def html_visible_text(data: bytes) -> str:
    try:
        html = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceAuthorityError("announcement article is not UTF-8") from exc
    parser = _TextParser()
    parser.feed(html)
    text = " ".join(parser.parts)
    return re.sub(r"\s+", " ", text).strip()


def _month_name(timestamp: str) -> str:
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    return value.strftime("%B %-d, %Y")


def _time_text(timestamp: str) -> tuple[int, int]:
    value = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    return value.hour, value.minute


def _window_patterns(spec: NoticeSpec) -> tuple[re.Pattern[str], ...]:
    start_hour, start_minute = _time_text(spec.window_start)
    end_hour, end_minute = _time_text(spec.window_end_exclusive)
    date_text = re.escape(_month_name(spec.window_start))
    start = rf"{start_hour}:{start_minute:02d}\s*(?:am|AM)?"
    end = rf"{end_hour}:{end_minute:02d}\s*(?:am|AM)?"
    return (
        re.compile(rf"{start}\s*[-–~]\s*{end}\s*UTC\s*on\s*{date_text}", re.I),
        re.compile(rf"{start}\s*[-–~]\s*{end}\s*(?:am|AM)?\s*UTC\s*on\s*{date_text}", re.I),
        re.compile(rf"{date_text}.{{0,80}}{start}\s*[-–~]\s*{end}.{{0,20}}UTC", re.I),
    )


def _published_pattern(spec: NoticeSpec) -> re.Pattern[str]:
    date = datetime.fromisoformat(spec.publication_date).replace(tzinfo=timezone.utc)
    month_first = re.escape(date.strftime("%b %-d, %Y"))
    long_month = re.escape(date.strftime("%B %-d, %Y"))
    day_first = re.escape(date.strftime("%-d %b %Y"))
    return re.compile(rf"(?:Published\s+on\s+)?(?:{month_first}|{long_month}|{day_first})", re.I)


def _row_pattern(spec: NoticeSpec) -> re.Pattern[str]:
    pair = re.escape(spec.pair_text)
    old = re.escape(spec.old_step)
    new = re.escape(spec.new_step)
    # Tables may contain coin-equivalent columns between the two contract-step values.
    return re.compile(
        rf"Perpetual\s+{pair}\s+{old}(?:\s+[0-9]+(?:\.[0-9]+)?){{0,2}}\s+{new}(?:\s+[0-9]+(?:\.[0-9]+)?)?",
        re.I,
    )


def parse_known_transition_notice(data: bytes, *, request_id: str, source_id: str) -> dict[str, Any]:
    spec = NOTICE_SPECS.get(request_id)
    if spec is None:
        raise SourceAuthorityError("announcement request is not a frozen transition notice")
    if not source_id:
        raise SourceAuthorityError("transition notice source ID is required")
    text = html_visible_text(data)
    normalized = text.casefold()
    missing_title_terms = [term for term in spec.title_terms if term.casefold() not in normalized]
    if missing_title_terms:
        raise SourceAuthorityError(f"transition notice title terms missing: {missing_title_terms}")
    if not _published_pattern(spec).search(text):
        raise SourceAuthorityError("transition notice publication date is unproven")
    if not any(pattern.search(text) for pattern in _window_patterns(spec)):
        raise SourceAuthorityError("transition notice UTC window is unproven")
    if not _row_pattern(spec).search(text):
        raise SourceAuthorityError("transition notice old/new contract steps are unproven")
    return {
        "request_id": request_id,
        "source_id": source_id,
        "instrument": spec.instrument,
        "window_start": spec.window_start,
        "window_end_exclusive": spec.window_end_exclusive,
        "old_lot": spec.old_step,
        "new_lot": spec.new_step,
        "old_min": spec.old_step,
        "new_min": spec.new_step,
        "publication_date": spec.publication_date,
        "final_authority": spec.final_authority,
        "status": "PASS",
    }


def final_transition_notice_proofs(notices: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    final = [notice for notice in notices if notice.get("final_authority") is True]
    identities = {
        (
            str(notice.get("instrument")),
            str(notice.get("window_start")),
            str(notice.get("window_end_exclusive")),
        )
        for notice in final
    }
    expected = {
        (spec.instrument, spec.window_start, spec.window_end_exclusive)
        for spec in NOTICE_SPECS.values()
        if spec.final_authority
    }
    if identities != expected or len(final) != len(expected):
        raise SourceAuthorityError("final transition notice set is incomplete or duplicated")
    return tuple(sorted(final, key=lambda row: (row["window_start"], row["instrument"])))
