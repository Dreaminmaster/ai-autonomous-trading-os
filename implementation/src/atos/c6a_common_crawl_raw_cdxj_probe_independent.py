"""Physically separate reviewer for the raw Common Crawl CDXJ access probe.

The reviewer imports no producer, HTTP client, binary-search, block-selection,
or gzip execution code. It reads retained files only and independently
recomputes the frozen query matrix, byte-range bindings, block selection, CDXJ
matches, and safety state.
"""
from __future__ import annotations

import gzip
import hashlib
import io
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
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode()


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
    if (
        not path.startswith("/help/")
        or re.fullmatch(r"/[a-z0-9_./-]+", path) is None
    ):
        return None
    return f"https://www.okx.com{path.rstrip('/') or '/'}"


def _surt(value: Any) -> str | None:
    normalized = _official_url(value)
    if normalized is None:
        return None
    return "com,okx)" + urllib.parse.urlsplit(normalized).path


def _hash_file(
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


def _parse_cluster(
    line: Any,
) -> tuple[str, str, str, int, int, int] | None:
    if not isinstance(line, str):
        return None
    fields = line.split("\t")
    if len(fields) != 5:
        return None
    first = fields[0].rsplit(" ", 1)
    if (
        len(first) != 2
        or TIMESTAMP_RE.fullmatch(first[1]) is None
        or CDX_SHARD_RE.fullmatch(fields[1]) is None
    ):
        return None
    try:
        offset, length, count = map(int, fields[2:])
    except ValueError:
        return None
    if offset < 0 or length <= 0 or count <= 0:
        return None
    return first[0], first[1], fields[1], offset, length, count


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


def _complete_lines(
    data: bytes,
    start: int,
    end: int,
    total: int,
) -> list[str]:
    begin = 0
    finish = len(data)
    if start > 0:
        first_break = data.find(b"\n")
        if first_break < 0:
            return []
        begin = first_break + 1
    if end < total - 1:
        last_break = data.rfind(b"\n")
        if last_break < begin:
            return []
        finish = last_break + 1
    try:
        return [
            line
            for line in data[begin:finish].decode("utf-8").splitlines()
            if line
        ]
    except UnicodeDecodeError:
        return []


def _contains_contiguous(
    haystack: list[str],
    needle: list[str],
) -> bool:
    if not needle or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(
        haystack[index : index + width] == needle
        for index in range(len(haystack) - width + 1)
    )


def _expected_block_selection(
    context_lines: list[str],
    target_surt: str,
    maximum: int,
) -> tuple[list[str], str] | None:
    parsed: list[
        tuple[str, tuple[str, str, str, int, int, int]]
    ] = []
    for line in context_lines:
        row = _parse_cluster(line)
        if row is None:
            return None
        parsed.append((line, row))
    sort_keys = [f"{row[0]} {row[1]}" for _, row in parsed]
    if (
        sort_keys != sorted(sort_keys)
        or len(sort_keys) != len(set(sort_keys))
    ):
        return None
    low = f"{target_surt} 00000000000000"
    high = f"{target_surt} 99999999999999"
    predecessors = [
        index
        for index, sort_key in enumerate(sort_keys)
        if sort_key <= low
    ]
    anchor = predecessors[-1] if predecessors else 0
    selected: list[str] = []
    upper = ""
    for index in range(anchor, len(parsed)):
        line, row = parsed[index]
        sort_key = f"{row[0]} {row[1]}"
        if selected and sort_key > high:
            upper = line
            break
        selected.append(line)
        if len(selected) > maximum:
            return None
    if not selected or not upper:
        return None
    first_row = _parse_cluster(selected[0])
    if first_row is None or f"{first_row[0]} {first_row[1]}" > low:
        return None
    upper_row = _parse_cluster(upper)
    if (
        upper_row is None
        or f"{upper_row[0]} {upper_row[1]}" <= high
    ):
        return None
    return selected, upper


def review_probe(root: Path) -> dict[str, Any]:
    errors: list[str] = []
    inventory = _load(root / "inventory_snapshot.json", errors)
    result = _load(root / "probe_result.json", errors)
    evidence = _load(root / "range_evidence.json", errors)
    if (
        inventory.get("schema_version") != 1
        or inventory.get("stage") != STAGE
    ):
        errors.append("inventory identity mismatch")
    if (
        result.get("schema_version") != 1
        or result.get("stage") != STAGE
    ):
        errors.append("result identity mismatch")
    if result.get("inventory_sha256") != hashlib.sha256(
        _canonical(inventory)
    ).hexdigest():
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
        if (
            not target_id
            or url is None
            or surt is None
            or not isinstance(crawls, list)
        ):
            errors.append(f"invalid target: {target_id}")
            continue
        for crawl in crawls:
            if (
                not isinstance(crawl, str)
                or CRAWL_RE.fullmatch(crawl) is None
            ):
                errors.append(f"invalid crawl: {crawl}")
                continue
            expected[f"{target_id}--{crawl}"] = (
                url,
                surt,
                crawl,
            )
    if len(expected) != 23:
        errors.append("frozen query matrix is not 23 rows")

    request_rows = evidence.get("requests")
    if (
        not isinstance(request_rows, list)
        or evidence.get("request_count") != len(request_rows)
    ):
        errors.append("range evidence list/count mismatch")
        request_rows = []
    seen_sequences: set[int] = set()
    range_by_locator: dict[
        tuple[str, int, int], tuple[Mapping[str, Any], bytes]
    ] = {}
    ranges_by_url: dict[
        str, list[tuple[Mapping[str, Any], bytes]]
    ] = {}
    object_identity: dict[str, tuple[int, Any]] = {}
    for row in request_rows:
        if not isinstance(row, Mapping):
            errors.append("invalid range evidence row")
            continue
        sequence = row.get("sequence")
        if (
            not isinstance(sequence, int)
            or sequence in seen_sequences
        ):
            errors.append("range evidence sequence invalid")
        else:
            seen_sequences.add(sequence)
        url = str(row.get("url", ""))
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "data.commoncrawl.org"
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.fragment
        ):
            errors.append(f"range URL escaped data host: {sequence}")
        start = row.get("start")
        end = row.get("end")
        total = row.get("total_size")
        if (
            not all(
                isinstance(value, int)
                for value in (start, end, total)
            )
            or start < 0
            or end < start
            or total <= end
        ):
            errors.append(f"range coordinates invalid: {sequence}")
            continue
        if (
            row.get("status") != 206
            or row.get("content_range")
            != f"bytes {start}-{end}/{total}"
        ):
            errors.append(f"range protocol mismatch: {sequence}")
        data = _hash_file(
            root,
            row.get("path"),
            row.get("size"),
            row.get("sha256"),
            errors,
            f"range[{sequence}]",
        )
        if data is None:
            continue
        identity = (total, row.get("etag"))
        prior = object_identity.get(url)
        if prior is not None and prior != identity:
            errors.append(f"remote object identity drift: {url}")
        object_identity[url] = identity
        locator = (url, start, end)
        if locator in range_by_locator:
            errors.append(f"duplicate retained range: {locator}")
        range_by_locator[locator] = (row, data)
        ranges_by_url.setdefault(url, []).append((row, data))

    producer_errors = result.get("errors")
    if not isinstance(producer_errors, list):
        errors.append("producer error list missing")
        producer_errors = []
    failed_ids: list[str] = []
    for row in producer_errors:
        if not isinstance(row, Mapping):
            errors.append("producer error row invalid")
            continue
        query_id = str(row.get("query_id", ""))
        if query_id not in expected or query_id in failed_ids:
            errors.append(
                f"producer error identity invalid: {query_id}"
            )
        else:
            failed_ids.append(query_id)
        if (
            not isinstance(row.get("error_type"), str)
            or not isinstance(row.get("error"), str)
        ):
            errors.append(
                f"producer error detail invalid: {query_id}"
            )

    queries = result.get("queries")
    if not isinstance(queries, list):
        errors.append("result queries missing")
        queries = []
    observed: set[str] = set()
    hit_ids: list[str] = []
    maximum_blocks = int(
        inventory.get("max_cdx_blocks_per_query", 0)
    )
    maximum_decompressed = int(
        inventory.get("max_decompressed_cdx_block_bytes", 0)
    )
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
        if (
            query.get("target_url") != url
            or query.get("target_surt") != surt
            or query.get("crawl_id") != crawl
            or query.get("status") != "PASS"
        ):
            errors.append(
                f"query identity/status mismatch: {query_id}"
            )
        cluster_url = str(query.get("cluster_url", ""))
        cluster = urllib.parse.urlsplit(cluster_url)
        expected_cluster_path = (
            f"/cc-index/collections/{crawl}/indexes/cluster.idx"
        )
        if (
            cluster.scheme != "https"
            or cluster.hostname != "data.commoncrawl.org"
            or cluster.path != expected_cluster_path
        ):
            errors.append(f"cluster URL mismatch: {query_id}")
        identity = object_identity.get(cluster_url)
        if (
            identity is None
            or query.get("cluster_total_size") != identity[0]
        ):
            errors.append(
                f"cluster total-size binding mismatch: {query_id}"
            )

        context_lines = query.get("cluster_context_lines")
        if (
            not isinstance(context_lines, list)
            or not all(
                isinstance(line, str) for line in context_lines
            )
        ):
            errors.append(f"cluster context missing: {query_id}")
            context_lines = []
        context_retained = False
        for range_row, range_data in ranges_by_url.get(
            cluster_url,
            [],
        ):
            retained_lines = _complete_lines(
                range_data,
                int(range_row["start"]),
                int(range_row["end"]),
                int(range_row["total_size"]),
            )
            if _contains_contiguous(
                retained_lines,
                context_lines,
            ):
                context_retained = True
                break
        if not context_retained:
            errors.append(
                f"cluster context not bound to retained bytes: {query_id}"
            )
        expected_selection = _expected_block_selection(
            context_lines,
            surt,
            maximum_blocks,
        )
        if expected_selection is None:
            errors.append(
                f"cluster selection proof invalid: {query_id}"
            )
            expected_block_lines: list[str] = []
            expected_upper = ""
        else:
            expected_block_lines, expected_upper = expected_selection
        if query.get("upper_boundary_cluster_line") != expected_upper:
            errors.append(f"upper boundary mismatch: {query_id}")

        blocks = query.get("selected_blocks")
        if (
            not isinstance(blocks, list)
            or not blocks
            or len(blocks) > maximum_blocks
        ):
            errors.append(
                f"selected block count invalid: {query_id}"
            )
            blocks = []
        observed_block_lines = [
            block.get("cluster_line")
            for block in blocks
            if isinstance(block, Mapping)
        ]
        if observed_block_lines != expected_block_lines:
            errors.append(
                f"selected block sequence mismatch: {query_id}"
            )

        recomputed_rows: list[dict[str, Any]] = []
        for block_index, block in enumerate(blocks):
            if not isinstance(block, Mapping):
                errors.append(
                    f"invalid block row: {query_id}:{block_index}"
                )
                continue
            parsed_cluster = _parse_cluster(
                block.get("cluster_line")
            )
            if parsed_cluster is None:
                errors.append(
                    f"cluster line invalid: {query_id}:{block_index}"
                )
                continue
            (
                first_key,
                first_ts,
                shard,
                offset,
                length,
                count,
            ) = parsed_cluster
            if (
                block.get("shard") != shard
                or block.get("offset") != offset
                or block.get("length") != length
                or block.get("record_count") != count
            ):
                errors.append(
                    f"cluster/block locator mismatch: "
                    f"{query_id}:{block_index}"
                )
            cdx_url = (
                "https://data.commoncrawl.org/cc-index/collections/"
                f"{crawl}/indexes/{shard}"
            )
            retained_range = range_by_locator.get(
                (cdx_url, offset, offset + length - 1)
            )
            if retained_range is None:
                errors.append(
                    f"compressed block range missing: "
                    f"{query_id}:{block_index}"
                )
                continue
            _, compressed = retained_range
            try:
                with gzip.GzipFile(
                    fileobj=io.BytesIO(compressed)
                ) as stream:
                    independently_decompressed = stream.read(
                        maximum_decompressed + 1
                    )
            except (OSError, EOFError):
                errors.append(
                    f"compressed block cannot be decompressed: "
                    f"{query_id}:{block_index}"
                )
                continue
            if len(independently_decompressed) > maximum_decompressed:
                errors.append(
                    f"decompressed block exceeds limit: "
                    f"{query_id}:{block_index}"
                )
                continue
            retained_decompressed = _hash_file(
                root,
                block.get("decompressed_path"),
                block.get("decompressed_size"),
                block.get("decompressed_sha256"),
                errors,
                f"block[{query_id}:{block_index}]",
            )
            if retained_decompressed != independently_decompressed:
                errors.append(
                    f"compressed/decompressed binding mismatch: "
                    f"{query_id}:{block_index}"
                )
            try:
                lines = [
                    line
                    for line in independently_decompressed.decode(
                        "utf-8"
                    ).splitlines()
                    if line
                ]
            except UnicodeDecodeError:
                errors.append(
                    f"block not UTF-8: {query_id}:{block_index}"
                )
                continue
            if (
                block.get("line_count") != len(lines)
                or len(lines) != count
                or not lines
            ):
                errors.append(
                    f"block line/cluster count mismatch: "
                    f"{query_id}:{block_index}"
                )
                continue
            first = _parse_cdx(lines[0])
            if (
                first is None
                or (first[0], first[1]) != (first_key, first_ts)
            ):
                errors.append(
                    f"block first line mismatch: "
                    f"{query_id}:{block_index}"
                )
            block_exact = 0
            for line in lines:
                parsed_line = _parse_cdx(line)
                if parsed_line is None:
                    errors.append(
                        f"malformed CDXJ line: "
                        f"{query_id}:{block_index}"
                    )
                    continue
                urlkey, timestamp, payload = parsed_line
                captured = _official_url(payload.get("url"))
                if (
                    urlkey != surt
                    or captured != url
                    or str(payload.get("status")) != "200"
                ):
                    continue
                try:
                    warc_offset = int(payload.get("offset"))
                    warc_length = int(payload.get("length"))
                except (TypeError, ValueError):
                    errors.append(
                        f"matching row WARC locator invalid: {query_id}"
                    )
                    continue
                filename = payload.get("filename")
                if (
                    not isinstance(filename, str)
                    or not filename.startswith(
                        f"crawl-data/{crawl}/"
                    )
                    or not filename.endswith(".warc.gz")
                    or warc_offset < 0
                    or warc_length <= 0
                ):
                    errors.append(
                        f"matching row escaped frozen crawl: {query_id}"
                    )
                    continue
                recomputed_rows.append(
                    {
                        "urlkey": urlkey,
                        "timestamp": timestamp,
                        "url": captured,
                        "status": "200",
                        "digest": payload.get("digest"),
                        "filename": filename,
                        "offset": warc_offset,
                        "length": warc_length,
                        "source_block_path": block.get(
                            "decompressed_path"
                        ),
                        "raw_line_sha256": hashlib.sha256(
                            (line + "\n").encode()
                        ).hexdigest(),
                    }
                )
                block_exact += 1
            if block.get("exact_row_count") != block_exact:
                errors.append(
                    f"block exact-row count mismatch: "
                    f"{query_id}:{block_index}"
                )
        if (
            query.get("exact_rows") != recomputed_rows
            or query.get("exact_row_count") != len(recomputed_rows)
        ):
            errors.append(f"query exact rows mismatch: {query_id}")
        if recomputed_rows:
            hit_ids.append(query_id)
        query_copy = _load(
            root / f"queries/{query_id}/query.json",
            errors,
        )
        if query_copy != query:
            errors.append(
                f"retained query file mismatch: {query_id}"
            )

    failed_set = set(failed_ids)
    if observed & failed_set:
        errors.append(
            "query appears in both completed and failed sets"
        )
    if observed | failed_set != set(expected):
        errors.append(
            "completed/failed query partition mismatch"
        )
    expected_status = "FAIL" if failed_ids or errors else "PASS"
    expected_result = (
        RESULT_FAILED if expected_status == "FAIL" else RESULT_VERIFIED
    )
    if (
        result.get("status") != expected_status
        or result.get("result") != expected_result
    ):
        errors.append("producer status/result mismatch")
    if (
        result.get("target_count") != 7
        or result.get("expected_query_count") != 23
        or result.get("completed_query_count") != len(queries)
        or result.get("failed_query_count") != len(failed_ids)
    ):
        errors.append("producer query counts mismatch")
    if (
        result.get("hit_query_ids") != hit_ids
        or result.get("hit_query_count") != len(hit_ids)
    ):
        errors.append("producer hit inventory mismatch")

    for payload_name, payload in (
        ("inventory", inventory),
        ("result", result),
    ):
        for key in (
            "direct_okx_access_authorized",
            "warc_retrieval_authorized",
            "article_expansion_authorized",
            "third_full_capture_authorized",
            "implementation_authorized",
            "economic_data_access_authorized",
        ):
            if payload.get(key) is not False:
                errors.append(
                    f"{payload_name} improperly authorizes {key}"
                )
        if (
            payload.get("paper_state") != "PAPER_CLOSED"
            or payload.get("shadow_state") != "SHADOW_CLOSED"
            or payload.get("live_state") != "LIVE_FORBIDDEN"
        ):
            errors.append(f"{payload_name} safety-state drift")

    final_probe_status = "FAIL" if errors or failed_ids else "PASS"
    final_probe_result = (
        RESULT_FAILED
        if final_probe_status == "FAIL"
        else RESULT_VERIFIED
    )
    return {
        "schema_version": 1,
        "stage": STAGE,
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "probe_status_recomputed": final_probe_status,
        "probe_result_recomputed": final_probe_result,
        "query_ids_recomputed": sorted(observed),
        "failed_query_ids_recomputed": sorted(failed_ids),
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
