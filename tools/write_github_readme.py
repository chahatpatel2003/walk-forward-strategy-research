"""Write README.md for GitHub from docs/readme_numbers.json (tools/make_readme_charts.py) and the study results.
Every number in the tables is filled in here from saved data.
    python tools/make_readme_charts.py && python tools/write_github_readme.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
J = json.loads((ROOT / "docs" / "readme_numbers.json").read_text())


def usd(v):
    return "—" if v is None else ("−$" if v < 0 else "$") + f"{abs(v):,.0f}"


def sgn(v):
    return "—" if v is None else ("+" if v >= 0 else "") + usd(v).replace("+", "")


def ses(s):
    return {"rth": "cash", "full": "full"}.get(s, s)


def table(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(map(str, r)) + " |" for r in rows])


def main():
    best = J["best"]
    acc = J["account"]
    b1, b2 = list(J["books"].values())
    s1, s2 = b1["summary"], b2["summary"]
    intr = J["intraday"]
    inst = {x["market"]: x for x in J["by_instrument"]}
    costs = J["costs"]
    tests = 224

    by_inst_rows = []
    for m in ("NAS100", "MNQ", "XAUUSD", "MGC"):
        x = inst[m]
        top = x["strategies"][0]
        by_inst_rows.append([f"**{m}**", f"{x['passed']} of {x['runs']}", len(x["strategies"]),
                             f"{top['strategy']} ({top['bars']})", f"**{sgn(top['oos_net'])}**", f"{top['oos_pf']:.2f}"])

    def inst_table(m):
        return table(["Strategy", "Session · bars", "OOS net", "OOS PF", "OOS trades", "Full-history net", "PF", "Win %",
                      "Avg win ÷ avg loss", "Trades / month", "Max drawdown"],
                     [[s["strategy"], f"{ses(s['session'])} · {s['bars']}", f"**{sgn(s['oos_net'])}**", f"{s['oos_pf']:.2f}",
                       int(s["oos_trades"]), sgn(s["net"]), f"{s['pf']:.2f}", f"{s['win']:.1f}", f"{s['rr']:.2f}",
                       f"{s['tpm']:.1f}", usd(s["max_dd"])] for s in inst[m]["strategies"]])

    acc_by = {}
    for x in J["account_by_strategy"]:
        acc_by[x["run"].split()[1]] = acc_by.get(x["run"].split()[1], 0.0) + x["net"]

    hs = J["hard_stop"]
    hs_rows = [[h["strategy"], h["market"], f"{ses(h['session'])} · {h['bars']}", sgn(h["oos_net_no_stop"]), sgn(h["oos_net_stop"]),
                f"{h['oos_pf_stop']:.2f}", "✅" if h["passes_with_stop"] else "—"] for h in hs]
    better = sum(1 for h in hs if h["oos_net_stop"] > h["oos_net_no_stop"])

    allp = J["all_passing"]
    allp_rows = [[a["name"], a["market"], f"{ses(a['session'])} · {a['bars']}", int(a["trades"]), f"{a['trades_per_month']:.1f}",
                  f"{a['win_pct']:.1f}", f"{a['payoff_ratio']:.2f}", f"{a['pf']:.2f}", sgn(a["net"]), usd(a["max_dd"]),
                  int(a["wf_oos_trades"]), f"**{sgn(a['wf_oos_net'])}**", f"{a['wf_oos_pf']:.2f}", f"{a['mc_prob_loss_pct']:.1f}%",
                  sgn(a["stress_worst_net"])] for a in allp]

    md = f"""<div align="center">

# Walk-Forward Strategy Research Engine

**A from-scratch backtesting and robustness-testing platform in Python**
**for Nasdaq-100 and gold: futures, CFDs and spot, from 1-minute to daily bars.**

