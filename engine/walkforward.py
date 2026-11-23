"""Walk-forward test on our own data.

The history is cut into consecutive folds:

  rolling  :  [ in-sample 1 ][ OOS 1 ]
                    [ in-sample 2 ][ OOS 2 ]
                          [ in-sample 3 ][ OOS 3 ] ...
  anchored :  [ in-sample 1      ][ OOS 1 ]
              [ in-sample 2            ][ OOS 2 ] ...   (in-sample always starts at the beginning)

In each fold the parameter grid is optimised on the in-sample (IS) period ONLY, and the chosen
parameters are then traded on the following out-of-sample (OOS) period, which the optimiser never saw.
The OOS periods don't overlap and follow each other, so stitching them together gives one honest
equity curve: what you would have got by re-optimising every `oos_months` months.

Indicator warm-up: each OOS run loads `warmup_days` of earlier (already past) data so indicators are
ready, but only trades entered inside the OOS window count.
"""
import json
from dataclasses import replace
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import metrics, sweep
from .parallel import Job, run_many


def make_folds(tdays, is_months: int, oos_months: int, anchored: bool = False) -> list[dict]:
    """Fold boundaries as ISO dates (inclusive), snapped to trading days.
    All boundaries are whole calendar months counted from the first month of the data, so consecutive
    out-of-sample windows join with no gap and no overlap, and in-sample always ends before its OOS."""
    for name, v in (("in-sample", is_months), ("out-of-sample", oos_months)):
        if int(v) != v or v < 1:
            raise ValueError(f"{name} window must be a whole number of months >= 1, got {v}")
    tdays = pd.DatetimeIndex(pd.to_datetime(np.asarray(tdays))).unique().sort_values()
    if not len(tdays):
        raise ValueError("no trading days to build walk-forward folds from (check the date range and session)")
    first, last = tdays[0], tdays[-1]
    m0 = pd.Timestamp(first.year, first.month, 1)
    edge = lambda k: m0 + pd.DateOffset(months=k)          # noqa: E731  (start of month k)
    folds, k = [], 0
    while True:
        oos_start = edge(is_months + k * oos_months)
        if oos_start > last:
            break
        oos_next = edge(is_months + (k + 1) * oos_months)
        is_start = first if anchored or k == 0 else edge(k * oos_months)
        is_days = tdays[(tdays >= is_start) & (tdays < oos_start)]
        oos_days = tdays[(tdays >= oos_start) & (tdays < oos_next)]
        if len(is_days) and len(oos_days):
            folds.append({"fold": len(folds) + 1, "period": k,      # k = the scheduled window, kept even when
                          #                                          an earlier window had no data (no fold row)
                          "is_start": str(is_days[0].date()), "is_end": str(is_days[-1].date()),
                          "oos_start": str(oos_days[0].date()), "oos_end": str(oos_days[-1].date()),
                          "is_days": len(is_days), "oos_days": len(oos_days)})
        k += 1
    return folds


def efficiency(folds: pd.DataFrame) -> float:
    """Walk-forward efficiency = out-of-sample P&L per scored day / in-sample P&L per day of the chosen parameters,
    each POOLED over the folds (total P&L / total days, so a short fold weighs less than a long one). NaN when the
    in-sample rate is not positive or there are no scored folds."""
    if not len(folds) or "oos_net_pnl" not in folds:
        return np.nan
    f = folds.dropna(subset=["is_net_pnl", "oos_net_pnl"])
    if not len(f) or f.is_days.sum() <= 0 or f.oos_days.sum() <= 0:
        return np.nan
    is_rate = f.is_net_pnl.sum() / f.is_days.sum()
    oos_rate = f.oos_net_pnl.sum() / f.oos_days.sum()
    return float(oos_rate / is_rate) if is_rate > 0 else np.nan


