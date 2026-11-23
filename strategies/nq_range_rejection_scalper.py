"""One-minute price rejections and trend pullbacks for the New York session."""
import numpy as np

from strategies.nq_order_flow_scalper import OneMinuteScalper


class NQRangeRejectionScalper(OneMinuteScalper):
    params = dict(mode="range", lookback=12, hold=8, stop_atr=0.65, target_r=1.5, atr_period=14,
                  risk_usd=200., pullback_ticks=2)

    def prepare(self, df):
        minutes = self.cash_minutes(df)
        p = self.p
        n = p["lookback"]
        if not isinstance(n, (int, np.integer)) or n < 2:
            raise ValueError("lookback must be an integer of at least two minutes")
        atr = self.atr(df)
        if p["mode"] == "range":
            prev_high = df.h.shift().rolling(n).max()
            prev_low = df.l.shift().rolling(n).min()
            long = df.l.lt(prev_low) & df.c.gt(prev_low)
            short = df.h.gt(prev_high) & df.c.lt(prev_high)
        elif p["mode"] == "deviation":
            center = df.c.shift().rolling(n).mean()
            width = 2.0 * df.c.shift().rolling(n).std(ddof=0)
            lower, upper = center - width, center + width
            long = df.l.lt(lower) & df.c.gt(lower)
            short = df.h.gt(upper) & df.c.lt(upper)
        elif p["mode"] == "trend_pullback":
            center = df.c.shift().ewm(span=n, adjust=False, min_periods=n).mean()
            slope = center.diff(5)
            long = df.l.lt(center) & df.c.gt(center) & df.c.shift().gt(center.shift()) & slope.gt(0.25*atr)
            short = df.h.gt(center) & df.c.lt(center) & df.c.shift().lt(center.shift()) & slope.lt(-0.25*atr)
        else:
            raise ValueError("mode must be range, deviation, or trend_pullback")

        contiguous = df.tday.eq(df.tday.shift(n)) & df.ts.sub(df.ts.shift(n)).eq(n * 60)
        middle = (df.h + df.l) / 2
        side = np.select([contiguous & long & ~short & df.c.gt(middle),
                          contiguous & short & ~long & df.c.lt(middle)], [1, -1], default=0)
        return self.annotate(df, minutes, side, atr)


STRATEGY = NQRangeRejectionScalper
