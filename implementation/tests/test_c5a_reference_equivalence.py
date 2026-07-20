from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

from atos.c5a_derivatives_crowding import run_screen
from scripts.c5a_reference_recompute import reference_run_screen
from test_c5a_derivatives_crowding import datasets

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c5a_derivatives_crowding_regime.json"


def _compare(left: Any, right: Any, path: str = "root") -> None:
    if isinstance(left, bool) or isinstance(right, bool):
        assert left is right, path
        return
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        assert math.isclose(float(left), float(right), rel_tol=1e-10, abs_tol=1e-10), (
            path,
            left,
            right,
        )
        return
    if isinstance(left, dict) and isinstance(right, dict):
        assert set(left) == set(right), (path, set(left) ^ set(right))
        for key in left:
            _compare(left[key], right[key], f"{path}.{key}")
        return
    if isinstance(left, list) and isinstance(right, list):
        assert len(left) == len(right), (path, len(left), len(right))
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            _compare(a, b, f"{path}[{index}]")
        return
    assert left == right, (path, left, right)


def test_independent_reference_matches_all_c5a_outputs() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    source = copy.deepcopy(datasets())
    production = run_screen(source, config)
    reference = reference_run_screen(copy.deepcopy(source), config)
    _compare(production["calibration"], reference["calibration"], "calibration")
    _compare(production["policy_rows"], reference["policy_rows"], "policy_rows")
    _compare(production["comparator_rows"], reference["comparator_rows"], "comparator_rows")
    _compare(production["policy_aggregates"], reference["policy_aggregates"], "policy_aggregates")
    _compare(production["comparator_aggregates"], reference["comparator_aggregates"], "comparator_aggregates")
    _compare(production["decision"], reference["decision"], "decision")
