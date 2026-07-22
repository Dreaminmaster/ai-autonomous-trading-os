from __future__ import annotations

import sys
from pathlib import Path

from scripts.ci_subprocess_timeout import run_logged


def test_run_logged_reports_success_and_exit_code(tmp_path: Path) -> None:
    success_log = tmp_path / "success.log"
    assert (
        run_logged(
            [sys.executable, "-c", "print('done')"],
            log_path=success_log,
            timeout_seconds=5,
        )
        == "SUCCESS"
    )
    assert success_log.read_text(encoding="utf-8").strip() == "done"

    failure_log = tmp_path / "failure.log"
    assert (
        run_logged(
            [sys.executable, "-c", "raise SystemExit(7)"],
            log_path=failure_log,
            timeout_seconds=5,
        )
        == "EXIT_7"
    )


def test_run_logged_terminates_timeout_and_records_reason(tmp_path: Path) -> None:
    log = tmp_path / "timeout.log"
    assert (
        run_logged(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            log_path=log,
            timeout_seconds=1,
        )
        == "TIMEOUT"
    )
    assert "ATOS_VALIDATION_TIMEOUT after 1 seconds" in log.read_text(
        encoding="utf-8"
    )
