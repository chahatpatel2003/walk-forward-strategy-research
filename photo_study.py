"""Run every photo strategy (strategies/photos) on every market and session through:
  1. a full-history backtest with the photo's default rules,
  2. the full robustness pipeline (parameter test, walk-forward, Monte Carlo, stress test),
  3. a buy-and-hold comparison over the same periods.

  python photo_study.py                       # everything (resumes an interrupted study)
  python photo_study.py --only a01 a05        # some strategies
  python photo_study.py --markets MNQ NAS100

Results: results/PHOTO_STUDY/  (study_rows.csv grows row by row; PHOTO_STUDY_REPORT.md at the end).
"""
import argparse
import json
import sys
import time
import traceback
from argparse import Namespace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import robust  # noqa: E402
from engine import Settings, data, get_instrument  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from engine.pairs import is_pairs, load_pair, pair_key  # noqa: E402
from engine.parallel import Job, run_job  # noqa: E402

OUT = ROOT / "results" / "PHOTO_STUDY"
DEFAULT_MARKETS = ("MNQ", "NAS100", "MGC", "XAUUSD")
CAPITAL = 100_000.0


def wf_settings(tf: int) -> dict:
    if tf >= 240:       # daily / 4-hour strategies trade rarely: long in-sample windows, lower minimum trade count
        return dict(is_months=36, oos_months=12, min_trades=15)
    return dict(is_months=18, oos_months=6, min_trades=40)


def benchmark(bars: pd.DataFrame, inst, windows: list[tuple[str, str]], capital: float = CAPITAL) -> dict:
    """Buy-and-hold over exactly the given scored windows (start and end dates inclusive).
    Consecutive windows (no bar of the traded session between them) are held as ONE continuous position;
    the position is closed at a real gap between scored windows and re-opened after it. Each position buys
    `capital` of contract value at its first bar's open (real price of the contract the bar opens with) and sells
    at its last bar's close. Same execution costs as the strategies: commission and slippage per side (futures),
    bid/ask (XAUUSD) or the fixed spread (NAS100), plus the roll cost for every contract switch while held.
    Drawdown uses the engine's open -> worst -> close walk (metrics.drawdown_walk)."""
    from engine import metrics
    tday = bars.tday.to_numpy().astype("datetime64[D]")
    spans = []                                              # [first bar index, last bar index] per held position
    for start, end in sorted(windows):
        idx = np.flatnonzero((tday >= np.datetime64(start)) & (tday <= np.datetime64(end)))
        if not len(idx):
            continue
        if spans and idx[0] == spans[-1][1] + 1:            # back-to-back: keep holding
            spans[-1][1] = idx[-1]
        else:
            spans.append([idx[0], idx[-1]])
    level, frames, qty0 = capital, [], None
    pv, slip, comm = inst.point_value, inst.slippage_ticks * inst.tick, inst.commission
    real = inst.uses_bid_ask and "bo" in bars
    adj_open = bars["adj_open"] if "adj_open" in bars else (bars["adj"] if "adj" in bars else None)
    for a, b in spans:
        w = bars.iloc[a:b + 1]
        hs = 0.0 if real else inst.spread / 2.0
        bid = {k: (w["b" + k] if real else w[k] - hs).to_numpy(dtype=float) for k in "olc"}
        ask_open = (w.ao.iloc[0] if real else w.o.iloc[0] + hs) + slip
        real_px = w.o.iloc[0] - (adj_open.iloc[a] if adj_open is not None else 0.0)
        qty = np.floor(capital / (real_px * pv) / inst.qty_step + 1e-9) * inst.qty_step
        qty0 = qty if qty0 is None else qty0
        roll_cost_each = (2 * comm + 2 * slip * pv) * qty
        base = level - comm * qty
        roll_flags = w.roll.to_numpy(dtype=bool).copy(); roll_flags[0] = False
        if "roll_inside" in w:
            roll_flags |= w.roll_inside.to_numpy(dtype=bool)
        paid = np.cumsum(roll_flags) * roll_cost_each
        f = pd.DataFrame({"tday": w.tday.to_numpy(),
                          "equity_open": base - paid + (bid["o"] - ask_open) * qty * pv,
                          "equity_low": base - paid + (bid["l"] - ask_open) * qty * pv,
                          "equity": base - paid + (bid["c"] - ask_open) * qty * pv})
        f.loc[f.index[-1], "equity"] = base - paid[-1] + (bid["c"][-1] - slip - ask_open) * qty * pv - comm * qty
        level = float(f.equity.iloc[-1])
        frames.append(f)
    if not frames:
        return {"net": None, "max_dd": None, "positions": 0, "qty": None}
    eq = pd.concat(frames, ignore_index=True)
    dd, _ = metrics.drawdown_walk(eq, capital)
    return {"net": round(level - capital, 2), "max_dd": round(float(dd.min()), 2), "positions": len(spans), "qty": qty0}


