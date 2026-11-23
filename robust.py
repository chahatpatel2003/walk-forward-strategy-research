"""Robustness testing: parameter test, walk-forward, Monte Carlo, stress test.

  python robust.py sweep       STRATEGY --symbol MNQ --grid rr=1.5,2,3 or_minutes=5,15,30
  python robust.py walkforward STRATEGY --symbol MNQ --grid rr=1.5,2,3 or_minutes=5,15,30 --is-months 24 --oos-months 6
  python robust.py montecarlo  --from results/<run folder>          (or: STRATEGY --symbol MNQ --set rr=2)
  python robust.py stress      STRATEGY --symbol MNQ --set rr=2
  python robust.py all         STRATEGY --symbol MNQ --grid rr=1.5,2,3 or_minutes=5,15,30 --ruin 3000

Grid values: comma list (rr=1.5,2,3) or inclusive range start:stop:step (rr=1:3:0.5).
Results go to results/<time>_<test>_<strategy>_<symbol>/.
"""
import argparse
import ast
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from engine import Settings, check_lookahead, data, get_instrument  # noqa: E402
from engine import montecarlo, stress, sweep, walkforward  # noqa: E402
from engine.data import _assert_not_data_path  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from engine.parallel import Job, default_workers  # noqa: E402

RESULTS = ROOT / "results"


def _val(v: str):
    try:
        return ast.literal_eval(v)
    except (ValueError, SyntaxError):
        return v


def parse_grid(items) -> dict:
    grid = {}
    for it in items or []:
        k, v = it.split("=", 1)
        if ":" in v:
            a, b, st = (float(x) for x in v.split(":"))
            vals = list(np.round(np.arange(a, b + st / 2, st), 10))
            grid[k] = [int(x) if float(x).is_integer() and all(float(y).is_integer() for y in (a, b, st)) else float(x) for x in vals]
        else:
            grid[k] = [_val(x) for x in v.split(",")]
    return grid


def parse_sets(items) -> dict:
    return {k: _val(v) for k, v in (it.split("=", 1) for it in items or [])}


def outdir(kind: str, strategy: str, sym: str) -> Path:
    p = RESULTS / f"{datetime.now():%Y%m%d_%H%M%S}_{kind}_{Path(strategy).stem}_{sym}"
    _assert_not_data_path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def make_job(a, sym: str) -> tuple[Job, pd.DataFrame]:
    inst = get_instrument(sym)
    over = {k: v for k, v in (("commission", a.commission), ("slippage_ticks", a.slippage), ("spread", a.spread)) if v is not None}
    if over:
        inst = inst.with_costs(**over)
    key = a.data or inst.data_key
    df = data.load(key, a.start, a.end)
    job = Job(str(Path(a.strategy).resolve()), key, a.tf, inst, Settings(capital=a.capital), parse_sets(a.set),
              start=str(df.tday.iloc[0])[:10], end=str(df.tday.iloc[-1])[:10], warmup_days=a.warmup_days)
    return job, df


def lookahead_gate(a, job: Job, df: pd.DataFrame) -> str:
    cls = load_strategy(a.strategy)
    bad = check_lookahead(cls(**job.params), data.resample(df.iloc[: min(len(df), 300_000 * a.tf)], a.tf))
    if bad:
        msg = f"FAILED: prepare() uses future data in columns {bad}"
        if not a.force:
            raise SystemExit(f"!! look-ahead check {msg}. Fix the strategy (or pass --force to run anyway).")
        return msg
    return "passed"


def trading_days(df):
    return np.unique(df.tday.to_numpy().astype("datetime64[D]"))


# ------------------------------------------------------------------------------------ commands
def cmd_sweep(a, sym):
    job, df = make_job(a, sym)
    la = lookahead_gate(a, job, df)
    grid = parse_grid(a.grid)
    if not grid:
        raise SystemExit("--grid is required, e.g. --grid rr=1.5,2,3 or_minutes=5,15,30")
    out = outdir("sweep", a.strategy, sym)
    print(f"parameter test: {len(sweep.expand_grid(grid))} combinations on {sym}")
    res = sweep.run_sweep(job, grid, a.objective, a.min_trades, a.workers)
    info = sweep.report(res, grid, out, a.objective, f"{Path(a.strategy).stem} on {sym}")
    info["lookahead_check"] = la
    print((out / "sweep_report.txt").read_text()); print(f"saved -> {out}")
    return info, res, out


