"""Run many backtests in parallel (parameter tests, walk-forward, stress tests).

A Job describes one backtest on one window of data. Each worker process loads the 1-minute
data once (from cache/) and reuses it for every job it receives.

Windows: the backtest runs on [start - warmup_days, end] so indicators are warmed up, but only
trades ENTERED on or after `start` are counted. Results are scored on realized P&L per trading day.
"""
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace
import multiprocessing as mp

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
    win = df.iloc[a:b]
    count_from = np.datetime64(job.start) if job.start else tday[0]
    if job.strategy_path not in _STRAT:
        _STRAT[job.strategy_path] = load_strategy(job.strategy_path)
    strat = _STRAT[job.strategy_path](**job.params)
    if len(win) == 0:
        trades, skipped = pd.DataFrame(), {}
    else:
        res = Engine(win, job.inst, strat, job.settings).run()
        trades, skipped = res["trades"], res["skipped"]
        if len(trades):
            trades = trades[trades.entry_tday.to_numpy().astype("datetime64[D]") >= count_from].reset_index(drop=True)
    days = np.unique(tday[a:b])
    days = days[days >= count_from]
    r = metrics.result_from_trades(trades, days, job.settings, job.inst, skipped)
    summ = metrics.summarize(r) if len(days) else {"trades": 0}
    return {"params": strat.p, "tag": job.tag, "summary": summ, "trades": trades,
            "days": days, "job": job}


def default_workers() -> int:
    """Each worker needs about 1.5 GB for 1-minute data; leave headroom for the system."""
    try:
        ram_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError):
        ram_gb = 8
    return max(1, min((os.cpu_count() or 2) - 2, int(ram_gb * 0.6 / 1.5), 8))


def run_many(jobs: list[Job], workers: int | None = None, progress: bool = True) -> list[dict]:
    """Run jobs, return results in the same order."""
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
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs)), mp_context=mp.get_context("spawn")) as ex:
        futs = {ex.submit(run_job, j): k for k, j in enumerate(jobs)}
        done = 0
        from concurrent.futures import as_completed
        for f in as_completed(futs):
            out[futs[f]] = f.result()
            done += 1
            if progress:
                print(f"\r  {done}/{len(jobs)} runs ({workers} workers)", end="", flush=True)
    if progress:
        print()
    return out
