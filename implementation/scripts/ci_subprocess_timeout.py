#!/usr/bin/env python3
"""Shared bounded subprocess helper for ordinary validation scripts.

The ordinary Freqtrade validation matrix is diagnostic and must never leave a
workflow step waiting indefinitely.  Every external command is terminated after
its explicit timeout and the caller receives a stable status for its report.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


def run_logged(
    command: Sequence[str],
    *,
    log_path: str | Path,
    timeout_seconds: int,
) -> str:
    """Run ``command`` with a hard timeout and return a stable status string."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    destination = Path(log_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        try:
            completed = subprocess.run(
                list(command),
                check=False,
                stdout=handle,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            handle.write(
                f"\nATOS_VALIDATION_TIMEOUT after {timeout_seconds} seconds\n"
            )
            return "TIMEOUT"
    return "SUCCESS" if completed.returncode == 0 else f"EXIT_{completed.returncode}"
