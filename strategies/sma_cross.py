"""Example: moving-average trend follower with an ATR stop (holds for days, so it crosses futures rolls).

  - Long when the fast average crosses above the slow one, short on the opposite cross.
  - Stop-loss = `atr_mult` x ATR from the entry; no profit target; exit on the opposite cross.
  - Use on hourly bars, e.g.  --tf 60
"""
import numpy as np
from engine import Strategy


class SMACross(Strategy):
    params = dict(fast=20, slow=50, atr_len=14, atr_mult=3.0, risk_usd=500.0)

    def prepare(self, df):
        p = self.p
        df["fast"] = df.c.rolling(p["fast"]).mean()
        df["slow"] = df.c.rolling(p["slow"]).mean()
        tr = np.maximum(df.h - df.l, np.maximum((df.h - df.c.shift()).abs(), (df.l - df.c.shift()).abs()))
        df["atr"] = tr.rolling(p["atr_len"]).mean()
        return df

    def on_bar(self, i):
        if i == 0:
            return
        d, b, p = self.d, self.broker, self.p
        f0, s0, f1, s1, atr = d["fast"][i - 1], d["slow"][i - 1], d["fast"][i], d["slow"][i], d["atr"][i]
        if s0 != s0 or atr != atr:
            return
        up, down = f0 <= s0 and f1 > s1, f0 >= s0 and f1 < s1
        if (up and b.position < 0) or (down and b.position > 0):
            b.close("signal")
        if up and b.position <= 0:
            b.buy(sl_dist=p["atr_mult"] * atr, risk_usd=p["risk_usd"], tag="long")
        elif down and b.position >= 0:
            b.sell(sl_dist=p["atr_mult"] * atr, risk_usd=p["risk_usd"], tag="short")


STRATEGY = SMACross
