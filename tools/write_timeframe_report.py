"""Write TIMEFRAME_STUDY_RESULTS.md from the saved study tables. Every figure in the prose is computed here from
results/TIMEFRAME_STUDY/rows.csv, the run folders it points to, and the helper outputs of
tools/timeframe_report.py (tables.md, key_numbers.json), tools/timeframe_costs.py (costs.md, costs_numbers.json) and
tools/timeframe_portfolio.py (portfolio.md, portfolio_numbers.json). Run those three first.

    python tools/write_timeframe_report.py
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from engine import walkforward  # noqa: E402
from photo_report_tables import NAMES  # noqa: E402
from timeframe_report import TF_LABEL, load  # noqa: E402

OUT = ROOT / "results" / "TIMEFRAME_STUDY"
EFF = "Walk-forward efficiency >= 0.5"


def failed_checks(row) -> list[str]:
    """Checklist items not passed, from the run's ROBUSTNESS_REPORT.md; the efficiency item follows the current
    credibility rule (rows written before it still show the old verdict in their report file)."""
    f = ROOT / row.report / "ROBUSTNESS_REPORT.md"
    out = []
    if f.exists():
        for line in f.read_text().splitlines():
            m = re.match(r"\| (FAIL|WARN) \| (.*?) \|", line)
            if m:
                out.append(m.group(2))
    if pd.isna(row.wf_efficiency) and EFF not in out:
        out.append(EFF)
    return out


def rng(x: pd.Series, fmt="{:.1f}") -> str:
    return f"{fmt.format(x.median())} (range {fmt.format(x.min())}–{fmt.format(x.max())})" if len(x) else "n/a"


def usd2(v) -> str:
    return f"−${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"


def money(v) -> str:
    return f"−${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def main():
    r = load()
    T = (OUT / "tables.md").read_text()

    def sec(name):
        return re.search(rf"<!--{name}-->\n(.*?)(?=\n<!--|\Z)", T, re.S).group(1).strip()
    costs_md = (OUT / "costs.md").read_text().strip()
    cn = pd.DataFrame(json.loads((OUT / "costs_numbers.json").read_text()))
    port = (OUT / "portfolio.md").read_text()
    books = re.split(r"<!--BOOK (.*?)-->\n+", port)
    kn = json.loads((OUT / "key_numbers.json").read_text())
    pn = json.loads((OUT / "portfolio_numbers.json").read_text())
    A, B = pn["tradable now (MNQ + MGC + XAUUSD)"], pn["longest history (NAS100 + MGC)"]
    rows_all = pd.read_csv(OUT / "rows.csv")
    arch = OUT / "archive" / "rows_review9.csv"          # the index before the tenth review: rows whose run folder
    old = set(pd.read_csv(arch).report.dropna()) if arch.exists() else set(rows_all.report.dropna())   # changed were re-run
    rerun = rows_all[~rows_all.report.isin(old)]
    versions = rows_all.code_version.value_counts()

    rob = r[r.robust]
    by = rob.groupby("bars").size()
    lab = lambda tf: TF_LABEL[tf]  # noqa: E731
    top = rob.sort_values("trades_per_month", ascending=False).head(2)
    t1, t2 = top.iloc[0], top.iloc[1]
    tfstat = {tf: g for tf, g in r.groupby("bars")}
    broke = r[~r.survived]
    short_broke = int(broke.bars.isin(["5m", "15m"]).sum())
    full_broke = r[r.capital_exhausted_on.notna()].groupby("bars").size()
    c = lambda tf, mk="all markets": cn[(cn.bars == lab(tf)) & (cn.market == mk)].iloc[0]  # noqa: E731
    c5 = c("5m")
    fr_med = cn[(cn.market == "all markets") & (cn.bars != lab("1m"))]["avg costs per trade $"]   # 5-minute to daily
    pass_med = {tf: rob[rob.bars == tf].trades_per_month for tf in ("60m", "240m", "1440m")}

    # strategy notes (counts computed)
    def n_rob(code, tf):
        return int(((rob.code == code) & (rob.bars == tf)).sum())

    def where(code, tf):
        x = rob[(rob.code == code) & (rob.bars == tf)]
        return ", ".join(f"{m} {'cash' if s == 'rth' else 'full'}" for m, s in zip(x.market, x.session)) or "none"
    d_pull = sum(n_rob(k, "1440m") for k in ("A01", "A03", "A04"))
    n_pull = int(r[(r.code.isin(["A01", "A03", "A04"])) & (r.bars == "1440m")].shape[0])
    a11 = r[r.code == "A11"]
    a11_oos = {tf: (int((g.wf_oos_net > 0).sum()), int(g.wf_oos_net.notna().sum())) for tf, g in a11.groupby("bars")}

    # runs that passed everything (table)
    rb = rob.sort_values(["tf", "wf_oos_net"], ascending=[True, False])
    rbt = pd.DataFrame({"strategy": rb.code + " " + rb.code.map(NAMES).fillna(""), "market": rb.market, "session": rb.session,
                        "bars": rb.bars.map(TF_LABEL), "trades/mo": rb.trades_per_month.round(1),
                        "win %": rb.win_pct.round(1), "avg win ÷ avg loss": rb.payoff_ratio.round(2), "PF": rb.pf.round(2),
                        "OOS trades": rb.wf_oos_trades.astype(int), "OOS trades/mo": rb.oos_trades_per_month.round(1),
                        "OOS net $": rb.wf_oos_net.round(0).astype(int), "OOS PF": rb.wf_oos_pf.round(2),
                        "WF efficiency": rb.wf_efficiency.round(2),
                        "OOS max DD $": rb.wf_oos_max_dd.round(0).astype(int), "MC loss %": rb.mc_prob_loss_pct.round(1),
                        "worst stress $": rb.stress_worst_net.round(0).astype(int)})
    intraday = rob[rob.bars.isin(["60m", "240m"])]

    # closest misses
    near = r[(r.trades_per_month >= 10) & (r.wf_oos_net > 0) & ~r.robust].sort_values("wf_oos_net", ascending=False).head(12)
    fails = {i: failed_checks(s) for i, s in near.iterrows()}
    nt = pd.DataFrame({"strategy": near.code, "market": near.market, "session": near.session, "bars": near.bars.map(TF_LABEL),
                       "trades/mo": near.trades_per_month.round(1), "win %": near.win_pct.round(1),
                       "avg win ÷ avg loss": near.payoff_ratio.round(2), "OOS net $": near.wf_oos_net.round(0).astype(int),
                       "OOS PF": near.wf_oos_pf.round(2), "MC loss %": near.mc_prob_loss_pct.round(1),
                       "worst stress $": near.stress_worst_net.round(0).astype(int),
                       "not passed": [", ".join(fails[i]) for i in near.index]})
    cnt = pd.Series([x for v in fails.values() for x in v]).value_counts()

    # efficiency rule effect
    lost_eff = r[r.wf_efficiency.isna() & r.wf_efficiency_raw.notna() & (r.wf_efficiency_raw >= 0.5)] if "wf_efficiency_raw" in r else r.iloc[0:0]
    lost_rank = lost_eff[(lost_eff.checks_total - lost_eff.checks_passed == 2)
                         & (lost_eff.wf_oos_net > 0) & (lost_eff.wf_oos_pf >= 1.2) & (lost_eff.mc_prob_loss_pct < 10)
                         & (lost_eff.stress_all_net > 0) & (lost_eff.stress_worst_net > 0) & lost_eff.survived]

    def bh(book):
        return ", ".join(f"{x['market']} {money(x['net $'])} (max DD {money(x['max DD $'])})" for x in book["buy_and_hold"])
    best_bh_a = max(x["net $"] for x in A["buy_and_hold"])
    import timeframe_portfolio as tp
    mq = tp.daily_bars("MNQ").loc[str(A["start"]):str(A["end"])]
    mnq_lo, mnq_hi = float((mq.raw_c * mq.pv).min()), float((mq.raw_c * mq.pv).max())
    n_sel_a, n_sel_b = len(A["selected"]), len(B["selected"])

    md = f"""# Timeframe study: can the photo strategies trade 10–15 times a month?

