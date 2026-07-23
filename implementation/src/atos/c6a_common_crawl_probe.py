"""Bounded Common Crawl recovery probe for official OKX GLOBAL Help Center bytes.

Common Crawl is treated only as an archive carrier. Authority remains the
retained official OKX HTTP response embedded in each WARC record. The probe
uses exact URLs, a frozen crawl inventory, sequential requests, a no-proxy
opener, bounded response sizes, and fail-closed GLOBAL-page proof.

This module never accesses OKX directly and never accesses instruments,
candles, funding, accounts, trading, paper, shadow, private API, or live
endpoints.
"""
from __future__ import annotations

import gzip
import hashlib
import html
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from atos.c6a_source_authority import SourceAuthorityError


STAGE = "C6A_COMMON_CRAWL_OFFICIAL_SOURCE_COVERAGE_PROBE"
RESULT_AVAILABLE = "COMMON_CRAWL_OFFICIAL_BYTES_AVAILABLE"
RESULT_INSUFFICIENT = "COMMON_CRAWL_COVERAGE_INSUFFICIENT"
INDEX_HOST = "index.commoncrawl.org"
DATA_HOST = "data.commoncrawl.org"
USER_AGENT = (
    "ai-autonomous-trading-os-c6a-common-crawl-probe/1.0 "
    "(+https://github.com/Dreaminmaster/ai-autonomous-trading-os)"
)
MAX_INDEX_BYTES = 5_000_000
MAX_WARC_RECORD_BYTES = 10_000_000
_FORBIDDEN_ENV = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "COOKIE",
    "COOKIES",
    "AUTHORIZATION",
    "PROXY_AUTHORIZATION",
)
_GLOBAL_SITE_RE = re.compile(
    r'["\']siteList["\']\s*:\s*\[\s*["\']OKX_GLOBAL["\']',
    re.IGNORECASE,
)
_LOCALE_HELP_RE = re.compile(
    r"^/[a-z]{2,3}(?:-[a-z]{2,4})?/help(?:/|$)", re.IGNORECASE
)
_WARC_FILENAME_RE = re.compile(
    r"^crawl-data/CC-MAIN-\d{4}-\d{2}/segments/.+\.warc\.gz$"
)


@dataclass(frozen=True)
class HttpResult:
    status: int
    final_url: str
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class Target:
    target_id: str
    kind: str
    url: str
    crawl_indexes: tuple[str, ...]
    required_markers: tuple[str, ...]


class _EvidenceHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.canonicals: list[str] = []
        self.og_urls: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {str(key).casefold(): value for key, value in attrs}
        if tag.casefold() == "link":
            rel = str(values.get("rel") or "").casefold().split()
            href = values.get("href")
            if "canonical" in rel and href:
                self.canonicals.append(str(href))
        if tag.casefold() == "meta":
            prop = str(values.get("property") or "").casefold()
            content = values.get("content")
            if prop == "og:url" and content:
                self.og_urls.append(str(content))


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        + "\n"
    ).encode("utf-8")


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


def _safe_id(value: str) -> str:
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", value) is None:
        raise SourceAuthorityError(f"unsafe frozen identifier: {value}")
    return value


def _normalized_official_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != "www.okx.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise SourceAuthorityError(
            f"target is not an exact public OKX URL: {value}"
        )
    path = parsed.path.rstrip("/") or "/"
    if not path.startswith("/help/") and path != "/help":
        raise SourceAuthorityError(
            f"target escaped public OKX Help Center: {value}"
        )
    if _LOCALE_HELP_RE.match(path):
        raise SourceAuthorityError(
            f"target is regional rather than locale-neutral GLOBAL: {value}"
        )
    return f"https://www.okx.com{path}"


def _validate_crawl_id(value: str) -> str:
    if re.fullmatch(r"CC-MAIN-\d{4}-\d{2}", value) is None:
        raise SourceAuthorityError(
            f"invalid frozen Common Crawl index: {value}"
        )
    return value


