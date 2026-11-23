"""Regression tests for findings.md, sections "Verification of the batched fixes" (remaining issues) and
"Consolidated end-to-end audit" (E1-E8, R1-R7, I1-I4, C1-C3)."""
import json
import sys
import threading
from argparse import Namespace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings, Strategy, data, metrics, montecarlo, stress, sweep, walkforward  # noqa: E402
from engine.core import check_lookahead  # noqa: E402
from engine.instruments import Instrument  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from test_engine import CFD, FREE, Script, bars  # noqa: E402

ET = "America/New_York"


def frame_at(times_et, px):
    """Bars at the given New York times (strings) with o=h=l=c from px (or (o,h,l,c) tuples)."""
    ts = [int(pd.Timestamp(t, tz=ET).tz_convert("UTC").timestamp()) for t in times_et]
    rows = [p if isinstance(p, tuple) else (p, p, p, p) for p in px]
    df = pd.DataFrame(rows, columns=["o", "h", "l", "c"], dtype=float)
    df["ts"], df["v"], df["contract"], df["roll"] = ts, 1, "A", False
    return data._add_time_columns(df)


# E1 --------------------------------------------------------------------------------------------------
class FirstRowPeek(Strategy):
    """Uses the NEXT close on the first row only."""
    def prepare(self, df):
        f = df.c.copy()
        f.iloc[0] = df.c.iloc[1]
        df["feat"] = f
        return df

    def on_bar(self, i):
        pass


def test_lookahead_check_finds_a_future_read_in_the_first_rows():
    df = bars([(100.0 + k, 101.0 + k, 99.0 + k, 100.5 + k) for k in range(400)])
    assert check_lookahead(FirstRowPeek, df)


def test_lookahead_gate_checks_the_whole_selected_period(monkeypatch):
    import robust
    seen = []
    big = bars([(100.0, 100, 100, 100)] * 50)
    monkeypatch.setattr(robust.data, "resample", lambda df, tf, session: pd.concat([big] * 7000, ignore_index=True))
    monkeypatch.setattr(robust, "check_lookahead", lambda make, b, inst, s, **k: seen.append(len(b)) or [])
    a = Namespace(strategy=str(ROOT / "strategies/photos/a01_rsi_ema_vwap.py"), tf=1, session="full", start=None, end=None,
                  force=False)
    from engine.parallel import Job
    msg = robust.lookahead_gate(a, Job(a.strategy, "NQ", 1, FREE, Settings()), big)
    assert seen and min(seen) == 350_000                 # no truncation to the last 300,000 bars
    assert "350,000 bars" in msg and "1 of 1 parameter set" in msg


def test_standalone_runner_refuses_to_publish_after_a_failed_check(tmp_path, monkeypatch):
    import run as runner
    f = tmp_path / "peek.py"
    f.write_text("from engine import Strategy\nclass P(Strategy):\n    def prepare(self, df):\n        df['x'] = df.c.shift(-1)\n"
                 "        return df\n    def on_bar(self, i):\n        if self.d['x'][i] == self.d['x'][i] and self.broker.flat:\n"
                 "            self.broker.buy(qty=1)\nSTRATEGY = P\n")
    df = bars([(100.0 + k, 101.0 + k, 99.0 + k, 100.5 + k) for k in range(60)])
    monkeypatch.setattr(runner.data, "load", lambda key, start=None, end=None: df)
    monkeypatch.setattr(runner.data, "resample", lambda d, tf, session: d)
    saved = []
    monkeypatch.setattr(runner.report, "save", lambda *a, **k: saved.append(1) or tmp_path)
    monkeypatch.setattr(sys, "argv", ["run.py", str(f), "--symbol", "MNQ"])
    with pytest.raises(SystemExit, match="look-ahead"):
        runner.main()
    assert not saved


# E2 --------------------------------------------------------------------------------------------------
def orb_day(extra_times=(), extra_px=()):
    times = [str(pd.Timestamp("2024-01-08 09:30") + pd.Timedelta(minutes=k)) for k in range(151)] + list(extra_times)
    px = [(100.0, 101.0, 99.0, 100.0)] + [100.0] * 150 + list(extra_px)
    return times, px


