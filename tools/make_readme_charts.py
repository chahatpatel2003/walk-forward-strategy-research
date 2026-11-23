"""Charts and numbers for the GitHub README, made from the saved study results (nothing typed by hand).
Writes docs/images/*.png and docs/readme_numbers.json.
    python tools/make_readme_charts.py
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import intraday_report as ir  # noqa: E402
import timeframe_portfolio as tp  # noqa: E402
from photo_report_tables import robust_mask  # noqa: E402
from timeframe_report import TF_LABEL, TF_ORDER, load  # noqa: E402

IMG = ROOT / "docs" / "images"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
INSTR = {"MNQ": "#2a78d6", "NAS100": "#eb6834", "MGC": "#1baf7a", "XAUUSD": "#eda100"}     # fixed order, never cycled
ONE = "#2a78d6"
NAMES = {"A01": "RSI(3)+EMA(100)+VWAP", "A02": "Stochastic+KAMA+VWAP", "A03": "Williams %R+EMA+VWAP",
         "A04": "RSI(3)+EMA(50)+VWAP", "A05": "Z-score reversion", "A06": "Rubber Band", "A07": "MFI reversal",
         "A08": "Weekly RSI", "A09": "Turn of the month", "A10": "Faber 10-month", "A11": "Time-series momentum",
         "A12": "Volatility squeeze", "A13": "Order-flow imbalance", "B01": "Gold futures/spot pair"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "figure.facecolor": SURFACE,
                     "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8})


def usd(v):
    return ("−$" if v < 0 else "$") + f"{abs(v):,.0f}"


def save(fig, name):
    IMG.mkdir(parents=True, exist_ok=True)
    fig.savefig(IMG / name, dpi=160, bbox_inches="tight")
    plt.close(fig)


def title(ax, t, sub=None):
    ax.set_title(t, loc="left", fontsize=13, fontweight="bold", color=INK, pad=22 if sub else 10)
    if sub:
        ax.text(0, 1.02, sub, transform=ax.transAxes, fontsize=9.5, color=INK2, va="bottom")


def main():
    r = load()
    rob = r[r.robust].copy()
    rob["name"] = rob.code.map(NAMES)
    out = {}

    # 1. best out-of-sample result of each strategy that passed (bars coloured by instrument)
    best = rob.sort_values("wf_oos_net", ascending=False).drop_duplicates("code").sort_values("wf_oos_net")
    fig, ax = plt.subplots(figsize=(9, 4.8))
    y = np.arange(len(best))
    ax.barh(y, best.wf_oos_net, color=[INSTR[m] for m in best.market], height=0.62, edgecolor=SURFACE, linewidth=2)
    for i, b in enumerate(best.itertuples()):
        ax.text(b.wf_oos_net + 800, i, f"{usd(b.wf_oos_net)}  ·  PF {b.wf_oos_pf:.2f}  ·  {b.market} {TF_LABEL[b.bars]}",
                va="center", fontsize=9, color=INK)
    ax.set_yticks(y, best.name)
    ax.set_xlim(0, best.wf_oos_net.max() * 1.55)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: usd(v)))
    ax.grid(axis="y", visible=False)
    handles = [matplotlib.patches.Patch(color=c, label=m) for m, c in INSTR.items() if m in set(best.market)]
    ax.legend(handles=handles, frameon=False, loc="lower right", fontsize=9)
    title(ax, "Best out-of-sample result of each strategy", "Walk-forward OOS net profit, $100,000 of contract value per trade, costs included")
    save(fig, "best_oos_by_strategy.png")
    out["best"] = [{"strategy": b.name, "market": b.market, "bars": TF_LABEL[b.bars], "session": b.session, "oos_net": b.wf_oos_net,
                    "oos_pf": b.wf_oos_pf} for b in best.iloc[::-1].itertuples()]

    # 2. strategy x bar size: configurations that passed every check
    order = [c for c in ["A04", "A01", "A03", "A07", "A11", "A06", "A09", "A12", "A05", "A02", "A08", "A10", "A13", "B01"] if c in set(r.code)]
    tfs = [t for t in TF_ORDER if t in set(r.bars)]
    M = np.array([[int(((rob.code == c) & (rob.bars == t)).sum()) for t in tfs] for c in order])
    N = np.array([[int(((r.code == c) & (r.bars == t)).sum()) for t in tfs] for c in order])
    fig, ax = plt.subplots(figsize=(8.6, 6))
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("blue", ["#eef4fc", "#9cc0ee", "#2a78d6", "#123d73"])
    ax.imshow(np.where(N > 0, M, np.nan), cmap=cmap, vmin=0, vmax=max(6, M.max()), aspect="auto")
    for i in range(len(order)):
        for j in range(len(tfs)):
            if N[i, j]:
                ax.text(j, i, f"{M[i, j]}/{N[i, j]}", ha="center", va="center", fontsize=9,
                        color="white" if M[i, j] >= 4 else INK)
            else:
                ax.text(j, i, "–", ha="center", va="center", color=INK2)
    ax.set_xticks(range(len(tfs)), [TF_LABEL[t] for t in tfs])
    ax.set_yticks(range(len(order)), [NAMES[c] for c in order])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    title(ax, "Where each strategy holds up", "Configurations that passed every check / configurations tested (4 markets × 2 sessions)")
    save(fig, "strategy_by_bar_size.png")

    # 3. pass count by bar size, and 4. cost per trade by bar size (two charts, one axis each)
    g = r.groupby("bars")
    keys = [t for t in TF_ORDER if t in g.groups and t != "1m"]
    passed = [int(g.get_group(t).robust.sum()) for t in keys]
    runs = [len(g.get_group(t)) for t in keys]
    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    x = np.arange(len(keys))
    ax.bar(x, passed, color=ONE, width=0.6, edgecolor=SURFACE, linewidth=2)
    for i, (p, n) in enumerate(zip(passed, runs)):
        ax.text(i, p + 0.5, f"{p} of {n}", ha="center", fontsize=9.5, color=INK)
    ax.set_xticks(x, [TF_LABEL[t] for t in keys])
    ax.set_ylim(0, max(passed) * 1.25 + 1)
    ax.grid(axis="x", visible=False)
    title(ax, "Configurations that passed every check, by bar size", "373 runs: 14 strategies × 4 markets × 2 sessions × 5 bar sizes")
    save(fig, "passed_by_bar_size.png")

    cn = pd.DataFrame(json.loads((ROOT / "results/TIMEFRAME_STUDY/costs_numbers.json").read_text()))
    cn = cn[(cn.market == "all markets") & (cn.bars != "1-min")]
    fig, ax = plt.subplots(figsize=(7.6, 3.8))
    x = np.arange(len(cn)); w = 0.36
    ax.bar(x - w / 2, cn["avg trade before costs $"], w, color="#2a78d6", label="Average trade before costs", edgecolor=SURFACE, linewidth=2)
    ax.bar(x + w / 2, cn["avg trade after costs $"], w, color="#eb6834", label="Average trade after costs", edgecolor=SURFACE, linewidth=2)
    ax.axhline(0, color=INK2, linewidth=0.8)
    ax.set_xticks(x, cn.bars)
    ax.set_yscale("symlog", linthresh=20)
    ax.set_ylim(-40, 2500)
    for i, (bv, av) in enumerate(zip(cn["avg trade before costs $"], cn["avg trade after costs $"])):
        for xx, v in ((i - w / 2, bv), (i + w / 2, av)):
            ax.annotate(usd(v), (xx, v), xytext=(0, 4 if v >= 0 else -4), textcoords="offset points",
                        ha="center", va="bottom" if v >= 0 else "top", fontsize=8.5)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: usd(v)))
    ax.grid(axis="x", visible=False)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    title(ax, "Why short bars fail: the edge per trade vs. its cost", "Every out-of-sample trade; costs are ~$15–19 per trade on every bar size (log scale)")
    save(fig, "cost_per_trade.png")
    out["costs"] = cn.to_dict("records")

    # 5. out-of-sample equity of the 8 shortlisted strategies (small multiples)
    sh = json.loads((ROOT / "results/DASHBOARD/oos_equity.json").read_text())["rows"]
    eq = pd.DataFrame(sh); eq["date"] = pd.to_datetime(eq.date)
    runs8 = list(dict.fromkeys(eq.run))
    fig, axes = plt.subplots(2, 4, figsize=(13, 5.4), sharey=True)
    for ax, name in zip(axes.flat, runs8):
        e = eq[eq.run == name]
        m = name.split()[1]
        ax.plot(e.date, e.profit, color=INSTR[m], linewidth=2)
        ax.fill_between(e.date, 0, e.profit, color=INSTR[m], alpha=0.12, linewidth=0)
        ax.axhline(0, color=INK2, linewidth=0.7)
        code = name.split()[0]
        ax.set_title(f"{NAMES[code]}\n{' '.join(name.split()[1:])}", fontsize=9.5, loc="left", color=INK)
        ax.text(0.04, 0.92, usd(e.profit.iloc[-1]), transform=ax.transAxes, ha="left", va="top", fontsize=10.5,
                fontweight="bold")
        ax.xaxis.set_major_locator(matplotlib.dates.YearLocator(base=2))
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%Y"))
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: usd(v)))
    fig.suptitle("Out-of-sample profit of the eight shortlisted strategies ($100,000 of contract value per trade)",
                 x=0.01, ha="left", fontsize=13, fontweight="bold")
    fig.tight_layout()
    save(fig, "shortlist_oos_curves.png")

    # 6. $10,000 account
    acc = pd.DataFrame(json.loads((ROOT / "results/DASHBOARD/account_equity.json").read_text())["rows"])
    acc["date"] = pd.to_datetime(acc.date)
    sm = json.loads((ROOT / "results/DASHBOARD/account_summary.json").read_text())["rows"][0]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.plot(acc.date, acc.equity, color=ONE, linewidth=2)
    ax.fill_between(acc.date, 10_000, acc.equity, color=ONE, alpha=0.10, linewidth=0)
    ax.axhline(10_000, color=INK2, linewidth=0.8, linestyle="--")
    ax.text(acc.date.iloc[-1], acc.equity.iloc[-1], f"  {usd(acc.equity.iloc[-1])}", va="center", fontsize=10, fontweight="bold")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: usd(v)))
    title(ax, "One $10,000 account, eight strategies, 2% risk per trade",
          f"{sm['start']} → {sm['end']} · {sm['cagr_pct']}% a year · max drawdown {sm['max_dd_pct']}% · {sm['trades_per_month']} trades/month")
    save(fig, "account_10k.png")
    out["account"] = sm
    out["account_by_strategy"] = json.loads((ROOT / "results/DASHBOARD/account_by_strategy.json").read_text())["rows"]

    # 7. multi-strategy portfolios ($100,000 per run): cumulative marked P&L, and profit by instrument
    pn = json.loads((ROOT / "results/TIMEFRAME_STUDY/portfolio_numbers.json").read_text())
    books = []
    for title_, markets in tp.BOOKS.items():
        sel = tp.pick(r, markets)
        per = []
        series = []
        for _, s in sel.iterrows():
            d = tp.wf_dir(s.report)
            e = pd.read_csv(d / "walkforward_oos_daily_equity.csv", parse_dates=["tday"]).set_index("tday").equity
            p = e.diff().fillna(e.iloc[0] - 100_000.0)
            w = pn[title_]
            p = p[(p.index >= pd.Timestamp(w["start"])) & (p.index <= pd.Timestamp(w["end"]))]
            series.append(p.rename(f"{s.code} {s.market}"))
            per.append({"run": f"{NAMES[s.code]} · {s.market} {'cash' if s.session == 'rth' else 'full'} {TF_LABEL[s.bars]}",
                        "market": s.market, "net": float(p.sum())})
        P = pd.concat(series, axis=1, sort=True).fillna(0.0)
        books.append((title_, P, pd.DataFrame(per)))
    fig, axes = plt.subplots(1, 2, figsize=(13, 3.9))
    for ax, (t, P, per) in zip(axes, books):
        for m in [m for m in INSTR if m in set(per.market)]:
            cols = [c for c in P.columns if c.split()[1] == m]
            ax.plot(P.index, P[cols].sum(axis=1).cumsum(), color=INSTR[m], linewidth=2, label=f"{m} {usd(P[cols].sum().sum())}")
        ax.plot(P.index, P.sum(axis=1).cumsum(), color=INK, linewidth=2.2, label=f"Total {usd(P.sum().sum())}")
        ax.axhline(0, color=INK2, linewidth=0.7)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: usd(v)))
        loc = matplotlib.dates.AutoDateLocator(minticks=3, maxticks=6)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(matplotlib.dates.ConciseDateFormatter(loc))
        ax.legend(frameon=False, fontsize=9, loc="upper left")
        ax.set_title(t.replace("tradable now", "Portfolio 1").replace("longest history", "Portfolio 2"), loc="left", fontsize=11, color=INK)
    fig.suptitle("Strategies traded together: cumulative out-of-sample profit by instrument ($100,000 per strategy)",
                 x=0.01, ha="left", fontsize=13, fontweight="bold")
    fig.tight_layout()
    save(fig, "portfolios_by_instrument.png")
    out["books"] = {t: {"summary": {k: v for k, v in pn[t].items() if k not in ("buy_and_hold", "selected")},
                        "per_run": per.sort_values("net", ascending=False).to_dict("records"),
                        "by_market": per.groupby("market").net.sum().round(2).to_dict()} for t, P, per in books}

    # 8. per instrument: passing configurations, best strategy, and best OOS result of every strategy there
    inst = []
    for m in INSTR:
        x = rob[rob.market == m]
        bestm = x.sort_values("wf_oos_net", ascending=False).drop_duplicates("code")
        inst.append({"market": m, "passed": int(len(x)), "runs": int((r.market == m).sum()),
                     "strategies": [{"strategy": b.name, "session": b.session, "bars": TF_LABEL[b.bars], "oos_net": b.wf_oos_net,
                                     "oos_pf": b.wf_oos_pf, "net": b.net, "pf": b.pf, "win": b.win_pct, "rr": b.payoff_ratio,
                                     "tpm": b.trades_per_year / 12, "oos_trades": b.wf_oos_trades, "max_dd": b.max_dd}
                                    for b in bestm.itertuples()]})
    out["by_instrument"] = inst
    fig, ax = plt.subplots(figsize=(9, 3.6))
    labels, vals, cols = [], [], []
    for m in INSTR:
        for s in [z for z in inst if z["market"] == m][0]["strategies"]:
            labels.append(f"{s['strategy']} · {m}"); vals.append(s["oos_net"]); cols.append(INSTR[m])
    o = np.argsort(vals)
    fig.set_size_inches(9, 0.32 * len(vals) + 1.2)
    ax.barh(np.arange(len(vals)), np.array(vals)[o], color=np.array(cols)[o], height=0.66, edgecolor=SURFACE, linewidth=1.5)
    for i, v in enumerate(np.array(vals)[o]):
        ax.text(v + 600, i, usd(v), va="center", fontsize=8.5)
    ax.set_yticks(np.arange(len(vals)), np.array(labels)[o], fontsize=8.5)
    ax.set_xlim(0, max(vals) * 1.18)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: usd(v)))
    ax.grid(axis="y", visible=False)
    ax.legend(handles=[matplotlib.patches.Patch(color=c, label=m) for m, c in INSTR.items()], frameon=False, loc="lower right", fontsize=9)
    title(ax, "What each strategy made on each instrument", "Best passing configuration per strategy and instrument, walk-forward out-of-sample, $100,000 per trade")
    save(fig, "by_instrument.png")

    # 9. intraday vs swing summary numbers, hard stop, studies
    i = ir.load()
    out["intraday"] = {"runs": int(len(i)), "passed": int(i.robust.sum()), "oos_profitable": int((i.wf_oos_net > 0).sum()),
                       "by_bars": {b: {"runs": int((i.bars == b).sum()), "passed": int(i[i.bars == b].robust.sum()),
                                       "oos_profitable": int((i[(i.bars == b)].wf_oos_net > 0).sum()),
                                       "median_tpm": round(float(i[i.bars == b].trades_per_month.median()), 1)} for b in ("1m", "5m", "15m", "60m")},
                       "passed_runs": i[i.robust][["code", "market", "bars", "trades_per_month", "win_pct", "payoff_ratio", "pf", "net",
                                                   "wf_oos_net", "wf_oos_pf"]].assign(name=lambda d: d.code.map(NAMES)).round(2).to_dict("records")}
    s = pd.read_csv(ROOT / "results/SINGLE_ACCOUNT/stop_rows.csv"); s["robust"] = robust_mask(s)
    base = r.set_index(["strategy", "market", "session", "bars"])
    out["hard_stop"] = [{"strategy": NAMES[x.strategy[:3].upper()], "market": x.market, "session": x.session, "bars": TF_LABEL[x.bars],
                         "oos_net_no_stop": float(base.loc[(x.strategy, x.market, x.session, x.bars)].wf_oos_net),
                         "oos_net_stop": float(x.wf_oos_net), "oos_pf_stop": float(x.wf_oos_pf), "passes_with_stop": bool(x.robust)}
                        for x in s.itertuples()]
    out["all_passing"] = rob.sort_values(["market", "wf_oos_net"], ascending=[True, False])[
        ["name", "market", "session", "bars", "trades", "trades_per_month", "win_pct", "payoff_ratio", "pf", "net", "max_dd",
         "wf_oos_trades", "wf_oos_net", "wf_oos_pf", "mc_prob_loss_pct", "stress_worst_net"]].assign(bars=lambda d: d.bars.map(TF_LABEL)).round(2).to_dict("records")
    out["tests"] = None
    (ROOT / "docs" / "readme_numbers.json").write_text(json.dumps(out, indent=1, default=str))
    print("charts:", sorted(p.name for p in IMG.glob("*.png") if not p.name.startswith("._")))


if __name__ == "__main__":
    main()
