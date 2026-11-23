"""Every strategy of both timeframe-study books (24 runs) on ONE account, risking a fixed % of the balance per trade
(compounding), four ways:
  A hold   saved out-of-sample trades, sized by 2 x ATR(14) (no hard stop)
  A 16:00  the same trades, each closed at the New York cash close (tools/session_exit.py)
  B hold   the re-runs with a real 2 x ATR stop (tools/stop_study.py; A12: its own stop)
  B 16:00  those, closed at the cash close
Uses every out-of-sample trade of every run (each run's whole walk-forward period), so the account trades NAS100
first (data to 2021-09) and MNQ / gold later.
    python tools/combined_account.py
Writes results/SINGLE_ACCOUNT/combined.json, combined_<variant>_equity.csv and COMBINED_ACCOUNT_10K.md.
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import session_exit as se  # noqa: E402
import single_account as sa  # noqa: E402
import single_account_study as sas  # noqa: E402
import timeframe_portfolio as tp  # noqa: E402
from timeframe_report import TF_LABEL, load  # noqa: E402

OUT = ROOT / "results" / "SINGLE_ACCOUNT"
CAPITAL, RISK, K, ATR_LEN = 10_000.0, 2.0, 2.0, 14


def runs(mode: str, session_end: bool) -> list[dict]:
    r = load()
    sel = pd.concat([tp.pick(r, m) for m in tp.BOOKS.values()], ignore_index=True)
    sel = sel.drop_duplicates(["strategy", "market", "session", "bars"]).reset_index(drop=True)
    out = []
    for _, s in sel.iterrows():
        t = sas.run_trades(s, mode, OUT / "stop_runs")
        if not len(t):
            continue
        t["stop_dist"] = sa.stop_distance(t, s.market, int(s.bars[:-1]), s.session, K, ATR_LEN)
        if session_end:
            t = se.to_session_end(t, s.market)
        out.append({"name": f"{s.code} {s.market} {'cash' if s.session == 'rth' else 'full'} {TF_LABEL[s.bars]}",
                    "market": s.market, "trades": t})
    return out


def yearly(eq: pd.Series, trades: pd.DataFrame) -> pd.DataFrame:
    ye = eq.groupby(eq.index.year).last()
    start = pd.concat([pd.Series([CAPITAL], index=[ye.index[0] - 1]), ye]).shift(1).iloc[1:]
    tk = trades[trades.new_qty > 0]
    yrs = pd.to_datetime(tk.entry_tday).dt.year
    dd = []
    for y in ye.index:
        e = eq[eq.index.year == y]
        pk = np.maximum.accumulate(np.r_[start[y], e.to_numpy()])[1:]
        dd.append(float(((e / pk) - 1).min() * 100))
    return pd.DataFrame({"start $": start.round(0), "end $": ye.round(0), "return %": ((ye / start - 1) * 100).round(1),
                         "max DD % in year": np.round(dd, 1), "trades": yrs.value_counts().reindex(ye.index).fillna(0).astype(int),
                         "markets traded": [", ".join(sorted(tk[yrs == y].market.unique())) for y in ye.index]})


def main():
    res, tabs = {}, {}
    for label, mode, cut in [("A hold", "atr", False), ("A 16:00", "atr", True), ("B hold", "stops", False), ("B 16:00", "stops", True)]:
        rs = runs(mode, cut)
        o = sa.simulate(rs, CAPITAL, RISK)
        T = o["trades"]
        s = o["summary"]
        s["cut_at_16:00"] = int(T.cut_at_session_end.sum()) if "cut_at_session_end" in T else 0
        tk = T[T.new_qty > 0]
        s["largest_position"] = ", ".join(f"{m} {tk[tk.market == m].new_qty.max():,.2f}".rstrip("0").rstrip(".")
                                          for m in sorted(tk.market.unique()))
        s["overnight_positions"] = int((pd.to_datetime(T[T.new_qty > 0].exit_tday) > pd.to_datetime(T[T.new_qty > 0].entry_tday)).sum())
        res[label] = {"summary": s, "per_run": o["per_run"].reset_index().to_dict("records")}
        tabs[label] = yearly(o["equity"], T)
        o["equity"].to_csv(OUT / f"combined_{label.replace(' ', '_').replace(':', '')}_equity.csv", header=["equity"])
        print(label, {k: s[k] for k in ("trades_taken", "final_equity", "max_dd_pct", "cut_at_16:00", "overnight_positions")}, flush=True)
    (OUT / "combined.json").write_text(json.dumps({k: {**v, "yearly": tabs[k].reset_index().to_dict("records")}
                                                   for k, v in res.items()}, indent=1, default=str))
    write_md(res, tabs)


def write_md(res, tabs):
    def money(v):
        return f"−${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"
    rows = [("Period", lambda s: f"{s['start']} → {s['end']}"), ("Trades taken", lambda s: f"{s['trades_taken']:,}"),
            ("Trades skipped (1 contract risks > 2%)", lambda s: f"{sum(s['skipped'].values()):,}"),
            ("Trades per month", lambda s: f"{s['trades_per_month']}"),
            ("Trades cut at the 16:00 close", lambda s: f"{s['cut_at_16:00']:,}"),
            ("Positions held overnight", lambda s: f"{s['overnight_positions']:,}"),
            ("$10,000 →", lambda s: f"**{money(s['final_equity'])}**"),
            ("Per year (compounded)", lambda s: f"{s['cagr_pct']}%" if s["cagr_pct"] is not None else "—"),
            ("Max drawdown (daily closes)", lambda s: f"{money(s['max_dd_usd'])} ({s['max_dd_pct']}%)"),
            ("Win rate", lambda s: f"{s['win_pct']}%"), ("Profit factor", lambda s: f"{s['profit_factor']}"),
            ("Average win / loss", lambda s: f"+{s['avg_win_r']}R / {s['avg_loss_r']}R"),
            ("Worst trade", lambda s: f"{s['worst_trade_r']}R"), ("Profitable months", lambda s: s["profitable_months"]),
            ("Worst month", lambda s: s["worst_month"]), ("Most positions open at the same moment", lambda s: f"{s['max_open_positions']}"),
            ("Max contract value ÷ balance (any moment)", lambda s: f"{s['max_leverage_any_time']}×"),
            ("Largest single position (contracts / lots)", lambda s: s["largest_position"]),
            ("Account hit $0", lambda s: s["account_hit_zero_on"] or "no")]
    ks = list(res)
    L = ["# All strategies on one $10,000 account, 2% risk per trade, compounding: holding vs. closing at 16:00 ET", "",
         f"*Generated {date.today():%B %d, %Y} by `tools/combined_account.py`. All 24 runs of both books in "
         "TIMEFRAME_STUDY_RESULTS.md section 7, every walk-forward out-of-sample trade.*", "",
         "* **A** = saved trades sized by 2 × ATR(14), no hard stop. **B** = re-runs with a real 2 × ATR stop "
         "(SINGLE_ACCOUNT_10K.md). **hold** = the strategies' own exits. **16:00** = every position still open at the New "
         "York cash close (13:00 on half days) is closed there at the bid (long) / ask (short) with slippage and "
         "commission; nothing is re-entered.",
         "* Risk sizing is the same in all four: 2% of the balance ÷ (stop distance × point value), rounded down to whole "
         "MNQ/MGC contracts or 0.01 lots; skipped if one contract risks more. With the 16:00 exit the stop distance is "
         "still 2 × ATR of the strategy's own bars, so intraday positions are sized conservatively.",
         "* **The multi-million 'hold' results are compounding arithmetic, not a tradable outcome:** at those balances 2% "
         "risk means up to 1,264 MNQ contracts or 160 lots of gold in one trade (see 'Largest single position'), with "
         "contract value up to ~15× equity; fills, margin and liquidity would not be the same. Per-strategy dollar "
         "figures are dominated by WHEN a strategy traded (late trades are sized on a much bigger balance), so compare "
         "the strategies by sign, not size. Drawdown is measured at daily closes, so the intraday swings of the 16:00 "
         "versions are not in it.",
         "* The markets don't overlap in time: NAS100 data ends 2021-09-30, while the MNQ and spot-gold out-of-sample "
         "trades start in 2022. The yearly table shows what traded when.", "",
         "| | " + " | ".join(ks) + " |", "|---" * (len(ks) + 1) + "|"]
    L += [f"| {n} | " + " | ".join(f(res[k]["summary"]) for k in ks) + " |" for n, f in rows]
    for k in ks:
        L += ["", f"### {k}: year by year", "", tabs[k].reset_index().rename(columns={"index": "year"}).to_markdown(index=False)]
    per = {k: pd.DataFrame(res[k]["per_run"]).set_index("run") for k in ks}
    t = pd.DataFrame({f"{k} net $": per[k].net.round(0) for k in ks})
    t.insert(0, "trades (A hold)", per["A hold"].trades.astype(int))
    L += ["", "### Net profit by strategy inside the combined account", "", t.reset_index().to_markdown(index=False), ""]
    (ROOT / "COMBINED_ACCOUNT_10K.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
