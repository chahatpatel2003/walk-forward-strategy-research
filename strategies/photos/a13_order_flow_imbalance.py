"""A13 - Order-flow imbalance, slow version (photos IMG_2711-2712): OFI = buyer-initiated volume - seller-
initiated volume; next move ~= lambda x OFI, lambda from rolling regressions. NQ only (needs aggressor-side
volume). The photo's sub-millisecond HFT version can't be tested; this is a 1-minute version on the New York
cash session, traded strictly intraday.
Rules: lambda = rolling OLS slope of the next-minute price change on this minute's OFI, over the last `window`
in-session samples (a sample never spans a session gap or a missing bar: the overnight move is excluded).
Input must be cash-session bars (session='rth'); other sessions are refused. Predicted move =
lambda x OFI. If it exceeds `threshold_ticks` ticks: buy (or sell if below minus that) at the next open, hold
`hold` bars. No new entries in the last `no_entry_min` minutes of the session; any position is closed at the
session's last minute (16:00, or 13:00 on half days). Orders are intraday: one that hasn't filled by the end of
its day expires, and if the data has no bar left to close a position in its own session, the engine closes it at
the next session's first open and labels the trade 'session_gap_exit'. One contract per trade.
"""
import numpy as np
import pandas as pd

from engine import Strategy
from engine.calendar import session_close_minute


def bar_minutes_so_far(ts: np.ndarray, tday: np.ndarray) -> np.ndarray:
    """Bar size in minutes as known AT each row: the most common step between consecutive bars of the same day
    among rows 0..i (ties -> the smaller step). Uses past rows only, so it is the same on any prefix of the data
    (a whole-frame median is not: 1-hour cash bars start with a 30-minute 09:30 bar). 0 until a step is seen."""
    n = len(ts)
    out = np.zeros(n, dtype=np.int64)
    if n < 2:
        return out
    step = np.r_[0, np.diff(ts) // 60]
    ok = np.r_[False, tday[1:] == tday[:-1]] & (step > 0)
    vals = np.unique(step[ok])
    if not len(vals):
        return out
    best = np.zeros(n, dtype=np.int64)
    for v in vals:                                         # ascending, and only a strictly larger count wins
        c = np.cumsum(ok & (step == v))
        win = c > best
        out[win], best[win] = v, c[win]
    return out


class OrderFlowImbalance(Strategy):
    params = dict(window=1950, threshold_ticks=2.0, hold=2, qty=1, no_entry_min=10)
    GRID = dict(threshold_ticks=[1.0, 2.0, 4.0], hold=[1, 3])
    TF, SESSIONS, MARKETS = 1, ("rth",), ("MNQ",)

    def warmup_bars(self) -> int:
        return self.p["window"] + 2

    def prepare(self, df):
        p = self.p
        if "buy_vol" not in df:
            raise ValueError("order-flow imbalance needs buy_vol / sell_vol (NQ data only)")
        m = df.ny_min.to_numpy()
        if len(df) and ((m < 9 * 60 + 30) | (m >= 16 * 60)).any():
            raise ValueError("order-flow imbalance trades the New York cash session only (09:30-16:00): "
                             "run it with session='rth'")
        tday = df.tday.to_numpy()
        tf = bar_minutes_so_far(df.ts.to_numpy(), tday)
        # a sample needs the previous bar to be exactly one bar earlier in the same session
        steps = np.r_[0, np.diff(df.ts.to_numpy())]
        gap = np.r_[True, tday[1:] != tday[:-1]] | (steps != tf * 60)
        first = gap
        ofi = (df.buy_vol - df.sell_vol).astype(float)
        ret = df.c.diff().mask(first)                             # never the move across a session gap
        x, y = ofi.shift(1).mask(first), ret                      # sample (OFI of bar t-1, move of bar t): complete at t
        ok = x.notna() & y.notna()
        x, y = x.where(ok), y.where(ok)
        w = p["window"]
        cnt = ok.astype(float).rolling(w, min_periods=1).sum()
        mx, my = x.rolling(w, min_periods=1).mean(), y.rolling(w, min_periods=1).mean()
        cov = (x * y).rolling(w, min_periods=1).mean() - mx * my
        var = (x * x).rolling(w, min_periods=1).mean() - mx * mx
        lam = (cov / var).where((var > 0) & (cnt >= w * 0.9))
        df["ofi_ret"] = ret
        df["ofi_pred"] = lam * ofi
        close = session_close_minute(tday)
        df["mins_left"] = (close - df.ny_min.to_numpy()).astype(np.int32)
        df["bar_min"] = np.maximum(tf, 1).astype(np.int32)       # bar size known at that bar (1 until known)
        return df

    def on_bar(self, i):
        d, b, p = self.d, self.broker, self.p
        left, tf = d["mins_left"][i], d["bar_min"][i]
        if not b.flat:
            if b.bars_in_trade() + 1 >= p["hold"] or left <= 2 * tf:       # the next bar is the session's last
                b.close("hold" if left > 2 * tf else "session_end")
            return
        if b.orders or left <= p["no_entry_min"]:
            return
        pr = d["ofi_pred"][i]
        if pr != pr:
            return
        th = p["threshold_ticks"] * self.inst.tick
        if pr > th:
            b.buy(qty=p["qty"], tag="ofi_long", intraday=True)
        elif pr < -th:
            b.sell(qty=p["qty"], tag="ofi_short", intraday=True)


STRATEGY = OrderFlowImbalance
