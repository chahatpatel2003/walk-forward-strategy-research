"""Regression tests for findings.md, section "Verification after the sixth revision"."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings, Strategy, data, metrics, stress, walkforward  # noqa: E402
from engine.parallel import Job  # noqa: E402
from test_engine import FREE, bars  # noqa: E402


# 1 ---------------------------------------------------------------------------------------------------
def test_pairs_engine_enforces_the_account_limit():
    from engine.pairs import PairsEngine
    from test_pairs import A, B, pair_frame
    # long spread: A collapses 2000 -> 800 (-$60k on 5 contracts x $10/pt... sized by notional) then recovers
    a = [2000, 2000, 2000, 800, 800, 2000, 2000, 2000]
    b = [1990] * 8
    df = pair_frame(a, b)

    class OpenWhenFlat(Strategy):
        params = dict(notional=500_000.0)      # 25 contracts: a $1,200 drop costs $300,000

        def on_bar(self, i):
            if self.broker.flat:
                self.broker.open(+1, 1.0, "long_spread")
    r = PairsEngine(df, A, B, OpenWhenFlat(), Settings(capital=50_000, account_constrained=True)).run()
    t = r["trades"]
    assert len(t) == 1 and t.iloc[0].exit_reason == "capital_exhausted"
    assert metrics.summarize(r)["capital_exhausted_on"] is not None
    assert r["notes"].get("orders_refused_capital_exhausted", 0) > 0


# 2 ---------------------------------------------------------------------------------------------------
def test_walkforward_stays_stopped_after_a_breach_even_if_balance_recovers(monkeypatch):
    seen = []

    def fake_run_many(jobs, workers=None, progress=True):
        out = []
        for j in jobs:
            seen.append(j)
            notes = {}
            if j.summary_only:
                out.append({"summary": {"trades": 50, "net_pnl": 1.0, "sharpe_daily_ann": 1.0}, "tag": j.tag})
                continue
            first = len([x for x in seen if not x.summary_only]) == 1
            if first:
                notes = {"capital_exhausted_ts": 123}
            d = pd.DataFrame({"tday": np.array([j.start], dtype="datetime64[D]"), "equity_open": [j.settings.capital],
                              "equity_low": [-10.0], "equity": [20_000.0], "start_equity": [j.settings.capital]})
            out.append({"summary": {"trades": 1, "net_pnl": 1.0, "notes": notes, "capital_exhausted_on": j.start if first else None},
                        "trades": pd.DataFrame(), "bars": d, "daily": d, "days": np.array([j.start], dtype="datetime64[D]"),
                        "tag": j.tag})
        return out
    monkeypatch.setattr(walkforward, "run_many", fake_run_many)
    base = Job("s.py", "NQ", 1, FREE, Settings(capital=50_000, account_constrained=True))
    wf = walkforward.run(base, {"x": [1]}, pd.bdate_range("2020-01-01", "2021-12-31").values.astype("datetime64[D]"), 6, 3)
    oos = [f for f in wf["folds"] if "oos_net_pnl" in f]
    skipped = [f for f in wf["folds"] if f.get("oos_skipped") == "capital_exhausted"]
    assert len(oos) == 1 and len(skipped) == len(wf["folds"]) - 1


# 3 ---------------------------------------------------------------------------------------------------
def test_forced_liquidation_happens_at_the_next_open_whatever_the_delay():
    # bar 3 opens at 100 and closes at 40 (breach at its CLOSE); next open (bar 4) = 20, then 80.
    # (A gap straight to 40 at the open would be a breach AT that open since the ninth review.)
    df = bars([(100, 100, 100, 100)] * 3 + [(100, 100, 40, 40), (20, 20, 20, 20), (80, 80, 80, 80), (80, 80, 80, 80)])

    class BuyOnce(Strategy):
        def on_bar(self, i):
            if i == 0:
                self.broker.buy(qty=100)
    t = Engine(df, FREE, BuyOnce(), Settings(capital=50_000, account_constrained=True, delay_bars=1)).run()["trades"].iloc[0]
    assert t.exit_reason == "capital_exhausted" and t.exit_px == 20


# 4 ---------------------------------------------------------------------------------------------------
def test_stress_table_shows_a_breach_even_if_the_scenario_recovers(monkeypatch):
    def fake(jobs, workers=None, progress=True):
        base = {"summary": {"trades": 2, "net_pnl": 5.0, "account_model": "constrained", "capital_exhausted_on": None,
                            "notes": {}}, "trades": pd.DataFrame(), "daily": None, "days": np.array([], dtype="datetime64[D]")}
        broke = {"summary": {"trades": 2, "net_pnl": -99_997.25, "account_model": "constrained",
                             "capital_exhausted_on": "2022-10-13", "notes": {"orders_refused_capital_exhausted": 31074}}}
        return [base] + [broke for _ in jobs[1:]]
    monkeypatch.setattr(stress, "run_many", fake)
    out = stress.run(Job("s.py", "GC", 15, FREE, Settings(account_constrained=True)))
    table = out["scenarios"]
    assert {"account_model", "capital_exhausted_on", "orders_refused"} <= set(table.columns)
    assert (table.capital_exhausted_on.iloc[1:] == "2022-10-13").all() and (table.orders_refused.iloc[1:] == 31074).all()
