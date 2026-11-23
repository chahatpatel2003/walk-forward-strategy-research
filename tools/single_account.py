"""Several strategies traded together on ONE account, risking a fixed % of the account balance per trade (compounding).

Replays saved out-of-sample trades (walkforward_oos_trades.csv): the entry/exit times and prices are the engine's,
only the SIZE changes.
  * Balance = starting capital + every trade closed before this entry (all strategies share it).
  * Risk per trade = risk_pct x balance. Stop distance = the trade's own stop (|entry - sl|) when it has one; otherwise
    `atr_k` x ATR(`atr_len`) of the run's own bars at the decision bar (the bar before the entry bar: known then).
    Without a hard stop this is a SIZING rule only: a loss can be larger than the risk.
  * Quantity = risk / (stop distance x point value), rounded DOWN to the instrument's step (whole MNQ/MGC contracts,
    0.01 XAUUSD/NAS100 lots). If even the minimum size would risk more than the budget, the trade is skipped.
  * P&L = new quantity x the trade's per-unit P&L after costs (commission, rolls, slippage and spread are all per unit).
  * Account marked to market at each day's close (adjusted daily close of the market). If equity reaches $0 trading
    stops. Margin is NOT modelled: gross exposure and leverage are reported so you can judge it.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from engine import data, get_instrument  # noqa: E402

_BARS: dict = {}


def bars_for(market: str, tf: int, session: str) -> pd.DataFrame:
    k = (market, tf, session)
    if k not in _BARS:
        inst = get_instrument(market)
        _BARS[k] = data.resample(data.load(inst.data_key), tf, session).reset_index(drop=True)
    return _BARS[k]


def atr(b: pd.DataFrame, n: int) -> np.ndarray:
    """Wilder ATR on bar i uses bars <= i only."""
    pc = b.c.shift(1)
    tr = np.maximum(b.h - b.l, np.maximum((b.h - pc).abs(), (b.l - pc).abs())).fillna(b.h - b.l)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy()


def stop_distance(t: pd.DataFrame, market: str, tf: int, session: str, atr_k: float, atr_len: int) -> pd.Series:
    """Per trade: |entry - sl| where the trade has a stop, else atr_k x ATR at the decision bar."""
    have = t.sl.notna() if "sl" in t else pd.Series(False, index=t.index)
    dist = (t.entry_px - t.sl).abs().where(have) if "sl" in t else pd.Series(np.nan, index=t.index)
    if (~have).any():
        b = bars_for(market, tf, session)
        a = atr(b, atr_len)
        ts = (pd.to_datetime(t.entry_time, utc=True) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
        j = np.searchsorted(b.ts.to_numpy(), ts.to_numpy())          # the entry bar
        ok = (j < len(b)) & (b.ts.to_numpy()[np.minimum(j, len(b) - 1)] == ts.to_numpy())
        dec = np.where(ok, j - 1, -1)                                  # the decision bar
        v = np.where(dec >= 0, a[np.maximum(dec, 0)], np.nan)
        dist = dist.where(have, pd.Series(atr_k * v, index=t.index))
    return dist


def daily_close(market: str) -> pd.Series:
    b = bars_for(market, 1440, "full")
    g = b.groupby(b.tday.to_numpy().astype("datetime64[D]"))
    s = g.c.last()
    s.index = pd.to_datetime(s.index)
    return s


def daily_raw(market: str) -> pd.Series:
    b = bars_for(market, 1440, "full")
    col = "raw_c" if "raw_c" in b else "c"
    g = b.groupby(b.tday.to_numpy().astype("datetime64[D]"))
    s = g[col].last()
    s.index = pd.to_datetime(s.index)
    return s


def simulate(runs: list[dict], capital: float, risk_pct: float, start=None, end=None, max_lev: float | None = None) -> dict:
    """runs: dicts with name, market, trades (DataFrame with stop_dist). Trades entered in [start, end].
    max_lev: optional cap on ONE position's contract value (quantity x real price x point value, at the entry day's
    real close) as a multiple of the balance; the quantity is cut down to it (rounded down)."""
    rows = []
    for r in runs:
        t = r["trades"].copy()
        t["run"], t["market"] = r["name"], r["market"]
        rows.append(t)
    T = pd.concat(rows, ignore_index=True)
    T["entry_time"] = pd.to_datetime(T.entry_time, utc=True)
    T["exit_time"] = pd.to_datetime(T.exit_time, utc=True)
    if start is not None:
        T = T[(pd.to_datetime(T.entry_tday) >= pd.Timestamp(start)) & (pd.to_datetime(T.entry_tday) <= pd.Timestamp(end))]
    T = T.reset_index(drop=True)
    T["unit_pnl"] = (T.pnl_gross - T.costs) / T.qty                      # per contract / lot, after costs
    # at one timestamp: exits of earlier positions, then entries, then exits of positions opened at that same
    # timestamp (entered and closed inside one bar)
    ev = [(x, 1, i) for i, x in enumerate(T.entry_time)] + \
         [(x, 2 if x <= T.entry_time[i] else 0, i) for i, x in enumerate(T.exit_time)]
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    bal, broke = capital, None
    qty = np.zeros(len(T)); risk = np.zeros(len(T)); skipped = {}
    for when, kind, i in ev:
        if kind == 1:
            if broke is not None:
                skipped["account at $0"] = skipped.get("account at $0", 0) + 1; continue
            inst = get_instrument(T.market[i])
            d = T.stop_dist[i]
            if not (d > 0):
                skipped["no stop distance (no ATR yet)"] = skipped.get("no stop distance (no ATR yet)", 0) + 1; continue
            budget = bal * risk_pct / 100.0
            q = budget / (d * inst.point_value)
            if max_lev is not None:
                raw = daily_raw(T.market[i]).reindex([pd.Timestamp(T.entry_tday[i])], method="ffill").iloc[0]
                q = min(q, max_lev * bal / (abs(raw) * inst.point_value))
            q = np.floor(q / inst.qty_step + 1e-9) * inst.qty_step
            if q < inst.qty_step - 1e-12:
                skipped[f"{T.market[i]}: one minimum size exceeds the {risk_pct}% risk (or the size cap)"] = \
                    skipped.get(f"{T.market[i]}: one minimum size exceeds the {risk_pct}% risk (or the size cap)", 0) + 1
                continue
            qty[i], risk[i] = q, q * d * inst.point_value
        elif qty[i] > 0:                                                # an exit
            bal += qty[i] * T.unit_pnl[i]
            if bal <= 0 and broke is None:
                broke = when
    T["new_qty"], T["risk_usd_new"] = qty, risk
    T["new_pnl"] = qty * T.unit_pnl
    taken = T[T.new_qty > 0].copy()
    # daily marked equity
    first = pd.to_datetime(T.entry_tday).min() if start is None else pd.Timestamp(start)
    last = max(pd.to_datetime(T.exit_tday).max(), first) if end is None else pd.Timestamp(end)
    days = pd.DatetimeIndex(sorted(set().union(*[set(daily_close(m).index) for m in T.market.unique()])))
    days = days[(days >= first) & (days <= max(last, pd.to_datetime(taken.exit_tday).max() if len(taken) else last))]
    realized = pd.Series(0.0, index=days)
    ex = taken.groupby(pd.to_datetime(taken.exit_tday)).new_pnl.sum()
    realized = realized.add(ex.reindex(days).fillna(0.0), fill_value=0.0).cumsum() + capital
    openm = np.zeros(len(days)); gross = np.zeros(len(days)); nopen = np.zeros(len(days), dtype=int)
    for m, g in taken.groupby("market"):
        inst = get_instrument(m)
        dc = daily_close(m).reindex(days).ffill().to_numpy()
        rc = daily_raw(m).reindex(days).ffill().to_numpy()
        side = np.where(g.side == "long", 1.0, -1.0)
        for (ed, xd, q, px, sd) in zip(pd.to_datetime(g.entry_tday), pd.to_datetime(g.exit_tday), g.new_qty, g.entry_px, side):
            on = (days >= ed) & (days < xd)                              # still open at that day's close
            openm += np.where(on, (dc - px) * sd * q * inst.point_value, 0.0)
            gross += np.where(on, q * rc * inst.point_value, 0.0)
            nopen += on
    eq = pd.Series(realized.to_numpy() + openm, index=days)
    peak = np.maximum.accumulate(np.r_[capital, eq.to_numpy()])[1:]
    dd = eq - peak
    ddp = (eq / peak - 1) * 100
    months = max((days[-1] - days[0]).days / 30.4375, 1e-9) if len(days) else np.nan
    monthly = eq.resample("ME").last().diff().fillna(eq.resample("ME").last().iloc[0] - capital) if len(eq) else pd.Series(dtype=float)
    lev = gross / np.maximum(eq.to_numpy(), 1e-9)
    # positions and contract value open at the same MOMENT (entry/exit timestamps; a day-close count misses intraday
    # positions), against the balance at that moment
    ev2, bal2, cur_n, cur_v, best_n, best_lev = [], capital, 0, 0.0, 0, 0.0
    for i, r in taken.iterrows():
        inst = get_instrument(r.market)
        raw = daily_raw(r.market).reindex([pd.Timestamp(r.entry_tday)], method="ffill").iloc[0]
        v = r.new_qty * abs(raw) * inst.point_value
        same = r.exit_time <= r.entry_time
        ev2 += [(r.entry_time, 1, v, 0.0), (r.exit_time, 2 if same else 0, -v, r.new_pnl)]
    for when, kind, dv, pnl in sorted(ev2, key=lambda e: (e[0], e[1])):
        cur_n += 1 if kind == 1 else -1
        cur_v += dv
        bal2 += pnl
        best_n = max(best_n, cur_n)
        best_lev = max(best_lev, cur_v / max(bal2, 1e-9))
    loss_r = (taken.new_pnl / taken.risk_usd_new)
    out = {
        "start": str(days[0].date()) if len(days) else None, "end": str(days[-1].date()) if len(days) else None,
        "months": round(months, 1), "capital": capital, "risk_pct": risk_pct,
        "trades_offered": int(len(T)), "trades_taken": int(len(taken)), "trades_per_month": round(len(taken) / months, 1),
        "skipped": skipped, "final_equity": round(float(eq.iloc[-1]), 2) if len(eq) else capital,
        "net": round(float(eq.iloc[-1] - capital), 2) if len(eq) else 0.0,
        "return_pct": round(float(eq.iloc[-1] / capital - 1) * 100, 1) if len(eq) else 0.0,
        "cagr_pct": round(float((eq.iloc[-1] / capital) ** (12 / months) - 1) * 100, 1) if len(eq) and eq.iloc[-1] > 0 else None,
        "max_dd_usd": round(float(dd.min()), 2), "max_dd_pct": round(float(ddp.min()), 1),
        "win_pct": round(float((taken.new_pnl > 0).mean() * 100), 1) if len(taken) else None,
        "avg_win_r": round(float(loss_r[taken.new_pnl > 0].mean()), 2) if (taken.new_pnl > 0).any() else None,
        "avg_loss_r": round(float(loss_r[taken.new_pnl <= 0].mean()), 2) if (taken.new_pnl <= 0).any() else None,
        "worst_trade_r": round(float(loss_r.min()), 2) if len(taken) else None,
        "losses_bigger_than_risk": int((loss_r < -1.0).sum()),
        "profit_factor": round(float(taken.new_pnl[taken.new_pnl > 0].sum() / -taken.new_pnl[taken.new_pnl < 0].sum()), 2)
        if (taken.new_pnl < 0).any() else None,
        "profitable_months": f"{int((monthly > 0).sum())} of {len(monthly)}",
        "worst_month": f"{monthly.idxmin():%Y-%m} {monthly.min():,.0f}" if len(monthly) else None,
        "max_open_positions": int(best_n), "max_open_at_day_close": int(nopen.max()) if len(nopen) else 0,
        "max_leverage_any_time": round(float(best_lev), 1),
        "max_gross_exposure": round(float(gross.max()), 0), "max_leverage": round(float(lev.max()), 1),
        "median_leverage": round(float(np.median(lev)), 1),
        "account_hit_zero_on": str(broke) if broke is not None else None,
    }
    per = taken.groupby("run").agg(trades=("new_pnl", "size"), net=("new_pnl", "sum"),
                                   win_pct=("new_pnl", lambda x: (x > 0).mean() * 100),
                                   median_qty=("new_qty", "median"))
    offered = T.groupby("run").size()
    per = per.reindex(offered.index).fillna({"trades": 0, "net": 0.0})
    per.insert(0, "offered", offered)
    return {"summary": out, "per_run": per.round(2), "equity": eq, "trades": T}
