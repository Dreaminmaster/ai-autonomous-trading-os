from __future__ import annotations

from pathlib import Path

import pytest

from scripts import c6a_authoritative_source_inventory as authoritative


def minimal_repo(root: Path) -> str:
    workflow = ".github/workflows/c6a-authoritative.yml"
    path = root / workflow
    path.parent.mkdir(parents=True)
    path.write_text("name: C6A authoritative\n", encoding="utf-8")
    for relative in authoritative.base.DESIGN_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("design\n", encoding="utf-8")
    for relative in authoritative.base.EXACT_IMPLEMENTATION_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("implementation\n", encoding="utf-8")
    # Satisfy the minimum effective-source count with reviewed C6A-shaped files.
    for index in range(20):
        target = root / f"implementation/src/atos/c6a_fixture_{index:02d}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"VALUE = {index}\n", encoding="utf-8")
    return workflow


def test_exactly_one_declared_temporary_workflow_is_recorded_not_economic(
    tmp_path: Path,
) -> None:
    workflow = minimal_repo(tmp_path)
    paths, record = authoritative.discover_with_temporary_workflow(
        root=tmp_path, workflow_path=workflow
    )
    assert workflow not in paths
    assert record["path"] == workflow
    assert record["economic_source"] is False
    assert record["must_be_removed_before_merge"] is True
    payload = authoritative.build_authoritative_inventory(
        root=tmp_path,
        source_sha="a" * 40,
        workflow_path=workflow,
    )
    assert payload["temporary_authoritative_workflow_present"] is True
    assert payload["workflow_in_economic_source_inventory"] is False
    assert payload["workflow_removal_required_before_merge"] is True


def test_additional_or_wrong_workflow_fails_closed(tmp_path: Path) -> None:
    workflow = minimal_repo(tmp_path)
    extra = tmp_path / ".github/workflows/another-c6a-check.yml"
    extra.write_text("name: extra\n", encoding="utf-8")
    with pytest.raises(
        authoritative.C6AAuthoritativeInventoryError,
        match="exactly one declared",
    ):
        authoritative.discover_with_temporary_workflow(
            root=tmp_path, workflow_path=workflow
        )

    extra.unlink()
    with pytest.raises(
        authoritative.C6AAuthoritativeInventoryError,
        match="missing or unsafe",
    ):
        authoritative.discover_with_temporary_workflow(
            root=tmp_path,
            workflow_path=".github/workflows/wrong-c6a.yml",
        )
