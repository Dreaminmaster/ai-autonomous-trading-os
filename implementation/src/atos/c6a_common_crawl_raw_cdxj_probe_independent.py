"""Physically separate reviewer for the raw Common Crawl CDXJ access probe.

The reviewer imports no producer, HTTP client, binary-search, or gzip-selection
code. It reads retained files only and independently recomputes the exact frozen
query matrix, narrow SURT keys, hashes, CDXJ matches, and safety state.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

STAGE = "C6A_COMMON_CRAWL_RAW_CDXJ_ACCESS_PROBE"
RESULT_VERIFIED = "RAW_CDXJ_ACCESS_PATH_VERIFIED"
RESULT_FAILED = "RAW_CDXJ_ACCESS_PATH_EXECUTION_FAILED"
CRAWL_RE = re.compile(r"CC-MAIN-\d{4}-\d{2}\Z")
TIMESTAMP_RE = re.compile(r"\d{14}\Z")
CDX_SHARD_RE = re.compile(r"cdx-\d{5}\.gz\Z")


def _load(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load {path.name}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name} is not an object")
        return {}
    return value


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _official_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
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
        return None
    path = parsed.path or "/"
    if not path.startswith("/help/") or re.fullmatch(r"/[a-z0-9_./-]+", path) is None:
        return None
    return f"https://www.okx.com{path.rstrip('/') or '/'}"


def _surt(value: Any) -> str | None:
    normalized = _official_url(value)
    if normalized is None:
        return None
    return "com,okx)" + urllib.parse.urlsplit(normalized).path


def _hash_file(root: Path, relative: Any, size: Any, digest: Any, errors: list[str], label: str) -> bytes | None:
    if not isinstance(relative, str) or not relative or relative.startswith("/") or ".." in Path(relative).parts:
        errors.append(f"{label} path unsafe")
        return None
    path = root / relative
    if not path.is_file():
        errors.append(f"{label} missing: {relative}")
        return None
    data = path.read_bytes()
    if size != len(data):
        errors.append(f"{label} size mismatch: {relative}")
    if digest != hashlib.sha256(data).hexdigest():
        errors.append(f"{label} hash mismatch: {relative}")
    return data


def _parse_cluster(line: Any) -> tuple[str, str, str, int, int] | None:
    if not isinstance(line, str):
        return None
    fields = line.split("\t")
    if len(fields) != 5:
        return None
    first = fields[0].rsplit(" ", 1)
    if len(first) != 2 or TIMESTAMP_RE.fullmatch(first[1]) is None or CDX_SHARD_RE.fullmatch(fields[1]) is None:
        return None
    try:
        offset, length, count = map(int, fields[2:])
    except ValueError:
        return None
    if offset < 0 or length <= 0 or count <= 0:
        return None
    return first[0], first[1], fields[1], offset, length


def _parse_cdx(line: str) -> tuple[str, str, dict[str, Any]] | None:
    parts = line.split(" ", 2)
    if len(parts) != 3 or TIMESTAMP_RE.fullmatch(parts[1]) is None:
        return None
    try:
        payload = json.loads(parts[2])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return parts[0], parts[1], payload


def review_probe(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    inventory = _load(root / "inventory_snapshot.json", errors)
    result = _load(root / "probe_result.json", errors)
    evidence = _load(root / "range_evidence.json", errors)
    if inventory.get("schema_version") != 1 or inventory.get("stage") != STAGE:
        errors.append("inventory identity mismatch")
    if result.get("schema_version") != 1 or result.get("stage") != STAGE:
        errors.append("result identity mismatch")
    if result.get("inventory_sha256") != hashlib.sha256(_canonical(inventory)).hexdigest():
        errors.append("inventory hash mismatch")

    expected: dict[str, tuple[str, str, str]] = {}
    targets = inventory.get("targets")
    if not isinstance(targets, list) or len(targets) != 7:
        errors.append("frozen target count mismatch")
        targets = []
    for target in targets:
        if not isinstance(target, Mapping):
            errors.append("invalid target row")
            continue
        target_id = str(target.get("target_id", ""))
        url = _official_url(target.get("url"))
        surt = _surt(target.get("url"))
        crawls = target.get("crawl_indexes")
        if not target_id or url is None or surt is None or not isinstance(crawls, list):
            errors.append(f"invalid target: {target_id}")
            continue
        for crawl in crawls:
            if not isinstance(crawl, str) or CRAWL_RE.fullmatch(crawl) is None:
                errors.append(f"invalid crawl: {crawl}")
                continue
            expected[f"{target_id}--{crawl}"] = (url, surt, crawl)
    if len(expected) != 23:
        errors.append("frozen query matrix is not 23 rows")

    request_rows = evidence.get("requests")
    if not isinstance(request_rows, list) or evidence.get("request_count") != len(request_rows):
        errors.append("range evidence list/count mismatch")
        request_rows = []
    seen_sequences: set[int] = set()
    for row in request_rows:
        if not isinstance(row, Mapping):
            errors.append("invalid range evidence row")
            continue
        sequence = row.get("sequence")
        if not isinstance(sequence, int) or sequence in seen_sequences:
            errors.append("range evidence sequence invalid")
        else:
            seen_sequences.add(sequence)
        parsed = urllib.parse.urlsplit(str(row.get("url", "")))
        if parsed.scheme != "https" or parsed.hostname != "data.commoncrawl.org" or parsed.username or parsed.password or parsed.port or parsed.fragment:
            errors.append(f"range URL escaped data host: {sequence}")
        start, end, total = row.get("start"), row.get("end"), row.get("total_size")
        if not all(isinstance(x, int) for x in (start, end, total)) or start < 0 or end < start or total <= end:
            errors.append(f"range coordinates invalid: {sequence}")
        if row.get("status") != 206 or row.get("content_range") != f"bytes {start}-{end}/{total}":
            errors.append(f"range protocol mismatch: {sequence}")
        _hash_file(root, row.get("path"), row.get("size"), row.get("sha256"), errors, f"range[{sequence}]")

    queries = result.get("queries")
    if not isinstance(queries, list):
        errors.append("result queries missing")
        queries = []
    observed: set[str] = set()
    hit_ids: list[str] = []
    for query in queries:
        if not isinstance(query, Mapping):
            errors.append("invalid query result row")
            continue
        query_id = str(query.get("query_id", ""))
        if query_id in observed:
            errors.append(f"duplicate query: {query_id}")
        observed.add(query_id)
        expected_row = expected.get(query_id)
        if expected_row is None:
            errors.append(f"unexpected query: {query_id}")
            continue
        url, surt, crawl = expected_row
        if query.get("target_url") != url or query.get("target_surt") != surt or query.get("crawl_id") != crawl or query.get("status") != "PASS":
            errors.append(f"query identity/status mismatch: {query_id}")
        cluster = urllib.parse.urlsplit(str(query.get("cluster_url", "")))
        expected_cluster_path = f"/cc-index/collections/{crawl}/indexes/cluster.idx"
        if cluster.scheme != "https" or cluster.hostname != "data.commoncrawl.org" or cluster.path != expected_cluster_path:
            errors.append(f"cluster URL mismatch: {query_id}")
        upper = _parse_cluster(query.get("upper_boundary_cluster_line"))
        if upper is None:
            errors.append(f"upper boundary invalid: {query_id}")
        blocks = query.get("selected_blocks")
        if not isinstance(blocks, list) or not blocks or len(blocks) > int(inventory.get("max_cdx_blocks_per_query", 0)):
            errors.append(f"selected block count invalid: {query_id}")
            blocks = []
        recomputed_rows: list[dict[str, Any]] = []
        last_cluster_key = ""
        for block_index, block in enumerate(blocks):
            if not isinstance(block, Mapping):
                errors.append(f"invalid block row: {query_id}:{block_index}")
                continue
            parsed_cluster = _parse_cluster(block.get("cluster_line"))
            if parsed_cluster is None:
                errors.append(f"cluster line invalid: {query_id}:{block_index}")
                continue
            first_key, first_ts, shard, offset, length = parsed_cluster
            sort_key = f"{first_key} {first_ts}"
            if last_cluster_key and sort_key <= last_cluster_key:
                errors.append(f"cluster block order invalid: {query_id}")
            last_cluster_key = sort_key
            if block.get("shard") != shard or block.get("offset") != offset or block.get("length") != length:
                errors.append(f"cluster/block locator mismatch: {query_id}:{block_index}")
            data = _hash_file(
                root,
                block.get("decompressed_path"),
                block.get("decompressed_size"),
                block.get("decompressed_sha256"),
                errors,
                f"block[{query_id}:{block_index}]",
            )
            if data is None:
                continue
            try:
                lines = [line for line in data.decode("utf-8").splitlines() if line]
            except UnicodeDecodeError:
                errors.append(f"block not UTF-8: {query_id}:{block_index}")
                continue
            if block.get("line_count") != len(lines) or not lines:
                errors.append(f"block line count invalid: {query_id}:{block_index}")
                continue
            first = _parse_cdx(lines[0])
            if first is None or (first[0], first[1]) != (first_key, first_ts):
                errors.append(f"block first line mismatch: {query_id}:{block_index}")
            block_exact = 0
            for line in lines:
                parsed_line = _parse_cdx(line)
                if parsed_line is None:
                    errors.append(f"malformed CDXJ line: {query_id}:{block_index}")
                    continue
                urlkey, timestamp, payload = parsed_line
                captured = _official_url(payload.get("url"))
                if urlkey != surt or captured != url or str(payload.get("status")) != "200":
                    continue
                try:
                    warc_offset = int(payload.get("offset"))
                    warc_length = int(payload.get("length"))
                except (TypeError, ValueError):
                    errors.append(f"matching row WARC locator invalid: {query_id}")
                    continue
                filename = payload.get("filename")
                if not isinstance(filename, str) or not filename.startswith(f"crawl-data/{crawl}/") or not filename.endswith(".warc.gz") or warc_offset < 0 or warc_length <= 0:
                    errors.append(f"matching row escaped frozen crawl: {query_id}")
                    continue
                recomputed_rows.append({
                    "urlkey": urlkey,
                    "timestamp": timestamp,
                    "url": captured,
                    "status": "200",
                    "digest": payload.get("digest"),
                    "filename": filename,
                    "offset": warc_offset,
                    "length": warc_length,
                    "source_block_path": block.get("decompressed_path"),
                    "raw_line_sha256": hashlib.sha256((line + "\n").encode()).hexdigest(),
                })
                block_exact += 1
            if block.get("exact_row_count") != block_exact:
                errors.append(f"block exact-row count mismatch: {query_id}:{block_index}")
        if query.get("exact_rows") != recomputed_rows or query.get("exact_row_count") != len(recomputed_rows):
            errors.append(f"query exact rows mismatch: {query_id}")
        if recomputed_rows:
            hit_ids.append(query_id)
        query_path = root / f"queries/{query_id}/query.json"
        query_copy = _load(query_path, errors)
        if query_copy != query:
            errors.append(f"retained query file mismatch: {query_id}")

    producer_errors = result.get("errors")
    expected_status = "PASS" if observed == set(expected) and not producer_errors else "FAIL"
    expected_result = RESULT_VERIFIED if expected_status == "PASS" else RESULT_FAILED
    if result.get("status") != expected_status or result.get("result") != expected_result:
        errors.append("producer status/result mismatch")
    if result.get("completed_query_count") != len(queries) or result.get("failed_query_count") != (len(producer_errors) if isinstance(producer_errors, list) else -1):
        errors.append("producer query counts mismatch")
    if result.get("hit_query_ids") != hit_ids or result.get("hit_query_count") != len(hit_ids):
        errors.append("producer hit inventory mismatch")

    for payload_name, payload in (("inventory", inventory), ("result", result)):
        for key in (
            "direct_okx_access_authorized", "warc_retrieval_authorized",
            "article_expansion_authorized", "third_full_capture_authorized",
            "implementation_authorized", "economic_data_access_authorized",
        ):
            if payload.get(key) is not False:
                errors.append(f"{payload_name} improperly authorizes {key}")
        if payload.get("paper_state") != "PAPER_CLOSED" or payload.get("shadow_state") != "SHADOW_CLOSED" or payload.get("live_state") != "LIVE_FORBIDDEN":
            errors.append(f"{payload_name} safety-state drift")

    return {
        "schema_version": 1,
        "stage": STAGE,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "probe_status_recomputed": expected_status,
        "probe_result_recomputed": expected_result,
        "query_ids_recomputed": sorted(observed),
        "hit_query_ids_recomputed": hit_ids,
        "direct_okx_access_authorized": False,
        "warc_retrieval_authorized": False,
        "article_expansion_authorized": False,
        "third_full_capture_authorized": False,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
