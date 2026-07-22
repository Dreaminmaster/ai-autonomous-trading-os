"""Independent replay of retained C6A events from primitive market inputs."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from atos.c6a_contract import C6AError, SPOT_INSTRUMENTS, SPOT_TO_SWAP, decimal_value, parse_timestamp
from atos.c6a_data import C6AMarket
from atos.c6a_metrics import annualized_one_way_turnover

ZERO = Decimal("0")


@dataclass(frozen=True)
class ReplayResult:
    gross_funding_receipts: Decimal
    gross_funding_payments: Decimal
    net_funding_pnl: Decimal
    active_funding_settlements: int
    normalized_turnover_events: tuple[Decimal, ...]
    annualized_one_way_turnover: Decimal
    funding_rows: tuple[Mapping[str, Any], ...]


def replay_window_events(
    *,
    events: Sequence[Mapping[str, Any]],
    market: C6AMarket,
    scored_weeks: int = 26,
) -> ReplayResult:
    market.validate_alignment()
    timestamps = tuple(row.timestamp for row in market.spot[SPOT_INSTRUMENTS[0]])
    index_by_time = {timestamp: index for index, timestamp in enumerate(timestamps)}
    spot_quantity = {spot: ZERO for spot in SPOT_INSTRUMENTS}
    perpetual_quantity = {spot: ZERO for spot in SPOT_INSTRUMENTS}
    receipts = ZERO
    payments = ZERO
    active_settlements = 0
    turnover: list[Decimal] = []
    funding_rows: list[Mapping[str, Any]] = []

    for sequence, event in enumerate(events):
        kind = str(event.get("kind", ""))
        timestamp = parse_timestamp(event.get("time"))
        if timestamp not in index_by_time:
            raise C6AError(f"event timestamp absent from market: {timestamp.isoformat()}")
        index = index_by_time[timestamp]

        if kind == "FUNDING":
            instrument = str(event.get("instrument", ""))
            matches = [spot for spot, swap in SPOT_TO_SWAP.items() if swap == instrument]
            if len(matches) != 1:
                raise C6AError(f"unknown funding event instrument: {instrument}")
            spot = matches[0]
            if index == 0:
                raise C6AError("funding replay lacks preceding mark candle")
            mark = market.mark[instrument][index - 1].close
            rate = decimal_value(event.get("realized_rate"), "realized funding rate")
            quantity = perpetual_quantity[spot]
            active = quantity > 0
            if bool(event.get("active_before")) != active:
                raise C6AError("funding active-state replay mismatch")
            pnl = quantity * mark * rate
            receipts += max(pnl, ZERO)
            payments += max(-pnl, ZERO)
            active_settlements += int(active)
            funding_rows.append(
                {
                    "sequence": sequence,
                    "time": timestamp.isoformat(),
                    "instrument": instrument,
                    "perpetual_base_quantity": str(quantity),
                    "preceding_mark_close": str(mark),
                    "realized_rate": str(rate),
                    "funding_pnl": str(pnl),
                }
            )
            continue

        if kind == "SCHEDULED_TRADE":
            spot = str(event.get("spot_instrument", ""))
            if spot not in SPOT_INSTRUMENTS:
                raise C6AError(f"unknown scheduled-trade spot: {spot}")
            before_spot = decimal_value(event.get("spot_quantity_before"), "spot quantity before")
            before_swap = decimal_value(event.get("perpetual_base_before"), "swap quantity before")
            if before_spot != spot_quantity[spot] or before_swap != perpetual_quantity[spot]:
                raise C6AError("scheduled-trade position replay mismatch")
            spot_quantity[spot] = decimal_value(event.get("spot_quantity_after"), "spot quantity after")
            perpetual_quantity[spot] = decimal_value(
                event.get("perpetual_base_after"), "swap quantity after"
            )
            turnover.append(
                decimal_value(
                    event.get("normalized_one_way_turnover"),
                    "scheduled normalized turnover",
                )
            )
            continue

        if kind in {"RISK_EXIT", "TERMINAL_LIQUIDATION"}:
            spot = str(event.get("spot_instrument", ""))
            if spot not in SPOT_INSTRUMENTS:
                raise C6AError(f"unknown close-event spot: {spot}")
            equity = decimal_value(event.get("equity_before"), "close-event equity")
            if equity <= 0:
                raise C6AError("close-event equity must be positive")
            spot_open = market.spot[spot][index].open
            swap_open = market.swap[SPOT_TO_SWAP[spot]][index].open
            paired = Decimal("0.5") * (
                spot_quantity[spot] * spot_open
                + perpetual_quantity[spot] * swap_open
            )
            turnover.append(paired / equity)
            spot_quantity[spot] = ZERO
            perpetual_quantity[spot] = ZERO
            continue

        raise C6AError(f"unknown retained event kind: {kind}")

    if any(value != 0 for value in (*spot_quantity.values(), *perpetual_quantity.values())):
        raise C6AError("event replay ended with open positions")
    return ReplayResult(
        gross_funding_receipts=receipts,
        gross_funding_payments=payments,
        net_funding_pnl=receipts - payments,
        active_funding_settlements=active_settlements,
        normalized_turnover_events=tuple(turnover),
        annualized_one_way_turnover=annualized_one_way_turnover(
            turnover, scored_weeks=scored_weeks
        ),
        funding_rows=tuple(funding_rows),
    )


def verify_window_replay(
    *, result: Mapping[str, Any], replay: ReplayResult
) -> None:
    components = result.get("components")
    if not isinstance(components, Mapping):
        raise C6AError("window result components missing")
    retained_funding = decimal_value(components.get("funding_pnl"), "retained funding PnL")
    retained_turnover = decimal_value(
        result.get("annualized_one_way_turnover"), "retained turnover"
    )
    if retained_funding != replay.net_funding_pnl:
        raise C6AError("funding replay mismatch")
    if retained_turnover != replay.annualized_one_way_turnover:
        raise C6AError("turnover replay mismatch")
    if int(result.get("active_funding_settlements", -1)) != replay.active_funding_settlements:
        raise C6AError("active funding-settlement replay mismatch")
