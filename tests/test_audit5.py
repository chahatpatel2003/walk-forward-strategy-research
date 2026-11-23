"""Regression tests for the photo-study recheck (findings.md, section "Photo-study recheck")."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings, Strategy, data  # noqa: E402
from engine.instruments import Instrument  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from test_engine import FREE, Script, bars  # noqa: E402

ONE = Instrument("ONE", point_value=1.0, tick=0.25, commission=0.0, slippage_ticks=0, qty_step=1)


def mixed_contract_minutes():
    """Ten 1-minute bars: contract A (raw 100, adjustment +20) for 3 minutes, then contract B (adjustment 0).
    Adjusted prices are continuous at 120."""
    rows = [(120.0, 120.0, 120.0, 120.0)] * 10
    df = bars(rows, contracts=["A"] * 3 + ["B"] * 7)
    df["adj"] = [20.0] * 3 + [0.0] * 7
    for k in "ohlc":
        df["raw_" + k] = df[k] - df["adj"]
    return df


# 1 ---------------------------------------------------------------------------------------------------
def test_opening_fill_is_sized_with_the_opening_contracts_adjustment():
    df5 = data.resample(mixed_contract_minutes(), 5)
    assert df5.roll_inside.iloc[0]
    # decide at bar 0's close -> fill at bar 1's open (contract B, adj 0, raw 120): 1000 / 120 = 8
    # the test that matters: an order filled at the open of the MIXED bar (bar 0) must use contract A's adjustment
    df = pd.concat([data.resample(bars([(120.0, 120, 120, 120)] * 5, contracts=["A"] * 5), 5).assign(adj=20.0, adj_open=20.0),
                    df5], ignore_index=True)
    df["tday"] = df.tday.iloc[0]
    t = Engine(df, ONE, Script({0: [("buy", dict(notional_usd=1000))]}), Settings()).run()["trades"].iloc[0]
    assert t.qty == 10                     # raw open of contract A = 120 - 20 = 100 -> 1000 / 100


def test_benchmark_sizes_with_the_opening_adjustment():
    import photo_study as ps
    df5 = data.resample(mixed_contract_minutes(), 5)
    b = ps.benchmark(df5, ONE, [(str(df5.tday.iloc[0])[:10], str(df5.tday.iloc[-1])[:10])], capital=1000)
    assert b["qty"] == 10


# 2 ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("edit", ["change", "drop", "create_roll_inside", "change_adj", "create_adj_open"])
def test_strategy_cannot_edit_execution_metadata(edit):
    df = bars([(100.0, 100, 100, 100)] * 4)
    df["adj"] = 0.0
    if edit in ("change", "drop"):
        df["roll_inside"] = [False, False, True, False]

    class Tamper(Strategy):
        def prepare(self, d):
            if edit == "change":
                d["roll_inside"] = False
            elif edit == "drop":
                d = d.drop(columns=["roll_inside"])
            elif edit == "create_roll_inside":
                d["roll_inside"] = True
            elif edit == "change_adj":
                d["adj"] = 50.0
            elif edit == "create_adj_open":
                d["adj_open"] = 50.0
            return d

        def on_bar(self, i):
            pass
    with pytest.raises(ValueError, match="prepare"):
        Engine(df, FREE, Tamper(), Settings())


# 3 ---------------------------------------------------------------------------------------------------
def test_cash_session_folds_use_eligible_days_only():
    import robust
    # minute data for 2024-06-28 .. 2024-07-05 (Jul 4 is a holiday; it is the full session's last-but-one day)
    days = pd.bdate_range("2024-06-03", "2024-07-04")
    ts = np.concatenate([((d + pd.Timedelta(hours=10)).tz_localize("America/New_York") - pd.Timestamp(0, tz="UTC"))
                         // pd.Timedelta(seconds=1) + 60 * np.arange(5) for d in days])
    df = pd.DataFrame({"ts": ts, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1, "contract": "X", "roll": False})
    df = data._add_time_columns(df)
    full = robust.fold_days(df, 1440, "full")
    rth = robust.fold_days(df, 1440, "rth")
    assert np.datetime64("2024-07-04") in full and np.datetime64("2024-07-04") not in rth
    assert rth[-1] == np.datetime64("2024-07-03")


# 4 ---------------------------------------------------------------------------------------------------
def test_benchmark_holds_through_consecutive_folds_and_closes_at_gaps():
    import photo_study as ps
    t0 = int(pd.Timestamp("2024-01-08 14:30", tz="UTC").timestamp())
    px = [100.0, 110, 120, 130, 140, 150]
    df = pd.DataFrame({"ts": t0 + 86400 * np.arange(6), "o": px, "h": px, "l": px, "c": px, "v": 1,
                       "contract": "X", "roll": False})
    df = data._add_time_columns(df)
    d = [str(x)[:10] for x in df.tday]
    inst = FREE.with_costs(commission=5.0)
    cont = ps.benchmark(df, inst, [(d[0], d[1]), (d[2], d[3])], capital=1000)       # back-to-back folds
    assert cont["positions"] == 1 and cont["net"] == pytest.approx((130 - 100) * 1 * 10 - 2 * 5)
    gap = ps.benchmark(df, inst, [(d[0], d[1]), (d[3], d[4])], capital=1000)        # day 3 is not scored
    assert gap["positions"] == 2


# 5 ---------------------------------------------------------------------------------------------------
def a13_frame(cutoff_minute=None):
    rng = np.random.default_rng(3)
    days = pd.bdate_range("2024-03-04", periods=3)
    ts = []
    for k, d in enumerate(days):
        n = 390 if (cutoff_minute is None or k != 0) else cutoff_minute
        ts.append(((d + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York") - pd.Timestamp(0, tz="UTC"))
                  // pd.Timedelta(seconds=1) + 60 * np.arange(n))
    ts = np.concatenate(ts)
    c = 100 + np.cumsum(rng.normal(0, 0.5, len(ts)))
    df = pd.DataFrame({"ts": ts, "o": c, "h": c + 0.25, "l": c - 0.25, "c": c, "v": 10, "contract": "X", "roll": False,
                       "buy_vol": rng.integers(0, 50, len(ts)), "sell_vol": rng.integers(0, 50, len(ts))})
    return data._add_time_columns(df)


def test_intraday_position_is_closed_at_the_next_session_open_and_flagged():
    df = a13_frame()
    df = df[~((df.tday == df.tday.iloc[0]) & (df.ny_min > 15 * 60 + 48))].reset_index(drop=True)   # day 1 data stops at 15:48

    class EnterLate(Strategy):
        def on_bar(self, i):
            if self.d["tday"][i] == self.d["tday"][0] and self.d["ny_min"][i] == 15 * 60 + 47 and self.broker.flat:
                self.broker.buy(qty=1, intraday=True)
    t = Engine(df, FREE, EnterLate(), Settings()).run()["trades"].iloc[0]
    assert t.exit_reason == "session_gap_exit"                         # flagged: no closing data that session
    assert pd.Timestamp(t.exit_time).tz_convert("America/New_York").strftime("%H:%M") == "09:30"


def test_intraday_pending_order_expires_at_the_session_boundary():
    df = a13_frame()

    class EnterAtLastBar(Strategy):
        def on_bar(self, i):
            if self.d["tday"][i] == self.d["tday"][0] and self.d["ny_min"][i] == 15 * 60 + 59:
                self.broker.buy(qty=1, intraday=True)
    r = Engine(df, FREE, EnterAtLastBar(), Settings()).run()
    assert len(r["trades"]) == 0 and r["notes"].get("intraday_orders_expired") == 1


def test_a13_with_early_data_cutoff_never_crosses_unflagged():
    cls = load_strategy(str(ROOT / "strategies/photos/a13_order_flow_imbalance.py"))
    df = a13_frame(cutoff_minute=300)                      # day 1 data stops at 14:29
    t = Engine(df, FREE, cls(window=60, threshold_ticks=0.1), Settings()).run()["trades"]
    crossing = t[t.entry_tday != t.exit_tday]
    assert len(t) > 0 and (crossing.exit_reason == "session_gap_exit").all()
