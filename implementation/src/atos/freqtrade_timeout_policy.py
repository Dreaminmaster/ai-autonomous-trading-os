"""Auditable timeout budgets for the existing Freqtrade validation workflow."""

BACKTEST_TIMEOUT_SECONDS = 900
LOOKAHEAD_TIMEOUT_SECONDS = 3000
LOOKAHEAD_WRAPPER_TIMEOUT_SECONDS = 3600

if not (
    0 < BACKTEST_TIMEOUT_SECONDS
    < LOOKAHEAD_TIMEOUT_SECONDS
    < LOOKAHEAD_WRAPPER_TIMEOUT_SECONDS
):
    raise RuntimeError("Freqtrade validation timeout ordering is invalid")
