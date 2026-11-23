"""A1 - RSI + EMA + VWAP pullback (photo IMG_2695, QuantifiedStrategies, QQQ daily).

Entry (all at the close, buy the next open):  RSI(3) < 22;  EMA(100) today > EMA(100) 5 days ago;
close at least 1% below the 10-day rolling VWAP.      Exit: next open after RSI(3) > 55.   Long only.
Complete rules from the photo (no assumptions).
"""
from engine import indicators as ind
from engine.strategy_kit import SignalStrategy


class RsiEmaVwap(SignalStrategy):
    params = dict(rsi_len=3, rsi_entry=22, rsi_exit=55, ema_len=100, ema_lag=5, vwap_len=10, vwap_disc_pct=1.0)
    GRID = dict(rsi_entry=[15, 22, 30], rsi_exit=[50, 55, 65], vwap_disc_pct=[0.5, 1.0, 1.5])
    TF, SESSIONS = 1440, ("rth", "full")
    PRICE_PCT = ("vwap_disc_pct",)          # thresholds in % of price (scaled when run on other bar sizes)

    def signals(self, df):
        p = self.p
        r = ind.rsi(df.c, p["rsi_len"])
        e = ind.ema(df.c, p["ema_len"])
        vwap = ind.rolling_vwap(df.h, df.l, df.c, df.v, p["vwap_len"])
        below = ind.pct_of_price(df.c - vwap, df) <= -p["vwap_disc_pct"]
        return {"long_entry": (r < p["rsi_entry"]) & (e > e.shift(p["ema_lag"])) & below,
                "long_exit": r > p["rsi_exit"]}


STRATEGY = RsiEmaVwap
