from __future__ import annotations


def moving_average(values: list[float], window: int) -> float:
    if not values:
        return 0.0
    if len(values) < window:
        return sum(values) / len(values)
    return sum(values[-window:]) / window


def simple_return(previous: float, current: float) -> float:
    if previous == 0:
        return 0.0
    return (current - previous) / previous
