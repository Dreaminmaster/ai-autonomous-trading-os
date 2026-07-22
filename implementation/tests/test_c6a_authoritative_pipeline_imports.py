from __future__ import annotations

import importlib
import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config/c6a_execution_contract_v2.json"


def module_name(relative: str) -> str:
    assert relative.startswith("scripts/") and relative.endswith(".py")
    return relative[:-3].replace("/", ".")


def test_every_frozen_authoritative_entrypoint_imports_and_has_main() -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    entrypoints = payload["authoritative_entrypoints"]
    assert len(entrypoints) == 11
    modules = []
    for role in payload["required_order"]:
        relative = entrypoints[role]
        module = importlib.import_module(module_name(relative))
        assert callable(getattr(module, "main", None)), role
        modules.append(module.__name__)
    assert len(modules) == len(set(modules)) == 11
