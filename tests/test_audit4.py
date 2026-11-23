"""Regression tests for the photo-study audit (findings.md, section "Photo-study audit")."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings, data, get_instrument  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from engine.parallel import Job  # noqa: E402
from test_engine import FREE, Script, bars  # noqa: E402

B01 = ROOT / "strategies/photos/b01_pairs_gold_futures_vs_spot.py"


def run(df, inst, plan, **kw):
    return Engine(df, inst, Script(plan), Settings(**kw)).run()


# 1 ---------------------------------------------------------------------------------------------------
def test_split_daily_session_gives_one_indicator_observation():
    # a futures session whose contract switches mid-session is ONE daily bar (one observation for indicators)
    t0 = int(pd.Timestamp("2024-01-09 23:00", tz="UTC").timestamp())          # 18:00 NY, session of Jan 10
    n = 23 * 60
    df = pd.DataFrame({"ts": t0 + 60 * np.arange(n), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1})
    df["contract"] = ["A"] * 300 + ["B"] * (n - 300)
    df["roll"] = (df.contract != df.contract.shift()).to_numpy(); df.loc[0, "roll"] = False
    df = data._add_time_columns(df)
    r = data.resample(df, 1440)
    assert len(r) == 1 and r.roll_inside.iloc[0] and not r.roll.iloc[0]


def test_roll_inside_a_bar_is_charged_only_if_held_after_its_open():
    rows = [(100.0, 100.0, 100.0, 100.0)] * 4
    df = bars(rows)
    df["roll_inside"] = [False, False, True, False]
    inst = FREE.with_costs(commission=1.0)
    held = run(df, inst, {0: [("buy", dict(qty=1))]})["trades"].iloc[0]                 # held through bar 2
    closed = run(df, inst, {0: [("buy", dict(qty=1))], 1: [("close", dict())]})["trades"].iloc[0]   # exits at bar 2 open
    assert held.rolls == 1 and closed.rolls == 0


# 2 ---------------------------------------------------------------------------------------------------
def test_benchmark_uses_scored_dates_and_opening_peaks():
    import photo_study as ps
    t0 = int(pd.Timestamp("2024-01-08 14:30", tz="UTC").timestamp())
    df = pd.DataFrame({"ts": t0 + 86400 * np.arange(4), "o": [100.0, 150, 100, 300], "h": [100.0, 150, 100, 300],
                       "l": [100.0, 100, 100, 300], "c": [100.0, 100, 100, 300], "v": 1, "contract": "X", "roll": False})
    df = data._add_time_columns(df)
    days = [str(x)[:10] for x in df.tday]
    b = ps.benchmark(df, FREE, [(days[0], days[2])], capital=100_000)
    # 100 units ($10/pt) from 100: bar 2 opens at 150 (+$50k) and trades down to 100: a $50k fall from an opening peak
    assert b["max_dd"] <= -50_000 + 1e-6
    assert b["net"] == pytest.approx(0.0)        # the scored window ends on day 3 at 100, not on day 4 at 300


# 3 ---------------------------------------------------------------------------------------------------
def test_warmup_counts_bars_for_nested_windows():
    from engine.parallel import warmup_start
    tday = np.repeat(np.arange(np.datetime64("2024-01-01"), np.datetime64("2024-03-01")), 23)
    first = int(np.searchsorted(tday, np.datetime64("2024-02-15")))
    a, short = warmup_start(tday, first, warmup_days=10, warmup_bars=919)
    assert first - a >= 919 and not short
    a2, short2 = warmup_start(tday, 100, warmup_days=10, warmup_bars=919)
    assert a2 == 0 and short2
    assert load_strategy(str(B01))(window=460).warmup_bars() >= 919


# 4 ---------------------------------------------------------------------------------------------------
def test_pair_bars_use_common_minutes():
    from engine.pairs import combine_legs
    rows = [(100.0 + k, 100.0 + k, 100.0 + k, 100.0 + k) for k in range(10)]
    a = bars(rows)
    b = bars([(200.0 + k, 200.0 + k, 200.0 + k, 200.0 + k) for k in range(10)],
             bidask={k: ([199.9 + j for j in range(10)], [200.1 + j for j in range(10)]) for k in "ohlc"})
    b = b.drop(index=[4, 9]).reset_index(drop=True)   # B has no quote for minute 4 and minute 9 (each bar's last)
    m = combine_legs(a, b, tf=5)
    assert list(m.c) == [103.0, 108.0] and list(m.xc) == [203.0, 208.0]     # both legs' last COMMON minute
    assert (m.ts_last_a == m.ts_last_b).all()


# 5 ---------------------------------------------------------------------------------------------------
def test_pair_stress_widens_the_spot_leg_and_pnl_reconciles():
    from engine.pairs import PairsEngine
    from test_pairs import A, B, Script as PScript, pair_frame
    df = pair_frame([2000, 2000, 2010, 2010], [1990, 1990, 1995, 1995])
    plan = {0: [("open", 1, 1.0)], 1: [("close",)]}
    base = PairsEngine(df, A, B, PScript(plan, notional=40_000), Settings()).run()["trades"].iloc[0]
    wide = PairsEngine(df, A, B, PScript(plan, notional=40_000), Settings(spread_mult=2)).run()["trades"].iloc[0]
    assert wide.pnl < base.pnl
    for t in (base, wide):
        assert t.pnl == pytest.approx(t.pnl_nominal - t.spread_cost - t.slippage_cost - t.commission - t.roll_cost)
    from engine.stress import scenarios
    sc = dict(scenarios(Job(str(B01), "GC+XAUUSD", 60, get_instrument("MGC"), Settings())))
    assert "spread x2" in sc and sc[[k for k in sc if k.startswith("ALL")][0]].settings.spread_mult == 2.0


# 6 ---------------------------------------------------------------------------------------------------
def test_cash_session_drops_exchange_holidays():
    t0 = int(pd.Timestamp("2024-07-04 13:30", tz="UTC").timestamp())        # 09:30 NY on July 4th (holiday)
    df = pd.DataFrame({"ts": t0 + 60 * np.arange(60), "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1,
                       "contract": "X", "roll": False})
    df = data._add_time_columns(df)
    assert len(data.session_filter(df, "rth")) == 0


def test_daily_signals_are_not_taken_on_exchange_holidays():
    from engine.strategy_kit import SignalStrategy

    class Always(SignalStrategy):
        def signals(self, df):
            return {"long_entry": pd.Series(True, index=df.index), "long_exit": pd.Series(True, index=df.index)}
    t0 = int(pd.Timestamp("2024-07-03 14:30", tz="UTC").timestamp())
    df = pd.DataFrame({"ts": t0 + 86400 * np.arange(3), "o": 100.0, "h": 100.0, "l": 100.0, "c": 100.0, "v": 1,
                       "contract": "X", "roll": False})                     # Jul 3, Jul 4 (holiday), Jul 5
    df = data._add_time_columns(df)
    out = Always().prepare(df.copy())
    assert list(out.sig_long_entry) == [True, False, True]


def test_order_flow_strategy_never_holds_overnight_or_learns_across_gaps():
    cls = load_strategy(str(ROOT / "strategies/photos/a13_order_flow_imbalance.py"))
    rng = np.random.default_rng(1)
    days = pd.bdate_range("2024-03-04", periods=4)
    ts = np.concatenate([((d + pd.Timedelta(hours=9, minutes=30)).tz_localize("America/New_York") - pd.Timestamp(0, tz="UTC"))
                         // pd.Timedelta(seconds=1) + 60 * np.arange(390) for d in days])      # 09:30-15:59 New York
    c = 100 + np.cumsum(rng.normal(0, 0.5, len(ts)))
    df = pd.DataFrame({"ts": ts, "o": c, "h": c + 0.25, "l": c - 0.25, "c": c, "v": 10, "contract": "X", "roll": False,
                       "buy_vol": rng.integers(0, 50, len(ts)), "sell_vol": rng.integers(0, 50, len(ts))})
    df = data._add_time_columns(df)
    s = cls(window=60, threshold_ticks=0.1)
    out = s.prepare(df.copy())
    first = np.r_[True, out.tday.to_numpy()[1:] != out.tday.to_numpy()[:-1]]
    assert out["ofi_ret"][first].isna().all()                   # the overnight move is never a training sample
    t = Engine(df, FREE, cls(window=60, threshold_ticks=0.1), Settings()).run()["trades"]
    assert len(t) > 0 and (t.entry_tday == t.exit_tday).all()


# 7 ---------------------------------------------------------------------------------------------------
def test_pair_run_rejects_the_wrong_instrument():
    import robust
    cls = load_strategy(str(B01))
    with pytest.raises(SystemExit):
        robust.check_pair_instrument("MNQ", cls)
    robust.check_pair_instrument("MGC", cls)


def test_study_resume_retries_failures_and_keeps_unrelated_rows(tmp_path, monkeypatch):
    import photo_study as ps
    monkeypatch.setattr(ps, "OUT", tmp_path)
    calls, failed = [], []

    def fake_run_one(path, sym, session, workers):
        calls.append((path.stem, sym, session))
        if path.stem.startswith("a01") and sym == "MNQ" and session == "rth" and not failed:
            failed.append(1)
            raise RuntimeError("boom")                  # fails once, succeeds when retried
        return {"strategy": path.stem, "market": sym, "session": session, "net": 1.0}
    monkeypatch.setattr(ps, "run_one", fake_run_one)
    monkeypatch.setattr(ps, "write_report", lambda rows: None)
    monkeypatch.setattr(sys, "argv", ["x", "--only", "a01", "--markets", "MNQ"])
    ps.main()                                    # first run: one failure
    rows = pd.read_csv(tmp_path / "study_rows.csv")
    assert rows.error.notna().sum() == 1
    calls.clear()
    ps.main()                                    # resume: only the failed row is retried
    assert calls == [("a01_rsi_ema_vwap", "MNQ", "rth")]
    monkeypatch.setattr(sys, "argv", ["x", "--only", "a02", "--markets", "MNQ", "--fresh"])
    ps.main()                                    # a filtered fresh run keeps the a01 rows
    rows = pd.read_csv(tmp_path / "study_rows.csv")
    assert set(rows.strategy) == {"a01_rsi_ema_vwap", "a02_stoch_kama_vwap"} and rows.error.isna().all()


def test_study_rows_record_code_and_data_versions(tmp_path, monkeypatch):
    import photo_study as ps
    v = ps.versions(ROOT / "strategies/photos/a01_rsi_ema_vwap.py", "NQ")
    assert v["code_version"] and v["data_version"]


# carryover --------------------------------------------------------------------------------------------
def test_trade_mae_includes_the_exit_bar_dip():
    rows = [(100, 100, 100, 100), (100, 100, 100, 100), (100, 111, 50, 105), (105, 105, 105, 105)]
    t = run(bars(rows), FREE, {0: [("buy", dict(qty=1, tp=110))]})["trades"].iloc[0]
    assert t.exit_reason == "tp" and t.mae_pts >= 50