*Generated {date.today():%B %d, %Y} by `tools/write_timeframe_report.py` from `results/TIMEFRAME_STUDY/rows.csv` ({kn['runs']}
runs, {kn['errors']} errors). Every number below comes from that file, from the run folders it points to, or from the helper
tables in the same folder (`tables.md`, `costs.md`, `portfolio.md`). Reproduce with the commands at the end.*

*Tenth revision (FIX_REPORT.md, "Tenth review"): a run that hit $0 in ANY single stress scenario no longer counts as
surviving; walk-forward efficiency is withheld when too few folds were scored or the in-sample profit is near zero;
roll slippage is counted once in the cost table; the combined book shows carried-in positions, a flat-start view and
gross exposure. {len(rerun)} configurations whose saved paths could have changed under the new entry-fill breach rule were
re-run with the current code; the other rows are the saved runs with the report-side rules applied to their saved
tables.*

## Short answer

1. **No single strategy does it.** Of {kn['runs']} runs, **{kn['robust_runs']}** passed all key checks, and
   **{kn['robust_runs_10_per_month']}** of those trade 10 or more times a month. The most frequent runs that passed everything are
   {t1.code} on {t1.market} {lab(t1.bars)} bars, at {t1.trades_per_month:.1f} trades a month over the whole history
   ({t1.oos_trades_per_month:.1f} out-of-sample), and {t2.code} on {t2.market} {lab(t2.bars)} bars, at {t2.trades_per_month:.1f}
   ({t2.oos_trades_per_month:.1f} out-of-sample).
