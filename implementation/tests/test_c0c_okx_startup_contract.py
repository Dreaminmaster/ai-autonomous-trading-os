from __future__ import annotations

from copy import deepcopy

import atos.c0c_walk_forward as c0c
from atos.c0c_okx_startup import (
    OKX_5M_MAX_STARTUP_CANDLES,
    OKX_STARTUP_ANALYSIS,
    apply_okx_startup_contract,
)


def test_okx_startup_contract_is_effective_and_idempotent() -> None:
    apply_okx_startup_contract()
    assert OKX_5M_MAX_STARTUP_CANDLES == 1499
    assert c0c.STARTUP_CANDLE_COUNT == 1499
    assert c0c.STARTUP_ANALYSIS == OKX_STARTUP_ANALYSIS
    assert c0c.STARTUP_ANALYSIS is not OKX_STARTUP_ANALYSIS
    assert c0c.STARTUP_ANALYSIS["startup_candidates"] == [499, 999, 1499]
    assert c0c.STARTUP_ANALYSIS["selected_startup_candles"] == 1499
    before = deepcopy(c0c.STARTUP_ANALYSIS)
    apply_okx_startup_contract()
    assert c0c.STARTUP_ANALYSIS == before
