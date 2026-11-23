"""Tests for the two-leg (pairs) engine."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import Settings, Strategy, data  # noqa: E402
from engine.instruments import Instrument  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from engine.pairs import PairsEngine, check_lookahead_pairs  # noqa: E402

A = Instrument("A", point_value=10.0, tick=0.1, commission=1.0, slippage_ticks=1, qty_step=1)       # like MGC
B = Instrument("B", point_value=100.0, tick=0.01, commission=0.0, slippage_ticks=0, qty_step=0.01, uses_bid_ask=True)


def pair_frame(a_close, b_mid, half_spread=0.1, contracts=None):
    n = len(a_close)
    t0 = int(pd.Timestamp("2024-01-08 14:30", tz="UTC").timestamp())
    df = pd.DataFrame({"ts": t0 + 3600 * np.arange(n)})
    for k in "ohlc":
        df[k] = np.asarray(a_close, float)
        df["x" + k] = np.asarray(b_mid, float)
        df["xb" + k] = df["x" + k] - half_spread
        df["xa" + k] = df["x" + k] + half_spread
    df["raw_o"] = df.o
    df["v"] = 1
    df["contract"] = contracts or ["A1"] * n
    df["roll"] = (df.contract != df.contract.shift()).to_numpy(); df.loc[0, "roll"] = False
    return data._add_time_columns(df)


class Script(Strategy):
    def __init__(self, plan, notional=100_000.0):
        super().__init__(notional=notional); self.plan = plan

    def on_bar(self, i):
        for act in self.plan.get(i, []):
            getattr(self.broker, act[0])(*act[1:])


def test_long_spread_pnl_by_leg():
    a = [2000, 2000, 2010, 2010]           # A rises 10
    b = [1990, 1990, 1995, 1995]           # B rises 5
    df = pair_frame(a, b)
    r = PairsEngine(df, A, B, Script({0: [("open", 1, 1.0)], 1: [("close",)]}, notional=40_000), Settings()).run()
    t = r["trades"].iloc[0]
    # entry bar 1 open: A 2000 + 0.1 slip; qty A = floor(40000 / (2000 x 10)) = 2; B qty = 1.0 x 2 x 10 / 100 = 0.2 lots
    assert t.qty == 2 and t.qty_b == pytest.approx(0.2)
    assert t.entry_px == pytest.approx(2000.1) and t.entry_px_b == pytest.approx(1989.9)        # sell B at the bid
    # exit bar 2 open: A 2010 - 0.1; buy B back at the ask 1995.1
    assert t.pnl_a == pytest.approx((2009.9 - 2000.1) * 2 * 10)
    assert t.pnl_b == pytest.approx((1989.9 - 1995.1) * 0.2 * 100)
    assert t.costs == pytest.approx(2 * 1.0 * 2)
    assert t.pnl == pytest.approx(t.pnl_a + t.pnl_b - t.costs)


def test_pair_roll_is_charged_once_while_held():
    df = pair_frame([2000] * 6, [1990] * 6, contracts=["A1"] * 3 + ["A2"] * 3)
    t = PairsEngine(df, A, B, Script({0: [("open", -1, 1.0)]}, notional=40_000), Settings()).run()["trades"].iloc[0]
    assert t.rolls == 1


def test_gold_pairs_strategy_has_no_lookahead():
    cls = load_strategy(str(ROOT / "strategies/photos/b01_pairs_gold_futures_vs_spot.py"))
    rng = np.random.default_rng(4)
    b = 2000 + np.cumsum(rng.normal(0, 2, 1500))
    basis = np.zeros(1500)
    for k in range(1, 1500):
        basis[k] = 0.95 * basis[k - 1] + rng.normal(0, 1.5)          # mean-reverting gap
    df = pair_frame(b + 10 + basis, b)
    assert check_lookahead_pairs(lambda: cls(window=200), df, A, B, Settings()) == []
    t = PairsEngine(df, A, B, cls(window=200, notional=40_000), Settings()).run()["trades"]
    assert len(t) > 5
