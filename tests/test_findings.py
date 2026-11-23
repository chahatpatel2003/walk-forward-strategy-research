"""Regression tests for the problems reported in findings.md (audit of commit 882fbd7).
Each test reproduces one reported failure; all must pass after the fixes."""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings, Strategy, check_lookahead, data, get_instrument, metrics, montecarlo, stress, walkforward  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from engine.instruments import Instrument  # noqa: E402
from engine.parallel import Job  # noqa: E402
from test_engine import FREE, CFD, Script, bars  # noqa: E402

FUT1 = Instrument("FUT1", point_value=10.0, tick=0.25, commission=0.0, slippage_ticks=1, qty_step=1)


def run(df, inst, plan, **kw):
    return Engine(df, inst, Script(plan), Settings(**kw)).run()


# ---------------------------------------------------------------- close scheduling
def test_repeated_close_calls_do_not_restart_the_delay():
    rows = [(100 + k, 100 + k, 100 + k, 100 + k) for k in range(8)]

    class CloseEveryBar(Strategy):
        def on_bar(self, i):
            if i == 0:
                self.broker.buy(qty=1)
            elif i >= 2:
                self.broker.close("eod")       # called again on every bar, like ORB after its flatten time
    t = Engine(bars(rows), FREE, CloseEveryBar(), Settings(delay_bars=1)).run()["trades"].iloc[0]
    assert t.exit_px == 104                    # requested on bar 2, one bar delay -> exit at bar 4's open


# ---------------------------------------------------------------- fill chronology
def test_no_entry_at_the_open_after_an_intrabar_exit():
    rows = [(100, 100, 100, 100), (100, 100, 100, 100), (110, 111, 94, 96), (96, 96, 96, 96)]
    plan = {0: [("buy", dict(qty=1, sl=95))], 1: [("sell", dict(kind="limit", price=108, qty=1))]}
    t = run(bars(rows), FREE, plan, oco=False)["trades"]
    assert t.iloc[0].exit_reason == "sl"
    # the short limit must not fill at bar 2's 110 open: that open came BEFORE the stop-out
    assert len(t) == 1 or t.iloc[1].entry_time > t.iloc[0].exit_time


def test_oco_takes_the_trigger_nearest_the_open_when_both_hit():
    rows = [(100, 100, 100, 100), (100, 105, 98, 100), (100, 100, 100, 100)]
    plan = {0: [("buy", dict(kind="stop", price=104, qty=1)), ("sell", dict(kind="stop", price=99, qty=1))]}
    r = run(bars(rows), FREE, plan)
    assert r["trades"].iloc[0].side == "short"      # 99 is 1 point from the open, 104 is 4 points
    assert r["notes"]["ambiguous_entry_bars"] == 1


def test_limit_entry_bar_cannot_award_a_target_reached_before_the_entry():
    rows = [(100, 100, 100, 100), (105, 110, 98, 100), (100, 100, 100, 100)]
    plan = {0: [("buy", dict(kind="limit", price=99, qty=1, tp=108))]}
    t = run(bars(rows), FREE, plan)["trades"].iloc[0]
    assert t.exit_reason != "tp"                    # the 110 high came before the dip to 99


# ---------------------------------------------------------------- look-ahead
def test_lookahead_check_catches_overwritten_prices():
    df = bars([(i, i + 1, i - 1, i) for i in range(100, 400)])

    class PeekClose(Strategy):
        def prepare(self, d):
            d["c"] = d["c"].shift(-1).ffill()
            return d

        def on_bar(self, i):
            pass
    assert check_lookahead(PeekClose(), df, FREE) != []


def test_lookahead_check_catches_future_reads_in_on_bar():
    rng = np.random.default_rng(0)
    p = 100 + np.cumsum(rng.normal(0, 1, 400))
    df = bars([(x, x + 0.5, x - 0.5, x) for x in p])

    class Clairvoyant(Strategy):
        def on_bar(self, i):
            d, b = self.d, self.broker
            if b.flat and i + 2 < len(d["c"]) and d["c"][i + 2] > d["c"][i] + 1:
                b.buy(qty=1)
            elif not b.flat and b.bars_in_trade() >= 2:
                b.close()
    assert check_lookahead(Clairvoyant(), df, FREE) != []


