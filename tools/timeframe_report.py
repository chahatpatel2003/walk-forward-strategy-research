"""Tables for TIMEFRAME_STUDY_RESULTS.md, generated from results/TIMEFRAME_STUDY/rows.csv (every number in the report
comes from here). Prints markdown sections separated by <!--NAME--> markers and writes key_numbers.json.
    python tools/timeframe_report.py > results/TIMEFRAME_STUDY/tables.md
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from photo_report_tables import NAMES, robust_mask, survived  # noqa: E402

ROWS = ROOT / "results" / "TIMEFRAME_STUDY" / "rows.csv"
TF_ORDER = ["1m", "5m", "15m", "60m", "240m", "1440m"]
TF_LABEL = {"1m": "1-min", "5m": "5-min", "15m": "15-min", "60m": "1-hour", "240m": "4-hour", "1440m": "daily"}


def months(period) -> float:
    if not isinstance(period, str) or "->" not in period:
        return np.nan
    a, b = [pd.Timestamp(x.strip()) for x in period.split("->")]
    return max((b - a).days / 30.4375, 1e-9)


def load() -> pd.DataFrame:
    r = pd.read_csv(ROWS)
    r = r[r.error.isna()].copy()
    r["code"] = r.strategy.str[:3].str.upper()
    r["tf"] = pd.Categorical(r.bars, TF_ORDER, ordered=True)
    r["trades_per_month"] = r.trades_per_year / 12
    r["oos_months"] = r.wf_oos_period.map(months)
    r["oos_trades_per_month"] = r.wf_oos_trades / r.oos_months
    r["robust"] = robust_mask(r)
    r["survived"] = survived(r)
    return r


def fmt(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False) if len(df) else "(none)"


def main():
    r = load()
    out = {}
    # 1. by timeframe
    g = r.groupby("tf", observed=True)
    by_tf = pd.DataFrame({
        "bars": [TF_LABEL[str(k)] for k in g.groups],
        "runs": g.size().values,
        "median trades / month": g.trades_per_month.median().round(1).values,
        "profitable full history": g.net.apply(lambda x: int((x > 0).sum())).values,
        "walk-forward possible": g.wf_oos_net.apply(lambda x: int(x.notna().sum())).values,
        "profitable out-of-sample": g.wf_oos_net.apply(lambda x: int((x > 0).sum())).values,
        "passed all key checks": g.robust.sum().astype(int).values,
        "hit $0 somewhere": g.survived.apply(lambda x: int((~x).sum())).values,
        "median win %": g.win_pct.median().round(1).values,
        "median PF": g.pf.median().round(2).values,
    })
    print("<!--BYTF-->"); print(fmt(by_tf))
    out["by_tf"] = by_tf.to_dict("records")
    # 2. strategy x timeframe: robust / runs, median trades per month
    cells = []
    for code, d in r.groupby("code"):
        row = {"strategy": f"{code} {NAMES.get(code, '')}"}
        for tf in TF_ORDER:
            x = d[d.bars == tf]
            row[TF_LABEL[tf]] = (f"{int(x.robust.sum())}/{len(x)} · {x.trades_per_month.median():.1f}/mo"
                                 if len(x) else "-")
        cells.append(row)
    print("<!--GRID-->"); print(fmt(pd.DataFrame(cells)))
    # 3. per strategy x timeframe detail (medians across market/session runs)
    det = (r.groupby(["code", "tf"], observed=True)
           .agg(runs=("net", "size"), trades_mo=("trades_per_month", "median"), win=("win_pct", "median"),
                payoff=("payoff_ratio", "median"), pf=("pf", "median"), net=("net", "median"),
                prof=("net", lambda x: int((x > 0).sum())), oos_prof=("wf_oos_net", lambda x: f"{int((x > 0).sum())}/{int(x.notna().sum())}"),
                oos_pf=("wf_oos_pf", "median"), robust=("robust", "sum"), dd=("max_dd", "median"))
           .reset_index())
    det["tf"] = det.tf.astype(str).map(TF_LABEL)
    det.columns = ["strategy", "bars", "runs", "trades/mo", "win %", "avg win ÷ avg loss", "PF", "median net $",
                   "profitable", "profitable OOS", "median OOS PF", "passed all", "median max DD $"]
    print("<!--DETAIL-->"); print(fmt(det.round(2)))
    # 4. every run that passed all key checks
    cols = ["code", "market", "session", "bars", "trades_per_month", "oos_trades_per_month", "win_pct", "payoff_ratio",
            "pf", "net", "max_dd", "wf_oos_trades", "wf_oos_net", "wf_oos_pf", "wf_oos_max_dd", "buy_hold_oos_net",
            "mc_prob_loss_pct", "stress_worst_net", "stress_worst_scenario"]
    rb = r[r.robust].sort_values(["wf_oos_net"], ascending=False)[cols].copy()
    rb["bars"] = rb.bars.map(TF_LABEL)
    rb.columns = ["code", "market", "session", "bars", "trades/mo", "OOS trades/mo", "win %", "avg win ÷ avg loss", "PF",
                  "net $", "max DD $", "OOS trades", "OOS net $", "OOS PF", "OOS max DD $", "buy&hold OOS $",
                  "MC loss %", "worst stress $", "worst scenario"]
    print("<!--ROBUST-->"); print(fmt(rb.round(2)))
    out["robust_runs"] = int(len(rb))
    # 5. frequent AND robust
    fr = rb[rb["trades/mo"] >= 10]
    print("<!--FREQUENT-->"); print(fmt(fr))
    out["robust_runs_10_per_month"] = int(len(fr))
    near = r[(r.trades_per_month >= 10) & (r.wf_oos_net > 0) & ~r.robust].sort_values("wf_oos_net", ascending=False)
    nc = near[["code", "market", "session", "bars", "trades_per_month", "win_pct", "pf", "wf_oos_net", "wf_oos_pf",
               "mc_prob_loss_pct", "stress_all_net", "stress_worst_net", "checks_passed", "checks_total"]].copy()
    nc["bars"] = nc.bars.map(TF_LABEL)
    print("<!--NEAR-->"); print(fmt(nc.head(25).round(2)))
    # 6. combinations of robust runs (one per strategy+market+bar size; cash and full session of the same thing count once)
    uniq = r[r.robust].sort_values("wf_oos_net", ascending=False).drop_duplicates(["code", "market", "bars"])
    out["robust_distinct"] = int(len(uniq))
    out["robust_distinct_trades_per_month"] = round(float(uniq.oos_trades_per_month.sum()), 1)
    combo = uniq[["code", "market", "session", "bars", "oos_trades_per_month", "wf_oos_net", "wf_oos_max_dd"]].copy()
    combo["bars"] = combo.bars.map(TF_LABEL)
    combo.columns = ["code", "market", "session", "bars", "OOS trades/mo", "OOS net $", "OOS max DD $"]
    print("<!--COMBO-->"); print(fmt(combo.round(1)))
    # 7. all runs (appendix)
    allc = ["code", "market", "session", "bars", "pct_threshold_scale", "trades", "trades_per_month", "win_pct", "payoff_ratio",
            "pf", "net", "max_dd", "wf_oos_trades", "wf_oos_net", "wf_oos_pf", "mc_prob_loss_pct", "stress_all_net",
            "stress_worst_net", "checks_passed", "checks_total", "robust"]
    a = r.sort_values(["code", "tf", "market", "session"])[allc].copy()
    a["bars"] = a.bars.map(TF_LABEL)
    print("<!--ALL-->"); print(fmt(a.round(2)))
    out["runs"] = int(len(r))
    out["errors"] = int(pd.read_csv(ROWS).error.notna().sum())
    out["broke"] = r[~r.survived][["code", "market", "session", "bars", "capital_exhausted_on", "wf_capital_exhausted_on",
                                   "stress_scenarios_breached"]].astype(str).to_dict("records")
    (ROWS.parent / "key_numbers.json").write_text(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
