from __future__ import annotations

import inspect

import atos.c6a_source_authority_package as package


def test_package_binds_transition_partition_to_final_independent_review() -> None:
    source = inspect.getsource(package.package_gate_artifact)
    assert "review_transition_partition(" in source
    assert 'independent["transition_partition_review"] = partition_review' in source
    assert 'independent["status"] = "FAIL"' in source
    assert source.index("review_transition_partition(") < source.index("_finalize_decision(")