def cmd_walkforward(a, sym):
    job, df = make_job(a, sym)
    la = lookahead_gate(a, job, df)
    grid = parse_grid(a.grid)
    if not grid:
        raise SystemExit("--grid is required for walk-forward")
    out = outdir("walkforward", a.strategy, sym)
    wf = walkforward.run(job, grid, trading_days(df), a.is_months, a.oos_months, a.anchored, a.objective,
                         a.min_trades, a.select, a.workers)
    info = walkforward.report(wf, out, f"{Path(a.strategy).stem} on {sym}")
    info["lookahead_check"] = la
    print((out / "walkforward_report.txt").read_text()); print(f"saved -> {out}")
    return info, wf, out


def _mc_from_trades(a, trades: pd.DataFrame, days, capital, out: Path, title: str):
    if a.method == "daily":
        dd = trades.groupby(pd.to_datetime(trades.exit_tday)).pnl.sum()
        dd = dd.reindex(pd.to_datetime(days), fill_value=0.0) if days is not None else dd
        items = dd.to_numpy()
    else:
        items = trades.pnl.to_numpy()
    mc = montecarlo.simulate(items, capital, a.sims, a.method, a.seed, a.block, a.skip, a.haircut, a.ruin)
    info = montecarlo.report(mc, out, title)
    print((out / "montecarlo_report.txt").read_text()); print(f"saved -> {out}")
    return info


def cmd_montecarlo(a, sym=None):
    if a.from_dir:
        src = Path(a.from_dir)
        f = src / "walkforward_oos_trades.csv" if (src / "walkforward_oos_trades.csv").exists() else src / "trades.csv"
        trades = pd.read_csv(f)
        out = src / f"montecarlo_{a.method}"
        summ = src / "summary.json"
        cap = json.loads(summ.read_text()).get("capital", a.capital) if summ.exists() else a.capital
        days = None
        if a.method == "daily":
            de = src / "daily_equity.csv"
            days = pd.read_csv(de).iloc[:, 0].to_numpy() if de.exists() else None
        return _mc_from_trades(a, trades, days, cap, out, f"{src.name} ({f.name})")
    job, df = make_job(a, sym)
    lookahead_gate(a, job, df)
    from engine.parallel import run_job
    r = run_job(job)
    out = outdir("montecarlo", a.strategy, sym)
    r["trades"].to_csv(out / "trades.csv", index=False)
    return _mc_from_trades(a, r["trades"], r["days"], a.capital, out, f"{Path(a.strategy).stem} on {sym}")


def cmd_stress(a, sym, params=None, out=None):
    job, df = make_job(a, sym)
    if params:
        job = job.with_(params={**job.params, **params})
    lookahead_gate(a, job, df)
    out = out or outdir("stress", a.strategy, sym)
    daily = data.resample(df, 1440)
    st = stress.run(job, daily, a.workers)
    info = stress.report(st, out, f"{Path(a.strategy).stem} on {sym}, params {job.params}")
    print((out / "stress_report.txt").read_text()); print(f"saved -> {out}")
    return info, st


def cmd_all(a, sym):
    """Parameter test -> walk-forward -> Monte Carlo on the walk-forward OOS trades -> stress test."""
    t0 = time.time()
    root = outdir("ALL", a.strategy, sym)
    global RESULTS
    keep, RESULTS = RESULTS, root          # sub-reports go inside this run's folder
    try:
        sw, sw_df, _ = cmd_sweep(a, sym)
        wf_info, wf, wf_out = cmd_walkforward(a, sym)
        oos = wf["oos_result"]["trades"]
        mc_info = {}
        if len(oos) >= 2:
            for m in ("bootstrap", "shuffle"):
                a.method = m
                mc_info[m] = _mc_from_trades(a, oos, wf["oos_result"]["equity"].tday, a.capital, root / f"montecarlo_{m}",
                                             f"{Path(a.strategy).stem} on {sym}: walk-forward OOS trades, {m}")
        params = sw.get("plateau_choice") or sw.get("best") or {}
        st_info, st = cmd_stress(a, sym, params, root / "stress")
    finally:
        RESULTS = keep
    checks = checklist(a, sym, sw, wf_info, mc_info, st)
    write_overview(a, sym, root, sw, wf_info, mc_info, st, params, checks, time.time() - t0)
    print((root / "ROBUSTNESS_REPORT.md").read_text())
    print(f"saved -> {root}")


