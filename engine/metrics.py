"""Performance statistics from a backtest result."""
import numpy as np
import pandas as pd


def _max_streak(mask: np.ndarray) -> int:
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best


def _bars(res: dict) -> pd.DataFrame:
    """The result's per-bar equity (tday, equity_open, equity_low, equity)."""
    eq = res["equity"]
    out = eq[["tday", "equity"]].copy()
    out["equity_open"] = eq["equity_open"] if "equity_open" in eq else eq["equity"]
    out["equity_low"] = eq["equity_low"] if "equity_low" in eq else eq["equity"]
    if "breach" in eq:
        out["breach"] = eq["breach"]
    return out


def drawdown_walk(bars: pd.DataFrame, capital: float) -> tuple[np.ndarray, np.ndarray]:
    """Exact drawdown, walking every bar in the order its prices are known to occur:
    open -> worst price inside the bar -> close. A bar's worst price is never used as a peak, and each low
    is measured from the highest open/close seen BEFORE it (so a later recovery can't be the peak).
    Returns per bar: worst drawdown in $ and in % of the preceding peak."""
    o = bars["equity_open"].to_numpy(dtype=float)
    lo = bars["equity_low"].to_numpy(dtype=float)
    c = bars["equity"].to_numpy(dtype=float)
    lo = np.minimum(lo, np.minimum(o, c))
    seq = np.column_stack([o, lo, c]).ravel()
    can_peak = seq.copy()
    can_peak[1::3] = -np.inf
    peak = np.maximum.accumulate(np.concatenate([[capital], can_peak]))[1:]
    dd = (seq - peak).reshape(-1, 3)
    pct = ((seq - peak) / peak).reshape(-1, 3) * 100
    return dd.min(axis=1), pct.min(axis=1)


def daily_equity(res: dict) -> pd.Series:
    """Equity at each trading day's last bar."""
    b = _bars(res)
    return b.groupby("tday").equity.last()


def daily_drawdown(res: dict) -> pd.Series:
    """Worst drawdown ($) reached on each trading day (from the exact bar walk)."""
    b = _bars(res)
    dd, _ = drawdown_walk(b, res["settings"].capital)
    return pd.Series(dd).groupby(b.tday.to_numpy()).min()


def drawdown(series: pd.Series) -> pd.Series:
    return series - series.cummax()


