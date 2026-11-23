"""Both timeframe-study books (tools/timeframe_portfolio.py selection) on ONE account, risking a fixed % of the balance
per trade, compounding (tools/single_account.py). Also each run alone on its own account of the same size.

    python tools/single_account_study.py --mode atr                    # saved OOS trades, sized by 2 x ATR(14)
    python tools/single_account_study.py --mode stops --stops-dir results/SINGLE_ACCOUNT/stop_runs
Writes results/SINGLE_ACCOUNT/<mode>.md and <mode>.json.
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import single_account as sa  # noqa: E402
import timeframe_portfolio as tp  # noqa: E402
from timeframe_report import TF_LABEL, load  # noqa: E402

OUT = ROOT / "results" / "SINGLE_ACCOUNT"


def run_trades(s, mode: str, stops_dir: Path | None) -> pd.DataFrame:
    if mode == "atr":
        return pd.read_csv(tp.wf_dir(s.report) / "walkforward_oos_trades.csv")
    if s.code == "A12":                                    # has its own stop: the saved run
        return pd.read_csv(tp.wf_dir(s.report) / "walkforward_oos_trades.csv")
    rows = pd.read_csv(stops_dir.parent / "stop_rows.csv")
    x = rows[(rows.strategy == s.strategy) & (rows.market == s.market) & (rows.session == s.session) & (rows.bars == s.bars)
             & rows.error.isna()]
    if not len(x):
        raise SystemExit(f"no stop run for {s.strategy} {s.market} {s.session} {s.bars}: run tools/stop_study.py")
    return pd.read_csv(tp.wf_dir(x.report.iloc[0]) / "walkforward_oos_trades.csv")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["atr", "stops"], default="atr")
    ap.add_argument("--stops-dir", default=str(OUT / "stop_runs"))
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--risk-pct", type=float, default=2.0)
    ap.add_argument("--atr-k", type=float, default=2.0)
    ap.add_argument("--atr-len", type=int, default=14)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    r = load()
    pn = json.loads((ROOT / "results/TIMEFRAME_STUDY/portfolio_numbers.json").read_text())
    res, md = {}, []
    for title, markets in tp.BOOKS.items():
        sel = tp.pick(r, markets)
        runs = []
        for _, s in sel.iterrows():
            t = run_trades(s, a.mode, Path(a.stops_dir))
            name = f"{s.code} {s.market} {'cash' if s.session == 'rth' else 'full'} {TF_LABEL[s.bars]}"
            if not len(t):
                runs.append({"name": name, "market": s.market, "trades": t}); continue
            t["stop_dist"] = sa.stop_distance(t, s.market, int(s.bars[:-1]), s.session, a.atr_k, a.atr_len)
            runs.append({"name": name, "market": s.market, "trades": t})
        runs = [x for x in runs if len(x["trades"])]
        w = pn[title]
        book = sa.simulate(runs, a.capital, a.risk_pct, w["start"], w["end"])
        alone = []
        for x in runs:
            o = sa.simulate([x], a.capital, a.risk_pct)["summary"]
            alone.append({"run": x["name"], "period": f"{o['start']} → {o['end']}", "trades taken": o["trades_taken"],
                          "of offered": o["trades_offered"], "trades/mo": o["trades_per_month"], "win %": o["win_pct"],
                          "PF": o["profit_factor"], "net $": o["net"], "return %": o["return_pct"],
                          "CAGR %": o["cagr_pct"], "max DD %": o["max_dd_pct"], "worst trade (R)": o["worst_trade_r"],
                          "hit $0": o["account_hit_zero_on"] or ""})
        res[title] = {"book": book["summary"], "per_run": book["per_run"].reset_index().to_dict("records"), "alone": alone}
        book["equity"].to_csv(OUT / f"{a.mode}_{markets[0]}_equity.csv", header=["equity"])
        md += [f"<!--BOOK {title}-->", pd.DataFrame([book["summary"]]).T.rename(columns={0: title}).to_markdown(), "",
               book["per_run"].reset_index().to_markdown(index=False), "", pd.DataFrame(alone).to_markdown(index=False), ""]
    (OUT / f"{a.mode}.json").write_text(json.dumps(res, indent=1, default=str))
    (OUT / f"{a.mode}.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