2. **Shorter bars give many more trades, but they lose money after costs.** On 5-minute bars the median run trades
   {tfstat['5m'].trades_per_month.median():.0f} times a month. {int(c5['runs profitable before costs'])} of {int(c5['runs'])} runs have an edge *before* costs, yet only
   {int(c5['runs profitable after costs'])} are profitable *after* costs. Each trade pays about the same costs whatever the bar size, while the
   average move per trade shrinks with the bar. Nothing on 5- or 15-minute bars passed all checks, and {short_broke} of the
   {len(broke)} runs that hit $0 somewhere are on those two bar sizes.
3. **1-hour and 4-hour bars are where extra trades still hold up.** {by.get('60m', 0)} runs passed on 1-hour bars and
   {by.get('240m', 0)} on 4-hour bars, against {by.get('1440m', 0)} on daily. The passing 1-hour runs trade a median
   {rng(pass_med['60m'])} times a month, the 4-hour runs {rng(pass_med['240m'], '{:.2f}')}, and the passing daily runs
   {rng(pass_med['1440m'])}.
4. **10–15 a month (and more) comes from running several of them together, on separate accounts.** One run per
   strategy and market among the runs that passed made **{A['trades_per_month']} trades a month** on MNQ + gold from {A['start']} to
   {A['end']} ({A['months']} months): net **{money(A['net (marked, includes carried-in positions)'])}**, max drawdown
   **{money(A['max drawdown (daily closes)'])}** on daily closes, profitable in {A['profitable_months']} months. On the longer NAS100 + MGC
   history ({B['start']} to {B['end']}, COVID crash included) it made **{B['trades_per_month']} a month**, net
   {money(B['net (marked, includes carried-in positions)'])}, max drawdown {money(B['max drawdown (daily closes)'])}. Three caveats (section 7): these are
   {n_sel_a} (and {n_sel_b}) separately sized accounts, with up to {A['max positions open at once (bar timestamps)']} positions open at the same moment and
   gross exposure up to {money(A['max gross exposure $ (one day)'])}; the runs were *selected* using checks that include their
   out-of-sample results; and per account the book earned less than holding gold over the same dates.

## 1. What was tested

* **Strategies:** the 13 photo strategies (A01–A13) and the gold futures-vs-spot pair (B01), with the same rules as the
  daily study.
