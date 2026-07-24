from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_scope_venue_preflight import begin_invocation, invocation_marker_path


IMPLEMENTATION_SHA = "1" * 40
SOURCE_COMMIT_SHA = "2" * 40
MERGE_REF = "refs/pull/77/merge@" + ("3" * 40)


def _begin(output: Path) -> None:
    begin_invocation(
        output,
        venue_label="test-neutral-venue",
        execution_mode="LOCAL_USER_CONTROLLED",
        implementation_sha=IMPLEMENTATION_SHA,
        source_commit_sha=SOURCE_COMMIT_SHA,
        validated_pr_merge_ref=MERGE_REF,
    )


def test_adjacent_marker_rejects_restart_after_output_deletion(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    _begin(output)
    marker = invocation_marker_path(output)
    shutil.rmtree(output)

    assert marker.is_file()
    with pytest.raises(SourceAuthorityError, match="repeated start rejected"):
        _begin(output)


def test_adjacent_marker_tamper_still_rejects_restart(tmp_path: Path) -> None:
    output = tmp_path / "evidence"
    _begin(output)
    marker = invocation_marker_path(output)
    shutil.rmtree(output)
    marker.write_text("tampered", encoding="utf-8")

    with pytest.raises(SourceAuthorityError, match="repeated start rejected"):
        _begin(output)
