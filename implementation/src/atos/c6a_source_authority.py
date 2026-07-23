"""Fail-closed primitives for the C6A historical metadata source-authority gate.

This module intentionally contains no candle, funding, portfolio, strategy, or
return logic.  It validates only pre-economic source plans, immutable source
records, exact-decimal metadata states, transition-safe intersections, and
continuous authority coverage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlparse


class SourceAuthorityError(ValueError):
    """Raised when source authority cannot be proven exactly."""


SCHEMA_VERSION = 1
STAGE = "C6A_SOURCE_AUTHORITY_GATE"
DESIGN_AUTHORITY_SHA = "26a7604c34c610562643d7a732d35b39df84c94f"
AUTHORITY_START_TEXT = "2023-06-05T00:00:00Z"
AUTHORITY_END_TEXT = "2025-12-29T00:00:00Z"
INSTRUMENTS = (
    "BTC-USDT",
    "ETH-USDT",
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
)
SPOT_INSTRUMENTS = frozenset({"BTC-USDT", "ETH-USDT"})
SWAP_INSTRUMENTS = frozenset({"BTC-USDT-SWAP", "ETH-USDT-SWAP"})
AUTHORITY_MODES = frozenset({"EXACT_EFFECTIVE_STATE", "TRANSITION_SAFE_INTERSECTION"})
AUTHORITY_CLASSES = frozenset(
    {
        "DIRECT_OFFICIAL_OKX_RESPONSE",
        "OFFICIAL_OKX_ANNOUNCEMENT",
        "EXACT_ARCHIVED_OFFICIAL_OKX_RESPONSE",
        "OFFICIAL_OKX_METADATA_DOWNLOAD",
    }
)
REQUEST_KINDS = frozenset(
    {
        "public_instruments",
        "announcement_catalog",
        "announcement_article",
        "official_metadata_download",
        "archive_lookup",
    }
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PROHIBITED_QUERY_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "secret",
        "passphrase",
        "signature",
        "sign",
        "token",
        "authorization",
    }
)
FORBIDDEN_ENDPOINT_MARKERS = (
    "/api/v5/market/history-candles",
    "/api/v5/market/history-mark-price-candles",
    "/api/v5/public/funding-rate-history",
    "/api/v5/trade/",
    "/api/v5/account/",
    "/api/v5/asset/",
    "/api/v5/broker/",
)
FAILURE_PRIORITY = (
    "FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED",
    "FAIL_FORBIDDEN_DATA_ACCESS",
    "FAIL_SOURCE_BYTES_MISSING",
    "FAIL_SOURCE_HASH_MISMATCH",
    "FAIL_SOURCE_NOT_OFFICIAL_OKX",
    "FAIL_ARCHIVE_DECODING_OR_PROVENANCE",
    "FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE",
    "FAIL_REQUIRED_FIELD_MISSING",
    "FAIL_INTERVAL_BOUNDARY_UNPROVEN",
    "FAIL_UNCOVERED_INTERVAL",
    "FAIL_AMBIGUOUS_OR_CONTRADICTORY_STATE",
    "FAIL_UNSUPPORTED_BACKWARD_PROJECTION",
    "FAIL_TRANSITION_WINDOW_UNPROVEN",
    "FAIL_TRANSITION_FIELDS_CHANGED",
    "FAIL_TRANSITION_INCREMENT_NOT_NESTED",
    "FAIL_TRANSITION_INTERSECTION_INVALID",
    "FAIL_NEW_UNFROZEN_TRANSITION",
    "FAIL_MANIFEST_INCOMPLETE",
    "FAIL_INDEPENDENT_REVIEW_MISMATCH",
)


def parse_utc_timestamp(value: Any) -> datetime:
    """Parse an explicit UTC timestamp without accepting naive local time."""

    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and value:
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            result = datetime.fromisoformat(text)
        except ValueError as exc:
            raise SourceAuthorityError(f"invalid UTC timestamp: {value!r}") from exc
    else:
        raise SourceAuthorityError("timestamp must be a non-empty ISO-8601 string")
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise SourceAuthorityError("timestamp must carry an explicit UTC offset")
    return result.astimezone(timezone.utc)


AUTHORITY_START = parse_utc_timestamp(AUTHORITY_START_TEXT)
AUTHORITY_END = parse_utc_timestamp(AUTHORITY_END_TEXT)


@dataclass(frozen=True)
class FrozenTransition:
    instrument: str
    start: datetime
    end: datetime
    old_step: str
    new_step: str


FROZEN_TRANSITIONS = (
    FrozenTransition(
        "ETH-USDT-SWAP",
        parse_utc_timestamp("2024-04-18T06:00:00Z"),
        parse_utc_timestamp("2024-04-18T08:00:00Z"),
        "1",
        "0.1",
    ),
    FrozenTransition(
        "BTC-USDT-SWAP",
        parse_utc_timestamp("2024-04-25T06:00:00Z"),
        parse_utc_timestamp("2024-04-25T08:00:00Z"),
        "1",
        "0.1",
    ),
    FrozenTransition(
        "ETH-USDT-SWAP",
        parse_utc_timestamp("2025-01-09T06:00:00Z"),
        parse_utc_timestamp("2025-01-09T10:00:00Z"),
        "0.1",
        "0.01",
    ),
    FrozenTransition(
        "BTC-USDT-SWAP",
        parse_utc_timestamp("2025-01-22T06:00:00Z"),
        parse_utc_timestamp("2025-01-22T08:00:00Z"),
        "0.1",
        "0.01",
    ),
)


def exact_decimal(value: Any, *, label: str, strictly_positive: bool = False) -> Decimal:
    """Parse the exact string form used by OKX without binary floating point."""

    if not isinstance(value, str) or not value or value != value.strip():
        raise SourceAuthorityError(f"{label} must be an exact non-empty decimal string")
    if "e" in value.lower():
        raise SourceAuthorityError(f"{label} must not use exponent notation")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise SourceAuthorityError(f"{label} is not an exact decimal") from exc
    if not result.is_finite() or result < 0:
        raise SourceAuthorityError(f"{label} must be finite and non-negative")
    if strictly_positive and result <= 0:
        raise SourceAuthorityError(f"{label} must be strictly positive")
    return result


def decimal_text(value: Decimal) -> str:
    """Return a canonical non-exponent decimal string."""

    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _is_okx_host(hostname: str) -> bool:
    hostname = hostname.lower()
    return hostname == "okx.com" or hostname.endswith(".okx.com")


def validate_url(
    url: str,
    *,
    request_kind: str,
    canonical_official_url: str | None = None,
) -> None:
    """Apply the pre-economic network allowlist and credential guard."""

    if request_kind not in REQUEST_KINDS:
        raise SourceAuthorityError("unsupported source-authority request kind")
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise SourceAuthorityError("source-authority URL must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise SourceAuthorityError("source-authority URL contains credentials or a fragment")
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_keys & PROHIBITED_QUERY_KEYS:
        raise SourceAuthorityError("source-authority URL contains a prohibited credential query")
    lowered_path = parsed.path.lower()
    if any(marker in lowered_path for marker in FORBIDDEN_ENDPOINT_MARKERS):
        raise SourceAuthorityError("forbidden economic or private endpoint")

    if request_kind == "archive_lookup":
        if not canonical_official_url:
            raise SourceAuthorityError("archive lookup requires a canonical official OKX URL")
        official = urlparse(canonical_official_url)
        if official.scheme != "https" or not official.hostname or not _is_okx_host(official.hostname):
            raise SourceAuthorityError("archive canonical URL must be an official OKX HTTPS URL")
        if any(marker in official.path.lower() for marker in FORBIDDEN_ENDPOINT_MARKERS):
            raise SourceAuthorityError("archive canonical URL points to forbidden economic data")
    elif not _is_okx_host(parsed.hostname):
        raise SourceAuthorityError("non-archive requests must target an official OKX domain")

    if request_kind == "public_instruments" and lowered_path != "/api/v5/public/instruments":
        raise SourceAuthorityError("public-instruments request path drift")


def validate_query_inventory(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Validate the committed, pre-network query inventory."""

    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("stage") != STAGE:
        raise SourceAuthorityError("query inventory identity drift")
    if payload.get("design_authority_sha") != DESIGN_AUTHORITY_SHA:
        raise SourceAuthorityError("query inventory design authority drift")
    if payload.get("authenticated") is not False:
        raise SourceAuthorityError("query inventory must explicitly forbid authentication")
    if payload.get("economic_endpoints_forbidden") is not True:
        raise SourceAuthorityError("query inventory must fail closed on economic endpoints")
    if payload.get("authority_start") != AUTHORITY_START_TEXT:
        raise SourceAuthorityError("query inventory authority start drift")
    if payload.get("authority_end_exclusive") != AUTHORITY_END_TEXT:
        raise SourceAuthorityError("query inventory authority end drift")
    instruments = payload.get("instruments")
    if not isinstance(instruments, list) or tuple(instruments) != INSTRUMENTS:
        raise SourceAuthorityError("query inventory instrument order or membership drift")
    rows = payload.get("requests")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or not rows:
        raise SourceAuthorityError("query inventory must contain at least one request")

    normalized: list[dict[str, Any]] = []
    request_ids: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise SourceAuthorityError("query inventory request must be an object")
        request_id = str(raw.get("request_id", ""))
        request_kind = str(raw.get("request_kind", ""))
        url = str(raw.get("url", ""))
        canonical = raw.get("canonical_official_url")
        canonical_text = None if canonical in (None, "") else str(canonical)
        if not request_id or request_id in request_ids:
            raise SourceAuthorityError("query inventory request IDs must be unique and non-empty")
        request_ids.add(request_id)
        if str(raw.get("method", "")) != "GET":
            raise SourceAuthorityError("source-authority requests must use GET")
        if not str(raw.get("expected_content_type", "")):
            raise SourceAuthorityError("query inventory request content type is required")
        validate_url(url, request_kind=request_kind, canonical_official_url=canonical_text)
        normalized.append(
            {
                "request_id": request_id,
                "request_kind": request_kind,
                "url": url,
                "canonical_official_url": canonical_text,
                "method": "GET",
                "expected_content_type": str(raw["expected_content_type"]),
            }
        )

    retry = payload.get("retry_policy")
    if not isinstance(retry, Mapping):
        raise SourceAuthorityError("query inventory retry policy is required")
    attempts = retry.get("max_attempts")
    timeout = retry.get("timeout_seconds")
    if type(attempts) is not int or not 1 <= attempts <= 5:
        raise SourceAuthorityError("query inventory max_attempts must be an integer from 1 to 5")
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise SourceAuthorityError("query inventory timeout_seconds must be an integer from 1 to 120")
    return tuple(normalized)


