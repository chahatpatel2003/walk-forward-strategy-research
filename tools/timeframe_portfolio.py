"""What several robust timeframe-study runs would have done TOGETHER, built only from their saved walk-forward
out-of-sample results (walkforward_oos_daily_equity.csv / walkforward_oos_trades.csv in each run folder).

Selection (decided before looking at the combined result, and NOT by profit):
  * only runs that passed all key checks (photo_report_tables.robust_mask);
  * one run per strategy and underlying (MNQ and NAS100 are both the Nasdaq-100, MGC and XAUUSD are both gold):
    the cash and full session, and the different bar sizes of one strategy on one underlying, mostly take the same
    trades, so counting them separately would inflate the trade count;
  * among those, the run with the most out-of-sample trades per month (the goal here is frequency).
Everything is measured on the dates covered by EVERY selected run's walk-forward fold schedule. A fold in which
the optimiser found no valid parameter set is part of that schedule and trades nothing (that is what following the
walk-forward would have done), so it counts as zero trades and zero P&L, not as missing.
Caveat printed with the tables: the runs were chosen among those that passed checks which include their
out-of-sample results, so this combined record is not a fresh hold-out test.

Two views of the same window are printed:
  * marked: the sum of each run's daily marked equity changes. Positions already open on the first day ("carried
    in") contribute their in-window P&L, but their entries are not counted as trades.
  * flat start: only trades ENTERED inside the window, each with its whole P&L, realised on its exit day.
Drawdowns are on daily closes. Positions open at once are counted from the bar timestamps of entries and exits (a
position is open from its entry bar to its exit bar); gross exposure is quantity x real (unadjusted) daily close x
point value, summed over open positions, per day.

    python tools/timeframe_portfolio.py > results/TIMEFRAME_STUDY/portfolio.md
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from timeframe_report import TF_LABEL, load  # noqa: E402

UNDERLYING = {"MNQ": "Nasdaq-100", "NAS100": "Nasdaq-100", "MGC": "gold", "XAUUSD": "gold"}
BOOKS = {"tradable now (MNQ + MGC + XAUUSD)": ("MNQ", "MGC", "XAUUSD"),
         "longest history (NAS100 + MGC)": ("NAS100", "MGC")}


def pick(r: pd.DataFrame, markets) -> pd.DataFrame:
    x = r[r.robust & r.market.isin(markets)].copy()
    x["underlying"] = x.market.map(UNDERLYING)
    x = x.sort_values(["oos_trades_per_month", "wf_oos_trades"], ascending=False)
    return x.drop_duplicates(["code", "underlying"]).sort_values(["underlying", "code"]).reset_index(drop=True)


def max_overlap(trades: dict) -> int:
    """Most positions open at the same moment, from entry/exit bar timestamps (an exit at the same timestamp as
    another run's entry happens first: exits are at the bar's open)."""
    ev = []
    for t in trades.values():
        ev += [(pd.Timestamp(x), 1) for x in t.entry_time] + [(pd.Timestamp(x), -1) for x in t.exit_time]
    ev.sort(key=lambda e: (e[0], e[1]))
    cur = best = 0
    for _, d in ev:
        cur += d
        best = max(best, cur)
    return best


def carried_in(trades: dict, start) -> int:
    """Positions already open when the window starts (entered before it, exited on or after its first day)."""
    start = pd.Timestamp(start)
    return int(sum(((pd.to_datetime(t.entry_tday) < start) & (pd.to_datetime(t.exit_tday) >= start)).sum()
                   for t in trades.values()))


_DAILY: dict = {}


def daily_bars(market: str) -> pd.DataFrame:
    if market not in _DAILY:
        sys.path.insert(0, str(ROOT))
        from engine import data, get_instrument
        inst = get_instrument(market)
        b = data.resample(data.load(inst.data_key), 1440, "full")
        g = b.groupby(b.tday.to_numpy().astype("datetime64[D]"))
        raw = (g.raw_c.last() if "raw_c" in b else g.c.last())
        adj = g.adj_open.first() if "adj_open" in b else pd.Series(0.0, index=raw.index)
        _DAILY[market] = pd.DataFrame({"raw_c": raw, "adj_open": adj, "pv": inst.point_value})
        _DAILY[market].index = pd.to_datetime(_DAILY[market].index)
    return _DAILY[market]


def wf_dir(report: str) -> Path:
    d = sorted(x for x in (ROOT / report).glob("*_walkforward_*") if x.is_dir() and not x.name.startswith("._"))
    if len(d) != 1:
        raise SystemExit(f"expected one walk-forward folder in {report}, found {len(d)}")
    return d[0]


def book(sel: pd.DataFrame, capital: float) -> dict:
    pnl, trades, spans, market = {}, {}, [], {}
    for _, s in sel.iterrows():
        d = wf_dir(s.report)
        eq = pd.read_csv(d / "walkforward_oos_daily_equity.csv", parse_dates=["tday"]).set_index("tday").equity
        name = f"{s.code} {s.market} {s.session} {TF_LABEL[s.bars]}"
        pnl[name] = eq.diff().fillna(eq.iloc[0] - capital)
        t = pd.read_csv(d / "walkforward_oos_trades.csv", parse_dates=["entry_tday", "exit_tday"])
        trades[name] = t
        market[name] = s.market
        f = pd.read_csv(d / "walkforward_folds.csv", parse_dates=["oos_start", "oos_end"])
        spans.append((f.oos_start.min(), f.oos_end.max()))  # the whole fold schedule: a fold with no valid
        #                                                       parameter set is part of it and trades nothing
    start, end = max(a for a, _ in spans), min(b for _, b in spans)
    if start >= end:
        return {"start": start, "end": end, "error": "the selected runs share no out-of-sample dates"}
    days = pd.DatetimeIndex(sorted(set().union(*[p.index for p in pnl.values()])))
    days = days[(days >= start) & (days <= end)]
    P = pd.DataFrame({k: v.reindex(days).fillna(0.0) for k, v in pnl.items()})
    tot = P.sum(axis=1)
    cum = tot.cumsum()
    dd = float((cum - np.maximum.accumulate(np.r_[0.0, cum.to_numpy()])[1:]).min())
    months = (end - start).days / 30.4375
    monthly = tot.groupby(tot.index.to_period("M")).sum()
    per, opened = [], np.zeros(len(days), dtype=int)
    gross = np.zeros(len(days))
    flat = []                                                  # flat start: trades entered inside the window
    for k, t in trades.items():
        w = t[(t.entry_tday >= start) & (t.entry_tday <= end)]
        db = daily_bars(market[k])
        real_entry = (w.entry_px - db.adj_open.reindex(pd.to_datetime(w.entry_tday)).fillna(0.0).to_numpy()) \
            * w.qty * db.pv.iloc[0]
        per.append({"run": k, "trades": len(w), "trades / month": round(len(w) / months, 2), "net $": round(float(P[k].sum()), 2),
                    "win %": round(float((w.pnl > 0).mean() * 100), 1) if len(w) else np.nan,
                    "median entry notional $": round(float(real_entry.median()), 0) if len(w) else np.nan,
                    "max entry notional $": round(float(real_entry.max()), 0) if len(w) else np.nan})
        close = db.raw_c.reindex(days).ffill().to_numpy()
        for a, b, q in zip(t.entry_tday, t.exit_tday, t.qty):    # open on each day from entry day to exit day
            m = (days >= a) & (days <= b)
            opened += m
            gross += np.where(m, q * close * db.pv.iloc[0], 0.0)
        flat.append(w[["exit_tday", "pnl"]])
    n_tr = sum(p["trades"] for p in per)
    fl = pd.concat(flat, ignore_index=True) if flat else pd.DataFrame(columns=["exit_tday", "pnl"])
    fd = fl.groupby(pd.to_datetime(fl.exit_tday)).pnl.sum().sort_index().cumsum()
    fdd = float((fd - np.maximum.accumulate(np.r_[0.0, fd.to_numpy()])[1:]).min()) if len(fd) else 0.0
    return {"start": start.date(), "end": end.date(), "months": round(months, 1), "runs": len(sel),
            "trades entered in window": n_tr, "trades_per_month": round(n_tr / months, 1),
            "positions carried in at start": carried_in(trades, start),
            "net (marked, includes carried-in positions)": round(float(tot.sum()), 2),
            "max drawdown (daily closes)": round(dd, 2),
            "net (flat start: trades entered in window, whole P&L)": round(float(fl.pnl.sum()), 2),
            "max drawdown (flat start, realised on exit days)": round(fdd, 2),
            "profitable_months": f"{int((monthly > 0).sum())} of {len(monthly)}",
            "worst_month": f"{monthly.idxmin()}: {monthly.min():,.0f}", "best_month": f"{monthly.idxmax()}: {monthly.max():,.0f}",
            "max positions open at once (bar timestamps)": max_overlap(trades),
            "max positions open on one day": int(opened.max()), "median positions open per day": float(np.median(opened)),
            "max gross exposure $ (one day)": round(float(gross.max()), 0),
            "median gross exposure $": round(float(np.median(gross)), 0),
            "per_run": pd.DataFrame(per), "monthly": monthly}


def buy_and_hold(markets, start: str, end: str, capital: float) -> pd.DataFrame:
    sys.path.insert(0, str(ROOT))
    from engine import data, get_instrument
    from photo_study import benchmark
    rows = []
    for m in markets:
        inst = get_instrument(m)
        bars = data.resample(data.load(inst.data_key), 1440, "full")
        bars = bars[(bars.tday >= start) & (bars.tday <= end)]
        if not len(bars):
            continue
        x = benchmark(bars.reset_index(drop=True), inst, [(start, end)], capital)
        rows.append({"market": m, "from": str(bars.tday.iloc[0])[:10], "to": str(bars.tday.iloc[-1])[:10],
                     "net $": x["net"], "max DD $": x["max_dd"]})
    return pd.DataFrame(rows)


def main():
    r = load()
    capital = 100_000.0
    out = {}
    print("Selection: runs that passed all key checks, one per strategy and underlying (most out-of-sample trades per "
          "month), measured only on the dates inside every selected run's walk-forward fold schedule (a fold with no "
          "valid parameter set trades nothing and counts as zero). Each run trades its own "
          f"${capital:,.0f} account with its own sizing rule (most size a trade at about ${capital:,.0f} of contract "
          "value; risk-sized ones vary, see the entry-notional columns), so the combined P&L below is the sum of "
          "separate accounts, NOT one capital-constrained account: see the gross-exposure and positions-open rows. "
          "'Marked' includes positions already open on the first day; 'flat start' counts only trades entered in "
          "the window. Drawdowns are on daily closes. The runs were chosen among those whose checks include their "
          "out-of-sample results, so this is NOT a fresh hold-out test.\n")
    for title, markets in BOOKS.items():
        sel = pick(r, markets)
        b = book(sel, capital)
        print(f"<!--BOOK {title}-->\n")
        if "error" in b:
            print(b["error"]); continue
        summary = {k: v for k, v in b.items() if k not in ("per_run", "monthly")}
        print(pd.DataFrame([summary]).T.rename(columns={0: title}).to_markdown())
        print()
        print(b["per_run"].to_markdown(index=False))
        print()
        bh = buy_and_hold(markets, str(b["start"]), str(b["end"]), capital)
        print(f"Buy-and-hold over the same dates (${capital:,.0f} of contract value, same costs):\n")
        print(bh.to_markdown(index=False))
        print()
        summary["buy_and_hold"] = bh.to_dict("records")
        out[title] = {**summary, "start": str(summary["start"]), "end": str(summary["end"]),
                      "selected": b["per_run"].run.tolist()}
    (ROOT / "results" / "TIMEFRAME_STUDY" / "portfolio_numbers.json").write_text(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
