"""A6 - "Rubber Band" (photo IMG_2714 #2, QuantifiedStrategies, SPY daily): buys on a close below a
volatility band, exits on the breakout. 77% win rate claimed.
ASSUMPTIONS (band not defined in the photo; QuantifiedStrategies' published version as I recall it,
unverified): band = highest high of the last 5 days - 2.5 x the 10-day average (high - low);
buy when the close is below the band; sell when the close is above yesterday's high.
The photo buys at the close; here the order fills at the next open (we can't trade a close we've just seen).
"""
from engine import indicators as ind
from engine.strategy_kit import SignalStrategy


class RubberBand(SignalStrategy):
    params = dict(hh_len=5, range_len=10, mult=2.5)
    GRID = dict(hh_len=[5, 10], range_len=[10, 20], mult=[2.0, 2.5, 3.0])
    TF, SESSIONS = 1440, ("rth", "full")

    def signals(self, df):
        p = self.p
        band = df.h.rolling(p["hh_len"], min_periods=p["hh_len"]).max() - p["mult"] * ind.avg_range(df.h, df.l, p["range_len"])
        return {"long_entry": df.c < band, "long_exit": df.c > df.h.shift()}


STRATEGY = RubberBand
