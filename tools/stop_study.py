"""Re-run the runs selected for the two timeframe-study books (tools/timeframe_portfolio.pick) through the FULL study
pipeline (full history, parameter grid with look-ahead gate, walk-forward, Monte Carlo, stress, checklist) with a hard
stop-loss added: SignalStrategy stop_atr=K. A12 already has its own stop: its saved runs are used as they are.
Rows -> results/SINGLE_ACCOUNT/stop_rows.csv, run folders under results/SINGLE_ACCOUNT/stop_runs/<bars>m/<session>/.

    python tools/stop_study.py --k 2 --workers 4
"""
import argparse
import sys
import time
import traceback
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import photo_study as ps  # noqa: E402
import timeframe_portfolio as tp  # noqa: E402
from timeframe_report import load  # noqa: E402

OUT = ROOT / "results" / "SINGLE_ACCOUNT"
KEY = ("strategy", "market", "session", "bars")


def selected() -> pd.DataFrame:
    r = load()
    sel = pd.concat([tp.pick(r, m) for m in tp.BOOKS.values()], ignore_index=True)
    return sel.drop_duplicates(list(KEY)).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=float, default=2.0)
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    rows_path = OUT / "stop_rows.csv"
    OUT.mkdir(parents=True, exist_ok=True)
    done = pd.read_csv(rows_path) if rows_path.exists() else pd.DataFrame(columns=list(KEY) + ["error"])
    have = set(map(tuple, done[done.error.isna()][list(KEY)].astype(str).to_numpy()))
    sel = selected()
    sel = sel[sel.code != "A12"].reset_index(drop=True)
    print(f"{len(sel)} configurations; {len(have)} already done")
    for k, s in enumerate(sel.itertuples(), 1):
        key = (s.strategy, s.market, s.session, s.bars)
        if key in have:
            continue
        tf = int(s.bars[:-1])
        extra = {"stop_atr": a.k}
        print(f"\n######## [{k}/{len(sel)}] {s.strategy} {s.market} {s.session} {s.bars} extra={extra}", flush=True)
        t0 = time.time()
        try:
            row = ps.run_one(ROOT / "strategies" / "photos" / f"{s.strategy}.py", s.market, s.session, a.workers, tf=tf,
                             out_root=OUT / "stop_runs" / f"{tf}m", extra=extra)
            row["error"] = None
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            row = {"strategy": s.strategy, "market": s.market, "session": s.session, "bars": s.bars,
                   "error": f"{type(e).__name__}: {e}"}
            traceback.print_exc()
        row["stop_atr"] = extra.get("stop_atr")
        row["seconds"] = round(time.time() - t0, 1)
        ps.save_row(rows_path, row, KEY)
    print(f"rows -> {rows_path}")


if __name__ == "__main__":
    main()