def summarize(res: dict) -> dict:
    t, cap = res["trades"], res["settings"].capital
    bars = _bars(res)
    de = bars.groupby("tday").equity.last()
    dpnl = de.diff().fillna(de.iloc[0] - cap) if len(de) else pd.Series(dtype=float)
    if len(bars):
        dd_bar, pct_bar = drawdown_walk(bars, cap)
        dd = pd.Series(dd_bar).groupby(bars.tday.to_numpy()).min()
    else:
        dd_bar = pct_bar = np.array([0.0])
        dd = pd.Series(dtype=float)
    low_mark = np.minimum(bars.equity.to_numpy(), bars.equity_open.to_numpy()) if len(bars) and "equity_open" in bars \
        else (bars.equity.to_numpy() if len(bars) else np.array([]))
    broke = bars.tday[low_mark <= 0] if len(bars) else pd.Series(dtype=object)       # marked at an open or a close
    if len(bars) and "breach" in bars:                       # also a breach the engine saw right after an entry fill
        broke = bars.tday[(low_mark <= 0) | bars.breach.fillna(False).to_numpy(dtype=bool)]
    out = {"instrument": res["instrument"].name, "start": str(de.index.min())[:10] if len(de) else None,
           "end": str(de.index.max())[:10] if len(de) else None, "capital": cap,
           "account_model": "constrained" if getattr(res["settings"], "account_constrained", False) else "unconstrained",
           "capital_exhausted_on": str(broke.iloc[0])[:10] if len(broke) else None,
           "trading_days": int(len(de)), "trades": int(len(t)), "skipped_orders": res["skipped"],
           "notes": res.get("notes", {})}
    if len(t) == 0:
        return out
    span_days = (pd.Timestamp(out["end"]) - pd.Timestamp(out["start"])).days
    years = span_days / 365.25 if span_days > 0 else None          # a one-day test has no meaningful annual rate
    under = (dd.values < -1e-9)
    wins, losses = t[t.pnl > 0], t[t.pnl <= 0]
    gp, gl = wins.pnl.sum(), -losses.pnl.sum()
    out.update({
        "net_pnl": round(t.pnl.sum(), 2),
        "return_pct": round(t.pnl.sum() / cap * 100, 2),
        "annual_return_pct_simple": round(t.pnl.sum() / cap * 100 / years, 2) if years else None,
        "win_rate_pct": round(len(wins) / len(t) * 100, 2),
        "profit_factor": round(gp / gl, 3) if gl > 0 else float("inf"),
        "avg_win": round(wins.pnl.mean(), 2) if len(wins) else 0.0,
        "avg_loss": round(losses.pnl.mean(), 2) if len(losses) else 0.0,
        "payoff_ratio": round(wins.pnl.mean() / -losses.pnl.mean(), 3) if len(wins) and len(losses) and losses.pnl.mean() < 0 else None,
        "expectancy_per_trade": round(t.pnl.mean(), 2),
        "avg_r": round(t.r.mean(), 3) if t.r.notna().any() else None,
        "max_drawdown_usd": round(float(dd_bar.min()), 2),
        "max_drawdown_pct": round(float(pct_bar.min()), 2),
        "longest_drawdown_days": int(_max_streak(under)),
        "sharpe_daily_ann": round(dpnl.mean() / dpnl.std() * np.sqrt(252), 3) if dpnl.std() > 0 else None,
        "best_day": round(dpnl.max(), 2), "worst_day": round(dpnl.min(), 2),
        "best_day_share_of_profit_pct": round(dpnl.max() / t.pnl.sum() * 100, 1) if t.pnl.sum() > 0 else None,
        "max_consecutive_losses": _max_streak((t.pnl <= 0).values),
        "trades_per_year": round(len(t) / years, 1) if years else None,
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
    dd_day = daily_drawdown(res)
    dd = dd_day.groupby(pd.to_datetime(dd_day.index).year).min()
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
    """Build a result dict from a trade list alone, for when no equity curve exists (e.g. Monte Carlo
    from a saved trade file). Equity = capital + realized P&L booked on each trade's exit day, over every
    trading day in `tdays` (days without trades count as 0). Drawdown inside a trade is NOT visible here;
    backtests and robustness windows use the engine's per-bar equity instead."""
    tdays = pd.DatetimeIndex(pd.to_datetime(np.asarray(tdays))).unique().sort_values()
    if len(trades):
        daily = trades.groupby(pd.to_datetime(trades.exit_tday)).pnl.sum()
        daily = daily.reindex(tdays.union(daily.index), fill_value=0.0)
    else:
        daily = pd.Series(0.0, index=tdays)
    e = settings.capital + daily.cumsum().values
    eq = pd.DataFrame({"tday": daily.index.values.astype("datetime64[D]"), "equity_open": e, "equity_low": e, "equity": e})
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


def result_from_bars(trades: pd.DataFrame, bars: pd.DataFrame, settings, inst, skipped=None, notes=None) -> dict:
    """Result from a window's per-bar equity (tday, equity_open, equity_low, equity)."""
    eq = bars.reset_index(drop=True)[["tday", "equity_open", "equity_low", "equity"] + (["breach"] if "breach" in bars else [])].copy()
    eq["tday"] = eq.tday.to_numpy().astype("datetime64[D]")
    return {"trades": trades.reset_index(drop=True), "equity": eq, "skipped": skipped or {}, "notes": notes or {},
            "settings": settings, "instrument": inst}


def stitch_bars(parts: list[pd.DataFrame], capital: float) -> pd.DataFrame:
    """Join consecutive windows' per-bar equity into one curve: each window continues from where the previous
    one ended. Each part has tday, equity_open, equity_low, equity and start_equity (equity before its first bar)."""
    out, level = [], capital
    for p in parts:
        if p is None or not len(p):
            continue
        q = p.copy()
        shift = level - q.start_equity.iloc[0]
        for c in ("equity_open", "equity_low", "equity"):
            q[c] = q[c] + shift
        level = q.equity.iloc[-1]
        out.append(q[["tday", "equity_open", "equity_low", "equity"] + (["breach"] if "breach" in q else [])])
    if not out:
        return pd.DataFrame({"tday": np.array([], dtype="datetime64[D]"), "equity_open": [], "equity_low": [], "equity": []})
    return pd.concat(out, ignore_index=True)