def test_orb_order_cannot_fill_at_the_entry_cutoff():
    times, px = orb_day()
    px[120] = (100.0, 102.0, 100.0, 100.0)              # 11:30 bar trades through the range high
    orb = load_strategy(str(ROOT / "strategies/orb.py"))
    t = Engine(frame_at(times, px), FREE, orb(), Settings()).run()["trades"]
    assert len(t) == 0


def test_orb_position_closes_at_the_first_bar_after_a_missing_close():
    times, px = orb_day(["2024-01-08 18:00", "2024-01-08 18:01"], [100.5, 100.5])
    times, px = times[:151], px[:151]
    px[30] = (100.0, 101.5, 100.0, 100.5)                # 10:00 breakout, then the data stops at 12:00
    times += ["2024-01-08 18:00", "2024-01-08 18:01"]; px += [100.5, 100.5]
    orb = load_strategy(str(ROOT / "strategies/orb.py"))
    t = Engine(frame_at(times, px), FREE, orb(), Settings()).run()["trades"].iloc[0]
    assert pd.Timestamp(t.exit_time).tz_convert(ET).strftime("%H:%M") == "18:00"


# E3 --------------------------------------------------------------------------------------------------
def test_futures_mfi_does_not_change_when_a_later_roll_rebases_history():
    rng = np.random.default_rng(4)
    raw = 100 + np.cumsum(rng.normal(0, 1, 60))
    rows = [(p, p + 1, p - 1, p + 0.3) for p in raw]
    a = bars(rows)
    a["adj"] = 0.0
    for k in "ohlc":
        a["raw_" + k] = a[k]
    b = a.copy()                                        # same raw prices; a later roll shifted all of them by 1,206.75
    for k in "ohlc":
        b[k] = b[k] + 1206.75
    b["adj"] = 1206.75
    a07 = load_strategy(str(ROOT / "strategies/photos/a07_mfi_reversal.py"))
    ma, mb = a07(mfi_len=5).prepare(a.copy())["mfi"], a07(mfi_len=5).prepare(b.copy())["mfi"]
    assert np.allclose(ma, mb, equal_nan=True)


# E4 --------------------------------------------------------------------------------------------------
def test_gc_fallback_roll_estimate_uses_past_rolls_only():
    prices = np.full(8, 1000.0)
    spreads = np.array([np.nan, 2.0, 3.0, np.nan, 5.0, 6.0, 7.0, 8.0])
    est, methods = data.estimate_missing_spreads(spreads.copy(), prices)
    later = spreads.copy(); later[4:] = 50.0
    est2, _ = data.estimate_missing_spreads(later, prices)
    assert est[3] == est2[3]                                  # changing later rolls leaves the earlier estimate alone
    assert est[3] == pytest.approx(2.5)                       # median ratio of the measured rolls before it
    assert "uncertain" in methods[0]                          # no earlier roll: flagged


# E5 --------------------------------------------------------------------------------------------------
class BuyOnce(Strategy):
    def on_bar(self, i):
        if i == 0:
            self.broker.buy(qty=100)


def test_opening_gap_below_zero_is_a_breach_even_if_the_close_recovers():
    df = bars([(100.0, 100, 100, 100), (100.0, 100, 100, 100), (40.0, 60, 40, 60), (60.0, 60, 60, 60)])
    r = Engine(df, FREE, BuyOnce(), Settings(capital=50_000)).run()
    assert metrics.summarize(r)["capital_exhausted_on"] is not None
    t = Engine(df, FREE, BuyOnce(), Settings(capital=50_000, account_constrained=True)).run()["trades"].iloc[0]
    assert t.exit_reason == "capital_exhausted" and t.exit_px == 40