def load_inventory(path: Path) -> tuple[dict[str, Any], tuple[Target, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SourceAuthorityError(
            "Common Crawl inventory root must be an object"
        )
    if payload.get("schema_version") != 1 or payload.get("stage") != STAGE:
        raise SourceAuthorityError("Common Crawl inventory identity drift")
    if payload.get("archive_carrier") != "COMMON_CRAWL":
        raise SourceAuthorityError("archive carrier drift")
    if (
        payload.get("authority_source")
        != "OFFICIAL_OKX_HTTP_RESPONSE_BYTES"
    ):
        raise SourceAuthorityError("authority-source contract drift")
    if (
        payload.get("match_type") != "exact"
        or payload.get("max_records_per_query") != 1
    ):
        raise SourceAuthorityError("bounded exact-query contract drift")
    if payload.get("minimum_request_interval_seconds") != 1:
        raise SourceAuthorityError("request pacing contract drift")

    rows = payload.get("targets")
    if not isinstance(rows, list) or not rows:
        raise SourceAuthorityError("Common Crawl target inventory missing")
    targets: list[Target] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise SourceAuthorityError(
                "Common Crawl target row is not an object"
            )
        target_id = _safe_id(str(row.get("target_id", "")))
        if target_id in seen:
            raise SourceAuthorityError(
                f"duplicate Common Crawl target: {target_id}"
            )
        seen.add(target_id)
        kind = str(row.get("kind", ""))
        if kind not in {"catalog", "announcement_article"}:
            raise SourceAuthorityError(
                f"unsupported Common Crawl target kind: {kind}"
            )
        url = _normalized_official_url(str(row.get("url", "")))
        crawls_raw = row.get("crawl_indexes")
        if not isinstance(crawls_raw, list) or not crawls_raw:
            raise SourceAuthorityError(
                f"crawl indexes missing for {target_id}"
            )
        crawls = tuple(
            _validate_crawl_id(str(value)) for value in crawls_raw
        )
        if len(set(crawls)) != len(crawls):
            raise SourceAuthorityError(
                f"duplicate crawl index for {target_id}"
            )
        markers_raw = row.get("required_markers")
        if not isinstance(markers_raw, list) or not markers_raw:
            raise SourceAuthorityError(
                f"required markers missing for {target_id}"
            )
        markers = tuple(
            str(value).strip().casefold() for value in markers_raw
        )
        if any(not value for value in markers):
            raise SourceAuthorityError(
                f"empty required marker for {target_id}"
            )
        targets.append(Target(target_id, kind, url, crawls, markers))

    for key in (
        "article_expansion_authorized",
        "third_full_capture_authorized",
        "implementation_authorized",
        "economic_data_access_authorized",
    ):
        if payload.get(key) is not False:
            raise SourceAuthorityError(
                f"inventory improperly authorizes {key}"
            )
    if payload.get("paper_state") != "PAPER_CLOSED":
        raise SourceAuthorityError("inventory paper-state drift")
    if payload.get("shadow_state") != "SHADOW_CLOSED":
        raise SourceAuthorityError("inventory shadow-state drift")
    if payload.get("live_state") != "LIVE_FORBIDDEN":
        raise SourceAuthorityError("inventory live-state drift")
    return payload, tuple(targets)


def assert_clean_network_environment(
    environ: Mapping[str, str] | None = None,
) -> None:
    effective = os.environ if environ is None else environ
    present = sorted(
        key for key in _FORBIDDEN_ENV if str(effective.get(key, "")).strip()
    )
    if present:
        raise SourceAuthorityError(
            "Common Crawl probe rejected prohibited proxy/cookie/auth "
            "environment state: " + ",".join(present)
        )


def build_index_query_url(crawl_id: str, target_url: str) -> str:
    crawl_id = _validate_crawl_id(crawl_id)
    target_url = _normalized_official_url(target_url)
    return (
        f"https://{INDEX_HOST}/{crawl_id}-index"
        f"?url={quote(target_url, safe='')}"
        "&output=json&matchType=exact&filter=status%3A200"
    )


def _validate_index_query_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != INDEX_HOST
        or parsed.username
        or parsed.password
        or parsed.fragment
        or re.fullmatch(r"/CC-MAIN-\d{4}-\d{2}-index", parsed.path)
        is None
    ):
        raise SourceAuthorityError(
            f"Common Crawl index request escaped frozen host/path: {url}"
        )
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) != {"url", "output", "matchType", "filter"}:
        raise SourceAuthorityError(
            f"Common Crawl index query parameters drifted: {url}"
        )
    if (
        query["output"] != ["json"]
        or query["matchType"] != ["exact"]
        or query["filter"] != ["status:200"]
    ):
        raise SourceAuthorityError(
            f"Common Crawl index query contract drifted: {url}"
        )
    _normalized_official_url(query["url"][0])


