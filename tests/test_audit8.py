"""Regression tests for findings.md, section "Batched audit before regenerating the study"."""
import json
import signal
import sys
import tracemalloc
from argparse import Namespace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import montecarlo, sweep, walkforward  # noqa: E402


def mc_args(**kw):
    base = dict(from_dir=None, method="daily", capital=50_000.0, sims=64, seed=1, block=1, skip=0.0, haircut=0.0, ruin=None)
    return Namespace(**{**base, **kw})


# 1 ---------------------------------------------------------------------------------------------------
def test_saved_walkforward_replay_uses_the_recorded_capital(tmp_path, monkeypatch):
    import robust
    pd.DataFrame({"pnl": [20_000.0, 13_301.70], "exit_tday": ["2024-01-03", "2024-01-05"]}).to_csv(
        tmp_path / "walkforward_oos_trades.csv", index=False)
    pd.DataFrame({"tday": ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
                  "equity": [100_000.0, 120_000.0, 120_000.0, 133_301.70]}).to_csv(
        tmp_path / "walkforward_oos_daily_equity.csv", index=False)
    (tmp_path / "walkforward_summary.json").write_text(json.dumps({"oos_net_pnl": 33_301.70,
                                                                   "oos_full_summary": {"capital": 100_000.0}}))
    seen = {}

    def fake_sim(items, capital, *a, **k):
        seen["items"], seen["capital"] = np.asarray(items), capital
        return {}
    monkeypatch.setattr(montecarlo, "simulate", fake_sim)
    def fake_report(mc, out, title):
        out.mkdir(parents=True, exist_ok=True); (out / "montecarlo_report.txt").write_text("x")
        return {}
    monkeypatch.setattr(montecarlo, "report", fake_report)
    robust.cmd_montecarlo(mc_args(from_dir=str(tmp_path)))
    assert seen["capital"] == 100_000.0
    assert seen["items"].sum() == pytest.approx(33_301.70)


# 2 ---------------------------------------------------------------------------------------------------
def breached_inputs():
    sw = {"lookahead_check": "passed", "profitable_pct": 80.0, "best_score": 1.0, "best_is_isolated_spike": False,
          "best_neighbourhood_score": 0.9}
    wf = {"oos_net_pnl": 15_000.0, "oos_profit_factor": 1.5, "walk_forward_efficiency": 0.8,
          "profitable_oos_folds_pct": 60.0, "account_model": "constrained", "oos_capital_exhausted_on": "2022-07-22"}
    sc = pd.DataFrame({"scenario": ["baseline", "commission x2", "ALL: costs x2 + slip +1 + delay 1"],
                       "net_pnl": [15_000.0, 14_000.0, 12_000.0],
                       "capital_exhausted_on": ["2022-07-01", "2022-07-02", "2022-07-03"]})
    return sw, wf, {}, {"scenarios": sc, "outlier_dependence": pd.DataFrame()}


def test_breached_account_never_passes_a_profit_check():
    import robust
    sw, wf, mc, st = breached_inputs()
    checks = {name: status for status, name, _ in robust.checklist(Namespace(ruin=None, capital=100_000), "MGC", sw, wf, mc, st)}
    assert checks["Walk-forward out-of-sample is profitable"] == "FAIL"
    assert checks["Still profitable under combined execution stress"] == "FAIL"
    assert checks["Still profitable with double commission"] == "FAIL"


def test_study_ranking_requires_the_account_to_survive():
    sys.path.insert(0, str(ROOT / "tools"))
    import photo_report_tables as prt
    row = dict(wf_oos_net=15_000.0, wf_oos_pf=1.5, checks_passed=12, mc_prob_loss_pct=1.0, stress_all_net=5_000.0,
               capital_exhausted_on=np.nan, wf_capital_exhausted_on=np.nan, stress_all_capital_exhausted_on=np.nan)
    r = pd.DataFrame([row, {**row, "wf_capital_exhausted_on": "2022-07-22"}, {**row, "stress_all_capital_exhausted_on": "2022-10-13"},
                      {**row, "capital_exhausted_on": "2021-08-23"}])
    assert list(prt.robust_mask(r)) == [True, False, False, False]


# 3 ---------------------------------------------------------------------------------------------------
class _Timeout(Exception):
    pass


def _alarm(*_):
    raise _Timeout


