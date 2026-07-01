from strategy_pool import Candle, default_strategies


def make_candidates():
    candles = [
        Candle(100, 102, 99, 101, 1000),
        Candle(101, 103, 100, 102, 1100),
        Candle(102, 104, 101, 103, 1200),
        Candle(103, 105, 102, 104, 1300),
        Candle(104, 107, 103, 106, 1500),
    ]
    out = []
    for strategy in default_strategies():
        candidate = strategy.generate('BTC-USDT', candles)
        if candidate:
            out.append(candidate.to_dict())
    return out