def test_prepare_may_not_change_the_prices_used_for_fills():
    df = bars([(100, 100, 100, 100)] * 5)

    class Tamper(Strategy):
        def prepare(self, d):
            d["o"] = d["o"] - 50
            return d

        def on_bar(self, i):
            pass
    with pytest.raises(ValueError, match="prepare"):
        Engine(df, FREE, Tamper(), Settings())


# ---------------------------------------------------------------- spread stress
def test_widened_real_spread_keeps_valid_ohlc():
    rows = [(100, 100, 100, 100)] * 3
    # bid/ask highs and lows happen at different moments with different spreads
    ba = {"o": ([99.9, 99.9, 99.9], [100.1, 100.1, 100.1]), "h": ([100.5, 100.5, 100.5], [100.6, 100.6, 100.6]),
          "l": ([99.0, 99.0, 99.0], [99.8, 99.8, 99.8]), "c": ([99.95, 99.95, 99.95], [100.05, 100.05, 100.05])}
    df = bars(rows, bidask=ba)
    e = Engine(df, CFD, Script({}), Settings(spread_mult=3))
    d = e.d
    for side in "ba":
        o, h, l, c = (np.asarray(d[side + k]) for k in "ohlc")
        assert np.all(h >= np.maximum(o, c) - 1e-12) and np.all(l <= np.minimum(o, c) + 1e-12)
    assert np.all(np.asarray(d["ao"]) - np.asarray(d["bo"]) > 0.2 * 3 - 1e-9)


# ---------------------------------------------------------------- walk-forward state
def test_warmup_positions_never_block_the_scored_window():
    rows = [(100, 100, 100, 100)] * 10

    class BuyAndHold(Strategy):
        def on_bar(self, i):
            if self.broker.flat:
                self.broker.buy(qty=1)
    df = bars(rows)
    start_ts = int(df.ts.iloc[5])
    r = Engine(df, FREE, BuyAndHold(), Settings(trade_start_ts=start_ts)).run()
    t = r["trades"]
    assert len(t) == 1 and t.iloc[0].entry_time == pd.Timestamp(df.ts.iloc[6], unit="s", tz="UTC")


def test_folds_from_a_month_end_start_have_no_gaps():
    days = pd.bdate_range("2020-01-31", "2022-12-30").values.astype("datetime64[D]")
    f = walkforward.make_folds(days, is_months=6, oos_months=1)
    for a, b in zip(f, f[1:]):
        gap = np.busday_count(np.datetime64(a["oos_end"]) + np.timedelta64(1, "D"), np.datetime64(b["oos_start"]))
        assert gap == 0, (a["oos_end"], b["oos_start"])


def test_walkforward_with_no_valid_parameters_does_not_crash(monkeypatch):
    def fake(jobs, workers=None, progress=True, **kw):
        return [{"summary": {"trades": 1}, "trades": pd.DataFrame(), "daily": None, "tag": j.tag} for j in jobs]
    monkeypatch.setattr(walkforward, "run_many", fake)
    wf = walkforward.run(Job("s.py", "NQ", 1, FREE, Settings()), {"x": [1, 2]},
                         pd.bdate_range("2020-01-01", "2021-12-31").values.astype("datetime64[D]"), 6, 3, min_trades=10_000)
    assert len(wf["oos_result"]["trades"]) == 0 and wf["folds"]


# ---------------------------------------------------------------- drawdown
def test_intraday_drawdown_is_reported():
    rows = [(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 50, 100), (100, 100, 100, 100)]
    r = run(bars(rows), FREE, {0: [("buy", dict(qty=1))]})
    s = metrics.summarize(r)
    assert s["max_drawdown_usd"] <= -500            # 50 points x $10 underwater inside bar 2