def versions(path: Path, data_key: str) -> dict:
    """Fingerprints that decide whether a saved study row is still valid: the code (this strategy file, the
    engine, the robustness tools and this runner, which holds the study configuration) and the input data."""
    import hashlib
    h = hashlib.sha1()
    for f in [path, *sorted((ROOT / "engine").glob("*.py")), ROOT / "robust.py", ROOT / "photo_study.py"]:
        h.update(Path(f).read_bytes())
    d = hashlib.sha1(json.dumps([data._fingerprint(k) for k in data_key.split("+")], sort_keys=True).encode())
    return {"code_version": h.hexdigest()[:12], "data_version": d.hexdigest()[:12]}


SESSION_MINUTES = {"rth": 390, "full": 1380}       # trading minutes in one daily bar
WARMUP_DAYS = {1: 10, 5: 10, 15: 15, 60: 40, 240: 120, 1440: 400}


def pct_scale(native_tf: int, tf: int, session: str) -> float:
    """Factor for thresholds written as a % of price when a rule designed on `native_tf` bars runs on `tf` bars: a
    typical move grows with the square root of time, so a '1% below VWAP' on daily bars is ~0.11% on 5-minute
    cash-session bars. Lengths (in bars) are NOT scaled: RSI(3) on 5-minute bars uses three 5-minute bars."""
    m = SESSION_MINUTES.get(session, 1380)
    span = lambda t: min(t, m)                         # noqa: E731  (a daily bar spans one session)
    return float(np.sqrt(span(tf) / span(native_tf)))


def scaled(params: dict, factor: float, keys=()) -> dict:
    """Scale the parameters a strategy declares as percentages of PRICE (class attribute PRICE_PCT); nothing else."""
    return {k: (round(v * factor, 6) if k in keys and isinstance(v, (int, float)) and not isinstance(v, bool) else v)
            for k, v in params.items()}


def study_args(path: Path, sym: str, session: str, workers: int, tf: int | None = None, extra: dict | None = None):
    """The exact robust.py arguments a study run uses (also used to re-check a saved run, e.g. its look-ahead gate).
    Returns (args, strategy class, instrument, data key, base params, bar size)."""
    cls = load_strategy(str(path))
    native = getattr(cls, "TF", 1440)
    tf = tf or native
    factor = pct_scale(native, tf, session) if tf != native else 1.0
    inst = get_instrument(sym)
    pairs = is_pairs(cls)
    key = pair_key(cls) if pairs else inst.data_key
    wf = wf_settings(tf)
    keys = getattr(cls, "PRICE_PCT", ())
    base_params = scaled(cls.params, factor, keys) if factor != 1.0 else {}
    base_params = {k: v for k, v in base_params.items() if v != cls.params.get(k)}
    base_params.update(extra or {})                      # extra fixed parameters (e.g. stop_atr=2): every stage
    grid = {k: [scaled({k: v}, factor, keys)[k] for v in vals] for k, vals in cls.GRID.items()}
    grid_items = [f"{k}=" + ",".join(str(v) for v in vals) for k, vals in grid.items()]
    set_items = [f"{k}={v}" for k, v in base_params.items()]
    a = Namespace(command="all", strategy=str(path), symbol=sym, data=None, tf=tf, session=session, start=None, end=None,
                  capital=CAPITAL, commission=None, slippage=None, spread=None, set=set_items, grid=grid_items,
                  objective="sharpe", min_trades=wf["min_trades"], select="plateau", is_months=wf["is_months"],
                  oos_months=wf["oos_months"], anchored=False, warmup_days=WARMUP_DAYS.get(tf, 10 if tf < 1440 else 400),
                  from_dir=None,
                  method="bootstrap", sims=5000, seed=42, block=5, skip=0.0, haircut=0.0, ruin=CAPITAL * 0.2,
                  workers=workers, force=False, account_constrained=True)
    return a, cls, inst, key, base_params, tf