def _validate_data_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != DATA_HOST
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not _WARC_FILENAME_RE.fullmatch(parsed.path.lstrip("/"))
    ):
        raise SourceAuthorityError(
            f"Common Crawl data request escaped frozen host/path: {url}"
        )


class _HostBoundRedirectHandler(HTTPRedirectHandler):
    def __init__(self, validator: Callable[[str], None]) -> None:
        super().__init__()
        self._validator = validator

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        self._validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def network_get(
    url: str,
    *,
    headers: Mapping[str, str],
    timeout_seconds: int,
    maximum_bytes: int,
) -> HttpResult:
    host = (urlparse(url).hostname or "").lower()
    validator = (
        _validate_index_query_url if host == INDEX_HOST else _validate_data_url
    )
    validator(url)
    opener = build_opener(
        ProxyHandler({}), _HostBoundRedirectHandler(validator)
    )
    request = Request(url, method="GET", headers=dict(headers))
    with opener.open(request, timeout=timeout_seconds) as response:
        body = response.read(maximum_bytes + 1)
        if len(body) > maximum_bytes:
            raise SourceAuthorityError(
                f"bounded Common Crawl response exceeded {maximum_bytes} bytes"
            )
        return HttpResult(
            status=int(getattr(response, "status", 200)),
            final_url=str(response.geturl()),
            headers={
                str(key).lower(): str(value)
                for key, value in response.headers.items()
            },
            body=body,
        )


def parse_cdx_lines(data: bytes, *, target_url: str) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceAuthorityError(
            "Common Crawl index response is not UTF-8"
        ) from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SourceAuthorityError(
                f"Common Crawl index line {line_number} is invalid JSON"
            ) from exc
        if not isinstance(row, dict):
            raise SourceAuthorityError(
                f"Common Crawl index line {line_number} is not an object"
            )
        if _normalized_official_url(str(row.get("url", ""))) != target_url:
            raise SourceAuthorityError(
                "Common Crawl exact-match response contains another target URL"
            )
        if str(row.get("status", "")) != "200":
            continue
        filename = str(row.get("filename", ""))
        if _WARC_FILENAME_RE.fullmatch(filename) is None:
            raise SourceAuthorityError(
                "Common Crawl WARC filename escaped archive namespace: "
                f"{filename}"
            )
        try:
            offset = int(row.get("offset"))
            length = int(row.get("length"))
        except (TypeError, ValueError) as exc:
            raise SourceAuthorityError(
                "Common Crawl WARC offset/length is invalid"
            ) from exc
        if offset < 0 or length < 1 or length > MAX_WARC_RECORD_BYTES:
            raise SourceAuthorityError(
                "Common Crawl WARC byte range is outside the bounded contract"
            )
        rows.append({**row, "offset": offset, "length": length})
    rows.sort(key=lambda value: str(value.get("timestamp", "")))
    return rows


def _parse_header_block(data: bytes) -> tuple[str, dict[str, str], bytes]:
    first, separator, rest = data.partition(b"\r\n\r\n")
    if not separator:
        first, separator, rest = data.partition(b"\n\n")
    if not separator:
        raise SourceAuthorityError(
            "retained WARC/HTTP header block is incomplete"
        )
    lines = first.decode("utf-8", errors="strict").splitlines()
    if not lines:
        raise SourceAuthorityError(
            "retained WARC/HTTP header block is empty"
        )
    values: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip().casefold()] = value.strip()
    return lines[0].strip(), values, rest