# When the ratio is credible enough to be a pass criterion (findings.md, ninth revision, R3). Below these the ratio is
# still published ("raw") with its numerator and denominator, but the verdict is "not available".
MIN_SCORED_SHARE = 0.5            # at least half of the scheduled folds scored (in-sample AND out-of-sample P&L)
MIN_IS_RETURN_PER_YEAR = 0.01     # pooled in-sample profit of at least 1% of starting capital per 252 trading days


def efficiency_detail(folds: pd.DataFrame, capital: float) -> dict:
    """Walk-forward efficiency with everything needed to judge it: pooled in-sample and out-of-sample P&L per day,
    how many of the scheduled folds were scored, and whether the ratio is credible (see the two limits above).
    `efficiency` is None when it is not; `raw_ratio` is the plain ratio whenever the in-sample rate is positive."""
    f = pd.DataFrame(folds)
    n_sched = int(len(f))
    have = f.dropna(subset=[c for c in ("is_net_pnl", "oos_net_pnl") if c in f]) if len(f) else f
    if "is_net_pnl" not in f or "oos_net_pnl" not in f:
        have = f.iloc[0:0]
    out = {"scheduled_folds": n_sched, "scored_folds": int(len(have)), "is_net_pnl": None, "is_days": None,
           "is_pnl_per_day": None, "oos_net_pnl": None, "oos_days": None, "oos_pnl_per_day": None,
           "raw_ratio": None, "efficiency": None, "reason": None}
    if not len(have) or have.is_days.sum() <= 0 or have.oos_days.sum() <= 0:
        out["reason"] = "not available: no fold has both in-sample and out-of-sample results"
        return out
    is_rate = float(have.is_net_pnl.sum() / have.is_days.sum())
    oos_rate = float(have.oos_net_pnl.sum() / have.oos_days.sum())
    out.update(is_net_pnl=round(float(have.is_net_pnl.sum()), 2), is_days=int(have.is_days.sum()),
               is_pnl_per_day=round(is_rate, 4), oos_net_pnl=round(float(have.oos_net_pnl.sum()), 2),
               oos_days=int(have.oos_days.sum()), oos_pnl_per_day=round(oos_rate, 4))
    if is_rate > 0:
        out["raw_ratio"] = round(oos_rate / is_rate, 3)
    min_rate = capital * MIN_IS_RETURN_PER_YEAR / 252.0
    if len(have) < MIN_SCORED_SHARE * n_sched:
        out["reason"] = (f"not available: only {len(have)} of {n_sched} folds scored "
                         f"(needs at least {MIN_SCORED_SHARE:.0%})")
    elif is_rate < min_rate:
        out["reason"] = (f"not available: in-sample profit ${is_rate:,.2f}/day is below the "
                         f"${min_rate:,.2f}/day minimum ({MIN_IS_RETURN_PER_YEAR:.0%} of capital a year)")
    else:
        out["efficiency"] = round(oos_rate / is_rate, 3)
    return out


