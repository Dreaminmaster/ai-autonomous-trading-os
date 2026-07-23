from __future__ import annotations

import inspect

import atos.c6a_source_authority_independent as independent


def test_final_reviewer_imports_no_production_gate_or_packager() -> None:
    source = inspect.getsource(independent)
    assert "from atos.c6a_source_authority" not in source
    assert "import atos.c6a_source_authority" not in source
    assert "c6a_source_authority_package" not in source
    assert "c6a_source_authority_schema" not in source


def test_expected_failure_priority_is_recomputed_deterministically() -> None:
    assert independent.choose_primary_failure(
        ["FAIL_TRANSITION_WINDOW_UNPROVEN", "FAIL_UNCOVERED_INTERVAL"]
    ) == "FAIL_UNCOVERED_INTERVAL"
    assert independent.choose_primary_failure([]) is None
