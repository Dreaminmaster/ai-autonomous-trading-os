from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from atos.c6a_common_crawl_raw_cdxj_core import (
    ProbeError,
    _load_inventory,
    exact_okx_surt,
    parse_cdxj_line,
    parse_cluster_line,
)
from atos.c6a_common_crawl_raw_cdxj_probe import (
    run_probe,
    select_cluster_blocks,
)
from atos.c6a_common_crawl_raw_cdxj_probe_independent import (
    review_probe,
)
from atos.c6a_common_crawl_raw_cdxj_transport import (
    MemoryRangeTransport,
    RecordingRangeReader,
    RemoteSortedLineIndex,
)


INVENTORY = (
    Path(__file__).parents[1]
    / "config/c6a_common_crawl_raw_cdxj_probe_inventory_v1.json"
)
DATA = "https://data.commoncrawl.org"


def _build_objects(
    inventory: dict,
    *,
    omit_crawl: str | None = None,
) -> dict[str, bytes]:
    targets = sorted(
        [
            (target["url"], exact_okx_surt(target["url"]))
            for target in inventory["targets"]
        ],
        key=lambda item: item[1],
    )
    crawls = sorted(
        {
            crawl
            for target in inventory["targets"]
            for crawl in target["crawl_indexes"]
        }
    )
    objects: dict[str, bytes] = {}
    for crawl in crawls:
        blocks: list[tuple[str, str, bytes]] = []
        sentinel_before = "com,okx)/help/000-before"
        before_line = (
            f'{sentinel_before} 20240101000000 '
            '{"url":"https://www.okx.com/help/000-before",'
            '"status":"404"}\n'
        ).encode()
        blocks.append(
            (
                sentinel_before,
                "20240101000000",
                gzip.compress(before_line, mtime=0),
            )
        )
        for index, (url, surt) in enumerate(targets):
            timestamp = f"2024{index + 1:02d}01000000"
            payload = {
                "url": url,
                "status": "200",
                "digest": hashlib.sha1(url.encode()).hexdigest().upper(),
                "filename": (
                    f"crawl-data/{crawl}/segments/test/warc/"
                    f"test-{index}.warc.gz"
                ),
                "offset": str(1000 + index),
                "length": str(2000 + index),
            }
            line = (
                f"{surt} {timestamp} "
                f"{json.dumps(payload, sort_keys=True)}\n"
            ).encode()
            blocks.append((surt, timestamp, gzip.compress(line, mtime=0)))
        sentinel_after = "com,okx)/help/zzzz-after"
        after_line = (
            f'{sentinel_after} 20241231235959 '
            '{"url":"https://www.okx.com/help/zzzz-after",'
            '"status":"404"}\n'
        ).encode()
        blocks.append(
            (
                sentinel_after,
                "20241231235959",
                gzip.compress(after_line, mtime=0),
            )
        )

        shard = bytearray()
        cluster_lines: list[str] = []
        for key, timestamp, compressed in blocks:
            offset = len(shard)
            shard.extend(compressed)
            cluster_lines.append(
                f"{key} {timestamp}\tcdx-00000.gz\t{offset}\t"
                f"{len(compressed)}\t1\n"
            )
        cluster_url = (
            f"{DATA}/cc-index/collections/{crawl}/indexes/cluster.idx"
        )
        shard_url = (
            f"{DATA}/cc-index/collections/{crawl}/indexes/cdx-00000.gz"
        )
        objects[cluster_url] = "".join(cluster_lines).encode()
        if crawl != omit_crawl:
            objects[shard_url] = bytes(shard)
    return objects


def test_narrow_surt_and_line_parsers() -> None:
    url = "https://www.okx.com/help/category/announcements"
    assert exact_okx_surt(url) == "com,okx)/help/category/announcements"
    with pytest.raises(ProbeError):
        exact_okx_surt(
            "https://www.okx.com/en-us/help/category/announcements"
        )
    block = parse_cluster_line(
        "com,okx)/help/category/announcements 20240418010101"
        "\tcdx-00042.gz\t123\t456\t3000"
    )
    assert block.shard == "cdx-00042.gz"
    assert block.offset == 123
    key, timestamp, payload = parse_cdxj_line(
        "com,okx)/help/category/announcements 20240418010101 "
        '{"url":"https://www.okx.com/help/category/announcements",'
        '"status":"200"}'
    )
    assert key == "com,okx)/help/category/announcements"
    assert timestamp == "20240418010101"
    assert payload["status"] == "200"