def parse_warc_record(
    compressed: bytes, *, expected_target_url: str
) -> dict[str, Any]:
    try:
        record = gzip.decompress(compressed)
    except (OSError, EOFError) as exc:
        raise SourceAuthorityError(
            "Common Crawl range is not a complete gzip WARC member"
        ) from exc
    warc_start, warc_headers, content = _parse_header_block(record)
    if not warc_start.startswith("WARC/"):
        raise SourceAuthorityError(
            "Common Crawl record lacks a WARC status line"
        )
    target_uri = _normalized_official_url(
        warc_headers.get("warc-target-uri", "")
    )
    if target_uri != expected_target_url:
        raise SourceAuthorityError(
            "WARC-Target-URI does not match the frozen official URL"
        )
    warc_type = warc_headers.get("warc-type", "").casefold()
    if warc_type != "response":
        return {
            "usable": False,
            "failure": f"unsupported WARC-Type {warc_type or 'missing'}",
            "record_bytes": record,
            "warc_headers": warc_headers,
            "warc_target_uri": target_uri,
        }

    declared = warc_headers.get("content-length")
    if declared:
        try:
            declared_length = int(declared)
        except ValueError as exc:
            raise SourceAuthorityError(
                "WARC Content-Length is invalid"
            ) from exc
        if declared_length < 1 or declared_length > len(content):
            raise SourceAuthorityError(
                "WARC Content-Length exceeds retained record"
            )
        content = content[:declared_length]

    http_start, http_headers, body = _parse_header_block(content)
    parts = http_start.split()
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        raise SourceAuthorityError(
            "embedded official response lacks an HTTP status line"
        )
    try:
        status = int(parts[1])
    except ValueError as exc:
        raise SourceAuthorityError(
            "embedded official HTTP status is invalid"
        ) from exc
    content_type = http_headers.get("content-type", "").casefold()
    if status != 200 or "text/html" not in content_type:
        return {
            "usable": False,
            "failure": (
                "official HTTP response status/content-type rejected: "
                f"{status} {content_type}"
            ),
            "record_bytes": record,
            "warc_headers": warc_headers,
            "warc_target_uri": target_uri,
            "http_status": status,
            "http_headers": http_headers,
            "http_body": body,
        }
    return {
        "usable": True,
        "record_bytes": record,
        "warc_headers": warc_headers,
        "warc_target_uri": target_uri,
        "http_status": status,
        "http_headers": http_headers,
        "http_body": body,
    }


def prove_official_global_html(
    body: bytes,
    *,
    target_url: str,
    required_markers: Sequence[str],
) -> dict[str, Any]:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceAuthorityError(
            "official OKX HTML is not UTF-8"
        ) from exc
    parser = _EvidenceHTMLParser()
    parser.feed(text)
    expected = _normalized_official_url(target_url)
    canonicals = [
        _normalized_official_url(value) for value in parser.canonicals
    ]
    og_urls = [_normalized_official_url(value) for value in parser.og_urls]
    if expected not in canonicals:
        raise SourceAuthorityError(
            "official HTML canonical URL does not prove the frozen GLOBAL target"
        )
    if og_urls and expected not in og_urls:
        raise SourceAuthorityError(
            "official HTML og:url conflicts with the frozen GLOBAL target"
        )
    if _GLOBAL_SITE_RE.search(text) is None:
        raise SourceAuthorityError(
            "official HTML lacks explicit OKX_GLOBAL siteList proof"
        )
    folded = html.unescape(text).casefold()
    missing = [
        marker
        for marker in required_markers
        if marker.casefold() not in folded
    ]
    if missing:
        raise SourceAuthorityError(
            f"official HTML lacks target-specific markers: {missing}"
        )
    return {
        "status": "PASS",
        "canonical_url": expected,
        "og_url": expected if expected in og_urls else None,
        "explicit_global_site_marker": "OKX_GLOBAL",
        "required_markers": list(required_markers),
    }


