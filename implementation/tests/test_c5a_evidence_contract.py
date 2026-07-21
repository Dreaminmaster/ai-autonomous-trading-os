from __future__ import annotations

import pytest

from atos.c5a_derivatives_crowding import EXPECTED_CONFIG_CANONICAL_SHA256, canonical_sha256
from scripts import c5a_evidence as evidence
from scripts import c5a_finalizer as finalizer
from scripts import c5a_source_inventory as inventory
from test_c5a_derivatives_crowding import config, datasets


def test_config_hash_and_safety_are_frozen() -> None:
    payload = config()
    assert canonical_sha256(payload) == EXPECTED_CONFIG_CANONICAL_SHA256
    assert payload["confirmation_opened"] is False
    assert payload["holdout_state"] == "HOLDOUT_CLOSED"
    assert payload["paper_state"] == "PAPER_CLOSED"
    assert payload["shadow_state"] == "SHADOW_CLOSED"
    assert payload["live"] == "FORBIDDEN"


def test_evidence_views_have_frozen_counts() -> None:
    from atos.c5a_derivatives_crowding import run_screen

    screen = run_screen(datasets(), config())
    views = evidence.evidence_views(screen)
    assert len(views["decisions"]) == 156
    assert len(views["signals"]) == 468
    assert len(views["weekly"]) == 156
    assert len(views["ledger"]) > 0


def test_source_inventory_is_unique_and_complete() -> None:
    assert len(inventory.SOURCE_PATHS) == len(set(inventory.SOURCE_PATHS))
    assert len(inventory.SOURCE_PATHS) == 33
    assert "implementation/scripts/c5a_reference_recompute.py" in inventory.SOURCE_PATHS
    assert "implementation/scripts/c5a_program_guard.py" in inventory.SOURCE_PATHS
    assert "implementation/scripts/c5a_program_evidence_extension.py" in inventory.SOURCE_PATHS
    assert "implementation/scripts/c5a_program_finalizer_extension.py" in inventory.SOURCE_PATHS
    assert "implementation/scripts/c5a_retention_evidence.py" in inventory.SOURCE_PATHS
    assert "implementation/scripts/c5a_retention_finalizer.py" in inventory.SOURCE_PATHS
    assert "implementation/tests/test_c5a_program_guard.py" in inventory.SOURCE_PATHS
    assert "implementation/tests/test_c5a_retention_contract.py" in inventory.SOURCE_PATHS
    assert "implementation/tests/test_c5a_evidence_contract.py" in inventory.SOURCE_PATHS


def test_finalizer_compare_is_strict_and_numerically_tolerant() -> None:
    finalizer.compare("same", {"a": [1.0, True]}, {"a": [1.0 + 1e-12, True]})
    with pytest.raises(finalizer.C5AFinalizerError, match="numeric mismatch"):
        finalizer.compare("different", 1.0, 1.01)
    with pytest.raises(finalizer.C5AFinalizerError, match="key mismatch"):
        finalizer.compare("keys", {"a": 1}, {"b": 1})
