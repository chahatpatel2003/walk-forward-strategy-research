"""Optional hard ATR stop on signal strategies (strategy_kit.SignalStrategy: stop_atr, atr_period)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings  # noqa: E402
from engine.core import check_lookahead  # noqa: E402
from engine.strategy_kit import SignalStrategy  # noqa: E402
from test_engine import FREE, bars  # noqa: E402


class BuyAt20(SignalStrategy):
    params = dict(hold=10)

    def signals(self, df):
        k = np.arange(len(df))                                   # works on any prefix of the data
        e = pd.Series(k == 20, index=df.index)
        x = pd.Series(k == 20 + self.p["hold"], index=df.index)
        return {"long_entry": e, "long_exit": x}


def frame(drop_at=None):
    rows = [(100.0, 101.0, 99.0, 100.0)] * 40                     # true range 2 on every bar -> ATR 2
    if drop_at is not None:
        rows[drop_at] = (100.0, 100.5, 90.0, 92.0)
    return bars(rows)


def test_without_stop_atr_nothing_changes():
    t = Engine(frame(25), FREE, BuyAt20(qty=1), Settings()).run()["trades"]
    assert len(t) == 1 and t.exit_reason.iloc[0] == "signal" and pd.isna(t.sl.iloc[0])


def test_stop_is_k_times_atr_from_the_fill_and_exits_inside_the_bar():
    t = Engine(frame(25), FREE, BuyAt20(qty=1, stop_atr=2.0, atr_period=14), Settings()).run()["trades"].iloc[0]
    assert t.sl == 100.0 - 2.0 * 2.0                              # fill 100 (bar 21 open), ATR 2
    assert t.exit_reason == "sl" and t.exit_px == 96.0


def test_atr_stop_passes_the_lookahead_check():
    assert check_lookahead(lambda: BuyAt20(qty=1, stop_atr=2.0), frame(25), FREE) == []


def test_warmup_covers_the_atr_when_the_stop_is_on():
    assert BuyAt20(stop_atr=2.0, atr_period=14).warmup_bars() >= 3 * 14
    assert BuyAt20().warmup_bars() == 0