def run(base: Job, grid: dict, tdays, is_months=24, oos_months=6, anchored=False, objective="sharpe",
        min_trades=30, select="plateau", workers=None) -> dict:
    folds = make_folds(tdays, is_months, oos_months, anchored)
    if not folds:
        raise SystemExit("not enough data for even one fold: lower --is-months / --oos-months")
    combos = sweep.expand_grid(grid)
    # 1. optimise every fold's in-sample window (all folds at once, in parallel; summaries only)
    jobs = [base.with_(params={**base.params, **c}, start=f["is_start"], end=f["is_end"], summary_only=True,
                       tag={"fold": f["fold"], **c})
            for f in folds for c in combos]
    print(f"walk-forward: {len(folds)} folds x {len(combos)} parameter sets = {len(jobs)} in-sample runs")
    is_res = run_many(jobs, workers)
    for f in folds:
        rows = []
        for c, r in zip(combos, [x for x in is_res if x["tag"]["fold"] == f["fold"]]):
            s = r["summary"]
            rows.append({**c, "score": metrics.score(s, objective, min_trades), "trades": s.get("trades", 0),
                         "net_pnl": s.get("net_pnl", 0.0)})
        df = pd.DataFrame(rows)
        df["plateau_score"] = sweep.plateau(df, grid, "score")
        p = sweep.pick(df, grid, select)
        f["chosen"] = p
        if p is not None:
            row = df[np.logical_and.reduce([df[k] == v for k, v in p.items()])].iloc[0]
            f["is_score"], f["is_net_pnl"], f["is_trades"] = float(row.score), float(row.net_pnl), int(row.trades)
    # 2. trade each fold's chosen parameters on its out-of-sample window, IN ORDER, carrying the
    #    account balance forward (so %-of-equity sizing compounds like one continuous account)
    todo = [f for f in folds if f.get("chosen") is not None]
    print(f"walk-forward: {len(todo)} out-of-sample runs" + ("" if todo else " (no fold had a valid parameter set)"))
    trades, parts, capital = [], [], base.settings.capital
    stopped = False                                        # constrained account: a breach stops trading for good
    for f in todo:
        if base.settings.account_constrained and (stopped or capital <= 0):
            f["oos_skipped"] = "capital_exhausted"
            continue
        job = base.with_(params={**base.params, **f["chosen"]}, start=f["oos_start"], end=f["oos_end"],
                         settings=replace(base.settings, capital=capital), tag={"fold": f["fold"]})
        r = run_many([job], 1, progress=False)[0]
        s = r["summary"]
        f.update({"oos_scored_days": int(len(r["days"])) if r.get("days") is not None else 0,
                  "oos_warmup_short": bool(s.get("notes", {}).get("insufficient_warmup")),
                  "oos_trades": s.get("trades", 0), "oos_net_pnl": s.get("net_pnl", 0.0),
                  "oos_profit_factor": s.get("profit_factor"), "oos_win_rate_pct": s.get("win_rate_pct"),
                  "oos_max_dd_usd": s.get("max_drawdown_usd"), "oos_score": metrics.score(s, objective, 1)})
        if len(r["trades"]):
            trades.append(r["trades"].assign(fold=f["fold"]))
        if r.get("bars") is not None and len(r["bars"]):
            parts.append(r["bars"])
            capital = float(r["bars"].equity.iloc[-1])
        if s.get("capital_exhausted_on") or s.get("notes", {}).get("capital_exhausted_ts"):
            stopped = True
    trades = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
    bars = metrics.stitch_bars(parts, base.settings.capital)
    stitched = metrics.result_from_bars(trades, bars, base.settings, base.inst)
    return {"folds": folds, "oos_result": stitched, "grid": grid, "objective": objective, "select": select,
            "is_months": is_months, "oos_months": oos_months, "anchored": anchored}


