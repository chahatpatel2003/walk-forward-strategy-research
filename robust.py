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
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from engine import INSTRUMENTS, Settings, check_lookahead, data, get_instrument, metrics  # noqa: E402
from engine import montecarlo, stress, sweep, walkforward  # noqa: E402
from engine.data import _assert_not_data_path  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from engine.parallel import Job, default_workers  # noqa: E402
from engine.pairs import check_lookahead_pairs, is_pairs, load_pair, pair_key  # noqa: E402

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
    """A new, unique results folder (never shared by two runs, even started in the same second)."""
    stem = f"{datetime.now():%Y%m%d_%H%M%S}_{kind}_{Path(strategy).stem}_{sym}"
    for k in range(10_000):
        p = RESULTS / (stem if k == 0 else f"{stem}_{k}")
        _assert_not_data_path(p)
        try:
            p.mkdir(parents=True, exist_ok=False)
            return p
        except FileExistsError:
            continue
    raise RuntimeError(f"could not create a unique folder for {stem}")


DATASETS_FOR = {"NQ": {"NQ"}, "MNQ": {"NQ"}, "GC": {"GC"}, "MGC": {"GC"}, "XAUUSD": {"XAUUSD"},
                 "NAS100": {"NAS100", "NAS100_RTH"}}


def check_dataset(symbol: str, key: str):
    """Refuse to price one market's data with another market's contract (e.g. NQ data as XAUUSD)."""
    ok = DATASETS_FOR.get(symbol.upper(), {symbol.upper()})
    if key.upper() not in ok:
        raise SystemExit(f"dataset {key!r} does not belong to instrument {symbol!r}; allowed: {sorted(ok)}")


def check_pair_instrument(symbol: str, cls):
    """A pair strategy trades its first leg with `symbol`: the symbol's dataset must be that leg's."""
    inst = get_instrument(symbol)
    if inst.data_key != cls.LEGS[0]:
        raise SystemExit(f"{cls.__name__} trades {cls.LEGS[0]} as its first leg; {symbol!r} uses {inst.data_key!r} data. "
                         f"Use one of: {[k for k, v in INSTRUMENTS.items() if v.data_key == cls.LEGS[0]]}")


def make_job(a, sym: str) -> tuple[Job, pd.DataFrame]:
    inst = get_instrument(sym)
    over = {k: v for k, v in (("commission", a.commission), ("slippage_ticks", a.slippage), ("spread", a.spread)) if v is not None}
    if over:
        inst = inst.with_costs(**over)
    cls = load_strategy(a.strategy)
    if is_pairs(cls):
        check_pair_instrument(inst.name, cls)
        key = pair_key(cls)
        df = load_pair(*cls.LEGS, tf=1, session="full", start=a.start, end=a.end)
    else:
        key = a.data or inst.data_key
        check_dataset(inst.name, key)
        df = data.load(key, a.start, a.end)
    if not len(df):
        raise SystemExit(f"no data for {inst.name} ({key}) between {a.start or 'the start'} and {a.end or 'the end'}; "
                         f"choose dates inside the available history")
    session = getattr(a, "session", "full")
    if session != "full" and not len(data.session_filter(df, session)):
        raise SystemExit(f"no bars in the {session} session for {inst.name} ({key}) between {a.start or 'the start'} "
                         f"and {a.end or 'the end'}: nothing to backtest")
    settings = Settings(capital=a.capital, account_constrained=getattr(a, "account_constrained", False))
    job = Job(str(Path(a.strategy).resolve()), key, a.tf, inst, settings, parse_sets(a.set),
              start=str(df.tday.iloc[0])[:10], end=str(df.tday.iloc[-1])[:10], warmup_days=a.warmup_days,
              session=a.session)
    return job, df


_LA_REUSE: dict | None = None      # passed checks within ONE `robust all` run (None = every command checks afresh)


@contextmanager
def lookahead_reuse():
    """Inside this block a parameter set already checked on the same strategy, data, period and settings is not
    checked again (cmd_all: the sweep, the walk-forward and the stress test check the same sets)."""
    global _LA_REUSE
    keep, _LA_REUSE = _LA_REUSE, {}
    try:
        yield
    finally:
        _LA_REUSE = keep