def checklist(a, sym, sw, wf, mc, st) -> list[tuple[str, str, str]]:
    """Rules of thumb, not guarantees. Returns (status, check, detail)."""
    c = []
    def add(ok, name, detail, warn=False):
        c.append(("PASS" if ok else ("WARN" if warn else "FAIL"), name, detail))
    add(sw.get("lookahead_check") == "passed", "No look-ahead in indicators", str(sw.get("lookahead_check")))
    pp = sw.get("profitable_pct")
    add(pp is not None and pp >= 60, "Most parameter sets are profitable (>= 60%)", f"{pp}% of combinations with enough trades", warn=pp is not None and pp >= 40)
    bs = sw.get("best_score")
    if bs is None or bs <= 0:
        add(False, "Best setting is on a plateau, not a spike", f"not applicable: best score {bs} is not positive")
    else:
        add(not sw.get("best_is_isolated_spike", True), "Best setting is on a plateau, not a spike",
            f"best score {bs}, its neighbourhood {sw.get('best_neighbourhood_score')}")
    on, opf = wf.get("oos_net_pnl"), wf.get("oos_profit_factor")
    add(on is not None and on > 0, "Walk-forward out-of-sample is profitable", f"OOS net {on}")
    add(opf is not None and opf >= 1.1, "Walk-forward OOS profit factor >= 1.1", f"{opf}", warn=opf is not None and opf >= 1.0)
    eff = wf.get("walk_forward_efficiency")
    add(eff is not None and eff >= 0.5, "Walk-forward efficiency >= 0.5", f"{eff}", warn=eff is not None and eff >= 0.25)
    pf = wf.get("profitable_oos_folds_pct")
    add(pf is not None and pf >= 50, "At least half of OOS folds profitable", f"{pf}%")
    if "bootstrap" in mc:
        pl = mc["bootstrap"]["prob_final_loss_pct"]
        add(pl < 10, "Monte Carlo: chance of ending at a loss < 10%", f"{pl:.1f}%", warn=pl < 25)
        dd95 = -mc["bootstrap"]["max_drawdown_usd_pct"][95]
        lim = a.ruin or a.capital * 0.2
        add(dd95 <= lim, f"Monte Carlo: 95%-worst drawdown within ${lim:,.0f}", f"${dd95:,.0f}")
    sc = st["scenarios"].set_index("scenario")
    worst = [i for i in sc.index if i.startswith("ALL")]
    if worst:
        v = sc.loc[worst[0], "net_pnl"]
        add(v > 0, "Still profitable under combined worst-case execution", f"net {v:,.0f}")
    if "commission x2" in sc.index and get_instrument(sym).commission > 0:
        add(sc.loc["commission x2", "net_pnl"] > 0, "Still profitable with double commission", f"net {sc.loc['commission x2', 'net_pnl']:,.0f}")
    if "outlier_dependence" in st and len(st["outlier_dependence"]):
        v = st["outlier_dependence"].iloc[1].net_pnl
        add(v > 0, "Still profitable without the best 5% of trades", f"net {v:,.0f}", warn=True)
    return c


