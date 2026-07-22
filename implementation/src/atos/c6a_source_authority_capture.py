"""Controlled public-source capture for the C6A metadata authority gate.

The module expands only the committed query inventory.  It retains response
bytes before parsing, never calls economic/private endpoints, and emits plain
records suitable for the separate gate and independent-review modules.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from atos.c6a_source_authority import (
    AUTHORITY_END,
    AUTHORITY_START,
    INSTRUMENTS,
    SourceAuthorityError,
    parse_utc_timestamp,
    validate_query_inventory,
    validate_url,
)


CATALOG_PAGE_RE = re.compile(r"Showing\s+(\d+)\s*-\s*(\d+)\s+of\s+(\d+)\s+articles", re.I)
PUBLISHED_RE = re.compile(
    r"^(?P<title>.+?)\s+Published\s+on\s+(?P<date>[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4})(?:\s+.*)?$"
)
WAYBACK_TIMESTAMP_RE = re.compile(r"^\d{14}$")
DEFAULT_USER_AGENT = "atos-c6a-source-authority/1.0"


@dataclass(frozen=True)
class FrozenRequest:
    request_id: str
    request_kind: str
    url: str
    expected_content_type: str
    canonical_official_url: str | None = None
    parent_request_id: str | None = None


@dataclass(frozen=True)
class CapturedResponse:
    request: FrozenRequest
    retrieval_started_at: str
    retrieval_completed_at: str
    status_code: int
    final_url: str
    headers: Mapping[str, str]
    raw_path: str
    raw_size: int
    raw_sha256: str


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a" and self._href is None:
            values = dict(attrs)
            self._href = values.get("href")
            self._parts = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.text_parts.append(text)
            if self._href is not None:
                self._parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            text = " ".join(self._parts).strip()
            if self._href and text:
                self.anchors.append((self._href, text))
            self._href = None
            self._parts = []


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def load_frozen_inventory(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SourceAuthorityError("query inventory root must be an object")
    validate_query_inventory(payload)
    _validate_inventory_extensions(payload)
    return payload


def _validate_inventory_extensions(payload: Mapping[str, Any]) -> None:
    aliases = payload.get("instrument_aliases")
    if not isinstance(aliases, Mapping) or tuple(aliases.keys()) != INSTRUMENTS:
        raise SourceAuthorityError("query inventory aliases must cover the frozen instruments in order")
    for instrument, values in aliases.items():
        if not isinstance(values, list) or not values or not all(isinstance(item, str) and item for item in values):
            raise SourceAuthorityError(f"invalid aliases for {instrument}")
    terms = payload.get("metadata_terms")
    if not isinstance(terms, list) or not terms or not all(isinstance(item, str) and item for item in terms):
        raise SourceAuthorityError("query inventory metadata terms are required")
    if len({item.casefold() for item in terms}) != len(terms):
        raise SourceAuthorityError("query inventory metadata terms must be unique")

    requests = payload.get("requests")
    assert isinstance(requests, Sequence)
    catalog_count = 0
    archive_count = 0
    for row in requests:
        assert isinstance(row, Mapping)
        kind = row.get("request_kind")
        if kind == "announcement_catalog":
            catalog_count += 1
            if "{page}" not in str(row.get("url", "")):
                raise SourceAuthorityError("announcement catalog URL must contain the frozen {page} slot")
            page_range = row.get("page_range")
            if not isinstance(page_range, Mapping):
                raise SourceAuthorityError("announcement catalog page range is required")
            start = page_range.get("start")
            end = page_range.get("end")
            size = page_range.get("page_size")
            if type(start) is not int or type(end) is not int or type(size) is not int:
                raise SourceAuthorityError("catalog pagination values must be integers")
            if start != 1 or end < start or end > 500 or size != 15:
                raise SourceAuthorityError("catalog pagination range drift")
            if page_range.get("stop_rule") != "DECLARED_TERMINAL_PAGE_AND_NO_NEXT_PAGE":
                raise SourceAuthorityError("catalog stop rule drift")
            expansion = row.get("article_expansion")
            if not isinstance(expansion, Mapping):
                raise SourceAuthorityError("catalog article expansion is required")
            if expansion.get("date_start") != payload.get("authority_start") or expansion.get(
                "date_end_exclusive"
            ) != payload.get("authority_end_exclusive"):
                raise SourceAuthorityError("catalog article date boundary drift")
        elif kind == "archive_lookup":
            archive_count += 1
            expansion = row.get("archive_expansion")
            if not isinstance(expansion, Mapping):
                raise SourceAuthorityError("archive expansion is required")
            if expansion.get("memento_url_template") != (
                "https://web.archive.org/web/{timestamp}id_/{original}"
            ):
                raise SourceAuthorityError("archive memento template drift")
            if expansion.get("accepted_status") != "200":
                raise SourceAuthorityError("archive status contract drift")
    if catalog_count != 1 or archive_count != 4:
        raise SourceAuthorityError("query inventory must contain one catalog and four archive lookups")

    retry = payload.get("retry_policy")
    assert isinstance(retry, Mapping)
    for key in ("initial_backoff_seconds", "maximum_backoff_seconds"):
        if type(retry.get(key)) is not int or retry[key] < 0:
            raise SourceAuthorityError("retry backoff must be a non-negative integer")
    if retry.get("initial_backoff_seconds", 0) > retry.get("maximum_backoff_seconds", 0):
        raise SourceAuthorityError("retry backoff order is invalid")
    if retry.get("respect_retry_after") is not True:
        raise SourceAuthorityError("retry policy must respect Retry-After")


def inventory_sha256(payload: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(payload))


def catalog_requests(payload: Mapping[str, Any]) -> tuple[FrozenRequest, ...]:
    row = next(item for item in payload["requests"] if item["request_kind"] == "announcement_catalog")
    page_range = row["page_range"]
    result: list[FrozenRequest] = []
    for page in range(page_range["start"], page_range["end"] + 1):
        url = str(row["url"]).format(page=page)
        validate_url(url, request_kind="announcement_catalog")
        result.append(
            FrozenRequest(
                request_id=f"{row['request_id']}-page-{page:03d}",
                request_kind="announcement_catalog",
                url=url,
                expected_content_type=str(row["expected_content_type"]),
                parent_request_id=str(row["request_id"]),
            )
        )
    return tuple(result)


def archive_lookup_requests(payload: Mapping[str, Any]) -> tuple[FrozenRequest, ...]:
    result: list[FrozenRequest] = []
    for row in payload["requests"]:
        if row["request_kind"] != "archive_lookup":
            continue
        result.append(
            FrozenRequest(
                request_id=str(row["request_id"]),
                request_kind="archive_lookup",
                url=str(row["url"]),
                canonical_official_url=str(row["canonical_official_url"]),
                expected_content_type=str(row["expected_content_type"]),
            )
        )
    return tuple(result)


def _header_mapping(headers: Message) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def capture_request(
    request: FrozenRequest,
    *,
    output_root: Path,
    timeout_seconds: int,
    max_attempts: int,
    initial_backoff_seconds: int,
    maximum_backoff_seconds: int,
) -> CapturedResponse:
    """Capture bytes once per successful request and retain them before parsing."""

    validate_url(
        request.url,
        request_kind=request.request_kind,
        canonical_official_url=request.canonical_official_url,
    )
    started = datetime.now(timezone.utc).isoformat()
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            http_request = Request(
                request.url,
                method="GET",
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": request.expected_content_type,
                    "Accept-Encoding": "identity",
                },
            )
            with urlopen(http_request, timeout=timeout_seconds) as response:
                data = response.read()
                status = int(getattr(response, "status", 200))
                final_url = str(response.geturl())
                headers = _header_mapping(response.headers)
            if status != 200 or not data:
                raise SourceAuthorityError(f"source capture returned status={status} size={len(data)}")
            completed = datetime.now(timezone.utc).isoformat()
            relative = Path("raw") / f"{request.request_id}.bin"
            atomic_write_bytes(output_root / relative, data)
            return CapturedResponse(
                request=request,
                retrieval_started_at=started,
                retrieval_completed_at=completed,
                status_code=status,
                final_url=final_url,
                headers=headers,
                raw_path=relative.as_posix(),
                raw_size=len(data),
                raw_sha256=sha256_bytes(data),
            )
        except (HTTPError, URLError, TimeoutError, SourceAuthorityError) as exc:
            last_error = exc
            if attempt == max_attempts:
                break
            delay = min(maximum_backoff_seconds, initial_backoff_seconds * (2 ** (attempt - 1)))
            time.sleep(delay)
    raise SourceAuthorityError(f"source capture failed after {max_attempts} attempts: {last_error}")


def response_record(capture: CapturedResponse) -> dict[str, Any]:
    return {
        "request_id": capture.request.request_id,
        "parent_request_id": capture.request.parent_request_id,
        "request_kind": capture.request.request_kind,
        "requested_url": capture.request.url,
        "canonical_official_url": capture.request.canonical_official_url,
        "retrieval_started_at": capture.retrieval_started_at,
        "retrieval_completed_at": capture.retrieval_completed_at,
        "status_code": capture.status_code,
        "final_url": capture.final_url,
        "headers": dict(sorted(capture.headers.items())),
        "raw_path": capture.raw_path,
        "raw_size": capture.raw_size,
        "raw_sha256": capture.raw_sha256,
    }


def parse_announcement_catalog(page_url: str, data: bytes, *, expected_page_size: int = 15) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceAuthorityError("announcement catalog is not UTF-8") from exc
    parser = _AnchorParser()
    parser.feed(text)
    joined_text = " ".join(parser.text_parts)
    summary_match = CATALOG_PAGE_RE.search(joined_text)
    if not summary_match:
        raise SourceAuthorityError("announcement catalog pagination summary missing")
    first, last, total = (int(value) for value in summary_match.groups())
    if first < 1 or last < first or total < last:
        raise SourceAuthorityError("announcement catalog pagination summary is invalid")
    page_number_match = re.search(r"/page/(\d+)(?:$|[/?#])", page_url)
    if not page_number_match:
        raise SourceAuthorityError("announcement catalog page URL lacks an exact page number")
    page_number = int(page_number_match.group(1))
    expected_first = (page_number - 1) * expected_page_size + 1
    if first != expected_first:
        raise SourceAuthorityError("announcement catalog first-item index drift")
    if last - first + 1 > expected_page_size:
        raise SourceAuthorityError("announcement catalog page exceeds frozen page size")
    terminal_page = (total + expected_page_size - 1) // expected_page_size

    articles: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for href, anchor_text in parser.anchors:
        match = PUBLISHED_RE.match(anchor_text)
        if not match:
            continue
        canonical_url = urljoin(page_url, href)
        parsed = urlparse(canonical_url)
        if parsed.scheme != "https" or parsed.hostname != "www.okx.com" or not parsed.path.startswith(
            "/help/"
        ):
            raise SourceAuthorityError("catalog article URL escaped the frozen OKX help scope")
        published_date = datetime.strptime(match.group("date"), "%b %d, %Y").replace(
            tzinfo=timezone.utc
        )
        if canonical_url in seen_urls:
            raise SourceAuthorityError("duplicate article URL within one catalog page")
        seen_urls.add(canonical_url)
        articles.append(
            {
                "title": match.group("title").strip(),
                "published_at": published_date.isoformat(),
                "canonical_url": canonical_url,
            }
        )
    expected_count = last - first + 1
    if len(articles) != expected_count:
        raise SourceAuthorityError(
            f"announcement catalog article count mismatch: parsed={len(articles)} expected={expected_count}"
        )
    return {
        "page_number": page_number,
        "first_item": first,
        "last_item": last,
        "total_items": total,
        "declared_terminal_page": terminal_page,
        "is_terminal_page": page_number == terminal_page,
        "articles": articles,
    }


def classify_article(
    article: Mapping[str, Any],
    *,
    aliases: Mapping[str, Sequence[str]],
    metadata_terms: Sequence[str],
) -> dict[str, Any]:
    title = str(article.get("title", ""))
    published_at = parse_utc_timestamp(article.get("published_at"))
    normalized = title.casefold()
    alias_matches = sorted(
        {
            alias
            for values in aliases.values()
            for alias in values
            if alias.casefold() in normalized
        }
    )
    term_matches = sorted(term for term in metadata_terms if term.casefold() in normalized)
    frozen_transition_hint = (
        ("btc" in normalized or "eth" in normalized)
        and ("adjust" in normalized or "minimum" in normalized or "lot" in normalized)
        and ("perpetual" in normalized or "swap" in normalized or "contract" in normalized)
    )
    inside_date_range = AUTHORITY_START <= published_at < AUTHORITY_END
    selected = inside_date_range and ((alias_matches and term_matches) or frozen_transition_hint)
    return {
        **dict(article),
        "inside_authority_date_range": inside_date_range,
        "alias_matches": alias_matches,
        "metadata_term_matches": term_matches,
        "frozen_transition_hint": frozen_transition_hint,
        "selected_for_article_capture": selected,
        "classification_rule": (
            "INSTRUMENT_ALIAS_AND_METADATA_TERM_OR_EXACT_FROZEN_TRANSITION_MATCH"
        ),
    }


def article_request(article: Mapping[str, Any], *, index: int) -> FrozenRequest:
    if article.get("selected_for_article_capture") is not True:
        raise SourceAuthorityError("unselected announcement cannot generate a request")
    url = str(article["canonical_url"])
    validate_url(url, request_kind="announcement_article")
    slug = re.sub(r"[^a-z0-9]+", "-", urlparse(url).path.rsplit("/", 1)[-1].casefold()).strip("-")
    return FrozenRequest(
        request_id=f"announcement-article-{index:04d}-{slug[:80]}",
        request_kind="announcement_article",
        url=url,
        expected_content_type="text/html",
        canonical_official_url=url,
        parent_request_id="okx-announcement-catalog-global",
    )


def _normalized_okx_instruments_url(url: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    parsed = urlparse(url)
    return parsed.path, tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True)))


def parse_wayback_cdx(data: bytes, *, canonical_official_url: str) -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceAuthorityError("Wayback CDX response is not valid JSON") from exc
    if not isinstance(payload, list) or not payload:
        raise SourceAuthorityError("Wayback CDX response is empty")
    expected_header = ["timestamp", "original", "statuscode", "mimetype", "digest", "length"]
    if payload[0] != expected_header:
        raise SourceAuthorityError("Wayback CDX header drift")
    expected_path_query = _normalized_okx_instruments_url(canonical_official_url)
    captures: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in payload[1:]:
        if not isinstance(row, list) or len(row) != len(expected_header):
            raise SourceAuthorityError("Wayback CDX row shape drift")
        item = dict(zip(expected_header, (str(value) for value in row), strict=True))
        timestamp = item["timestamp"]
        if not WAYBACK_TIMESTAMP_RE.fullmatch(timestamp):
            raise SourceAuthorityError("Wayback capture timestamp is invalid")
        captured_at = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        if not (AUTHORITY_START <= captured_at < AUTHORITY_END):
            raise SourceAuthorityError("Wayback capture escaped the frozen authority interval")
        if item["statuscode"] != "200" or item["mimetype"] not in {"application/json", "text/json"}:
            raise SourceAuthorityError("Wayback capture status or MIME type is ineligible")
        if _normalized_okx_instruments_url(item["original"]) != expected_path_query:
            raise SourceAuthorityError("Wayback original URL does not match the frozen canonical URL")
        key = (timestamp, item["digest"])
        if key in seen:
            raise SourceAuthorityError("duplicate Wayback capture identity")
        seen.add(key)
        captures.append(
            {
                **item,
                "captured_at": captured_at.isoformat(),
                "canonical_official_url": canonical_official_url,
                "memento_url": f"https://web.archive.org/web/{timestamp}id_/{item['original']}",
            }
        )
    return tuple(captures)


def memento_request(capture: Mapping[str, Any], *, parent_request_id: str, index: int) -> FrozenRequest:
    url = str(capture["memento_url"])
    canonical = str(capture["canonical_official_url"])
    validate_url(url, request_kind="archive_lookup", canonical_official_url=canonical)
    return FrozenRequest(
        request_id=f"{parent_request_id}-memento-{index:04d}-{capture['timestamp']}",
        request_kind="archive_lookup",
        url=url,
        canonical_official_url=canonical,
        expected_content_type="application/json",
        parent_request_id=parent_request_id,
    )


def decode_okx_instruments_response(data: bytes, *, expected_instrument: str) -> dict[str, Any]:
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceAuthorityError("archived OKX response is not valid JSON") from exc
    if not isinstance(payload, Mapping) or payload.get("code") != "0" or payload.get("msg") not in ("", None):
        raise SourceAuthorityError("archived object is not an eligible OKX public response")
    rows = payload.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
        raise SourceAuthorityError("archived OKX instruments response must contain exactly one row")
    row = rows[0]
    if row.get("instId") != expected_instrument:
        raise SourceAuthorityError("archived OKX instrument identity mismatch")
    required = ["instId", "instType", "baseCcy", "quoteCcy", "lotSz", "minSz", "tickSz", "state"]
    if expected_instrument.endswith("-SWAP"):
        required.extend(["settleCcy", "ctVal", "ctValCcy"])
    missing = [field for field in required if not isinstance(row.get(field), str) or not row[field]]
    if missing:
        raise SourceAuthorityError(f"archived OKX response missing required fields: {missing}")
    selected = {field: row[field] for field in required}
    return {
        "code": "0",
        "msg": "",
        "data": [selected],
    }


def build_recursive_manifest(root: Path, *, excluded_paths: Iterable[str] = ("manifest.json",)) -> dict[str, Any]:
    excluded = set(excluded_paths)
    files: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        data = path.read_bytes()
        files.append({"path": relative, "size": len(data), "sha256": sha256_bytes(data)})
    if not files:
        raise SourceAuthorityError("manifest cannot be empty")
    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GATE",
        "files": files,
        "file_count": len(files),
    }
