from __future__ import annotations

import json
from pathlib import Path

from atos.c6a_source_plan import validate_source_plan
from scripts.c6a_source_plan_preflight import preflight

IMPL = Path(__file__).resolve().parents[1]
PLAN = IMPL / "config/c6a_public_source_plan.json"


def test_authoritative_public_source_plan_is_committed_and_valid() -> None:
    assert PLAN.is_file(), (
        "authoritative C6A pipeline requires committed "
        "implementation/config/c6a_public_source_plan.json"
    )
    payload = json.loads(PLAN.read_text(encoding="utf-8"))
    entries = validate_source_plan(payload)
    report = preflight(payload)
    assert len(entries) == report["source_count"]
    assert report["status"] == "PASS"
    assert report["placeholder_count"] == 0
    assert report["economic_result_run"] is False
    assert report["c6b_state"] == "C6B_CLOSED"
    assert report["c5b_state"] == "C5B_CLOSED_AND_UNTOUCHED"
    assert report["live"] == "FORBIDDEN"