@dataclass(frozen=True)
class SourceObject:
    source_id: str
    authority_class: str
    canonical_official_url: str
    retrieval_url: str
    raw_sha256: str
    decoded_sha256: str
    raw_size: int
    decoded_size: int
    parser_version: str
    eligible: bool
    rejection_reason: str | None

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "SourceObject":
        result = cls(
            source_id=str(row.get("source_id", "")),
            authority_class=str(row.get("authority_class", "")),
            canonical_official_url=str(row.get("canonical_official_url", "")),
            retrieval_url=str(row.get("retrieval_url", "")),
            raw_sha256=str(row.get("raw_sha256", "")),
            decoded_sha256=str(row.get("decoded_sha256", "")),
            raw_size=row.get("raw_size"),
            decoded_size=row.get("decoded_size"),
            parser_version=str(row.get("parser_version", "")),
            eligible=row.get("eligible"),
            rejection_reason=(
                None if row.get("rejection_reason") in (None, "") else str(row["rejection_reason"])
            ),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if not self.source_id or self.authority_class not in AUTHORITY_CLASSES:
            raise SourceAuthorityError("invalid source object identity or authority class")
        official = urlparse(self.canonical_official_url)
        if official.scheme != "https" or not official.hostname or not _is_okx_host(official.hostname):
            raise SourceAuthorityError("source object canonical URL is not official OKX HTTPS")
        retrieval = urlparse(self.retrieval_url)
        if retrieval.scheme != "https" or not retrieval.hostname:
            raise SourceAuthorityError("source object retrieval URL must use HTTPS")
        if self.authority_class != "EXACT_ARCHIVED_OFFICIAL_OKX_RESPONSE" and not _is_okx_host(
            retrieval.hostname
        ):
            raise SourceAuthorityError("non-archive source retrieval must remain on an OKX domain")
        if not SHA256_RE.fullmatch(self.raw_sha256) or not SHA256_RE.fullmatch(
            self.decoded_sha256
        ):
            raise SourceAuthorityError("source object SHA-256 is invalid")
        if type(self.raw_size) is not int or self.raw_size <= 0:
            raise SourceAuthorityError("source object raw size must be a positive integer")
        if type(self.decoded_size) is not int or self.decoded_size <= 0:
            raise SourceAuthorityError("source object decoded size must be a positive integer")
        if not self.parser_version:
            raise SourceAuthorityError("source object parser version is required")
        if type(self.eligible) is not bool:
            raise SourceAuthorityError("source object eligibility must be boolean")
        if self.eligible and self.rejection_reason is not None:
            raise SourceAuthorityError("eligible source object cannot carry a rejection reason")
        if not self.eligible and self.rejection_reason is None:
            raise SourceAuthorityError("ineligible source object requires a rejection reason")


@dataclass(frozen=True)
class MetadataState:
    state_id: str
    instrument: str
    authority_mode: str
    inst_type: str
    base_ccy: str
    quote_ccy: str
    settle_ccy: str | None
    ct_val: str | None
    ct_val_ccy: str | None
    lot_sz: str
    min_sz: str
    tick_sz: str
    listing_state: str
    effective_from: datetime
    effective_to: datetime | None
    open_ended: bool
    source_ids: tuple[str, ...]
    contradiction: bool

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "MetadataState":
        effective_to_raw = row.get("effective_to")
        result = cls(
            state_id=str(row.get("state_id", "")),
            instrument=str(row.get("instrument", "")),
            authority_mode=str(row.get("authority_mode", "")),
            inst_type=str(row.get("inst_type", "")),
            base_ccy=str(row.get("base_ccy", "")),
            quote_ccy=str(row.get("quote_ccy", "")),
            settle_ccy=(None if row.get("settle_ccy") in (None, "") else str(row["settle_ccy"])),
            ct_val=(None if row.get("ct_val") in (None, "") else str(row["ct_val"])),
            ct_val_ccy=(
                None if row.get("ct_val_ccy") in (None, "") else str(row["ct_val_ccy"])
            ),
            lot_sz=str(row.get("lot_sz", "")),
            min_sz=str(row.get("min_sz", "")),
            tick_sz=str(row.get("tick_sz", "")),
            listing_state=str(row.get("listing_state", "")),
            effective_from=parse_utc_timestamp(row.get("effective_from")),
            effective_to=(
                None if effective_to_raw in (None, "") else parse_utc_timestamp(effective_to_raw)
            ),
            open_ended=row.get("open_ended"),
            source_ids=tuple(str(item) for item in row.get("source_ids", ())),
            contradiction=row.get("contradiction"),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if not self.state_id or self.instrument not in INSTRUMENTS:
            raise SourceAuthorityError("invalid metadata state identity")
        if self.authority_mode not in AUTHORITY_MODES:
            raise SourceAuthorityError("invalid metadata authority mode")
        if not self.inst_type or not self.base_ccy or not self.quote_ccy or not self.listing_state:
            raise SourceAuthorityError("required metadata identity field is missing")
        exact_decimal(self.lot_sz, label="lot_sz", strictly_positive=True)
        exact_decimal(self.min_sz, label="min_sz", strictly_positive=True)
        exact_decimal(self.tick_sz, label="tick_sz", strictly_positive=True)
        if self.instrument in SWAP_INSTRUMENTS:
            if not self.settle_ccy or self.ct_val is None or not self.ct_val_ccy:
                raise SourceAuthorityError("swap metadata contract or settlement field is missing")
            exact_decimal(self.ct_val, label="ct_val", strictly_positive=True)
        elif self.settle_ccy is not None or self.ct_val is not None or self.ct_val_ccy is not None:
            raise SourceAuthorityError("spot metadata cannot carry swap contract fields")
        if type(self.open_ended) is not bool:
            raise SourceAuthorityError("metadata open_ended must be boolean")
        if self.open_ended == (self.effective_to is not None):
            raise SourceAuthorityError("metadata state must have exactly one of effective_to/open_ended")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise SourceAuthorityError("metadata effective interval is invalid")
        if not self.source_ids or len(self.source_ids) != len(set(self.source_ids)):
            raise SourceAuthorityError("metadata state source IDs must be unique and non-empty")
        if type(self.contradiction) is not bool:
            raise SourceAuthorityError("metadata contradiction must be boolean")
        if self.contradiction:
            raise SourceAuthorityError("contradictory metadata state is never eligible")

    @property
    def bounded_end(self) -> datetime:
        return AUTHORITY_END if self.open_ended else self.effective_to  # type: ignore[return-value]


def _is_multiple(quantity: Decimal, increment: Decimal) -> bool:
    return quantity % increment == 0


def quantity_valid(quantity: Decimal, *, lot: Decimal, minimum: Decimal) -> bool:
    if quantity < 0 or not _is_multiple(quantity, lot):
        return False
    return quantity == 0 or quantity >= minimum


def transition_intersection(
    *, old_lot: str, new_lot: str, old_min: str, new_min: str
) -> dict[str, str]:
    """Derive the strict quantity intersection for an ambiguous switch window."""

    old_lot_d = exact_decimal(old_lot, label="old_lot", strictly_positive=True)
    new_lot_d = exact_decimal(new_lot, label="new_lot", strictly_positive=True)
    old_min_d = exact_decimal(old_min, label="old_min", strictly_positive=True)
    new_min_d = exact_decimal(new_min, label="new_min", strictly_positive=True)
    coarse = max(old_lot_d, new_lot_d)
    fine = min(old_lot_d, new_lot_d)
    ratio = coarse / fine
    if ratio != ratio.to_integral_value():
        raise SourceAuthorityError("FAIL_TRANSITION_INCREMENT_NOT_NESTED")
    maximum_minimum = max(old_min_d, new_min_d)
    transition_min = (maximum_minimum / coarse).to_integral_value(rounding=ROUND_CEILING) * coarse
    if not quantity_valid(transition_min, lot=old_lot_d, minimum=old_min_d):
        raise SourceAuthorityError("FAIL_TRANSITION_INTERSECTION_INVALID")
    if not quantity_valid(transition_min, lot=new_lot_d, minimum=new_min_d):
        raise SourceAuthorityError("FAIL_TRANSITION_INTERSECTION_INVALID")
    return {
        "transition_lot": decimal_text(coarse),
        "transition_min": decimal_text(transition_min),
        "nested_ratio": decimal_text(ratio),
    }


def prove_transition(
    old_state: MetadataState,
    new_state: MetadataState,
    window: FrozenTransition,
) -> dict[str, Any]:
    """Prove unchanged fields and the strict intersection for one frozen window."""

    if old_state.instrument != window.instrument or new_state.instrument != window.instrument:
        raise SourceAuthorityError("FAIL_TRANSITION_WINDOW_UNPROVEN")
    if old_state.authority_mode != "EXACT_EFFECTIVE_STATE" or new_state.authority_mode != (
        "EXACT_EFFECTIVE_STATE"
    ):
        raise SourceAuthorityError("FAIL_TRANSITION_WINDOW_UNPROVEN")
    if old_state.bounded_end != window.start or new_state.effective_from != window.end:
        raise SourceAuthorityError("FAIL_TRANSITION_WINDOW_UNPROVEN")
    unchanged = (
        "inst_type",
        "base_ccy",
        "quote_ccy",
        "settle_ccy",
        "ct_val",
        "ct_val_ccy",
        "tick_sz",
        "listing_state",
    )
    changed_fields = [name for name in unchanged if getattr(old_state, name) != getattr(new_state, name)]
    if changed_fields:
        raise SourceAuthorityError("FAIL_TRANSITION_FIELDS_CHANGED")
    result = transition_intersection(
        old_lot=old_state.lot_sz,
        new_lot=new_state.lot_sz,
        old_min=old_state.min_sz,
        new_min=new_state.min_sz,
    )
    if {old_state.lot_sz, new_state.lot_sz} != {window.old_step, window.new_step}:
        raise SourceAuthorityError("FAIL_TRANSITION_WINDOW_UNPROVEN")
    transition_lot = exact_decimal(result["transition_lot"], label="transition_lot", strictly_positive=True)
    transition_min = exact_decimal(result["transition_min"], label="transition_min", strictly_positive=True)
    old_lot = exact_decimal(old_state.lot_sz, label="old_lot", strictly_positive=True)
    new_lot = exact_decimal(new_state.lot_sz, label="new_lot", strictly_positive=True)
    old_min = exact_decimal(old_state.min_sz, label="old_min", strictly_positive=True)
    new_min = exact_decimal(new_state.min_sz, label="new_min", strictly_positive=True)
    candidates = sorted(
        {
            Decimal(0),
            max(Decimal(0), transition_min - transition_lot),
            transition_min,
            transition_min + transition_lot,
            transition_min + transition_lot * 2,
        }
    )
    boundary_cases = [
        {
            "quantity": decimal_text(quantity),
            "admitted_by_intersection": quantity_valid(
                quantity, lot=transition_lot, minimum=transition_min
            ),
            "valid_old": quantity_valid(quantity, lot=old_lot, minimum=old_min),
            "valid_new": quantity_valid(quantity, lot=new_lot, minimum=new_min),
        }
        for quantity in candidates
    ]
    if any(
        row["admitted_by_intersection"] and not (row["valid_old"] and row["valid_new"])
        for row in boundary_cases
    ):
        raise SourceAuthorityError("FAIL_TRANSITION_INTERSECTION_INVALID")
    return {
        "instrument": window.instrument,
        "window_start": window.start.isoformat(),
        "window_end_exclusive": window.end.isoformat(),
        "old_state_id": old_state.state_id,
        "new_state_id": new_state.state_id,
        **result,
        "unchanged_fields": list(unchanged),
        "boundary_cases": boundary_cases,
        "status": "PASS",
    }


def build_coverage_matrix(states: Sequence[MetadataState]) -> tuple[dict[str, Any], ...]:
    """Require exactly one non-contradictory state across the full interval."""

    rows: list[dict[str, Any]] = []
    for instrument in INSTRUMENTS:
        selected = sorted(
            (state for state in states if state.instrument == instrument),
            key=lambda state: state.effective_from,
        )
        if not selected:
            raise SourceAuthorityError("FAIL_REQUIRED_FIELD_MISSING")
        if selected[0].effective_from != AUTHORITY_START:
            raise SourceAuthorityError("FAIL_INTERVAL_BOUNDARY_UNPROVEN")
        previous_end = AUTHORITY_START
        for state in selected:
            start = state.effective_from
            end = min(state.bounded_end, AUTHORITY_END)
            if start < previous_end:
                raise SourceAuthorityError("FAIL_AMBIGUOUS_OR_CONTRADICTORY_STATE")
            if start > previous_end:
                raise SourceAuthorityError("FAIL_UNCOVERED_INTERVAL")
            if end <= start:
                raise SourceAuthorityError("FAIL_INTERVAL_BOUNDARY_UNPROVEN")
            if state.authority_mode == "TRANSITION_SAFE_INTERSECTION":
                if not any(
                    transition.instrument == instrument
                    and transition.start == start
                    and transition.end == end
                    for transition in FROZEN_TRANSITIONS
                ):
                    raise SourceAuthorityError("FAIL_NEW_UNFROZEN_TRANSITION")
            rows.append(
                {
                    "instrument": instrument,
                    "state_id": state.state_id,
                    "authority_mode": state.authority_mode,
                    "interval_start": start.isoformat(),
                    "interval_end_exclusive": end.isoformat(),
                    "source_coverage_status": "PASS",
                    "overlap_count": 0,
                    "contradiction_count": 0,
                    "uncovered_duration_seconds": 0,
                }
            )
            previous_end = end
            if previous_end == AUTHORITY_END:
                break
        if previous_end != AUTHORITY_END:
            raise SourceAuthorityError("FAIL_UNCOVERED_INTERVAL")
    return tuple(rows)


def choose_primary_failure(failures: Sequence[str]) -> str | None:
    """Choose one deterministic primary failure from the frozen taxonomy."""

    unique = set(failures)
    unknown = unique - set(FAILURE_PRIORITY)
    if unknown:
        raise SourceAuthorityError(f"unknown source-authority failure code: {sorted(unknown)}")
    return next((code for code in FAILURE_PRIORITY if code in unique), None)


def gate_result(
    *,
    source_commit_sha: str,
    query_inventory_sha256: str,
    failures: Sequence[str],
    source_object_count: int,
    eligible_source_object_count: int,
    coverage_rows: int,
    transition_proof_count: int,
) -> dict[str, Any]:
    """Create the fail-closed, non-authorizing gate decision record."""

    if not COMMIT_RE.fullmatch(source_commit_sha):
        raise SourceAuthorityError("source commit SHA is invalid")
    if not SHA256_RE.fullmatch(query_inventory_sha256):
        raise SourceAuthorityError("query inventory SHA-256 is invalid")
    for label, value in (
        ("source_object_count", source_object_count),
        ("eligible_source_object_count", eligible_source_object_count),
        ("coverage_rows", coverage_rows),
        ("transition_proof_count", transition_proof_count),
    ):
        if type(value) is not int or value < 0:
            raise SourceAuthorityError(f"{label} must be a non-negative integer")
    primary = choose_primary_failure(failures)
    passed = primary is None
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": STAGE,
        "source_commit_sha": source_commit_sha,
        "query_inventory_sha256": query_inventory_sha256,
        "result": "PASS" if passed else primary,
        "status": "PASS" if passed else "FAIL",
        "secondary_failures": [code for code in FAILURE_PRIORITY if code in set(failures) and code != primary],
        "source_object_count": source_object_count,
        "eligible_source_object_count": eligible_source_object_count,
        "coverage_rows": coverage_rows,
        "transition_proof_count": transition_proof_count,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