# ---------------------------------------------------------------- execution details
def test_target_needs_trade_through_even_at_the_open():
    rows = [(100, 100, 100, 100), (100, 100, 100, 100), (104, 104, 103, 103.5), (103.5, 103.5, 103.5, 103.5)]
    t = run(bars(rows), FUT1.with_costs(slippage_ticks=0), {0: [("buy", dict(qty=1, tp=104))]})["trades"].iloc[0]
    assert t.exit_reason == "end_of_data"           # 104 only touched, never traded through


def test_stop_never_fills_above_the_best_bid():
    rows = [(100, 100, 100, 100)] * 3
    ba = {"o": ([99.0, 99.0, 99.0], [100.1, 100.1, 100.1]), "h": ([99.1, 99.1, 99.1], [100.2, 100.2, 100.2]),
          "l": ([98.9, 98.9, 98.9], [100.0, 100.0, 100.0]), "c": ([99.0, 99.0, 99.0], [100.1, 100.1, 100.1])}
    t = run(bars(rows, bidask=ba), CFD, {0: [("buy", dict(qty=1, sl=99.5))]})["trades"].iloc[0]
    assert t.exit_px <= 99.1                        # bid never reached 99.5


def test_forced_final_exit_pays_slippage():
    rows = [(100, 100, 100, 100)] * 3
    t = run(bars(rows), FUT1, {0: [("buy", dict(qty=1))]})["trades"].iloc[0]
    assert t.exit_reason == "end_of_data" and t.exit_px == 100 - 0.25


def test_futures_quantity_is_whole_contracts():
    rows = [(100, 100, 100, 100)] * 3
    t = run(bars(rows), FREE, {0: [("buy", dict(qty=1.5))]})["trades"].iloc[0]
    assert t.qty == 1


# ---------------------------------------------------------------- input / report checks
def test_short_window_stress_report_does_not_crash():
    t = pd.DataFrame({"pnl": [10.0, -5.0], "exit_tday": np.array(["2024-01-03", "2024-01-10"], dtype="datetime64[D]")})
    out = stress.worst_stretches(t, np.array(["2024-01-02", "2024-01-03", "2024-01-10"], dtype="datetime64[D]"), Settings(), FREE)
    assert out is not None


def test_dataset_must_match_instrument():
    import robust
    with pytest.raises(SystemExit):
        robust.check_dataset("XAUUSD", "NQ")
    robust.check_dataset("MNQ", "NQ")


def test_orb_rejects_range_not_a_multiple_of_bar_size():
    from engine.loader import load_strategy
    ORB = load_strategy(str(ROOT / "strategies/orb.py"))
    df = data.resample(bars([(100, 100, 100, 100)] * 40), 15)
    with pytest.raises(ValueError):
        ORB(or_minutes=10).prepare(df)


def test_daily_monte_carlo_rejects_skip():
    with pytest.raises(ValueError):
        montecarlo.simulate(np.array([1.0, -1, 2]), 1000, n_sims=10, method="daily", skip_pct=10)


def test_compare_runs_exits_nonzero_when_different(tmp_path):
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    cols = "entry_time,exit_time,side,qty,entry_px,exit_px,pnl,costs,exit_reason\n"
    a.write_text(cols + "t1,t2,long,1,100,101,10,0,tp\n")
    b.write_text(cols + "t1,t2,long,1,100,101.0000001,10,0,tp\n")
    r = subprocess.run([sys.executable, str(ROOT / "tools/compare_runs.py"), str(a), str(b)], capture_output=True)
    assert r.returncode != 0


def test_drawdown_from_an_intraday_peak_is_reported():
    # +50 points by bar 2's close, all given back by bar 3's low, flat at the day's close: $500 drawdown
    rows = [(100, 100, 100, 100), (100, 100, 100, 100), (100, 150, 100, 150), (150, 150, 100, 100), (100, 100, 100, 100)]
    r = run(bars(rows), FREE, {0: [("buy", dict(qty=1))]})
    assert metrics.summarize(r)["max_drawdown_usd"] <= -500


