# Backtesting engine audit findings

**Reviewed commit** `882fbd7`  
**Audit date** November 22, 2026

For current results and open issues, see [Verification after the ninth revision](#verification-after-the-ninth-revision). The [consolidated audit](#consolidated-end-to-end-audit) and [original photo-study audit](#photo-study-audit) preserve the earlier evidence.

**Recheck workflow.** After every requested recheck, update this file with the verified fixes, open issues, and test and result evidence before reporting back.

All 29 existing tests passed. The full MNQ robustness run reproduced the previous stress scenario CSV and the walk-forward trade file exactly. Independent checks confirmed bugs that change reported P&L, allow fills before an order could execute, and let future data pass the look-ahead check. Treat the profitability and risk figures as provisional until the affected components are fixed and the tests rerun.

## Stress tests

The full MNQ run used the previous report’s 16-setting grid, nine walk-forward folds, three workers, and 10,000 simulations each for bootstrap and shuffle. It completed in **38 seconds**. The engine reported **+$31,646.75 out of sample**, a **1.159 profit factor**, and a **99.73% simulated chance of hitting a $5,000 drawdown limit** in the trade bootstrap. The 95th-percentile bootstrap drawdown was **$19,082**. Removing the best 5% of trades changed the full-period stress baseline from **+$50,389.50** to **−$34,348**. [MNQ robustness report](results/20261122_174834_ALL_orb_MNQ/ROBUSTNESS_REPORT.md) · [Outlier stress results](results/20261122_174834_ALL_orb_MNQ/stress/stress_outlier_dependence.csv)

| Strategy and market | Coverage | Baseline P&L | Combined stress P&L |
|---|---|---:|---:|
| [ORB · MGC](results/20261122_174521_stress_orb_MGC/stress_report.txt) | Jan–Jun 2024 | −$6,921.50 | −$10,872.00 |
| [ORB · XAUUSD](results/20261122_174528_stress_orb_XAUUSD/stress_report.txt) | Jan–Jun 2024 | −$6,278.17 | −$10,186.04 |
| [ORB · NAS100](results/20261122_174521_stress_orb_NAS100/stress_report.txt) | Jan–Jun 2019, cash session | −$2,481.53 | −$5,523.73 |
| [Hourly SMA · GC](results/20261122_174728_stress_sma_cross_GC/stress_report.txt) | Full GC history | −$5,889.00 | −$5,976.14 |

### Delayed close requests inflate the MNQ stress results

**High.** ORB calls `close()` on every bar after its flatten time. Each call replaces the pending request’s timestamp, restarting the one- or two-bar delay. In the one-bar run, **669 scheduled end-of-day exits executed at 00:01 New York time**. I replayed the full MNQ history with one change in memory: preserve the first pending close request for each position. The table isolates that change. [Broker close request](engine/core.py#L155) · [ORB flatten logic](strategies/orb.py#L41)

| MNQ scenario | Reported P&L | P&L with first close request preserved | Reported minus replay |
|---|---:|---:|---:|
| One-bar delay | +$52,522.00 | +$46,441.50 | +$6,080.50 |
| Two-bar delay | +$49,840.00 | +$41,929.00 | +$7,911.00 |
| Combined costs and delay | +$44,255.00 | +$38,179.50 | +$6,075.50 |

The zero-delay baseline also had **37 trades cross a trading-day boundary**, with **33 scheduled exits at 18:01 ET**. ORB’s flatten rule needs a session-aware cutoff and explicit handling for early closes and missing bars. [ORB session logic](strategies/orb.py#L35)

## Correctness findings

### High priority

| Finding | Reproduction and impact |
|---|---|
| **Orders can fill at the open after an intrabar exit.** | A long stopped out at 95 during a bar that opened at 110. A pending short then filled at the earlier 110 open and booked **$150**. An order eligible only while flat can act once the long exits. [Execution loop](engine/core.py#L365) |
| **OCO order-list order can choose the wrong breakout.** | On **Aug 27, 2021 at 10:00 ET**, the NQ one-second data show the short trigger at **10:00:06** and the long trigger at **10:00:56**. The engine took the long because it checks the buy first. The same-bar logic can also award a target using a high reached before the entry. A bar that opens at 105, then trades 110, then drops to 98 can falsely award a target of 108 to a long limit entry at 99. [Order fills](engine/core.py#L299) · [Same-bar exits](engine/core.py#L269) |
| **The look-ahead check gives false passes.** | A strategy that replaced `c` with `c.shift(-1)` passed. A strategy that read `self.d["c"][i+2]` in `on_bar()` also passed and booked three synthetic winners. The checker compares only newly added columns, and the sweep and walk-forward gate checks only the base parameters on a sampled prefix. Strategy preparation can overwrite prices the engine uses for fills. [Engine input](engine/core.py#L168) · [Look-ahead checker](engine/core.py#L416) · [Robustness gate](robust.py#L77) |
| **XAUUSD spread stress creates impossible quotes.** | The code widens bid and ask highs and lows independently, even though the extrema can occur at different times. At 2× spread, **21,378 bid bars** and **20,881 ask bars** out of 175,994 had invalid OHLC, such as a high below the open. These bars can create or suppress fills. Widen synchronized quotes before aggregating them. [Spread construction](engine/core.py#L175) |
| **Walk-forward warm-up can suppress scored trades.** | Warm-up runs the broker and filters out warm-up trades afterward. A warm-up position blocked the first scored trade in a synthetic run, leaving the reported window with zero trades. Each fold starts with fresh capital, so stitched dollar P&L differs from a continuous run using `risk_pct`. Month-end folds can leave gaps. With two workers, I also reproduced a crash when every fold fell below the minimum trade count and the OOS job list was empty. [Window runner](engine/parallel.py#L50) · [Fold dates](engine/walkforward.py#L36) · [OOS stitching](engine/walkforward.py#L86) |
| **Reported drawdown hides some losses within a session.** | A synthetic position went **$500 underwater** and recovered before the close. The summary reported **$0** drawdown. Full-run summaries use day-end marks, while robustness windows reconstruct equity from closed trades. Actual MNQ baseline drawdown was **$5,689** in the report and **$6,053** using minute-close marks. Minute-close marks still omit movement within each minute. [Summary metrics](engine/metrics.py#L14) · [Robustness equity](engine/metrics.py#L95) |
| **Futures roll handling can erase market moves or use a later price.** | The GC adjustment forced the new open to equal the previous adjusted close at **all 50 rolls**, erasing whatever market move was embedded in those gaps. NQ uses the roll minute’s **close** spread while executing the roll at the **open**. Those spreads differed on **21 of 22 rolls**, by up to **10.75 points**. Full-history back-adjustment also embeds later rolls in earlier price levels, which affects signals based on absolute prices or percentage moves. [Futures loaders](engine/data.py#L47) · [Roll execution](engine/core.py#L348) |

### Medium priority

| Finding | Reproduction and impact |
|---|---|
| **Execution rules allow optimistic fills and invalid quantities.** | Verified a futures target filling on an opening touch despite the configured trade-through rule, a spread-gap stop filling above every available bid, a forced final exit with zero slippage, and a **1.5-contract** futures fill. The simulator omits margin, buying-power, and available-volume checks. [Sizing](engine/core.py#L210) · [Exit fills](engine/core.py#L269) · [Limit entry](engine/core.py#L321) · [Final exit](engine/core.py#L387) |
| **Daily Monte Carlo can silently omit flat days.** | The command used **987 days** from the saved walk-forward folder because that export lacks a daily equity file. Rebuilding the same simulation with all **1,064 OOS trading days** changed its 95th-percentile drawdown from **$15,736** to **$16,011**. Also, `--skip` skips entire daily P&L observations in daily mode. [Monte Carlo input](robust.py#L123) · [Simulation](engine/montecarlo.py#L27) · [Daily simulation report](results/20261122_174455_ALL_orb_MNQ/20261122_174504_walkforward_orb_MNQ/montecarlo_daily/montecarlo_report.txt) |
| **Input and report checks miss common failures.** | A one-month stress run crashed computing its worst three-month window. `--data NQ` with the XAUUSD instrument produced NQ trades labeled XAUUSD. A 10-minute ORB on 15-minute bars used the full 15-minute bar. The regression comparator uses numerical tolerance and exits successfully when it prints `DIFFERENT`. [Stress report](engine/stress.py#L93) · [Dataset selection](robust.py#L65) · [ORB range](strategies/orb.py#L19) · [Regression comparator](tools/compare_runs.py#L5) |

## Performance and cache integrity

- **The single-run engine is reasonably fast on the tested workload.** A cached, full-history MNQ ORB run processed **1.99 million bars in about one second** outside the profiler. The profiler showed the bar loop and nearly two million strategy callbacks dominating the run. [Engine loop](engine/core.py#L336)
- **The robustness pipeline repeats work.** Sweep, walk-forward, and stress reload data in the parent and recreate worker pools. Each worker loads its own full frame. Each optimization job builds per-bar equity and returns trades even when selection only needs summary scores. Reusing workers and adding a summary-only path for in-sample jobs would target this repeated work. [CLI stages](robust.py#L93) · [Worker implementation](engine/parallel.py#L44) · [In-sample selection](engine/walkforward.py#L65)
- **Monte Carlo’s memory estimate is too low.** A 10,000-simulation bootstrap with 3,500 observations reached **1,214 MiB peak RSS** despite a comment estimating about 300 MB. Several full matrices coexist, and retained sample paths keep their original batch allocation alive. [Monte Carlo batching](engine/montecarlo.py#L65)
- **Cache rebuilds can race with readers.** The cache loader accepts existing files without checking source freshness and writes rebuilds directly to the final path. Concurrent runs can read a partially written file. [Cache loader](engine/data.py#L125)

## Reproducing the runs

Run from `/Volumes/T9/BACKTESTING` using the project’s configured Python environment. Commands write new reports under `results/`.

```bash
PY=~/.venvs/t9-backtesting/bin/python

"$PY" -m pytest tests -q -p no:cacheprovider

"$PY" robust.py all strategies/orb.py --symbol MNQ \
  --grid rr=1.5,2,2.5,3 or_minutes=10,15,20,30 \
  --is-months 18 --oos-months 6 --ruin 5000 --workers 3

"$PY" robust.py stress strategies/orb.py --symbol MGC,XAUUSD \
  --start 2024-01-02 --end 2024-06-28 --workers 2 --set rr=3 or_minutes=30

"$PY" robust.py stress strategies/orb.py --symbol NAS100 --data NAS100_RTH \
  --start 2019-01-02 --end 2019-06-28 --workers 1 --set rr=3 or_minutes=30

"$PY" robust.py stress strategies/sma_cross.py --symbol GC --tf 60 --workers 2

"$PY" robust.py montecarlo \
  --from results/20261122_174455_ALL_orb_MNQ/20261122_174504_walkforward_orb_MNQ \
  --method daily --block 5 --ruin 5000

# Reproduces the short-window stress report crash.
"$PY" robust.py stress strategies/orb.py --symbol MNQ \
  --start 2024-01-02 --end 2024-01-31 --workers 1 --set rr=3 or_minutes=30

# Reproduces the empty OOS job list crash.
"$PY" robust.py walkforward strategies/orb.py --symbol MNQ \
  --start 2024-01-02 --end 2024-03-29 --is-months 1 --oos-months 1 \
  --grid rr=2,3 --min-trades 10000 --workers 2
```

Fix fill chronology and OCO ordering, close scheduling, look-ahead enforcement, and walk-forward state first. Add regression cases for the verified failures, then compare trades, P&L, and drawdown against the original reports.

## Follow-up after the first fixes

**Recheck date** November 22, 2026  
**Reviewed version** Revised working tree following the changes described in [FIX_REPORT.md](FIX_REPORT.md)

All **51 tests passed**, and a fresh MNQ run reproduced the revised stress scenarios and walk-forward trade file. The targeted checks below identify five remaining defects. Their effect on full-history P&L and drawdown has yet to be measured. [Revised robustness report](results/20261122_181839_ALL_orb_MNQ/ROBUSTNESS_REPORT.md)

| Priority | Open issue | Reproduction and expected behavior |
|---|---|---|
| High | **Reverse slices bypass the look-ahead guard.** | At bar 0, `self.d["c"][2:0:-1][0]` returned the close of bar 2. The test strategy passed the look-ahead check and used that read to book a **$100 synthetic profit**. Validate every index a slice can access, including reverse slices. [Guard](engine/core.py#L137) |
| High | **Intraday drawdown misses declines from opening peaks.** | A one-contract position entered at 100 with a synthetic point value of $10. A later bar opened at 150, fell to 100, and closed there. The position gave back **$500** from an observable opening peak, while the report showed **$0** drawdown. Include opening marks in the equity peak calculation and preserve the order of the open and later prices. [Drawdown calculation](engine/metrics.py#L14) |
| High for gold stress tests | **XAUUSD spread stress uses later quotes to price the open.** | Two test bars opened with the same 100.10 ask and 99.90 bid. At 2× spread, the simulated buy filled at **100.20** when the closing ask was 100.10 and **101.10** when it was 101.00. The opening fill should use the opening quote. Widen synchronized quotes before aggregating whenever quote-level data are available. [Spread calculation](engine/core.py#L252) |
| Medium | **Futures limit entries bypass the one-tick rule at the open.** | A buy limit and a sell limit each filled at 100 when the next bar opened exactly at 100 and never traded one tick through the order. Each booked **$20** in its synthetic case. Apply the configured trade-through rule at the open as well as inside the bar. [Limit entries](engine/core.py#L420) |
| Medium | **Four-hour GC bars move rolls earlier.** | Resampling moved **37 of 50** rolls to earlier timestamps. The engine can charge roll costs before the contract switches, and the aggregated bar can carry the new contract label while using the old contract’s open. Preserve the underlying roll time or split the bar at the switch. [Resampling](engine/data.py#L215) · [Roll execution](engine/core.py#L473) |

### MNQ fill verification still pending

For the one-minute MNQ ORB, replay ambiguous fills against the available one-second NQ data. The revised engine chooses the trigger nearest the bar’s open when several entry orders qualify. That rule matched the observed sequence in the Aug 27, 2021 example, but the minute bar alone cannot establish the sequence. Compare the first trigger, subsequent stop and target order, and resulting trade P&L. Flag cases where both triggers still occur within the same second. [Breakout ordering](engine/core.py#L433)

## Remaining fixes after the second revision

**Last verified** November 22, 2026

All **60 tests passed**. The four cases below also reproduced on the latest available code. The full MNQ rerun reproduced the revised stress scenarios and walk-forward trade file. The new one-second verifier confirmed the same August 27, 2021 short entry and **−$495** stop-out for both the default 15-minute, 2R setup and the 30-minute, 3R setup. That was one trade checked for both entry and exit ordering. [MNQ robustness rerun](results/20261122_183241_ALL_orb_MNQ/ROBUSTNESS_REPORT.md) · [Default replay](results/20261122_183243_verify_1s_orb_MNQ/summary.txt) · [30-minute replay](results/20261122_183246_verify_1s_orb_MNQ/summary.txt)

### 1. Guard strategy access to broker data

**High priority.** On bar 0, a synthetic strategy read bar 2 through `self.broker.d["c"][2]`, passed the look-ahead checker, and booked **$100** from the future-derived signal. The reverse-slice fix applies to the guarded view in `strategy.d`. The broker still exposes the original columns.

Route strategy-facing reads through the same bar-bounded view, including access through the broker. Keep the engine’s internal execution data separate. Add a regression that rejects the broker read at bar 0 and accepts current and historical reads. [Broker data](engine/core.py#L169) · [Guard setup](engine/core.py#L244)

### 2. Include pre-exit equity and use the correct drawdown peak

**High priority.** A synthetic long entered at 100 with a $10 point value. On a path of 100 → 50 → 110 target, it went **$500 underwater** before exiting at a profit. The bar-based report showed **$0 drawdown** because it used the flat balance after the exit. In a separate case, equity fell from **$51,000 to $50,000**, then rose to **$51,500** later that day. The report used the later peak and showed **−1.94%** instead of **−1.96%**.

Carry equity extrema observed while the position was open into exit-bar metrics. Use finer data when available to establish which moves happened before the exit. If OHLC leaves the order ambiguous, document the assumption or report bounds. Compute percentage drawdown from the peak that preceded the trough and test both examples. [Equity marking](engine/core.py#L530) · [Drawdown percentage](engine/metrics.py#L52)

### 3. Preserve the actual roll event within resampled bars

**Medium priority.** Four-hour GC data moved **37 of 50** roll charges later, by up to **180 minutes**. In a synthetic position held through a switch inside the final bar, the one-minute engine charged one roll and **$4 total commission**. The five-minute engine charged zero rolls and **$2 total commission**.

Keep the actual switch timestamp and either split mixed-contract bars or account for the switch inside the bar. Charge exactly one roll when a position spans the switch, including on a final or window-ending bar. Test positions that close before the switch, survive it, and open afterward. [Resampling](engine/data.py#L232) · [Roll execution](engine/core.py#L498)

### 4. Report unresolved replay events and handle zero trades

**Medium priority.** The one-second verifier marked a same-second tie as both **unresolvable** and **agrees**, then copied the engine P&L into the replay column. It also crashed on a zero-trade run because the empty trade frame lacked `entry_time`. Reproduce the crash with `tools/verify_orb_fills_1s.py --start 2024-01-02 --end 2024-01-04 --set min_range=1000000000`.

Use distinct outcomes for agreement, disagreement, and unresolved events. Leave replay P&L blank when the sequence cannot be established, and compare totals only for resolved events. A zero-trade run should exit successfully with a zero-case summary and a readable CSV. Add tests for a tie, missing second data, and a zero-trade run. [Zero-trade handling](tools/verify_orb_fills_1s.py#L109) · [Tie handling](tools/verify_orb_fills_1s.py#L135)

## Photo-study audit

**Audit date** November 22, 2026

**Reviewed version** `audit-fixes` working tree based on `4749c7a`

### Verification

All **96 tests passed**. I reconciled all **94 study rows** against the saved out-of-sample P&L, profit factor, Monte Carlo probability of ending at a loss, and combined stress P&L. The numbers matched, including the **32 runs** that met the study's pass criteria. I independently reran three complete robustness suites. All three reproduced the saved walk-forward trade file and stress scenario table exactly. [Published study](PHOTO_STUDY_RESULTS.md) · [Study rows](results/PHOTO_STUDY/study_rows.csv)

| Independent rerun | Out-of-sample net P&L |
|---|---:|
| [A01 RSI, EMA, and VWAP on MNQ cash-session bars](results/20261122_201723_ALL_a01_rsi_ema_vwap_MNQ/ROBUSTNESS_REPORT.md) | +$17,526.50 |
| [A09 turn of the month on NAS100 full-session bars](results/20261122_201723_ALL_a09_turn_of_month_NAS100/ROBUSTNESS_REPORT.md) | +$75,592.26 |
| [B01 MGC and XAUUSD pair](results/20261122_201723_ALL_b01_pairs_gold_futures_vs_spot_MGC/ROBUSTNESS_REPORT.md) | −$172.81 |

The latest MNQ ORB execution stress table also matched the previous verified table exactly, including **+$49,613.50** at baseline and **+$38,931.50** under combined costs and delay. [ORB stress rerun](results/20261122_201829_stress_orb_MNQ/stress_report.txt)

### 1. Use one signal bar per completed trading session

**High priority.** GC full-session resampling creates **37 trading days with two daily bars** because it splits bars at the actual contract switch. The Faber strategy fed both fragments into its monthly moving average on **21 month-end dates**. An isolated MGC replay that made one decision per completed session and retained roll execution changed full-history Faber P&L from **+$86,944.86 to +$104,129.87**. The first entry moved from October 2 to October 31, 2016 UTC.

Compute daily indicators on a single OHLCV row per completed session and deliver each signal after the final fragment closes. Keep the split execution bars for rollover accounting. Test that a month-end roll contributes one observation to the moving average and generates a decision only at session close. Apply the same one-observation check to weekly RSI and daily lookbacks. [Resampling](engine/data.py#L243) · [Faber signals](strategies/photos/a10_faber_10_month.py#L17) · [Weekly RSI](strategies/photos/a08_weekly_rsi.py#L20)

### 2. Match benchmark dates and drawdown accounting

**High priority.** The study passes only the walk-forward start date to `buy_and_hold()`, so the benchmark can extend past the last scored fold. For A11 on MGC cash-session bars, the strategy's walk-forward ended **December 31, 2024**, and its reported buy-and-hold profit was **+$112,017.14**. Ending the benchmark on that date gave **+$29,672.60**. In a synthetic benchmark that opened with equity at $150,000 and fell to $100,000 in the same bar, reported drawdown was **$0**.

Use the actual scored dates, including both endpoints, and explicitly account for gaps between scored folds. Use the same chronological open, low, and close drawdown calculation as the strategy. Test a walk-forward period ending before the dataset ends and the $50,000 opening-peak decline. Keep benchmark sizing and costs explicit in the report. [Benchmark calculation](photo_study.py#L42) · [Walk-forward date selection](photo_study.py#L81) · [Engine drawdown](engine/metrics.py#L23)

### 3. Give B01 enough warm-up for both rolling windows

**High priority.** The study gives hourly strategies **10 calendar days** of warm-up. B01 uses a rolling hedge ratio followed by a rolling spread z-score. Its configured windows of 460, 1,380, and 2,760 bars need **919, 2,759, and 5,519 observations**, respectively, for the first valid z-score. Using the saved dates and parameter choices, extending warm-up to 90 days changed OOS from **61 trades and −$172.81** to **107 trades and −$1,035.76**. This replay kept the selections fixed.

Warm up each parameter combination with enough actual preceding observations before scoring. Surface insufficient history in the fold report. Rerun both in-sample selection and out-of-sample scoring after the change. [Study warm-up](photo_study.py#L64) · [Nested windows](strategies/photos/b01_pairs_gold_futures_vs_spot.py#L24)

### 4. Synchronize B01 price observations

**High priority.** The loader resamples GC and XAUUSD separately and inner-joins on bar opening timestamp. Of **26,438 matched hourly bars**, **267** had different last source-minute timestamps. **55** differed by at least five minutes and the largest mismatch was **54 minutes**. These pairs can generate spread moves from prices observed at different times.

Align both legs on common observation times and define how to handle missing or stale quotes. Preserve contract switch times explicitly. Test a missing minute, a gap at the start or end of an hour, and a roll-split bar. For each accepted pair observation, verify both timestamps and the next executable entry time. [Pair loader](engine/pairs.py#L26)

### 5. Stress both B01 legs and label before-cost P&L accurately

**High priority.** The stress builder checks the primary MGC instrument for spread, so combined stress left the XAUUSD spread at its baseline. Applying the 2× XAUUSD spread with the other combined settings held fixed changed P&L from **−$2,430.18 to −$4,482.60**. The published verdict also says the pair loses before costs. The default run reported **−$3,701.61 net** and **−$2,819.11** in its gross field, which already embeds bid/ask and slippage. Removing explicit commissions, slippage, bid/ask spread, and roll charges in a replay gave **+$300.31**.

Build execution stress from both instruments in a pair. Report the nominal P&L before execution costs, spread and slippage effects, and the final result as distinct values. Test that combined B01 stress actually changes the spot opening and closing quotes, and reconcile the reported P&L components to the trade totals. [Stress builder](engine/stress.py#L31) · [Pair P&L](engine/pairs.py#L145) · [Study verdict](PHOTO_STUDY_RESULTS.md#verdict-by-strategy)

### 6. Separate session clocks from the eligible trading calendar

**Medium priority.** NAS100 cash-session filtering retained **51 dates** the project's equity calendar marks closed, and the A09 cash-session run entered on **two** of those dates. A13 also trains its one-minute regression on price changes spanning session gaps. Its default MNQ cash-session run had **352 trades crossing a trading-day boundary**, and the longest lasted **3 days, 17 hours, 32 minutes**. Masking the prediction on the first bar of a session leaves the overnight return in the fit and permits a pending order or position to cross into the next day.

Use a consistent instrument-specific session calendar for filtering, signal dates, and order eligibility. Make the distinction between a cash-market day and a futures holiday session explicit. If A13 is intended to trade intraday, exclude returns spanning gaps and define a last-entry and flatten rule. Test a holiday, a shortened session, and the final bar before a weekend. [Session filtering](engine/data.py#L221) · [Calendar logic](engine/calendar.py#L54) · [A13 signals and execution](strategies/photos/a13_order_flow_imbalance.py#L21)

### 7. Validate pair instruments and make study resume reproducible

**Medium priority.** A B01 run accepted `--symbol MNQ`, used the GC and XAUUSD datasets, and reported **56 trades** under MNQ contract specifications in the tested window. Separately, the study's resume key uses only strategy name, market, and session. In a temporary study, a normal resume skipped previously failed rows, and a filtered `--fresh` run replaced unrelated rows in the summary CSV.

Validate the configured primary and secondary instruments against their datasets before launching a pair run. Version completed study rows with the code, input, configuration, and data fingerprints, and let failed rows retry. Preserve unrelated rows in filtered reruns or write reruns to a separate study. Test both the wrong-symbol rejection and the resume cases against a temporary results directory. [Pair job setup](robust.py#L77) · [Study resume](photo_study.py#L126)

### Lower-priority carryover

The exit-bar adverse move can still be present in the account drawdown and absent from the exported trade's `mae_pts`. Apply the same documented path assumption to the export before using that column to tune stops. The last targeted check found no mismatch among the **59 intrabar target exits** in the 30-minute, 3R MNQ baseline. [Trade export](engine/core.py#L363) · [Exit-bar drawdown](engine/core.py#L427)

Fix daily signal timing and benchmark date alignment before ranking the photo strategies. Rerun B01 after synchronizing its bars, extending its warm-up, and applying stress to both legs.

## Photo-study recheck

**Verified** November 22, 2026, on the revised `audit-fixes` working tree.

All **109 tests passed**. All **94 updated study rows** matched their saved reports and the current code and data fingerprints. **32 of 94** met the study's criteria. I independently reproduced the walk-forward trade CSVs and stress tables for A01 MNQ cash session, A10 MGC full session, and B01 MGC full session. [Updated study rows](results/PHOTO_STUDY/study_rows.csv) · [Updated study report](PHOTO_STUDY_RESULTS.md) · [A01 rerun](results/20261122_204647_ALL_a01_rsi_ema_vwap_MNQ/ROBUSTNESS_REPORT.md) · [A10 rerun](results/20261122_204647_ALL_a10_faber_10_month_MGC/ROBUSTNESS_REPORT.md) · [B01 rerun](results/20261122_204647_ALL_b01_pairs_gold_futures_vs_spot_MGC/ROBUSTNESS_REPORT.md)

### Verified fixes

- **Daily signals and MAE.** GC now has one bar per trading day, with **13 rolls at the open** and **37 inside a bar**. Full-history A10 on MGC reproduced **+$104,129.87**, and its walk-forward sample was too small to score. The regression for exporting the exit-bar adverse move in `mae_pts` now passes. [Resampling](engine/data.py#L246) · [MAE regression](tests/test_audit4.py#L185)
- **Gold pair.** All **26,684** hourly closes matched common source-minute prices. Trade P&L reconciled to its cost components, both-leg stress widened the spot spread, and the CLI rejected MNQ as the primary leg. B01 reproduced **−$5,338.81** over full history and **−$1,937.40** out of sample. The saved report shows zero folds flagged for short warm-up. [Pair alignment](engine/pairs.py#L28) · [B01 stress rerun](results/20261122_204647_ALL_b01_pairs_gold_futures_vs_spot_MGC/stress/stress_report.txt)
- **Cash-session and resume behavior.** NAS100 cash-session bars contained **zero dates** the project's exchange calendar marks closed. A13 held **zero overnight positions** across **25,176 trades** on the supplied data. The tests also verified that failed study rows retry, valid rows use matching fingerprints, and filtered reruns preserve unrelated rows. [Session filter](engine/data.py#L221) · [Resume regression](tests/test_audit4.py#L152)

### 1. Size opening fills using the opening contract's adjustment

**High priority.** Five-minute resampling kept the old contract's open and the new contract's adjustment when a roll fell inside the bar. In the reproduction, the bar opened on contract A at **100 raw** and **120 adjusted**, then rolled to contract B with a zero adjustment. A $1,000 opening order at $1 per point bought **8 contracts** on the five-minute data and **10** on the one-minute data. Replaying default MGC daily photo strategies with the opening adjustment changed no trade quantities in that sample.

Use the adjustment in force at the execution timestamp. For an opening fill, preserve the opening adjustment or derive the raw fill from the old contract's raw open plus the fill's price offset. Apply this to notional and leverage sizing. Test both order sizing and the benchmark at an opening on a mixed-contract bar. [Resampling](engine/data.py#L246) · [Engine sizing](engine/core.py#L308) · [Benchmark sizing](photo_study.py#L57)

### 2. Protect intrabar roll metadata from strategy edits

**High priority.** A synthetic strategy's `prepare()` set `roll_inside=False`. It passed the look-ahead check and avoided a rollover fee. The field controls costs and is absent from the protected-column list.

Protect `roll_inside` and other execution metadata, including the fields used to convert adjusted fills to raw prices. Read those values from the unmodified execution frame. Test that changing, dropping, or creating a false roll flag cannot change the roll count or P&L. [Protected columns](engine/core.py#L36) · [Roll charges](engine/core.py#L580)

### 3. Build cash-session folds from eligible bars

**Medium priority.** In the first A01 NAS100 cash-session fold, the report counted **257 OOS days** while the strategy scored **251**. Across the study, **15 rows** reported an OOS end date later than their full-history cash-session run's last eligible bar. The result affects reported periods and per-day walk-forward efficiency.

Use the session-filtered frame to choose fold boundaries and denominators. Test a dataset whose last full-session bar falls on a day excluded from the cash session, and reconcile every fold's date count against its actual scored bars. [Fold inputs](robust.py#L149) · [Fold report](engine/walkforward.py#L110)

### 4. Label the benchmark's fixed notional reset per fold

**Medium priority.** The OOS benchmark closes and opens a new fixed-notional position at every fold boundary, including between consecutive folds. For A01 NAS100 cash session, that reported **+$144,174.60** and **−$32,665.71** drawdown. Holding continuously over the same dates gave **+$253,118.36** and **−$71,002.14** drawdown.

If the reset is intentional, label it as a per-fold fixed-notional benchmark and state that sizing and execution costs reset at each fold. If the comparison is meant to represent continuous buy-and-hold, keep the position through consecutive scored folds and close it at actual gaps. Test both consecutive folds and folds separated by a gap. [Benchmark](photo_study.py#L42) · [Scored windows](photo_study.py#L122)

### 5. Handle missing closing bars in A13

**Medium priority.** A13's default two-bar hold can still cross sessions when closing data are missing. With a valid signal and a gap after **15:48 ET**, the synthetic position opened at 15:48 and closed at **09:31 ET the next day**. The flat rule depends on a near-close bar arriving.

Define how to handle unfillable session exits and expire pending intraday entries at the session boundary. Mark trades with missing closing data explicitly so the report can distinguish an unverified close from a confirmed intraday fill. Test an early cutoff in the data and a session boundary with a pending order. [A13 exit logic](strategies/photos/a13_order_flow_imbalance.py#L49)

Address roll-bar sizing and roll metadata first, then reconcile the cash-session fold dates and benchmark labels before comparing strategy rankings.

## Verification after the fifth revision

**Verified** November 22, 2026, on the revised `audit-fixes` working tree.

All **121 tests passed**. I reconciled all **94 study rows** against their saved reports and current fingerprints. All **361 scored walk-forward folds** had matching day counts, and **32 of 94** runs met the study's stated pass criteria. Fresh A01 NAS100 and A13 MNQ runs reproduced the saved trade and stress CSVs exactly. The fold files matched after parsing parameter values. [Study rows](results/PHOTO_STUDY/study_rows.csv) · [A01 rerun](results/20261122_211314_ALL_a01_rsi_ema_vwap_NAS100/ROBUSTNESS_REPORT.md) · [A13 rerun](results/20261122_211314_ALL_a13_order_flow_imbalance_MNQ/ROBUSTNESS_REPORT.md)

### Five fixes verified

| Previous issue | Verified behavior |
|---|---|
| Opening fill on a bar with an intrabar roll | Both 1-minute and 5-minute data bought **10 contracts** and charged one roll in the original reproduction. |
| Strategy could overwrite roll metadata | Setting `roll_inside=False` now fails the look-ahead check with an explicit message. The regression suite also covers removing and creating execution fields. |
| Cash-session folds counted ineligible dates | A01's first NAS100 cash-session fold now counts **251** eligible days. Every scored fold matched its actual day count. |
| Benchmark reset at adjacent folds | The A01 NAS100 cash-session benchmark used one continuous position, with **+$253,118.36** net P&L and **−$71,002.14** drawdown. |
| A13 missing closing bars | The original missing-bars scenario now exits at **09:30 ET the next day** and records one `session_gap_exit`. The tests also cover expiration of a pending intraday entry at the day boundary. |

[Fifth-revision regression tests](tests/test_audit5.py)

### 1. Flag capital exhaustion and define the behavior of an account-constrained run

**High priority for account simulations.** The A12 MGC full-session walk-forward began with **$100,000**, first ended a day below zero on **July 22, 2022**, and opened **753 additional trades** after that date. Its lowest day-end equity was **−$38,115.13**, and it ended at **−$27,415.63**. The engine's unconstrained research model permits this, so the subsequent fills do not represent trades the stated account could fund.

Report the first capital breach and label unconstrained results explicitly. For an account-constrained run, define when new orders stop and how existing positions are liquidated under the chosen model. Add a regression with a loss larger than the remaining capital and a subsequent entry signal. [A12 equity data](results/PHOTO_STUDY/full/20261122_210536_ALL_a12_volatility_squeeze_breakout_MGC/20261122_210602_walkforward_a12_volatility_squeeze_breakout_MGC/walkforward_oos_daily_equity.csv) · [A12 trade data](results/PHOTO_STUDY/full/20261122_210536_ALL_a12_volatility_squeeze_breakout_MGC/20261122_210602_walkforward_a12_volatility_squeeze_breakout_MGC/walkforward_oos_trades.csv)

### 2. Correct the out-of-sample drawdown summary

**Reporting.** The fix report says all 67 comparable runs had smaller drawdowns than buy-and-hold. The data show **64 of 67** had smaller drawdowns and three had larger ones. All 67 earned less absolute OOS P&L than buy-and-hold.

| Run | Strategy max drawdown | Buy-and-hold max drawdown |
|---|---:|---:|
| A05 MGC full session | −$38,117.17 | −$36,298.14 |
| A09 MNQ cash session | −$25,592.00 | −$23,789.00 |
| A12 MGC full session | −$138,932.38 | −$42,099.58 |

Generate the drawdown comparison counts from the study rows, using only rows with both drawdown figures. [Fix report claim](FIX_REPORT.md#L163) · [Study rows](results/PHOTO_STUDY/study_rows.csv)

### 3. Update exported risk multiples after intrabar roll charges

**Reporting and risk metrics.** A synthetic trade entered with **$1 initial risk** and closed at a stop inside a roll bar. The one-minute and five-minute runs both charged the roll and reported **−$5 final P&L**. The five-minute run exported **−3R** because it calculated `r` before applying the roll charge. The correct value is **−5R**. All **6,152** saved A12 out-of-sample trades reconciled against their initial risk.

Calculate `r` from final net P&L after the last cost adjustment, including roll fees added after the trade record is created. Test an intrabar exit with a roll charge and verify both the exported multiple and the summary's average R. [Trade finalization](engine/core.py#L367) · [Intrabar roll adjustment](engine/core.py#L454)

## Verification after the sixth revision

**Verified** November 22, 2026, on the revised `audit-fixes` working tree.

All **125 tests passed**. All **94 study rows** matched their current fingerprints and saved reports. All **355 scored walk-forward folds** had matching day counts, and **32 of 94** runs met the study's stated criteria. I independently reran A12 on MGC in constrained mode. Its walk-forward folds, OOS trades, and stress CSVs matched the saved study files exactly. [Study rows](results/PHOTO_STUDY/study_rows.csv) · [Fresh A12 rerun](results/20261122_215346_ALL_a12_volatility_squeeze_breakout_MGC/ROBUSTNESS_REPORT.md)

### Three original fixes verified

- **Capital exhaustion on the real A12 run.** The unconstrained full-history replay took **2,460 trades** and lost **$140,674.27**. The constrained replay took **1,399 trades**, lost **$100,205.00**, and opened zero trades on later days after the August 23, 2021 breach. Its walk-forward breached on **July 22, 2022**, ended with **−$71.72 equity**, opened zero trades on later days, and skipped **six** later folds. [A12 study report](results/PHOTO_STUDY/full/20261122_214135_ALL_a12_volatility_squeeze_breakout_MGC/ROBUSTNESS_REPORT.md)
- **Drawdown summary.** The updated report now matches the data. **64 of 67** comparable runs had smaller OOS drawdowns than buy-and-hold and three had larger ones. All 67 earned less OOS absolute profit. [Updated comparison](PHOTO_STUDY_RESULTS.md#runs-that-passed-all-key-checks-32-of-94-with-buy-and-hold-for-comparison) · [Comparison counter](tools/photo_report_tables.py#L15)
- **Intrabar rollover R-multiple.** The original synthetic position with **$1 initial risk** and **−$5** final P&L now exports **−5R** after the roll charge. [Roll adjustment](engine/core.py#L459) · [Regression](tests/test_audit6.py#L61)

### 1. Apply account constraints to the pairs engine

**High priority.** The pairs engine reports `account_model = constrained` through the shared summary, but its broker accepts new positions after capital exhaustion. In a synthetic pair run on a **$50,000** account, a **$60,000** loss left **−$10,000** equity. The engine then opened a second trade. The saved B01 study row had no capital breach, so this reproduction establishes a gap in the model without a measured effect on that row.

Give paired positions the same permanent breach state and liquidation policy as single-market positions. Cancel pending entries, liquidate both legs at the next executable common open, and refuse subsequent entries. Add a pair regression that asserts the breach timestamp, exit reason, and absence of entries after the breach. [Pair order acceptance](engine/pairs.py#L95) · [Pair execution loop](engine/pairs.py#L189)

### 2. Carry the capital-breach state across walk-forward folds

**High priority.** The walk-forward runner skips later folds only while the balance is at or below zero. In an end-to-end synthetic walk-forward, the February fold breached, then its forced liquidation left **+$20,000** after a price recovery. The March fold opened a new position and booked **+$20,000** because a fresh broker started with the recovered balance. That contradicts the constrained model's permanent stop policy.

Carry forward the breach state or timestamp as well as the account balance. Mark later folds as skipped even if the liquidation fill leaves a positive balance. Add a walk-forward test covering a below-zero mark followed by a positive balance at liquidation. [Walk-forward rollover of account state](engine/walkforward.py#L84)

### 3. Separate forced liquidation from strategy execution delays

**High priority.** Capital exhaustion schedules an ordinary close request, which obeys `delay_bars`. With a one-bar delay, a synthetic breach on bar 3 liquidated on **bar 5 at 80**. Bar 4 was the next open and traded at **20**. The delayed exit left **+$30,000** in the synthetic account. The documented model promises liquidation at the next open.

Give forced liquidation its own execution priority and enforce the next executable open. If liquidation latency is intended as a stress assumption, define and report it separately. Test a breach with strategy delay enabled and a rebound between the first and second opens. [Close scheduling](engine/core.py#L630) · [Close execution](engine/core.py#L584) · [Documented account model](PHOTO_STUDY_RESULTS.md#photo-strategy-study-results)

### 4. Show capital breaches in stress scenario tables

**Medium priority.** Individual scenario summaries record capital exhaustion, but the exported stress table omits it. A12 MGC's real **two-bar-delay** scenario breached on **October 13, 2022**, then ended with **+$2.75 equity** and refused **31,074** orders. The CSV shows **−$99,997.25 P&L** and omits the breach, so an ending balance alone cannot identify the event.

Include the account model, first breach date, and refused-order count in each stress row. Show a breach explicitly even if final equity is positive. Test the exported table using a scenario that breaches and subsequently recovers above zero. [Stress row construction](engine/stress.py#L63) · [A12 stress table](results/20261122_215346_ALL_a12_volatility_squeeze_breakout_MGC/stress/stress_scenarios.csv)

## Batched audit before regenerating the study

**Verified** November 22, 2026, on the revised `audit-fixes` working tree. The review covered the account state in both engines, handoff between walk-forward folds, execution delays, stress verdicts, saved Monte Carlo inputs, parameter selection, CLI input validation, and the study's rerun scope. I used targeted reproductions and screened the saved 94-run study artifacts.

### Verified account fixes and measured impact

All **129 tests passed**. I independently verified all four findings from the sixth revision. A constrained pair booked a $60,000 loss and refused the next entry. A synthetic February account breached and liquidated with $20,000 left, and March was skipped. Forced liquidation with a one-bar strategy delay filled at the next open of 20. A real A12 stress report now includes account model, breach date, and refused orders. [Regression tests](tests/test_audit7.py) · [A12 stress report with breach columns](results/20261122_220918_stress_a12_volatility_squeeze_breakout_MGC/stress_report.txt)

Using the saved **A12 MGC study plateau parameters**, a targeted replay showed the expected impact of the liquidation timing change. The baseline stayed at **−$100,041.81** and combined stress stayed at **−$100,010.21**. The one-bar delay result changed from **−$100,068.24 to −$100,082.24** and the two-bar delay from **−$99,997.25 to −$100,012.25**. The standalone stress report linked above uses the default parameters; this comparison used the parameters saved with the study. [Saved plateau and scenario results](results/PHOTO_STUDY/full/20261122_214135_ALL_a12_volatility_squeeze_breakout_MGC/ROBUSTNESS_REPORT.md)

### Fix together before refreshing the published results

| Priority | Issue and verified reproduction | Acceptance check and shortest validation |
|---|---|---|
| High | **Reopening a saved walk-forward can use the wrong starting capital for Monte Carlo.** The saved A01 NAS100 cash-session run started at **$100,000**, but the loader used the CLI default **$50,000** because it looks for `summary.json` and skips the capital in `walkforward_summary.json`. Daily replay then derived **+$83,301.70** from a saved run whose trades total **+$33,301.70**. Trade-based replay also uses the wrong capital for percent-of-capital statistics. [Saved-results loader](robust.py#L188) · [Daily P&L construction](robust.py#L173) | Replay the same saved folder. The sum of reconstructed daily P&L must match the saved OOS net, and risk percentages must use the recorded capital. Validate with saved artifacts and a fixture. |
| High for account-constrained reporting | **A breached account can still receive a positive robustness verdict.** Supplying a constrained result with a recorded breach and **+$15,000** final P&L produced a `PASS` for profitable OOS and combined stress. Both checks use P&L alone. A favorable liquidation fill can leave a positive balance after the strategy has permanently stopped. [Checklist](robust.py#L258) | Make survival explicit in constrained rankings and verdicts. Test a positive closing balance after a breach. Regenerate report verdicts from saved summaries where breach metadata exists. Replay only scenarios whose breach metadata is missing and whose paths can reach zero. |
| Medium | **Walk-forward accepts a zero-month step that hangs.** With a valid date range, `make_folds(days, 1, 0)` failed to return before a one-second alarm because the loop never advances its date. A date range outside the available history also crashes at `df.tday.iloc[0]`; a January 2020 MNQ stress request reproduced it. [Fold loop](engine/walkforward.py#L33) · [Date range loading](robust.py#L85) | Reject nonpositive window lengths and empty eligible date ranges with a clear error. Test at the CLI and the function boundary using tiny inputs. |
| Medium | **Daily Monte Carlo can silently produce identical paths.** With three daily observations and the default five-day block, all **128** synthetic simulations returned the same **+$10**. There is only one eligible block start, so increasing the simulation count adds no new sample paths. [Block sampling](engine/montecarlo.py#L27) | Reject or explicitly flag a block size that gives too few distinct starts. Verify an undersized series and a valid series with multiple possible starts. Only daily Monte Carlo outputs using unsuitable settings need regeneration. |
| Medium, performance | **Monte Carlo still retains completed batches.** `cum[:, -1]` is a view, so retaining it in `finals` keeps the entire cumulative matrix alive. A **12,000 × 3,500** bootstrap peaked at **672 MiB**. Copying that final column in an isolated replay reduced the process peak to **518.5 MiB**. [Monte Carlo batches](engine/montecarlo.py#L68) | Copy the retained column and benchmark several batches. Check that a seeded simulation still produces identical values. Existing numeric outputs can be retained when the parity test passes. |
| Policy check for optional objective | **The profit-factor objective silently discards qualifying no-loss settings.** A 40-trade setting with infinite profit factor and a 30-trade minimum returned `NaN`. The sweep then excludes it from the count labeled `with_enough_trades`. The photo study uses Sharpe. [Objective score](engine/metrics.py#L162) · [Sweep reporting](engine/sweep.py#L88) | Define how to rank a qualifying no-loss sample or report the reason it was excluded separately from minimum trade count. Verify with a synthetic grid using the profit-factor objective. |

### Validation scope for the next batch

1. Run the unit suite and the targeted boundary cases above together. The archived study stays a useful baseline with its original fingerprints.
2. For the liquidation change, screen the prior paths for potential capital exhaustion. With $100,000 initial capital, any path that reached zero must have at least $100,000 of drawdown. Among the saved stress tables, only **A12 on NAS100, MGC, and XAUUSD** crossed that screening threshold. The saved full-period sweep tables also flag candidate settings in **A12 MGC, A13 MNQ, and A05 XAUUSD**. A flagged drawdown is a candidate, not proof of a breach. Check actual breach metadata or rerun the flagged stage. Fold-level in-sample candidate paths are not all stored, so use targeted walk-forward reruns for affected candidate selections. [Study artifact index](results/PHOTO_STUDY/study_rows.csv)
3. Regenerate Monte Carlo from the existing saved trade and equity files. Generate verdict and report-only corrections from verified values. Run any affected configuration end to end once after the batch is stable.

The current resume fingerprint hashes shared engine and runner files for every strategy. A shared-code edit therefore marks unrelated rows stale as well. At the time of this review, **54 of 94** stored rows differed only in the code fingerprint. Preserve the old run's provenance and record targeted parity evidence separately before promoting a selective refresh. [Fingerprint calculation](photo_study.py#L93) · [Resume logic](photo_study.py#L180)

## Verification of the batched fixes

**November 22, 2026.** All **144 tests passed**, including the 15 new cases for the six earlier findings. I reviewed the current working tree, replayed saved inputs in scratch directories, and ran a one-month MNQ stress check. The 94-run photo study was checked against its saved archive.

| Earlier finding | Verification |
|---|---|
| Wrong starting capital in saved Monte Carlo | The CLI replayed the saved **A01 RSI/EMA/VWAP on NAS100, cash session** with the recorded **$100,000** starting capital. Across **1,679** daily equity observations, reconstructed P&L was **+$33,301.70** to the cent, matching saved out-of-sample P&L and the trade sum. [Saved walk-forward](results/PHOTO_STUDY/rth/20261122_222740_ALL_a01_rsi_ema_vwap_NAS100/20261122_222743_walkforward_a01_rsi_ema_vwap_NAS100/walkforward_summary.json) |
| Profitable verdicts after breach | With **+$15,000** booked P&L, the walk-forward profitability, double-commission and combined-stress checks all passed when the account survived and failed when a breach date was present. The study ranking also excludes verified breaches in the full history, walk-forward or combined stress. [Checklist](robust.py#L277) · [Ranking rule](tools/photo_report_tables.py#L37) |
| Zero-month hang and out-of-history dates | Nonpositive fold lengths are rejected. A real MNQ stress request for January 1–2, 2020 returned a clear no-data message. [Fold validation](engine/walkforward.py#L33) · [Data-range validation](robust.py#L96) |
| Daily Monte Carlo with too few block starts | Three days with a five-day block are rejected. A valid 40-day input with a five-day block reports 36 possible starts. [Daily Monte Carlo tests](tests/test_audit8.py#L127) |
| Monte Carlo memory retention | For **6,000 paths × 1,000 trades** in 60 batches, tracing allocations around the prior implementation and current implementation showed a peak drop from **48.17 MiB to 3.19 MiB**. Every seeded path's final P&L and drawdown matched. [Batch loop](engine/montecarlo.py#L84) |
| Undefined profit-factor objective | The sweep reports the minimum-trade count, number scored and reason the no-loss settings were excluded. The independent profitability percentage still needs the denominator correction below. [Sweep report](engine/sweep.py#L90) |

**Saved study reconciliation.** All **94** strategy, market and session keys matched the archive. All shared result columns matched, with differences in report paths, run times and code fingerprints. **32 of 94** still pass the study rule. Starting capital and ending P&L reconciled in all **68** nonempty walk-forward equity files. All **355** scored folds matched their expected trading-day counts. I re-simulated all **136** saved bootstrap and shuffle summaries from their trade CSVs and matched both the current and archived summaries exactly. I reconciled the study's combined-stress net and breach counts with all **707** saved scenario rows. The A12 stress runs recorded breaches in **7** MGC, **3** NAS100 and **1** XAUUSD scenarios. [Current study rows](results/PHOTO_STUDY/study_rows.csv) · [Prior study rows](results/PHOTO_STUDY/archive/study_rows_review7.csv)

**Targeted stress replay.** Default MNQ opening-range breakout on one-minute full-session data in April 2024 produced **22 trades** per scenario. Baseline net was **+$2,437.50** and combined execution stress net was **+$1,606.50**. The worst drawdown in combined stress was **−$1,690.50**. None of the seven scenarios breached. Removing the ten best baseline trades left **−$4,936.50**. This sample exercises the reporting and execution stress paths over one month. [ORB strategy](strategies/orb.py) · [Execution scenarios](engine/stress.py#L32)

### Remaining issues found in the same pass

| Priority | Reproduction and impact | Fix and targeted acceptance check |
|---|---|---|
| Medium | **Daily Monte Carlo can sample across months with no walk-forward coverage.** Saved replay discards the trading dates and treats adjacent CSV rows as consecutive days. A11 Time-Series Momentum on NAS100 full session jumps directly from **January 29, 2016 to February 1, 2017** across **259** skipped trading days. Its real CLI report counts **944** five-day starts, including **12** that cross skipped folds. Across the study I found **five** such gaps in **three** runs. Blocks that cross a gap join P&L observations from different periods and can distort simulated risk. [Saved A11 folds](results/PHOTO_STUDY/full/20261122_223305_ALL_a11_time_series_momentum_NAS100/20261122_223307_walkforward_a11_time_series_momentum_NAS100/walkforward_folds.csv) · [Replay loader](robust.py#L220) · [Block sampler](engine/montecarlo.py#L33) | Preserve dates and walk-forward segment boundaries in the replay. Count and sample only starts inside a continuous eligible segment, or explicitly document and model those skipped days as flat if that is the intended account history. Recheck the saved A11 folder and a small split-series fixture. |
| Medium | **The sweep's profitability verdict uses the wrong denominator.** Three settings each had 40 trades. Two were profitable with infinite profit factor and one lost money with a finite score. The checklist reported **0.0% of combinations with enough trades** and failed the 60% test. The actual share was **66.7%**. All 94 saved Sharpe sweeps had zero settings that met the trade minimum but lacked a defined score. [Sweep percentage](engine/sweep.py#L96) · [Checklist label](robust.py#L283) | Calculate the profitability percentage over all settings meeting the minimum trade count. Keep the defined-score filter for ranking. Verify the synthetic case in both the sweep summary and checklist. |
| Low | **Saved daily replay rejects sparse trade histories even with usable daily data.** A scratch folder with one trade, six daily equity values and two-day blocks was rejected with “1 trades: nothing to simulate.” The same daily P&L series supports **five** starts in the simulator. [Saved replay trade gate](robust.py#L205) | Validate daily history and block length in daily mode. Keep the trade-count minimum for bootstrap and shuffle. Exercise the CLI with six days and one trade. |

These three checks can be validated with saved files and fixtures. The published study used trade bootstrap and shuffle, and its Sharpe sweeps are unaffected by the denominator issue. A full study rerun is unnecessary for these fixes. The shared-code resume fingerprint still invalidates rows broadly, so preserve the saved run provenance during targeted validation. [Study method](photo_study.py#L104) · [Fingerprint](photo_study.py#L93)

## Consolidated end-to-end audit

**November 22, 2026.** I reviewed data and roll construction, both execution engines, built-in strategies, parameter selection, walk-forward, Monte Carlo, execution stress, the one-second verifier, and study storage. All **144 existing tests passed**. I checked all **94 saved stress tables** and used targeted market replays and scratch fixtures for cases those tests miss. The code and the 94 published result rows were left as found. The three carryover items and the additional issues are below.

### Execution, data, and strategy behavior

| ID | Verified issue | Fix and shortest verification |
|---|---|---|
| E1 · High | **The look-ahead verdict overstates what ran, and the standalone CLI publishes after a failure.** A fixture used the next close on the first row of 300,001 bars. The robustness gate returned `passed` because it examined only the last 300,000 bars. Checking the first 16 detected the future read. For larger grids the gate also samples at most 40 parameter sets. In a separate fixture the default `run.py` entry point flagged a future-close feature, then wrote a normal report with six trades, **+$85** and **35.0 PF**. [Robustness gate](robust.py#L109) · [Standalone runner](run.py#L61) | Make the standalone runner fail by default before writing results, with any explicit override recorded. Show the actual date range and settings checked. Regress the flagged early-history case and the normal output path after a failure. Cover full-history guarded trade decisions for each setting whose results will be trusted, or make sampled coverage explicit. |
| E2 · High for ORB on incomplete history | **ORB orders can fill at the entry cutoff, and a missing closing segment can defer exit by an extra bar.** A one-minute fixture filled at the specified **11:30 ET** cutoff before the strategy could cancel the order. In a missing-afternoon fixture the next executable bar started at **18:00 ET**, but exit waited until **18:01** because the ORB position lacks the broker's intraday flag. In the full saved-market coverage replay with default MNQ parameters, **0 of 1,430 trades** showed either symptom. [ORB lifecycle](strategies/orb.py#L48) · [Order processing](engine/core.py#L516) · [Session-gap handling](engine/core.py#L575) | Apply an absolute entry deadline before trigger evaluation and give ORB positions an explicit session expiry. Test a trigger exactly at 11:30 and a missing close followed immediately by the next session's first open. Check an early close, a delayed fill, and the existing default MNQ trade list. |
| E3 · High for A07 futures | **Money Flow Index signals can change when future futures rolls are appended.** MFI multiplies adjusted typical price by volume, so the weights depend on future additive back-adjustments. On MNQ cash-session bars through April 30, 2025, the grid setting `mfi_len=5, mfi_entry=20` saw its April 10 MFI move from **19.9626 to 20.0067** when the later **1,206.75-point** rebase was removed. The isolated replay moved from **56 trades and +$17,136** to **55 trades and +$14,856** using identical raw prices and dates. [MFI calculation](engine/indicators.py#L71) · [A07 rule](strategies/photos/a07_mfi_reversal.py#L14) | Use an as-of or rebase-invariant futures MFI. For example, classify the direction of price moves on the adjusted path and derive money-flow weights from a contemporaneous raw typical price. Verify that appending a later roll leaves earlier signals unchanged. Replay only affected A07 futures rows with the chosen definition. |
| E4 · High for early GC history | **Some GC roll spreads use observations from later rolls.** All **eight** long-gap fallback rolls use two to four future roll observations. The January 31, 2016 switch uses four future observations. These estimates change the historical price move at the switch itself, so positions crossing a switch and signals around it can change. The source contains only a stitched GC series, so the actual spread at these switches remains unknown. [GC fallback calculation](engine/data.py#L91) · [Saved roll estimates](cache/GC_rolls.csv) | Use same-time overlapping quotes where available. For the earliest switches, use a documented causal proxy or mark the spread uncertain. Run a sensitivity comparison on GC/MGC paths crossing the eight flags before republishing derived returns or benchmarks. |
| E5 · High if modeling executable account limits | **A gap below zero can recover by the close and leave a constrained account trading.** The fixture opened at **−$500** marked equity, closed at **+$500**, and recorded no breach. Both engines trigger at closes only. In the single-market engine, a next-session gap exit can also take precedence over an already scheduled insolvency exit and mask the cause. [Single-market equity and breach](engine/core.py#L568) · [Pair breach](engine/pairs.py#L224) | Explicitly label close-only checks as the current model. For an account intended to react to observable breaches, define ordering for opening gaps, protective orders and forced liquidation, then test an opening breach that recovers, a close breach at a session boundary, and terminal liquidation costs. Require separate validation before using OHLC-based adverse estimates to liquidate inside a bar. |
| E6 · Medium for B01 risk | **Pair drawdown can miss all losses between hourly marks.** A synthetic hour with unchanged open and close, unchanged leg B and an observable adverse move on leg A reported **$0 drawdown** versus a **$500** interim loss. On the **93 saved B01 OOS trades**, marking common minute opens and closes with recorded positions and rolls gave **−$4,442.37** drawdown versus the saved **−$4,434.07**, while final equity reconciled to **$98,062.60**. [Pair equity](engine/pairs.py#L236) · [Saved B01 result](results/PHOTO_STUDY/full/20261122_223638_ALL_b01_pairs_gold_futures_vs_spot_MGC/ROBUSTNESS_REPORT.md) | Mark pair risk on synchronized observations at the desired monitoring frequency, or label the statistics as hourly open/close estimates. Use the existing pair ledger for a minute-mark verification and test joint exposures on a known adverse move. |
| E7 · Medium for pair settings | **The pair ignores the sign of a negative hedge ratio and the leverage setting.** At `beta=-1`, the fixture still shorted leg B, producing **−$100** on that leg after it rose. The documented `A − beta × B` formula requires long B for this long spread. The same fixture accepted **$4,000 gross exposure** on **$1,000 equity** with `max_leverage=1`. Default B01 showed no negative beta in the sampled study history. [Pair sizing and leg direction](engine/pairs.py#L143) · [Leverage setting](engine/core.py#L90) | Implement signed hedge direction or reject unsupported beta values. Define and enforce leverage against both legs' gross exposure when configured. Test negative beta and a gross-cap boundary; baseline B01 uses no explicit leverage cap. |
| E8 · Medium for standalone A13 | **The documented one-minute cash-session strategy can trade before the cash open.** With the CLI's default full session, an April 2024 MNQ replay entered **123** trades before 09:30 ET. Full session had **731 trades and −$2,914** versus **142 trades and −$666** on cash-session input. A separate fixture removed one minute, and the regression used a **13.5-point** two-minute move as a one-minute sample. The saved study used the required session and its NQ cash-session frame had no same-day missing-minute transitions. [A13 regression](strategies/photos/a13_order_flow_imbalance.py#L23) · [CLI defaults](robust.py#L370) | Enforce the required timeframe and session and exclude samples whose timestamps are more than a minute apart. Test a full-session invocation and a missing intraday minute. |

### Stress, robustness, and report accuracy

| ID | Verified issue | Fix and shortest verification |
|---|---|---|
| R1 · High for the published shortlist | **The “combined worst-case” label and passing check can hide a losing individual scenario.** In **62 of 94** saved runs another scenario did worse. In three runs the combined scenario earned money while an individual scenario lost. One is a current shortlist entry, **A06 Rubber Band on MNQ cash-session bars**, at **+$17,412.50** combined versus **−$6,549.50** with a two-bar delay. [Checklist](robust.py#L308) · [A06 saved scenarios](results/PHOTO_STUDY/rth/20261122_223045_ALL_a06_rubber_band_MNQ/stress/stress_scenarios.csv) | Label the existing scenario “combined execution stress.” Show the actual worst tested scenario, net and breach. If the shortlist is meant to require survival under every tested scenario, apply that rule to the saved tables and regenerate the shortlist. |
| R2 · Medium | **Market-stress reports attribute all P&L to the exit date and label partial months as full rolling windows.** A position gained **$600** during the COVID window and realized it after the window. The report showed **$0** for that period. A separate input covering January 31 through March 1 produced a “worst rolling 3 months” result from three dated observations. [Stress periods and stretches](engine/stress.py#L92) | Use marked daily equity changes for period P&L, or label exit-date attribution explicitly. Show actual dates and mark incomplete rolling windows. Cover a position spanning a period boundary and a short history touching three calendar months. |
| R3 · Medium | **Walk-forward efficiency weights short folds as heavily as long folds.** The report calls this “profit per day,” but averages each fold's daily rate. A03 on XAUUSD cash-session bars shows **0.295**, versus **0.755** when calculated as total P&L divided by total scored days on each side. This crosses the checklist's **0.5** threshold. [Efficiency formula](engine/walkforward.py#L131) · [Saved A03 report](results/PHOTO_STUDY/rth/20261122_222922_ALL_a03_williams_ema_vwap_XAUUSD/ROBUSTNESS_REPORT.md) | Name the current metric as fold-weighted, or use total P&L per scored day if that is the intended verdict. Verify unequal folds and recalculate the affected verdicts directly from fold CSVs if the definition changes. |
| R4 · Medium | **The double-commission verdict uses the instrument default instead of the tested commission.** The check disappeared on a NAS100 run configured with a positive commission, and appeared on MNQ with explicitly zero commission. [Commission scenario](engine/stress.py#L40) · [Checklist condition](robust.py#L316) | Use the effective cost from the stress job or exported baseline. Test a zero-cost override on MNQ and a positive override on NAS100. |
| R5 · Medium for cost attribution | **The reported spread cost uses the opening spread for later fills.** A constant-midpoint fixture with a **1-point opening spread** and **4-point closing spread** paid **$250** across entry and final exit but reported **$100** in `spread_usd`. Trade net correctly reflected the executed prices. [Spread-attribution helper](engine/core.py#L318) · [Final exit](engine/core.py#L647) | Use the closing quote for a known close and the opening quote for a known open. Document any estimate for an intrabar fill whose contemporaneous spread is unavailable. Check reported cost versus execution at two different quoted spreads. |
| R6 · Medium for fill verification | **Partial one-second data can be called a resolved disagreement.** A fixture supplied a single entry-second bar and no tape through the requested flat time. The verifier assigned an exit of `end`, **+$10** and a resolved `disagree` verdict. [Replay fallback](tools/verify_orb_fills_1s.py#L72) | Establish coverage through a definitive exit or flag the replay as unresolved with blank replay P&L. Test partial tape as well as completely missing data and same-second ties. |
| R7 · Low | **Single-day reports print unusable annualized figures.** A one-day test earning **10%** from one trade reported **10,000,000,000% annualized** and **1,000,000,000 trades/year** because elapsed years is floored at `1e-9`. [Summary annualization](engine/metrics.py#L78) | Return a missing annualized figure for a zero-day date span or define elapsed exposure at a finer resolution. Test one-day and multi-day reports. |

### Input validation, saved results, and performance

| ID | Verified issue | Fix and shortest verification |
|---|---|---|
| I1 · Medium | **Eligibility is checked before session filtering.** NAS100 on December 5, 2018 had **930 raw bars** and **zero eligible cash-session bars**. The stress command returned successfully and exported eight **$0** scenarios rather than reporting that no backtest ran. [Job setup](robust.py#L83) · [Cash-session filter](engine/data.py#L221) | Validate eligible bars in the requested market, dates and session before look-ahead or output. Test the recorded date, a valid no-trade day, and a short matched pair window. |
| I2 · Medium | **Invalid Monte Carlo parameters can return plausible but meaningless risk estimates.** `skip_pct=101` produced zero median P&L and zero probability of loss, `haircut_pct=120` turned a $100 gain into a $20 loss, and `n_sims=0` crashed when concatenating an empty batch list. [Monte Carlo validation](engine/montecarlo.py#L65) · [CLI options](robust.py#L386) | Require positive simulation counts, finite positive starting capital, finite P&L, and percentages in `[0, 100]`. Return clear errors at the CLI and simulator boundary. Test the three inputs above and both legal percentage endpoints. |
| I3 · Medium for provenance | **Concurrent runs can overwrite study rows or share a report directory.** A scratch replay wrote another completed row after the first process had read its initial CSV. The first writer's subsequent save erased that unrelated row. Allocating two runs with the same strategy, market and second produced the same output path. [Study upsert](photo_study.py#L208) · [Robustness output path](robust.py#L59) · [Standalone output path](engine/report.py#L16) | Use unique per-run directories and serialize the study index read/merge/atomic-write step. Test two concurrent writers with different keys and two same-name runs started together. Preserve the current archive during migration. |
| I4 · Medium, performance | **Worker loading and resampling can exceed the memory assumption used by automatic parallelism.** In a single process, loading the 14 frame combinations used by the study peaked at **2,633 MiB RSS** on this Mac, with **145 MiB** of retained frame arrays by pandas' shallow measurement. The worker default budgets **1.5 GB per process**, and baseline, sweep, walk-forward and stress maintain separate frame/preprocessing paths. The observed peak includes temporary loading and pair assembly. [Frame cache](engine/parallel.py#L44) · [Worker selection](engine/parallel.py#L114) | Profile concurrent cold starts by market and timeframe before choosing a worker count. Reduce peak allocations and repeated loads, especially in pair alignment. Verify numeric parity with the current results and measure both cold peak RSS and elapsed time. |

### Three open findings carried forward from the prior check

| ID | Verified issue | Fix and shortest verification |
|---|---|---|
| C1 · Medium | **Saved daily Monte Carlo samples across skipped walk-forward periods.** Five gaps appear in three study runs. For A11 on NAS100 full session, **12 of 944** reported five-day starts crossed skipped folds, including a gap of **259 trading days**. [Daily replay loader](robust.py#L220) · [Saved A11 folds](results/PHOTO_STUDY/full/20261122_223305_ALL_a11_time_series_momentum_NAS100/20261122_223307_walkforward_a11_time_series_momentum_NAS100/walkforward_folds.csv) | Retain the trading dates and eligible segment boundaries. Sample within continuous segments, or explicitly represent the skipped period as flat days if that matches the account history. Test with the A11 folder and a split-series fixture. |
| C2 · Medium | **Profitability uses the scored subset while the checklist claims to count all settings with enough trades.** Two profitable infinite-PF settings and one finite losing setting all qualified at 40 trades. The report claimed **0.0%** instead of **66.7%** and failed the 60% check. The saved Sharpe study had no trade-qualified undefined scores. [Sweep statistics](engine/sweep.py#L96) · [Checklist wording](robust.py#L283) | Measure profitability across all trade-qualified settings and use the defined-score subset to rank. Regression-test the three settings and the resulting checklist status. |
| C3 · Low | **Saved daily Monte Carlo rejects a valid daily history with one trade.** Six recorded daily equity values supported **five** two-day block starts, yet saved replay refused to run. [Saved replay trade gate](robust.py#L205) | Validate equity history and block length for daily mode. Apply the two-trade minimum to trade bootstrap and shuffle. Test the saved-folder entry point with six days and one trade. |

### Validation after fixes

1. Batch these changes before regenerating published results. Recalculate stress labels, shortlist policy, walk-forward efficiency and other report-only changes from saved tables where the inputs exist. Test optional CLI paths and concurrent writes with scratch fixtures.
2. Replay only strategy, market and stage combinations whose execution inputs or decisions change. Start with A07 futures, historical GC/MGC around the eight uncertain rolls, and B01 risk marks. Include default MNQ ORB and the exact cutoff/gap fixtures as controls. If account rules change, screen saved paths for possible breaches and rerun the affected stages.
3. Compare trades, equity and the affected metrics with the preserved archive before replacing results. The current shared-code fingerprint may schedule all rows on resume, so use explicit targeted runs and retain their provenance while validating the batch. [Saved study](results/PHOTO_STUDY/study_rows.csv) · [Archive](results/PHOTO_STUDY/archive/study_rows_review7.csv) · [Resume fingerprint](photo_study.py#L93)

## Verification after the ninth revision

**November 23, 2026.** All **188 tests passed**. I reconciled all **94 photo-study rows** and **373 timeframe-study rows** against their saved walk-forward net P&L, combined stress P&L, worst stress scenario and breach counts. Both indexes had zero failed runs or duplicate keys. The 94 overlapping configurations matched on full-history and OOS net, worst stress net, walk-forward drawdown, selected settings, pass counts and fingerprints. The current ranking yields **27 of 94** and **47 of 373** passes. None of the 47 single runs averaged ten trades per month over either the full history or the scored OOS span. I used saved data, fixtures and targeted replays for this review. [Photo-study index](results/PHOTO_STUDY/study_rows.csv) · [Timeframe index](results/TIMEFRAME_STUDY/rows.csv) · [Revision tests](tests/test_audit9.py)

### Verified changes from the 22-item audit

| Earlier items | Verification and remaining scope |
|---|---|
| E1, E2 | The direct early-history future-read case is detected and the standalone runner rejects a detected failure. The ORB cutoff test passes when the final pre-cutoff bar is present and the next-day exit uses the first new-session open. A default full-history MNQ ORB replay produced **1,430 trades and +$53,714.50** with zero trades crossing sessions. The April 2024 stress check reproduced **22 trades** in each of seven scenarios, **+$2,437.50 baseline** and **+$1,606.50 combined**. Open cases for sparse indicators and missing cutoff bars are below. |
| E3, E4 | MNQ A07 now gives the same April 10, 2025 MFI (**20.006747**) with or without the later rebase, and both targeted replays yield **55 trades and +$14,856.00**. I checked the eight historical GC fallback flags, including zero spread on the first uncertain roll, and all 22 spot-proxy rolls used a spot opening timestamp matching the roll timestamp in the saved data. The archive comparison found **23** full-history net changes, all on MGC. [GC adjustments](cache/GC_rolls.csv) · [Prior photo-study index](results/PHOTO_STUDY/archive/study_rows_review8.csv) |
| E5–E8 | Tests cover a held-position opening breach, a liquidation at a session boundary, both pair-leg directions, the pair leverage cap, and A13 cash-session and missing-bar handling. B01 still has **93 OOS trades and −$1,937.40** net. Its more conservative pair drawdown is **−$4,566.20**, previously **−$4,434.07**. A known opening mark immediately after a new entry can still be missed, as shown below. [Pair risk and fills](engine/pairs.py#L210) |
| R1–R3 | A06 MNQ cash now leaves the shortlist because its worst scenario is **−$6,549.50**, despite combined stress of **+$17,412.50**. Named-period P&L uses equity changes and efficiency uses pooled daily rates. Remaining problems involve stress-only breaches, partial months, and interpretation of the efficiency ratio. [A06 stress tests](results/PHOTO_STUDY/rth/20261123_021152_ALL_a06_rubber_band_MNQ/stress/stress_scenarios.csv) |
| R4–R7 | Regression cases pass for effective double-commission eligibility, spread attribution on known closes, incomplete one-second tape, and single-day annualization. |
| I1–I4 | Session-empty and invalid Monte Carlo inputs are covered. Atomic study-index updates and unique output folders are tested. The frame cache is capped at two and the automatic worker budget has been raised. A measured repeated look-ahead check remains below. [Worker setup](engine/parallel.py#L44) |
| C1–C3 | A current A11 NAS100 full-session folder replayed through the CLI at **$100,000** starting capital. Its **948** daily observations were split into four segments, with **932** eligible five-day starts versus **944** before excluding cross-gap starts. Tests pass for the sweep denominator and one-trade daily replay. A gap without a fold row can still defeat the segment split. |

### Open issues and corrections for the next batch

| Priority | Verified evidence | Targeted fix and check |
|---|---|---|
| High · R1 | **A breach in an individual stress scenario is omitted by the survival mask.** The timeframe report says **52** runs hit $0, while the saved scenarios show **64**. The 5-minute count is **41** versus **35**, 15-minute **20** versus **15**, and hourly **3** versus **2**. The daily index also has a third breached configuration, A12 XAUUSD, which breaches only in an individual stress. The 47- and 27-run shortlist counts are unaffected on these artifacts because those scenarios also lost money. A fixture with positive worst stress P&L, one individual breach and 12 of 13 checklist passes still qualified, though. [Survival and ranking functions](tools/photo_report_tables.py#L25) · [Published timeframe count](TIMEFRAME_STUDY_RESULTS.md#short-answer) | Include `stress_scenarios_breached` in the shared survival predicate and require zero breaches for the shortlist. Regenerate the figures from the saved stress tables and test a breach followed by recovery to positive P&L. |
| High · E1 | **Sparse look-ahead in `prepare()` can still pass the gate.** A 200-bar fixture set a trigger only at row 60 using row 61's close. The full-period default check passed. A cut at exactly 61 rows detected the leak, because the standard cuts left the earlier signals and their next close together or excluded both. [Prefix sampling](engine/core.py#L737) | Distinguish full-period guarded `on_bar` coverage from sampled checks of prepared features. Add checks at signal or decision boundaries and a strategy-level causal test for any feature used to make production decisions. Verify with the sparse fixture. |
| High · E5 | **A new position can consume all equity at the opening fill.** The breach check marks the account before entry execution. With **$500** capital and a **$600** opening commission, post-entry equity was **−$100** at the open but recovered to **+$1,100** by the close. No breach was recorded. The single-market and pair loops both evaluate the opening breach before new fills. [Single-market order of events](engine/core.py#L588) · [Pair order of events](engine/pairs.py#L235) | Define whether such fills are rejected or liquidated. Mark the known post-fill bid/ask and opening fees before allowing the position to continue, with fixtures for both engines. Screen actual paths for entry-cost breaches before rerunning selected configurations. |
| Medium · E2 | **The ORB entry deadline is still bypassed if the pre-cutoff minute is absent.** In a fixture with valid morning bars and no bars between **09:33 and 11:31 ET**, a resting order filled at **11:31**, after the **11:30** cutoff. Cancellation depends on a strategy callback from the last minute before the deadline. ORB also still infers timeframe from the median of the first 5,000 steps, so sparse or mixed-width bars can make that inference unstable. [ORB cutoff and timeframe inference](strategies/orb.py#L26) · [Entry trigger](engine/core.py#L523) | Give the broker an absolute entry expiry checked before fill evaluation. Use explicit timeframe and interval information for the strategy. Test 11:31 after a gap, cutoff on a coarse bar and the known one-minute control. |
| Medium · C1 | **Daily Monte Carlo can bridge an entirely absent fold.** An anchored one-month walk-forward with February data, no March data and April data numbered February and April consecutively. With two equity rows on each side, replay produced one four-day segment. The current fix catches explicit skipped folds, as demonstrated on the real A11 folder. [Fold numbering](engine/walkforward.py#L33) · [Segment detection](robust.py#L192) | Preserve the scheduled period ID or calendar bounds, including windows without bars. Require the replay to keep nonadjacent scheduled windows separate. Validate with an entirely absent month and existing saved folders. |
| Medium · R2 | **The stress report's “complete calendar month” rule is a date heuristic.** A fixture ending January 26 still printed a full January result through January 31. The code accepts starts on days 1–3 and ends on days 26–31, and internally missing months can become zero through resampling. [Complete-month filter](engine/stress.py#L129) | Verify coverage against eligible sessions or label the date cutoff as a heuristic. Exclude internally absent months or flag missing data, and test start, end and internal gaps. |
| Medium · R3 | **An almost-zero in-sample return makes walk-forward efficiency a weak pass criterion.** I reproduced Claude's A11 MGC cash example at **3,316.291**. Only **2 of 7** folds were scored, with **+$11.15** pooled IS P&L and **+$12,309.20** OOS net. The ratio formula is correct, but this is easy to read as evidence of repeatability and the result passes the current rule. [Current A11 fold data](results/PHOTO_STUDY/rth/20261123_023215_ALL_a11_time_series_momentum_MGC/20261123_023218_walkforward_a11_time_series_momentum_MGC/walkforward_folds.csv) | Publish coverage and the numerator and denominator next to the ratio. Decide the minimum credible coverage and in-sample rate for a passing verdict, or mark the ratio unavailable near zero. Recalculate from saved folds. |
| Medium · Timeframe cost report | **Before-cost P&L and friction both count futures roll slippage twice.** `costs` includes roll slippage debited directly from equity, and `slippage_usd` includes the same amount. Reconciliation of the saved OOS ledgers found **$7,658** of duplicate add-back across **149** single-market runs, including **$1,225** on 5-minute bars. Correcting the add-back changes zero signs in the before-cost profitability counts. Net P&L remains the saved ledger's actual value. [Cost aggregation](tools/timeframe_costs.py#L29) · [Roll fees](engine/core.py#L581) · [Published costs table](TIMEFRAME_STUDY_RESULTS.md#3-why-the-short-bars-fail-costs-per-trade) | Export commission, roll slippage and fill slippage as distinct components or subtract the overlap once. Validate on a known roll ledger and regenerate the report from saved trades. Treat the friction add-back as a diagnostic on the executed trades, separate from a simulation with zero execution costs. |
| Medium · Timeframe portfolio | **The generated portfolio is a sum of separately sized accounts, and the report understates how variable the actual sizing is.** The reported **+$220,933.43** and **33.4 entries/month** reproduce. Its 11 positions are counted across a day, while a sweep of recorded entry/exit bar timestamps found nine overlapping positions. Six positions were already open at the report's start, so the P&L includes inherited positions that the entry count omits. The reported maximum drawdown uses daily closes. The text says every trade has **$100,000** contract value, but a selected risk-sized A12 XAUUSD position had **$118,592.26** entry notional. The report already discloses selection using the same OOS results. [Portfolio aggregation](tools/timeframe_portfolio.py#L48) · [Report and exposure notes](TIMEFRAME_STUDY_RESULTS.md#7-getting-to-1015-trades-a-month-run-several-robust-strategies-together) | Label the drawdown frequency, carry-in and day-level position count. Compute aggregate gross exposure from quantities and actual marks. Use a capital-constrained, flat-start portfolio on an untouched period before treating the published frequency and dollar P&L as a single-account result. |
| Medium · Performance | **The full-period look-ahead gate repeats identical work inside `robust all`.** A three-month MNQ ORB run with two parameter sets spent **0.904 s** on the sweep check and **0.926 s** repeating the same dates and settings for walk-forward, out of **5.305 s** overall. Stress checked one already-covered setting again in **0.326 s**. [Pipeline calls](robust.py#L301) | Reuse passed coverage within one run for identical strategy, data, settings and parameters. Preserve independent checks for standalone commands and any setting outside recorded coverage. Use one real small-grid run to compare timing and output parity. |

### Rerun scope

The survival count, cost add-back, and efficiency or portfolio labels can be corrected from saved tables and ledgers. Use small fixtures for the remaining execution, look-ahead and replay boundaries. Rerun historically affected strategy or stress configurations only after checking the size of the impact. Rebuilding the entire daily and timeframe studies would add no evidence for those report-only changes.

## NQ and MNQ data audit for the five-minute scalper

November 23, 2026. Reviewed the one-contract replay with five-minute candle entries, a 50-period hourly EMA filter, a 20-point stop, and a 40-point target. The test windows were June 3, 2024 through December 31, 2025 and January 2 through August 14, 2026. [Original replay summary](results/20261123_093248_five_minute_candle_1h_ema_20_40/summary.csv)

- **Missing session.** The backtest had 551 of 552 expected cash sessions. All **390 cash-session minutes on June 17, 2026** are missing. The preceding tick file ends at about 03:03 UTC and the next starts at 22:00 UTC that date. The local one-second file also has zero cash-session records for any contract that day. The replay's existing list of days with missing close quotes did not flag this date because the list started from dates present in the file. Compare coverage with the expected calendar, flag the gap in each result, and repair it from same-contract history before replaying that date.
- **The one-minute exit model changes actual results.** A one-minute bar touching the stop and target defaults to the stop. I reran the same orders and account rules, using the local one-second highs and lows to determine which level was reached first whenever a minute touched both. For 2026 MNQ, eight exits reached the target first and 15 reached the stop first. The revised replay used the same number of trades and reduced the after-cost loss by **$964.00**. All inspected outcomes resolved to different seconds. Route this scalper's ambiguous exits through available sub-minute data and log the source and count of any remaining ambiguities. This check still uses modeled fills and costs. [One-minute exit rule](engine/core.py#L431)
- **MNQ is priced from NQ.** The all-contract file contains NQ futures only, and the engine maps MNQ to the same series. Each run applies the instrument's own multiplier and modeled costs. The two series of reported trades therefore share an underlying tape. Validate MNQ on native MNQ trades and quotes before treating these as measured MNQ execution results. The available local NQ top-of-book history ends in June 2025, and the separate TradingView NQ file starts in November 2026, so it supplies no overlapping external price verification for these windows. [Instrument mapping](engine/instruments.py#L33)
- **Minute bars reconcile on the observed test sessions.** Rebuilding every used minute from the local one-second file reproduced OHLC, volume, and contract on all **214,361** rows, including one closing quote minute per observed session. Cached raw prices matched their source throughout. New York conversion agreed with the raw timestamps, and no rolls occurred during the replay sessions. The 1,986,571-row source had zero duplicate or off-minute timestamps, malformed candles, off-tick prices, or nonpositive volumes. The blanket 100% front-versus-all-contract match in `DATA_REPORT.md` needs a qualifier. The all-contract front subset omits 6,151 holiday rows, and five shared rows differ in volume only. The sole volume difference during these test dates was at 08:30 ET on April 10, 2025, outside the replay hours. The matching local files originate from the same provider.

| Window | Market | Trades before → after | Original net | One-second exit sequencing net | One-second exit sequencing net excluding best 5% |
|---|---|---:|---:|---:|---:|
| 2024–2025 | NQ | 407 → 413 | −$9,886.50 | −$9,933.50 | −$26,639.00 |
| 2024–2025 | MNQ | 2,140 → 2,146 | −$9,967.00 | −$9,978.00 | −$18,456.00 |
| 2026 through Aug 14 | NQ | 505 → 505 | −$9,647.50 | −$9,647.50 | −$30,330.50 |
| 2026 through Aug 14 | MNQ | 3,628 → 3,628 | −$4,574.50 | −$3,610.50 | −$17,898.00 |

The one-second diagnostic altered the exit order only in minutes that touched both levels. It retained the original entry signals, one-contract limit, ending-time rules, starting equity, commissions, and slippage. Updated equity could change when the one-contract risk check stopped allowing entries.