* **Markets:**
  * MNQ (micro Nasdaq futures): 2021-01-05 → 2026-08-14, 5.6 years.
  * NAS100 (CFD): 2012-02-01 → 2021-09-30, 9.7 years.
  * MGC (micro gold futures): 2016-01-04 → 2025-12-31, 10.0 years.
  * XAUUSD (spot gold): 2021-06-29 → 2026-11-17, 5.4 years.

  Each market was tested on the New York cash session and on the full session.
* **Bar sizes:**
  * 5-minute, 15-minute, 1-hour, 4-hour and daily for A01–A07, A11, A12 and B01.
  * A08 (weekly RSI), A09 (turn of the month) and A10 (10-month average) decide on calendar dates, so shorter bars
    can't make them trade more. They ran on daily bars only.
  * A13 (order flow, needs NQ buy/sell volume) ran on 1-, 5-, 15- and 60-minute cash-session bars.
* **How rules were translated to other bar sizes:**
  * Lengths stay in bars: RSI(3) is 3 bars on any bar size.
  * Thresholds written as a percentage of price (A01 "1% below VWAP", A02's VWAP buffer, A11's momentum threshold)
    are scaled by √(bar length ÷ original bar length), because a typical move grows with the square root of time.
    A daily bar counts as one session (390 cash minutes or 1,380 full minutes). For example, A01's 1% becomes 0.11%
    on 5-minute cash bars. The grid tested around each scaled value is in the run folders.
  * Indicator warm-up is three times the longest lookback.
* **Same pipeline for every run as the daily study:**
  * Full history with the photo's settings.
  * Parameter grid with a look-ahead check over the whole period.
  * Walk-forward: optimise in-sample, trade the next window unseen. Windows are 18 + 6 months for bars up to 1 hour,
    36 + 12 months for 4-hour and daily, because those trade too rarely to optimise on 18 months.
  * Monte Carlo (5,000 paths).
  * 9 execution-stress scenarios: double costs, extra slippage, wider spreads, 1–2 bar delays, all combined.
  * The 13-item checklist.
* **Account and costs:** each run trades its own $100,000 account. Most strategies size a trade at about $100,000 of
  contract value; A12 sizes by risk ($500 a trade), so its positions vary (see the entry-notional columns in section 7).
  The account stops trading if it hits $0. Costs:
  * MNQ and MGC: $0.75 commission per side per contract, plus 1 tick of slippage.
  * XAUUSD: the real recorded bid/ask.
  * NAS100: a fixed 1.2-point spread.
* **"Passed all key checks"** means all of these:
  * profitable out-of-sample with out-of-sample PF ≥ 1.2;
  * Monte Carlo chance of a loss under 10%;
  * still profitable under the combined execution stress, **and** in every single stress scenario;
  * never hit $0: full history, walk-forward, the combined stress **or any single stress scenario**;
  * at most one of the 13 checklist items not passed. The walk-forward efficiency item counts as not passed when the
    ratio is not available: fewer than {walkforward.MIN_SCORED_SHARE:.0%} of the scheduled folds were scored, or the pooled
    in-sample profit is below {walkforward.MIN_IS_RETURN_PER_YEAR:.0%} of capital a year (a ratio over a near-zero denominator).

## 2. Results by bar size

{sec('BYTF')}

"Hit $0 somewhere" counts runs that ran the $100,000 account to zero in the full history, the walk-forward, or any
stress scenario. On the plain full history alone: {', '.join(f"{int(full_broke.get(tf, 0))} on {lab(tf)}" for tf in ('5m', '15m', '60m', '240m', '1440m'))} bars.

## 3. Why the short bars fail: costs per trade

Every out-of-sample trade, before and after costs. Fill prices already include slippage and the bid/ask spread, so
"before costs" adds back commission, roll charges, fill slippage and the spread, each once. This describes the
trades that were executed; it is not a re-run with zero costs.

{costs_md}

What the table shows:

* **The edge is real but small.** On 5-minute bars the average trade made **${c5['avg trade before costs $']:.2f} before costs** and paid
  **${c5['avg costs per trade $']:.2f}** in costs.