def run_one(path: Path, sym: str, session: str, workers: int, tf: int | None = None, out_root: Path | None = None,
            extra: dict | None = None) -> dict:
    """tf: run on this bar size instead of the strategy's own (percent-of-price thresholds are scaled, see pct_scale)."""
    a, cls, inst, key, base_params, tf = study_args(path, sym, session, workers, tf, extra)
    pairs = is_pairs(cls)
    native = getattr(cls, "TF", 1440)
    factor = pct_scale(native, tf, session) if tf != native else 1.0
    # 1. full history, photo defaults
    bars = load_pair(*cls.LEGS, tf=tf, session=session) if pairs else data.resample(data.load(key), tf, session)
    base = run_job(Job(str(path), key, tf, inst, Settings(capital=CAPITAL, account_constrained=True), base_params,
                       warmup_days=0, session=session))
    s0 = base["summary"]
    held = (base["trades"].bars.sum() / len(bars) * 100) if len(base["trades"]) else 0.0
    whole = [(str(bars.tday.iloc[0])[:10], str(bars.tday.iloc[-1])[:10])]
    bh = {"net": None, "max_dd": None} if pairs else benchmark(bars, inst, whole)   # market-neutral: no buy-and-hold
    # 2. robustness pipeline
    robust.RESULTS = (out_root or OUT) / session
    robust.RESULTS.mkdir(parents=True, exist_ok=True)
    r = robust.cmd_all(a, sym)
    wfi, mc, st = r["walkforward"], r["montecarlo"], r["stress"]
    scored = [(f["oos_start"], f["oos_end"]) for f in r["folds"] if f.get("chosen") is not None and "oos_net_pnl" in f]
    bh_oos = benchmark(bars, inst, scored) if scored and not pairs else {"net": None, "max_dd": None}
    sc = st["scenarios"].set_index("scenario")
    worst = [i for i in sc.index if i.startswith("ALL")]
    checks = r["checks"]
    return {
        "strategy": path.stem, "market": sym, "session": session, "bars": f"{tf}m", "native_bars": f"{native}m",
        "pct_threshold_scale": round(factor, 4), "base_params": json.dumps({**cls.params, **base_params}),
        "avg_win": s0.get("avg_win"), "avg_loss": s0.get("avg_loss"), "payoff_ratio": s0.get("payoff_ratio"),
        "trades_per_year": s0.get("trades_per_year"), "expectancy": s0.get("expectancy_per_trade"),
        "wf_oos_win_pct": wfi.get("oos_win_rate_pct"),
        "period": f"{s0.get('start')} -> {s0.get('end')}",
        "account_model": s0.get("account_model"), "capital_exhausted_on": s0.get("capital_exhausted_on"),
        "trades": s0.get("trades", 0), "net": s0.get("net_pnl"), "pf": s0.get("profit_factor"),
        "win_pct": s0.get("win_rate_pct"), "max_dd": s0.get("max_drawdown_usd"), "sharpe": s0.get("sharpe_daily_ann"),
        "time_in_market_pct": round(held, 1), "buy_hold_net": bh["net"], "buy_hold_max_dd": bh["max_dd"],
        "best_params": json.dumps(r["sweep"].get("plateau_choice")), "pct_param_sets_profitable": r["sweep"].get("profitable_pct"),
        "wf_oos_period": wfi.get("oos_period"), "wf_capital_exhausted_on": wfi.get("oos_capital_exhausted_on"),
        "wf_folds_skipped_capital_exhausted": wfi.get("folds_skipped_capital_exhausted"), "wf_oos_trades": wfi.get("oos_trades"), "wf_oos_net": wfi.get("oos_net_pnl"),
        "wf_oos_pf": wfi.get("oos_profit_factor"), "wf_folds_profitable_pct": wfi.get("profitable_oos_folds_pct"),
        "wf_efficiency": wfi.get("walk_forward_efficiency"), "wf_efficiency_raw": wfi.get("walk_forward_efficiency_raw"),
        "wf_efficiency_note": wfi.get("walk_forward_efficiency_note"), "buy_hold_oos_net": bh_oos["net"],
        "buy_hold_oos_max_dd": bh_oos["max_dd"], "wf_oos_max_dd": wfi.get("oos_max_drawdown_usd"),
        "wf_oos_windows": len(scored), "buy_hold_oos_positions": bh_oos.get("positions"), "warmup_short_folds": sum(1 for f in r["folds"] if f.get("oos_warmup_short")),
        "mc_prob_loss_pct": mc.get("bootstrap", {}).get("prob_final_loss_pct"),
        "stress_all_net": float(sc.loc[worst[0], "net_pnl"]) if worst else None,
        "stress_all_capital_exhausted_on": (sc.loc[worst[0], "capital_exhausted_on"] or None)
        if worst and "capital_exhausted_on" in sc and isinstance(sc.loc[worst[0], "capital_exhausted_on"], str) else None,
        "stress_scenarios_breached": int(sc.capital_exhausted_on.map(lambda v: isinstance(v, str) and bool(v)).sum())
        if "capital_exhausted_on" in sc else 0,
        "stress_worst_net": float(sc.net_pnl.min()) if len(sc) else None,
        "stress_worst_scenario": str(sc.net_pnl.idxmin()) if len(sc) else None,
        "checks_passed": sum(1 for c in checks if c[0] == "PASS"), "checks_total": len(checks),
        "report": str(Path(r["root"]).relative_to(ROOT)),
    }


KEY = ("strategy", "market", "session")