def test_liquidation_is_not_masked_by_a_session_gap_exit():
    times = ["2024-01-08 15:58", "2024-01-08 15:59", "2024-01-09 09:30", "2024-01-09 09:31"]
    df = frame_at(times, [100.0, (100.0, 100.0, 30.0, 30.0), 50.0, 50.0])     # fills at 100, closes the day at 30

    class BuyIntraday(Strategy):
        def on_bar(self, i):
            if i == 0:
                self.broker.buy(qty=100, intraday=True)
    t = Engine(df, FREE, BuyIntraday(), Settings(capital=50_000, account_constrained=True)).run()["trades"].iloc[0]
    assert t.exit_reason == "capital_exhausted"


def test_pair_opening_gap_breach_is_detected():
    from engine.pairs import PairsEngine
    from test_pairs import A, B, pair_frame
    df = pair_frame([2000, 2000, 2000, 2000, 2000], [1990] * 5)
    df.loc[2, "o"] = 800.0                                   # opens 1,200 lower, closes back at 2,000

    class Open(Strategy):
        params = dict(notional=500_000.0)

        def on_bar(self, i):
            if i == 0:
                self.broker.open(+1, 1.0)
    r = PairsEngine(df, A, B, Open(), Settings(capital=50_000, account_constrained=True)).run()
    assert r["trades"].iloc[0].exit_reason == "capital_exhausted"


# E6 / E7 ---------------------------------------------------------------------------------------------
def test_pair_drawdown_includes_an_adverse_move_between_marks():
    from engine.pairs import PairsEngine
    from test_pairs import A, B, Script as PScript, pair_frame
    df = pair_frame([2000] * 5, [1990] * 5)
    df.loc[2, "l"] = 1950.0                                  # leg A dips 50 inside the bar; open = close
    r = PairsEngine(df, A, B, PScript({0: [("open", 1, 1.0)]}, notional=20_000), Settings()).run()
    qa = r["trades"].iloc[0].qty
    assert metrics.summarize(r)["max_drawdown_usd"] <= -50 * qa * A.point_value + 1e-6


def test_pair_negative_beta_goes_long_the_second_leg():
    from engine.pairs import PairsEngine
    from test_pairs import A, B, Script as PScript, pair_frame
    df = pair_frame([2000] * 4, [1990, 1990, 2000, 2000])    # B rises 10
    t = PairsEngine(df, A, B, PScript({0: [("open", 1, -1.0)], 2: [("close",)]}, notional=20_000), Settings()).run()["trades"].iloc[0]
    assert t.pnl_b > 0


def test_pair_leverage_cap_counts_both_legs():
    from engine.pairs import PairsEngine
    from test_pairs import A, B, Script as PScript, pair_frame
    df = pair_frame([20.0] * 4, [20.0] * 4)                   # 1 A contract = $200, B 0.01 lot = $20
    r = PairsEngine(df, A, B, PScript({0: [("open", 1, 1.0)]}, notional=2_000), Settings(capital=1_000, max_leverage=1)).run()
    t = r["trades"].iloc[0]
    gross = t.qty * 20 * A.point_value + t.qty_b * 20 * B.point_value
    assert gross <= 1_000 + 1e-6


# E8 --------------------------------------------------------------------------------------------------
def test_order_flow_strategy_refuses_full_session_input():
    from test_audit5 import a13_frame
    df = a13_frame()
    early = df.iloc[[0]].copy()
    early["ts"] = early.ts - 2 * 3600                         # 07:30 ET: outside the cash session
    df = data._add_time_columns(pd.concat([early, df], ignore_index=True).drop(columns=["tday", "ny_min"], errors="ignore"))
    a13 = load_strategy(str(ROOT / "strategies/photos/a13_order_flow_imbalance.py"))
    with pytest.raises(ValueError, match="cash session"):
        a13().prepare(df)


def test_order_flow_sample_never_spans_a_missing_minute():
    from test_audit5 import a13_frame
    df = a13_frame()
    gap = df.index[60]                                        # remove 10:30 on day 1
    df = df.drop(index=gap).reset_index(drop=True)
    a13 = load_strategy(str(ROOT / "strategies/photos/a13_order_flow_imbalance.py"))
    out = a13(window=30).prepare(df.copy())
    assert np.isnan(out.ofi_ret.iloc[60])