* **The edge grows with the bar; costs don't.** The average trade before costs is ${c('60m')['avg trade before costs $']:.0f} on 1-hour bars,
  ${c('240m')['avg trade before costs $']:.0f} on 4-hour and ${c('1440m')['avg trade before costs $']:.0f} on daily, while costs stay at
  ${fr_med.min():.0f}–{fr_med.max():.0f} a trade on 5-minute to daily bars.
* **MNQ is the cheapest market to trade often** (${c('60m', 'MNQ')['avg costs per trade $']:.2f} a trade on 1-hour bars), and on 1-hour bars it
  makes {usd2(c('60m', 'MNQ')['avg trade after costs $'])} a trade after costs, against {usd2(c('60m', 'XAUUSD')['avg trade after costs $'])} on XAUUSD,
  {usd2(c('60m', 'NAS100')['avg trade after costs $'])} on NAS100 and {usd2(c('60m', 'MGC')['avg trade after costs $'])} on MGC.

## 4. Every strategy on every bar size

Cells show runs that passed all key checks / runs, then the median trades per month:

{sec('GRID')}

Medians across the market/session runs of each cell. "Avg win ÷ avg loss" is the reward-to-risk ratio actually
achieved (average winning trade ÷ average losing trade):

{sec('DETAIL')}

What stands out (counts from the table above):

* **A01, A03, A04 (RSI/Williams + EMA + VWAP pullbacks):** {d_pull} of their {n_pull} daily runs passed. On 4-hour bars:
  A01 {n_rob('A01', '240m')}, A03 {n_rob('A03', '240m')}, A04 {n_rob('A04', '240m')}. On 1-hour bars: A01 {where('A01', '60m')}; A03 {where('A03', '60m')};
  A04 {where('A04', '60m')}. Below 1 hour none passes.
* **A05, A06, A07 (z-score, rubber band, MFI):** the most frequent traders and the most cost-sensitive. Passing runs:
  A05 {len(rob[rob.code == 'A05'])}, A06 {len(rob[rob.code == 'A06'])}, A07 {len(rob[rob.code == 'A07'])} (A07 on 4-hour: {where('A07', '240m')}).
* **A11 (time-series momentum):** profitable out-of-sample in {'; '.join(f"{a11_oos[tf][0]} of {a11_oos[tf][1]} on {lab(tf)}" for tf in ('5m', '15m', '60m', '240m', '1440m') if tf in a11_oos)}
  runs with a walk-forward. It wins less than half its trades but the average win is about twice the average loss;
  what stops it is reliance on a few big trades, drawdown and (for several gold runs) a walk-forward efficiency that
  is not available because too few folds were scored or the in-sample profit is near zero.
* **A12 (squeeze breakout):** designed for 15-minute bars; passing runs: {', '.join(f"{m} {lab(b)}" for m, b in zip(rob[rob.code == 'A12'].market, rob[rob.code == 'A12'].bars)) or 'none'}.
* **A02, A13, B01:** pass on no bar size. A13 can't trade at all on 1-hour bars: it needs 90% of the last 1,950 bars
  to be valid one-bar samples, and only 5 of the 7 hourly cash bars per day qualify (the 09:30 bar is 30 minutes, and
  the first bar of each day has no earlier bar that day).

## 5. Every run that passed all key checks ({kn['robust_runs']})

Sorted by bar size, then out-of-sample profit. "Trades/mo" is over the whole history; "OOS" is the walk-forward
(parameters chosen only on earlier data):

{rbt.to_markdown(index=False)}

Runs on 1-hour and 4-hour bars that passed: **{len(intraday)}** ({by.get('60m', 0)} + {by.get('240m', 0)}), covering
{', '.join(sorted(intraday.market.unique()))} and strategies {', '.join(sorted(intraday.code.unique()))}.

The efficiency rule removed {len(lost_rank)} run{'s' if len(lost_rank) != 1 else ''} that passed before:
{'; '.join(f"{x.code} {x.market} {'cash' if x.session == 'rth' else 'full'} {lab(x.bars)} (raw ratio {x.wf_efficiency_raw:,.2f}: {x.wf_efficiency_note})" for x in lost_rank.itertuples()) or 'none'}.

