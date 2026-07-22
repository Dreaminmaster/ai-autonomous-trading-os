from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from atos.c6a_contract import C6AError
from atos.c6a_data import C6AMarket, validate_mark_candles, validate_trade_candles
from atos.c6a_replay import replay_window_events, verify_window_replay


def market() -> C6AMarket:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=3)
    trade_rows = [
        {
            "timestamp": (start + timedelta(hours=index)).isoformat(),
            "open": "100",
            "high": "100",
            "low": "100",
            "close": "100",
            "quote_volume": "1",
        }
        for index in range(3)
    ]
    mark_rows = [
        {key: value for key, value in row.items() if key != "quote_volume"}
        for row in trade_rows
    ]
    return C6AMarket(
        spot={
            instrument: validate_trade_candles(
                trade_rows, instrument=instrument, start=start, end=end
            )
            for instrument in ("BTC-USDT", "ETH-USDT")
        },
        swap={
            instrument: validate_trade_candles(
                trade_rows, instrument=instrument, start=start, end=end
            )
            for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
        },
        mark={
            instrument: validate_mark_candles(
                mark_rows, instrument=instrument, start=start, end=end
            )
            for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
        },
    )


def events() -> list[dict]:
    return [
        {
            "kind": "SCHEDULED_TRADE",
            "time": "2024-01-01T00:00:00Z",
            "spot_instrument": "BTC-USDT",
            "spot_quantity_before": "0",
            "spot_quantity_after": "1",
            "perpetual_base_before": "0",
            "perpetual_base_after": "1",
            "normalized_one_way_turnover": "0.1",
        },
        {
            "kind": "FUNDING",
            "time": "2024-01-01T01:00:00Z",
            "instrument": "BTC-USDT-SWAP",
            "realized_rate": "0.001",
            "active_before": True,
        },
        {
            "kind": "TERMINAL_LIQUIDATION",
            "time": "2024-01-01T02:00:00Z",
            "spot_instrument": "BTC-USDT",
            "equity_before": "1000.1",
        },
    ]


def test_replay_reconstructs_funding_and_close_turnover() -> None:
    replay = replay_window_events(events=events(), market=market(), scored_weeks=1)
    assert replay.gross_funding_receipts == Decimal("0.100")
    assert replay.gross_funding_payments == 0
    assert replay.net_funding_pnl == Decimal("0.100")
    assert replay.active_funding_settlements == 1
    expected_turnover = (Decimal("0.1") + Decimal("100") / Decimal("1000.1")) * Decimal("52")
    assert replay.annualized_one_way_turnover == expected_turnover
    verify_window_replay(
        result={
            "components": {"funding_pnl": "0.100"},
            "annualized_one_way_turnover": str(expected_turnover),
            "active_funding_settlements": 1,
        },
        replay=replay,
    )


def test_replay_detects_active_state_or_position_drift() -> None:
    bad = events()
    bad[1]["active_before"] = False
    with pytest.raises(C6AError, match="active-state"):
        replay_window_events(events=bad, market=market(), scored_weeks=1)

    bad = events()
    bad[0]["spot_quantity_before"] = "1"
    with pytest.raises(C6AError, match="position replay"):
        replay_window_events(events=bad, market=market(), scored_weeks=1)
