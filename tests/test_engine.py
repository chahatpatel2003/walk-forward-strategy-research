"""Hand-checked scenarios for the engine. Run:  ~/.venvs/t9-backtesting/bin/python -m pytest tests -q"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from engine import Engine, Settings, Strategy, check_lookahead, data  # noqa: E402
from engine.instruments import Instrument  # noqa: E402

FUT = Instrument("TEST", point_value=10.0, tick=0.25, commission=2.0, slippage_ticks=1, qty_step=1)
FREE = Instrument("FREE", point_value=10.0, tick=0.25, commission=0.0, slippage_ticks=0, qty_step=1)
CFD = Instrument("CFD", point_value=100.0, tick=0.01, commission=0.0, slippage_ticks=0, qty_step=0.01, uses_bid_ask=True)


def bars(rows, contracts=None, bidask=None):
    """rows: list of (o, h, l, c). One bar per minute starting Mon 2024-01-08 14:30 UTC (09:30 ET)."""
    t0 = int(pd.Timestamp("2024-01-08 14:30", tz="UTC").timestamp())
    df = pd.DataFrame(rows, columns=["o", "h", "l", "c"], dtype=float)
    df["ts"] = t0 + 60 * np.arange(len(df))
    df["v"] = 1
    df["contract"] = contracts or ["A"] * len(df)
    df["roll"] = (df.contract != df.contract.shift()).values
    df.loc[0, "roll"] = False
    if bidask:
        for k, (b, a) in bidask.items():
            df["b" + k], df["a" + k] = b, a
    return data._add_time_columns(df)


class Script(Strategy):
    """Places the orders given in self.plan = {bar_index: [(method, kwargs), ...]}."""
    def __init__(self, plan):
        super().__init__(); self.plan = plan

    def on_bar(self, i):
        for meth, kw in self.plan.get(i, []):
            getattr(self.broker, meth)(**kw)


def run(df, inst, plan, **settings):
    return Engine(df, inst, Script(plan), Settings(**settings)).run()


def test_market_order_fills_next_open_with_costs_and_hits_target():
    df = bars([(100, 101, 99, 100), (100.5, 101, 100, 100.5), (100.5, 105, 100.25, 104), (104, 104, 104, 104)])
    r = run(df, FUT, {0: [("buy", dict(qty=2, sl=98, tp=103))]})
    t = r["trades"].iloc[0]
    assert t.entry_px == 100.75                      # bar 1 open 100.5 + 1 tick slippage; never bar 0
    assert t.exit_reason == "tp" and t.exit_px == 103
    assert t.pnl_gross == pytest.approx((103 - 100.75) * 10 * 2)
    assert t.costs == pytest.approx(2.0 * 2 * 2)     # $2/side x 2 sides x 2 contracts
    assert t.pnl == pytest.approx(45 - 8)
    assert r["equity"].equity.iloc[-1] == pytest.approx(50_000 + 37)


def test_both_stop_and_target_in_one_bar_assumes_stop_first():
    df = bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 106, 94, 100)])
    t = run(df, FREE, {0: [("buy", dict(qty=1, sl=95, tp=105))]})["trades"].iloc[0]
    assert t.exit_reason == "sl" and t.exit_px == 95


def test_gap_through_stop_fills_at_open():
    df = bars([(100, 100, 100, 100), (100, 100, 100, 100), (90, 91, 89, 90)])
    t = run(df, FUT, {0: [("buy", dict(qty=1, sl=95))]})["trades"].iloc[0]
    assert t.exit_reason == "sl_gap" and t.exit_px == 90 - 0.25


def test_stop_entry_and_stop_loss_in_same_bar_counts_as_loss():
    df = bars([(100, 100, 100, 100), (100, 103, 97, 100), (100, 100, 100, 100)])
    t = run(df, FREE, {0: [("buy", dict(kind="stop", price=102, qty=1, sl=98, tp=110))]})["trades"].iloc[0]
    assert t.entry_px == 102 and t.exit_reason == "sl" and t.exit_px == 98


def test_stop_entry_gapping_past_price_fills_at_open():
    df = bars([(100, 100, 100, 100), (104, 105, 104, 105), (105, 105, 105, 105)])
    t = run(df, FREE, {0: [("buy", dict(kind="stop", price=102, qty=1))]})["trades"].iloc[0]
    assert t.entry_px == 104


def test_limit_must_trade_through_by_one_tick_for_futures():
    df = bars([(100, 100, 100, 100), (100, 100, 99, 99.5), (100, 100, 98.75, 99), (99, 99, 99, 99)])
    t = run(df, FREE, {0: [("buy", dict(kind="limit", price=99, qty=1))]})["trades"].iloc[0]
    assert t.entry_time == pd.Timestamp(df.ts[2], unit="s", tz="UTC") and t.entry_px == 99   # bar 1 only touched 99


def test_bid_ask_long_buys_ask_sells_bid_and_stop_uses_bid():
    rows = [(100, 100, 100, 100)] * 3
    ba = {"o": ([99.9, 99.9, 99.4], [100.1, 100.1, 99.6]), "h": ([99.9, 99.9, 99.5], [100.1, 100.1, 99.7]),
          "l": ([99.9, 99.9, 99.3], [100.1, 100.1, 99.5]), "c": ([99.9, 99.9, 99.4], [100.1, 100.1, 99.6])}
    df = bars(rows, bidask=ba)
    t = run(df, CFD, {0: [("buy", dict(qty=1, sl=99.5))]})["trades"].iloc[0]
    assert t.entry_px == 100.1                       # paid the ask
    assert t.exit_reason == "sl_gap" and t.exit_px == 99.4   # bid opened below the stop


def test_risk_sizing_rounds_down():
    df = bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 100)])
    t = run(df, FREE, {0: [("buy", dict(risk_usd=500, sl_dist=12))]})["trades"].iloc[0]
    assert t.qty == 4                                # 500 / (12 pts x $10) = 4.17 -> 4


def test_tp_r_multiple():
    df = bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 109, 100, 108)])
    t = run(df, FREE, {0: [("buy", dict(qty=1, sl_dist=4, tp_r=2))]})["trades"].iloc[0]
    assert t.tp == 108 and t.exit_reason == "tp" and t.r == pytest.approx(2.0)


def test_oco_cancels_other_side():
    df = bars([(100, 100, 100, 100), (100, 103, 100, 103), (103, 103, 96, 97), (97, 97, 97, 97)])
    plan = {0: [("buy", dict(kind="stop", price=102, qty=1)), ("sell", dict(kind="stop", price=98, qty=1))]}
    r = run(df, FREE, plan)
    assert len(r["trades"]) == 1 and r["trades"].iloc[0].side == "long"


def test_close_exits_at_next_open_and_reversal():
    df = bars([(100, 100, 100, 100), (101, 101, 101, 101), (102, 102, 102, 102), (103, 103, 103, 103)])
    plan = {0: [("buy", dict(qty=1))], 1: [("close", dict()), ("sell", dict(qty=1))]}
    t = run(df, FREE, plan)["trades"]
    assert list(t.side) == ["long", "short"]
    assert t.iloc[0].entry_px == 101 and t.iloc[0].exit_px == 102 and t.iloc[1].entry_px == 102
    assert t.iloc[1].exit_reason == "end_of_data"


def test_roll_charges_cost_and_back_adjusted_pnl_is_true_pnl():
    # contract A trades 100->102, rolls to B (+10 pts dearer) which goes 112->113. Real P&L of a rolled long = 2 + 1 = 3 pts.
    raw = [(100, 100, 100, 100), (100, 100, 100, 100), (102, 102, 102, 102), (112, 112, 112, 112), (113, 113, 113, 113)]
    df = bars(raw, contracts=["A", "A", "A", "B", "B"])
    df = data._back_adjust(df, np.array([10.0]), np.array([3]))
    r = run(df, FREE.with_costs(commission=1.0), {0: [("buy", dict(qty=1))]})
    t = r["trades"].iloc[0]
    assert t.pnl_gross == pytest.approx(3 * 10)
    assert t.rolls == 1 and t.costs == pytest.approx(1 * 2 + 2)   # entry+exit, plus 2 sides at the roll


def test_order_placed_on_last_bar_never_fills_and_open_position_closes_at_end():
    df = bars([(100, 100, 100, 100), (101, 101, 101, 101)])
    r = run(df, FREE, {1: [("buy", dict(qty=1))]})
    assert len(r["trades"]) == 0


def test_lookahead_checker():
    df = bars([(i, i + 1, i - 1, i) for i in range(100, 400)])

    class Good(Strategy):
        def prepare(self, d): d["x"] = d.c.rolling(10).mean(); return d

    class Bad(Strategy):
        def prepare(self, d): d["x"] = d.c.rolling(10, center=True).mean(); d["y"] = d.c.shift(-1); return d

    assert check_lookahead(Good(), df) == []
    bad = check_lookahead(Bad(), df)
    assert len(bad) == 2 and "'x'" in bad[0] and "'y'" in bad[1]


def test_resample_ohlc():
    df = bars([(1, 2, 0.5, 1.5), (1.5, 3, 1, 2), (2, 2.5, 0.25, 1), (1, 1, 1, 1), (1, 4, 1, 3), (3, 3, 2, 2)])
    r = data.resample(df, 5)
    assert len(r) == 2
    assert tuple(r.iloc[0][["o", "h", "l", "c"]]) == (1, 4, 0.25, 3) and r.iloc[0].v == 5
    assert r.iloc[1].ny_min == 9 * 60 + 35
