"""Export the data files behind the "Trading System Performance Report" dashboard (results/DASHBOARD/*.json). Each file
is {rows, meta}; meta carries this script's own text, so every number can be traced to the code that made it.

The shortlist is the 8 runs recommended in the chat (one version per strategy and market, current markets only), all
of which passed every check in the timeframe study (results/TIMEFRAME_STUDY/rows.csv).
    python tools/export_dashboard_data.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import single_account as sa  # noqa: E402
from photo_report_tables import NAMES, robust_mask  # noqa: E402
from timeframe_portfolio import wf_dir  # noqa: E402
from timeframe_report import TF_LABEL, load  # noqa: E402

OUT = ROOT / "results" / "DASHBOARD"
SHORTLIST = [("a01_rsi_ema_vwap", "MNQ", "rth", "240m"), ("a07_mfi_reversal", "MNQ", "rth", "1440m"),
             ("a11_time_series_momentum", "MNQ", "full", "240m"), ("a11_time_series_momentum", "XAUUSD", "full", "240m"),
             ("a07_mfi_reversal", "XAUUSD", "rth", "240m"), ("a09_turn_of_month", "XAUUSD", "rth", "1440m"),
             ("a12_volatility_squeeze_breakout", "XAUUSD", "full", "60m"), ("a01_rsi_ema_vwap", "MGC", "rth", "1440m")]
CAPITAL, RISK = 10_000.0, 2.0
CODE = Path(__file__).read_text()


def write(name, rows, inputs):
    meta = [{"label": "export_dashboard_data.py", "value": CODE, "type": "code", "lang": "python"},
            {"label": "Input", "value": inputs}]
    (OUT / name).write_text(json.dumps({"rows": rows, "meta": meta}, default=str, allow_nan=False))


def clean(v):
    if isinstance(v, (np.floating, float)):
        return None if not np.isfinite(v) else round(float(v), 4)
    if isinstance(v, np.integer):
        return int(v)
    return v


def label(s):
    return f"{s.code} {s.market} {'cash' if s.session == 'rth' else 'full'} {TF_LABEL[s.bars]}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    r = load()
    key = r.set_index(["strategy", "market", "session", "bars"])
    sel = key.loc[SHORTLIST].reset_index()
    sel["code"] = sel.strategy.str[:3].str.upper()
    stop = pd.read_csv(ROOT / "results/SINGLE_ACCOUNT/stop_rows.csv")
    stop["robust"] = robust_mask(stop)
    stop_ok = set(map(tuple, stop[stop.robust][["strategy", "market", "session", "bars"]].to_numpy()))
    # 1. shortlist stats
    rows = []
    for s in sel.itertuples():
        a, b = [pd.Timestamp(x.strip()) for x in s.period.split("->")]
        rows.append({k: clean(v) for k, v in {
            "run": label(s), "strategy": f"{s.code} {NAMES[s.code]}", "market": s.market,
            "session": "cash" if s.session == "rth" else "full", "bars": TF_LABEL[s.bars],
            "years": (b - a).days / 365.25, "trades": s.trades, "trades_per_month": s.trades_per_year / 12,
            "win_pct": s.win_pct, "rr": s.payoff_ratio, "pf": s.pf, "net": s.net, "max_dd": s.max_dd,
            "oos_period": s.wf_oos_period, "oos_trades": s.wf_oos_trades, "oos_net": s.wf_oos_net, "oos_pf": s.wf_oos_pf,
            "oos_max_dd": s.wf_oos_max_dd, "mc_loss_pct": s.mc_prob_loss_pct, "worst_stress_net": s.stress_worst_net,
            "worst_stress_scenario": s.stress_worst_scenario, "checks_passed": s.checks_passed, "checks_total": s.checks_total,
            "passes_with_hard_stop": "yes" if (s.strategy, s.market, s.session, s.bars) in stop_ok else "no"}.items()})
    write("shortlist.json", rows, "results/TIMEFRAME_STUDY/rows.csv; results/SINGLE_ACCOUNT/stop_rows.csv")
    # 2. out-of-sample equity of each run ($100,000 of contract value per trade), weekly
    eq = []
    for s in sel.itertuples():
        e = pd.read_csv(wf_dir(s.report) / "walkforward_oos_daily_equity.csv", parse_dates=["tday"]).set_index("tday").equity
        w = e.resample("W-FRI").last().dropna()
        eq += [{"date": d.strftime("%Y-%m-%d"), "run": label(s), "profit": round(float(v - 100_000.0), 2)} for d, v in w.items()]
    write("oos_equity.json", eq, "walkforward_oos_daily_equity.csv of each shortlisted run")
    # 3. one $10,000 account, 2% risk, compounding (2 x ATR(14) sizing, the strategies' own exits)
    runs = []
    for s in sel.itertuples():
        t = pd.read_csv(wf_dir(s.report) / "walkforward_oos_trades.csv")
        t["stop_dist"] = sa.stop_distance(t, s.market, int(s.bars[:-1]), s.session, 2.0, 14)
        runs.append({"name": label(s), "market": s.market, "trades": t})
    # from the first day every shortlisted run is in its out-of-sample period (latest walk-forward start) to the last
    # out-of-sample day (MGC's data ends earlier, 2025-12-31)
    starts = [pd.Timestamp(s.wf_oos_period.split("->")[0].strip()) for s in sel.itertuples()]
    ends = [pd.Timestamp(s.wf_oos_period.split("->")[1].strip()) for s in sel.itertuples()]
    o = sa.simulate(runs, CAPITAL, RISK, str(max(starts).date()), str(max(ends).date()))
    acct = o["equity"]
    write("account_equity.json", [{"date": d.strftime("%Y-%m-%d"), "equity": round(float(v), 2)} for d, v in acct.items()],
          "walkforward_oos_trades.csv of each shortlisted run; tools/single_account.py")
    m = acct.resample("ME").last()
    prev = m.shift(1).fillna(CAPITAL)
    write("account_monthly.json", [{"month": d.strftime("%Y-%m"), "return_pct": round(float((v / p - 1) * 100), 2),
                                    "equity": round(float(v), 2)} for d, v, p in zip(m.index, m, prev)],
          "account_equity.json, month-end values")
    sm = o["summary"]
    write("account_summary.json", [{k: clean(v) for k, v in {
        "start": sm["start"], "end": sm["end"], "months": sm["months"], "start_equity": CAPITAL, "final_equity": sm["final_equity"],
        "net": sm["net"], "return_pct": sm["return_pct"], "cagr_pct": sm["cagr_pct"], "max_dd_pct": sm["max_dd_pct"],
        "max_dd_usd": sm["max_dd_usd"], "trades_taken": sm["trades_taken"], "trades_offered": sm["trades_offered"],
        "trades_per_month": sm["trades_per_month"], "win_pct": sm["win_pct"], "profit_factor": sm["profit_factor"],
        "avg_win_r": sm["avg_win_r"], "avg_loss_r": sm["avg_loss_r"], "worst_trade_r": sm["worst_trade_r"],
        "profitable_months": sm["profitable_months"], "max_open_positions": sm["max_open_positions"],
        "max_leverage": sm["max_leverage_any_time"], "risk_pct": RISK}.items()}],
        "tools/single_account.py on the shortlisted runs")
    per = o["per_run"].reset_index()
    write("account_by_strategy.json", [{k: clean(v) for k, v in {"run": x.run, "trades_given": x.offered, "trades_taken": x.trades,
                                                                  "net": x.net, "win_pct": x.win_pct}.items()} for x in per.itertuples()],
          "tools/single_account.py on the shortlisted runs")
    # 4. every run that passed every check, and the studies behind it
    allp = r[r.robust].sort_values(["market", "wf_oos_net"], ascending=[True, False])
    write("all_passing.json", [{k: clean(v) for k, v in {
        "run": label(s), "market": s.market, "bars": TF_LABEL[s.bars], "trades_per_month": s.trades_per_year / 12,
        "win_pct": s.win_pct, "rr": s.payoff_ratio, "pf": s.pf, "oos_net": s.wf_oos_net, "oos_pf": s.wf_oos_pf,
        "max_dd": s.max_dd}.items()} for s in allp.itertuples()], "results/TIMEFRAME_STUDY/rows.csv")
    studies = []
    for name, f in (("Daily (photo study)", "results/PHOTO_STUDY/study_rows.csv"), ("5-min to daily (timeframe study)", "results/TIMEFRAME_STUDY/rows.csv"),
                    ("Intraday, flat by 15:55", "results/INTRADAY_STUDY/rows.csv")):
        x = pd.read_csv(ROOT / f)
        ok = x[x.error.isna()]
        studies.append({"study": name, "runs": int(len(x)), "errors": int(x.error.notna().sum()),
                        "profitable_oos": int((ok.wf_oos_net > 0).sum()), "passed_every_check": int(robust_mask(ok).sum())})
    write("studies.json", studies, "study_rows.csv, rows.csv of each study")
    print("wrote", sorted(p.name for p in OUT.glob("*.json")))


if __name__ == "__main__":
    main()
