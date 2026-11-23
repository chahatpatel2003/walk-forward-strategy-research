"""A12 - Volatility compression breakout (photo IMG_2700, daytrading.co): when price trades in a very tight
range, enter on the breakout with momentum.
ASSUMPTIONS (no rules in the photo), on 15-minute bars:
  squeeze = Bollinger(20, 2) width (in % of price) is in the lowest `squeeze_pct`% of the last 200 bars;
  then place a buy stop at the highest high and a sell stop at the lowest low of the last `range_len` bars
  (one cancels the other), valid for 4 bars; stop-loss = the other side of that range; target = rr x risk;
  exit after `max_hold` bars at the latest. Risk `risk_usd` per trade.
  Optional intraday mode `flat_at` (minute of the New York day): flat before the cash close, as in
  engine.strategy_kit (no new orders from then on; orders and positions are intraday).
"""
import numpy as np

from engine import Strategy
from engine import indicators as ind
from engine.strategy_kit import bar_minutes, end_of_day


class SqueezeBreakout(Strategy):
    params = dict(bb_len=20, bb_k=2.0, lookback=200, squeeze_pct=10, range_len=20, rr=2.0, risk_usd=500.0, max_hold=32,
                  flat_at=None, bar_minutes=None)
    GRID = dict(squeeze_pct=[5, 10, 20], rr=[1.5, 2.0, 3.0])
    TF, SESSIONS = 15, ("full",)

    def warmup_bars(self) -> int:
        return self.p["lookback"] + self.p["bb_len"] + self.p["range_len"]

    def prepare(self, df):
        p = self.p
        mid, up, lo = ind.bollinger(df.c, p["bb_len"], p["bb_k"])
        width = (up - lo) / ind.real_price(df) * 100
        thresh = width.rolling(p["lookback"], min_periods=p["lookback"]).quantile(p["squeeze_pct"] / 100.0)
        df["squeeze"] = (width <= thresh).to_numpy() & thresh.notna().to_numpy()
        df["rng_hi"] = df.h.rolling(p["range_len"], min_periods=p["range_len"]).max()
        df["rng_lo"] = df.l.rolling(p["range_len"], min_periods=p["range_len"]).min()
        if p.get("flat_at"):
            df["kit_eod"] = end_of_day(df, p["flat_at"], bar_minutes(df, p))
        return df

    def on_bar(self, i):
        d, b, p = self.d, self.broker, self.p
        intraday = bool(p.get("flat_at"))
        if intraday and d["kit_eod"][i]:                      # out before the close, no new orders
            b.cancel_all()
            if not b.flat:
                b.close("eod")
            return
        if not b.flat:
            if b.bars_in_trade() + 1 >= p["max_hold"]:
                b.close("max_hold")
            return
        if b.orders or not d["squeeze"][i]:
            return
        hi, lo = d["rng_hi"][i], d["rng_lo"][i]
        if hi != hi or lo != lo or hi <= lo:
            return
        b.buy(kind="stop", price=hi, sl=lo, tp_r=p["rr"], risk_usd=p["risk_usd"], valid_bars=4, tag="breakout_long",
              intraday=intraday)
        b.sell(kind="stop", price=lo, sl=hi, tp_r=p["rr"], risk_usd=p["risk_usd"], valid_bars=4, tag="breakout_short",
               intraday=intraday)


STRATEGY = SqueezeBreakout