@pytest.mark.parametrize("is_m,oos_m", [(1, 0), (0, 1), (-1, 3), (12, -1)])
def test_walkforward_rejects_nonpositive_windows(is_m, oos_m):
    days = pd.bdate_range("2020-01-01", "2020-12-31").values.astype("datetime64[D]")
    old = signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(2)
    try:
        with pytest.raises(ValueError, match="month"):
            walkforward.make_folds(days, is_m, oos_m)
    finally:
        signal.alarm(0); signal.signal(signal.SIGALRM, old)


def test_walkforward_rejects_an_empty_day_list():
    with pytest.raises(ValueError, match="no trading days"):
        walkforward.make_folds(np.array([], dtype="datetime64[D]"), 12, 3)


def test_cli_rejects_nonpositive_months(monkeypatch):
    import robust
    monkeypatch.setattr(sys, "argv", ["robust.py", "walkforward", "x.py", "--oos-months", "0"])
    with pytest.raises(SystemExit) as e:
        robust.main()
    assert e.value.code == 2                       # argparse usage error, before any data is loaded


def test_date_range_outside_the_data_gives_a_clear_error(monkeypatch):
    import robust
    from engine import data
    empty = pd.DataFrame({"ts": pd.Series([], dtype="int64"), "tday": pd.Series([], dtype="datetime64[ns]")})
    monkeypatch.setattr(data, "load", lambda key, start=None, end=None: empty)
    a = Namespace(strategy=str(ROOT / "strategies/photos/a01_rsi_ema_vwap.py"), commission=None, slippage=None, spread=None,
                  data=None, start="2000-01-01", end="2000-01-31", capital=50_000.0, account_constrained=False, tf=1,
                  set=None, warmup_days=10, session="full")
    with pytest.raises(SystemExit, match="no data"):
        robust.make_job(a, "MNQ")


# 4 ---------------------------------------------------------------------------------------------------
def test_daily_monte_carlo_rejects_a_block_with_too_few_starts():
    with pytest.raises(ValueError, match="block"):
        montecarlo.simulate([5.0, -2.0, 7.0], 100.0, 128, "daily", seed=1, block=5)


def test_daily_monte_carlo_reports_its_distinct_block_starts():
    pnl = np.sin(np.arange(40)) * 10
    mc = montecarlo.simulate(pnl, 1000.0, 256, "daily", seed=1, block=5)
    assert mc["distinct_block_starts"] == 36
    assert np.std(mc["_finals"]) > 0


# 5 ---------------------------------------------------------------------------------------------------
def test_monte_carlo_does_not_keep_finished_batches_alive(monkeypatch):
    monkeypatch.setattr(montecarlo, "BATCH_CELLS", 100_000)      # 100 sims x 1,000 items per batch (0.8 MB)
    pnl = np.random.default_rng(0).normal(0, 10, 1000)
    tracemalloc.start()
    montecarlo.simulate(pnl, 1000.0, 6_000, "bootstrap", seed=1, keep_paths=0)    # 60 batches
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert peak < 15e6                                           # retaining every batch would need ~48 MB


def test_monte_carlo_is_still_reproducible():
    pnl = np.random.default_rng(0).normal(0, 10, 300)
    a = montecarlo.simulate(pnl, 1000.0, 2_000, "bootstrap", seed=7)
    b = montecarlo.simulate(pnl, 1000.0, 2_000, "bootstrap", seed=7)
    assert np.array_equal(a["_finals"], b["_finals"]) and a["final_pnl_pct"] == b["final_pnl_pct"]


# 6 ---------------------------------------------------------------------------------------------------
def test_profit_factor_sweep_reports_no_loss_settings_separately(tmp_path):
    from engine import metrics
    grid = {"x": [1, 2, 3]}
    summaries = [{"trades": 40, "profit_factor": float("inf"), "net_pnl": 500.0},      # no losing trade
                 {"trades": 40, "profit_factor": 1.4, "net_pnl": 300.0},
                 {"trades": 10, "profit_factor": 2.0, "net_pnl": 100.0}]                # too few trades
    df = pd.DataFrame([{"x": x, "score": metrics.score(s, "profit_factor", 30), **s} for x, s in zip(grid["x"], summaries)])
    df["plateau_score"] = sweep.plateau(df, grid, "score")
    info = sweep.report(df, grid, tmp_path, "profit_factor", "t", min_trades=30)
    assert info["with_enough_trades"] == 2
    assert info["scored"] == 1
    assert info["excluded_undefined_score"] == 1
    assert "no losing trades" in (tmp_path / "sweep_report.txt").read_text()
