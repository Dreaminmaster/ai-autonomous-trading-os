"""Fail-closed discovery of Freqtrade backtest exports for C0B."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from atos.profitability_diagnostics import (
    ProfitabilityDiagnosticsError,
    load_freqtrade_export,
)


class C0BExportDiscoveryError(RuntimeError):
    """Raised when a matrix cell has no unique authoritative export."""


def discover_authoritative_export(
    directory: str | Path,
    expected_strategies: Sequence[str],
) -> Path:
    """Return the unique export whose strategy set matches the matrix cell.

    Modern Freqtrade writes timestamped result archives into a backtest directory.
    Metadata JSON files are not authoritative. Every remaining ZIP/JSON candidate is
    parsed using the existing C0A loader, and exactly one matching result is required.
    """

    root = Path(directory)
    if not root.is_dir():
        raise C0BExportDiscoveryError(f"backtest directory missing: {root}")

    expected = list(expected_strategies)
    if not expected or any(not isinstance(name, str) or not name for name in expected):
        raise C0BExportDiscoveryError("expected_strategies must be non-empty names")
    if len(set(expected)) != len(expected):
        raise C0BExportDiscoveryError("expected_strategies contains duplicates")
    expected_set = set(expected)

    candidates = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and (
            path.suffix.lower() == ".zip"
            or (
                path.suffix.lower() == ".json"
                and not path.name.lower().endswith(".meta.json")
            )
        )
    )

    matches: list[Path] = []
    rejected: list[str] = []
    for candidate in candidates:
        try:
            payload = load_freqtrade_export(candidate)
        except ProfitabilityDiagnosticsError as exc:
            rejected.append(f"{candidate}: {exc}")
            continue

        strategies = payload.get("strategy")
        if not isinstance(strategies, dict):
            rejected.append(f"{candidate}: strategy mapping missing")
            continue
        actual_set = set(strategies)
        if actual_set != expected_set:
            rejected.append(
                f"{candidate}: strategy set {sorted(actual_set)} != {sorted(expected_set)}"
            )
            continue
        matches.append(candidate)

    if len(matches) != 1:
        raise C0BExportDiscoveryError(
            "expected one authoritative C0B export in "
            f"{root}, found {[str(path) for path in matches]}; "
            f"candidates={[str(path) for path in candidates]}; rejected={rejected}"
        )
    return matches[0]