# R1 --------------------------------------------------------------------------------------------------
def test_checklist_reports_the_worst_tested_scenario():
    import robust
    sc = pd.DataFrame({"scenario": ["baseline", "delay 2 bars", "ALL: costs x2 + slip +1 + delay 1"],
                       "net_pnl": [20_000.0, -6_549.5, 17_412.5], "capital_exhausted_on": [None, None, None]})
    sw = {"lookahead_check": "passed", "profitable_pct": 80.0, "best_score": 1.0, "best_is_isolated_spike": False,
          "best_neighbourhood_score": 0.9}
    wf = {"oos_net_pnl": 1.0, "oos_profit_factor": 1.5, "walk_forward_efficiency": 0.8, "profitable_oos_folds_pct": 60.0}
    checks = {n: (s, d) for s, n, d in robust.checklist(Namespace(ruin=None, capital=100_000), "MNQ", sw, wf, {},
                                                        {"scenarios": sc, "outlier_dependence": pd.DataFrame()})}
    assert "Still profitable under combined execution stress" in checks
    status, detail = checks["Still profitable in every tested execution scenario"]
    assert status == "FAIL" and "delay 2 bars" in detail


def test_study_ranking_requires_every_scenario_to_be_profitable():
    sys.path.insert(0, str(ROOT / "tools"))
    import photo_report_tables as prt
    row = dict(wf_oos_net=15_000.0, wf_oos_pf=1.5, checks_passed=12, mc_prob_loss_pct=1.0, stress_all_net=5_000.0,
               stress_worst_net=1_000.0)
    r = pd.DataFrame([row, {**row, "stress_worst_net": -6_549.5}])
    assert list(prt.robust_mask(r)) == [True, False]


# R2 --------------------------------------------------------------------------------------------------
def test_market_period_pnl_comes_from_marked_equity(monkeypatch):
    days = pd.bdate_range("2020-01-02", "2020-06-30")
    eq = pd.Series(100_000.0, index=days)
    inside = (days >= "2020-02-19") & (days <= "2020-04-30")
    eq[inside] = 100_000 + np.linspace(0, 600, inside.sum())
    eq[days > "2020-04-30"] = 100_600.0
    daily = pd.DataFrame({"tday": days.values.astype("datetime64[D]"), "equity": eq.values, "start_equity": 100_000.0})
    trades = pd.DataFrame({"pnl": [600.0], "exit_tday": [np.datetime64("2020-05-15")], "entry_tday": [np.datetime64("2020-03-02")]})

    def fake(jobs, workers=None, progress=True):
        base = {"summary": {"net_pnl": 600.0, "trades": 1}, "trades": trades, "daily": daily,
                "days": days.values.astype("datetime64[D]")}
        return [base] + [{"summary": {"net_pnl": 600.0, "trades": 1}} for _ in jobs[1:]]
    monkeypatch.setattr(stress, "run_many", fake)
    from engine.parallel import Job
    out = stress.run(Job("s.py", "NQ", 1440, FREE, Settings(capital=100_000)))
    covid = out["named_periods"].set_index("period").loc["COVID crash 2020"]
    assert covid.net_pnl == pytest.approx(600.0, abs=1.0)


def test_worst_stretch_marks_incomplete_windows():
    d = pd.Series([10.0, -20.0, 5.0], index=pd.to_datetime(["2020-01-31", "2020-02-14", "2020-03-02"]))
    t = stress._stretches(d).set_index("window")
    assert pd.isna(t.loc["worst rolling 3 months", "net_pnl"])
    assert "2020-01-31" in t.loc["worst rolling 3 months", "when"] or "incomplete" in t.loc["worst rolling 3 months", "when"]


# R3 --------------------------------------------------------------------------------------------------
def test_walk_forward_efficiency_uses_total_pnl_per_scored_day():
    folds = pd.DataFrame({"is_net_pnl": [100.0, 100.0], "is_days": [100, 100], "oos_net_pnl": [10.0, 0.0], "oos_days": [10, 90]})
    assert walkforward.efficiency(folds) == pytest.approx(0.1)


