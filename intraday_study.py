"""Intraday study: the photo strategies traded strictly INTRADAY on the New York cash session (09:30-16:00) with
`flat_at=15:55` (every position closed before the close, nothing held overnight, no entry on the last bars), on 1-, 5-,
15- and 60-minute bars. Same pipeline as the other studies (photo_study.run_one: full history, grid + look-ahead gate,
walk-forward, Monte Carlo, stress, checklist); percentage thresholds scaled to the bar size as in the timeframe study.
A08-A10 (weekly/monthly calendar rules) can't be intraday and are left out; A13 is intraday already (see the
timeframe study); B01 (pair) is not included.

    python intraday_study.py --workers 4                  # resumes: a configuration already saved is not redone
    python intraday_study.py --only a01 --tfs 5
Rows -> results/INTRADAY_STUDY/rows.csv, run folders under results/INTRADAY_STUDY/<bars>m/rth/.
"""
import argparse
import time
import traceback
from pathlib import Path

import pandas as pd

import photo_study as ps
from engine.loader import load_strategy

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results" / "INTRADAY_STUDY"
STRATS = ("a01", "a02", "a03", "a04", "a05", "a06", "a07", "a11", "a12")
TFS = (1, 5, 15, 60)
FLAT_AT = 15 * 60 + 55
KEY = ("strategy", "market", "session", "bars")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*"); ap.add_argument("--tfs", nargs="*", type=int)
    ap.add_argument("--markets", nargs="*"); ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows_path = OUT / "rows.csv"
    done = pd.read_csv(rows_path) if rows_path.exists() else pd.DataFrame(columns=list(KEY) + ["error"])
    have = set(map(tuple, done[done.error.isna()][list(KEY)].astype(str).to_numpy()))
    todo = []
    for path in sorted((ROOT / "strategies/photos").glob("[a][0-9]*.py")):
        if path.stem[:3] not in STRATS or (a.only and path.stem[:3] not in a.only):
            continue
        cls = load_strategy(str(path))
        for tf in TFS:
            if a.tfs and tf not in a.tfs:
                continue
            for sym in getattr(cls, "MARKETS", ps.DEFAULT_MARKETS):
                if a.markets and sym not in a.markets:
                    continue
                if (path.stem, sym, "rth", f"{tf}m") not in have:
                    todo.append((path, sym, tf))
    print(f"intraday study: {len(todo)} runs to do ({len(have)} saved)", flush=True)
    for k, (path, sym, tf) in enumerate(todo, 1):
        t0 = time.time()
        print(f"\n######## [{k}/{len(todo)}] {path.stem} on {sym} (rth, {tf}m, flat at 15:55)", flush=True)
        try:
            row = ps.run_one(path, sym, "rth", a.workers, tf=tf, out_root=OUT / f"{tf}m", extra={"flat_at": FLAT_AT})
            row["error"] = None
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            row = {"strategy": path.stem, "market": sym, "session": "rth", "bars": f"{tf}m", "error": f"{type(e).__name__}: {e}"}
            traceback.print_exc()
        row["seconds"] = round(time.time() - t0, 1)
        ps.save_row(rows_path, row, KEY)
    print(f"\nrows -> {rows_path}")


if __name__ == "__main__":
    main()
