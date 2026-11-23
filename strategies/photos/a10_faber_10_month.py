"""A10 - Faber tactical allocation (photo IMG_2730): at each month end, hold the market if its close is above
its 10-month simple moving average, otherwise hold cash.
Month-end closes = the close of each month's last trading day (exchange calendar).
"""
import numpy as np
import pandas as pd

from engine.calendar import period_position
from engine.strategy_kit import SignalStrategy


class Faber(SignalStrategy):
    params = dict(months=10)
    GRID = dict(months=[6, 8, 10, 12])
    TF, SESSIONS = 1440, ("rth", "full")

    def signals(self, df):
        p = self.p
        me = period_position(df.tday.to_numpy(), "M").left.to_numpy() == 0
        sma = pd.Series(np.nan, index=df.index)
        sma[me] = df.c[me].rolling(p["months"], min_periods=p["months"]).mean().to_numpy()
        me_s = pd.Series(me, index=df.index)
        return {"long_entry": me_s & (df.c > sma), "long_exit": me_s & (df.c < sma)}


STRATEGY = Faber