# R4 --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("sym,commission,expected", [("MNQ", 0.0, False), ("NAS100", 2.0, True)])
def test_double_commission_check_follows_the_tested_cost(sym, commission, expected):
    import robust
    sc = pd.DataFrame({"scenario": ["baseline", "commission x2"], "net_pnl": [1.0, 1.0], "capital_exhausted_on": [None, None]})
    sw = {"lookahead_check": "passed", "profitable_pct": 80.0, "best_score": None}
    names = [n for _, n, _ in robust.checklist(Namespace(ruin=None, capital=100_000), sym, sw, {}, {},
                                               {"scenarios": sc, "outlier_dependence": pd.DataFrame(),
                                                "baseline_commission": commission})]
    assert ("Still profitable with double commission" in names) == expected


# R5 --------------------------------------------------------------------------------------------------
def test_spread_cost_uses_the_quote_of_the_actual_fill():
    rows = [(100.0, 100, 100, 100)] * 3
    ba = {"o": ([99.5] * 3, [100.5] * 3), "h": ([98.0] * 3, [102.0] * 3), "l": ([98.0] * 3, [102.0] * 3),
          "c": ([98.0] * 3, [102.0] * 3)}
    t = Engine(bars(rows, bidask=ba), CFD, Script({0: [("buy", dict(qty=1))]}), Settings()).run()["trades"].iloc[0]
    assert t.exit_reason == "end_of_data"
    assert t.spread_usd == pytest.approx((0.5 + 2.0) * CFD.point_value)


# R6 --------------------------------------------------------------------------------------------------
def test_partial_one_second_tape_is_unresolved(monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import verify_orb_fills_1s as v
    monkeypatch.setattr(v, "seconds", lambda t0, t1, c: pd.DataFrame({"ts": [t0], "o": [100.0], "h": [100.0], "l": [100.0], "c": [101.0]}))
    assert v.replay_trade(1, 1000, 100.0, 95.0, 110.0, 1, 10.0, 0.0, 0.0, 0.25, 5000, "X") is None


# R7 --------------------------------------------------------------------------------------------------
def test_single_day_report_has_no_annualised_figures():
    df = bars([(100.0, 100, 100, 100), (100.0, 100, 100, 100), (110.0, 110, 110, 110)])
    s = metrics.summarize(Engine(df, FREE, Script({0: [("buy", dict(qty=100))], 1: [("close", {})]}), Settings(capital=100_000)).run())
    assert s["trades"] == 1 and s["annual_return_pct_simple"] is None and s["trades_per_year"] is None


# I1 --------------------------------------------------------------------------------------------------
def test_session_without_bars_is_rejected(monkeypatch):
    import robust
    evening = frame_at(["2018-12-05 18:00", "2018-12-05 18:01"], [100.0, 100.0])
    monkeypatch.setattr(robust.data, "load", lambda key, start=None, end=None: evening)
    a = Namespace(strategy=str(ROOT / "strategies/photos/a01_rsi_ema_vwap.py"), commission=None, slippage=None, spread=None,
                  data=None, start="2018-12-05", end="2018-12-05", capital=50_000.0, account_constrained=False, tf=1,
                  set=None, warmup_days=10, session="rth")
    with pytest.raises(SystemExit, match="no bars in the rth session"):
        robust.make_job(a, "NAS100")


# I2 --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kw", [dict(skip_pct=101), dict(haircut_pct=120), dict(n_sims=0), dict(capital=0.0),
                                dict(pnl=[1.0, float("nan")]), dict(skip_pct=-1)])
def test_monte_carlo_rejects_meaningless_inputs(kw):
    args = dict(pnl=[5.0, -2.0, 3.0], capital=1000.0, n_sims=10, method="bootstrap")
    args.update(kw)
    with pytest.raises(ValueError):
        montecarlo.simulate(**args)


