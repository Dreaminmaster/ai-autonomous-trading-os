"""Shared immutable types and validators for the raw Common Crawl CDXJ probe."""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

STAGE = "C6A_COMMON_CRAWL_RAW_CDXJ_ACCESS_PROBE"
RESULT_VERIFIED = "RAW_CDXJ_ACCESS_PATH_VERIFIED"
RESULT_FAILED = "RAW_CDXJ_ACCESS_PATH_EXECUTION_FAILED"
DATA_HOST = "data.commoncrawl.org"
CRAWL_RE = re.compile(r"CC-MAIN-\d{4}-\d{2}\Z")
CDX_SHARD_RE = re.compile(r"cdx-\d{5}\.gz\Z")
TIMESTAMP_RE = re.compile(r"\d{14}\Z")
CONTENT_RANGE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+)\Z", re.I)
FORBIDDEN_ENV = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
    "all_proxy", "COOKIE", "COOKIES", "AUTHORIZATION",
    "PROXY_AUTHORIZATION",
)


class ProbeError(RuntimeError):
    """Fail-closed probe error."""


@dataclass(frozen=True)
class RangeResponse:
    url: str
    start: int
    end: int
    total_size: int
    status: int
    headers: Mapping[str, str]
    body: bytes


class RangeTransport(Protocol):
    def read(self, url: str, start: int, end: int) -> RangeResponse: ...


@dataclass(frozen=True)
class ClusterBlock:
    first_urlkey: str
    first_timestamp: str
    shard: str
    offset: int
    length: int
    record_count: int
    raw_line: str

    @property
    def sort_key(self) -> str:
        return f"{self.first_urlkey} {self.first_timestamp}"


@dataclass(frozen=True)
class TextLine:
    start: int
    end: int
    text: str


def _validate_data_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != DATA_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
    ):
        raise ProbeError("URL escaped frozen Common Crawl data host")


def normalized_okx_url(value: Any) -> str:
    if not isinstance(value, str):
        raise ProbeError("target URL must be a string")
    parsed = urllib.parse.urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"www.okx.com", "okx.com"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ProbeError("target URL escaped frozen official OKX URL scope")
    path = parsed.path or "/"
    if not path.startswith("/help/") or not re.fullmatch(r"/[a-z0-9_./-]+", path):
        raise ProbeError("target URL path is outside frozen ASCII Help Center scope")
    return f"https://www.okx.com{path.rstrip('/') or '/'}"


def exact_okx_surt(value: Any) -> str:
    normalized = normalized_okx_url(value)
    path = urllib.parse.urlsplit(normalized).path
    return f"com,okx){path}"


def parse_cluster_line(line: str) -> ClusterBlock:
    fields = line.rstrip("\r\n").split("\t")
    if len(fields) != 5:
        raise ProbeError("cluster line field count mismatch")
    key_timestamp = fields[0].rsplit(" ", 1)
    if len(key_timestamp) != 2:
        raise ProbeError("cluster line lacks key/timestamp")
    urlkey, timestamp = key_timestamp
    shard = fields[1]
    try:
        offset, length, count = map(int, fields[2:])
    except ValueError as exc:
        raise ProbeError("cluster line numeric field invalid") from exc
    if (
        not urlkey
        or TIMESTAMP_RE.fullmatch(timestamp) is None
        or CDX_SHARD_RE.fullmatch(shard) is None
        or offset < 0
        or length <= 0
        or count <= 0
    ):
        raise ProbeError("cluster line value outside frozen contract")
    return ClusterBlock(urlkey, timestamp, shard, offset, length, count, line.rstrip("\r\n"))


def parse_cdxj_line(line: str) -> tuple[str, str, dict[str, Any]]:
    parts = line.rstrip("\r\n").split(" ", 2)
    if len(parts) != 3 or TIMESTAMP_RE.fullmatch(parts[1]) is None:
        raise ProbeError("CDXJ line header invalid")
    try:
        payload = json.loads(parts[2])
    except json.JSONDecodeError as exc:
        raise ProbeError("CDXJ JSON invalid") from exc
    if not isinstance(payload, dict):
        raise ProbeError("CDXJ payload is not an object")
    return parts[0], parts[1], payload


def _cluster_url(crawl: str) -> str:
    if CRAWL_RE.fullmatch(crawl) is None:
        raise ProbeError("invalid crawl identifier")
    return f"https://{DATA_HOST}/cc-index/collections/{crawl}/indexes/cluster.idx"


def _cdx_url(crawl: str, shard: str) -> str:
    if CRAWL_RE.fullmatch(crawl) is None or CDX_SHARD_RE.fullmatch(shard) is None:
        raise ProbeError("invalid CDX object identity")
    return f"https://{DATA_HOST}/cc-index/collections/{crawl}/indexes/{shard}"


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(_canonical_json_bytes(value))
    temporary.replace(path)


def _load_inventory(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProbeError(f"inventory load failed: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("stage") != STAGE:
        raise ProbeError("inventory identity mismatch")
    for key in (
        "direct_okx_access_authorized", "warc_retrieval_authorized",
        "article_expansion_authorized", "third_full_capture_authorized",
        "implementation_authorized", "economic_data_access_authorized",
    ):
        if value.get(key) is not False:
            raise ProbeError(f"inventory improperly authorizes {key}")
    if value.get("paper_state") != "PAPER_CLOSED" or value.get("shadow_state") != "SHADOW_CLOSED" or value.get("live_state") != "LIVE_FORBIDDEN":
        raise ProbeError("inventory safety-state drift")
    targets = value.get("targets")
    if not isinstance(targets, list) or len(targets) != 7:
        raise ProbeError("inventory must freeze exactly seven targets")
    query_count = 0
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ProbeError("inventory target is not an object")
        target_id = target.get("target_id")
        if not isinstance(target_id, str) or not target_id or target_id in seen:
            raise ProbeError("inventory target identity invalid")
        seen.add(target_id)
        normalized_okx_url(target.get("url"))
        crawls = target.get("crawl_indexes")
        if not isinstance(crawls, list) or not crawls:
            raise ProbeError("inventory target crawl list invalid")
        for crawl in crawls:
            if not isinstance(crawl, str) or CRAWL_RE.fullmatch(crawl) is None:
                raise ProbeError("inventory crawl identifier invalid")
            query_count += 1
    if query_count != 23:
        raise ProbeError("inventory must freeze exactly 23 target/crawl queries")
    return value


def _validate_environment() -> None:
    present = sorted(name for name in FORBIDDEN_ENV if os.environ.get(name))
    if present:
        raise ProbeError("forbidden network state present: " + ",".join(present))
