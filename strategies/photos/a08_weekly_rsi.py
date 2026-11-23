"""A8 - Weekly RSI (photo IMG_2714 #5, QuantifiedStrategies, XLP): buy when the 2-week RSI drops below 15.
Invested ~11% of the time.
Weekly closes = the close of each week's last trading day (exchange calendar, known in advance).
ASSUMPTION (exit not in the photo): sell when the weekly RSI(2) is back above 70. Signals are only
evaluated at week ends; orders fill at the next open (the following Monday).
"""
import numpy as np
import pandas as pd

from engine import indicators as ind
from engine.calendar import period_position
from engine.strategy_kit import SignalStrategy


class WeeklyRsi(SignalStrategy):
    params = dict(rsi_len=2, rsi_entry=15, rsi_exit=70)
    GRID = dict(rsi_len=[2, 3], rsi_entry=[10, 15, 25], rsi_exit=[50, 70])
    TF, SESSIONS = 1440, ("rth", "full")

    def signals(self, df):
        p = self.p
        week_end = (period_position(df.tday.to_numpy(), "W").left.to_numpy() == 0)
        r = pd.Series(np.nan, index=df.index)
        r[week_end] = ind.rsi(df.c[week_end], p["rsi_len"]).to_numpy()
        we = pd.Series(week_end, index=df.index)
        return {"long_entry": we & (r < p["rsi_entry"]), "long_exit": we & (r > p["rsi_exit"])}


STRATEGY = WeeklyRsi