def test_monte_carlo_accepts_percentage_endpoints():
    montecarlo.simulate([5.0, -2.0, 3.0], 1000.0, 10, "bootstrap", skip_pct=100)
    montecarlo.simulate([5.0, -2.0, 3.0], 1000.0, 10, "bootstrap", haircut_pct=0)


# I3 --------------------------------------------------------------------------------------------------
def test_concurrent_study_writers_keep_every_row(tmp_path):
    import photo_study as ps
    path = tmp_path / "rows.csv"

    def writer(tag):
        for k in range(15):
            ps.save_row(path, {"strategy": f"{tag}{k}", "market": "X", "session": "full", "net": 1.0})
    ts = [threading.Thread(target=writer, args=(t,)) for t in "ab"]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(pd.read_csv(path)) == 30


def test_output_folders_are_unique_within_one_second(tmp_path, monkeypatch):
    import robust
    monkeypatch.setattr(robust, "RESULTS", tmp_path)
    assert robust.outdir("ALL", "s.py", "MNQ") != robust.outdir("ALL", "s.py", "MNQ")


# I4 --------------------------------------------------------------------------------------------------
def test_worker_count_respects_the_memory_budget(monkeypatch):
    from engine import parallel
    monkeypatch.setattr(parallel, "_ram_gb", lambda: 16.0)
    assert parallel.default_workers(per_worker_gb=3.0) <= 3
    assert parallel.default_workers(per_worker_gb=1.0) >= parallel.default_workers(per_worker_gb=3.0)


# C1 --------------------------------------------------------------------------------------------------
def test_daily_blocks_stay_inside_continuous_segments():
    pnl = np.arange(10, dtype=float)
    mc = montecarlo.simulate(pnl, 1000.0, 200, "daily", block=5, segments=[5, 5])
    assert mc["distinct_block_starts"] == 2


def test_saved_replay_splits_daily_history_at_skipped_folds(tmp_path, monkeypatch):
    import robust
    d1 = pd.bdate_range("2016-01-04", periods=8); d2 = pd.bdate_range("2017-02-01", periods=8)
    eq = pd.DataFrame({"tday": [str(x.date()) for x in d1.append(d2)], "equity": 100_000 + np.arange(16.0)})
    eq.to_csv(tmp_path / "walkforward_oos_daily_equity.csv", index=False)
    pd.DataFrame({"pnl": [5.0, 3.0], "exit_tday": ["2016-01-05", "2017-02-02"]}).to_csv(tmp_path / "walkforward_oos_trades.csv", index=False)
    pd.DataFrame({"fold": [1, 2, 3], "oos_start": ["2016-01-01", "2016-02-01", "2017-02-01"],
                  "oos_end": ["2016-01-31", "2017-01-31", "2017-02-28"], "chosen": ["{}", None, "{}"],
                  "oos_net_pnl": [5.0, np.nan, 3.0]}).to_csv(tmp_path / "walkforward_folds.csv", index=False)
    (tmp_path / "walkforward_summary.json").write_text(json.dumps({"oos_full_summary": {"capital": 100_000.0}}))
    seen = {}

    def fake(items, capital, *a, **k):
        seen.update(k)
        return {}
    monkeypatch.setattr(montecarlo, "simulate", fake)
    monkeypatch.setattr(montecarlo, "report", lambda mc, out, title: (out.mkdir(parents=True, exist_ok=True),
                                                                     (out / "montecarlo_report.txt").write_text("x"), {})[2])
    robust.cmd_montecarlo(Namespace(from_dir=str(tmp_path), method="daily", capital=50_000.0, sims=10, seed=1, block=5,
                                    skip=0.0, haircut=0.0, ruin=None))
    assert seen.get("segments") == [8, 8]


# C2 --------------------------------------------------------------------------------------------------
def test_profitable_share_counts_every_setting_with_enough_trades(tmp_path):
    grid = {"x": [1, 2, 3]}
    s = [{"trades": 40, "profit_factor": float("inf"), "net_pnl": 500.0},
         {"trades": 40, "profit_factor": float("inf"), "net_pnl": 300.0},
         {"trades": 40, "profit_factor": 0.8, "net_pnl": -100.0}]
    df = pd.DataFrame([{"x": x, "score": metrics.score(v, "profit_factor", 30), **v} for x, v in zip(grid["x"], s)])
    df["plateau_score"] = sweep.plateau(df, grid, "score")
    info = sweep.report(df, grid, tmp_path, "profit_factor", "t", min_trades=30)
    assert info["profitable_pct"] == pytest.approx(66.7)


