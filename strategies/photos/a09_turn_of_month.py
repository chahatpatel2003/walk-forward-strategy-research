"""A9 - Turn of the month (photo IMG_2714 #6, QuantifiedStrategies): buy 5 trading days before month-end,
sell 3 trading days into the next month.
Signal on the close of the day with `entry_days_before` trading days left in the month -> buy the next open;
exit signal on the close of the `exit_day`-th trading day of the new month -> sell the next open.
Trading days come from the exchange calendar (known in advance, so not look-ahead).
"""
from engine.calendar import period_position
from engine.strategy_kit import SignalStrategy


class TurnOfMonth(SignalStrategy):
    params = dict(entry_days_before=5, exit_day=3)
    GRID = dict(entry_days_before=[3, 5, 7], exit_day=[1, 3, 5])
    TF, SESSIONS = 1440, ("rth", "full")

    def signals(self, df):
        p = self.p
        pos = period_position(df.tday.to_numpy(), "M")
        left, n = pos.left.to_numpy(), pos.n_in_period.to_numpy()
        import pandas as pd
        return {"long_entry": pd.Series(left == p["entry_days_before"], index=df.index),
                "long_exit": pd.Series((n == p["exit_day"]) & (left > p["entry_days_before"]), index=df.index)}


STRATEGY = TurnOfMonth