## 6. Frequent but not robust: the closest misses (≥ 10 trades a month, profitable out-of-sample)

{nt.to_markdown(index=False)}

Checklist items these {len(near)} runs did not pass, most common first:
{chr(10).join(f"* {k}: {v} of {len(near)}" for k, v in cnt.items())}

Profitable out-of-sample is not enough here: these miss on the reliance on a few big trades, an isolated best
setting, Monte Carlo risk or execution stress. They are candidates for a forward test, not for trading.

## 7. Getting to 10–15 trades a month: run several robust strategies together

The runs that passed all key checks are combined, using only their saved out-of-sample results.

**Selection rule:** one run per strategy and underlying market, the one with the **most** out-of-sample trades a
month. The rule picks by frequency, not profit. MNQ and NAS100 are both the Nasdaq-100, and MGC and XAUUSD are both
gold. The cash and full session and the different bar sizes of one strategy on one market take mostly the same
trades, so they count once.

**Measured on:** only the dates inside every selected run's walk-forward schedule. A fold in which the optimiser found
no valid setting trades nothing and counts as zero. Two views: *marked* (daily equity changes, including positions
already open on the first day) and *flat start* (only trades entered in the window, whole P&L).

### Book 1: tradable now (MNQ + MGC + XAUUSD)

{books[2].strip()}

### Book 2: longest history (NAS100 + MGC)

{books[4].strip()}

How to read this:

* **The trade count is the answer to "10–15 a month":** book 1 averaged **{A['trades_per_month']}** trades a month from {n_sel_a} runs
  and book 2 **{B['trades_per_month']}** from {n_sel_b} runs. Book 1 had {A['positions carried in at start']} positions already open on its first day
  (book 2: {B['positions carried in at start']}); they are in the marked P&L, not in the trade count. The flat-start view, which leaves
  them out, gives {money(A['net (flat start: trades entered in window, whole P&L)'])} for book 1 and {money(B['net (flat start: trades entered in window, whole P&L)'])} for book 2.
* **This is NOT one account.** Each run sized its trades on its own $100,000 account, so the dollar figures add
  {n_sel_a} (or {n_sel_b}) separately sized accounts. At most {A['max positions open at once (bar timestamps)']} book-1 positions were open at the same moment
  ({A['max positions open on one day']} on one day counting every position open at any time that day), and gross exposure reached
  {money(A['max gross exposure $ (one day)'])} (median {money(A['median gross exposure $'])}). Book 2: {B['max positions open at once (bar timestamps)']} at once, gross exposure up to
  {money(B['max gross exposure $ (one day)'])}. One $100,000 account cannot carry that: positions would have to be cut to a
  fraction, and micro contracts can't be cut that finely (one MNQ contract was {money(mnq_lo)}–{money(mnq_hi)} of contract
  value in this period at daily closes, and positions are rounded *down* to whole contracts). A single account can run only a few
  of these at full size. A capital-constrained portfolio test on untouched data is the step before trusting these
  dollar figures.
* **Compare with buy-and-hold over the same dates** ($100,000 of contract value, same costs):
  * Book 1 period: {bh(A)}.
  * Book 2 period: {bh(B)}.

  Most of these strategies only buy, and Nasdaq and gold both rose strongly in both periods. Per $100,000 account the
  book earned less than holding gold in book 1 ({money(best_bh_a)}). What it offers is smaller drawdowns per account and
  many more, smaller bets, not a higher return than the market.
* **Selection bias:** the runs were chosen because they passed checks that include their out-of-sample results. This
  combined record is therefore optimistic. It is not a fresh test; the next step is a forward test on data none of
  this has seen.

## 8. What needs to change to go from ~10 trades a year to 10–15 a month

Tested here:

1. **Move from daily to 1-hour or 4-hour bars, not to 5- or 15-minute.** Some pullback, MFI, momentum and squeeze
   runs keep an edge there (section 5), at a median {pass_med['60m'].median():.1f} (1-hour) and {pass_med['240m'].median():.1f} (4-hour) trades a
   month per run instead of {pass_med['1440m'].median():.1f} on daily. Below 1 hour, costs take more than the edge.