def save_row(path: Path, row: dict, key=KEY) -> pd.DataFrame:
    """Insert or replace one row in the study table, safely when several processes write at once: under an
    exclusive lock, re-read the file AS IT IS NOW, replace only this row's key, write to a temporary file and move it
    into place. Every other row (including ones another process wrote meanwhile) is kept."""
    import fcntl
    import os
    import tempfile
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path) + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            rows = pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()
            if len(rows) and all(k in rows for k in key):
                same = np.logical_and.reduce([rows[k].astype(str) == str(row.get(k)) for k in key])
                rows = rows[~same]
            rows = pd.concat([rows, pd.DataFrame([row])], ignore_index=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            os.close(fd)
            rows.to_csv(tmp, index=False)
            os.replace(tmp, path)
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)
    return rows


def write_report(rows: pd.DataFrame):
    if rows.empty:
        return
    ok = rows[rows["error"].isna()] if "error" in rows else rows
    lines = ["# Photo strategy study", "",
             f"Generated {time.strftime('%Y-%m-%d %H:%M')}. Capital ${CAPITAL:,.0f} (account-constrained: trading stops if the "
             "account's marked equity reaches $0); daily strategies trade "
             f"${CAPITAL:,.0f} of contract value per position (no leverage); costs = engine defaults "
             "(futures commission + 1 tick slippage per side; XAUUSD real spread; NAS100 1.2-pt spread).",
             "Walk-forward: daily strategies 36 months optimise -> 12 months trade; intraday 18 -> 6.",
             "**OOS** = out-of-sample (walk-forward, never seen by the optimiser). Compare with buy-and-hold over the same period.", ""]
    cols = ["strategy", "market", "session", "trades", "net", "pf", "max_dd", "time_in_market_pct", "buy_hold_net",
            "wf_oos_net", "wf_oos_pf", "buy_hold_oos_net", "wf_folds_profitable_pct", "mc_prob_loss_pct",
            "stress_all_net", "checks_passed"]
    view = ok[cols].copy()
    view["checks_passed"] = ok.checks_passed.astype(str) + "/" + ok.checks_total.astype(str)
    view = view.sort_values(["wf_oos_net"], ascending=False, na_position="last")
    lines += ["## All runs, ranked by walk-forward out-of-sample net P&L", "", view.to_markdown(index=False) if robust._has_tabulate()
              else "```\n" + view.to_string(index=False) + "\n```", ""]
    if "error" in rows and rows.error.notna().any():
        lines += ["## Runs that failed", "", "```\n" + rows[rows.error.notna()][["strategy", "market", "session", "error"]].to_string(index=False) + "\n```"]
    (OUT / "PHOTO_STUDY_REPORT.md").write_text("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="strategy file prefixes, e.g. a01 a05")
    ap.add_argument("--markets", nargs="*")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--fresh", action="store_true", help="re-run the selected runs even if their saved rows are still valid")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows_path = OUT / "study_rows.csv"
    rows = pd.read_csv(rows_path) if rows_path.exists() else pd.DataFrame()
    paths = sorted((ROOT / "strategies/photos").glob("[ab][0-9]*.py"))
    if a.only:
        paths = [p for p in paths if any(p.stem.startswith(x) for x in a.only)]
    todo = []
    for path in paths:
        cls = load_strategy(str(path))
        for sym in getattr(cls, "MARKETS", DEFAULT_MARKETS):
            if a.markets and sym not in a.markets:
                continue
            key = pair_key(cls) if is_pairs(cls) else get_instrument(sym).data_key
            v = versions(path, key)
            for session in getattr(cls, "SESSIONS", ("full",)):
                same = rows[(rows.strategy == path.stem) & (rows.market == sym) & (rows.session == session)] if len(rows) else rows
                valid = (len(same) and "error" in same and same.error.isna().all()
                         and (same.get("code_version") == v["code_version"]).all()
                         and (same.get("data_version") == v["data_version"]).all()) if len(same) else False
                if a.fresh or not valid:
                    todo.append((path, sym, session, v))
    print(f"photo study: {len(todo)} runs to do (saved rows that are still valid are reused)")
    for k, (path, sym, session, v) in enumerate(todo, 1):
        t0 = time.time()
        print(f"\n######## [{k}/{len(todo)}] {path.stem} on {sym} ({session})", flush=True)
        try:
            row = run_one(path, sym, session, a.workers)
            row["error"] = None
        except BaseException as e:                       # keep going; record the failure (it is retried next time)
            if isinstance(e, KeyboardInterrupt):
                raise
            row = {"strategy": path.stem, "market": sym, "session": session, "error": f"{type(e).__name__}: {e}"}
            traceback.print_exc()
        row.update(v)
        row["seconds"] = round(time.time() - t0, 1)
        rows = save_row(rows_path, row)
        write_report(rows)
    write_report(rows)
    print(f"\nreport -> {OUT / 'PHOTO_STUDY_REPORT.md'}")


if __name__ == "__main__":
    main()
