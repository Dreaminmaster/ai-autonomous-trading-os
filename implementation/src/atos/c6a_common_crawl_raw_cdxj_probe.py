"""Bounded raw Common Crawl ZipNum/CDXJ access probe.

The implementation byte-range searches official Common Crawl raw index files,
retains exact metadata evidence, and stops before any WARC or OKX request.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from atos.c6a_common_crawl_raw_cdxj_core import (
    RESULT_FAILED,
    RESULT_VERIFIED,
    STAGE,
    ClusterBlock,
    ProbeError,
    RangeTransport,
    _canonical_json_bytes,
    _cdx_url,
    _cluster_url,
    _load_inventory,
    _validate_environment,
    atomic_write_json,
    exact_okx_surt,
    normalized_okx_url,
    parse_cdxj_line,
)
from atos.c6a_common_crawl_raw_cdxj_transport import (
    RecordingRangeReader,
    RemoteSortedLineIndex,
    UrllibRangeTransport,
)


def select_cluster_blocks(
    context: list[ClusterBlock],
    target_surt: str,
    maximum: int,
) -> tuple[list[ClusterBlock], str]:
    low = f"{target_surt} 00000000000000"
    high = f"{target_surt} 99999999999999"
    ordered = sorted(context, key=lambda row: row.sort_key)
    predecessor_indices = [
        index
        for index, row in enumerate(ordered)
        if row.sort_key <= low
    ]
    anchor = predecessor_indices[-1] if predecessor_indices else 0
    selected: list[ClusterBlock] = []
    upper_boundary = ""
    for row in ordered[anchor:]:
        if selected and row.sort_key > high:
            upper_boundary = row.raw_line
            break
        selected.append(row)
        if len(selected) > maximum:
            raise ProbeError(
                "exact URL spans more CDX blocks than frozen maximum"
            )
    if not selected or not upper_boundary:
        raise ProbeError(
            "cluster context did not prove an upper boundary"
        )
    return selected, upper_boundary


def _query_one(
    target: Mapping[str, Any],
    crawl: str,
    reader: RecordingRangeReader,
    output: Path,
    inventory: Mapping[str, Any],
) -> dict[str, Any]:
    target_id = str(target["target_id"])
    target_url = normalized_okx_url(target["url"])
    target_surt = exact_okx_surt(target_url)
    query_id = f"{target_id}--{crawl}"
    cluster_url = _cluster_url(crawl)
    index = RemoteSortedLineIndex(
        reader,
        cluster_url,
        window_bytes=int(inventory["cluster_window_bytes"]),
        max_requests=int(
            inventory["max_cluster_range_requests_per_query"]
        ),
    )
    context = index.context_for_predecessor(
        f"{target_surt} 00000000000000",
        following=int(inventory["max_cdx_blocks_per_query"]),
    )
    selected, upper_boundary = select_cluster_blocks(
        context,
        target_surt,
        int(inventory["max_cdx_blocks_per_query"]),
    )
    cluster_context_lines = [row.raw_line for row in context]
    exact_rows: list[dict[str, Any]] = []
    block_rows: list[dict[str, Any]] = []
    for block_index, block in enumerate(selected):
        if block.length > int(inventory["max_cdx_block_bytes"]):
            raise ProbeError("CDX gzip block exceeds frozen maximum")
        response = reader.read(
            _cdx_url(crawl, block.shard),
            block.offset,
            block.offset + block.length - 1,
            f"{query_id}:cdx-block-{block_index:02d}",
        )
        maximum_decompressed = int(
            inventory["max_decompressed_cdx_block_bytes"]
        )
        try:
            with gzip.GzipFile(
                fileobj=io.BytesIO(response.body)
            ) as stream:
                decompressed = stream.read(maximum_decompressed + 1)
        except (OSError, EOFError) as exc:
            raise ProbeError(
                "selected CDX gzip block failed to decompress"
            ) from exc
        if len(decompressed) > maximum_decompressed:
            raise ProbeError(
                "decompressed CDX block exceeds frozen maximum"
            )
        try:
            text = decompressed.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProbeError(
                "selected CDX block is not UTF-8"
            ) from exc
        lines = [line for line in text.splitlines() if line]
        if not lines:
            raise ProbeError("selected CDX block is empty")
        if len(lines) != block.record_count:
            raise ProbeError(
                "CDX block line count does not match cluster record count"
            )
        first_key, first_timestamp, _ = parse_cdxj_line(lines[0])
        if (first_key, first_timestamp) != (
            block.first_urlkey,
            block.first_timestamp,
        ):
            raise ProbeError(
                "CDX block first row does not match cluster secondary index"
            )
        relative = (
            f"queries/{query_id}/block-{block_index:02d}.cdxj"
        )
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(decompressed)
        block_exact = 0
        for line in lines:
            urlkey, timestamp, payload = parse_cdxj_line(line)
            if urlkey != target_surt:
                continue
            try:
                captured_url = normalized_okx_url(payload.get("url"))
            except ProbeError:
                continue
            if (
                captured_url != target_url
                or str(payload.get("status")) != "200"
            ):
                continue
            filename = payload.get("filename")
            try:
                offset = int(payload.get("offset"))
                length = int(payload.get("length"))
            except (TypeError, ValueError):
                raise ProbeError(
                    "matching CDX row lacks valid WARC locator"
                )
            if (
                not isinstance(filename, str)
                or not filename.startswith(f"crawl-data/{crawl}/")
                or not filename.endswith(".warc.gz")
                or offset < 0
                or length <= 0
            ):
                raise ProbeError(
                    "matching CDX row WARC locator escaped frozen crawl"
                )
            exact_rows.append(
                {
                    "urlkey": urlkey,
                    "timestamp": timestamp,
                    "url": captured_url,
                    "status": "200",
                    "digest": payload.get("digest"),
                    "filename": filename,
                    "offset": offset,
                    "length": length,
                    "source_block_path": relative,
                    "raw_line_sha256": hashlib.sha256(
                        (line + "\n").encode()
                    ).hexdigest(),
                }
            )
            block_exact += 1
            if len(exact_rows) > int(
                inventory["max_exact_rows_per_query"]
            ):
                raise ProbeError(
                    "exact CDX row count exceeds frozen maximum"
                )
        block_rows.append(
            {
                "cluster_line": block.raw_line,
                "shard": block.shard,
                "offset": block.offset,
                "length": block.length,
                "decompressed_path": relative,
                "decompressed_size": len(decompressed),
                "decompressed_sha256": hashlib.sha256(
                    decompressed
                ).hexdigest(),
                "record_count": block.record_count,
                "line_count": len(lines),
                "exact_row_count": block_exact,
            }
        )
    query = {
        "schema_version": 1,
        "stage": STAGE,
        "query_id": query_id,
        "target_id": target_id,
        "target_url": target_url,
        "target_surt": target_surt,
        "crawl_id": crawl,
        "cluster_url": cluster_url,
        "cluster_total_size": index.total_size,
        "cluster_context_lines": cluster_context_lines,
        "selected_blocks": block_rows,
        "upper_boundary_cluster_line": upper_boundary,
        "exact_rows": exact_rows,
        "exact_row_count": len(exact_rows),
        "status": "PASS",
    }
    atomic_write_json(
        output / f"queries/{query_id}/query.json",
        query,
    )
    return query


def run_probe(
    inventory_path: Path,
    output: Path,
    *,
    transport: RangeTransport | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    validate_environment: bool = True,
) -> dict[str, Any]:
    if validate_environment:
        _validate_environment()
    output.mkdir(parents=True, exist_ok=True)
    inventory = _load_inventory(inventory_path)
    inventory_bytes = _canonical_json_bytes(inventory)
    (output / "inventory_snapshot.json").write_bytes(
        inventory_bytes
    )
    reader = RecordingRangeReader(
        transport
        or UrllibRangeTransport(
            max_bytes=int(inventory["max_cdx_block_bytes"])
        ),
        output,
        minimum_interval_seconds=float(
            inventory["minimum_request_interval_seconds"]
        ),
        sleeper=sleeper,
    )
    queries: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for target in inventory["targets"]:
        for crawl in target["crawl_indexes"]:
            try:
                queries.append(
                    _query_one(
                        target,
                        crawl,
                        reader,
                        output,
                        inventory,
                    )
                )
            except ProbeError as exc:
                errors.append(
                    {
                        "query_id": (
                            f"{target['target_id']}--{crawl}"
                        ),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
    atomic_write_json(
        output / "range_evidence.json",
        {
            "schema_version": 1,
            "stage": STAGE,
            "requests": reader.evidence,
            "request_count": len(reader.evidence),
        },
    )
    hit_queries = [
        row["query_id"]
        for row in queries
        if row["exact_row_count"] > 0
    ]
    completed = not errors and len(queries) == 23
    result = {
        "schema_version": 1,
        "stage": STAGE,
        "inventory_sha256": hashlib.sha256(
            inventory_bytes
        ).hexdigest(),
        "status": "PASS" if completed else "FAIL",
        "result": RESULT_VERIFIED if completed else RESULT_FAILED,
        "target_count": 7,
        "expected_query_count": 23,
        "completed_query_count": len(queries),
        "failed_query_count": len(errors),
        "hit_query_ids": hit_queries,
        "hit_query_count": len(hit_queries),
        "queries": queries,
        "errors": errors,
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
    atomic_write_json(output / "probe_result.json", result)
    return result


def build_manifest(output: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(
        item for item in output.rglob("*") if item.is_file()
    ):
        relative = path.relative_to(output).as_posix()
        if relative == "manifest.json":
            continue
        data = path.read_bytes()
        files.append(
            {
                "path": relative,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    manifest = {
        "schema_version": 1,
        "stage": STAGE,
        "files": files,
        "file_count": len(files),
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
    atomic_write_json(output / "manifest.json", manifest)
    return manifest