def _la_key(a, job: Job, bars: pd.DataFrame, params: dict) -> str:
    span = (int(bars.ts.iloc[0]), int(bars.ts.iloc[-1]), len(bars)) if len(bars) else (0, 0, 0)
    return json.dumps([str(Path(a.strategy).resolve()), job.inst.name, a.tf, a.session, span, repr(job.settings),
                       params], sort_keys=True, default=str)


def lookahead_gate(a, job: Job, df: pd.DataFrame, extra_params: list[dict] | None = None) -> str:
    """Look-ahead check (indicators AND on_bar trades, see core.check_lookahead) on the WHOLE selected period, for
    the base parameters and every parameter set that will be tested (if there are more than 40, an even sample of
    40 is checked and the message says so). The returned message states the dates, bars and sets covered. Inside
    lookahead_reuse() a set that already passed on the same data and settings is not re-checked (and the message
    says how many were reused)."""
    cls = load_strategy(a.strategy)
    every = [job.params] + [{**job.params, **p} for p in (extra_params or [])]
    uniq = []
    for p in every:
        if p not in uniq:
            uniq.append(p)
    sets = uniq if len(uniq) <= 40 else [uniq[int(k)] for k in np.linspace(0, len(uniq) - 1, 40)]
    bars = load_pair(*cls.LEGS, tf=a.tf, session=a.session, start=a.start, end=a.end) if is_pairs(cls) \
        else data.resample(df, a.tf, a.session)
    span = (f"{str(bars.tday.iloc[0])[:10]} to {str(bars.tday.iloc[-1])[:10]}, {len(bars):,} bars"
            if len(bars) else "no bars")
    cover = f"{len(sets)} of {len(uniq)} parameter set{'s' if len(uniq) > 1 else ''}" + (" (even sample)" if len(sets) < len(uniq) else "")
    reused, bcuts, drows = 0, [], []
    for params in sets:
        key = _la_key(a, job, bars, params) if _LA_REUSE is not None else None
        if key is not None and key in _LA_REUSE:
            reused += 1
            continue
        cov = {}
        if is_pairs(cls):
            bad = check_lookahead_pairs(lambda p=params: cls(**p), bars, job.inst, get_instrument(cls.INST_B), job.settings,
                                        coverage=cov)
        else:
            bad = check_lookahead(lambda p=params: cls(**p), bars, job.inst, job.settings, coverage=cov)
        bcuts.append(cov.get("boundary_cuts", 0)); drows.append(cov.get("decision_rows") or 0)
        if bad:
            msg = f"FAILED for params {params}: " + "; ".join(bad) + f" [checked {span}; {cover}]"
            if not a.force:
                raise SystemExit(f"!! look-ahead check {msg}. Fix the strategy (or pass --force to run anyway).")
            return msg + " (run anyway with --force)"
        if key is not None:
            _LA_REUSE[key] = True
    note = f"; {reused} already checked in this run" if reused else ""
    feat = (f"; features also re-checked at {min(bcuts)}-{max(bcuts)} cuts per set right after decision bars "
            f"({min(drows):,}-{max(drows):,} per set) and signal flips" if bcuts else "")
    return f"passed ({span}; {cover}{note}{feat})"


def trading_days(df):
    return np.unique(df.tday.to_numpy().astype("datetime64[D]"))


def fold_days(df: pd.DataFrame, tf: int, session: str = "full") -> np.ndarray:
    """Trading days that actually have bars in the traded session (cash-session runs exclude holidays and
    days without cash-session data): walk-forward folds and their day counts are built from these."""
    return trading_days(data.session_filter(df, session))


