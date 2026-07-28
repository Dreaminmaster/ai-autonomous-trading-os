from __future__ import annotations

import subprocess

import pytest

from atos.c7a_historical_run_guard import (
    C7AHistoricalRunGuardError,
    verify_checkout_binding,
)

SHA = "a" * 40


def _runner(*outputs: tuple[str, int]):
    remaining = list(outputs)

    def run(*_args, **_kwargs):
        stdout, code = remaining.pop(0)
        if code:
            raise subprocess.CalledProcessError(code, "git")
        return subprocess.CompletedProcess("git", code, stdout=stdout, stderr="")

    return run


def test_exact_clean_checkout_binding_passes(tmp_path) -> None:
    result = verify_checkout_binding(
        SHA,
        repository_root=tmp_path,
        runner=_runner((f"{SHA}\n", 0), ("", 0)),
    )
    assert result["observed_head_sha"] == SHA
    assert result["tracked_worktree_clean"] is True


@pytest.mark.parametrize(
    ("head", "status", "match"),
    [
        ("b" * 40, "", "does not match"),
        (SHA, " M implementation/src/atos/example.py", "clean tracked worktree"),
    ],
)
def test_checkout_binding_rejects_sha_or_dirty_drift(
    tmp_path, head: str, status: str, match: str
) -> None:
    with pytest.raises(C7AHistoricalRunGuardError, match=match):
        verify_checkout_binding(
            SHA,
            repository_root=tmp_path,
            runner=_runner((f"{head}\n", 0), (status, 0)),
        )
