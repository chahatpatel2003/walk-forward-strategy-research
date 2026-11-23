"""Regression tests for findings.md, section "Verification after the ninth revision" (open issues R1, E1, E5, E2,
C1, R2, R3, the timeframe cost and portfolio reports, and repeated look-ahead work)."""
import json
import sys
from argparse import Namespace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings, Strategy, data, metrics, stress, walkforward  # noqa: E402
from engine.calendar import trading_days  # noqa: E402
from engine.core import check_lookahead  # noqa: E402
from engine.instruments import Instrument  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from test_audit9 import frame_at  # noqa: E402
from test_engine import FREE, bars  # noqa: E402

ET = "America/New_York"


# R1: a breach in any single stress scenario counts as hitting $0 ----------------------------------------
def test_an_individual_stress_breach_means_the_run_did_not_survive():
    import photo_report_tables as prt
    row = dict(wf_oos_net=15_000.0, wf_oos_pf=1.5, mc_prob_loss_pct=1.0, stress_all_net=5_000.0, stress_worst_net=1_000.0,
               checks_passed=12, checks_total=13, capital_exhausted_on=np.nan, wf_capital_exhausted_on=np.nan,
               stress_all_capital_exhausted_on=np.nan, stress_scenarios_breached=0)
    r = pd.DataFrame([row, {**row, "stress_scenarios_breached": 1}])   # breached, then recovered to a profit
    assert list(prt.survived(r)) == [True, False]
    assert list(prt.robust_mask(r)) == [True, False]


# E5: an opening fill whose costs take the account to $0 is a breach ------------------------------------
COSTLY = Instrument("COSTLY", point_value=10.0, tick=0.25, commission=600.0, slippage_ticks=0, qty_step=1)


class BuyFirstBar(Strategy):
    def on_bar(self, i):
        if i == 0:
            self.broker.buy(qty=1)


def test_entry_costs_that_exhaust_the_account_are_a_breach():
    df = bars([(100.0, 100, 100, 100), (100.0, 220, 100, 220), (220.0, 220, 220, 220), (220.0, 220, 220, 220)])
    r = Engine(df, COSTLY, BuyFirstBar(), Settings(capital=500)).run()   # -100 after the fill, +1,100 at the close
    assert r["notes"].get("capital_exhausted_at") == "entry"
    assert metrics.summarize(r)["capital_exhausted_on"] is not None
    t = Engine(df, COSTLY, BuyFirstBar(), Settings(capital=500, account_constrained=True)).run()["trades"].iloc[0]
    assert t.exit_reason == "capital_exhausted" and t.exit_time == pd.Timestamp(int(df.ts[2]), unit="s", tz="UTC")


def test_pair_entry_costs_that_exhaust_the_account_are_a_breach():
    from engine.pairs import PairsEngine
    from test_pairs import A, B, pair_frame
    df = pair_frame([2000, 2000, 2100, 2100], [2000] * 4)
    df.loc[1, ["h", "c"]] = 2100.0                          # fills at 2,000; closes (and stays) well above it

    class Open(Strategy):
        params = dict(notional=100_000.0)

        def on_bar(self, i):
            if i == 0:
                self.broker.open(+1, 1.0)
    r = PairsEngine(df, A, B, Open(), Settings(capital=8.0)).run()
    assert r["notes"].get("capital_exhausted_at") == "entry"
    r = PairsEngine(df, A, B, Open(), Settings(capital=8.0, account_constrained=True)).run()
    assert r["trades"].iloc[0].exit_reason == "capital_exhausted"


# E1: a sparse future read in prepare() is caught at the strategy's own decision bars --------------------
class SparsePeek(Strategy):
    """Signals only at row 60, using row 61's close."""
    def prepare(self, df):
        trig = np.zeros(len(df), dtype=bool)
        if len(df) > 61:
            trig[60] = df.c.iloc[61] > df.c.iloc[60]
        df["trig"] = trig
        return df

    def on_bar(self, i):
        if self.d["trig"][i] and self.broker.flat:
            self.broker.buy(qty=1)


def test_lookahead_check_catches_a_sparse_future_read_at_a_decision_bar():
    df = bars([(100.0 + k, 101.0 + k, 99.0 + k, 100.5 + k) for k in range(200)])
    problems = check_lookahead(SparsePeek, df, FREE)
    assert problems and any("trig" in p for p in problems)


# E2: the ORB entry deadline is absolute; bar size is declared, not guessed ------------------------------
def test_orb_order_cannot_fill_after_the_deadline_when_the_last_minute_is_missing():
    times = ["2024-01-08 09:30", "2024-01-08 09:31", "2024-01-08 09:32"] + \
            [str(pd.Timestamp("2024-01-08 11:31") + pd.Timedelta(minutes=k)) for k in range(30)]
    px = [(100.0, 101.0, 99.0, 100.0), 100.0, 100.0, (100.0, 102.0, 100.0, 101.5)] + [101.5] * 29
    orb = load_strategy(str(ROOT / "strategies/orb.py"))
    t = Engine(frame_at(times, px), FREE, orb(or_minutes=3), Settings()).run()["trades"]
    assert len(t) == 0


