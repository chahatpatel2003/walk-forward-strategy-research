"""Example: New York opening-range breakout.

Rules
  - Opening range = high/low of the first `or_minutes` after 09:30 New York time.
  - When the range is complete, place a buy stop at the range high and a sell stop at the range low
    (one-cancels-other: when one fills, the other is cancelled). One trade per day.
  - Stop-loss = the other side of the range. Take-profit = `rr` x the risk.
  - Unfilled orders are cancelled at `last_entry`. Any open trade is closed at `flat_at`.
  - Size: risk `risk_usd` dollars per trade (rounded down to whole contracts / 0.01 lots).
"""
import numpy as np
from engine import Strategy


class ORB(Strategy):
    params = dict(or_start=9 * 60 + 30, or_minutes=15, rr=2.0, risk_usd=500.0,
                  last_entry=11 * 60 + 30, flat_at=15 * 60 + 55, min_range=0.0)

    def prepare(self, df):
        p = self.p
        tf = int(np.median(np.diff(df.ts.values[:5000])) // 60) or 1
        or_end = p["or_start"] + p["or_minutes"]
        m = df.ny_min.astype(int)
        in_win = (m >= p["or_start"]) & (m < or_end)
        hi = df.h.where(in_win).groupby(df.tday).transform("max")
        lo = df.l.where(in_win).groupby(df.tday).transform("min")
        # The window's last bar has closed. Evening bars (18:00-23:59 ET) belong to the NEXT trading day,
        # so they must not see that day's range (the look-ahead checker catches this if you forget).
        known = (m + tf >= or_end) & (m < 18 * 60)
        df["or_hi"] = hi.where(known)
        df["or_lo"] = lo.where(known)
        self.tf = tf
        return df

    def on_bar(self, i):
        d, b, p = self.d, self.broker, self.p
        day, m = d["tday"][i], d["ny_min"][i]
        if day != getattr(self, "_day", None):
            self._day, self._placed = day, False
            b.cancel_all()
        if not b.flat and m >= p["flat_at"]:
            b.close("eod"); return
        if b.orders and m >= p["last_entry"]:
            b.cancel_all()
        if self._placed or not b.flat or m >= p["last_entry"]:
            return
        hi, lo = d["or_hi"][i], d["or_lo"][i]
        if hi != hi or lo != lo or hi - lo <= p["min_range"]:   # NaN check
            return
        b.buy(kind="stop", price=hi, sl=lo, tp_r=p["rr"], risk_usd=p["risk_usd"], tag="orb_long")
        b.sell(kind="stop", price=lo, sl=hi, tp_r=p["rr"], risk_usd=p["risk_usd"], tag="orb_short")
        self._placed = True


STRATEGY = ORB
