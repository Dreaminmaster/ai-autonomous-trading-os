from __future__ import annotations

import inspect

import atos.c6a_source_authority_package as package


def test_package_binds_all_subreviews_before_final_decision() -> None:
    source = inspect.getsource(package.package_gate_artifact)
    assert "review_transition_partition(" in source
    assert "review_source_boundaries(" in source
    assert 'independent["transition_partition_review"] = partition_review' in source
    assert 'independent["retained_source_review"] = source_review' in source
    assert "_append_review_errors(independent, partition_review)" in source
    assert "_append_review_errors(independent, source_review)" in source
    finalization = source.index("_finalize_decision(")
    assert source.index("review_transition_partition(") < finalization
    assert source.index("review_source_boundaries(") < finalization
