"""Average out-of-sample trade before and after execution costs, by bar size (from every run's saved
walkforward_oos_trades.csv). This is a diagnostic on the trades that were actually executed, not a re-simulation
with zero costs (without costs some trades would have been different).

What each saved column holds:
  costs         commissions + every roll charge (a roll charge = both sides' commission AND slippage)
  slippage_usd  fill slippage + the slippage part of roll charges   <- roll slippage is in BOTH columns
  spread_usd    bid/ask spread paid (inside the fill prices)
so: friction = costs + (slippage_usd - roll slippage) + spread_usd, and before costs = pnl + friction.
Ledgers written before the engine exported `roll_slippage_usd` get it rebuilt as rolls x 2 x slippage x qty.
    python tools/timeframe_costs.py > results/TIMEFRAME_STUDY/costs.md
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from engine import get_instrument  # noqa: E402
from timeframe_portfolio import wf_dir  # noqa: E402
from timeframe_report import TF_LABEL, TF_ORDER, load  # noqa: E402


def friction(t: pd.DataFrame, inst) -> pd.Series:
    """Every execution cost of each trade, each counted once (see the module notes)."""
    if "roll_slippage_usd" in t:
        roll_slip = t.roll_slippage_usd.fillna(0.0)
    else:
        roll_slip = t.rolls * 2 * inst.slippage_ticks * inst.tick * inst.point_value * t.qty
    return t.costs + (t.slippage_usd - roll_slip) + t.spread_usd


def main():
    r = load()
    rows = []
    for _, s in r.iterrows():
        if s.code in ("B01",):                                 # pairs: two legs per trade, different cost columns
            continue
        try:
            t = pd.read_csv(wf_dir(s.report) / "walkforward_oos_trades.csv")
        except (SystemExit, FileNotFoundError, pd.errors.EmptyDataError):
            continue
        if not len(t):
            continue
        fr = friction(t, get_instrument(s.market))
        rows.append({"bars": s.bars, "market": s.market, "trades": len(t), "before": (t.pnl + fr).sum(), "friction": fr.sum(),
                     "after": t.pnl.sum()})
    x = pd.DataFrame(rows)
    out = []
    for tf in TF_ORDER:
        for mk, g in [("all markets", x[x.bars == tf])] + [(m, x[(x.bars == tf) & (x.market == m)]) for m in ("MNQ", "NAS100", "MGC", "XAUUSD")]:
            if not len(g):
                continue
            n = g.trades.sum()
            out.append({"bars": TF_LABEL[tf], "market": mk, "runs": len(g), "OOS trades": int(n),
                        "avg trade before costs $": round(g.before.sum() / n, 2), "avg costs per trade $": round(g.friction.sum() / n, 2),
                        "avg trade after costs $": round(g.after.sum() / n, 2),
                        "runs profitable before costs": int((g.before > 0).sum()), "runs profitable after costs": int((g.after > 0).sum())})
    print(pd.DataFrame(out).to_markdown(index=False))
    (ROOT / "results" / "TIMEFRAME_STUDY" / "costs_numbers.json").write_text(pd.DataFrame(out).to_json(orient="records", indent=1))


if __name__ == "__main__":
    main()
