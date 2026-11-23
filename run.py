"""Run a strategy file on one or more markets.

Examples
  python run.py strategies/orb.py --symbol NQ
  python run.py strategies/orb.py --symbol NQ,GC,XAUUSD --start 2022-01-01 --set rr=3 or_minutes=30
  python run.py strategies/sma_cross.py --symbol GC --tf 60
  python run.py strategies/orb.py --symbol NAS100 --data NAS100_RTH --spread 1.5
  python run.py strategies/orb.py --symbol MNQ --commission 0.5 --slippage 2
"""
import argparse
import ast
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings, check_lookahead, data, get_instrument, report  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from robust import check_dataset  # noqa: E402


def parse_sets(items):
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        try:
            out[k] = ast.literal_eval(v)
        except (ValueError, SyntaxError):
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("strategy")
    ap.add_argument("--symbol", default="NQ", help="NQ, MNQ, GC, MGC, XAUUSD, NAS100 (comma-separated for several)")
    ap.add_argument("--data", default=None, help="override the dataset, e.g. NAS100_RTH")
    ap.add_argument("--tf", type=int, default=1, help="bar size in minutes (1, 5, 15, 60, 240, 1440)")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--capital", type=float, default=50_000)
    ap.add_argument("--commission", type=float, help="$ per side per contract/lot")
    ap.add_argument("--slippage", type=float, help="ticks per side on market/stop fills")
    ap.add_argument("--spread", type=float, help="fixed spread in points (instruments without bid/ask)")
    ap.add_argument("--set", nargs="*", help="strategy parameters, key=value")
    ap.add_argument("--no-lookahead-check", action="store_true")
    a = ap.parse_args()

    cls = load_strategy(a.strategy)
    params = parse_sets(a.set)
    for sym in a.symbol.split(","):
        inst = get_instrument(sym)
        over = {k: v for k, v in (("commission", a.commission), ("slippage_ticks", a.slippage), ("spread", a.spread)) if v is not None}
        if over:
            inst = inst.with_costs(**over)
        t0 = time.time()
        key = a.data or inst.data_key
        check_dataset(inst.name, key)
        df = data.resample(data.load(key, a.start, a.end), a.tf)
        strat = cls(**params)
        la = "skipped"
        if not a.no_lookahead_check:
            bad = check_lookahead(lambda: cls(**params), df.iloc[max(0, len(df) - 300_000):], inst, Settings(capital=a.capital))
            la = "passed" if not bad else "FAILED: " + "; ".join(bad)
            if bad:
                print(f"!! LOOK-AHEAD: {la}  (results below are not trustworthy)")
        res = Engine(df, inst, strat, Settings(capital=a.capital)).run()
        out = report.save(res, Path(a.strategy).stem, strat.p, extra={"timeframe_min": a.tf, "lookahead_check": la,
                                                                      "costs": {"commission": inst.commission, "slippage_ticks": inst.slippage_ticks,
                                                                                "spread": "real bid/ask" if inst.uses_bid_ask else inst.spread}})
        print(f"\n===== {cls.__name__} on {inst.name} ({len(df):,} bars of {a.tf}m, {time.time() - t0:.1f}s) =====")
        print((out / "summary.txt").read_text())
        print(f"saved -> {out}")


if __name__ == "__main__":
    main()
