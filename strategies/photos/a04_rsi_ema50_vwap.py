"""A4 - RSI + EMA(50) + VWAP (photo IMG_2698, QuantifiedStrategies, ES futures daily, $30 round trip assumed).

Photo: RSI pullback; EMA(50) confirms trend; ES closes below 10-day rolling VWAP; buy next open; exit after
mean reversion / RSI recovery.
ASSUMPTIONS: RSI(3) < 22 and exit RSI(3) > 55 (as in A1); trend = close above EMA(50). We have no ES data,
so it runs on the Nasdaq and gold markets.
"""
from engine import indicators as ind
from engine.strategy_kit import SignalStrategy


class RsiEma50Vwap(SignalStrategy):
    params = dict(rsi_len=3, rsi_entry=22, rsi_exit=55, ema_len=50, vwap_len=10)
    GRID = dict(rsi_entry=[15, 22, 30], rsi_exit=[50, 55, 65], ema_len=[50, 100])
    TF, SESSIONS = 1440, ("rth", "full")

    def signals(self, df):
        p = self.p
        r = ind.rsi(df.c, p["rsi_len"])
        e = ind.ema(df.c, p["ema_len"])
        vwap = ind.rolling_vwap(df.h, df.l, df.c, df.v, p["vwap_len"])
        return {"long_entry": (r < p["rsi_entry"]) & (df.c > e) & (df.c < vwap), "long_exit": r > p["rsi_exit"]}


STRATEGY = RsiEma50Vwap