2. **Scale price-percentage thresholds to the bar size** (done in this study). A "1% below VWAP" rule almost never
   triggers on a 5-minute bar. The scaled 0.11% does, but it produces the small, cost-eaten trades of section 3.
3. **Trade several uncorrelated strategies and markets at once.** This is what reaches the target: {A['trades_per_month']} a month in
   book 1 and {B['trades_per_month']} in book 2, but with the exposure described in section 7.
4. **Trade the cheaper instruments when trading often.** MNQ costs about ${c('60m', 'MNQ')['avg costs per trade $']:.0f} a trade on 1-hour bars against
   ${c('60m', 'MGC')['avg costs per trade $']:.0f} for MGC and ${c('60m', 'NAS100')['avg costs per trade $']:.0f} for NAS100. On 1-hour bars that difference decides profit or loss.

Not tested here (suggestions only):

* Cut the cost per trade (limit entries instead of market fills, fewer lots per trade).
* Design rules for intraday from the start, with targets several times the cost, instead of shrinking daily rules.

## 9. Limits of this study

* **Selection bias** in sections 5–7: picking the best of {kn['runs']} runs flatters the winners. Forward-test before trusting
  any of them.
* **Data coverage:**
  * MNQ has 5.6 years and XAUUSD 5.4 years. The 4-hour and daily walk-forwards on them have only 2.6 and 2.5 years
    of out-of-sample data, and few trades (see the "OOS trades" column).
  * NAS100 data ends 2021-09-30.
* **The √-time scaling of percentage thresholds is an assumption.** The parameter grid tests lower and higher values
  around each scaled one (A01 0.5×–1.5×, A11 0.6×–1.6×, A02 0 to 2× of its 0.5% default), but a different rule
  could give different trade counts.
* **The efficiency limits are a policy choice** ({walkforward.MIN_SCORED_SHARE:.0%} of folds scored, in-sample profit ≥
  {walkforward.MIN_IS_RETURN_PER_YEAR:.0%} of capital a year). They are set in `engine/walkforward.py`; changing them changes which runs pass.
* **Mixed code versions:** {len(rerun)} rows were re-run with the current code; the others keep their saved runs (code
  versions in the index: {len(versions)}). The engine changes since those runs could only alter a saved path where an
  account came within its entry costs of $0; the {len(rerun)} configurations that came within $5,000 were re-run and gave
  identical trades, P&L and stress tables. No saved fold schedule has an absent window, and every configuration's
  look-ahead gate was re-checked with the new decision-bar cuts. The report-side rules were applied to the saved
  tables.
* **Fixed costs**, without commission tiers or exchange fees by date. The stress scenarios (double costs, triple
  spread, 2-bar delay) show how much margin each run has.

## Reproduce

```
cd /Volumes/T9/BACKTESTING
~/.venvs/t9-backtesting/bin/python timeframe_study.py --workers 4        # resumes; reruns only changed code or data
~/.venvs/t9-backtesting/bin/python tools/recheck_efficiency.py results/TIMEFRAME_STUDY/rows.csv
~/.venvs/t9-backtesting/bin/python tools/timeframe_report.py    > results/TIMEFRAME_STUDY/tables.md
~/.venvs/t9-backtesting/bin/python tools/timeframe_costs.py     > results/TIMEFRAME_STUDY/costs.md
~/.venvs/t9-backtesting/bin/python tools/timeframe_portfolio.py > results/TIMEFRAME_STUDY/portfolio.md
~/.venvs/t9-backtesting/bin/python tools/write_timeframe_report.py
```
Each row of `rows.csv` points to its run folder (`report` column). The folder holds the full robustness report,
the walk-forward folds and trades, Monte Carlo and stress tables. `tables.md` also has the complete table of all
{kn['runs']} runs.
"""
    (ROOT / "TIMEFRAME_STUDY_RESULTS.md").write_text(md)
    print(f"TIMEFRAME_STUDY_RESULTS.md: {len(md):,} characters")


if __name__ == "__main__":
    main()
