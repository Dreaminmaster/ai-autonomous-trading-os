from __future__ import annotations

import json
from pathlib import Path

import pytest

from atos.c6a_common_crawl_raw_cdxj_core import ProbeError
from atos.c6a_common_crawl_raw_cdxj_probe import run_probe
from atos.c6a_common_crawl_raw_cdxj_transport import (
    MemoryRangeTransport,
)
from test_c6a_common_crawl_raw_cdxj_probe import INVENTORY


def _write_inventory(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps(payload) + "\n")
    return path


def test_producer_rejects_frozen_limit_drift(
    tmp_path: Path,
) -> None:
    inventory = json.loads(INVENTORY.read_text())
    inventory["max_cdx_blocks_per_query"] = 5
    with pytest.raises(ProbeError, match="frozen value drift"):
        run_probe(
            _write_inventory(tmp_path, inventory),
            tmp_path / "output",
            transport=MemoryRangeTransport({}),
            sleeper=lambda _: None,
            validate_environment=False,
        )


def test_producer_rejects_frozen_target_matrix_drift(
    tmp_path: Path,
) -> None:
    inventory = json.loads(INVENTORY.read_text())
    inventory["targets"][0]["url"] = (
        "https://www.okx.com/help/category/security"
    )
    with pytest.raises(ProbeError, match="target matrix drift"):
        run_probe(
            _write_inventory(tmp_path, inventory),
            tmp_path / "output",
            transport=MemoryRangeTransport({}),
            sleeper=lambda _: None,
            validate_environment=False,
        )
