"""Building block for rule-based strategies: compute entry/exit signals in prepare(), trade them on the
next bar's open.

A subclass implements `signals(df)` and returns a dict of boolean Series (any it doesn't need can be left out):
  long_entry, long_exit, short_entry, short_exit
A signal on bar i is acted on at bar i+1's open (an exit has priority over a new entry on the same bar).
Signals on exchange holidays (futures/CFD holiday sessions) are ignored: decisions are made on trading days only.
Sizing: `notional` dollars of contract value (default), or `qty` contracts/lots. Optional `max_hold` bars.
Optional hard stop: `stop_atr` = k puts a stop-loss k x ATR(`atr_period`) from the fill (Wilder ATR of the decision
bar, known when the order is placed). None (the default) = no stop, exactly as before.
Optional intraday mode: `flat_at` = minute of the New York day (e.g. 955 = 15:55). Every position is closed so that the
exit fills at the last bar starting at or before min(flat_at, session close - 5 min) (12:55 on half days), no new
entry is placed from then on, and orders are intraday (a missing afternoon is closed at the next session's first bar).
"""
import numpy as np
import pandas as pd

from .core import Strategy


def bar_minutes(df: pd.DataFrame, p: dict) -> int:
    """The declared bar size (strategy param `bar_minutes`, else df.attrs set by data.resample); frames that declare
    nothing (hand-built test data) fall back to the median step of their first 5,000 bars."""
    tf = p.get("bar_minutes") or df.attrs.get("bar_minutes")
    if not tf:
        steps = np.diff(df.ts.to_numpy()[:5000])
        tf = int(np.median(steps) // 60) if len(steps) else 1
    return max(int(tf), 1)


def end_of_day(df: pd.DataFrame, flat_at: int, tf: int) -> np.ndarray:
    """True on bar i when a close decided now is the last one that still fills (at bar i+1's open) by the flat time:
    the bar after next would start later than min(flat_at, session close - 5). Evening bars are never flagged."""
    from .calendar import session_close_minute
    flat = np.minimum(int(flat_at), session_close_minute(df.tday.to_numpy()) - 5)
    m = df.ny_min.to_numpy().astype(int)
    return (m + 2 * tf > flat) & (m < 18 * 60)


class SignalStrategy(Strategy):
    params: dict = {}
    base_params = dict(notional=100_000.0, qty=None, max_hold=None, stop_atr=None, atr_period=14, flat_at=None,
                       bar_minutes=None)

    def __init__(self, **params):
        super().__init__(**{**self.base_params, **self.params, **params})

    LENGTH_SUFFIXES = ("_len", "window", "lookback", "_ma", "_n", "_slow", "_lag")

    def warmup_bars(self) -> int:
        """Bars of history before the first trusted signal: 3 x the longest lookback (an EMA needs ~3 lengths to forget
        its starting value). Used to size every window's warm-up on any bar size."""
        n = [v for k, v in self.p.items() if isinstance(v, (int, np.integer)) and not isinstance(v, bool)
             and k.endswith(self.LENGTH_SUFFIXES)]
        w = 3 * max(n) + 2 if n else 0
        if self.p.get("stop_atr"):
            w = max(w, 3 * int(self.p["atr_period"]) + 2)
        return w

    def signals(self, df: pd.DataFrame) -> dict:
        raise NotImplementedError

    def prepare(self, df):
        sig = self.signals(df)
        # decisions only on exchange trading days (futures/CFD holiday sessions are not decision days)
        from .calendar import holidays
        hol = holidays()
        days = df.tday.to_numpy().astype("datetime64[D]")
        uniq, inv = np.unique(days, return_inverse=True)
        trading = np.array([d.astype(object) not in hol for d in uniq])[inv]
        for k in ("long_entry", "long_exit", "short_entry", "short_exit"):
            s = sig.get(k)
            v = s.fillna(False).astype(bool).to_numpy() if s is not None else np.zeros(len(df), dtype=bool)
            df["sig_" + k] = v & trading
        if self.p.get("stop_atr"):
            pc = df.c.shift(1)
            tr = np.maximum(df.h - df.l, np.maximum((df.h - pc).abs(), (df.l - pc).abs())).fillna(df.h - df.l)
            n = int(self.p["atr_period"])
            df["kit_atr"] = tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy()
        if self.p.get("flat_at"):
            df["kit_eod"] = end_of_day(df, self.p["flat_at"], bar_minutes(df, self.p))
        return df

    def _size(self, i=None):
        out = dict(qty=self.p["qty"]) if self.p.get("qty") else dict(notional_usd=self.p["notional"])
        if self.p.get("stop_atr") and i is not None:
            a = self.d["kit_atr"][i]
            if not (a > 0):                                     # ATR not ready yet: no entry
                return None
            out["sl_dist"] = float(self.p["stop_atr"]) * a
        if self.p.get("flat_at"):
            out["intraday"] = True
        return out

    def on_bar(self, i):
        d, b, p = self.d, self.broker, self.p
        pos = b.position
        held = b.bars_in_trade() + 1 if pos else 0
        timed_out = p.get("max_hold") and held >= p["max_hold"]
        if p.get("flat_at") and d["kit_eod"][i]:              # intraday: out before the close, no new entry
            if pos:
                b.close("eod")
            return
        if pos > 0 and (d["sig_long_exit"][i] or timed_out):
            b.close("signal" if d["sig_long_exit"][i] else "max_hold"); return
        if pos < 0 and (d["sig_short_exit"][i] or timed_out):
            b.close("signal" if d["sig_short_exit"][i] else "max_hold"); return
        if pos == 0 and not b.orders:
            if d["sig_long_entry"][i] or d["sig_short_entry"][i]:
                size = self._size(i)
                if size is None:
                    return
                if d["sig_long_entry"][i]:
                    b.buy(**size, tag="long")
                else:
                    b.sell(**size, tag="short")
