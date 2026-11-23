"""SINGLE_ACCOUNT_10K.md: the two books on one account, risking a % of the balance per trade, sized two ways side by
side (results/SINGLE_ACCOUNT/atr.json and stops.json from tools/single_account_study.py; stop re-runs' checks from
results/SINGLE_ACCOUNT/stop_rows.csv).
    python tools/write_single_account_report.py
"""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from photo_report_tables import robust_mask  # noqa: E402
from timeframe_report import TF_LABEL  # noqa: E402

OUT = ROOT / "results" / "SINGLE_ACCOUNT"


def money(v):
    return "—" if v is None or v != v else (f"−${abs(v):,.0f}" if v < 0 else f"${v:,.0f}")


def num(v, f="{:.1f}"):
    return "—" if v is None or v != v else f.format(v)


ROWS = [("Period", lambda b: f"{b['start']} → {b['end']} ({b['months']} months)"),
        ("Trades the strategies gave", lambda b: f"{b['trades_offered']}"),
        ("Trades taken", lambda b: f"{b['trades_taken']}"),
        ("Trades skipped (minimum size risks > 2%)", lambda b: f"{sum(b['skipped'].values())}"),
        ("Trades per month (taken)", lambda b: num(b["trades_per_month"])),
        ("Final balance", lambda b: money(b["final_equity"])),
        ("Net profit", lambda b: money(b["net"])),
        ("Return", lambda b: f"{b['return_pct']:,.0f}%"),
        ("Per year (compounded)", lambda b: f"{b['cagr_pct']:,.0f}%" if b["cagr_pct"] is not None else "—"),
        ("Max drawdown (daily closes)", lambda b: f"{money(b['max_dd_usd'])} ({b['max_dd_pct']}%)"),
        ("Win rate", lambda b: f"{num(b['win_pct'])}%"),
        ("Profit factor", lambda b: num(b["profit_factor"], "{:.2f}")),
        ("Average win / average loss (in R)", lambda b: f"+{num(b['avg_win_r'], '{:.2f}')}R / {num(b['avg_loss_r'], '{:.2f}')}R"),
        ("Worst trade", lambda b: f"{num(b['worst_trade_r'], '{:.2f}')}R"),
        ("Losses bigger than the 2% risk", lambda b: f"{b['losses_bigger_than_risk']}"),
        ("Profitable months", lambda b: b["profitable_months"]),
        ("Worst month", lambda b: b["worst_month"]),
        ("Most positions open at once (day closes)", lambda b: f"{b['max_open_positions']}"),
        ("Leverage (contract value ÷ equity): max / median", lambda b: f"{b['max_leverage']}× / {b['median_leverage']}×"),
        ("Account hit $0", lambda b: b["account_hit_zero_on"] or "no")]


