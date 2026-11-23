"""A7 - MFI reversal (photo IMG_2714 #3, QuantifiedStrategies, QQQ daily): buy when the 2-day Money Flow
Index drops below 10. 70% win rate claimed.
ASSUMPTION (exit not in the photo): sell when the close is above yesterday's high.
"""
from engine import indicators as ind
from engine.strategy_kit import SignalStrategy


class MfiReversal(SignalStrategy):
    params = dict(mfi_len=2, mfi_entry=10)
    GRID = dict(mfi_len=[2, 3, 5], mfi_entry=[5, 10, 20])
    TF, SESSIONS = 1440, ("rth", "full")

    def signals(self, df):
        p = self.p
        m = ind.money_flow_index(df, p["mfi_len"])       # unchanged when later futures rolls are appended
        df["mfi"] = m
        return {"long_entry": m < p["mfi_entry"], "long_exit": df.c > df.h.shift()}


STRATEGY = MfiReversal
