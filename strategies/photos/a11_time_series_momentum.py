"""A11 - Time-series momentum (photos IMG_2713, 2720, 2727): "buy when the 20-day return > 5% (or price above
the 50-day MA), exit on trend break".
ASSUMPTION: exit ("trend break") = close below the `exit_ma`-day simple moving average. Long only.
The return is measured in % of the real (unadjusted) price.
"""
from engine import indicators as ind
from engine.strategy_kit import SignalStrategy


class TSMomentum(SignalStrategy):
    params = dict(lookback=20, threshold_pct=5.0, exit_ma=50)
    GRID = dict(lookback=[20, 60], threshold_pct=[3.0, 5.0, 8.0], exit_ma=[50, 100])
    TF, SESSIONS = 1440, ("rth", "full")
    PRICE_PCT = ("threshold_pct",)          # thresholds in % of price (scaled when run on other bar sizes)

    def signals(self, df):
        p = self.p
        ret = ind.pct_of_price(df.c - df.c.shift(p["lookback"]), df, lag=p["lookback"])
        ma = ind.sma(df.c, p["exit_ma"])
        return {"long_entry": ret > p["threshold_pct"], "long_exit": df.c < ma}


STRATEGY = TSMomentum
