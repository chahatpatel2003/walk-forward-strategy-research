"""Parameter test: run every combination of a parameter grid and check how robust the result is.

What it tells you
  - The best combination, and how it compares with the typical one.
  - Plateau score: for each combination, look at it AND its neighbours (one step either way on every
    parameter) and take  0.5 x their average + 0.5 x their worst  score. This rewards settings whose
    whole neighbourhood is good and never terrible. A best setting that sits on a broad plateau is far
    more trustworthy than an isolated spike, which is usually curve-fitting.
  - Sensitivity: the average score for each value of each parameter, holding nothing fixed.
"""
import itertools
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import metrics
from .parallel import Job, run_many


def expand_grid(grid: dict) -> list[dict]:
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]


def plateau(df: pd.DataFrame, grid: dict, col: str = "score") -> pd.Series:
    """0.5*mean + 0.5*min of `col` over each combination's neighbourhood (+-1 step on every axis,
    diagonals included). NaN scores (too few trades) count as missing; a neighbourhood that is mostly
    missing scores NaN."""
    keys = list(grid)
    pos = {k: {v: i for i, v in enumerate(grid[k])} for k in keys}
    shape = tuple(len(grid[k]) for k in keys)
    cube = np.full(shape, np.nan)
    idx = [tuple(pos[k][row[k]] for k in keys) for _, row in df.iterrows()]
    for ix, s in zip(idx, df[col].to_numpy()):
        cube[ix] = s
    out = []
    for ix in idx:
        sl = tuple(slice(max(0, j - 1), j + 2) for j in ix)
        nb = cube[sl]
        ok = ~np.isnan(nb)
        out.append(0.5 * np.nanmean(nb) + 0.5 * np.nanmin(nb) if ok.sum() >= max(1, nb.size / 2) else np.nan)
    return pd.Series(out, index=df.index)


def run_sweep(base: Job, grid: dict, objective="sharpe", min_trades=30, workers=None) -> pd.DataFrame:
    combos = expand_grid(grid)
    jobs = [base.with_(params={**base.params, **c}, tag=c, summary_only=True) for c in combos]
    res = run_many(jobs, workers)
    rows = []
    for c, r in zip(combos, res):
        s = r["summary"]
        rows.append({**c, "score": metrics.score(s, objective, min_trades), "trades": s.get("trades", 0),
                     "net_pnl": s.get("net_pnl", 0.0), "profit_factor": s.get("profit_factor"),
                     "win_rate_pct": s.get("win_rate_pct"), "max_drawdown_usd": s.get("max_drawdown_usd"),
                     "sharpe": s.get("sharpe_daily_ann"), "avg_r": s.get("avg_r")})
    df = pd.DataFrame(rows)
    df["plateau_score"] = plateau(df, grid, "score")
    return df


def pick(df: pd.DataFrame, grid: dict, how: str = "plateau") -> dict | None:
    """Choose a parameter set: 'best' = highest score, 'plateau' = highest neighbourhood score."""
    col = "plateau_score" if how == "plateau" else "score"
    ok = df[df[col].notna() & df["score"].notna()]
    if ok.empty:
        return None
    idx = ok[col].idxmax()
    return {k: _py(df.at[idx, k]) for k in grid}       # df.at keeps each column's own type (int stays int)


def on_edge(choice: dict | None, grid: dict) -> bool:
    """True if any chosen value is the first or last value tried (the best area may lie beyond the grid)."""
    return bool(choice) and any(len(grid[k]) > 2 and v in (grid[k][0], grid[k][-1]) for k, v in choice.items())


def _py(v):
    return v.item() if hasattr(v, "item") else v