def main():
    atr = json.loads((OUT / "atr.json").read_text())
    stp = json.loads((OUT / "stops.json").read_text())
    sr = pd.read_csv(OUT / "stop_rows.csv")
    sr = sr[sr.error.isna()].copy()
    sr["robust"] = robust_mask(sr)
    L = [f"# The book on one $10,000 account, 2% risk per trade, compounding",
         "",
         f"*Generated {date.today():%B %d, %Y} by `tools/write_single_account_report.py`. Data: the walk-forward "
         "out-of-sample trades of the runs selected in TIMEFRAME_STUDY_RESULTS.md section 7.*",
         "",
         "## How it was run",
         "",
         "* **One account, $10,000.** All the strategies in a book share it and can hold positions at the same time.",
         "* **Risk 2% of the balance on every trade, compounding:** the balance is $10,000 plus every trade closed "
         "before this one is entered. Quantity = 2% of the balance ÷ (stop distance × point value), rounded **down** "
         "to whole MNQ/MGC micro contracts or 0.01 lots of XAUUSD/NAS100. If even one contract would risk more than "
         "2%, the trade is **skipped**.",
         "* **Two ways to define the stop distance** (13 of the 15 strategies have no stop of their own):",
         "  * **A. ATR-sized, no hard stop:** the saved trades exactly as they were, sized as if the stop were "
         "2 × ATR(14) of the decision bar. The exits are the strategies' own, so a loss can be bigger than 2%.",
         "  * **B. Real 2 × ATR stop:** every strategy re-run through the whole pipeline (grid, walk-forward, Monte Carlo, "
         "stress, checklist) with a hard stop 2 × ATR(14) from the fill. The walk-forward re-optimised the settings "
         "with the stop in place; those new out-of-sample trades are then sized the same way.",
         "  * A12 already has its own stop and is the same in both.",
         "* Costs (commission, slippage, spread, rolls) are per contract, so they scale with the new size. **Margin is not "
         "modelled**: the leverage row shows how much contract value was open per dollar of equity.",
         ""]
    def share(book, mk):
        pr = pd.DataFrame(book["per_run"])
        return pr[pr.run.str.contains(f" {mk} ")].net.sum() / max(pr.net.sum(), 1e-9) * 100
    t1 = list(atr)[0]
    L += ["## Read this first", "",
          f"* **The profit comes mostly from spot gold.** In the MNQ + gold book, XAUUSD strategies made "
          f"{share(atr[t1], 'XAUUSD'):.0f}% (A) / {share(stp[t1], 'XAUUSD'):.0f}% (B) of the net profit, in a period when "
          "gold rose strongly. The out-of-sample window is only about 19 months.",
          "* **At $10,000, MNQ and MGC are often too big:** one micro contract with a 2 × ATR stop usually risks more than "
          "$200. On their own $10,000 account the MNQ strategies took almost no trades (table below); inside the book they "
          "start trading only after gold profits have grown the balance.",
          "* **Leverage:** with 2% risk on several positions at once, open contract value reached about 10–12 × equity. "
          "Check your broker's margin before relying on this.",
          "* **Selection bias:** these strategies were picked because they passed checks that include these same "
          "out-of-sample results, and compounding magnifies that optimism. Treat the returns as an upper bound and "
          "forward-test first.", ""]
    for title in atr:
        a, s = atr[title]["book"], stp[title]["book"]
        L += [f"## {title}", "", "| | A. ATR-sized, no hard stop | B. Real 2×ATR stop |", "|---|---|---|"]
        L += [f"| {name} | {f(a)} | {f(s)} |" for name, f in ROWS]
        pa = pd.DataFrame(atr[title]["per_run"]).set_index("run")
        ps_ = pd.DataFrame(stp[title]["per_run"]).set_index("run")
        t = pd.DataFrame({"trades given": pa.offered.astype(int), "A taken": pa.trades.astype(int), "A net $": pa.net.round(0),
                          "A win %": pa.win_pct.round(1), "B given": ps_.offered.reindex(pa.index).fillna(0).astype(int),
                          "B taken": ps_.trades.reindex(pa.index).fillna(0).astype(int),
                          "B net $": ps_.net.reindex(pa.index).round(0), "B win %": ps_.win_pct.reindex(pa.index).round(1)})
        L += ["", "Per strategy inside the book:", "", t.reset_index().to_markdown(index=False), ""]
        al = pd.DataFrame(atr[title]["alone"]).set_index("run")[["trades taken", "of offered", "net $", "return %", "max DD %"]]
        bl = pd.DataFrame(stp[title]["alone"]).set_index("run")[["trades taken", "of offered", "net $", "return %", "max DD %"]]
        both = al.add_prefix("A ").join(bl.add_prefix("B "))
        L += ["Each strategy **alone** on its own $10,000 (its whole out-of-sample period):", "",
              both.reset_index().to_markdown(index=False), ""]
    keep = ["strategy", "market", "session", "bars", "trades", "win_pct", "payoff_ratio", "pf", "net", "wf_oos_trades", "wf_oos_net",
            "wf_oos_pf", "mc_prob_loss_pct", "stress_worst_net", "checks_passed", "checks_total", "robust"]
    x = sr[keep].copy()
    x["bars"] = x.bars.map(TF_LABEL)
    L += ["## Do the strategies still pass every check with a real 2×ATR stop?", "",
          f"{int(sr.robust.sum())} of {len(sr)} re-runs pass every key check (same rule as the timeframe study; all "
          f"{len(sr)} passed without the stop). Full-history and out-of-sample figures at $100,000 of contract value:", "",
          x.round(2).to_markdown(index=False), ""]
    (ROOT / "SINGLE_ACCOUNT_10K.md").write_text("\n".join(L))
    print("SINGLE_ACCOUNT_10K.md written")


if __name__ == "__main__":
    main()
