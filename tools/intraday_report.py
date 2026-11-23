"""INTRADAY_STUDY_RESULTS.md from results/INTRADAY_STUDY/rows.csv and the run folders: results by bar size, every
strategy x bar size, costs per trade, the runs that passed every check, an overnight check of every out-of-sample
trade, and the passing runs together on ONE $10,000 account risking 2% of the balance per trade (compounding).
    python tools/intraday_report.py
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import single_account as sa  # noqa: E402
from engine import get_instrument  # noqa: E402
from photo_report_tables import NAMES, robust_mask, survived  # noqa: E402
from timeframe_costs import friction  # noqa: E402
from timeframe_portfolio import UNDERLYING, wf_dir  # noqa: E402

OUT = ROOT / "results" / "INTRADAY_STUDY"
LAB = {"1m": "1-min", "5m": "5-min", "15m": "15-min", "60m": "1-hour"}
ORDER = ["1m", "5m", "15m", "60m"]
CAPITAL, RISK, K, ATR_LEN, CAP = 10_000.0, 2.0, 2.0, 14, 5.0


def months(period):
    if not isinstance(period, str) or "->" not in period:
        return np.nan
    a, b = [pd.Timestamp(x.strip()) for x in period.split("->")]
    return max((b - a).days / 30.4375, 1e-9)


def load():
    r = pd.read_csv(OUT / "rows.csv")
    r = r[r.error.isna()].copy()
    r["code"] = r.strategy.str[:3].str.upper()
    r["trades_per_month"] = r.trades_per_year / 12
    r["oos_trades_per_month"] = r.wf_oos_trades / r.wf_oos_period.map(months)
    r["years"] = r.period.map(months) / 12
    r["robust"] = robust_mask(r)
    r["survived"] = survived(r)
    return r


def ledger(report):
    try:
        return pd.read_csv(wf_dir(report) / "walkforward_oos_trades.csv")
    except (SystemExit, FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def money(v):
    return "—" if v is None or v != v else (f"−${abs(v):,.0f}" if v < 0 else f"${v:,.0f}")


def main():
    r = load()
    allr = pd.read_csv(OUT / "rows.csv")
    L = [f"# Intraday study: the photo strategies, flat every day by 15:55 ET",
         "",
         f"*Generated {date.today():%B %d, %Y} by `tools/intraday_report.py` from `results/INTRADAY_STUDY/rows.csv` "
         f"({len(allr)} runs, {int(allr.error.notna().sum())} errors).*",
         "",
         "## How it was run",
         "",
         "* **Same strategies, same entry and exit rules** as the daily and timeframe studies, on 1-, 5-, 15-minute and "
         "1-hour bars of the **New York cash session (09:30–16:00)**. Lengths stay in bars; thresholds written as a % of "
         "price are scaled by √(bar length ÷ original bar length), as in the timeframe study.",
         "* **Intraday:** every open position is closed so the exit fills at the last bar starting by 15:55 (12:55 on half "
         "days): 15:55 on 1- and 5-minute bars, 15:45 on 15-minute, 15:00 on 1-hour. No new entry from that point; "
         "orders expire at the end of the day. Nothing is held overnight (checked on every trade below).",
         "* Strategies: A01–A07, A11, A12. A08–A10 decide once a week or month (can't be intraday); A13 is intraday "
         "already (timeframe study); the B01 pair is not included.",
         "* **Same pipeline:** full history, parameter grid with the look-ahead gate, walk-forward (18 months in-sample → 6 "
         "out-of-sample), Monte Carlo, 9 stress scenarios, 13-item checklist; $100,000 of contract value per trade, costs "
         "as before. **\"Passed every check\"** is the same rule as the other studies.",
         ""]
    # 1. by bar size
    g = r.groupby("bars")
    by = pd.DataFrame({"bars": [LAB[b] for b in ORDER if b in g.groups]})
    keys = [b for b in ORDER if b in g.groups]
    by["runs"] = [len(g.get_group(b)) for b in keys]
    by["median trades / month"] = [round(g.get_group(b).trades_per_month.median(), 1) for b in keys]
    by["profitable full history"] = [int((g.get_group(b).net > 0).sum()) for b in keys]
    by["profitable out-of-sample"] = [int((g.get_group(b).wf_oos_net > 0).sum()) for b in keys]
    by["passed every check"] = [int(g.get_group(b).robust.sum()) for b in keys]
    by["hit $0 somewhere"] = [int((~g.get_group(b).survived).sum()) for b in keys]
    by["median win %"] = [round(g.get_group(b).win_pct.median(), 1) for b in keys]
    by["median PF"] = [round(g.get_group(b).pf.median(), 2) for b in keys]
    L += ["## 1. Results by bar size", "", by.to_markdown(index=False), ""]
    # 2. grid
    cells = []
    for code, d in r.groupby("code"):
        row = {"strategy": f"{code} {NAMES.get(code, '')}"}
        for b in ORDER:
            x = d[d.bars == b]
            row[LAB[b]] = f"{int(x.robust.sum())}/{len(x)} · {x.trades_per_month.median():.1f}/mo · OOS+ {int((x.wf_oos_net > 0).sum())}" if len(x) else "-"
        cells.append(row)
    L += ["## 2. Every strategy on every bar size", "",
          "Cells: runs that passed every check / runs · median trades per month · runs profitable out-of-sample.", "",
          pd.DataFrame(cells).to_markdown(index=False), ""]
    # 3. costs + overnight check
    rows, overnight, n_tr = [], 0, 0
    for _, s in r.iterrows():
        t = ledger(s.report)
        if not len(t):
            continue
        et = pd.to_datetime(t.entry_time, utc=True).dt.tz_convert("America/New_York").dt.date
        xt = pd.to_datetime(t.exit_time, utc=True).dt.tz_convert("America/New_York").dt.date
        overnight += int((et != xt).sum()); n_tr += len(t)
        gap_exits = globals().setdefault("_gap", [0]); gap_exits[0] += int(((et != xt) & (t.exit_reason == "session_gap_exit")).sum())
        fr = friction(t, get_instrument(s.market))
        rows.append({"bars": s.bars, "market": s.market, "trades": len(t), "before": (t.pnl + fr).sum(), "fr": fr.sum(), "after": t.pnl.sum()})
    c = pd.DataFrame(rows)
    ct = []
    for b in ORDER:
        x = c[c.bars == b]
        if len(x):
            n = x.trades.sum()
            ct.append({"bars": LAB[b], "runs": len(x), "OOS trades": int(n), "avg trade before costs $": round(x.before.sum() / n, 2),
                       "avg costs per trade $": round(x.fr.sum() / n, 2), "avg trade after costs $": round(x.after.sum() / n, 2),
                       "runs profitable before costs": int((x.before > 0).sum()), "runs profitable after costs": int((x.after > 0).sum())})
    L += ["## 3. Costs per trade (every out-of-sample trade)", "", pd.DataFrame(ct).to_markdown(index=False), "",
          f"**Overnight check:** {n_tr:,} out-of-sample trades; **{overnight}** of them exit on a different New York "
          f"date than they entered, and {globals().get('_gap', [0])[0]} of those are `session_gap_exit`: days where the data "
          "has no bar left before 15:55 (missing afternoon data), so the engine closes the position at the next session's "
          "first bar. No position is held overnight by choice.", ""]
    # 4. runs that passed
    rb = r[r.robust].sort_values(["bars", "wf_oos_net"], ascending=[True, False])
    t = pd.DataFrame({"strategy": rb.code + " " + rb.code.map(NAMES).fillna(""), "market": rb.market, "bars": rb.bars.map(LAB),
                      "years": rb.years.round(1), "trades": rb.trades.astype(int), "trades/mo": rb.trades_per_month.round(1),
                      "win %": rb.win_pct.round(1), "RR": rb.payoff_ratio.round(2), "PF": rb.pf.round(2), "net $": rb.net.round(0),
                      "max DD $": rb.max_dd.round(0), "OOS trades": rb.wf_oos_trades, "OOS net $": rb.wf_oos_net.round(0),
                      "OOS PF": rb.wf_oos_pf.round(2), "MC loss %": rb.mc_prob_loss_pct.round(1)})
    L += [f"## 4. Runs that passed every check ({len(rb)} of {len(r)})", "",
          t.to_markdown(index=False) if len(t) else "(none)", ""]
    near = r[(r.wf_oos_net > 0) & ~r.robust].sort_values("wf_oos_net", ascending=False).head(15)
    nt = pd.DataFrame({"strategy": near.code, "market": near.market, "bars": near.bars.map(LAB), "trades/mo": near.trades_per_month.round(1),
                       "win %": near.win_pct.round(1), "RR": near.payoff_ratio.round(2), "OOS net $": near.wf_oos_net.round(0),
                       "OOS PF": near.wf_oos_pf.round(2), "MC loss %": near.mc_prob_loss_pct.round(1),
                       "worst stress $": near.stress_worst_net.round(0), "checks not passed": (near.checks_total - near.checks_passed).astype(int)})
    L += ["### Profitable out-of-sample but not passing every check (top 15 by OOS profit)", "",
          nt.to_markdown(index=False) if len(nt) else "(none)", ""]
    # 5. one account
    acc = {}
    for label, pool in (("passed every check", r[r.robust]), ("profitable out-of-sample (looser)", r[(r.wf_oos_net > 0) & (r.wf_oos_pf >= 1.1)])):
        if not len(pool):
            continue
        x = pool.assign(underlying=pool.market.map(UNDERLYING)).sort_values("oos_trades_per_month", ascending=False)
        x = x.drop_duplicates(["code", "underlying"])
        runs = []
        for _, s in x.iterrows():
            tr = ledger(s.report)
            if not len(tr):
                continue
            tr["stop_dist"] = sa.stop_distance(tr, s.market, int(s.bars[:-1]), "rth", K, ATR_LEN)
            runs.append({"name": f"{s.code} {s.market} {LAB[s.bars]}", "market": s.market, "trades": tr})
        if not runs:
            continue
        for cap in (None, CAP):
            o = sa.simulate(runs, CAPITAL, RISK, max_lev=cap)
            acc[f"{label}, {'no size cap' if cap is None else f'position ≤ {cap:g}× balance'}"] = (o, [x["name"] for x in runs])
    if acc:
        rows_ = [("Runs", lambda o, n: f"{len(n)}"), ("Period", lambda o, n: f"{o['start']} → {o['end']}"),
                 ("Trades taken / skipped", lambda o, n: f"{o['trades_taken']:,} / {sum(o['skipped'].values()):,}"),
                 ("Trades per month", lambda o, n: f"{o['trades_per_month']}"),
                 ("$10,000 →", lambda o, n: f"**{money(o['final_equity'])}**"),
                 ("Per year", lambda o, n: f"{o['cagr_pct']}%" if o["cagr_pct"] is not None else "—"),
                 ("Max drawdown (daily closes)", lambda o, n: f"{money(o['max_dd_usd'])} ({o['max_dd_pct']}%)"),
                 ("Win rate", lambda o, n: f"{o['win_pct']}%"), ("Profit factor", lambda o, n: f"{o['profit_factor']}"),
                 ("Average win / loss", lambda o, n: f"+{o['avg_win_r']}R / {o['avg_loss_r']}R"),
                 ("Worst trade", lambda o, n: f"{o['worst_trade_r']}R"),
                 ("Profitable months", lambda o, n: o["profitable_months"]),
                 ("Most positions open at once", lambda o, n: f"{o['max_open_positions']}"),
                 ("Max contract value ÷ balance", lambda o, n: f"{o['max_leverage_any_time']}×"),
                 ("Account hit $0", lambda o, n: o["account_hit_zero_on"] or "no")]
        ks = list(acc)
        L += ["## 5. On one $10,000 account, 2% risk per trade, compounding", "",
              "One run per strategy and underlying market (the one with the most out-of-sample trades per month), every "
              "out-of-sample trade, sized at 2% of the balance ÷ (2 × ATR(14) of the run's bars × point value), rounded "
              "down to whole MNQ/MGC contracts or 0.01 lots (skipped if one contract is too much). No hard stop: the "
              "strategies' own exits and the 15:55 close. Because a 2 × ATR distance on minute bars is small, the same "
              f"account is also shown with each position capped at {CAP:g}× the balance in contract value.", "",
              "| | " + " | ".join(ks) + " |", "|---" * (len(ks) + 1) + "|"]
        L += [f"| {nm} | " + " | ".join(f(acc[k][0]["summary"], acc[k][1]) for k in ks) + " |" for nm, f in rows_]
        for k in ks:
            pr = acc[k][0]["per_run"].reset_index()
            L += ["", f"**{k}**, per strategy:", "", pr.round(2).to_markdown(index=False)]
        (OUT / "account.json").write_text(json.dumps({k: {"summary": v[0]["summary"], "runs": v[1]} for k, v in acc.items()},
                                                     indent=1, default=str))
    # 6. all runs
    a = r.sort_values(["code", "bars", "market"])[["code", "market", "bars", "trades", "trades_per_month", "win_pct", "payoff_ratio",
                                                   "pf", "net", "max_dd", "wf_oos_trades", "wf_oos_net", "wf_oos_pf",
                                                   "mc_prob_loss_pct", "stress_worst_net", "checks_passed", "checks_total", "robust"]].copy()
    a["bars"] = a.bars.map(LAB)
    L += ["", "## 6. Every run", "", a.round(2).to_markdown(index=False), "",
          "## Reproduce", "", "```", "cd /Volumes/T9/BACKTESTING",
          "~/.venvs/t9-backtesting/bin/python intraday_study.py --workers 4", "~/.venvs/t9-backtesting/bin/python tools/intraday_report.py", "```"]
    (ROOT / "INTRADAY_STUDY_RESULTS.md").write_text("\n".join(L))
    print("INTRADAY_STUDY_RESULTS.md written")


if __name__ == "__main__":
    main()
