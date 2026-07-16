"""Compatibility package for the frozen C0C runner with current Freqtrade output.

The sibling ``run_c0c_development.py`` remains the authoritative implementation.
This package re-exports it and narrows one parser compatibility edge: Freqtrade
2026.6 may emit an explicit no-recursive-variance marker and omit the Rich table.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Sequence


_ORIGINAL_PATH = Path(__file__).resolve().parents[1] / "run_c0c_development.py"
_SPEC = importlib.util.spec_from_file_location("_atos_run_c0c_development_original", _ORIGINAL_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"unable to load frozen C0C runner: {_ORIGINAL_PATH}")
_ORIGINAL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ORIGINAL)

for _name in dir(_ORIGINAL):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_ORIGINAL, _name)

_original_validate_recursive_analysis_log = _ORIGINAL.validate_recursive_analysis_log
_EXPLICIT_ZERO_VARIANCE_MARKER = "No variance on indicator(s) found due to recursive formula."
_NO_LOOKAHEAD_MARKER = "No lookahead bias on indicators found."


def validate_recursive_analysis_log(
    path: str | Path,
    *,
    startup_count: int,
    required_indicators: Sequence[str],
    max_variance_pct: float,
) -> dict[str, Any]:
    """Accept Freqtrade's explicit zero-variance no-table output fail-closed.

    Numeric/table output still delegates unchanged to the frozen parser. The
    no-table branch is accepted only when the exact zero-variance marker, the
    selected startup calculation, and the no-lookahead proof are all present.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise C0CWalkForwardError(f"unable to read recursive analysis log: {exc}") from exc

    if not any(_EXPLICIT_ZERO_VARIANCE_MARKER in line for line in lines):
        return _original_validate_recursive_analysis_log(
            path,
            startup_count=startup_count,
            required_indicators=required_indicators,
            max_variance_pct=max_variance_pct,
        )

    if any("=> found lookahead in indicator" in line for line in lines):
        raise C0CWalkForwardError("recursive analysis reported indicator lookahead")
    if not any(_NO_LOOKAHEAD_MARKER in line for line in lines):
        raise C0CWalkForwardError("recursive analysis missing no-lookahead proof")

    selected_marker = f"Calculating indicators using startup candle of {startup_count}."
    if not any(selected_marker in line for line in lines):
        raise C0CWalkForwardError(
            f"recursive analysis explicit-zero output missing selected startup {startup_count}"
        )

    required = list(dict.fromkeys(str(item) for item in required_indicators))
    if not required or any(not item for item in required):
        raise C0CWalkForwardError("recursive analysis required indicators are empty")
    if max_variance_pct < 0:
        raise C0CWalkForwardError("recursive analysis max variance must be nonnegative")

    observed = {indicator: 0.0 for indicator in required}
    basis = {
        indicator: "FREQTRADE_EXPLICIT_NO_RECURSIVE_VARIANCE_MARKER"
        for indicator in required
    }
    return {
        "status": "PASS",
        "startup_candle_count": startup_count,
        "max_variance_pct": max_variance_pct,
        "output_semantics": "FREQTRADE_2026_6_EXPLICIT_NO_VARIANCE_NO_TABLE",
        "lookahead_status": "PASS",
        "indicator_variance_pct": dict(sorted(observed.items())),
        "indicator_evidence_basis": dict(sorted(basis.items())),
        "omitted_as_zero_variance": sorted(required),
        "dash_as_zero_variance": [],
        "explicit_zero_variance_marker": True,
        "selected_startup_execution_proved": True,
    }