def _record_paths(
    target_id: str, crawl_id: str, timestamp: str
) -> dict[str, Path]:
    stem = (
        f"{target_id}--{crawl_id.lower()}--{_safe_id(timestamp.lower())}"
    )
    return {
        "compressed": Path("warc") / f"{stem}.warc.gz",
        "record": Path("warc") / f"{stem}.warc",
        "body": Path("official") / f"{stem}.html",
        "metadata": Path("records") / f"{stem}.json",
    }


def _query_once(
    target: Target,
    crawl_id: str,
    output_root: Path,
    *,
    get: Callable[..., HttpResult],
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    query_url = build_index_query_url(crawl_id, target.url)
    query_id = f"{target.target_id}--{crawl_id.lower()}"
    base = {
        "query_id": query_id,
        "target_id": target.target_id,
        "target_kind": target.kind,
        "target_url": target.url,
        "crawl_id": crawl_id,
        "query_url": query_url,
    }
    try:
        response = get(
            query_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/x-ndjson,application/json",
            },
            timeout_seconds=timeout_seconds,
            maximum_bytes=MAX_INDEX_BYTES,
        )
        _validate_index_query_url(response.final_url)
        if response.status != 200:
            raise SourceAuthorityError(
                f"Common Crawl index returned HTTP {response.status}"
            )
        raw_index_path = Path("index") / f"{query_id}.ndjson"
        atomic_write_bytes(output_root / raw_index_path, response.body)
        hits = parse_cdx_lines(response.body, target_url=target.url)
        query_meta = {
            **base,
            "status": "PASS",
            "http_status": response.status,
            "response_headers": dict(response.headers),
            "raw_index_path": raw_index_path.as_posix(),
            "raw_index_size": len(response.body),
            "raw_index_sha256": sha256_bytes(response.body),
            "hit_count": len(hits),
            "selected_count": min(1, len(hits)),
        }
        if not hits:
            return query_meta, None

        hit = hits[0]
        filename = str(hit["filename"])
        data_url = f"https://{DATA_HOST}/{filename}"
        _validate_data_url(data_url)
        length = int(hit["length"])
        offset = int(hit["offset"])
        warc_response = get(
            data_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/warc",
                "Range": f"bytes={offset}-{offset + length - 1}",
            },
            timeout_seconds=timeout_seconds,
            maximum_bytes=length,
        )
        _validate_data_url(warc_response.final_url)
        if warc_response.status != 206:
            raise SourceAuthorityError(
                "Common Crawl range request must return 206, got "
                f"{warc_response.status}"
            )
        if len(warc_response.body) != length:
            raise SourceAuthorityError(
                "Common Crawl range length mismatch: "
                f"expected={length} observed={len(warc_response.body)}"
            )
        parsed = parse_warc_record(
            warc_response.body, expected_target_url=target.url
        )
        timestamp = str(hit.get("timestamp", "unknown"))
        paths = _record_paths(target.target_id, crawl_id, timestamp)
        atomic_write_bytes(
            output_root / paths["compressed"], warc_response.body
        )
        record = bytes(parsed.pop("record_bytes"))
        atomic_write_bytes(output_root / paths["record"], record)
        http_body = parsed.pop("http_body", None)
        proof: dict[str, Any] | None = None
        proof_error: str | None = None
        if isinstance(http_body, bytes):
            atomic_write_bytes(output_root / paths["body"], http_body)
            try:
                proof = prove_official_global_html(
                    http_body,
                    target_url=target.url,
                    required_markers=target.required_markers,
                )
            except SourceAuthorityError as exc:
                proof_error = str(exc)

        usable = bool(parsed.get("usable")) and proof is not None
        record_meta = {
            **base,
            "status": "PASS" if usable else "FAIL",
            "usable_official_global_bytes": usable,
            "cdx_record": hit,
            "data_url": data_url,
            "range_header": f"bytes={offset}-{offset + length - 1}",
            "range_http_status": warc_response.status,
            "range_response_headers": dict(warc_response.headers),
            "compressed_path": paths["compressed"].as_posix(),
            "compressed_size": len(warc_response.body),
            "compressed_sha256": sha256_bytes(warc_response.body),
            "record_path": paths["record"].as_posix(),
            "record_size": len(record),
            "record_sha256": sha256_bytes(record),
            "body_path": (
                paths["body"].as_posix()
                if isinstance(http_body, bytes)
                else None
            ),
            "body_size": (
                len(http_body) if isinstance(http_body, bytes) else None
            ),
            "body_sha256": (
                sha256_bytes(http_body)
                if isinstance(http_body, bytes)
                else None
            ),
            "warc_target_uri": parsed.get("warc_target_uri"),
            "warc_headers": parsed.get("warc_headers"),
            "http_status": parsed.get("http_status"),
            "http_headers": parsed.get("http_headers"),
            "global_proof": proof,
            "failure": proof_error or parsed.get("failure"),
        }
        atomic_write_json(output_root / paths["metadata"], record_meta)
        record_meta["metadata_path"] = paths["metadata"].as_posix()
        return query_meta, record_meta
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        ValueError,
        SourceAuthorityError,
    ) as exc:
        return {
            **base,
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "hit_count": 0,
            "selected_count": 0,
        }, None


