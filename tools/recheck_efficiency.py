"""Apply the walk-forward efficiency credibility rule (engine.walkforward.efficiency_detail, ninth-revision R3) to
saved study rows from each run's saved walkforward_folds.csv, without re-running anything.

For each row written before the rule existed (no `wf_efficiency_note` yet):
  * wf_efficiency_raw  = the plain pooled ratio (must equal the saved wf_efficiency: checked),
  * wf_efficiency      = the ratio only when it is credible, else empty,
  * wf_efficiency_note = why it is not available, or the coverage and both rates,
  * checks_passed      = one less where the old verdict was a PASS (ratio >= 0.5) and the ratio is now unavailable.
Rows already carrying the note (re-run with the current code) are left as they are.

    python tools/recheck_efficiency.py results/TIMEFRAME_STUDY/rows.csv      # rewrites the file (keep an archive copy)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import walkforward  # noqa: E402

CAPITAL = 100_000.0


def folds_csv(report: str) -> Path | None:
    d = sorted(x for x in (ROOT / report).glob("*_walkforward_*") if x.is_dir() and not x.name.startswith("._"))
    return d[0] / "walkforward_folds.csv" if len(d) == 1 else None


def capital_of(report: str) -> float:
    d = folds_csv(report)
    s = d.parent / "walkforward_summary.json" if d is not None else None
    if s is not None and s.exists():
        cap = json.loads(s.read_text()).get("oos_full_summary", {}).get("capital")
        if cap:
            return float(cap)
    return CAPITAL


def main(path: str):
    p = Path(path)
    r = pd.read_csv(p)
    for c in ("wf_efficiency_raw", "wf_efficiency_note"):
        if c not in r:
            r[c] = np.nan
    r["wf_efficiency_note"] = r.wf_efficiency_note.astype(object)
    changed, mismatched, lost = 0, [], []
    for i, s in r.iterrows():
        if isinstance(s.wf_efficiency_note, str) or isinstance(s.get("error"), str) or not isinstance(s.report, str):
            continue
        f = folds_csv(s.report)
        if f is None or not f.exists():
            continue
        d = walkforward.efficiency_detail(pd.read_csv(f), capital_of(s.report))
        old = s.wf_efficiency
        if pd.notna(old) and (d["raw_ratio"] is None or abs(d["raw_ratio"] - old) > 1e-3):
            mismatched.append((s.strategy, s.market, s.session, s.bars, old, d["raw_ratio"]))
            continue
        note = d["reason"] or (f"{d['scored_folds']} of {d['scheduled_folds']} folds scored; OOS "
                               f"${d['oos_pnl_per_day']:,.2f}/day vs in-sample ${d['is_pnl_per_day']:,.2f}/day")
        was_pass = pd.notna(old) and old >= 0.5
        now_pass = d["efficiency"] is not None and d["efficiency"] >= 0.5
        r.at[i, "wf_efficiency_raw"] = d["raw_ratio"]
        r.at[i, "wf_efficiency"] = d["efficiency"] if d["efficiency"] is not None else np.nan
        r.at[i, "wf_efficiency_note"] = note
        if was_pass and not now_pass:
            r.at[i, "checks_passed"] = s.checks_passed - 1
            lost.append((s.strategy, s.market, s.session, s.bars, old, note))
        changed += 1
    if mismatched:
        raise SystemExit(f"saved efficiency does not match the recomputed ratio for {len(mismatched)} rows: {mismatched[:5]}")
    tmp = p.with_suffix(".tmp")
    r.to_csv(tmp, index=False)
    tmp.replace(p)
    print(f"{p}: {changed} rows rechecked; {len(lost)} lose the efficiency pass:")
    for x in lost:
        print("  ", x)


if __name__ == "__main__":
    main(sys.argv[1])
