"""Regression tests for findings.md, section "Verification after the fifth revision"."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings, Strategy, data, metrics  # noqa: E402
from engine.instruments import Instrument  # noqa: E402
from test_engine import FREE, Script, bars  # noqa: E402

ONE = Instrument("ONE", point_value=1.0, tick=0.25, commission=0.0, slippage_ticks=0, qty_step=1)


# 1 ---------------------------------------------------------------------------------------------------
def blowup_frame():
    # long 100 units ($10/pt) from 100; price falls to 0 -> loss of $100,000 on a $50,000 account; then recovers
    px = [100, 100, 40, 0.5, 50, 60, 70]
    return bars([(p, p, p, p) for p in px])


class BuyAgain(Strategy):
    """Buys at the start and again whenever flat."""
    def on_bar(self, i):
        if self.broker.flat and not self.broker.orders:
            self.broker.buy(qty=100)


def test_capital_breach_is_reported_in_unconstrained_runs():
    r = Engine(blowup_frame(), FREE, BuyAgain(), Settings(capital=50_000)).run()
    s = metrics.summarize(r)
    assert s["account_model"] == "unconstrained"
    assert s["capital_exhausted_on"] is not None


def test_constrained_account_liquidates_and_stops_trading():
    r = Engine(blowup_frame(), FREE, BuyAgain(), Settings(capital=50_000, account_constrained=True)).run()
    t = r["trades"]
    assert len(t) == 1 and t.iloc[0].exit_reason == "capital_exhausted"     # no new trade after the breach
    s = metrics.summarize(r)
    assert s["account_model"] == "constrained" and s["capital_exhausted_on"] is not None
    assert r["notes"]["orders_refused_capital_exhausted"] > 0


# 2 ---------------------------------------------------------------------------------------------------
def test_report_drawdown_counts_come_from_the_rows():
    sys.path.insert(0, str(ROOT / "tools"))
    import photo_report_tables as prt
    rows = pd.DataFrame({"wf_oos_max_dd": [-10.0, -50.0, np.nan], "buy_hold_oos_max_dd": [-20.0, -40.0, -30.0],
                         "wf_oos_net": [1.0, 2.0, np.nan], "buy_hold_oos_net": [5.0, 1.0, 3.0]})
    c = prt.comparison_counts(rows)
    assert c == {"both": 2, "smaller_dd": 1, "larger_dd": 1, "less_profit": 1, "more_profit": 1}


# 3 ---------------------------------------------------------------------------------------------------
def test_r_multiple_includes_a_roll_charged_inside_the_exit_bar():
    df = bars([(100.0, 100, 100, 100), (100.0, 100, 100, 100), (100.0, 100, 98, 99), (99.0, 99, 99, 99)])
    df["roll_inside"] = [False, False, True, False]
    inst = Instrument("R", point_value=1.0, tick=1.0, commission=1.0, slippage_ticks=0, qty_step=1)
    t = Engine(df, inst, Script({0: [("buy", dict(qty=1, sl=99))]}), Settings()).run()["trades"].iloc[0]
    # stop at 99: -1 gross, -2 commission, roll charged in the exit bar -2 -> -5; initial risk $1 -> -5R
    assert t.rolls == 1 and t.pnl == pytest.approx(-5.0) and t.r == pytest.approx(-5.0)
