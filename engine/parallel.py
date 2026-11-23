"""Run many backtests in parallel (parameter tests, walk-forward, stress tests).

A Job describes one backtest on one window of data. Each worker process loads the 1-minute
data once (from cache/) and reuses it; the process pool itself is reused between calls.

Windows: the backtest runs on [start - warmup_days, end] so indicators are warmed up. Orders placed
before `start` are ignored (Settings.trade_start_ts), so warm-up can never open a position that blocks
or distorts the scored window. Results use the per-bar marked-to-market equity of the scored days only (exact drawdown walk).
"""
import atexit
import multiprocessing as mp
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from . import data, metrics
from .core import Engine, Settings
from .instruments import Instrument
from .loader import load_strategy


@dataclass
class Job:
    strategy_path: str
    data_key: str
    tf: int
    inst: Instrument
    settings: Settings
    params: dict = field(default_factory=dict)
    start: str | None = None          # first trading day whose entries count (inclusive)
    end: str | None = None            # last trading day (inclusive)
    warmup_days: int = 10             # calendar days of extra history loaded before `start`
    tag: dict = field(default_factory=dict)   # free-form labels carried to the result
    summary_only: bool = False        # True: return only the summary (parameter search)

    def with_(self, **kw):
        return replace(self, **kw)


_DF: dict = {}
_STRAT: dict = {}


def _frame(key: str, tf: int) -> pd.DataFrame:
    if (key, tf) not in _DF:
        _DF[(key, tf)] = data.resample(data.load(key), tf)
    return _DF[(key, tf)]


def run_job(job: Job) -> dict:
    df = _frame(job.data_key, job.tf)
    tday = df.tday.to_numpy().astype("datetime64[D]")
    lo = np.datetime64(job.start) - np.timedelta64(job.warmup_days, "D") if job.start else tday[0]
    hi = np.datetime64(job.end) if job.end else tday[-1]
    a, b = np.searchsorted(tday, lo, "left"), np.searchsorted(tday, hi, "right")
    count_from = np.datetime64(job.start) if job.start else tday[0]
    first_scored = np.searchsorted(tday, count_from, "left")
    if job.strategy_path not in _STRAT:
        _STRAT[job.strategy_path] = load_strategy(job.strategy_path)
    strat = _STRAT[job.strategy_path](**job.params)
    days = np.unique(tday[max(a, first_scored):b])
    if b <= max(a, first_scored):
        empty = metrics.result_from_trades(pd.DataFrame(), days, job.settings, job.inst)
        return {"params": strat.p, "tag": job.tag, "summary": {"trades": 0}, "trades": pd.DataFrame(),
                "daily": None, "bars": None, "days": days, "job": job, "notes": {}}
    settings = replace(job.settings, trade_start_ts=int(df.ts.iloc[first_scored]) if first_scored > a else None)
    res = Engine(df.iloc[a:b], job.inst, strat, settings).run()
    trades = res["trades"]
    eq = res["equity"]
    scored = eq[eq.tday.to_numpy().astype("datetime64[D]") >= count_from]
    start_equity = float(eq.equity.iloc[len(eq) - len(scored) - 1]) if len(scored) < len(eq) else job.settings.capital
    bars = scored[["tday", "equity_open", "equity_low", "equity"]].reset_index(drop=True)
    bars["tday"] = bars.tday.to_numpy().astype("datetime64[D]")
    shift = job.settings.capital - start_equity
    r = metrics.result_from_bars(trades, bars.assign(**{c: bars[c] + shift for c in ("equity_open", "equity_low", "equity")}),
                                 job.settings, job.inst, res["skipped"], res["notes"])
    bars["start_equity"] = start_equity
    g = bars.groupby("tday").equity.last()
    daily = pd.DataFrame({"tday": g.index.to_numpy().astype("datetime64[D]"), "equity": g.to_numpy(), "start_equity": start_equity})
    summ = metrics.summarize(r)
    if job.summary_only:
        return {"params": strat.p, "tag": job.tag, "summary": summ, "job": job}
    return {"params": strat.p, "tag": job.tag, "summary": summ, "trades": trades, "daily": daily, "bars": bars,
            "days": days, "job": job, "notes": res["notes"]}


def default_workers() -> int:
    """Each worker needs about 1.5 GB for 1-minute data; leave headroom for the system."""
    try:
        ram_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError):
        ram_gb = 8
    return max(1, min((os.cpu_count() or 2) - 2, int(ram_gb * 0.6 / 1.5), 8))


_POOL: dict = {}


def _pool(workers: int) -> ProcessPoolExecutor:
    if workers not in _POOL:
        for p in _POOL.values():
            p.shutdown()
        _POOL.clear()
        _POOL[workers] = ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn"))
    return _POOL[workers]


@atexit.register
def _close_pools():
    for p in _POOL.values():
        p.shutdown(cancel_futures=True)


def run_many(jobs: list[Job], workers: int | None = None, progress: bool = True) -> list[dict]:
    """Run jobs, return results in the same order."""
    if not jobs:
        return []
    workers = workers or default_workers()
    if workers <= 1 or len(jobs) == 1:
        out = []
        for k, j in enumerate(jobs):
            out.append(run_job(j))
            if progress:
                print(f"\r  {k + 1}/{len(jobs)} runs", end="", flush=True)
        if progress:
            print()
        return out
    out = [None] * len(jobs)
    ex = _pool(workers)
    futs = {ex.submit(run_job, j): k for k, j in enumerate(jobs)}
    for done, f in enumerate(as_completed(futs), 1):
        out[futs[f]] = f.result()
        if progress:
            print(f"\r  {done}/{len(jobs)} runs ({workers} workers)", end="", flush=True)
    if progress:
        print()
    return out