def test_remote_binary_search_returns_bounded_context(
    tmp_path: Path,
) -> None:
    lines = []
    for index in range(2000):
        lines.append(
            f"com,example)/{index:05d} 20240101000000"
            f"\tcdx-00000.gz\t{index * 100}\t100\t1\n"
        )
    url = (
        f"{DATA}/cc-index/collections/CC-MAIN-2024-18/"
        "indexes/cluster.idx"
    )
    transport = MemoryRangeTransport({url: "".join(lines).encode()})
    reader = RecordingRangeReader(
        transport,
        tmp_path,
        minimum_interval_seconds=0,
        sleeper=lambda _: None,
    )
    index = RemoteSortedLineIndex(
        reader,
        url,
        window_bytes=4096,
        max_requests=32,
    )
    context = index.context_for_predecessor(
        "com,example)/01000 00000000000000",
        following=4,
    )
    assert any(
        row.first_urlkey == "com,example)/00999" for row in context
    )
    assert any(
        row.first_urlkey == "com,example)/01000" for row in context
    )
    selected, boundary = select_cluster_blocks(
        context,
        "com,example)/01000",
        4,
    )
    assert selected[-1].first_urlkey == "com,example)/01000"
    assert "com,example)/01001" in boundary


def test_full_offline_probe_and_independent_review_pass(
    tmp_path: Path,
) -> None:
    inventory = _load_inventory(INVENTORY)
    objects = _build_objects(inventory)
    result = run_probe(
        INVENTORY,
        tmp_path,
        transport=MemoryRangeTransport(objects),
        sleeper=lambda _: None,
        validate_environment=False,
    )
    assert result["status"] == "PASS"
    assert result["completed_query_count"] == 23
    assert result["hit_query_count"] == 23
    review = review_probe(tmp_path)
    assert review["status"] == "PASS", review["errors"]
    assert review["probe_status_recomputed"] == "PASS"


def test_transport_failure_is_retained_as_execution_failure(
    tmp_path: Path,
) -> None:
    inventory = _load_inventory(INVENTORY)
    objects = _build_objects(
        inventory,
        omit_crawl="CC-MAIN-2025-13",
    )
    result = run_probe(
        INVENTORY,
        tmp_path,
        transport=MemoryRangeTransport(objects),
        sleeper=lambda _: None,
        validate_environment=False,
    )
    assert result["status"] == "FAIL"
    assert result["result"] == "RAW_CDXJ_ACCESS_PATH_EXECUTION_FAILED"
    assert result["failed_query_count"] == 2
    review = review_probe(tmp_path)
    assert review["status"] == "PASS", review["errors"]
    assert review["probe_status_recomputed"] == "FAIL"


def test_independent_review_detects_tampered_block(
    tmp_path: Path,
) -> None:
    inventory = _load_inventory(INVENTORY)
    result = run_probe(
        INVENTORY,
        tmp_path,
        transport=MemoryRangeTransport(_build_objects(inventory)),
        sleeper=lambda _: None,
        validate_environment=False,
    )
    assert result["status"] == "PASS"
    block = next((tmp_path / "queries").rglob("block-00.cdxj"))
    block.write_bytes(block.read_bytes() + b"tamper\n")
    review = review_probe(tmp_path)
    assert review["status"] == "FAIL"
    assert any("mismatch" in error for error in review["errors"])


def test_forbidden_proxy_state_fails_before_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    with pytest.raises(ProbeError, match="forbidden network state"):
        run_probe(
            INVENTORY,
            tmp_path,
            transport=MemoryRangeTransport({}),
            sleeper=lambda _: None,
        )


def test_independent_review_binds_compressed_range_to_block(
    tmp_path: Path,
) -> None:
    inventory = _load_inventory(INVENTORY)
    result = run_probe(
        INVENTORY,
        tmp_path,
        transport=MemoryRangeTransport(_build_objects(inventory)),
        sleeper=lambda _: None,
        validate_environment=False,
    )
    assert result["status"] == "PASS"
    evidence_path = tmp_path / "range_evidence.json"
    evidence = json.loads(evidence_path.read_text())
    row = next(
        item
        for item in evidence["requests"]
        if item["url"].endswith("cdx-00000.gz")
    )
    retained = tmp_path / row["path"]
    original = retained.read_bytes()
    tampered = original[:-1] + bytes([original[-1] ^ 1])
    retained.write_bytes(tampered)
    row["sha256"] = hashlib.sha256(tampered).hexdigest()
    row["size"] = len(tampered)
    evidence_path.write_text(
        json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    review = review_probe(tmp_path)
    assert review["status"] == "FAIL"
    assert any(
        "decompress" in error or "binding mismatch" in error
        for error in review["errors"]
    )


def test_independent_review_recomputes_cluster_selection(
    tmp_path: Path,
) -> None:
    inventory = _load_inventory(INVENTORY)
    result = run_probe(
        INVENTORY,
        tmp_path,
        transport=MemoryRangeTransport(_build_objects(inventory)),
        sleeper=lambda _: None,
        validate_environment=False,
    )
    assert result["status"] == "PASS"
    result_path = tmp_path / "probe_result.json"
    payload = json.loads(result_path.read_text())
    query = payload["queries"][0]
    del query["cluster_context_lines"][1]
    result_path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    query_path = tmp_path / f"queries/{query['query_id']}/query.json"
    query_path.write_text(
        json.dumps(
            query,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    review = review_probe(tmp_path)
    assert review["status"] == "FAIL"
    assert any(
        "context not bound" in error
        or "selection proof" in error
        or "selected block sequence" in error
        or "upper boundary" in error
        for error in review["errors"]
    )
