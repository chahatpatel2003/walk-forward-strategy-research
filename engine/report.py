"""Write a backtest's results to BACKTESTING/results/<run>/ and print a summary."""
import json
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from . import metrics
from .data import _assert_not_data_path

RESULTS = Path(__file__).resolve().parent.parent / "results"


def save(res: dict, name: str, params: dict | None = None, extra: dict | None = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS / f"{stamp}_{name}_{res['instrument'].name}"
    _assert_not_data_path(out)
    out.mkdir(parents=True, exist_ok=True)
    summ = metrics.summarize(res)
    summ["params"] = params or {}
    if extra:
        summ.update(extra)
    (out / "summary.json").write_text(json.dumps(summ, indent=2, default=str))
    res["trades"].to_csv(out / "trades.csv", index=False)
    de = metrics.daily_equity(res)
    de.to_csv(out / "daily_equity.csv", header=["equity"])
    yr = metrics.by_year(res)
    mo = metrics.by_month(res)
    with open(out / "summary.txt", "w") as f:
        f.write(text_summary(summ, yr, mo))
    if len(de):
        idx = pd.to_datetime(de.index)
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        a1.plot(idx, de.values, lw=1.2, color="#2b6cb0")
        a1.axhline(res["settings"].capital, color="#999", lw=0.8, ls="--")
        a1.set_title(f"{name} on {res['instrument'].name}: equity (net of costs)")
        a1.set_ylabel("$"); a1.grid(alpha=.3)
        dd = metrics.daily_drawdown(res)
        a2.fill_between(idx, dd.values, 0, color="#c53030", alpha=.5)
        a2.set_ylabel("drawdown $"); a2.grid(alpha=.3)
        fig.tight_layout(); fig.savefig(out / "equity.png", dpi=110); plt.close(fig)
    return out


def text_summary(s: dict, yr: pd.DataFrame, mo: pd.DataFrame) -> str:
    keys = ["instrument", "start", "end", "capital", "trades", "net_pnl", "return_pct", "annual_return_pct_simple",
            "win_rate_pct", "profit_factor", "avg_win", "avg_loss", "payoff_ratio", "expectancy_per_trade", "avg_r",
            "max_drawdown_usd", "max_drawdown_pct", "longest_drawdown_days", "sharpe_daily_ann", "best_day", "worst_day",
            "best_day_share_of_profit_pct", "max_consecutive_losses", "trades_per_year", "avg_bars_held",
            "total_costs", "of_which_slippage", "spread_paid_inside_prices", "long_trades", "long_pnl", "short_trades", "short_pnl",
            "trades_across_rolls", "skipped_orders", "notes", "exit_reasons"]
    lines = [f"{k:30s} {s.get(k)}" for k in keys if k in s]
    if s.get("params"):
        lines.append(f"{'params':30s} {s['params']}")
    if s.get("lookahead_check"):
        lines.append(f"{'lookahead_check':30s} {s['lookahead_check']}")
    txt = "\n".join(lines)
    if len(yr):
        txt += "\n\nBy year:\n" + yr.to_string()
    if len(mo):
        txt += "\n\nNet P&L by month:\n" + mo.to_string()
    return txt + "\n"
