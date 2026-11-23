"""Performance statistics from a backtest result."""
import numpy as np
import pandas as pd


def _max_streak(mask: np.ndarray) -> int:
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best


def daily_equity(res: dict) -> pd.Series:
    eq = res["equity"]
    return eq.groupby("tday").equity.last()


def drawdown(series: pd.Series) -> pd.Series:
    return series - series.cummax()


def summarize(res: dict) -> dict:
    t, cap = res["trades"], res["settings"].capital
    de = daily_equity(res)
    dpnl = de.diff().fillna(de.iloc[0] - cap) if len(de) else pd.Series(dtype=float)
    dd = drawdown(pd.concat([pd.Series([cap]), de.reset_index(drop=True)]))
    out = {"instrument": res["instrument"].name, "start": str(de.index.min())[:10] if len(de) else None,
           "end": str(de.index.max())[:10] if len(de) else None, "capital": cap,
           "trading_days": int(len(de)), "trades": int(len(t)), "skipped_orders": res["skipped"]}
    if len(t) == 0:
        return out
    wins, losses = t[t.pnl > 0], t[t.pnl <= 0]
    years = max((pd.Timestamp(out["end"]) - pd.Timestamp(out["start"])).days / 365.25, 1e-9)
    gp, gl = wins.pnl.sum(), -losses.pnl.sum()
    peak = pd.concat([pd.Series([cap]), de.reset_index(drop=True)]).cummax()
    dd_pct = (dd / peak).min() * 100
    # longest time under water (trading days)
    under = (dd.values < -1e-9)
    out.update({
        "net_pnl": round(t.pnl.sum(), 2),
        "return_pct": round(t.pnl.sum() / cap * 100, 2),
        "annual_return_pct_simple": round(t.pnl.sum() / cap * 100 / years, 2),
        "win_rate_pct": round(len(wins) / len(t) * 100, 2),
        "profit_factor": round(gp / gl, 3) if gl > 0 else float("inf"),
        "avg_win": round(wins.pnl.mean(), 2) if len(wins) else 0.0,
        "avg_loss": round(losses.pnl.mean(), 2) if len(losses) else 0.0,
        "payoff_ratio": round(wins.pnl.mean() / -losses.pnl.mean(), 3) if len(wins) and len(losses) and losses.pnl.mean() < 0 else None,
        "expectancy_per_trade": round(t.pnl.mean(), 2),
        "avg_r": round(t.r.mean(), 3) if t.r.notna().any() else None,
        "max_drawdown_usd": round(dd.min(), 2),
        "max_drawdown_pct": round(dd_pct, 2),
        "longest_drawdown_days": int(_max_streak(under)),
        "sharpe_daily_ann": round(dpnl.mean() / dpnl.std() * np.sqrt(252), 3) if dpnl.std() > 0 else None,
        "best_day": round(dpnl.max(), 2), "worst_day": round(dpnl.min(), 2),
        "best_day_share_of_profit_pct": round(dpnl.max() / t.pnl.sum() * 100, 1) if t.pnl.sum() > 0 else None,
        "max_consecutive_losses": _max_streak((t.pnl <= 0).values),
        "trades_per_year": round(len(t) / years, 1),
        "avg_bars_held": round(t.bars.mean(), 1),
        "total_costs": round(t.costs.sum(), 2),
        "of_which_slippage": round(t.slippage_usd.sum(), 2),
        "spread_paid_inside_prices": round(t.spread_usd.sum(), 2),
        "long_trades": int((t.side == "long").sum()), "long_pnl": round(t[t.side == "long"].pnl.sum(), 2),
        "short_trades": int((t.side == "short").sum()), "short_pnl": round(t[t.side == "short"].pnl.sum(), 2),
        "trades_across_rolls": int((t.rolls > 0).sum()),
        "exit_reasons": t.exit_reason.value_counts().to_dict(),
    })
    return out


def by_year(res: dict) -> pd.DataFrame:
    t = res["trades"]
    if len(t) == 0:
        return pd.DataFrame()
    t = t.assign(year=pd.to_datetime(t.exit_tday).dt.year)
    de = daily_equity(res)
    dd = de.groupby(pd.to_datetime(de.index).year).apply(lambda s: (s - s.cummax()).min())
    g = t.groupby("year")
    out = pd.DataFrame({
        "trades": g.size(), "net_pnl": g.pnl.sum().round(2), "win_rate_pct": (g.pnl.apply(lambda x: (x > 0).mean()) * 100).round(1),
        "profit_factor": g.pnl.apply(lambda x: x[x > 0].sum() / -x[x <= 0].sum() if (x <= 0).any() and x[x <= 0].sum() < 0 else np.inf).round(2),
        "avg_r": g.r.mean().round(3), "max_dd_in_year": dd.round(2),
    })
    return out


def by_month(res: dict) -> pd.DataFrame:
    t = res["trades"]
    if len(t) == 0:
        return pd.DataFrame()
    x = pd.to_datetime(t.exit_tday)
    return t.assign(y=x.dt.year, m=x.dt.month).pivot_table(index="y", columns="m", values="pnl", aggfunc="sum").round(0)


def result_from_trades(trades: pd.DataFrame, tdays, settings, inst, skipped=None) -> dict:
    """Build a result dict from a trade list alone (used for walk-forward windows and stitched
    out-of-sample results). Equity = capital + realized P&L booked on each trade's exit day,
    over every trading day in `tdays` (days without trades count as 0, which matters for Sharpe)."""
    tdays = pd.DatetimeIndex(pd.to_datetime(np.asarray(tdays))).unique().sort_values()
    if len(trades):
        daily = trades.groupby(pd.to_datetime(trades.exit_tday)).pnl.sum()
        daily = daily.reindex(tdays.union(daily.index), fill_value=0.0)
    else:
        daily = pd.Series(0.0, index=tdays)
    eq = pd.DataFrame({"tday": daily.index.values.astype("datetime64[D]"), "equity": settings.capital + daily.cumsum().values})
    return {"trades": trades.reset_index(drop=True), "equity": eq, "skipped": skipped or {}, "settings": settings, "instrument": inst}


OBJECTIVES = {
    "sharpe": "sharpe_daily_ann",
    "profit_factor": "profit_factor",
    "net_pnl": "net_pnl",
    "expectancy": "expectancy_per_trade",
    "return_dd": None,          # net P&L / |max drawdown|
}


def score(summary: dict, objective: str = "sharpe", min_trades: int = 30) -> float:
    """One number to rank parameter sets by. NaN when there are too few trades to judge."""
    if summary.get("trades", 0) < min_trades:
        return float("nan")
    if objective == "return_dd":
        dd = abs(summary.get("max_drawdown_usd") or 0)
        return summary["net_pnl"] / dd if dd > 0 else float("nan")
    v = summary.get(OBJECTIVES[objective])
    if v is None or v == float("inf"):
        return float("nan")
    return float(v)
