"""Re-run the studies' look-ahead gate (robust.lookahead_gate: the base parameters and every grid set, up to 40, on the
whole period, with the current check: fixed, early, signal-flip and decision-bar cuts) for saved study rows, without
re-running the backtests. Prints one line per configuration and writes a CSV.

    python tools/recheck_lookahead.py --rows results/TIMEFRAME_STUDY/rows.csv --out results/TIMEFRAME_STUDY/lookahead_recheck.csv
    python tools/recheck_lookahead.py --rows ... --only a01 --bars 5m --market MNQ
    python tools/recheck_lookahead.py --rows ... --mode boundary      # only the new boundary cuts (much faster)
"""
import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import photo_study  # noqa: E402
import robust  # noqa: E402
from engine import sweep  # noqa: E402


def boundary_gate(a, job, df, extra) -> str:
    """The new part of the gate only (core.check_boundary_cuts), on exactly the gate's parameter sets and bars."""
    import numpy as np
    from engine import data, get_instrument
    from engine.core import check_boundary_cuts
    from engine.loader import load_strategy
    from engine.pairs import PairsEngine, is_pairs, load_pair
    cls = load_strategy(a.strategy)
    every = [job.params] + [{**job.params, **p} for p in extra]
    uniq = []
    for p in every:
        if p not in uniq:
            uniq.append(p)
    sets = uniq if len(uniq) <= 40 else [uniq[int(k)] for k in np.linspace(0, len(uniq) - 1, 40)]
    pairs = is_pairs(cls)
    bars = load_pair(*cls.LEGS, tf=a.tf, session=a.session) if pairs else data.resample(df, a.tf, a.session)
    cuts, rows = [], []
    for params in sets:
        cov = {}
        kw = dict(engine=PairsEngine, run_args=(get_instrument(cls.INST_B),)) if pairs else {}
        bad = check_boundary_cuts(lambda p=params: cls(**p), bars, job.inst, job.settings, coverage=cov, **kw)
        cuts.append(cov["boundary_cuts"]); rows.append(cov["decision_rows"])
        if bad:
            return f"FAILED for params {params}: " + "; ".join(bad)
    return (f"passed boundary cuts ({len(bars):,} bars; {len(sets)} of {len(uniq)} parameter sets; {min(cuts)}-{max(cuts)} "
            f"cuts per set after decision bars ({min(rows):,}-{max(rows):,} per set) and signal flips)")


def recheck(strategy: str, market: str, session: str, bars: str, mode: str = "gate") -> dict:
    path = ROOT / "strategies" / "photos" / f"{strategy}.py"
    tf = int(str(bars).rstrip("m"))
    a, cls, inst, key, base_params, tf = photo_study.study_args(path, market, session, 1, tf)
    a.force = True                                         # report a failure instead of stopping
    t0 = time.time()
    job, df = robust.make_job(a, market)
    extra = sweep.expand_grid(robust.parse_grid(a.grid))
    msg = robust.lookahead_gate(a, job, df, extra) if mode == "gate" else boundary_gate(a, job, df, extra)
    return {"strategy": strategy, "market": market, "session": session, "bars": bars, "mode": mode,
            "lookahead": msg, "passed": msg.startswith("passed"), "seconds": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--bars", nargs="*")
    ap.add_argument("--market", nargs="*")
    ap.add_argument("--mode", choices=["gate", "boundary"], default="gate",
                    help="gate: the full look-ahead gate; boundary: only the decision/signal-boundary cuts (for saved "
                         "runs that already passed the rest of the gate with the same strategy code and data)")
    a = ap.parse_args()
    r = pd.read_csv(a.rows)
    r = r[r.error.isna()]
    if a.only:
        r = r[r.strategy.str[:3].isin(a.only)]
    if a.bars:
        r = r[r.bars.isin(a.bars)]
    if a.market:
        r = r[r.market.isin(a.market)]
    out = Path(a.out)
    done = pd.read_csv(out) if out.exists() else pd.DataFrame(columns=["strategy", "market", "session", "bars"])
    have = set(map(tuple, done[["strategy", "market", "session", "bars"]].astype(str).to_numpy()))
    rows = done.to_dict("records")
    for _, s in r.iterrows():
        k = (s.strategy, s.market, s.session, s.bars)
        if k in have:
            continue
        try:
            x = recheck(*k, mode=a.mode)
        except SystemExit as e:
            x = {"strategy": k[0], "market": k[1], "session": k[2], "bars": k[3], "lookahead": f"error: {e}",
                 "passed": False, "seconds": None}
        print(f"{'ok  ' if x['passed'] else 'FAIL'} {k} {x['seconds']}s  {x['lookahead'][:160]}", flush=True)
        rows.append(x)
        pd.DataFrame(rows).to_csv(out, index=False)


if __name__ == "__main__":
    main()
