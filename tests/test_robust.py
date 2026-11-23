"""Tests for parameter test, walk-forward, Monte Carlo, stress settings.
Run:  ~/.venvs/t9-backtesting/bin/python -m pytest tests -q -p no:cacheprovider"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import Engine, Settings, data, get_instrument, metrics, montecarlo, sweep, walkforward  # noqa: E402
from engine import parallel  # noqa: E402
from engine.parallel import Job  # noqa: E402
from test_engine import FREE, CFD, Script, bars  # noqa: E402

import robust  # noqa: E402

HAVE_DATA = Path("/Volumes/T9/DATA").exists()


# ---------------------------------------------------------------- walk-forward folds
def _days(a, b):
    return pd.bdate_range(a, b).values.astype("datetime64[D]")


def test_folds_rolling_no_overlap_and_back_to_back():
    f = walkforward.make_folds(_days("2020-01-01", "2023-12-31"), is_months=12, oos_months=6)
    assert len(f) == 6
    for x in f:
        assert x["is_end"] < x["oos_start"]                       # OOS strictly after IS
    for a, b in zip(f, f[1:]):
        assert a["oos_end"] < b["oos_start"]                      # OOS windows never overlap
        assert (pd.Timestamp(b["oos_start"]) - pd.Timestamp(a["oos_end"])).days <= 4   # and leave no gap (weekends only)
    assert f[0]["is_start"] == "2020-01-01" and f[1]["is_start"] == "2020-07-01"      # rolling window moves
    assert f[-1]["oos_end"] == "2023-12-29"


def test_folds_anchored_keep_start():
    f = walkforward.make_folds(_days("2020-01-01", "2022-12-31"), is_months=12, oos_months=12, anchored=True)
    assert [x["is_start"] for x in f] == ["2020-01-01", "2020-01-01"]
    assert f[1]["is_end"] < f[1]["oos_start"] == "2022-01-03"


def test_walkforward_optimiser_only_sees_in_sample(monkeypatch):
    seen = []

    def fake_run_many(jobs, workers=None, progress=True):
        seen.extend(jobs)
        return [{"summary": {"trades": 50, "net_pnl": 1.0, "sharpe_daily_ann": float(j.params["x"])},
                 "trades": pd.DataFrame(), "daily": None, "days": np.array([], dtype="datetime64[D]"), "tag": j.tag}
                for j in jobs]
    monkeypatch.setattr(walkforward, "run_many", fake_run_many)
    base = Job("s.py", "NQ", 1, FREE, Settings())
    wf = walkforward.run(base, {"x": [1, 2, 3]}, _days("2020-01-01", "2022-12-31"), 12, 6)
    folds = {f["fold"]: f for f in wf["folds"]}
    is_jobs = [j for j in seen if "x" in j.tag]
    oos_jobs = [j for j in seen if "x" not in j.tag]
    for j in is_jobs:
        f = folds[j.tag["fold"]]
        assert j.start == f["is_start"] and j.end == f["is_end"] < f["oos_start"]
    for j in oos_jobs:
        f = folds[j.tag["fold"]]
        assert j.start == f["oos_start"] and j.end == f["oos_end"]
        assert j.params["x"] == 3                                # the in-sample winner was used
    assert len(is_jobs) == 3 * len(folds) and len(oos_jobs) == len(folds)


# ---------------------------------------------------------------- parameter test
def test_expand_grid_and_parse_grid():
    assert len(sweep.expand_grid({"a": [1, 2], "b": [1, 2, 3]})) == 6
    g = robust.parse_grid(["rr=1:3:0.5", "n=5,10,20", "k=1:5:2"])
    assert g == {"rr": [1.0, 1.5, 2.0, 2.5, 3.0], "n": [5, 10, 20], "k": [1, 3, 5]}


def test_plateau_mean_of_neighbourhood():
    grid = {"a": [1, 2, 3], "b": [1, 2, 3]}
    df = pd.DataFrame(sweep.expand_grid(grid))
    df["score"] = np.arange(9, dtype=float)                       # a-major: score = 3*(a-1) + (b-1)
    p = sweep.plateau(df, grid)
    assert p[4] == pytest.approx(0.5 * 4.0 + 0.5 * 0)            # centre: all 9 cells, mean 4, worst 0
    assert p[8] == pytest.approx(0.5 * np.mean([4, 5, 7, 8]) + 0.5 * 4)   # corner: 4 cells


def test_pick_prefers_plateau_over_spike():
    grid = {"a": [1, 2, 3, 4, 5, 6]}
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5, 6], "score": [0.0, 3.0, 0.0, 1.5, 1.6, 1.2]})
    df["plateau_score"] = sweep.plateau(df, grid)
    assert sweep.pick(df, grid, "best") == {"a": 2}             # isolated spike
    assert sweep.pick(df, grid, "plateau") == {"a": 5}          # middle of the broad good area
    assert isinstance(sweep.pick(df, grid, "best")["a"], int)
    assert sweep.on_edge({"a": 6}, grid) and not sweep.on_edge({"a": 5}, grid)


def test_score_needs_min_trades():
    assert np.isnan(metrics.score({"trades": 5, "sharpe_daily_ann": 2.0}, "sharpe", 30))
    assert metrics.score({"trades": 50, "net_pnl": 100, "max_drawdown_usd": -50}, "return_dd") == 2.0


# ---------------------------------------------------------------- Monte Carlo
def test_shuffle_keeps_final_pnl_and_finds_known_drawdown():
    pnl = np.array([100, -50, -50, 200, -300, 100.0])
    mc = montecarlo.simulate(pnl, 10_000, n_sims=500, method="shuffle", seed=1)
    assert np.allclose(mc["_finals"], pnl.sum())
    assert mc["actual_max_drawdown_usd"] == pytest.approx(-300)   # peak 200 after 4 trades, then -300
    assert mc["_maxdd"].min() >= -400 - 1e-9                       # worst possible order: all losses in a row
    assert mc["longest_losing_streak_pct"][99] <= 3


def test_monte_carlo_reproducible_and_all_winners():
    pnl = np.array([10.0, 20, 30, 5])
    a = montecarlo.simulate(pnl, 1000, n_sims=300, method="bootstrap", seed=7)
    b = montecarlo.simulate(pnl, 1000, n_sims=300, method="bootstrap", seed=7)
    assert np.array_equal(a["_finals"], b["_finals"])
    assert a["prob_final_loss_pct"] == 0 and a["_maxdd"].max() == 0


def test_monte_carlo_skip_and_ruin():
    pnl = np.array([-100.0] * 10)
    mc = montecarlo.simulate(pnl, 1000, n_sims=200, method="shuffle", ruin_usd=500)
    assert mc["prob_ruin_pct"] == 100.0
    mc2 = montecarlo.simulate(pnl, 1000, n_sims=200, method="shuffle", skip_pct=100)
    assert np.all(mc2["_finals"] == 0)


# ---------------------------------------------------------------- stress settings in the engine
def test_delay_bars_shifts_market_fill_and_close():
    df = bars([(100, 100, 100, 100), (101, 101, 101, 101), (102, 102, 102, 102), (103, 103, 103, 103), (104, 104, 104, 104), (105, 105, 105, 105)])
    plan = {0: [("buy", dict(qty=1))], 2: [("close", dict())]}
    t0 = Engine(df, FREE, Script(plan), Settings()).run()["trades"].iloc[0]
    t1 = Engine(df, FREE, Script(plan), Settings(delay_bars=1)).run()["trades"].iloc[0]
    assert (t0.entry_px, t0.exit_px) == (101, 103)
    assert (t1.entry_px, t1.exit_px) == (102, 104)


def test_spread_mult_widens_real_bid_ask():
    rows = [(100, 100, 100, 100)] * 3
    ba = {k: ([99.9] * 3, [100.1] * 3) for k in "ohlc"}
    df = bars(rows, bidask=ba)
    plan = {0: [("buy", dict(qty=1))]}
    t1 = Engine(df, CFD, Script(plan), Settings()).run()["trades"].iloc[0]
    t2 = Engine(df, CFD, Script(plan), Settings(spread_mult=2)).run()["trades"].iloc[0]
    assert t1.entry_px == pytest.approx(100.1) and t2.entry_px == pytest.approx(100.2)
    assert t2.exit_px == pytest.approx(99.8)


def test_result_from_trades_counts_flat_days():
    t = pd.DataFrame({"pnl": [100.0, -40.0], "exit_tday": np.array(["2024-01-03", "2024-01-05"], dtype="datetime64[D]")})
    days = np.array(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], dtype="datetime64[D]")
    r = metrics.result_from_trades(t, days, Settings(capital=1000), FREE)
    assert list(r["equity"].equity) == [1000, 1100, 1100, 1060]


# ---------------------------------------------------------------- integration on the real data
@pytest.mark.skipif(not HAVE_DATA, reason="T9/DATA not mounted")
def test_windows_reproduce_full_run_exactly():
    """ORB resets daily, so cutting the history into windows must give exactly the full run's trades:
    nothing lost or double-counted at window edges, and the warm-up never adds trades."""
    strat = str(ROOT / "strategies/orb.py")
    inst = get_instrument("MNQ")
    base = Job(strat, "NQ", 1, inst, Settings(), {}, start="2024-01-02", end="2024-06-28")
    full = parallel.run_job(base)["trades"]
    parts = [parallel.run_job(base.with_(start=a, end=b))["trades"] for a, b in
             (("2024-01-02", "2024-02-15"), ("2024-02-16", "2024-04-30"), ("2024-05-01", "2024-06-28"))]
    stitched = pd.concat(parts, ignore_index=True)
    cols = ["entry_time", "exit_time", "side", "qty", "entry_px", "exit_px", "pnl"]
    assert len(full) > 50
    pd.testing.assert_frame_equal(full[cols].reset_index(drop=True), stitched[cols].reset_index(drop=True))
