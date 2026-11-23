"""Monte Carlo risk simulation from a list of trades (best fed with walk-forward out-of-sample trades).

The backtest is one path out of many that the same edge could have produced. Re-ordering and
re-sampling the trades shows how bad things could plausibly get.

Methods
  shuffle   : same trades, random order. Final P&L is unchanged; drawdowns and losing streaks vary.
  bootstrap : draw trades with replacement. Final P&L varies too (how lucky was the backtest?).
  daily     : block bootstrap of DAILY P&L (blocks of `block` days, keeps clustered good/bad weeks).

Extra stress inside the simulation
  skip_pct    : randomly miss this % of trades (missed fills, days off, platform issues)
  haircut_pct : shrink every winning trade by this % (worse fills than the backtest)
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

PCTS = [1, 5, 25, 50, 75, 95, 99]


def _paths(pnl: np.ndarray, n_sims: int, method: str, rng, block: int, skip_pct: float, haircut_pct: float):
    n = len(pnl)
    if method == "shuffle":
        idx = np.argsort(rng.random((n_sims, n)), axis=1)
    elif method in ("bootstrap", "daily"):
        if method == "daily":
            starts = rng.integers(0, max(1, n - block + 1), size=(n_sims, int(np.ceil(n / block))))
            idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_sims, -1)[:, :n]
            idx = np.minimum(idx, n - 1)
        else:
            idx = rng.integers(0, n, size=(n_sims, n))
    else:
        raise ValueError(method)
    x = pnl[idx]
    if haircut_pct:
        x = np.where(x > 0, x * (1 - haircut_pct / 100.0), x)
    if skip_pct:
        x = np.where(rng.random(x.shape) < skip_pct / 100.0, 0.0, x)
    return x


def _streaks(x: np.ndarray) -> np.ndarray:
    """Longest run of losing entries per row."""
    best = np.zeros(x.shape[0], dtype=np.int32)
    cur = np.zeros(x.shape[0], dtype=np.int32)
    for j in range(x.shape[1]):
        lose = x[:, j] < 0
        cur = np.where(lose, cur + 1, 0)
        best = np.maximum(best, cur)
    return best


def simulate(pnl, capital: float, n_sims=10_000, method="shuffle", seed=42, block=5,
             skip_pct=0.0, haircut_pct=0.0, ruin_usd=None, keep_paths=200) -> dict:
    pnl = np.asarray(pnl, dtype=float)
    if len(pnl) < 2:
        raise ValueError("need at least 2 trades/days for Monte Carlo")
    rng = np.random.default_rng(seed)
    finals, maxdd, streak, ruined, sample = [], [], [], [], []
    batch = max(1, min(n_sims, int(4e7 // max(len(pnl), 1))))     # keep memory around 300 MB
    done = 0
    while done < n_sims:
        k = min(batch, n_sims - done)
        x = _paths(pnl, k, method, rng, block, skip_pct, haircut_pct)
        cum = np.cumsum(x, axis=1)
        peak = np.maximum.accumulate(np.maximum(cum, 0.0), axis=1)     # peak includes the starting balance
        dd = (cum - peak).min(axis=1)
        finals.append(cum[:, -1]); maxdd.append(dd); streak.append(_streaks(x))
        if ruin_usd:
            ruined.append(dd <= -abs(ruin_usd))
        if len(sample) < keep_paths:
            sample.extend(cum[: keep_paths - len(sample)])
        done += k
    finals, maxdd, streak = np.concatenate(finals), np.concatenate(maxdd), np.concatenate(streak)
    actual_cum = np.cumsum(pnl)
    actual_dd = float((actual_cum - np.maximum.accumulate(np.maximum(actual_cum, 0))).min())
    out = {
        "method": method, "simulations": int(n_sims), "items": int(len(pnl)), "capital": capital,
        "skip_pct": skip_pct, "haircut_pct": haircut_pct,
        "actual_final_pnl": float(actual_cum[-1]), "actual_max_drawdown_usd": actual_dd,
        "final_pnl_pct": {p: float(np.percentile(finals, p)) for p in PCTS},
        "max_drawdown_usd_pct": {p: float(np.percentile(maxdd, 100 - p)) for p in PCTS},   # p = "p% of runs are better"
        "longest_losing_streak_pct": {p: float(np.percentile(streak, p)) for p in PCTS},
        "prob_final_loss_pct": float((finals < 0).mean() * 100),
        "prob_drawdown_worse_than_actual_pct": float((maxdd < actual_dd).mean() * 100),
        "prob_drawdown_over_pct_of_capital": {f"{q}%": float((maxdd <= -capital * q / 100).mean() * 100) for q in (5, 10, 20, 30, 50)},
    }
    if ruin_usd:
        out["ruin_usd"] = float(abs(ruin_usd))
        out["prob_ruin_pct"] = float(np.concatenate(ruined).mean() * 100)
        dd95 = -np.percentile(maxdd, 5)
        out["size_multiplier_for_95pct_safe"] = round(float(abs(ruin_usd) / dd95), 3) if dd95 > 0 else None
    out["_finals"], out["_maxdd"], out["_paths"] = finals, maxdd, np.array(sample)
    return out


def report(mc: dict, out: Path, title: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    pub = {k: v for k, v in mc.items() if not k.startswith("_")}
    (out / "montecarlo_summary.json").write_text(json.dumps(pub, indent=2, default=str))
    tab = pd.DataFrame({"final_pnl": mc["final_pnl_pct"], "max_drawdown_usd": mc["max_drawdown_usd_pct"],
                        "longest_losing_streak": mc["longest_losing_streak_pct"]})
    tab.index = [f"{p}th pct" for p in tab.index]
    lines = [f"MONTE CARLO: {title}", "",
             f"method {mc['method']}, {mc['simulations']:,} simulations of {mc['items']:,} {'days' if mc['method'] == 'daily' else 'trades'}"
             + (f", {mc['skip_pct']}% trades skipped" if mc["skip_pct"] else "") + (f", winners cut {mc['haircut_pct']}%" if mc["haircut_pct"] else ""),
             f"backtest actual: final P&L {mc['actual_final_pnl']:,.0f}, max drawdown {mc['actual_max_drawdown_usd']:,.0f}", "",
             "Distribution (for drawdown, the 95th pct row = only 5% of simulations were WORSE):", tab.round(1).to_string(), "",
             f"chance of finishing with a loss:            {mc['prob_final_loss_pct']:.2f}%",
             f"chance of a drawdown worse than backtest's: {mc['prob_drawdown_worse_than_actual_pct']:.1f}%"]
    for q, v in mc["prob_drawdown_over_pct_of_capital"].items():
        lines.append(f"chance drawdown exceeds {q:>4s} of capital:    {v:.2f}%")
    if "prob_ruin_pct" in mc:
        lines += [f"chance of hitting the ${mc['ruin_usd']:,.0f} loss limit:  {mc['prob_ruin_pct']:.2f}%",
                  f"size multiplier so the 95%-worst drawdown fits the limit: x{mc['size_multiplier_for_95pct_safe']}"
                  "  (1.0 = current size; below 1 = trade smaller)"]
    (out / "montecarlo_report.txt").write_text("\n".join(lines) + "\n")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5))
    P = mc["_paths"]
    for p in P:
        a1.plot(p, color="#2b6cb0", alpha=.06, lw=.8)
    if len(P):
        for q, ls in ((5, "--"), (50, "-"), (95, "--")):
            a1.plot(np.percentile(P, q, axis=0), color="#1a365d", lw=1.4, ls=ls, label=f"{q}th pct of shown paths")
    a1.axhline(0, color="#999", lw=.8)
    a1.set_title("simulated equity paths (P&L, $)"); a1.set_xlabel("trade #" if mc["method"] != "daily" else "day #"); a1.legend(); a1.grid(alpha=.3)
    a2.hist(mc["_maxdd"], bins=80, color="#c53030", alpha=.7)
    a2.axvline(mc["actual_max_drawdown_usd"], color="k", lw=1.5, label="backtest drawdown")
    a2.axvline(np.percentile(mc["_maxdd"], 5), color="#c53030", lw=1.5, ls="--", label="5% worst")
    if "ruin_usd" in mc:
        a2.axvline(-mc["ruin_usd"], color="#744210", lw=1.5, ls=":", label="loss limit")
    a2.set_title("max drawdown across simulations ($)"); a2.legend(); a2.grid(alpha=.3)
    fig.suptitle(title); fig.tight_layout(); fig.savefig(out / "montecarlo.png", dpi=110); plt.close(fig)
    return pub
