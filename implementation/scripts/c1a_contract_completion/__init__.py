"""Package wrapper that extends the frozen C1A effective-source inventory."""
from __future__ import annotations

import importlib.util
from pathlib import Path


_ORIGINAL_PATH = Path(__file__).resolve().parents[1] / "c1a_contract_completion.py"
_SPEC = importlib.util.spec_from_file_location("_atos_c1a_contract_completion_original", _ORIGINAL_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"unable to load C1A contract completion module: {_ORIGINAL_PATH}")
_ORIGINAL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ORIGINAL)

_ADDITIONAL_SOURCE_PATHS = [
    Path("scripts/run_c0c_development/__init__.py"),
    Path("scripts/c1a_contract_completion/__init__.py"),
    Path("tests/test_c1a_recursive_adapter.py"),
]
for _path in _ADDITIONAL_SOURCE_PATHS:
    if _path not in _ORIGINAL.SOURCE_PATHS:
        _ORIGINAL.SOURCE_PATHS.append(_path)

for _name in dir(_ORIGINAL):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_ORIGINAL, _name)

SOURCE_PATHS = _ORIGINAL.SOURCE_PATHS
