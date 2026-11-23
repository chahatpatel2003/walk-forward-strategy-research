"""Timeframe study: every photo strategy on 5-minute, 15-minute, 1-hour, 4-hour and daily bars, through the same
pipeline as photo_study.py (full history, parameter test, walk-forward, Monte Carlo, stress), account-constrained,
$100,000, on MNQ, NAS100, MGC and XAUUSD (strategy-specific markets and sessions as declared).

Translating a rule to another bar size:
  - lengths stay in BARS (RSI(3) on 5-minute bars = the last three 5-minute bars);
  - thresholds the strategy declares as a % of price (PRICE_PCT) are scaled by sqrt(bar minutes / native bar
    minutes) (a daily bar spans one session: 390 minutes cash, 1380 full), see photo_study.pct_scale;
  - calendar strategies (A8 weekly RSI, A9 turn of the month, A10 10-month MA) decide once per week/month on fixed
    dates: on intraday bars they would take the same trades (or compute weekly values from intraday bars, which is
    meaningless), so they are run on daily bars only;
  - A13 needs aggressor volume on the cash session (MNQ only): 1, 5, 15 and 60-minute bars (4-hour and daily bars
    leave too few samples for its rolling regression).

Results: results/TIMEFRAME_STUDY/rows.csv (one row per strategy, market, session, bar size; resumable: rows whose
code and data fingerprints still match are reused; failures are retried) and one folder per run.
    python timeframe_study.py [--only a01 a06] [--tfs 5 60] [--markets MNQ] [--workers 4] [--fresh]
"""
import argparse
import sys
import time
import traceback
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import photo_study as ps  # noqa: E402
from engine import get_instrument  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from engine.pairs import is_pairs, pair_key  # noqa: E402

OUT = ROOT / "results" / "TIMEFRAME_STUDY"
TFS = (5, 15, 60, 240, 1440)
CALENDAR = ("a08", "a09", "a10")
KEY = ("strategy", "market", "session", "bars")


def timeframes(stem: str, native: int) -> list[int]:
    if stem.startswith(CALENDAR):
        return [1440]
    if stem.startswith("a13"):
        return [1, 5, 15, 60]
    return sorted(set(TFS) | {native})


def plan(a, rows: pd.DataFrame) -> list[tuple]:
    paths = sorted((ROOT / "strategies/photos").glob("[ab][0-9]*.py"))
    if a.only:
        paths = [p for p in paths if any(p.stem.startswith(x) for x in a.only)]
    todo = []
    for path in paths:
        cls = load_strategy(str(path))
        for tf in timeframes(path.stem, getattr(cls, "TF", 1440)):
            if a.tfs and tf not in a.tfs:
                continue
            for sym in getattr(cls, "MARKETS", ps.DEFAULT_MARKETS):
                if a.markets and sym not in a.markets:
                    continue
                key = pair_key(cls) if is_pairs(cls) else get_instrument(sym).data_key
                v = ps.versions(path, key)
                for session in getattr(cls, "SESSIONS", ("full",)):
                    if a.keys is not None:          # targeted re-runs: exactly these configurations, always
                        if f"{path.stem}:{sym}:{session}:{tf}" in a.keys:
                            todo.append((path, sym, session, tf, v))
                        continue
                    same = rows[(rows.strategy == path.stem) & (rows.market == sym) & (rows.session == session)
                                & (rows.bars == f"{tf}m")] if len(rows) else rows
                    valid = bool(len(same)) and same.error.isna().all() \
                        and (same.code_version == v["code_version"]).all() and (same.data_version == v["data_version"]).all()
                    if a.fresh or not valid:
                        todo.append((path, sym, session, tf, v))
    return todo


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*"); ap.add_argument("--markets", nargs="*")
    ap.add_argument("--tfs", nargs="*", type=int); ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--keys", nargs="*", default=None,
                    help="re-run exactly these configurations (strategy_stem:MARKET:session:minutes), e.g. "
                         "a05_zscore_mean_reversion:MGC:rth:15")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows_path = OUT / "rows.csv"
    rows = pd.read_csv(rows_path) if rows_path.exists() else pd.DataFrame()
    todo = plan(a, rows)
    print(f"timeframe study: {len(todo)} runs to do (saved rows that are still valid are reused)")
    for k, (path, sym, session, tf, v) in enumerate(todo, 1):
        t0 = time.time()
        print(f"\n######## [{k}/{len(todo)}] {path.stem} on {sym} ({session}, {tf}m)", flush=True)
        try:
            row = ps.run_one(path, sym, session, a.workers, tf=tf, out_root=OUT / f"{tf}m")
            row["error"] = None
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            row = {"strategy": path.stem, "market": sym, "session": session, "bars": f"{tf}m", "error": f"{type(e).__name__}: {e}"}
            traceback.print_exc()
        row.update(v)
        row["seconds"] = round(time.time() - t0, 1)
        ps.save_row(rows_path, row, KEY)
    print(f"\nrows -> {rows_path}")


if __name__ == "__main__":
    main()