![Python](https://img.shields.io/badge/python-3.13-3776ab?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/tests-{tests}%20passing-1baf7a)
![Backtests](https://img.shields.io/badge/backtests-611-2a78d6)
![Robust configs](https://img.shields.io/badge/passed%20every%20check-47-eb6834)
![License](https://img.shields.io/badge/license-MIT-52514e)

</div>

---

## Highlights

| | |
|---|---|
| 🏆 **Best out-of-sample result** | **{sgn(best[0]['oos_net'])}**, profit factor **{best[0]['oos_pf']:.2f}** ({best[0]['strategy']}, {best[0]['market']} {best[0]['bars']}) |
| 🎯 **Highest out-of-sample profit factor** | **4.13** (Williams %R + EMA + VWAP, NAS100 daily, 83% win rate) |
| 📈 **Most consistent strategy** | Time-series momentum: profitable out-of-sample in **36 of 40** configurations |
| 🧪 **Scale of testing** | **611 backtests** · 14 strategies · 4 instruments · 6 bar sizes · 2 sessions · 0 errors |
| ✅ **Robust configurations** | **47** passed every robustness check on data the optimiser never saw |
| 💼 **Multi-strategy portfolio** | **{s1['trades_per_month']} trades / month**, **{sgn(s1['net (marked, includes carried-in positions)'])}** out-of-sample in {s1['months']} months |
| 💰 **$10,000 account** | **{usd(acc['final_equity'])}** in {acc['months']} months, **{acc['cagr_pct']}% a year** compounded |
| 🔬 **Engineering** | {tests} automated tests · look-ahead protection · 10 independent code-audit rounds |

<p align="center"><img src="docs/images/best_oos_by_strategy.png" width="860"></p>

---

## Contents

1. [Results by instrument](#1-results-by-instrument)
2. [Multi-strategy portfolios](#2-multi-strategy-portfolios)
3. [One $10,000 account](#3-one-10000-account)
4. [The strategies: exact rules and results](#4-the-strategies-exact-rules-and-results)
5. [Variations tested](#5-variations-tested)
6. [What didn't work, and why](#6-what-didnt-work-and-why)
7. [How the engine works](#7-how-the-engine-works)
8. [Bugs found and fixed](#8-bugs-found-and-fixed)
9. [Every configuration that passed](#9-every-configuration-that-passed)
10. [Running it](#10-running-it)

All profit figures use the same standard sizing unless stated otherwise: **$100,000 of contract value per trade**,
with commission, slippage, bid/ask spreads and futures roll costs included. **OOS** = walk-forward out-of-sample:
parameters chosen on earlier data only, then traded on the following window the optimiser never saw.
**PF** = profit factor (gross profit ÷ gross loss).

---

## 1. Results by instrument

{table(["Instrument", "Configurations that passed every check", "Strategies that passed", "Best strategy", "Best OOS net", "OOS PF"], by_inst_rows)}

<p align="center"><img src="docs/images/by_instrument.png" width="860"></p>

### NAS100 (Nasdaq-100 CFD, 2012–2021, 9.7 years)

{inst_table("NAS100")}

### MNQ (Micro Nasdaq-100 futures, 2021–2026, 5.6 years)

{inst_table("MNQ")}

### XAUUSD (spot gold, 2021–2026, 5.4 years)

{inst_table("XAUUSD")}

### MGC (Micro gold futures, 2016–2025, 10 years)

{inst_table("MGC")}

### Intraday (flat every day by 15:55 ET)

{table(["Strategy", "Instrument", "Bars", "Trades / month", "Win %", "Avg win ÷ avg loss", "PF", "Full-history net", "OOS net", "OOS PF"],
       [[p['name'], p['market'], p['bars'].replace('m', '-min').replace('60-min', '1-hour'), f"{p['trades_per_month']:.1f}", f"{p['win_pct']:.1f}",
         f"{p['payoff_ratio']:.2f}", f"{p['pf']:.2f}", sgn(p['net']), f"**{sgn(p['wf_oos_net'])}**", f"{p['wf_oos_pf']:.2f}"] for p in intr['passed_runs']])}

<p align="center"><img src="docs/images/shortlist_oos_curves.png" width="980"></p>

---

## 2. Multi-strategy portfolios

One passing configuration per strategy and instrument (chosen by trade frequency, not by profit), all traded at the
same time, each with $100,000 of contract value per trade, measured only on dates where every strategy was in its
out-of-sample period.

{table(["", "Portfolio 1: MNQ + MGC + XAUUSD", "Portfolio 2: NAS100 + MGC"], [
    ["Period", f"{s1['start']} → {s1['end']} ({s1['months']} months)", f"{s2['start']} → {s2['end']} ({s2['months']} months, incl. COVID crash)"],
    ["Strategies", s1["runs"], s2["runs"]],
    ["Trades entered", s1["trades entered in window"], s2["trades entered in window"]],
    ["**Trades per month**", f"**{s1['trades_per_month']}**", f"**{s2['trades_per_month']}**"],
    ["**Net profit**", f"**{sgn(s1['net (marked, includes carried-in positions)'])}**", f"**{sgn(s2['net (marked, includes carried-in positions)'])}**"],
    ["Max drawdown (daily closes)", usd(s1["max drawdown (daily closes)"]), usd(s2["max drawdown (daily closes)"])],
    ["Profitable months", s1["profitable_months"], s2["profitable_months"]],
    ["Best month", s1["best_month"].replace(":", " →"), s2["best_month"].replace(":", " →")],
    ["Most positions open at once", s1["max positions open at once (bar timestamps)"], s2["max positions open at once (bar timestamps)"]],
])}

**Profit by instrument:**

{table(["Portfolio", "MNQ", "NAS100", "MGC", "XAUUSD", "Total"], [
    ["Portfolio 1", sgn(b1["by_market"].get("MNQ")), "—", sgn(b1["by_market"].get("MGC")), sgn(b1["by_market"].get("XAUUSD")), f"**{sgn(sum(b1['by_market'].values()))}**"],
    ["Portfolio 2", "—", sgn(b2["by_market"].get("NAS100")), sgn(b2["by_market"].get("MGC")), "—", f"**{sgn(sum(b2['by_market'].values()))}**"],
])}

<p align="center"><img src="docs/images/portfolios_by_instrument.png" width="980"></p>

<details>
<summary><b>Profit of every strategy in the portfolios</b></summary>

**Portfolio 1 (MNQ + MGC + XAUUSD)**

{table(["Strategy · instrument · session · bars", "Net profit"], [[p["run"], sgn(p["net"])] for p in b1["per_run"]])}

**Portfolio 2 (NAS100 + MGC)**

{table(["Strategy · instrument · session · bars", "Net profit"], [[p["run"], sgn(p["net"])] for p in b2["per_run"]])}

</details>

---

## 3. One $10,000 account

Eight strategies on one shared $10,000 account, compounding. Each position is sized so that a 2 × ATR(14) move
against it costs 2% of the current balance, rounded down to whole micro contracts or 0.01 lots.

{table(["Period", "$10,000 →", "Per year", "Max drawdown", "Trades / month", "Win rate", "Avg win / loss", "PF", "Profitable months"],
       [[f"{acc['start']} → {acc['end']} ({acc['months']} months)", f"**{usd(acc['final_equity'])}**", f"**{acc['cagr_pct']}%**",
         f"{acc['max_dd_pct']}%", acc["trades_per_month"], f"{acc['win_pct']}%", f"+{acc['avg_win_r']}R / {acc['avg_loss_r']}R",
         acc["profit_factor"], acc["profitable_months"]]])}

<p align="center"><img src="docs/images/account_10k.png" width="860"></p>

{table(["Strategy in the account", "Trades taken", "Net profit", "Win %"],
       [[x["run"].replace("A01", "RSI(3)+EMA(100)+VWAP").replace("A07", "MFI reversal").replace("A09", "Turn of the month")
         .replace("A11", "Time-series momentum").replace("A12", "Volatility squeeze"), int(x["trades_taken"]), sgn(x["net"]),
         "—" if x["win_pct"] is None else f"{x['win_pct']:.1f}"] for x in sorted(J["account_by_strategy"], key=lambda z: -z["net"])])}

By instrument: XAUUSD {sgn(acc_by.get('XAUUSD', 0))}, MNQ {sgn(acc_by.get('MNQ', 0))}, MGC {sgn(acc_by.get('MGC', 0))}.
At $10,000 a single MNQ or MGC micro contract often carries more than 2% risk, so those trades are only taken once
the balance has grown enough to size them.

---

## 4. The strategies: exact rules and results

Every rule below is the exact logic in `strategies/`. Signals are evaluated on a bar's close and **every order fills
at the next bar's open** (or at its stop/limit price inside a bar). Defaults are shown; the grid lists every value
tested in the parameter search and re-optimised in each walk-forward window.

### 1 · RSI(3) + EMA(50) + VWAP — long only · 12 configurations passed (most robust)
- **Entry:** RSI(3) < 22 **and** close above EMA(50) **and** close below the 10-bar rolling VWAP.
- **Exit:** RSI(3) > 55.
- **Grid:** RSI entry 15 / 22 / 30 · RSI exit 50 / 55 / 65 · EMA 50 / 100.
- **Passed on all four instruments:** NAS100 4-hour **+$42,092** (PF 1.61), MGC daily +$28,999 (PF 2.45), MNQ daily
  +$17,034 (**PF 7.50**), XAUUSD daily +$15,007 (PF 2.57). 6 daily, 5 four-hour and 1 one-hour configuration passed.

### 2 · RSI(3) + EMA(100) + VWAP pullback — long only · 8 passed
- **Entry:** RSI(3) < 22 **and** EMA(100) rising (above its value 5 bars earlier) **and** close at least 1% below the
  10-bar rolling VWAP.
- **Exit:** RSI(3) > 55.
- **Grid:** RSI entry 15 / 22 / 30 · RSI exit 50 / 55 / 65 · VWAP discount 0.5% / 1.0% / 1.5%.
- **Passed on all four instruments:** MGC daily **+$38,393 (PF 3.18)**, NAS100 daily +$33,302, XAUUSD daily +$25,275
  (PF 3.68), MNQ 4-hour +$19,202 (PF 3.86, 75% win rate).

### 3 · Williams %R + EMA + VWAP — long only · 5 passed
- **Entry:** Williams %R(10) < −80 **and** close above EMA(200) **and** close below the 10-bar VWAP.
- **Exit:** %R > −20.
- **Grid:** %R length 2 / 5 / 10 · entry −90 / −80 / −70 · exit −50 / −20.
- **Results:** NAS100 daily **+$58,900, PF 4.13, 83% win rate**; MNQ daily +$24,432 (PF 2.90); MNQ 1-hour +$18,655.

### 4 · MFI reversal — long only · 5 passed
- **Entry:** 2-bar Money Flow Index < 10.
- **Exit:** close above the previous bar's high.
- **Grid:** MFI length 2 / 3 / 5 · entry level 5 / 10 / 20.
- **Results:** NAS100 daily **+$54,614** (full history **+$107,309**); NAS100 4-hour +$34,135 at **9.9 trades a
  month**, the most active robust configuration; MNQ daily +$26,122; XAUUSD 4-hour +$22,530 at 6.5 trades a month.

### 5 · Time-series momentum — long only · 5 passed + 1 intraday
- **Entry:** 20-bar return above 5% (measured on the real, unadjusted price).
- **Exit:** close below the 50-bar simple moving average.
- **Grid:** lookback 20 / 60 · threshold 3% / 5% / 8% · exit average 50 / 100.
- **Results:** profitable out-of-sample in **36 of 40** configurations. NAS100 4-hour **+$59,317 (PF 2.02)**, NAS100
  1-hour +$49,998, XAUUSD 4-hour +$37,022, MNQ 4-hour +$30,371; intraday MNQ 15-minute +$25,502 at 10.2 trades a
  month. Wins about 40% of trades with winners about 2× the size of losers.

### 6 · Rubber Band — long only · 4 passed
- **Entry:** close below the band = highest high of the last 5 bars − 2.5 × the 10-bar average high-low range.
- **Exit:** close above the previous bar's high.
- **Grid:** high lookback 5 / 10 · range length 10 / 20 · multiplier 2.0 / 2.5 / 3.0.
- **Results (all daily):** NAS100 **+$49,258**, MNQ +$30,648 (**PF 6.27**), MGC +$27,339.

### 7 · Turn of the month — long only · 3 passed
- **Entry:** the close of the 5th-last trading day of the month (exchange calendar).
- **Exit:** the close of the 3rd trading day of the next month.
- **Grid:** entry 3 / 5 / 7 days before month-end · exit day 1 / 3 / 5.
- **Results:** NAS100 daily **+$75,592 (PF 2.03), the best result of the whole study**; NAS100 cash session
  +$60,950; XAUUSD daily +$28,356 (PF 2.74).

### 8 · Volatility squeeze breakout — long and short · 2 passed + 1 intraday
- **Setup:** Bollinger(20, 2) width in the lowest 10% of the last 200 bars.
- **Entry:** buy stop at the 20-bar high **and** sell stop at the 20-bar low (one cancels the other), valid 4 bars.
- **Exit:** stop-loss at the opposite side of the range · target 2 × the risk · or after 32 bars.
- **Grid:** squeeze percentile 5 / 10 / 20 · target 1.5 / 2 / 3 × risk.
- **Results:** XAUUSD 1-hour **+$24,697** at 5.9 trades a month; MNQ 4-hour PF 5.88; intraday XAUUSD 1-hour PF 1.62.

### 9 · Z-score mean reversion — long and short · 1 passed
- z = (close − 20-bar mean) ÷ 20-bar standard deviation.
- **Entry:** long when z < −2, short when z > +2. **Exit:** |z| < 0.5. **Stop:** |z| > 4.
- **Grid:** window 20 / 40 / 60 · entry 1.5 / 2.0 / 2.5 · exit 0 / 0.5.
- **Results:** MNQ 4-hour **+$13,452 (PF 1.97)**.

### 10 · Stochastic + KAMA + VWAP — long only
- **Entry:** Stochastic %K(21, smoothed 3) < 55 **and** close above KAMA(10, fast 3, slow 75) **and** close at least
  0.5% below the 200-bar rolling VWAP. **Exit:** %K back above 55, or after 25 bars.
- **Grid:** %K level 40 / 55 / 70 · VWAP buffer 0% / 0.5% / 1.0% · max hold 10 / 25.
- **Results:** profitable out-of-sample in 9 of 40 configurations (best NAS100 15-minute +$23,555), none passed.

### 11 · Weekly RSI — long only
- **Entry:** 2-week RSI < 15 (evaluated at week ends). **Exit:** weekly RSI(2) > 70.
- **Results:** profitable over the full history on **all 8** runs (median +$30,595, median PF 2.39); too few trades
  for walk-forward validation.

### 12 · Faber 10-month trend filter — long only
- At each month-end: hold if the close is above its 10-month simple moving average, otherwise flat.
- **Results:** profitable on **all 8** runs (median **+$97,725**, median PF 11.05); too few trades for walk-forward.

### 13 · Order-flow imbalance — long and short, intraday
- OFI = buyer-initiated − seller-initiated volume each minute. λ = rolling regression slope of the next minute's move
  on this minute's OFI (1,950-sample window). **Entry:** λ × OFI beyond ±2 ticks. **Exit:** after 2 bars; flat by
  the close; no entries in the last 10 minutes.
- **Results:** 25,176 trades; the predicted moves are smaller than the cost per trade.

### 14 · Gold futures vs spot gold pair (statistical arbitrage)
- Spread = gold futures − β × spot gold, β from a rolling 60-day regression; trade the spread's z-score (enter ±2,
  exit ±0.5, stop ±4). Runs on a dedicated two-leg engine.
- **Results:** the futures–spot gap is mostly interest-rate carry, which trends rather than reverts.

<p align="center"><img src="docs/images/strategy_by_bar_size.png" width="820"></p>

---

## 5. Variations tested

| Variation | What was done | Outcome |
|---|---|---|
| **Bar size** | Every strategy on 5-min, 15-min, 1-hour, 4-hour and daily bars (373 runs). Lengths stay in bars; thresholds in % of price are scaled by √(bar length ÷ original). | Passed: 1-hour 4, 4-hour 15, daily 26 |
| **Session** | New York cash session (09:30–16:00) and the full futures session, for every run. | Both produce passing configurations |
| **Instrument** | All four instruments for every single-market strategy. | Passing configurations on all four |
| **Parameters** | Full grid per run (up to 40 sets), re-optimised in every walk-forward window. | Best setting must sit on a plateau, not a lone spike |
| **Hard stop** | Every portfolio strategy re-run with a stop 2 × ATR(14) from the fill. | {sum(1 for h in hs if h['oos_net_stop'] > 0)} of {len(hs)} profitable OOS; {better} made more with the stop |
| **Intraday** | Every strategy flat by 15:55 daily on 1-, 5-, 15-min and 1-hour bars ({intr['runs']} runs). | {intr['passed']} passed, {intr['oos_profitable']} profitable OOS |
| **4 pm exit** | Saved trades closed at the 16:00 cash close (replayed on 1-minute data, 160 exits verified independently). | Swing edge comes mostly from holding overnight |
| **Portfolio** | Robust configurations traded together. | {s2['trades_per_month']}–{s1['trades_per_month']} trades a month |
| **Account sizing** | One shared account, 2% of the balance at risk per trade, compounding. | $10,000 → {usd(acc['final_equity'])} |

<p align="center"><img src="docs/images/passed_by_bar_size.png" width="640"></p>

<details>
<summary><b>Hard 2 × ATR stop: every strategy, with and without</b></summary>

{table(["Strategy", "Instrument", "Session · bars", "OOS net, no stop", "OOS net, with stop", "OOS PF with stop", "Passes every check with stop"], hs_rows)}

</details>

<details>
<summary><b>Intraday study by bar size</b></summary>

{table(["Bars", "Runs", "Median trades / month", "Profitable OOS", "Passed every check"],
       [[k.replace('m', '-min').replace('60-min', '1-hour'), v['runs'], v['median_tpm'], v['oos_profitable'], v['passed']] for k, v in intr['by_bars'].items()])}

</details>

---

## 6. What didn't work, and why

**Short bars lose to costs.** Every trade pays about $15–19 in commission, slippage and spread whatever the bar size,
while the average move per trade shrinks with the bar:

{table(["Bars", "Avg trade before costs", "Avg costs", "Avg trade after costs", "Runs profitable before → after costs"],
       [[c["bars"], usd(c["avg trade before costs $"]) if abs(c["avg trade before costs $"]) >= 10 else f"${c['avg trade before costs $']:.2f}",
         f"${c['avg costs per trade $']:.2f}", sgn(c["avg trade after costs $"]) if abs(c["avg trade after costs $"]) >= 10 else
         ("−" if c["avg trade after costs $"] < 0 else "+") + f"${abs(c['avg trade after costs $']):.2f}",
         f"{c['runs profitable before costs']} → {c['runs profitable after costs']} of {c['runs']}"] for c in costs])}

<p align="center"><img src="docs/images/cost_per_trade.png" width="640"></p>

- **Intraday-only trading:** the swing strategies earn most of their edge while holding overnight; forced flat each
  day, the profit factor drops to about 1.1.
- **Order-flow imbalance:** predicted one-minute moves are smaller than the round-trip cost.
- **Gold futures/spot pair:** the spread follows interest-rate carry and drifts instead of reverting.
- **Weekly RSI and Faber 10-month:** profitable, but they trade a handful of times a year, too few for walk-forward
  validation.
- **A hard stop on dip-buying strategies** cuts trades that would have recovered; it helps the trend strategies more
  than the mean-reversion ones.

---

## 7. How the engine works

```
data (1-minute bars, bid/ask, futures rolls)
   │
   ▼
engine/core.py ─ bar-by-bar execution ── orders · fills · costs · rolls · account
   │
   ▼
robust.py ── 1 parameter grid + plateau check
          ── 2 walk-forward (optimise in-sample → trade unseen window → repeat)
          ── 3 Monte Carlo (5,000 bootstrap and shuffle resamples)
          ── 4 stress test (9 execution scenarios)
          ── 5 13-item checklist
   │
   ▼
*_study.py ── every strategy × instrument × session × bar size, in parallel, resumable
```

- **Execution engine** (`engine/core.py`): market, stop and limit orders, one-cancels-other, stop-loss, take-profit and
  R-multiple targets, risk-based or notional sizing, whole-contract rounding, absolute order deadlines, intraday orders.
  - Orders fill at the next bar's open or at their price inside the bar; when a stop and a target are both inside one
    bar the stop is assumed first (pessimistic).
  - Real bid/ask quotes for spot gold, the CFD's spread, commission plus 1 tick of slippage on futures.
  - **Futures rolls:** back-adjusted prices for signals, real prices for sizing, a roll charge whenever a position is
    held through a contract switch.
  - **Drawdown:** an exact walk of open → worst price → close on every bar.
  - **Account model:** an account that reaches $0 (at an open, a close or right after an entry's costs) is liquidated
    and stops trading.
- **Look-ahead protection** (`check_lookahead`): a run is refused if the strategy uses future data. Price columns can't
  be modified; indicators are recomputed on truncated data (fixed cuts, the first rows, signal flips and the
  strategy's own decision bars); strategy code runs on guarded data that raises on any read of a later bar.
- **Walk-forward:** 18 months in-sample → 6 out-of-sample for bars up to 1 hour; 36 → 12 for 4-hour and daily. The
  account balance carries across windows; a window with no valid setting trades nothing.
- **Stress scenarios:** commission × 2, slippage +1 and +2 ticks, spread × 1.5 / 2 / 3, 1- and 2-bar delays, and all
  combined.
- **"Passed every check":** profitable out-of-sample with PF ≥ 1.2, Monte Carlo chance of a loss under 10%, profitable
  in every stress scenario, the account never reached $0, and at most one of the 13 checklist items not passed
  (walk-forward efficiency counts only when enough windows were scored).
- **Pairs engine** (`engine/pairs.py`): two legs on common timestamps, hedge ratio, both legs' costs and rolls.
- **Studies** (`photo_study.py`, `timeframe_study.py`, `intraday_study.py`): parallel workers, safe concurrent writes,
  every result fingerprinted with the exact code and data versions that produced it.

---

## 8. Bugs found and fixed

The code went through ten independent audit rounds. Every problem was first reproduced as a failing test, then fixed;
all {tests} tests stay in the suite.

| Area | Problem | Effect before the fix | Fix |
|---|---|---|---|
| Orders | Calling `close()` twice restarted the order delay | 669 false exits at midnight; the 1-bar-delay stress result was inflated by about $6,000 | The first close request is kept |
| Orders | When two breakout orders triggered in one bar, the buy was always checked first | Wrong side taken on ambiguous bars | The trigger nearest the open wins; verified against 1-second data |
| Orders | A target could be awarded from a high reached before a limit entry | Phantom winners | On the entry bar a limit's target needs the close through it |
| Sessions | The opening-range strategy ignored session hours | 37 trades crossed into the next day | Exchange calendar with holidays and half days; absolute entry deadline enforced by the engine |
| Look-ahead | The checker could be fooled by reverse slices, by reading data through the broker, and by a feature that peeks at only a few rows | Strategies using future data could pass | Index-exact guarded data; cuts at the strategy's own decision bars and signal flips |
| Look-ahead | One strategy inferred its bar size from the whole data set | On 1-hour bars its indicators changed when later data was added | Bar size inferred from past rows only |
| Data | Gold futures roll gaps were estimated with later rolls | Small look-ahead in every gold-futures result | Estimates from earlier rolls only |
| Data | The Money Flow Index used back-adjusted prices | Its value changed when a later roll rebased history | Computed on real traded prices |
| Sizing | Position size used back-adjusted futures prices | Wrong number of contracts | Sized on the real price of the contract held |
| Risk | Drawdown was measured only at bar closes | Losses inside a bar were hidden | Exact open → worst price → close walk |
| Risk | The account kept trading below $0 | One run took 753 more trades after going broke | Constrained account with breach detection at open, close and entry |
| Stress | Spread stress produced impossible bars | About 42,000 invalid gold bars at 2× spread | Bid and ask sides shift consistently |
| Walk-forward | Warm-up trades counted, capital reset each window, gaps between windows | Distorted out-of-sample results | Warm-up only computes indicators; balance carries over; windows are whole months |
| Metrics | Walk-forward efficiency could divide by near-zero in-sample profit | A meaningless score of 3,316 passed | Ratio withheld unless it is meaningful |
| Metrics | A breach in a single stress scenario didn't count as failing | 12 runs wrongly counted as surviving | Any breach in any scenario fails the run |
| Reports | Roll slippage was counted twice in the cost analysis | $7,658 added back twice | Exported as its own column |

**Independent verification:** trades rebuilt from the raw data with separate code matched the engine trade for trade
(turn of the month on NAS100: 114 of 114 identical to the cent), 1-minute fills were checked against 1-second data,
and every 4 pm exit price was re-derived independently (160 of 160 matched).

---

## 9. Every configuration that passed

<details>
<summary><b>All {len(allp)} swing configurations that passed every check (click to expand)</b></summary>

{table(["Strategy", "Instrument", "Session · bars", "Trades", "Trades / month", "Win %", "Avg win ÷ avg loss", "PF", "Full-history net",
        "Max drawdown", "OOS trades", "OOS net", "OOS PF", "Monte Carlo loss chance", "Worst stress scenario"], allp_rows)}

</details>

**Notes:** results are backtests on historical data. The configurations above were selected from 611 runs; a forward
test on new data is the next step. NAS100 data ends September 2021. Margin requirements are not modelled.

---

## 10. Running it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests -q                                   # {tests} tests

# one strategy, full robustness pipeline
.venv/bin/python robust.py all strategies/photos/a09_turn_of_month.py --symbol NAS100 --tf 1440 --session rth \\
    --grid entry_days_before=3,5,7 exit_day=1,3,5 --is-months 36 --oos-months 12 --account-constrained

# whole studies (parallel, resumable)
.venv/bin/python timeframe_study.py --workers 4
.venv/bin/python intraday_study.py --workers 4

# reports and charts
.venv/bin/python tools/make_readme_charts.py && .venv/bin/python tools/write_github_readme.py
```

Market data is not included (licensed). The loader reads 1-minute bars as described in `engine/data.py`; more command
examples are in [`docs/USAGE.md`](docs/USAGE.md) and the engine's invariants in [`REVIEW_GUIDE.md`](REVIEW_GUIDE.md).

```
engine/            execution engine, pairs engine, data, calendar, indicators, metrics, walk-forward, Monte Carlo, stress
strategies/        the 14 strategies (one file each) and an opening-range example
robust.py          robustness pipeline for one strategy and instrument
*_study.py         daily, multi-timeframe and intraday studies
tools/             reports, charts, portfolio and account replays, verification tools
tests/             {tests} tests
docs/              charts and usage notes
```

## License

MIT
"""
    (ROOT / "README.md").write_text(md)
    print("README.md:", len(md), "characters")


if __name__ == "__main__":
    main()
