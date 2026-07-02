# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
from functools import reduce
import talib.abstract as ta
import pandas as pd
import numpy as np
from pandas import DataFrame
from freqtrade.strategy import IStrategy


class SmaCrossover(IStrategy):
    """Simple 5/20 SMA Crossover — baseline comparison strategy."""

    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "5m"
    stoploss = -0.10
    trailing_stop = False
    process_only_new_candles = True
    use_exit_signal = True
    startup_candle_count = 40

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["sma5"] = dataframe["close"].rolling(window=5).mean()
        dataframe["sma20"] = dataframe["close"].rolling(window=20).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["sma5"] > dataframe["sma20"]) &
            (dataframe["sma5"].shift(1) <= dataframe["sma20"].shift(1)),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["sma5"] < dataframe["sma20"]),
            "exit_long",
        ] = 1
        return dataframe
