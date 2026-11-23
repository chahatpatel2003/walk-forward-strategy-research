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
    session: str = "full"             # 'full' (every bar) or 'rth' (New York cash session only)

    def with_(self, **kw):
        return replace(self, **kw)


_DF: dict = {}
_STRAT: dict = {}


FRAME_CACHE = 2          # bar tables kept per worker (most recently used); bounds memory across many markets/timeframes


def _frame(key: str, tf: int, session: str = "full") -> pd.DataFrame:
    k = (key, tf, session)
    if k in _DF:
        _DF[k] = _DF.pop(k)                               # most recently used goes last
        return _DF[k]
    while len(_DF) >= FRAME_CACHE:
        _DF.pop(next(iter(_DF)))                          # drop the least recently used table
    if "+" in key:                                        # a pair of markets, e.g. "GC+XAUUSD"
        from .pairs import load_pair
        _DF[k] = load_pair(*key.split("+"), tf=tf, session=session)
    else:
        _DF[k] = data.resample(data.load(key), tf, session)
    return _DF[k]


def run_job(job: Job) -> dict:
    df = _frame(job.data_key, job.tf, job.session)
    tday = df.tday.to_numpy().astype("datetime64[D]")
    lo = np.datetime64(job.start) - np.timedelta64(job.warmup_days, "D") if job.start else tday[0]
    hi = np.datetime64(job.end) if job.end else tday[-1]
    a, b = np.searchsorted(tday, lo, "left"), np.searchsorted(tday, hi, "right")
    count_from = np.datetime64(job.start) if job.start else tday[0]
    first_scored = np.searchsorted(tday, count_from, "left")
    if job.strategy_path not in _STRAT:
        _STRAT[job.strategy_path] = load_strategy(job.strategy_path)
    strat = _STRAT[job.strategy_path](**job.params)
    short_warmup = False
    if job.start:
        a, short_warmup = warmup_start(tday, first_scored, job.warmup_days, strat.warmup_bars())
    days = np.unique(tday[max(a, first_scored):b])
    if b <= max(a, first_scored):
        empty = metrics.result_from_trades(pd.DataFrame(), days, job.settings, job.inst)
        return {"params": strat.p, "tag": job.tag, "summary": {"trades": 0}, "trades": pd.DataFrame(),
                "daily": None, "bars": None, "days": days, "job": job, "notes": {}}
    settings = replace(job.settings, trade_start_ts=int(df.ts.iloc[first_scored]) if first_scored > a else None)
    from .pairs import PairsEngine, is_pairs
    if is_pairs(type(strat)):
        from .instruments import get as get_instrument
        res = PairsEngine(df.iloc[a:b], job.inst, get_instrument(type(strat).INST_B), strat, settings).run()
    else:
        res = Engine(df.iloc[a:b], job.inst, strat, settings).run()
    if short_warmup:
        res["notes"]["insufficient_warmup"] = True
    trades = res["trades"]
    eq = res["equity"]
    scored = eq[eq.tday.to_numpy().astype("datetime64[D]") >= count_from]
    start_equity = float(eq.equity.iloc[len(eq) - len(scored) - 1]) if len(scored) < len(eq) else job.settings.capital
    bars = scored[["tday", "equity_open", "equity_low", "equity"] + (["breach"] if "breach" in scored else [])].reset_index(drop=True)
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


def warmup_start(tday: np.ndarray, first_scored: int, warmup_days: int, warmup_bars: int = 0) -> tuple[int, bool]:
    """Index of the first bar to load: `warmup_days` calendar days before the scored window, and at least
    `warmup_bars` bars before it. Returns (index, True if the data doesn't have enough bars before the window)."""
    by_days = int(np.searchsorted(tday, tday[first_scored] - np.timedelta64(warmup_days, "D"), "left")) \
        if first_scored < len(tday) else first_scored
    want = min(by_days, first_scored - warmup_bars)
    return max(want, 0), want < 0


def _ram_gb() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError):
        return 8.0


# Measured peak resident memory of one worker process (cold start: load 1-minute data, resample, run one backtest),
# GB, on this Mac: NQ 5m 0.96, GC 5m 1.47, NAS100 5m 0.80, XAUUSD 5m 1.11, NQ 1m cash 1.01, GC+XAUUSD pair 5m 2.01.
# The largest (the pair) is the default budget; FRAME_CACHE keeps a worker from accumulating tables.
WORKER_PEAK_GB = 2.0


def default_workers(per_worker_gb: float | None = None) -> int:
    """Workers that fit in 60% of RAM at the measured per-worker peak, leaving cores for the system."""
    per = per_worker_gb or WORKER_PEAK_GB
    return max(1, min((os.cpu_count() or 2) - 2, int(_ram_gb() * 0.6 / per), 8))


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
