"""Shared deterministic helpers for C1A backtest-only strategies."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import math
import pandas as pd
from pandas import DataFrame
from freqtrade.exchange import timeframe_to_prev_date
from freqtrade.persistence import Trade
from freqtrade.strategy import merge_informative_pair, stoploss_from_absolute


BTC_PAIR = "BTC/USDT"
DAILY_TIMEFRAME = "1d"


def true_range(dataframe: DataFrame) -> pd.Series:
    previous = dataframe["close"].shift(1)
    return pd.concat(
        [
            dataframe["high"] - dataframe["low"],
            (dataframe["high"] - previous).abs(),
            (dataframe["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    average_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = average_gain / average_loss.replace(0.0, float("nan"))
    rsi = 100.0 - (100.0 / (1.0 + relative_strength))
    return rsi.where(average_loss != 0.0, 100.0)


def informative_pairs(strategy: Any) -> list[tuple[str, str]]:
    if getattr(strategy, "dp", None) is None:
        return []
    pairs = set(strategy.dp.current_whitelist())
    pairs.add(BTC_PAIR)
    return sorted((pair, DAILY_TIMEFRAME) for pair in pairs)


def _pair_daily(dataframe: DataFrame) -> DataFrame:
    result = dataframe.copy().sort_values("date")
    result["pair_close"] = result["close"]
    result["pair_ema90"] = result["close"].ewm(span=90, adjust=False).mean()
    result["pair_return_20d"] = result["close"].pct_change(20)
    result["pair_return_60d"] = result["close"].pct_change(60)
    return result[
        ["date", "pair_close", "pair_ema90", "pair_return_20d", "pair_return_60d"]
    ]


def _btc_daily(dataframe: DataFrame) -> DataFrame:
    result = dataframe.copy().sort_values("date")
    result["btc_close"] = result["close"]
    result["btc_ema90"] = result["close"].ewm(span=90, adjust=False).mean()
    result["btc_ema20"] = result["close"].ewm(span=20, adjust=False).mean()
    result["btc_ema20_slope_5"] = result["btc_ema20"].pct_change(5)
    result["btc_return_20d"] = result["close"].pct_change(20)
    return result[
        ["date", "btc_close", "btc_ema90", "btc_ema20", "btc_ema20_slope_5", "btc_return_20d"]
    ]


def merge_daily_context(
    strategy: Any, dataframe: DataFrame, metadata: dict[str, Any]
) -> DataFrame:
    required = [
        "pair_close_1d",
        "pair_ema90_1d",
        "pair_return_20d_1d",
        "pair_return_60d_1d",
        "btc_close_1d",
        "btc_ema90_1d",
        "btc_ema20_1d",
        "btc_ema20_slope_5_1d",
        "btc_return_20d_1d",
    ]
    if getattr(strategy, "dp", None) is None:
        for column in required:
            dataframe[column] = float("nan")
        return dataframe

    pair_daily = _pair_daily(
        strategy.dp.get_pair_dataframe(pair=metadata["pair"], timeframe=DAILY_TIMEFRAME)
    )
    btc_daily = _btc_daily(
        strategy.dp.get_pair_dataframe(pair=BTC_PAIR, timeframe=DAILY_TIMEFRAME)
    )
    daily = pair_daily.merge(
        btc_daily,
        on="date",
        how="left",
        validate="one_to_one",
    ).sort_values("date")
    return merge_informative_pair(
        dataframe,
        daily,
        strategy.timeframe,
        DAILY_TIMEFRAME,
        ffill=True,
    )


def broad_regime(dataframe: DataFrame) -> pd.Series:
    return (
        (dataframe["btc_close_1d"] > dataframe["btc_ema90_1d"])
        & (dataframe["btc_ema20_slope_5_1d"] > 0.0)
    )


def pair_regime(dataframe: DataFrame) -> pd.Series:
    return dataframe["pair_close_1d"] > dataframe["pair_ema90_1d"]


def atr_stoploss_from_entry(
    strategy: Any,
    pair: str,
    trade: Trade,
    current_time: datetime,
    current_rate: float,
) -> float | None:
    del current_time
    if getattr(strategy, "dp", None) is None:
        return None
    dataframe, _ = strategy.dp.get_analyzed_dataframe(pair, strategy.timeframe)
    if dataframe.empty or "atr_14" not in dataframe:
        return None
    trade_date = timeframe_to_prev_date(strategy.timeframe, trade.open_date_utc)
    eligible = dataframe.loc[dataframe["date"] <= trade_date]
    if eligible.empty:
        return None
    entry_atr = float(eligible.iloc[-1]["atr_14"])
    if not math.isfinite(entry_atr) or entry_atr <= 0.0:
        return None
    stop_price = float(trade.open_rate) - 2.5 * entry_atr
    if not math.isfinite(stop_price) or stop_price <= 0.0 or stop_price >= current_rate:
        return None
    return stoploss_from_absolute(
        stop_price,
        current_rate=current_rate,
        is_short=trade.is_short,
        leverage=trade.leverage,
    )