def test_orb_order_cannot_fill_in_a_coarse_bar_that_ends_after_the_deadline():
    times = ["2024-01-08 09:30", "2024-01-08 10:00", "2024-01-08 10:30", "2024-01-08 11:30", "2024-01-08 12:00"]
    px = [(100.0, 101.0, 99.0, 100.0), 100.0, 100.0, (100.0, 102.0, 100.0, 101.5), 101.5]   # no 11:00 bar
    df = frame_at(times, px)
    df.attrs["bar_minutes"] = 30
    orb = load_strategy(str(ROOT / "strategies/orb.py"))
    t = Engine(df, FREE, orb(or_minutes=30), Settings()).run()["trades"]
    assert len(t) == 0


def test_resampled_bars_declare_their_size_and_orb_uses_it():
    times = [str(pd.Timestamp("2024-01-08 09:30") + pd.Timedelta(minutes=k)) for k in range(120)]
    one = frame_at(times, [100.0] * 120)
    five = data.resample(one, 5, "full")
    assert five.attrs.get("bar_minutes") == 5
    sparse = five.iloc[::2].reset_index(drop=True)          # every other 5-minute bar: the steps say 10 minutes
    orb = load_strategy(str(ROOT / "strategies/orb.py"))()
    orb.prepare(sparse.copy())
    assert orb.tf == 5


# C1: a scheduled window with no data at all still separates the daily history --------------------------
def test_folds_keep_their_scheduled_period():
    days = pd.bdate_range("2016-01-04", "2016-02-29").append(pd.bdate_range("2016-04-01", "2016-04-29"))
    f = walkforward.make_folds(days, 1, 1, anchored=True)
    assert [x["oos_start"][:7] for x in f] == ["2016-02", "2016-04"]
    assert [x["period"] for x in f] == [0, 2]


@pytest.mark.parametrize("with_period", [True, False])
def test_daily_replay_does_not_bridge_an_absent_window(tmp_path, with_period):
    import robust
    dates = pd.Series(pd.to_datetime(["2016-02-25", "2016-02-26", "2016-04-01", "2016-04-04"]))
    f = pd.DataFrame({"fold": [1, 2], "oos_start": ["2016-02-01", "2016-04-01"], "oos_end": ["2016-02-26", "2016-04-04"],
                      "oos_net_pnl": [1.0, 2.0]})
    if with_period:
        f["period"] = [0, 2]
    f.to_csv(tmp_path / "walkforward_folds.csv", index=False)
    assert robust.daily_segments(dates, tmp_path / "walkforward_folds.csv") == [2, 2]


# R2: a "complete month" covers every exchange trading day of that month ---------------------------------
def daily(days, v=1.0):
    return pd.Series(v, index=pd.DatetimeIndex(days))


def test_a_month_ending_on_the_26th_is_not_complete():
    d = trading_days("2024-01-01", "2024-01-26").append(trading_days("2024-02-01", "2024-02-29"))
    m = stress.complete_months(daily(d))
    assert [str(x)[:7] for x in m.index] == ["2024-01", "2024-02"]
    assert pd.isna(m.iloc[0]) and m.iloc[1] == len(trading_days("2024-02-01", "2024-02-29"))


def test_rolling_windows_do_not_bridge_an_absent_month():
    d = trading_days("2024-01-01", "2024-01-31").append(trading_days("2024-03-01", "2024-04-30"))
    t = stress._stretches(daily(d, -1.0)).set_index("window")
    assert pd.isna(t.loc["worst rolling 3 months", "net_pnl"])
    assert "3 of 3 complete months" in t.loc["losing months", "when"]


# R3: walk-forward efficiency is withheld when its inputs are not credible -------------------------------
def test_efficiency_is_unavailable_with_low_coverage_or_a_tiny_in_sample_rate():
    thin = pd.DataFrame({"is_net_pnl": [5.0, 6.15] + [np.nan] * 5, "is_days": [500] * 7,
                         "oos_net_pnl": [6_000.0, 6_309.2] + [np.nan] * 5, "oos_days": [60] * 7})
    d = walkforward.efficiency_detail(thin, capital=100_000.0)
    assert d["efficiency"] is None and d["raw_ratio"] > 1_000
    assert d["scored_folds"] == 2 and d["scheduled_folds"] == 7 and "fold" in d["reason"]
    tiny = thin.fillna({"is_net_pnl": 1.0, "oos_net_pnl": 1.0})
    assert walkforward.efficiency_detail(tiny, capital=100_000.0)["efficiency"] is None
    ok = pd.DataFrame({"is_net_pnl": [20_000.0] * 4, "is_days": [500] * 4, "oos_net_pnl": [1_500.0] * 4, "oos_days": [60] * 4})
    d = walkforward.efficiency_detail(ok, capital=100_000.0)
    assert d["efficiency"] == pytest.approx((1_500 / 60) / (20_000 / 500))


