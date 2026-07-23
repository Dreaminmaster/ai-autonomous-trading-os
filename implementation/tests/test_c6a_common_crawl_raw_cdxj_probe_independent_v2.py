from __future__ import annotations

import hashlib
import json
from pathlib import Path

from atos.c6a_common_crawl_raw_cdxj_core import _load_inventory
from atos.c6a_common_crawl_raw_cdxj_probe import run_probe
from atos.c6a_common_crawl_raw_cdxj_probe_independent_v2 import (
    review_probe,
)
from atos.c6a_common_crawl_raw_cdxj_transport import (
    MemoryRangeTransport,
)
from test_c6a_common_crawl_raw_cdxj_probe import (
    INVENTORY,
    _build_objects,
)


def test_frozen_inventory_wrapper_accepts_exact_package(
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
    review = review_probe(tmp_path)
    assert review["status"] == "PASS", review["errors"]


def test_frozen_inventory_wrapper_rejects_semantic_rebinding(
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
    snapshot_path = tmp_path / "inventory_snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["targets"][0]["url"] = (
        "https://www.okx.com/help/category/security"
    )
    snapshot_bytes = (
        json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode()
    snapshot_path.write_bytes(snapshot_bytes)
    result_path = tmp_path / "probe_result.json"
    payload = json.loads(result_path.read_text())
    payload["inventory_sha256"] = hashlib.sha256(
        snapshot_bytes
    ).hexdigest()
    result_path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    review = review_probe(tmp_path)
    assert review["status"] == "FAIL"
    assert (
        "independent frozen inventory digest mismatch"
        in review["errors"]
    )
