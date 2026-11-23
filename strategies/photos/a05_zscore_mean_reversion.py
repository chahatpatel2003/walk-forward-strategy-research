"""A5 - Z-score mean reversion (photos IMG_2701-2702, 2713, 2736, 2742-2744).

z = (close - rolling mean) / rolling standard deviation over `window` days (photo: 20-60).
Long when z < -entry, short when z > +entry (photo: 2.0). Exit when |z| < exit (photo: 0.5).
Stop: exit when |z| > stop (photo: 4). Applied to one market's price (the photos apply it to a pair spread;
the pairs version is B1).
"""
from engine import indicators as ind
from engine.strategy_kit import SignalStrategy


class ZScoreMR(SignalStrategy):
    params = dict(window=20, entry=2.0, exit=0.5, stop=4.0)
    GRID = dict(window=[20, 40, 60], entry=[1.5, 2.0, 2.5], exit=[0.0, 0.5])
    TF, SESSIONS = 1440, ("rth", "full")

    def signals(self, df):
        p = self.p
        z = ind.zscore(df.c, p["window"])
        return {"long_entry": z < -p["entry"], "long_exit": (z > -p["exit"]) | (z < -p["stop"]),
                "short_entry": z > p["entry"], "short_exit": (z < p["exit"]) | (z > p["stop"])}


STRATEGY = ZScoreMR