def report(df: pd.DataFrame, grid: dict, out: Path, objective: str, title: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    df.sort_values("score", ascending=False).to_csv(out / "sweep_results.csv", index=False)
    valid = df[df.score.notna()]
    best, plat = pick(df, grid, "best"), pick(df, grid, "plateau")
    info = {"objective": objective, "combinations": len(df), "with_enough_trades": int(len(valid)),
            "profitable_pct": round(float((valid.net_pnl > 0).mean() * 100), 1) if len(valid) else None,
            "best": best, "best_score": _py(valid.score.max()) if len(valid) else None,
            "plateau_choice": plat, "plateau_choice_on_grid_edge": on_edge(plat, grid),
            "plateau_choice_score": _py(df.loc[df.plateau_score.idxmax(), "plateau_score"]) if df.plateau_score.notna().any() else None,
            "median_score": _py(valid.score.median()) if len(valid) else None}
    # Is the best an isolated spike? Compare best score with its own neighbourhood.
    if best is not None:
        row = df[np.logical_and.reduce([df[k] == v for k, v in best.items()])].iloc[0]
        info["best_neighbourhood_score"] = _py(row.plateau_score)
        bs, ns = row.score, row.plateau_score
        info["best_is_isolated_spike"] = bool(pd.notna(ns) and bs > 0 and ns < 0.5 * bs)
    sens = {k: df.groupby(k).score.mean().round(4).to_dict() for k in grid}
    info["sensitivity_mean_score_by_value"] = {k: {str(a): b for a, b in v.items()} for k, v in sens.items()}
    (out / "sweep_summary.json").write_text(json.dumps(info, indent=2, default=str))
    # Heatmaps: every pair of parameters, score averaged over the other parameters.
    keys = [k for k in grid if len(grid[k]) > 1]
    pairs = list(itertools.combinations(keys, 2))[:6]
    if pairs:
        n = len(pairs)
        fig, axes = plt.subplots(1, n, figsize=(5.2 * n, 4.2), squeeze=False)
        for ax, (a, b) in zip(axes[0], pairs):
            pv = df.pivot_table(index=a, columns=b, values="score", aggfunc="mean")
            im = ax.imshow(pv.values, cmap="RdYlGn", aspect="auto", origin="lower")
            ax.set_xticks(range(len(pv.columns))); ax.set_xticklabels([str(x) for x in pv.columns])
            ax.set_yticks(range(len(pv.index))); ax.set_yticklabels([str(x) for x in pv.index])
            ax.set_xlabel(b); ax.set_ylabel(a)
            for (yy, xx), v in np.ndenumerate(pv.values):
                if not np.isnan(v):
                    ax.text(xx, yy, f"{v:.2f}", ha="center", va="center", fontsize=8)
            fig.colorbar(im, ax=ax, shrink=.8)
        fig.suptitle(f"{title}: {objective} by parameter pair (averaged over other parameters)")
        fig.tight_layout(); fig.savefig(out / "sweep_heatmaps.png", dpi=110); plt.close(fig)
    elif keys:
        k = keys[0]
        s = df.groupby(k).score.mean()
        fig, ax = plt.subplots(figsize=(7, 4)); ax.plot([str(x) for x in s.index], s.values, marker="o")
        ax.set_xlabel(k); ax.set_ylabel(objective); ax.grid(alpha=.3); ax.set_title(title)
        fig.tight_layout(); fig.savefig(out / "sweep_heatmaps.png", dpi=110); plt.close(fig)
    lines = [f"PARAMETER TEST: {title}", f"objective: {objective} (combinations with fewer than the minimum trades are ignored)", ""]
    for k, v in info.items():
        if k != "sensitivity_mean_score_by_value":
            lines.append(f"{k:30s} {v}")
    lines.append("\nMean score for each parameter value (sensitivity):")
    for k, v in info["sensitivity_mean_score_by_value"].items():
        lines.append(f"  {k}: {v}")
    lines.append("\nTop 15 combinations:\n" + df.sort_values("score", ascending=False).head(15).to_string(index=False))
    (out / "sweep_report.txt").write_text("\n".join(lines) + "\n")
    return info