def report(wf: dict, out: Path, title: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    folds = pd.DataFrame(wf["folds"])
    folds.to_csv(out / "walkforward_folds.csv", index=False)
    res = wf["oos_result"]
    summ = metrics.summarize(res) if len(res["equity"]) else {}
    res["trades"].to_csv(out / "walkforward_oos_trades.csv", index=False)
    de = metrics.daily_equity(res)
    pd.DataFrame({"tday": de.index, "equity": de.values}).to_csv(out / "walkforward_oos_daily_equity.csv", index=False)
    # Walk-forward efficiency: OOS profit per day vs the profit per day the optimiser found in-sample.
    have = folds.dropna(subset=["is_net_pnl"]) if "is_net_pnl" in folds else folds.iloc[0:0]
    if "oos_net_pnl" in have:
        have = have.dropna(subset=["oos_net_pnl"])
    eff_d = efficiency_detail(folds, float(res["settings"].capital))
    eff = eff_d["efficiency"]
    chosen = [json.dumps(c, sort_keys=True) for c in folds.chosen if c is not None] if "chosen" in folds else []
    info = {"folds": len(folds), "mode": "anchored" if wf["anchored"] else "rolling",
            "in_sample_months": wf["is_months"], "out_of_sample_months": wf["oos_months"],
            "objective": wf["objective"], "selection": wf["select"],
            "oos_period": f"{have.oos_start.iloc[0]} -> {have.oos_end.iloc[-1]}" if len(have) else None,
            "oos_net_pnl": summ.get("net_pnl"), "oos_trades": summ.get("trades"),
            "oos_profit_factor": summ.get("profit_factor"), "oos_sharpe": summ.get("sharpe_daily_ann"),
            "oos_max_drawdown_usd": summ.get("max_drawdown_usd"), "oos_win_rate_pct": summ.get("win_rate_pct"),
            "account_model": summ.get("account_model"), "oos_capital_exhausted_on": summ.get("capital_exhausted_on"),
            "folds_skipped_capital_exhausted": int((folds.get("oos_skipped") == "capital_exhausted").sum()) if "oos_skipped" in folds else 0,
            "profitable_oos_folds_pct": round(float((have.oos_net_pnl > 0).mean() * 100), 1) if len(have) and "oos_net_pnl" in have else None,
            "walk_forward_efficiency": eff,
            "walk_forward_efficiency_raw": eff_d["raw_ratio"],
            "walk_forward_efficiency_note": eff_d["reason"] or (
                f"{eff_d['scored_folds']} of {eff_d['scheduled_folds']} folds scored; OOS ${eff_d['oos_pnl_per_day']:,.2f}/day"
                f" vs in-sample ${eff_d['is_pnl_per_day']:,.2f}/day"),
            "wf_is_net_pnl_pooled": eff_d["is_net_pnl"], "wf_is_pnl_per_day": eff_d["is_pnl_per_day"],
            "wf_oos_pnl_per_day": eff_d["oos_pnl_per_day"], "wf_scored_folds": eff_d["scored_folds"],
            "folds_with_day_count_mismatch": int((have.oos_days != have.oos_scored_days).sum()) if "oos_scored_days" in have else None,
            "distinct_parameter_sets_chosen": len(set(chosen)),
            "folds_without_valid_parameters": int(folds.chosen.isna().sum()) if "chosen" in folds else len(folds)}
    (out / "walkforward_summary.json").write_text(json.dumps({**info, "oos_full_summary": summ}, indent=2, default=str))
    show = [c for c in ["fold", "is_start", "is_end", "oos_start", "oos_end", "chosen", "is_trades", "is_net_pnl",
                        "oos_trades", "oos_net_pnl", "oos_profit_factor", "oos_max_dd_usd"] if c in folds]
    lines = [f"WALK-FORWARD: {title}", ""] + [f"{k:34s} {v}" for k, v in info.items()]
    lines += ["", "walk_forward_efficiency = out-of-sample profit per scored day / in-sample profit per day of the chosen",
              "parameters, each pooled over all folds (total P&L / total days). Around 0.5 or more is usually considered",
              "healthy; near 0 or negative means the in-sample optimisation did not carry forward. It is reported as",
              f"not available when fewer than {MIN_SCORED_SHARE:.0%} of the folds were scored or the pooled in-sample profit",
              f"is below {MIN_IS_RETURN_PER_YEAR:.0%} of capital a year (a ratio over a near-zero denominator means nothing);",
              "walk_forward_efficiency_raw is the plain ratio either way.", "", "Folds:",
              folds[show].to_string(index=False)]
    (out / "walkforward_report.txt").write_text("\n".join(lines) + "\n")
    de = metrics.daily_equity(res)
    if len(de):
        fig, ax = plt.subplots(figsize=(12, 5))
        ax.plot(pd.to_datetime(de.index), de.values, lw=1.2, color="#2b6cb0", label="stitched out-of-sample equity")
        for s in folds.oos_start:
            ax.axvline(pd.Timestamp(s), color="#bbb", lw=.7, ls=":")
        ax.axhline(res["settings"].capital, color="#999", lw=.8, ls="--")
        ax.set_title(f"{title}: walk-forward, out-of-sample only (dotted lines = re-optimisation)")
        ax.legend(); ax.grid(alpha=.3); fig.tight_layout(); fig.savefig(out / "walkforward_equity.png", dpi=110); plt.close(fig)
    return info
