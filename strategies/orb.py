"""Example: New York opening-range breakout.

Rules
  - Opening range = high/low of the first `or_minutes` after 09:30 New York time.
    `or_minutes` and 09:30 must line up with the bar size (e.g. 15-minute range on 1, 5 or 15-minute bars).
  - When the range is complete, place a buy stop at the range high and a sell stop at the range low
    (one-cancels-other: when one fills, the other is cancelled). One trade per day.
  - Stop-loss = the other side of the range. Take-profit = `rr` x the risk.
  - Unfilled orders are cancelled at `last_entry`.
  - Any open trade is closed at `flat_at`, or 5 minutes before an early (13:00) close on half days.
    If a position is somehow still open when a new trading day starts (missing bars), it is closed at once.
  - Size: risk `risk_usd` dollars per trade (rounded down to whole contracts / 0.01 lots).
"""
import numpy as np

from engine import Strategy
from engine.calendar import session_close_minute


class ORB(Strategy):
    params = dict(or_start=9 * 60 + 30, or_minutes=15, rr=2.0, risk_usd=500.0,
                  last_entry=11 * 60 + 30, flat_at=15 * 60 + 55, min_range=0.0)

    def prepare(self, df):
        p = self.p
        steps = np.diff(df.ts.values[:5000])
        tf = int(np.median(steps) // 60) if len(steps) else 1
        tf = max(tf, 1)
        if p["or_minutes"] % tf or p["or_start"] % tf:
            raise ValueError(f"opening range {p['or_minutes']} min from minute {p['or_start']} does not line up "
                             f"with {tf}-minute bars; use a bar size that divides both")
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
        # flatten time per day: normal flat_at, or 5 minutes before a 13:00 early close
        close_min = session_close_minute(df.tday.to_numpy())
        df["flat_min"] = np.minimum(p["flat_at"], close_min - 5).astype(np.int32)
        self.tf = tf
        return df

    def on_bar(self, i):
        d, b, p = self.d, self.broker, self.p
        day, m = d["tday"][i], d["ny_min"][i]
        if day != getattr(self, "_day", None):
            self._day, self._placed = day, False
            b.cancel_all()
            if not b.flat:
                b.close("session_end"); return
        if m >= 18 * 60:                       # evening session: belongs to the next trading day
            return
        if not b.flat and m >= d["flat_min"][i]:
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