def write_overview(a, sym, root, sw, wf, mc, st, params, checks, secs):
    n_pass = sum(1 for s, _, _ in checks if s == "PASS")
    L = [f"# Robustness report: {Path(a.strategy).stem} on {sym}", "",
         f"Generated {datetime.now():%Y-%m-%d %H:%M} in {secs / 60:.1f} min. Data {a.start or 'start'} → {a.end or 'end'}, "
         f"{a.tf}-minute bars, capital ${a.capital:,.0f}, base params `{parse_sets(a.set)}`, grid `{parse_grid(a.grid)}`.", "",
         f"## Checklist: {n_pass}/{len(checks)} passed", "",
         "These are common rules of thumb, not guarantees. A FAIL means look closer, not necessarily discard.", "",
         "| Result | Check | Detail |", "|---|---|---|"]
    L += [f"| {s} | {n} | {d} |" for s, n, d in checks]
    L += ["", "## 1. Parameter test", f"Best: `{sw.get('best')}` (score {sw.get('best_score')}). "
          f"Plateau choice: `{sw.get('plateau_choice')}`. {sw.get('profitable_pct')}% of combinations profitable. "
          f"Objective: {sw.get('objective')}. Details: `sweep_*/sweep_report.txt`, heatmap `sweep_heatmaps.png`.",
          "", "## 2. Walk-forward (out-of-sample only)",
          f"{wf.get('folds')} {wf.get('mode')} folds ({wf.get('in_sample_months')} months optimise → {wf.get('out_of_sample_months')} months trade), "
          f"OOS {wf.get('oos_period')}: net **{wf.get('oos_net_pnl')}**, {wf.get('oos_trades')} trades, PF {wf.get('oos_profit_factor')}, "
          f"max DD {wf.get('oos_max_drawdown_usd')}, efficiency {wf.get('walk_forward_efficiency')}, "
          f"{wf.get('profitable_oos_folds_pct')}% of folds profitable. Details: `walkforward_*/`."]
    if mc:
        b = mc.get("bootstrap", {})
        L += ["", "## 3. Monte Carlo (on the walk-forward OOS trades)",
              f"Bootstrap, {b.get('simulations'):,} runs: median final P&L {b['final_pnl_pct'][50]:,.0f}, "
              f"5%-worst final {b['final_pnl_pct'][5]:,.0f}, chance of a loss {b['prob_final_loss_pct']:.1f}%, "
              f"median max DD {b['max_drawdown_usd_pct'][50]:,.0f}, 5%-worst max DD {b['max_drawdown_usd_pct'][95]:,.0f}, "
              f"5%-worst losing streak {b['longest_losing_streak_pct'][95]:.0f} trades."
              + (f" Chance of hitting the ${a.ruin:,.0f} loss limit: {b.get('prob_ruin_pct', 0):.2f}%." if a.ruin else ""),
              "Details: `montecarlo_bootstrap/`, `montecarlo_shuffle/`."]
    L += ["", f"## 4. Stress test (params `{params}`)", "", st["scenarios"].to_markdown(index=False) if _has_tabulate() else "```\n" + st["scenarios"].to_string(index=False) + "\n```",
          "", "Details: `stress/stress_report.txt`.", ""]
    (root / "ROBUSTNESS_REPORT.md").write_text("\n".join(L))


def _has_tabulate():
    try:
        import tabulate  # noqa: F401
        return True
    except ImportError:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["sweep", "walkforward", "montecarlo", "stress", "all"])
    ap.add_argument("strategy", nargs="?")
    ap.add_argument("--symbol", default="MNQ", help="comma-separated for several")
    ap.add_argument("--data"); ap.add_argument("--tf", type=int, default=1)
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--capital", type=float, default=50_000)
    ap.add_argument("--commission", type=float); ap.add_argument("--slippage", type=float); ap.add_argument("--spread", type=float)
    ap.add_argument("--set", nargs="*", help="fixed strategy parameters key=value")
    ap.add_argument("--grid", nargs="*", help="parameters to test key=v1,v2,.. or key=start:stop:step")
    ap.add_argument("--objective", default="sharpe", choices=["sharpe", "profit_factor", "net_pnl", "expectancy", "return_dd"])
    ap.add_argument("--min-trades", type=int, default=30, help="ignore parameter sets with fewer trades")
    ap.add_argument("--select", default="plateau", choices=["plateau", "best"], help="walk-forward parameter choice")
    ap.add_argument("--is-months", type=int, default=24); ap.add_argument("--oos-months", type=int, default=6)
    ap.add_argument("--anchored", action="store_true", help="in-sample always starts at the beginning of the data")
    ap.add_argument("--warmup-days", type=int, default=10, help="extra past days loaded before each window for indicators")
    ap.add_argument("--from", dest="from_dir", help="Monte Carlo on an existing results folder")
    ap.add_argument("--method", default="bootstrap", choices=["bootstrap", "shuffle", "daily"])
    ap.add_argument("--sims", type=int, default=10_000); ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--block", type=int, default=5, help="block length (days) for --method daily")
    ap.add_argument("--skip", type=float, default=0.0, help="%% of trades randomly missed")
    ap.add_argument("--haircut", type=float, default=0.0, help="%% cut from every winning trade")
    ap.add_argument("--ruin", type=float, help="loss limit in $ (e.g. prop-firm max drawdown)")
    ap.add_argument("--workers", type=int, default=None, help=f"parallel processes (default {default_workers()})")
    ap.add_argument("--force", action="store_true", help="run even if the look-ahead check fails")
    a = ap.parse_args()
    if a.command == "montecarlo" and a.from_dir:
        return cmd_montecarlo(a)
    if not a.strategy:
        ap.error("strategy file is required")
    for sym in a.symbol.split(","):
        {"sweep": cmd_sweep, "walkforward": cmd_walkforward, "montecarlo": cmd_montecarlo,
         "stress": cmd_stress, "all": cmd_all}[a.command](a, sym)


if __name__ == "__main__":
    main()
