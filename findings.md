# Backtesting engine audit findings

**Reviewed commit** `882fbd7`  
**Audit date** November 22, 2026

For current open issues and acceptance checks, see [Remaining fixes after the second revision](#remaining-fixes-after-the-second-revision).

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
