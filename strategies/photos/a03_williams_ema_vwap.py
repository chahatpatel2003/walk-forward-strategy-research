"""A3 - Williams %R + EMA + VWAP (photo IMG_2697, QuantifiedStrategies, QQQ daily).

Photo: %R identifies a pullback; long-term EMA trend filter must be bullish; QQQ below rolling VWAP;
buy next open; exit after momentum recovery; one position at a time.
ASSUMPTIONS (no numbers in the photo): %R(10) < -80; close above EMA(200); close below the 10-day VWAP;
exit when %R > -20. The parameter test explores the %R settings.
"""
from engine import indicators as ind
from engine.strategy_kit import SignalStrategy


class WilliamsEmaVwap(SignalStrategy):
    params = dict(wr_len=10, wr_entry=-80, wr_exit=-20, ema_len=200, vwap_len=10)
    GRID = dict(wr_len=[2, 5, 10], wr_entry=[-90, -80, -70], wr_exit=[-50, -20])
    TF, SESSIONS = 1440, ("rth", "full")

    def signals(self, df):
        p = self.p
        wr = ind.williams_r(df.h, df.l, df.c, p["wr_len"])
        e = ind.ema(df.c, p["ema_len"])
        vwap = ind.rolling_vwap(df.h, df.l, df.c, df.v, p["vwap_len"])
        return {"long_entry": (wr < p["wr_entry"]) & (df.c > e) & (df.c < vwap), "long_exit": wr > p["wr_exit"]}


STRATEGY = WilliamsEmaVwap
