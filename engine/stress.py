"""Stress test: does the strategy survive worse conditions than the backtest assumed?

1. Execution stress (each one is a full re-run of the backtest):
     higher commission, more slippage, wider spread, entries/exits delayed by 1-2 bars, and all combined.
2. Dependence on a few big winners: P&L after removing the best 1% / 5% of trades and the top 10 trades.
3. Market stress: results inside known turbulent periods that our data covers (P&L = change in MARKED equity over
   the period, so an open position's gains and losses count when they happen, not when the trade is closed), on
   the most volatile 20% of days vs the rest (by trade exit day), and the worst calendar month / rolling 3- and
   12-month stretches (complete calendar months only; dates shown).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import metrics
from .calendar import trading_days
from .parallel import Job, run_many

PERIODS = [  # (name, first day, last day)
    ("Brexit vote 2016", "2016-06-20", "2016-07-08"),
    ("US election 2016", "2016-11-07", "2016-11-30"),
    ("Volmageddon Feb 2018", "2018-01-29", "2018-02-16"),
    ("Q4 2018 sell-off", "2018-10-01", "2018-12-31"),
    ("COVID crash 2020", "2020-02-19", "2020-04-30"),
    ("2022 bear market", "2022-01-03", "2022-10-14"),
    ("SVB banking stress Mar 2023", "2023-03-08", "2023-03-31"),
    ("Yen carry unwind Aug 2024", "2024-07-15", "2024-08-30"),
    ("Tariff shock Apr 2025", "2025-03-31", "2025-04-30"),
]


def scenarios(job: Job) -> list[tuple[str, Job]]:
    inst, s = job.inst, job.settings
    has_spread = inst.uses_bid_ask or inst.spread > 0
    try:                                        # a pair's second leg (XAUUSD) has a real bid/ask spread
        from .loader import load_strategy
        from .pairs import is_pairs
        if is_pairs(load_strategy(job.strategy_path)):
            has_spread = True
    except (FileNotFoundError, OSError, SystemExit, ImportError):
        pass
    out = [("baseline", job),
           ("commission x2", job.with_(inst=inst.with_costs(commission=inst.commission * 2)))]
    if inst.slippage_ticks or not has_spread:
        out += [("slippage +1 tick", job.with_(inst=inst.with_costs(slippage_ticks=inst.slippage_ticks + 1))),
                ("slippage +2 ticks", job.with_(inst=inst.with_costs(slippage_ticks=inst.slippage_ticks + 2)))]
    if has_spread:
        out += [("spread x1.5", job.with_(settings=_s(s, spread_mult=1.5))),
                ("spread x2", job.with_(settings=_s(s, spread_mult=2.0))),
                ("spread x3", job.with_(settings=_s(s, spread_mult=3.0)))]
    out += [("delay 1 bar", job.with_(settings=_s(s, delay_bars=1))),
            ("delay 2 bars", job.with_(settings=_s(s, delay_bars=2)))]
    worst_inst = inst.with_costs(commission=inst.commission * 2, slippage_ticks=inst.slippage_ticks + 1)
    out.append(("ALL: costs x2 + slip +1" + (" + spread x2" if has_spread else "") + " + delay 1",
                job.with_(inst=worst_inst, settings=_s(s, delay_bars=1, spread_mult=2.0 if has_spread else 1.0))))
    return out


def _s(settings, **kw):
    from dataclasses import replace
    return replace(settings, **kw)


def _row(name, summ, base_net=None):
    net = summ.get("net_pnl", 0.0)
    return {"scenario": name, "trades": summ.get("trades", 0), "net_pnl": net,
            "change_vs_baseline": round(net - base_net, 2) if base_net is not None else None,
            "profit_factor": summ.get("profit_factor"), "win_rate_pct": summ.get("win_rate_pct"),
            "max_drawdown_usd": summ.get("max_drawdown_usd"), "sharpe": summ.get("sharpe_daily_ann"),
            "account_model": summ.get("account_model"), "capital_exhausted_on": summ.get("capital_exhausted_on"),
            "orders_refused": summ.get("notes", {}).get("orders_refused_capital_exhausted", 0)}


def run(job: Job, daily_bars: pd.DataFrame | None = None, workers=None) -> dict:
    sc = scenarios(job)
    res = run_many([j if k == 0 else j.with_(summary_only=True) for k, (_, j) in enumerate(sc)], workers)
    base = res[0]
    base_net = base["summary"].get("net_pnl", 0.0)
    table = pd.DataFrame([_row(n, r["summary"], base_net) for (n, _), r in zip(sc, res)])
    t = base["trades"]
    extra = {}
    if len(t):
        pnl = t.pnl.sort_values(ascending=False)
        rem = []
        for label, k in (("best 1% of trades removed", max(1, int(len(t) * .01))),
                         ("best 5% of trades removed", max(1, int(len(t) * .05))),
                         ("top 10 trades removed", min(10, len(t)))):
            rest = pnl.iloc[k:]
            gp, gl = rest[rest > 0].sum(), -rest[rest <= 0].sum()
            rem.append({"test": label, "trades_removed": k, "net_pnl": round(rest.sum(), 2),
                        "profit_factor": round(gp / gl, 3) if gl > 0 else None})
        extra["outlier_dependence"] = pd.DataFrame(rem)
        days = pd.to_datetime(t.exit_tday)
        daily = base.get("daily")
        if daily is not None and len(daily):
            dpnl = pd.Series(np.diff(np.concatenate([[daily.start_equity.iloc[0]], daily.equity.to_numpy()])),
                             index=pd.to_datetime(daily.tday))
        else:
            dpnl = _daily_pnl_from_trades(t, base["days"], job.settings, job.inst)
        per = []
        lo, hi = pd.to_datetime(base["days"]).min(), pd.to_datetime(base["days"]).max()
        for name, a, b in PERIODS:
            if pd.Timestamp(a) >= lo and pd.Timestamp(b) <= hi:
                m = (days >= a) & (days <= b)
                x = t.pnl[m]
                inside = dpnl[(dpnl.index >= a) & (dpnl.index <= b)]
                per.append({"period": name, "from": a, "to": b, "net_pnl": round(float(inside.sum()), 2),
                            "trades_closed": int(m.sum()),
                            "win_rate_pct": round(float((x > 0).mean() * 100), 1) if len(x) else None,
                            "worst_trade": round(x.min(), 2) if len(x) else None})
        extra["named_periods"] = pd.DataFrame(per)
        extra["worst_stretches"] = _stretches(dpnl)
        if daily_bars is not None and len(daily_bars):
            # one value per trading day (futures daily bars can be split at a contract switch)
            g = daily_bars.groupby(daily_bars.tday.to_numpy().astype("datetime64[D]"))
            day = pd.DataFrame({"h": g.h.max(), "l": g.l.min(), "c": g.c.last()})
            rng = (day.h - day.l) / day.c
            rng.index = pd.to_datetime(rng.index)
            hot = rng >= rng.quantile(.8)
            tag = hot.reindex(days.values).fillna(False).to_numpy()
            a, b = t.pnl[tag], t.pnl[~tag]
            extra["volatility_regime"] = pd.DataFrame([
                {"days": "most volatile 20% of days", "trades": len(a), "net_pnl": round(a.sum(), 2), "avg_trade": round(a.mean(), 2) if len(a) else None},
                {"days": "other 80% of days", "trades": len(b), "net_pnl": round(b.sum(), 2), "avg_trade": round(b.mean(), 2) if len(b) else None}])
    return {"scenarios": table, **extra, "baseline_trades": t, "baseline_commission": job.inst.commission}


def complete_months(dpnl: pd.Series) -> pd.Series:
    """Monthly P&L for COMPLETE calendar months only, on a continuous monthly index: a month is complete when the
    daily series has a row for every exchange trading day of that month (engine.calendar.trading_days: weekdays that
    are not exchange holidays). Incomplete months (data starting or ending inside them, or missing days or the whole
    month inside the history) are NaN, so a rolling window never bridges them."""
    if not len(dpnl):
        return pd.Series(dtype=float)
    idx = pd.DatetimeIndex(pd.to_datetime(dpnl.index)).normalize()
    s = pd.Series(np.asarray(dpnl, dtype=float), index=idx)
    have = set(idx)
    months = pd.period_range(idx.min().to_period("M"), idx.max().to_period("M"), freq="M")
    vals = []
    for mo in months:
        need = trading_days(mo.start_time, mo.end_time.normalize())
        ok = len(need) > 0 and all(d in have for d in need)
        vals.append(float(s[(idx >= mo.start_time) & (idx <= mo.end_time)].sum()) if ok else np.nan)
    return pd.Series(vals, index=months.to_timestamp(how="end").normalize())


def _stretches(dpnl: pd.Series) -> pd.DataFrame:
    """Worst month / rolling 3 and 12 months from daily P&L, over complete calendar months (dates shown). A rolling
    window counts only when ALL its months are complete; windows with none available are reported as n/a."""
    m = complete_months(dpnl)
    full = m.dropna()
    rows = []
    for label, w in (("worst calendar month", 1), ("worst rolling 3 months", 3), ("worst rolling 12 months", 12)):
        r = (m.rolling(w, min_periods=w).sum().dropna() if w > 1 else full)
        if len(r):
            end = r.idxmin()
            start = (end - pd.DateOffset(months=w - 1)).to_period("M").start_time
            rows.append({"window": label, "net_pnl": round(float(r.min()), 2),
                         "when": f"{start.date()} to {end.date()}"})
        else:
            rows.append({"window": label, "net_pnl": None,
                         "when": f"n/a ({len(full)} complete month(s), {len(m) - len(full)} incomplete; data "
                                 f"{dpnl.index.min().date() if len(dpnl) else '-'} to "
                                 f"{dpnl.index.max().date() if len(dpnl) else '-'}; a month is complete when every "
                                 "exchange trading day has a row)"})
    rows.append({"window": "losing months", "net_pnl": None,
                 "when": f"{int((full < 0).sum())} of {len(full)} complete months"
                         + (f" ({len(m) - len(full)} incomplete month(s) excluded)" if len(m) > len(full) else "")})
    return pd.DataFrame(rows)


def _daily_pnl_from_trades(trades, days, settings, inst) -> pd.Series:
    r0 = metrics.result_from_trades(trades, days, settings, inst)
    de = metrics.daily_equity(r0)
    dpnl = de.diff().fillna(de.iloc[0] - settings.capital)
    dpnl.index = pd.to_datetime(dpnl.index)
    return dpnl


def worst_stretches(trades: pd.DataFrame, days, settings, inst) -> pd.DataFrame:
    """Same as _stretches, from realized trade P&L (used when no equity curve is available)."""
    return _stretches(_daily_pnl_from_trades(trades, days, settings, inst))


def report(st: dict, out: Path, title: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    lines = [f"STRESS TEST: {title}", "", "1. Execution stress (full re-runs):", st["scenarios"].to_string(index=False)]
    st["scenarios"].to_csv(out / "stress_scenarios.csv", index=False)
    labels = {"outlier_dependence": "2. Dependence on the biggest winners:",
              "named_periods": "3a. Known turbulent periods inside the data:",
              "volatility_regime": "3b. Volatile vs normal days (daily range, top 20%):",
              "worst_stretches": "3c. Worst stretches:"}
    for k, lab in labels.items():
        if k in st and len(st[k]):
            lines += ["", lab, st[k].to_string(index=False)]
            st[k].to_csv(out / f"stress_{k}.csv", index=False)
    (out / "stress_report.txt").write_text("\n".join(lines) + "\n")
    summ = {"scenarios": st["scenarios"].to_dict("records")}
    for k in labels:
        if k in st:
            summ[k] = st[k].to_dict("records")
    (out / "stress_summary.json").write_text(json.dumps(summ, indent=2, default=str))
    return summ
