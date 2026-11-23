"""Intraday mode: `flat_at` closes every position before the New York cash close; nothing is held overnight."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings  # noqa: E402
from engine.core import check_lookahead  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from engine.strategy_kit import SignalStrategy  # noqa: E402
from test_audit9 import frame_at  # noqa: E402
from test_engine import FREE  # noqa: E402

ET = "America/New_York"
FLAT = 15 * 60 + 55


def day_bars(day, tf, px=100.0):
    t = pd.date_range(f"{day} 09:30", f"{day} 15:59", freq=f"{tf}min")
    df = frame_at([str(x) for x in t], [px] * len(t))
    df.attrs["bar_minutes"] = tf
    return df


def two_days(tf):
    a, b = day_bars("2024-01-08", tf), day_bars("2024-01-09", tf)
    df = pd.concat([a, b], ignore_index=True)
    df.attrs["bar_minutes"] = tf
    return df


class BuyFirst(SignalStrategy):
    def signals(self, df):
        k = np.arange(len(df))
        return {"long_entry": pd.Series(k == 1, index=df.index)}          # never an exit signal


def hm(ts):
    return pd.Timestamp(ts).tz_convert(ET).strftime("%H:%M")


def test_without_flat_at_the_position_is_held_overnight():
    t = Engine(two_days(5), FREE, BuyFirst(qty=1), Settings()).run()["trades"].iloc[0]
    assert t.exit_reason == "end_of_data"


def test_flat_at_closes_at_1555_on_5_minute_bars():
    t = Engine(two_days(5), FREE, BuyFirst(qty=1, flat_at=FLAT), Settings()).run()["trades"].iloc[0]
    assert t.exit_reason == "eod" and hm(t.exit_time) == "15:55" and str(t.exit_tday)[:10] == "2024-01-08"


def test_flat_at_closes_at_the_last_bar_open_on_15_minute_bars():
    t = Engine(two_days(15), FREE, BuyFirst(qty=1, flat_at=FLAT), Settings()).run()["trades"].iloc[0]
    assert t.exit_reason == "eod" and hm(t.exit_time) == "15:45"


def test_flat_at_on_one_minute_bars_and_no_entry_at_the_close():
    df = two_days(1)

    class BuyLate(SignalStrategy):
        def signals(self, df):
            m = df.ny_min.to_numpy()
            return {"long_entry": pd.Series(m == 15 * 60 + 54, index=df.index)}
    t = Engine(df, FREE, BuyFirst(qty=1, flat_at=FLAT), Settings()).run()["trades"].iloc[0]
    assert hm(t.exit_time) == "15:55"
    assert len(Engine(df, FREE, BuyLate(qty=1, flat_at=FLAT), Settings()).run()["trades"]) == 0


def test_early_close_day_flattens_before_1300():
    df = day_bars("2024-11-29", 5)                                          # day after Thanksgiving: 13:00 close
    t = Engine(df, FREE, BuyFirst(qty=1, flat_at=FLAT), Settings()).run()["trades"].iloc[0]
    assert hm(t.exit_time) == "12:55"


def test_squeeze_breakout_also_goes_flat():
    a12 = load_strategy(str(ROOT / "strategies/photos/a12_volatility_squeeze_breakout.py"))
    assert "flat_at" in a12.params


def test_flat_rule_passes_the_lookahead_check():
    assert check_lookahead(lambda: BuyFirst(qty=1, flat_at=FLAT), two_days(5), FREE) == []