# ================================================================ follow-up findings (second review)
def test_reverse_slices_cannot_read_future_bars():
    rng = np.random.default_rng(1)
    p = 100 + np.cumsum(rng.normal(0, 1, 300))
    df = bars([(x, x + 0.5, x - 0.5, x) for x in p])

    class ReverseSlicePeek(Strategy):
        def on_bar(self, i):
            d, b = self.d, self.broker
            if i + 2 < len(d["c"]) and b.flat and d["c"][i + 2:i:-1][0] > d["c"][i]:
                b.buy(qty=1)
            elif not b.flat:
                b.close()
    assert check_lookahead(ReverseSlicePeek(), df, FREE) != []


def test_drawdown_from_an_opening_peak_is_reported():
    # long 1 @ 100 ($10/pt); next bar OPENS at 150 (observable peak), falls to 100 and closes there: $500 given back
    rows = [(100, 100, 100, 100), (100, 100, 100, 100), (150, 150, 100, 100), (100, 100, 100, 100)]
    r = run(bars(rows), FREE, {0: [("buy", dict(qty=1))]})
    assert metrics.summarize(r)["max_drawdown_usd"] <= -500


@pytest.mark.parametrize("close_ask", [100.10, 101.00])
def test_spread_stress_prices_the_open_from_the_opening_quote(close_ask):
    rows = [(100, 100, 100, 100)] * 3
    ba = {"o": ([99.9] * 3, [100.1] * 3), "h": ([99.9] * 3, [close_ask] * 3),
          "l": ([99.9] * 3, [100.1] * 3), "c": ([99.9] * 3, [close_ask] * 3)}
    t = run(bars(rows, bidask=ba), CFD, {0: [("buy", dict(qty=1))]}, spread_mult=2)["trades"].iloc[0]
    assert t.entry_px == pytest.approx(100.2)       # mid 100 + 2 x the OPENING half-spread (0.1)


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_futures_limit_entry_needs_trade_through_at_the_open(side):
    rows = [(101, 101, 101, 101), (100, 100, 100, 100), (100, 100, 100, 100)] if side == "buy" else \
           [(99, 99, 99, 99), (100, 100, 100, 100), (100, 100, 100, 100)]
    r = run(bars(rows), FUT1.with_costs(slippage_ticks=0), {0: [(side, dict(kind="limit", price=100, qty=1))]})
    assert len(r["trades"]) == 0                    # 100 only touched, never traded through by a tick


def test_resampled_bars_keep_one_bar_per_bucket_and_flag_a_roll_inside():
    rows = [(100 + k, 100 + k, 100 + k, 100 + k) for k in range(10)]
    r = data.resample(bars(rows, contracts=["A"] * 7 + ["B"] * 3), 5)   # switch at minute 7, inside bar 2
    assert len(r) == 2 and list(r.roll) == [False, False] and list(r.roll_inside) == [False, True]
    r2 = data.resample(bars(rows, contracts=["A"] * 5 + ["B"] * 5), 5)  # switch exactly on a bar boundary
    assert list(r2.roll) == [False, True] and list(r2.roll_inside) == [False, False]


def test_guard_blocks_every_slice_that_reaches_a_later_bar():
    from engine.core import FutureReadError, _Guarded

    class B:
        i = 0
    seq = list(range(10))
    g = _Guarded(seq, B())
    for bad in (slice(2, 0, -1), slice(None, None, -1), slice(-1, None), slice(None, -1), slice(0, 5), slice(1, None)):
        with pytest.raises(FutureReadError):
            g[bad]
    assert g[0] == 0 and g[0:1] == [0] and g[:1] == [0]
    B.i = 5
    assert g[5:2:-1] == [5, 4, 3] and g[3:6] == [3, 4, 5]