# C3 --------------------------------------------------------------------------------------------------
def test_saved_daily_replay_accepts_one_trade_with_enough_days(tmp_path, monkeypatch):
    import robust
    pd.DataFrame({"pnl": [5.0], "exit_tday": ["2024-01-03"]}).to_csv(tmp_path / "trades.csv", index=False)
    pd.DataFrame({"tday": [str(d.date()) for d in pd.bdate_range("2024-01-02", periods=6)],
                  "equity": [1000.0, 1005, 1005, 1005, 1005, 1005]}).to_csv(tmp_path / "daily_equity.csv", index=False)
    (tmp_path / "summary.json").write_text(json.dumps({"capital": 1000.0}))
    ran = []
    monkeypatch.setattr(montecarlo, "simulate", lambda items, *a, **k: ran.append(len(items)) or {})
    monkeypatch.setattr(montecarlo, "report", lambda mc, out, title: (out.mkdir(parents=True, exist_ok=True),
                                                                     (out / "montecarlo_report.txt").write_text("x"), {})[2])
    robust.cmd_montecarlo(Namespace(from_dir=str(tmp_path), method="daily", capital=50_000.0, sims=10, seed=1, block=2,
                                    skip=0.0, haircut=0.0, ruin=None))
    assert ran == [6]


# Timeframe study ------------------------------------------------------------------------------------
def test_percent_thresholds_scale_with_the_square_root_of_bar_time():
    import photo_study as ps
    assert ps.pct_scale(1440, 1440, "rth") == 1.0
    assert ps.pct_scale(1440, 5, "rth") == pytest.approx(np.sqrt(5 / 390))
    assert ps.pct_scale(1440, 240, "full") == pytest.approx(np.sqrt(240 / 1380))


def test_only_declared_price_percentages_are_scaled():
    import photo_study as ps
    a12 = load_strategy(str(ROOT / "strategies/photos/a12_volatility_squeeze_breakout.py"))
    a01 = load_strategy(str(ROOT / "strategies/photos/a01_rsi_ema_vwap.py"))
    assert ps.scaled(a12.params, 0.1, getattr(a12, "PRICE_PCT", ())) == a12.params       # squeeze_pct is a percentile
    assert ps.scaled(a01.params, 0.1, a01.PRICE_PCT)["vwap_disc_pct"] == pytest.approx(0.1)
    assert ps.scaled(a01.params, 0.1, a01.PRICE_PCT)["ema_len"] == 100                  # lengths stay in bars


def test_signal_strategies_ask_for_three_times_their_longest_lookback():
    a03 = load_strategy(str(ROOT / "strategies/photos/a03_williams_ema_vwap.py"))
    assert a03().warmup_bars() == 3 * 200 + 2


# Study run: A13 on 1-hour cash-session bars failed its own look-ahead check ---------------------------
def test_order_flow_bar_size_is_inferred_from_past_bars_only():
    """1-hour cash-session bars start 09:30 (a 30-minute bar), then 10:00, 11:00 ... A bar size guessed from the
    whole frame (60) differs from the one guessed on a two-bar prefix (30), so the 10:00 sample was in or out
    depending on how much FUTURE data existed. The strategy must give the same columns on every prefix."""
    from test_audit5 import a13_frame
    m1 = a13_frame()
    starts = [570] + list(range(600, 960, 60))                       # 09:30, 10:00, 11:00 ... 15:00
    rows = m1[m1.ny_min.isin(starts)].reset_index(drop=True)
    a13 = load_strategy(str(ROOT / "strategies/photos/a13_order_flow_imbalance.py"))
    bad = check_lookahead(lambda: a13(window=5), rows)
    assert bad == [], bad
