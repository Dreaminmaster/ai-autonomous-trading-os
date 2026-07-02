from pandas import DataFrame
from freqtrade.strategy import IStrategy


class RsiMeanReversion(IStrategy):
    """RSI Mean Reversion — baseline comparison strategy.
    BUY when RSI < 30 (oversold), EXIT when RSI > 70 (overbought).
    """

    INTERFACE_VERSION = 3
    can_short = False
    timeframe = "5m"
    stoploss = -0.10
    trailing_stop = False
    process_only_new_candles = True
    use_exit_signal = True
    startup_candle_count = 14

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        delta = dataframe["close"].diff()
        gain = delta.clip(lower=0).rolling(window=14).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 1)
        dataframe["rsi"] = 100 - (100 / (1 + rs))
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["rsi"] < 30, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["rsi"] > 70, "exit_long"] = 1
        return dataframe