def run_probe(
    inventory_path: Path,
    output_root: Path,
    *,
    get: Callable[..., HttpResult] = network_get,
    timeout_seconds: int = 60,
    environ: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run the frozen exact-URL archive coverage inventory."""
    assert_clean_network_environment(environ)
    inventory, targets = load_inventory(inventory_path)
    output_root.mkdir(parents=True, exist_ok=True)
    inventory_bytes = canonical_json_bytes(inventory)
    atomic_write_bytes(
        output_root / "inventory_snapshot.json", inventory_bytes
    )

    query_rows: list[dict[str, Any]] = []
    record_rows: list[dict[str, Any]] = []
    first = True
    for target in targets:
        for crawl_id in target.crawl_indexes:
            if not first:
                sleep(float(inventory["minimum_request_interval_seconds"]))
            first = False
            query_row, record_row = _query_once(
                target,
                crawl_id,
                output_root,
                get=get,
                timeout_seconds=timeout_seconds,
            )
            query_rows.append(query_row)
            if record_row is not None:
                record_rows.append(record_row)

    covered = sorted(
        {
            str(row["target_id"])
            for row in record_rows
            if row.get("usable_official_global_bytes") is True
        }
    )
    target_ids = sorted(target.target_id for target in targets)
    missing = sorted(set(target_ids) - set(covered))
    status = "PASS" if not missing else "FAIL"
    result = RESULT_AVAILABLE if status == "PASS" else RESULT_INSUFFICIENT
    payload = {
        "schema_version": 1,
        "stage": STAGE,
        "status": status,
        "result": result,
        "inventory_sha256": sha256_bytes(inventory_bytes),
        "query_count": len(query_rows),
        "target_count": len(targets),
        "covered_target_ids": covered,
        "missing_target_ids": missing,
        "query_results": query_rows,
        "record_results": record_rows,
        "archive_carrier": "COMMON_CRAWL",
        "authority_source": "OFFICIAL_OKX_HTTP_RESPONSE_BYTES",
        "article_expansion_authorized": False,
        "third_full_capture_authorized": False,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    atomic_write_json(output_root / "probe_result.json", payload)
    return payload


def build_manifest(output_root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(
        item for item in output_root.rglob("*") if item.is_file()
    ):
        relative = path.relative_to(output_root).as_posix()
        if relative == "manifest.json":
            continue
        data = path.read_bytes()
        files.append(
            {
                "path": relative,
                "size": len(data),
                "sha256": sha256_bytes(data),
            }
        )
    payload = {
        "schema_version": 1,
        "stage": f"{STAGE}_MANIFEST",
        "files": files,
        "file_count": len(files),
        "article_expansion_authorized": False,
        "third_full_capture_authorized": False,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }
    atomic_write_json(output_root / "manifest.json", payload)
    return payload