def test_checklist_explains_an_unavailable_efficiency():
    import robust
    sc = pd.DataFrame({"scenario": ["baseline"], "net_pnl": [1.0], "capital_exhausted_on": [None]})
    wf = {"oos_net_pnl": 1.0, "oos_profit_factor": 1.5, "walk_forward_efficiency": None, "profitable_oos_folds_pct": 60.0,
          "walk_forward_efficiency_note": "not available: only 2 of 7 folds scored"}
    sw = {"lookahead_check": "passed", "profitable_pct": 80.0, "best_score": 1.0, "best_is_isolated_spike": False,
          "best_neighbourhood_score": 0.9}
    checks = {n: (s, d) for s, n, d in robust.checklist(Namespace(ruin=None, capital=100_000), "MNQ", sw, wf, {},
                                                        {"scenarios": sc, "outlier_dependence": pd.DataFrame()})}
    status, detail = checks["Walk-forward efficiency >= 0.5"]
    assert status == "FAIL" and "2 of 7" in detail


# Timeframe cost report: roll slippage is counted once ---------------------------------------------------
SLIP = Instrument("SLIP", point_value=10.0, tick=0.25, commission=2.0, slippage_ticks=1, qty_step=1)


def test_roll_slippage_is_added_back_once():
    import timeframe_costs
    df = bars([(100.0, 100, 100, 100)] * 6, contracts=["A", "A", "A", "B", "B", "B"])

    class HoldThroughRoll(Strategy):
        def on_bar(self, i):
            if i == 0:
                self.broker.buy(qty=1)
            if i == 3:
                self.broker.close()
    t = Engine(df, SLIP, HoldThroughRoll(), Settings()).run()["trades"]
    assert t.rolls.iloc[0] == 1 and t.roll_slippage_usd.iloc[0] == pytest.approx(5.0)
    before = t.pnl + timeframe_costs.friction(t, SLIP)
    assert before.iloc[0] == pytest.approx(0.0)              # flat prices: nothing earned before costs
    old = t.drop(columns="roll_slippage_usd")                # ledgers saved before the column existed
    assert (old.pnl + timeframe_costs.friction(old, SLIP)).iloc[0] == pytest.approx(0.0)


# Timeframe portfolio: carry-in, exact overlap and exposure ----------------------------------------------
def ledger(rows):
    t = pd.DataFrame(rows, columns=["entry_time", "exit_time", "qty", "entry_px"])
    for c in ("entry_time", "exit_time"):
        t[c] = pd.to_datetime(t[c], utc=True)
    t["entry_tday"] = t.entry_time.dt.tz_convert(None).dt.normalize()
    t["exit_tday"] = t.exit_time.dt.tz_convert(None).dt.normalize()
    return t


def test_portfolio_counts_overlap_from_timestamps_and_reports_carry_in():
    import timeframe_portfolio as tp
    a = ledger([("2024-06-03 14:00", "2024-06-03 15:00", 1, 100.0), ("2024-05-30 14:00", "2024-06-04 15:00", 1, 100.0)])
    b = ledger([("2024-06-03 16:00", "2024-06-03 17:00", 1, 100.0)])
    assert tp.max_overlap({"a": a, "b": b}) == 2              # same day, but never three at once
    assert tp.carried_in({"a": a, "b": b}, pd.Timestamp("2024-06-03")) == 1


# Repeated look-ahead work inside one `robust all` ---------------------------------------------------------
def test_lookahead_gate_reuses_coverage_only_inside_one_run(monkeypatch):
    import robust
    from engine.parallel import Job
    calls = []
    big = bars([(100.0, 100, 100, 100)] * 50)
    monkeypatch.setattr(robust.data, "resample", lambda df, tf, session: big)
    monkeypatch.setattr(robust, "check_lookahead", lambda make, b, inst, s, **k: calls.append(1) or [])
    a = Namespace(strategy=str(ROOT / "strategies/photos/a01_rsi_ema_vwap.py"), tf=1, session="full", start=None, end=None,
                  force=False)
    job = Job(a.strategy, "NQ", 1, FREE, Settings())
    robust.lookahead_gate(a, job, big); robust.lookahead_gate(a, job, big)
    assert len(calls) == 2                                    # standalone commands: independent checks
    calls.clear()
    with robust.lookahead_reuse():
        robust.lookahead_gate(a, job, big)
        msg = robust.lookahead_gate(a, job, big)
        robust.lookahead_gate(a, job.with_(settings=Settings(capital=1.0)), big)   # different settings: checked
    assert len(calls) == 2 and "already checked in this run" in msg


def test_boundary_only_recheck_finds_the_sparse_future_read():
    from engine.core import check_boundary_cuts
    df = bars([(100.0 + k, 101.0 + k, 99.0 + k, 100.5 + k) for k in range(200)])
    cov = {}
    problems = check_boundary_cuts(SparsePeek, df, FREE, coverage=cov)
    assert problems and cov["decision_rows"] == 1 and cov["boundary_cuts"] >= 1