def test_one_second_replay_follows_the_second_by_second_path(monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import verify_orb_fills_1s as v
    secs = pd.DataFrame({"ts": [0, 1, 2, 3], "o": [100, 101, 104, 99], "h": [101, 105, 104, 99],
                         "l": [100, 101, 98, 99], "c": [101, 104, 99, 99]})
    monkeypatch.setattr(v, "seconds", lambda t0, t1, c: secs[(secs.ts >= t0) & (secs.ts < t1)])
    # long @100, stop 98, target 104 (+1 tick through): the target (second 1) comes before the stop (second 2)
    r = v.replay_trade(1, 0, 100.0, 98.0, 104.0, 1, 10.0, 0.0, 0.0, 0.25, 999, "X")
    assert r[0] == "tp" and r[3] == pytest.approx(40.0)
    # stop 101 is touched inside the entry second: cannot tell, flagged as same-second
    r = v.replay_trade(1, 0, 100.5, 100.0, 110.0, 1, 10.0, 0.0, 0.0, 0.25, 999, "X")
    assert r[4] is True


# ================================================================ third review
def test_broker_data_is_guarded_too():
    rng = np.random.default_rng(2)
    p = 100 + np.cumsum(rng.normal(0, 1, 300))
    df = bars([(x, x + 0.5, x - 0.5, x) for x in p])

    class BrokerPeek(Strategy):
        def on_bar(self, i):
            b = self.broker
            if i + 2 < len(b.d["c"]) and b.flat and b.d["c"][i + 2] > b.d["c"][i] + 0.5:
                b.buy(qty=1)
            elif not b.flat:
                b.close()
    problems = check_lookahead(BrokerPeek(), df, FREE)
    assert any("later bar" in x for x in problems)

    class HistoryOnly(Strategy):          # current and past reads through the broker are fine
        def on_bar(self, i):
            b = self.broker
            if i >= 2 and b.flat and b.d["c"][i] > b.d["c"][i - 2]:
                b.buy(qty=1)
            elif not b.flat:
                b.close()
    assert check_lookahead(HistoryOnly(), df, FREE) == []


def test_drawdown_inside_the_exit_bar_is_reported():
    # long @100 ($10/pt), target 110; the exit bar dips to 50 before the target (OHLC can't tell the order:
    # the pessimistic assumption counts the dip)
    rows = [(100, 100, 100, 100), (100, 100, 100, 100), (100, 111, 50, 105), (105, 105, 105, 105)]
    r = run(bars(rows), FREE, {0: [("buy", dict(qty=1, tp=110))]})
    assert r["trades"].iloc[0].exit_reason == "tp"
    assert metrics.summarize(r)["max_drawdown_usd"] <= -500


def test_drawdown_percent_uses_the_peak_before_the_trough():
    # equity 50,000 -> 51,000 (close) -> 50,000 (low) -> 51,500 later the same day
    rows = [(100, 100, 100, 100), (100, 100, 100, 100), (200, 200, 200, 200), (200, 200, 100, 100),
            (100, 250, 100, 250), (250, 250, 250, 250)]
    r = run(bars(rows), FREE, {0: [("buy", dict(qty=1))]})
    s = metrics.summarize(r)
    assert s["max_drawdown_usd"] == pytest.approx(-1000)
    assert s["max_drawdown_pct"] == pytest.approx(-1000 / 51000 * 100, abs=0.005)


@pytest.mark.parametrize("case,expected", [("close_before_switch", 0), ("hold_through_switch", 1),
                                           ("hold_to_final_bar", 1), ("open_after_switch", 0)])
def test_resampled_roll_costs_match_one_minute(case, expected):
    # 12 one-minute bars, contract switch at minute 8 (inside the 3-minute bucket 6-8)
    rows = [(100.0, 100.0, 100.0, 100.0)] * 12
    df1 = bars(rows, contracts=["A"] * 8 + ["B"] * 4)
    df3 = data.resample(df1, 3)
    t0 = int(df1.ts.iloc[0])
    m = lambda k: t0 + 60 * k                                     # noqa: E731
    # (decide-to-enter minute, decide-to-exit minute): fills happen at the next bar's open
    plan = {"close_before_switch": (m(2), m(5)), "hold_through_switch": (m(2), m(8)),
            "hold_to_final_bar": (m(2), None), "open_after_switch": (m(8), None)}[case]

    class Plan(Strategy):
        def on_bar(self, i):
            last_min = self.last_min[i]          # decisions are made when the bar's last minute closes
            if last_min == plan[0]:
                self.broker.buy(qty=1)
            if plan[1] is not None and last_min == plan[1]:
                self.broker.close()

    def run_on(df, tf):
        s = Plan()
        # the last 1-minute timestamp inside each bar (when the bar's decision is made)
        nxt = np.r_[df.ts.to_numpy()[1:], int(df1.ts.iloc[-1]) + 60]
        s.last_min = (nxt - 60).tolist()
        return Engine(df, FREE.with_costs(commission=1.0), s, Settings()).run()["trades"]
    t1, t3 = run_on(df1, 1), run_on(df3, 3)
    assert int(t1.rolls.sum()) == expected
    assert int(t3.rolls.sum()) == expected and t3.costs.sum() == pytest.approx(t1.costs.sum())


def test_verifier_tie_is_unresolved_not_agreement(monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import verify_orb_fills_1s as v
    assert v.outcome(agree=True, unresolved=True) == "unresolved"
    assert v.outcome(agree=False, unresolved=False) == "disagree"
    assert v.outcome(agree=True, unresolved=False) == "agree"


@pytest.mark.skipif(not (ROOT.parent / "DATA").exists(), reason="T9/DATA not mounted")
def test_verifier_zero_trade_run_succeeds(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "tools/verify_orb_fills_1s.py"), "--start", "2024-01-02",
                        "--end", "2024-01-04", "--set", "min_range=1000000000"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]
    assert "0 trades" in r.stdout


def test_verifier_marks_missing_second_data_unresolved(monkeypatch):
    sys.path.insert(0, str(ROOT / "tools"))
    import verify_orb_fills_1s as v
    monkeypatch.setattr(v, "seconds", lambda t0, t1, c: pd.DataFrame(columns=["ts", "o", "h", "l", "c"]))
    assert v.replay_trade(1, 0, 100.0, 98.0, 104.0, 1, 10.0, 0.0, 0.0, 0.25, 999, "X") is None
    assert v.first_second(pd.DataFrame(columns=["ts", "o", "h", "l", "c"]), 1, 100.0, "stop") is None


def test_stress_volatility_split_handles_split_daily_bars(monkeypatch):
    # futures daily bars can be split at a contract switch: two bars on one trading day must not crash
    days = np.array(["2024-01-03", "2024-01-04", "2024-01-05"], dtype="datetime64[D]")
    trades = pd.DataFrame({"pnl": [10.0, -5.0], "exit_tday": days[[0, 2]]})
    daily = pd.DataFrame({"tday": days, "equity": [100010.0, 100010, 100005], "start_equity": 100000.0})

    def fake(jobs, workers=None, progress=True):
        base = {"summary": {"trades": 2, "net_pnl": 5.0}, "trades": trades, "daily": daily, "days": days}
        return [base] + [{"summary": {"trades": 2, "net_pnl": 5.0}} for _ in jobs[1:]]
    monkeypatch.setattr(stress, "run_many", fake)
    bars_ = pd.DataFrame({"tday": np.array(["2024-01-03", "2024-01-03", "2024-01-04", "2024-01-05"], dtype="datetime64[D]"),
                          "h": [101.0, 103, 102, 101], "l": [99.0, 100, 98, 100], "c": [100.0, 102, 101, 100]})
    out = stress.run(Job("s.py", "GC", 1440, FREE, Settings()), bars_)
    assert out["volatility_regime"].trades.sum() == 2


def test_notional_sizing_uses_the_real_futures_price():
    # back-adjusted price 150 (= real 100 + 50 adjustment): $10,000 of contract value at $1/pt = 100 contracts, not 66
    rows = [(150, 150, 150, 150)] * 4
    df = bars(rows)
    df["adj"] = 50.0
    one = Instrument("ONE", point_value=1.0, tick=0.25, commission=0.0, slippage_ticks=0, qty_step=1)
    t = run(df, one, {0: [("buy", dict(notional_usd=10_000))]})["trades"].iloc[0]
    assert t.qty == 100
