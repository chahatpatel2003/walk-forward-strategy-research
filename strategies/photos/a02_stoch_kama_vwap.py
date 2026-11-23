"""A2 - Stochastic + KAMA + VWAP (photo IMG_2696, QuantifiedStrategies, SPY daily).

Photo: Stochastic(21,3) below 55; KAMA(10) with fast 3 / slow 75 as trend filter; 200-day rolling VWAP
with 1.005 / 0.995 buffers as price filter; buy next open; exit on signal recovery or after 25 days.
ASSUMPTIONS (not in the photo): %K = 21-bar stochastic smoothed over 3 bars; trend filter = close above
KAMA; price filter = close at least `vwap_buffer_pct` below the 200-day VWAP (0.5% = the 0.995 buffer);
"recovery" = %K back above the entry level.
"""
from engine import indicators as ind
from engine.strategy_kit import SignalStrategy


class StochKamaVwap(SignalStrategy):
    params = dict(k_len=21, k_smooth=3, k_entry=55, kama_n=10, kama_fast=3, kama_slow=75, vwap_len=200,
                  vwap_buffer_pct=0.5, max_hold=25)
    GRID = dict(k_entry=[40, 55, 70], vwap_buffer_pct=[0.0, 0.5, 1.0], max_hold=[10, 25])
    TF, SESSIONS = 1440, ("rth", "full")
    PRICE_PCT = ("vwap_buffer_pct",)          # thresholds in % of price (scaled when run on other bar sizes)

    def signals(self, df):
        p = self.p
        k = ind.stochastic_k(df.h, df.l, df.c, p["k_len"], p["k_smooth"])
        km = ind.kama(df.c, p["kama_n"], p["kama_fast"], p["kama_slow"])
        vwap = ind.rolling_vwap(df.h, df.l, df.c, df.v, p["vwap_len"])
        below = ind.pct_of_price(df.c - vwap, df) <= -p["vwap_buffer_pct"]
        return {"long_entry": (k < p["k_entry"]) & (df.c > km) & below, "long_exit": k > p["k_entry"]}


STRATEGY = StochKamaVwap