# ------------------------------------------------------------------------------------ commands
def cmd_sweep(a, sym):
    job, df = make_job(a, sym)
    grid = parse_grid(a.grid)
    if not grid:
        raise SystemExit("--grid is required, e.g. --grid rr=1.5,2,3 or_minutes=5,15,30")
    la = lookahead_gate(a, job, df, sweep.expand_grid(grid))
    out = outdir("sweep", a.strategy, sym)
    print(f"parameter test: {len(sweep.expand_grid(grid))} combinations on {sym}")
    res = sweep.run_sweep(job, grid, a.objective, a.min_trades, a.workers)
    info = sweep.report(res, grid, out, a.objective, f"{Path(a.strategy).stem} on {sym}", a.min_trades)
    info["lookahead_check"] = la
    print((out / "sweep_report.txt").read_text()); print(f"saved -> {out}")
    return info, res, out


def cmd_walkforward(a, sym):
    job, df = make_job(a, sym)
    grid = parse_grid(a.grid)
    if not grid:
        raise SystemExit("--grid is required for walk-forward")
    la = lookahead_gate(a, job, df, sweep.expand_grid(grid))
    out = outdir("walkforward", a.strategy, sym)
    days = trading_days(load_pair(*load_strategy(a.strategy).LEGS, tf=1, session=a.session, start=a.start, end=a.end)) \
        if is_pairs(load_strategy(a.strategy)) else fold_days(df, a.tf, a.session)
    wf = walkforward.run(job, grid, days, a.is_months, a.oos_months, a.anchored, a.objective,
                         a.min_trades, a.select, a.workers)
    info = walkforward.report(wf, out, f"{Path(a.strategy).stem} on {sym}")
    info["lookahead_check"] = la
    print((out / "walkforward_report.txt").read_text()); print(f"saved -> {out}")
    return info, wf, out


