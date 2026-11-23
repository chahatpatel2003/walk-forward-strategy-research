"""NQ/MNQ scalping signals on completed five-minute bars with one-minute execution."""
import math

import numpy as np
import pandas as pd

from engine import data
from strategies.nq_order_flow_scalper import OneMinuteScalper


class NQFiveMinuteScalper(OneMinuteScalper):
    params = dict(mode="trend_pullback", lookback=6, hold=10, stop_points=9., target_r=1.5,
                  atr_period=14, stop_atr=1., atr_stop_multiple=0., risk_usd=200., pullback_ticks=2)

    def prepare(self, df):
        minutes = self.cash_minutes(df)
        p = self.p
        n = p["lookback"]
        if not isinstance(n, (int, np.integer)) or n < 2:
            raise ValueError("lookback must be at least two five-minute bars")
        if not math.isfinite(p["stop_points"]) or p["stop_points"] <= 0:
            raise ValueError("stop_points must be positive and finite")
        if not math.isfinite(p["atr_stop_multiple"]) or p["atr_stop_multiple"] < 0:
            raise ValueError("atr_stop_multiple must be finite and nonnegative")

        # Only expose signals at the close of a full five-minute block. Prefixes ending inside a block,
        # gapped data, and partial session bars must not create a signal that could not have existed live.
        complete = df.ts.mod(300).eq(240) & df.ts.sub(df.ts.shift(4)).eq(240) & df.tday.eq(df.tday.shift(4))
        closed_minutes = df.loc[complete, "ts"]
        coarse = data.resample(df.assign(ts_last=df.ts), 5)
        coarse = coarse[coarse.ts_last.isin(closed_minutes)].reset_index(drop=True)
        context = coarse.ts.sub(coarse.ts.shift(n)).eq(n * 300) & coarse.tday.eq(coarse.tday.shift(n))

        if p["mode"] in {"rejection", "breakout"}:
            prev_high = coarse.h.shift().rolling(n).max()
            prev_low = coarse.l.shift().rolling(n).min()
            if p["mode"] == "rejection":
                mid = (coarse.h + coarse.l) / 2.
                long = coarse.l.lt(prev_low) & coarse.c.gt(prev_low) & coarse.c.gt(mid)
                short = coarse.h.gt(prev_high) & coarse.c.lt(prev_high) & coarse.c.lt(mid)
            else:
                long = coarse.c.gt(prev_high) & coarse.c.gt(coarse.o)
                short = coarse.c.lt(prev_low) & coarse.c.lt(coarse.o)
        elif p["mode"] == "trend_pullback":
            center = coarse.c.shift().ewm(span=n, adjust=False, min_periods=n).mean()
            previous = coarse.c.shift()
            slope = center.diff(2)
            long = coarse.l.lt(center) & coarse.c.gt(center) & previous.gt(center.shift()) & slope.gt(0)
            short = coarse.h.gt(center) & coarse.c.lt(center) & previous.lt(center.shift()) & slope.lt(0)
        else:
            raise ValueError("mode must be rejection, breakout, or trend_pullback")

        signal = np.select([context & long & ~short, context & short & ~long], [1, -1], default=0)
        direction = df.ts.map(pd.Series(signal, index=coarse.ts_last)).fillna(0).to_numpy()
        if p["atr_stop_multiple"]:
            previous = coarse.c.shift().where(coarse.tday.eq(coarse.tday.shift()) & coarse.ts.diff().eq(300), coarse.o)
            tr = np.maximum(coarse.h - coarse.l, np.maximum((coarse.h - previous).abs(), (coarse.l - previous).abs()))
            period = p["atr_period"]
            coarse_distance = p["atr_stop_multiple"] * tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
            distance = df.ts.map(pd.Series(coarse_distance.to_numpy(), index=coarse.ts_last))
        else:
            distance = pd.Series(p["stop_points"], index=df.index)
        return self.annotate(df, minutes, direction, distance)


STRATEGY = NQFiveMinuteScalper
