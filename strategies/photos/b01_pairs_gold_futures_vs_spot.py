"""B1 - Pairs / statistical arbitrage: gold futures (MGC) vs spot gold (XAUUSD).
Photos IMG_2705-2706, 2713, 2719 (basis trade), 2729, 2732, 2736-2747.

Spread = A - beta x B, where A = gold futures (back-adjusted), B = XAUUSD mid, and beta = rolling OLS slope of A
on B over `window` bars. z = (spread - its rolling mean) / its rolling std over the same window.
Long the spread (buy MGC, sell XAUUSD) when z < -entry; short it when z > +entry; exit when z returns inside
+-exit; stop when |z| > stop. Photo values: window 60 days, entry 2, exit 0.5, stop 4.
Size: `notional` of MGC contract value; XAUUSD leg = beta x the same number of ounces (0.01-lot steps).
Hourly bars; one window = 60 trading days x 23 hours = 1380 bars.
Note: this pair is really futures-vs-spot "basis": the gap is mostly interest-rate carry, which drifts.
"""
import numpy as np
import pandas as pd

from engine import Strategy


class GoldBasisPairs(Strategy):
    ENGINE, LEGS, INST_B = "pairs", ("GC", "XAUUSD"), "XAUUSD"
    TF, SESSIONS, MARKETS = 60, ("full",), ("MGC",)
    params = dict(window=1380, entry=2.0, exit=0.5, stop=4.0, notional=100_000.0)
    GRID = dict(window=[460, 1380, 2760], entry=[1.5, 2.0, 2.5], exit=[0.0, 0.5])

    def warmup_bars(self) -> int:
        # beta needs `window` bars; the spread's z-score needs `window` spreads -> 2 x window - 1 bars
        return 2 * self.p["window"]

    def prepare(self, df):
        w = self.p["window"]
        a, b = df.c, df.xc
        ma, mb = a.rolling(w, min_periods=w).mean(), b.rolling(w, min_periods=w).mean()
        cov = (a * b).rolling(w, min_periods=w).mean() - ma * mb
        var = (b * b).rolling(w, min_periods=w).mean() - mb * mb
        beta = (cov / var).where(var > 0)
        spread = a - beta * b
        m, sd = spread.rolling(w, min_periods=w).mean(), spread.rolling(w, min_periods=w).std(ddof=0)
        df["beta"] = beta
        df["z"] = ((spread - m) / sd).where(sd > 0)
        return df

    def on_bar(self, i):
        d, b, p = self.d, self.broker, self.p
        z, beta = d["z"][i], d["beta"][i]
        if z != z or beta != beta:
            return
        if b.flat:
            if z < -p["entry"]:
                b.open(+1, beta, "long_spread")
            elif z > p["entry"]:
                b.open(-1, beta, "short_spread")
        elif b.position > 0 and (z > -p["exit"] or z < -p["stop"]):
            b.close("stop" if z < -p["stop"] else "exit")
        elif b.position < 0 and (z < p["exit"] or z > p["stop"]):
            b.close("stop" if z > p["stop"] else "exit")


STRATEGY = GoldBasisPairs
