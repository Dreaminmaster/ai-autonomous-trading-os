from __future__ import annotations

from .c3a_residual_common import (
    ANNUAL_BARS, COST_RATES, PAIR_TO_ASSET, POLICY_IDS, STARTING_EQUITY, WINDOWS,
    C3AError, CellResult, Trade,
)
from .c3a_residual_decision import aggregate_policy, decide, run_screen
from .c3a_residual_indicators import compute_indicators, frame_from_rows
from .c3a_residual_simulation import comparator_cell, simulate_window

__all__ = [
    "ANNUAL_BARS", "COST_RATES", "PAIR_TO_ASSET", "POLICY_IDS", "STARTING_EQUITY",
    "WINDOWS", "C3AError", "CellResult", "Trade", "aggregate_policy", "decide",
    "run_screen", "compute_indicators", "frame_from_rows", "comparator_cell",
    "simulate_window",
]
