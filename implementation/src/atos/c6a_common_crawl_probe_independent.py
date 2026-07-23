"""Physically separate reviewer for the C6A Common Crawl coverage probe.

The reviewer imports no producer, HTTP, WARC, or parser code. It reads only the
retained inventory, result, record metadata, and raw files; then independently
recomputes exact target coverage, GLOBAL proof, file hashes, and safety state.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse


STAGE = "C6A_COMMON_CRAWL_OFFICIAL_SOURCE_COVERAGE_PROBE"
RESULT_AVAILABLE = "COMMON_CRAWL_OFFICIAL_BYTES_AVAILABLE"
RESULT_INSUFFICIENT = "COMMON_CRAWL_COVERAGE_INSUFFICIENT"
_GLOBAL_SITE_RE = re.compile(
    r'["\']siteList["\']\s*:\s*\[\s*["\']OKX_GLOBAL["\']',
    re.IGNORECASE,
)
_LOCALE_HELP_RE = re.compile(
    r"^/[a-z]{2,3}(?:-[a-z]{2,4})?/help(?:/|$)", re.IGNORECASE
)


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


def _load_object(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"{path.name} missing")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path.name} unreadable: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name} root is not an object")
        return {}
    return value


def _normalized_official_url(value: Any) -> str | None:
    parsed = urlparse(str(value))
    path = parsed.path.rstrip("/") or "/"
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != "www.okx.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (not path.startswith("/help/") and path != "/help")
        or _LOCALE_HELP_RE.match(path)
    ):
        return None
    return f"https://www.okx.com{path}"


def _hash_matches(
    root: Path,
    relative: Any,
    size: Any,
    digest: Any,
    errors: list[str],
    label: str,
) -> bytes | None:
    if (
        not isinstance(relative, str)
        or not relative
        or relative.startswith("/")
        or ".." in Path(relative).parts
    ):
        errors.append(f"{label} path is unsafe")
        return None
    path = root / relative
    if not path.is_file():
        errors.append(f"{label} file missing: {relative}")
        return None
    data = path.read_bytes()
    if size != len(data):
        errors.append(f"{label} size mismatch: {relative}")
    if digest != hashlib.sha256(data).hexdigest():
        errors.append(f"{label} SHA-256 mismatch: {relative}")
    return data


def _prove_body(
    body: bytes,
    target: Mapping[str, Any],
    errors: list[str],
    label: str,
) -> bool:
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        errors.append(f"{label} official HTML is not UTF-8")
        return False
    expected = _normalized_official_url(target.get("url"))
    parser = _EvidenceHTMLParser()
    parser.feed(text)
    canonicals = [
        _normalized_official_url(value) for value in parser.canonicals
    ]
    og_urls = [_normalized_official_url(value) for value in parser.og_urls]
    if expected is None or expected not in canonicals:
        errors.append(f"{label} canonical URL mismatch")
        return False
    if og_urls and expected not in og_urls:
        errors.append(f"{label} og:url mismatch")
        return False
    if _GLOBAL_SITE_RE.search(text) is None:
        errors.append(f"{label} lacks explicit OKX_GLOBAL marker")
        return False
    markers = target.get("required_markers")
    if not isinstance(markers, list) or not markers:
        errors.append(f"{label} required markers missing from inventory")
        return False
    folded = html.unescape(text).casefold()
    missing = [
        str(marker)
        for marker in markers
        if str(marker).casefold() not in folded
    ]
    if missing:
        errors.append(f"{label} target-specific markers missing: {missing}")
        return False
    return True


def review_probe(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    inventory = _load_object(root / "inventory_snapshot.json", errors)
    result = _load_object(root / "probe_result.json", errors)

    if inventory.get("schema_version") != 1 or inventory.get("stage") != STAGE:
        errors.append("inventory identity drift")
    if result.get("schema_version") != 1 or result.get("stage") != STAGE:
        errors.append("probe result identity drift")
    inventory_bytes = (
        json.dumps(
            inventory,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    if result.get("inventory_sha256") != hashlib.sha256(
        inventory_bytes
    ).hexdigest():
        errors.append("inventory snapshot digest mismatch")

    targets_raw = inventory.get("targets")
    targets: dict[str, Mapping[str, Any]] = {}
    expected_queries: set[tuple[str, str]] = set()
    if not isinstance(targets_raw, list) or not targets_raw:
        errors.append("inventory targets missing")
    else:
        for row in targets_raw:
            if not isinstance(row, Mapping):
                errors.append("inventory target row is invalid")
                continue
            target_id = str(row.get("target_id", ""))
            target_url = _normalized_official_url(row.get("url"))
            if not target_id or target_id in targets or target_url is None:
                errors.append(
                    f"inventory target invalid or duplicated: {target_id}"
                )
                continue
            crawls = row.get("crawl_indexes")
            if not isinstance(crawls, list) or not crawls:
                errors.append(
                    f"inventory crawl coverage missing: {target_id}"
                )
                continue
            targets[target_id] = row
            for crawl_id in crawls:
                if re.fullmatch(
                    r"CC-MAIN-\d{4}-\d{2}", str(crawl_id)
                ) is None:
                    errors.append(
                        f"invalid crawl ID in inventory: {crawl_id}"
                    )
                expected_queries.add((target_id, str(crawl_id)))

    query_rows = result.get("query_results")
    observed_queries: set[tuple[str, str]] = set()
    if not isinstance(query_rows, list):
        errors.append("query result rows missing")
        query_rows = []
    for row in query_rows:
        if not isinstance(row, Mapping):
            errors.append("query result row is invalid")
            continue
        key = (
            str(row.get("target_id", "")),
            str(row.get("crawl_id", "")),
        )
        if key in observed_queries:
            errors.append(f"duplicate query result: {key}")
        observed_queries.add(key)
        parsed = urlparse(str(row.get("query_url", "")))
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            parsed.scheme != "https"
            or (parsed.hostname or "").lower()
            != "index.commoncrawl.org"
            or re.fullmatch(
                r"/CC-MAIN-\d{4}-\d{2}-index", parsed.path
            )
            is None
            or set(query) != {"url", "output", "matchType", "filter"}
            or query.get("output") != ["json"]
            or query.get("matchType") != ["exact"]
            or query.get("filter") != ["status:200"]
            or _normalized_official_url((query.get("url") or [""])[0])
            != _normalized_official_url(row.get("target_url"))
        ):
            errors.append(
                f"query escaped Common Crawl index boundary: {key}"
            )
        if row.get("status") == "PASS":
            _hash_matches(
                root,
                row.get("raw_index_path"),
                row.get("raw_index_size"),
                row.get("raw_index_sha256"),
                errors,
                f"query {key} raw index",
            )
    if observed_queries != expected_queries:
        errors.append("exact target/crawl query coverage mismatch")
    if result.get("query_count") != len(expected_queries):
        errors.append("query count mismatch")

    covered: set[str] = set()
    record_rows = result.get("record_results")
    if not isinstance(record_rows, list):
        errors.append("record result rows missing")
        record_rows = []
    seen_metadata: set[str] = set()
    for index, row in enumerate(record_rows):
        label = f"record[{index}]"
        if not isinstance(row, Mapping):
            errors.append(f"{label} is invalid")
            continue
        target_id = str(row.get("target_id", ""))
        target = targets.get(target_id)
        if target is None:
            errors.append(f"{label} references unknown target")
            continue
        target_url = _normalized_official_url(target.get("url"))
        if _normalized_official_url(row.get("target_url")) != target_url:
            errors.append(f"{label} target URL mismatch")
        if _normalized_official_url(row.get("warc_target_uri")) != target_url:
            errors.append(f"{label} WARC target URI mismatch")
        data_url = urlparse(str(row.get("data_url", "")))
        if (
            data_url.scheme != "https"
            or (data_url.hostname or "").lower()
            != "data.commoncrawl.org"
            or not data_url.path.endswith(".warc.gz")
        ):
            errors.append(f"{label} data URL escaped Common Crawl")
        metadata_path = row.get("metadata_path")
        if isinstance(metadata_path, str):
            if metadata_path in seen_metadata:
                errors.append(f"{label} duplicate metadata path")
            seen_metadata.add(metadata_path)
            metadata = _load_object(root / metadata_path, errors)
            comparable = dict(row)
            comparable.pop("metadata_path", None)
            if metadata != comparable:
                errors.append(
                    f"{label} metadata file does not equal result row"
                )
        else:
            errors.append(f"{label} metadata path missing")

        _hash_matches(
            root,
            row.get("compressed_path"),
            row.get("compressed_size"),
            row.get("compressed_sha256"),
            errors,
            f"{label} compressed WARC",
        )
        _hash_matches(
            root,
            row.get("record_path"),
            row.get("record_size"),
            row.get("record_sha256"),
            errors,
            f"{label} decompressed WARC",
        )
        body = _hash_matches(
            root,
            row.get("body_path"),
            row.get("body_size"),
            row.get("body_sha256"),
            errors,
            f"{label} official body",
        )
        independently_usable = bool(
            body is not None
            and row.get("range_http_status") == 206
            and row.get("http_status") == 200
            and _prove_body(body, target, errors, label)
        )
        if (
            row.get("usable_official_global_bytes")
            is not independently_usable
        ):
            errors.append(
                f"{label} producer/reviewer usability mismatch"
            )
        if independently_usable:
            covered.add(target_id)

    target_ids = set(targets)
    missing = sorted(target_ids - covered)
    recomputed_status = "PASS" if not missing else "FAIL"
    recomputed_result = (
        RESULT_AVAILABLE
        if recomputed_status == "PASS"
        else RESULT_INSUFFICIENT
    )
    if result.get("covered_target_ids") != sorted(covered):
        errors.append("covered target IDs mismatch")
    if result.get("missing_target_ids") != missing:
        errors.append("missing target IDs mismatch")
    if result.get("status") != recomputed_status:
        errors.append("producer/reviewer probe status mismatch")
    if result.get("result") != recomputed_result:
        errors.append("producer/reviewer probe result mismatch")
    if result.get("target_count") != len(targets):
        errors.append("target count mismatch")
    if result.get("archive_carrier") != "COMMON_CRAWL":
        errors.append("archive-carrier identity drift")
    if (
        result.get("authority_source")
        != "OFFICIAL_OKX_HTTP_RESPONSE_BYTES"
    ):
        errors.append("authority-source identity drift")

    for payload_name, payload in (
        ("inventory", inventory),
        ("result", result),
    ):
        for key in (
            "article_expansion_authorized",
            "third_full_capture_authorized",
            "implementation_authorized",
            "economic_data_access_authorized",
        ):
            if payload.get(key) is not False:
                errors.append(
                    f"{payload_name} improperly authorizes {key}"
                )
        if payload.get("paper_state") != "PAPER_CLOSED":
            errors.append(f"{payload_name} paper-state drift")
        if payload.get("shadow_state") != "SHADOW_CLOSED":
            errors.append(f"{payload_name} shadow-state drift")
        if payload.get("live_state") != "LIVE_FORBIDDEN":
            errors.append(f"{payload_name} live-state drift")

    return {
        "schema_version": 1,
        "stage": f"{STAGE}_INDEPENDENT_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "probe_status_recomputed": recomputed_status,
        "probe_result_recomputed": recomputed_result,
        "covered_target_ids_recomputed": sorted(covered),
        "missing_target_ids_recomputed": missing,
        "errors": errors,
        "article_expansion_authorized": False,
        "third_full_capture_authorized": False,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
