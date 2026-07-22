from __future__ import annotations

from pathlib import Path

import pytest

from scripts import c6a_source_inventory as inventory


def test_repository_effective_source_inventory_is_complete() -> None:
    paths = inventory.discover_effective_sources()
    assert "implementation/config/c6a_market_neutral_funding_carry.json" in paths
    assert "implementation/scripts/run_c6a_screen.py" in paths
    assert "implementation/scripts/c6a_reference_recompute.py" in paths
    assert "implementation/scripts/c6a_finalizer.py" in paths
    assert len(paths) >= 20
    payload = inventory.build_inventory(source_sha="a" * 40, paths=paths)
    assert payload["status"] == "PASS"
    assert payload["file_count"] == len(paths)
    assert payload["temporary_authoritative_workflow_present"] is False
    assert payload["live"] == "FORBIDDEN"


def test_snapshot_hashes_every_inventory_file(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    first = root / "a.txt"
    second = root / "nested/b.txt"
    second.parent.mkdir()
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    payload = inventory.build_inventory(
        root=root,
        source_sha="b" * 40,
        paths=("a.txt", "nested/b.txt"),
    )
    destination = tmp_path / "snapshot"
    copied = inventory.snapshot_sources(
        payload, root=root, destination=destination
    )
    assert len(copied) == 2
    assert (destination / "a.txt").read_text(encoding="utf-8") == "alpha"
    assert (destination / "nested/b.txt").read_text(encoding="utf-8") == "beta"
    with pytest.raises(inventory.C6ASourceInventoryError, match="overwrite"):
        inventory.snapshot_sources(payload, root=root, destination=destination)


def test_inventory_rejects_unsorted_or_escaping_paths(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "b.txt").write_text("b", encoding="utf-8")
    with pytest.raises(inventory.C6ASourceInventoryError, match="sorted and unique"):
        inventory.build_inventory(
            root=root, source_sha="c" * 40, paths=("b.txt", "a.txt")
        )
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    with pytest.raises(inventory.C6ASourceInventoryError, match="escapes repository"):
        inventory.build_inventory(
            root=root, source_sha="c" * 40, paths=("../outside.txt",)
        )