def _scheduled_period(f: pd.DataFrame, summary_json: Path | None = None) -> pd.Series:
    """Each fold's place in the walk-forward schedule. Saved since the ninth revision as `period`; older folders are
    rebuilt from the calendar: windows are whole months counted from the first one, `step` months long (the saved
    summary's out_of_sample_months, else the longest month span of any fold), so a scheduled window with no data at
    all still leaves a hole."""
    if "period" in f and f.period.notna().all():
        return f.period.astype(int)
    step = None
    if summary_json is not None and summary_json.exists():
        try:
            step = int(json.loads(summary_json.read_text()).get("out_of_sample_months") or 0) or None
        except (ValueError, TypeError):
            step = None
    a = pd.to_datetime(f.oos_start).dt.to_period("M").astype("int64")
    if step is None:
        b = pd.to_datetime(f.oos_end).dt.to_period("M").astype("int64")
        step = int((b - a).max()) + 1 if len(f) else 1
    return ((a - a.min()) // step).astype(int)


def daily_segments(dates: pd.Series, folds_csv: Path) -> list[int] | None:
    """Lengths of the continuous runs of days in a saved daily equity file. A walk-forward file joins the scored
    out-of-sample windows; where a scheduled window was skipped (no valid parameters) or had no data at all, the
    history has a hole, and the days on either side belong to different segments. Without a folds file the whole
    history is one segment."""
    if not folds_csv.exists() or not len(dates):
        return None
    f = pd.read_csv(folds_csv)
    if "oos_start" not in f:
        return None
    f = f.assign(_period=_scheduled_period(f, folds_csv.parent / "walkforward_summary.json"))
    scored = f.dropna(subset=["oos_net_pnl"]) if "oos_net_pnl" in f else f
    seg_id = np.full(len(dates), -1)
    run, prev, prev_fold = -1, None, None
    for _, r in scored.sort_values(["_period", "fold"]).iterrows():
        if prev is None or r._period != prev + 1 or r.fold != prev_fold + 1:
            run += 1                         # a skipped or absent window (or the first one) starts a new segment
        m = (dates >= pd.Timestamp(r.oos_start)) & (dates <= pd.Timestamp(r.oos_end))
        seg_id[m.to_numpy()] = run
        prev, prev_fold = r._period, r.fold
    if (seg_id < 0).any():
        return None                                        # dates outside the scored windows: don't guess
    change = np.r_[True, seg_id[1:] != seg_id[:-1]]
    bounds = np.r_[np.flatnonzero(change), len(seg_id)]
    return [int(x) for x in np.diff(bounds)]


def _mc_from_trades(a, trades: pd.DataFrame, daily_equity, capital, out: Path, title: str, segments=None):
    """daily_equity: equity at the end of EVERY trading day (flat days included), needed for --method daily.
    segments: lengths of the continuous runs of days (daily blocks never cross from one to the next)."""
    if a.method == "daily":
        if daily_equity is None or len(daily_equity) < 2:
            raise SystemExit("daily Monte Carlo needs the daily equity file (days without trades cannot be "
                             "recovered from a trade list). Re-run the backtest/walk-forward to create it.")
        items = np.diff(np.concatenate([[capital], np.asarray(daily_equity, dtype=float)]))
        try:
            mc = montecarlo.simulate(items, capital, a.sims, a.method, a.seed, a.block, a.skip, a.haircut, a.ruin,
                                     segments=segments)
        except ValueError as e:
            raise SystemExit(f"daily Monte Carlo: {e}")
        info = montecarlo.report(mc, out, title)
        print((out / "montecarlo_report.txt").read_text()); print(f"saved -> {out}")
        return info
    items = trades.pnl.to_numpy()
    mc = montecarlo.simulate(items, capital, a.sims, a.method, a.seed, a.block, a.skip, a.haircut, a.ruin)
    info = montecarlo.report(mc, out, title)
    print((out / "montecarlo_report.txt").read_text()); print(f"saved -> {out}")
    return info


def saved_capital(src: Path) -> float | None:
    """Starting capital recorded in a saved results folder: a backtest's summary.json, or a walk-forward's
    walkforward_summary.json (stored in its out-of-sample summary). None if neither records it."""
    for name, path in (("summary.json", ("capital",)), ("walkforward_summary.json", ("oos_full_summary", "capital"))):
        f = src / name
        if f.exists():
            v = json.loads(f.read_text())
            for k in path:
                v = v.get(k) if isinstance(v, dict) else None
            if v is not None:
                return float(v)
    return None


def cmd_montecarlo(a, sym=None):
    if a.from_dir:
        src = Path(a.from_dir)
        f = src / "walkforward_oos_trades.csv" if (src / "walkforward_oos_trades.csv").exists() else src / "trades.csv"
        try:
            trades = pd.read_csv(f)
        except pd.errors.EmptyDataError:
            trades = pd.DataFrame()
        if a.method != "daily" and len(trades) < 2:
            raise SystemExit(f"{f} has {len(trades)} trades: nothing to simulate")
        out = src / f"montecarlo_{a.method}"
        cap = saved_capital(src)
        if cap is None:
            print(f"warning: {src} records no starting capital; using --capital {a.capital:,.0f}")
            cap = a.capital
        eq, segments = None, None
        for name in ("walkforward_oos_daily_equity.csv", "daily_equity.csv"):
            if (src / name).exists():
                e = pd.read_csv(src / name)
                eq = e["equity"].to_numpy()
                date_col = "tday" if "tday" in e else e.columns[0]
                segments = daily_segments(pd.to_datetime(e[date_col]), src / "walkforward_folds.csv")
                break
        return _mc_from_trades(a, trades, eq, cap, out, f"{src.name} ({f.name})", segments)
    job, df = make_job(a, sym)
    lookahead_gate(a, job, df)
    from engine.parallel import run_job
    r = run_job(job)
    out = outdir("montecarlo", a.strategy, sym)
    r["trades"].to_csv(out / "trades.csv", index=False)
    eq = r["daily"].equity.to_numpy() if r["daily"] is not None else None
    return _mc_from_trades(a, r["trades"], eq, a.capital, out, f"{Path(a.strategy).stem} on {sym}")


def cmd_stress(a, sym, params=None, out=None):
    job, df = make_job(a, sym)
    if params:
        job = job.with_(params={**job.params, **params})
    lookahead_gate(a, job, df)
    out = out or outdir("stress", a.strategy, sym)
    daily = data.resample(df, 1440, a.session)
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
        with lookahead_reuse():               # the sweep, walk-forward and stress test check overlapping sets
            sw, sw_df, _ = cmd_sweep(a, sym)
            wf_info, wf, wf_out = cmd_walkforward(a, sym)
            oos = wf["oos_result"]["trades"]
            mc_info = {}
            if len(oos) >= 2:
                for m in ("bootstrap", "shuffle"):
                    a.method = m
                    mc_info[m] = _mc_from_trades(a, oos, metrics.daily_equity(wf["oos_result"]).to_numpy(), a.capital, root / f"montecarlo_{m}",
                                                 f"{Path(a.strategy).stem} on {sym}: walk-forward OOS trades, {m}")
            params = sw.get("plateau_choice") or sw.get("best") or {}
            st_info, st = cmd_stress(a, sym, params, root / "stress")
    finally:
        RESULTS = keep
    checks = checklist(a, sym, sw, wf_info, mc_info, st)
    write_overview(a, sym, root, sw, wf_info, mc_info, st, params, checks, time.time() - t0)
    print((root / "ROBUSTNESS_REPORT.md").read_text())
    print(f"saved -> {root}")
    return {"root": root, "sweep": sw, "walkforward": wf_info, "montecarlo": mc_info, "stress": st,
            "params": params, "checks": checks, "folds": wf["folds"]}


def checklist(a, sym, sw, wf, mc, st) -> list[tuple[str, str, str]]:
    """Rules of thumb, not guarantees. Returns (status, check, detail)."""
    c = []
    def add(ok, name, detail, warn=False):
        c.append(("PASS" if ok else ("WARN" if warn else "FAIL"), name, detail))
    add(str(sw.get("lookahead_check", "")).startswith("passed"), "No look-ahead (indicators and trade decisions)", str(sw.get("lookahead_check")))
    pp = sw.get("profitable_pct")
    add(pp is not None and pp >= 60, "Most parameter sets are profitable (>= 60%)", f"{pp}% of combinations with enough trades", warn=pp is not None and pp >= 40)
    bs = sw.get("best_score")
    if bs is None or bs <= 0:
        add(False, "Best setting is on a plateau, not a spike", f"not applicable: best score {bs} is not positive")
    else:
        add(not sw.get("best_is_isolated_spike", True), "Best setting is on a plateau, not a spike",
            f"best score {bs:.3f}, its neighbourhood {sw.get('best_neighbourhood_score', float('nan')):.3f}")
    on, opf = wf.get("oos_net_pnl"), wf.get("oos_profit_factor")
    wf_broke = wf.get("oos_capital_exhausted_on")
    add(on is not None and on > 0 and not wf_broke, "Walk-forward out-of-sample is profitable",
        f"OOS net {on}" + (f"; account hit $0 on {wf_broke} and stopped trading" if wf_broke else ""))
    add(opf is not None and opf >= 1.1, "Walk-forward OOS profit factor >= 1.1", f"{opf}", warn=opf is not None and opf >= 1.0)
    eff = wf.get("walk_forward_efficiency")
    note = wf.get("walk_forward_efficiency_note")
    add(eff is not None and eff >= 0.5, "Walk-forward efficiency >= 0.5",
        (f"{eff}" if eff is not None else "not available") + (f" ({note})" if note else ""),
        warn=eff is not None and eff >= 0.25)
    pf = wf.get("profitable_oos_folds_pct")
    add(pf is not None and pf >= 50, "At least half of OOS folds profitable", f"{pf}%")
    if "bootstrap" in mc:
        pl = mc["bootstrap"]["prob_final_loss_pct"]
        add(pl < 10, "Monte Carlo: chance of ending at a loss < 10%", f"{pl:.1f}%", warn=pl < 25)
        dd95 = -mc["bootstrap"]["max_drawdown_usd_pct"][95]
        lim = a.ruin or a.capital * 0.2
        add(dd95 <= lim, f"Monte Carlo: 95%-worst drawdown within ${lim:,.0f}", f"${dd95:,.0f}")
    sc = st["scenarios"].set_index("scenario")
    comm = st.get("baseline_commission", get_instrument(sym).commission)

    def scenario_check(name, label):
        v = sc.loc[name, "net_pnl"]
        broke = sc.loc[name, "capital_exhausted_on"] if "capital_exhausted_on" in sc else None
        broke = broke if isinstance(broke, str) and broke else None
        add(v > 0 and not broke, label, f"net {v:,.0f}" + (f"; account hit $0 on {broke}" if broke else ""))
    combined = [i for i in sc.index if i.startswith("ALL")]
    if combined:
        scenario_check(combined[0], "Still profitable under combined execution stress")
    if "commission x2" in sc.index and comm > 0:
        scenario_check("commission x2", "Still profitable with double commission")
    if len(sc):
        nets = sc.net_pnl.astype(float)
        w = nets.idxmin()
        brk = sc.capital_exhausted_on if "capital_exhausted_on" in sc else pd.Series(index=sc.index, dtype=object)
        broke = [n for n, v in brk.items() if isinstance(v, str) and v]
        add(nets.min() > 0 and not broke, "Still profitable in every tested execution scenario",
            f"worst: {w}, net {nets.min():,.0f}" + (f"; hit $0 in: {', '.join(broke)}" if broke else ""))
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


def positive_int(text: str) -> int:
    v = int(text)
    if v < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {v}")
    return v


def percent(text: str) -> float:
    v = float(text)
    if not (0 <= v <= 100):
        raise argparse.ArgumentTypeError(f"must be between 0 and 100, got {v}")
    return v


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["sweep", "walkforward", "montecarlo", "stress", "all"])
    ap.add_argument("strategy", nargs="?")
    ap.add_argument("--symbol", default="MNQ", help="comma-separated for several")
    ap.add_argument("--data"); ap.add_argument("--tf", type=int, default=1)
    ap.add_argument("--session", default="full", choices=["full", "rth"], help="rth = New York cash session 09:30-16:00 only")
    ap.add_argument("--start"); ap.add_argument("--end")
    ap.add_argument("--capital", type=float, default=50_000)
    ap.add_argument("--commission", type=float); ap.add_argument("--slippage", type=float); ap.add_argument("--spread", type=float)
    ap.add_argument("--set", nargs="*", help="fixed strategy parameters key=value")
    ap.add_argument("--grid", nargs="*", help="parameters to test key=v1,v2,.. or key=start:stop:step")
    ap.add_argument("--objective", default="sharpe", choices=["sharpe", "profit_factor", "net_pnl", "expectancy", "return_dd"])
    ap.add_argument("--min-trades", type=int, default=30, help="ignore parameter sets with fewer trades")
    ap.add_argument("--select", default="plateau", choices=["plateau", "best"], help="walk-forward parameter choice")
    ap.add_argument("--is-months", type=positive_int, default=24); ap.add_argument("--oos-months", type=positive_int, default=6)
    ap.add_argument("--anchored", action="store_true", help="in-sample always starts at the beginning of the data")
    ap.add_argument("--warmup-days", type=int, default=10, help="extra past days loaded before each window for indicators")
    ap.add_argument("--from", dest="from_dir", help="Monte Carlo on an existing results folder")
    ap.add_argument("--method", default="bootstrap", choices=["bootstrap", "shuffle", "daily"])
    ap.add_argument("--sims", type=positive_int, default=10_000); ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--block", type=positive_int, default=5, help="block length (days) for --method daily")
    ap.add_argument("--skip", type=percent, default=0.0, help="%% of trades randomly missed (0-100)")
    ap.add_argument("--haircut", type=percent, default=0.0, help="%% cut from every winning trade (0-100)")
    ap.add_argument("--ruin", type=float, help="loss limit in $ (e.g. prop-firm max drawdown)")
    ap.add_argument("--workers", type=int, default=None, help=f"parallel processes (default {default_workers()})")
    ap.add_argument("--force", action="store_true", help="run even if the look-ahead check fails")
    ap.add_argument("--account-constrained", action="store_true",
                    help="stop trading when the account's marked equity reaches 0 (close the position, refuse new orders)")
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
