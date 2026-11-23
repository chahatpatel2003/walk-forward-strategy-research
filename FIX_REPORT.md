# Fix report: response to `findings.md` (audit of commit `882fbd7`)

Date 2026-11-22. **Status: fixes applied, not yet committed, awaiting your review.**

**Method.** Every finding was first reproduced as a failing test in `tests/test_findings.py`. All 20 failed against the old code, matching the audit. Then each was fixed, and the old tests were kept.

**Result.** **51/51 tests pass** (the original 29, plus 1 updated look-ahead test, plus 21 regression tests). I then re-ran the audit's own reproduction commands on the real data.

Nothing in `T9/DATA` was modified.

## High priority

| Finding | Status | What changed | Proof |
|---|---|---|---|
| **Repeated `close()` restarts the delay** (669 MNQ exits at 00:01) | Fixed | `Broker.close()` keeps the first pending request. | Test `test_repeated_close_calls...`. Real data: exits at 00:00–00:59 NY are **0** with 1- and 2-bar delays. Stress "delay 1 bar" is now **−$3,139 vs baseline** (it was inflated by about $6k). |
| **ORB flatten not session-aware** (37 cross-day trades, exits at 18:01) | Fixed | New `engine/calendar.py`: exchange holidays, half days, and holiday futures sessions, all with a 13:00 close. ORB flattens 5 min before the session close, and closes immediately if a position survives into a new trading day. | The remaining 24 cross-day trades were all US-holiday sessions that close at 13:00. Now **0 cross-day trades** at every delay. |
| **Entry at the open after an intrabar exit** | Fixed | Bar processing now follows time order: open events, then inside-bar events. No entry fills in a bar after a held position exited inside it. | `test_no_entry_at_the_open_after_an_intrabar_exit` |
| **OCO picks the wrong breakout** (buy checked first) | Fixed (rule-based) | When several entries trigger in one bar, the trigger nearest the open is taken. These bars are counted in `notes.ambiguous_entry_bars`. | The audit's case (27 Aug 2021, 10:00 ET) now takes the **short**, matching the 1-second data; it's then stopped out. 1 ambiguous bar in 1,430 MNQ trades. |
| **Target awarded from a high reached before a limit entry** | Fixed | On the entry bar, a limit entry's target counts only if the bar *closes* through it. Market and stop entries use the high/low, which the path must reach after the entry. | `test_limit_entry_bar_cannot_award...` |
| **Look-ahead check gives false passes** | Fixed | (1) `prepare()` may not change price/engine columns; the engine refuses. (2) Every column `prepare()` produces is compared on truncated data. (3) `on_bar()` is replayed with guarded data: any read of a later bar raises. (4) Entries and exits up to each cut must not change. `robust.py` now checks **every** parameter set (up to 40), on the most recent 300k bars. | `test_lookahead_check_catches_overwritten_prices`, `..._future_reads_in_on_bar`, `test_prepare_may_not_change...`. ORB passes for all 17 parameter sets. |
| **XAUUSD spread stress makes impossible bars** (~42k bad bars at 2×) | Fixed | Each bar's whole bid side shifts down and ask side up by one amount, based on the wider of its open/close spread. | `test_widened_real_spread_keeps_valid_ohlc`. Real data at 2×: **0 invalid bars**. |
| **Walk-forward warm-up blocks scored trades; fresh capital per fold; month-end gaps; crash on empty OOS** | Fixed | Orders placed during warm-up are ignored (`Settings.trade_start_ts`), so warm-up only computes indicators. OOS folds run in order and carry the account balance forward. Fold boundaries are whole calendar months (no gaps, no overlap). An empty OOS list is handled. | `test_warmup_positions...`, `test_folds_from_a_month_end_start...`, `test_walkforward_with_no_valid_parameters...`. The audit's crash command now completes and reports "2 folds without valid parameters". |
| **Drawdown hides losses inside a session** | Fixed | The engine records equity at each bar's close **and** at its worst price while a position is open. Daily frames keep the day's low, high and largest intraday fall. Backtests and robustness windows both use this. | `test_intraday_drawdown_is_reported`, `test_drawdown_from_an_intraday_peak...`. Real data: summary drawdown **equals an exact bar-by-bar calculation** (MNQ −$5,999.00 both ways; minute-close-only would show −$5,978). |
| **Futures roll handling erases market moves / uses a later price** | Fixed (GC partly estimated) | **NQ:** spread = both contracts' **open of the roll minute** (all 22 rolls). **GC:** jump minus spot gold's move over the same minutes (22 rolls). Pauses under 4 h assume no move (20 rolls). Only the 8 weekend rolls before 2021 are estimated from neighbouring rolls. Method per roll in `cache/*_rolls.csv`. Unadjusted `raw_o/h/l/c` columns added, and the effect on %/level signals is documented. | Roll logs. Cache version bumped to 2 so old caches rebuild. |

## Medium priority

| Finding | Status | What changed |
|---|---|---|
| Futures target filled on an opening touch | Fixed | Gap fills at the open need the trade-through too (`test_target_needs_trade_through...`). |
| Spread-gap stop filled above every bid | Fixed | A stop never fills better than the bar's quotes; on a market-entry bar it uses the bid/ask open (`test_stop_never_fills_above_the_best_bid`). |
| Forced final exit with zero slippage | Fixed | It pays slippage (`test_forced_final_exit_pays_slippage`). |
| 1.5-contract futures fill | Fixed | Every size is rounded down to `qty_step` (`test_futures_quantity_is_whole_contracts`). New `notional_usd=` sizing. |
| No margin / buying power / volume checks | **Partly** | Optional `Settings.max_leverage` caps notional at equity × N. A per-contract margin schedule and volume limits are **not** modelled; this is documented in REVIEW_GUIDE. |
| Daily Monte Carlo omits flat days; `--skip` drops whole days | Fixed | Walk-forward now writes `walkforward_oos_daily_equity.csv`. Daily mode uses every day and refuses to run without that file. `--skip` with `--method daily` is refused. Real run: **1,066 days** (was 987). |
| One-month stress crash | Fixed | Windows longer than the data report "n/a" (`test_short_window_stress...`). The audit's command now completes. |
| `--data NQ` with XAUUSD | Fixed | Datasets must match the instrument (`test_dataset_must_match_instrument`). |
| 10-min ORB on 15-min bars | Fixed | ORB refuses bar sizes that don't divide the range (`test_orb_rejects_range...`). |
| Comparator tolerance / exit code 0 | Fixed | Exact text comparison; exit 1 when different (`test_compare_runs_exits_nonzero...`). |

## Performance and cache

| Finding | Status | What changed |
|---|---|---|
| Repeated work in the pipeline | Improved | The process pool is reused across stages. Parameter-search and stress-scenario jobs return summaries only. Each worker still loads its own data copy, which is inherent to separate processes. |
| Monte Carlo memory estimate too low | Fixed | Batches cut to about 1e7 cells; sample paths are copied so batches are freed; the comment is corrected. |
| Cache races / staleness | Fixed | Each cache file stores a fingerprint of its sources (size + modification time + format version) and rebuilds when they change. Writes go to a temporary file and are swapped in atomically. |

## Results before → after (MNQ, same command as the audit)
| | Audit (old code) | Now |
|---|---:|---:|
| Walk-forward OOS net | +$31,646.75 | **+$28,951.25** |
| OOS profit factor | 1.159 | **1.146** |
| Stress baseline (rr 3, 30-min range) | +$50,389.50 | **+$49,613.50** |
| Stress "delay 1 bar" | +$52,522.00 (above baseline: the bug) | **+$46,474.50** (−$3,139 vs baseline) |
| Stress baseline max drawdown | −$5,689 | **−$5,999** (includes intrabar lows) |
| Bootstrap 95%-worst drawdown | $19,082 | **$19,576** |
| Checklist | 9/12 | **9/12** |

Full new report: `results/20261122_181254_ALL_orb_MNQ/ROBUSTNESS_REPORT.md`.

## Not changed, by design
- **Ambiguous bars use rules, not finer data.** Using the NQ 1-second bars to settle them exactly would be a separate feature.
- **8 GC weekend roll spreads remain estimates.** Only the missing contract prices could fix this.
- **Back-adjusted prices shift old price levels** (needed for correct P&L). Strategies that use % changes or absolute levels should use `raw_*` columns; documented.

---

# Follow-up: second review (findings.md, section "Follow-up after the first fixes")

All five open issues were reproduced as failing tests first (`tests/test_findings.py`, follow-up section), then fixed. **60/60 tests pass.**

| Priority | Issue | Status | What changed | Proof |
|---|---|---|---|---|
| High | **Reverse slices bypass the look-ahead guard** | Fixed | The guard now expands every slice to the exact indexes it reads (any direction, any step) and refuses any later bar. Negative indexes are refused (they count from the end of the data). | `test_guard_blocks_every_slice...` (`[2:0:-1]`, `[::-1]`, `[-1:]`, `[:-1]`, ...), `test_reverse_slices_cannot_read_future_bars` |
| High | **Drawdown misses falls from an opening peak** | Fixed | The engine records equity at each bar's **open** too. Drawdown walks each bar in its known order (open, then worst price, then close). | `test_drawdown_from_an_opening_peak_is_reported`. Real data: summary drawdown **equals an exact open→low→close walk** (MNQ −$5,999.00; XAUUSD −$50,404.72). |
| High (gold) | **Spread stress priced the open with a later quote** | Fixed | Open and close are widened by their own quote's spread. Highs/lows are widened by the larger/smaller one so bars stay valid. | `test_spread_stress_prices_the_open...` (both cases now fill at 100.20). Real data at 2×: **0 invalid bars**, and every opening spread is exactly 2× the opening quote. |
| Medium | **Futures limit entries filled on a touch at the open** | Fixed | The 1-tick trade-through applies at the open as well. | `test_futures_limit_entry_needs_trade_through_at_the_open` (buy and sell) |
| Medium | **Resampled GC bars moved rolls earlier** | Fixed | A switch inside a bar is charged on the **next** bar; a switch on a bar's first minute on that bar. The bar keeps the contract it opened with. | `test_resampled_bars_never_charge_a_roll...`. Real GC data at 60 min, 240 min and daily: **0 of 50 rolls charged before the switch**; contract label = contract at the bar's open on every bar. |

## 1-second verification of MNQ fills (requested)
New tool: `tools/verify_orb_fills_1s.py`. It replays every minute that 1-minute OHLC cannot settle against the NQ **1-second** bars of the traded contract:
- **A:** competing entries
- **B:** stop and target in one minute
- **C:** exit inside the entry minute

For each it compares the first trigger, the stop/target order and the trade P&L, and flags events inside a single second. Prices are converted from back-adjusted to raw. A first version of the tool compared adjusted with raw prices; that was caught before any result was reported and is covered by a test.

| ORB setting | Trades | Ambiguous minutes | Agree with 1-second data | Same-second | P&L difference |
|---|---:|---:|---:|---:|---:|
| default (15-min range, 2R) | 1,430 | A: 1, B: 0, C: 1 (the same minute) | 2 of 2 | 0 | $0.00 |
| 30-min range, 3R | 1,336 | A: 1, B: 0, C: 1 (the same minute) | 2 of 2 | 0 | $0.00 |

The single case is 27 Aug 2021 10:00 ET. The 1-second data confirm the short triggered first (raw 15,284.25) and was stopped at the range high (raw 15,332.75) inside that minute, exactly as the engine booked it (−$495). Output: `results/20261122_182740_verify_1s_orb_MNQ/`.

## Effect on the full-history results
The MNQ ORB numbers are **unchanged** by this round: walk-forward OOS +$28,951.25, PF 1.146, stress baseline +$49,613.50 with max drawdown −$5,999.00. The fixed cases (XAUUSD spread stress, futures limit entries, opening-peak drawdown, resampled rolls) don't occur in this strategy on 1-minute MNQ. They do affect gold spread stress (XAUUSD Jan–Jun 2024, 2× spread now −$7,947.75) and resampled futures strategies. Run: `results/20261122_182810_ALL_orb_MNQ/`.

Remaining by design: margin/volume model (only `max_leverage`), 8 estimated GC weekend roll spreads, ambiguous-minute rules for markets without 1-second data (GC, XAUUSD, NAS100).

---

# Third review (findings.md, section "Remaining fixes after the second revision")

All four issues were reproduced as failing tests first, then fixed. **70/70 tests pass.**

| Priority | Issue | Status | What changed | Proof |
|---|---|---|---|---|
| High | **Strategy could read future bars through `self.broker.d`** | Fixed | The broker keeps execution data private (`Broker._d`). `broker.d` returns the same view as `self.d`: bar-bounded during the look-ahead check. | `test_broker_data_is_guarded_too`: the broker read at bar 0 is rejected; current and past reads through the broker pass. |
| High | **Drawdown missed a dip inside the exit bar, and % used a later peak** | Fixed | Drawdown is now an exact walk over every bar: open → worst price → close, with each low measured from the highest open/close *before* it (in $ and %). When a target is hit inside a bar, the bar's adverse extreme is assumed to come first (pessimistic, documented; 1-minute OHLC can't tell). Robustness windows and the stitched walk-forward keep per-bar equity, so they use the same walk. | `test_drawdown_inside_the_exit_bar_is_reported` (−$500), `test_drawdown_percent_uses_the_peak_before_the_trough` (−1.96%). Real data: $ and % match an independent plain loop (MNQ −$5,999.00 / −9.31%; XAUUSD −$50,404.72 / −91.52%). |
| Medium | **Resampled bars charged rolls at the wrong time** | Fixed | A bucket in which the contract switches is **split at the switch minute**. The roll is charged exactly at the switch, including on a final bar; never for a position closed before it or opened after it. | `test_resampled_roll_costs_match_one_minute`: 4 cases (close before, hold through, hold to final bar, open after), rolls and costs equal to the 1-minute engine. Real GC: all 50 roll charges are at an exact switch minute on 60-min, 4-h and daily bars (37 extra short bars on 4-h/daily). |
| Medium | **Verifier counted ties as agreement; crashed on zero trades** | Fixed | Outcomes are `agree`, `disagree` or `unresolved` (same second, or no 1-second data). Unresolved cases get no replay P&L and are excluded from P&L totals. A zero-trade run writes a readable empty CSV and a 0-case summary. | `test_verifier_tie_is_unresolved_not_agreement`, `test_verifier_marks_missing_second_data_unresolved`, `test_verifier_zero_trade_run_succeeds` (the reviewer's command). |

**Effect on results:** MNQ ORB is unchanged: walk-forward OOS +$28,951.25 (PF 1.146); stress baseline +$49,613.50, max drawdown −$5,999.00; daily Monte Carlo over 1,066 days. The verifier still finds 1 ambiguous minute (27 Aug 2021), resolved as agreeing in both entry and exit, P&L difference $0. MGC 4-h SMA cross: 286 trades, 39 across rolls. Run: `results/20261122_190614_ALL_orb_MNQ/`.

---

# Fourth review: photo-study audit (findings.md, section "Photo-study audit")

All seven issues and the carryover were reproduced as failing tests first (`tests/test_audit4.py`, plus updated roll tests in `tests/test_findings.py`), then fixed. **109/109 tests pass.** The whole study (94 runs) was re-run; every row now records its code and data fingerprints.

| # | Issue | What changed | Proof |
|---|---|---|---|
| 1 | Split gold daily bars fed two observations per roll day into indicators (Faber, weekly RSI) | Resampled bars are no longer split. Each session is one bar; `roll_inside` flags a switch inside a bar, and the roll is charged if a position is held after that bar's open. That's exact when positions change only at opens (all daily strategies, pairs), pessimistic otherwise (counted in notes). | `test_split_daily_session_gives_one_indicator_observation`, `test_roll_inside_a_bar_is_charged_only_if_held_after_its_open`; roll costs still equal the 1-minute engine in all 4 roll cases. Real GC daily: **0 duplicate days**; 13 + 37 = 50 rolls. **A10 on MGC (full) = +$104,129.87, matching the reviewer's one-decision-per-session replay exactly.** |
| 2 | Buy-and-hold past the scored dates; opening-peak drawdown missed | `photo_study.benchmark()`: exactly the scored windows (both endpoints; flat in gaps), whole contracts, the same costs and roll charges as the strategies, and the engine's open → worst → close drawdown walk. Out-of-sample benchmark drawdown is reported too. | `test_benchmark_uses_scored_dates_and_opening_peaks` (−$50k opening-peak fall; ends on the last scored day). A11 on MGC (cash session) now ends 2024-12-31. |
| 3 | B1 warm-up too short for nested windows | `Strategy.warmup_bars()` (B1: 2 × window; A12, A13 too). Windows load enough bars by days **and** bars; too little history is flagged (`insufficient_warmup`, fold column `oos_warmup_short`). In-sample selection and out-of-sample scoring were both re-run. | `test_warmup_counts_bars_for_nested_windows`; study: 0 folds with short warm-up. |
| 4 | B1 legs observed at different minutes | `pairs.combine_legs()`: both legs are joined on common 1-minute observations **before** bars are built; a minute missing in either leg is dropped from both; leg A's switches on dropped minutes are carried forward. | `test_pair_bars_use_common_minutes`. Real data: **0 of 26,684** hourly bars with mismatched close minutes. |
| 5 | Pair stress ignored the spot spread; "before costs" mislabelled | Stress treats pairs as having a spread (spread ×1.5/×2/×3 and the combined scenario widen XAUUSD). Each pair trade reports `pnl_nominal` (mid prices, no costs), `spread_cost`, `slippage_cost`, `commission`, `roll_cost`; `pnl` reconciles exactly. | `test_pair_stress_widens_the_spot_leg_and_pnl_reconciles`. Full history: nominal −$1,360.66, costs −$3,978.15, net −$5,338.81 (reconciles). The results report now states these values. |
| 6 | Cash session kept holiday dates; A13 crossed days and trained on overnight moves | `rth` = exchange trading days only. Daily signal strategies make no decisions on holiday sessions. A13: no sample spans a session gap, no entries in the last 10 minutes, flat by the session's last minute. | `test_cash_session_drops_exchange_holidays`, `test_daily_signals_are_not_taken_on_exchange_holidays`, `test_order_flow_strategy_never_holds_overnight...`. Real data: NAS100 cash session **0 holiday dates**; A13 MNQ **0 of 25,176 trades** cross a day. |
| 7 | Wrong pair instrument accepted; resume could skip failures or drop rows | `check_pair_instrument()` rejects a symbol whose dataset isn't the pair's first leg. Study rows carry `code_version` and `data_version`; a resume reuses only error-free rows with matching fingerprints, retries failures, replaces only the re-run rows, and never removes unrelated rows (also with `--fresh`). | `test_pair_run_rejects_the_wrong_instrument`, `test_study_resume_retries_failures_and_keeps_unrelated_rows`, `test_study_rows_record_code_and_data_versions` (temporary results directory). |
| carry | Trade `mae_pts` missed the exit-bar dip | The same pessimistic assumption used for drawdown updates the trade's MAE. | `test_trade_mae_includes_the_exit_bar_dip` |

**Also found and fixed before this review** (on the same branch, reported in PHOTO_STUDY_RESULTS.md): notional sizing used back-adjusted futures prices (now the real price; `test_notional_sizing_uses_the_real_futures_price`); the stress volatility split crashed on split daily bars (`test_stress_volatility_split_handles_split_daily_bars`).

**Independent re-checks after the re-run** (raw data, no engine code):
- Turn-of-month on NAS100 (cash session): 114 of 114 closed trades identical to the cent; plus the one end-of-data trade = $80,070.79, exactly the study row.
- A1 on MNQ (cash session): 41 trades, $23,224.00, exactly the study row.

**Effect on the study:** 32 of 94 runs pass all key checks (the same count as before; the composition changed).
- A1, A4, A6: profitable in all 8 runs, full history and out-of-sample; pass every check in 6 of 8.
- A3: passes every check in 3 of 8.
- A7: loses out-of-sample on spot gold.
- Buy-and-hold figures are lower than before, because they now use whole contracts, costs, rolls and exact windows.

---

# Fifth review: photo-study recheck (findings.md, section "Photo-study recheck")

All five issues were reproduced as failing tests first (`tests/test_audit5.py`, 12 cases), then fixed. **121/121 tests pass.** The study was re-run in full, then resumed once (only A13, whose file changed, was re-run; a final resume found 0 runs to do).

| # | Issue | What changed | Proof |
|---|---|---|---|
| 1 | Opening fill on a mixed-contract bar sized with the new contract's adjustment | Resampled bars carry `adj_open` (the adjustment of the contract the bar opens with). Notional and leverage sizing and the benchmark use it to get the real price. | `test_opening_fill_is_sized_with_the_opening_contracts_adjustment` (10 contracts, as on 1-minute data), `test_benchmark_sizes_with_the_opening_adjustment`. |
| 2 | `prepare()` could edit `roll_inside` and avoid roll costs | `roll_inside`, `adj`, `adj_open` and `raw_*` are protected like prices: changing, dropping or creating them is refused. | `test_strategy_cannot_edit_execution_metadata` (change, drop, create, edit `adj`, create `adj_open`). |
| 3 | Cash-session folds were dated from the full-session calendar | Folds are built from the days that have bars in the traded session (`robust.fold_days`). Each fold records `oos_scored_days`, and the report counts `folds_with_day_count_mismatch`. | `test_cash_session_folds_use_eligible_days_only`. A1 NAS100 cash session: fold 1 = 251 days = 251 scored days; last OOS end = last eligible bar (2021-09-30). **Whole study: 0 mismatched folds in 94 walk-forward runs.** |
| 4 | OOS benchmark re-opened a fixed-notional position at every fold boundary | One continuous position through back-to-back windows; it closes only at real gaps (where a fold had no valid parameters) and re-buys after. The result records the number of positions. | `test_benchmark_holds_through_consecutive_folds_and_closes_at_gaps`. A1 NAS100 cash session: **+$253,118.36, −$71,002.14 drawdown**, the reviewer's continuous-hold figures exactly. Study: 64 runs held as one position, 3 with gaps. |
| 5 | A13 could cross a session when closing bars were missing | New `intraday=True` orders: they expire at the end of the day they were placed. An intraday position still open in a new trading day is closed at that day's first open, labelled `session_gap_exit` and counted in notes. A13 uses them. | `test_intraday_position_is_closed_at_the_next_session_open_and_flagged` (data stops at 15:48 → exit 09:30, flagged), `test_intraday_pending_order_expires_at_the_session_boundary`, `test_a13_with_early_data_cutoff_never_crosses_unflagged`. Real data: 0 of 25,176 trades cross a day; 0 gap exits needed. |

**Independent re-checks after the re-run** (raw data, no engine code): turn-of-month on NAS100, 114 of 114 trades identical (+ end-of-data trade = $80,070.79, the study row); A1 on MNQ, 41 trades, $23,224.00 (the study row).

**Effect on the study:**
- Strategy results are unchanged from the fourth-review run; none of these cases occurred in the daily strategies' trades.
- The out-of-sample buy-and-hold benchmarks are larger (continuous holding). In all 67 runs with both numbers the strategy earned less than buy-and-hold. ~~with smaller drawdowns~~ **Correction (sixth review):** that drawdown claim was wrong. It was 64 of 67, not all; see the sixth-review section, where the counts are now generated from the data.
- 32 of 94 runs pass all key checks.

---

# Sixth review (findings.md, section "Verification after the fifth revision")

All three issues were reproduced as failing tests first (`tests/test_audit6.py`), then fixed. **125/125 tests pass.** The study was re-run in full in the new account-constrained mode; a final resume found 0 runs to do.

| # | Issue | What changed | Proof |
|---|---|---|---|
| 1 | Trading continued after the account went below $0 (A12 MGC: 753 more trades) | Every result reports `account_model` and `capital_exhausted_on` (the first bar whose marked equity is ≤ $0). New `Settings(account_constrained=True)` (`--account-constrained` in `robust.py`): at that bar's close pending orders are cancelled, the position is closed at the next open (reason `capital_exhausted`), new orders are refused (counted), and the walk-forward skips later folds. **The photo study now runs constrained.** | `test_capital_breach_is_reported_in_unconstrained_runs`, `test_constrained_account_liquidates_and_stops_trading`. A12 MGC: breach on 2021-08-23 (full history) and 2022-07-22 (walk-forward, the reviewer's date). Unconstrained it ran to −$140,674 over 2,460 trades; constrained it stops at −$100,205 after 1,399 trades and refuses 22,332 later orders. It is the only run in the study that hit $0. |
| 2 | Fix report claimed all 67 comparable runs had smaller drawdowns than buy-and-hold | The claim was wrong (written without counting) and is corrected above. Every count quoted in PHOTO_STUDY_RESULTS.md is now generated from `study_rows.csv` (`tools/photo_report_tables.py`, rows with both figures only), and the exceptions are listed in their own table. | `test_report_drawdown_counts_come_from_the_rows`. Study: **64 of 67** smaller drawdowns, **3** larger (A5 MGC full, A9 MNQ cash, A12 MGC full); **67 of 67** earned less than buy-and-hold. These match the reviewer's counts. |
| 3 | `r` computed before a roll charged inside the exit bar | Trades keep `risk_usd`; `r` is recomputed from the final net P&L whenever a roll is charged after the trade record exists. | `test_r_multiple_includes_a_roll_charged_inside_the_exit_bar` (−5R, not −3R). |

**Independent re-checks after the re-run:** turn-of-month on NAS100, 114 of 114 trades identical (+ end-of-data trade = $80,070.79); A1 on MNQ, 41 trades, $23,224.00. Both are exactly the study rows. 0 fold day-count mismatches across 94 walk-forward runs; 32 of 94 runs pass all key checks.

**A second unverified statement, caught before publishing:** while updating the results report I first described A12's position size as "1–3 MGC contracts" without checking. The data show 1–41 contracts (median 13), and the report states that.

**Correction (eighth review):** "0 fold day-count mismatches across 94 walk-forward runs" (fifth and sixth reviews) overstated the coverage. Only 67 of the 94 runs had out-of-sample folds to check. In the other 27, no fold had a parameter set with enough trades, so they report "not applicable". The statement that holds is: every scored fold in the 67 runs has matching day counts (355 folds, the reviewer's count).

---

# Seventh review (findings.md, section "Verification after the sixth revision")

All four issues were reproduced as failing tests first (`tests/test_audit7.py`), then fixed. **129/129 tests pass.** The study was re-run in full; a resume pass found 0 runs to do. Every regenerated table is identical to the sixth-review tables (only A12 on MGC ever hits $0, and its results were already final at the breach).

| # | Issue | What changed | Proof |
|---|---|---|---|
| 1 | The pairs engine kept opening trades after the account reached $0 | The pair broker has the same breach state as the single-market broker. At the breach bar's close pending entries are cancelled. Both legs are liquidated at the next common open (`capital_exhausted`). Later `open()` calls are refused and counted. | `test_pairs_engine_enforces_the_account_limit` (one trade, exit `capital_exhausted`, refused orders > 0). B01's study row has no breach and is unchanged. |
| 2 | Walk-forward resumed trading if a forced liquidation left a positive balance | A breach in any fold sets a permanent `stopped` flag. Every later fold is skipped (`oos_skipped = capital_exhausted`), whatever the balance. | `test_walkforward_stays_stopped_after_a_breach_even_if_balance_recovers`. A12 MGC: breach 2022-07-22, 6 later folds skipped. |
| 3 | Forced liquidation waited for `delay_bars` | The liquidation has its own flag. It is executed at the very next open, before anything else, whatever `delay_bars` is. | `test_forced_liquidation_happens_at_the_next_open_whatever_the_delay` (exit at 20 at the next open, not 80 one bar later). |
| 4 | Stress tables hid a breach when the scenario ended above $0 | Each stress row has `account_model`, `capital_exhausted_on` and `orders_refused`. | `test_stress_table_shows_a_breach_even_if_the_scenario_recovers`. Real A12 MGC stress table (study parameters): all 7 scenarios show their breach date. 2-bar delay: 2022-10-13 with 31,074 refused orders, the reviewer's figures. |

**Independent re-checks after the re-run:** turn-of-month on NAS100, 114 of 114 trades identical (+ end-of-data trade = $80,070.79); A1 on MNQ, 41 trades, $23,224.00. Both are exactly the study rows.

---

# Eighth review (findings.md, section "Batched audit before regenerating the study")

All six issues were reproduced as failing tests first (`tests/test_audit8.py`, 15 cases; the zero-month step really hung and was stopped by a 2-second alarm), then fixed. **144/144 tests pass.** The memory test was also run against the old line to confirm that it fails there.

| # | Issue | What changed | Proof |
|---|---|---|---|
| 1 | `montecarlo --from` on a saved walk-forward used the CLI default capital ($50,000), so the daily replay invented +$50,000 | `robust.saved_capital` reads the capital from `summary.json` or `walkforward_summary.json` (out-of-sample summary). If neither records it, a warning names the fallback. | `test_saved_walkforward_replay_uses_the_recorded_capital`. Real A01 NAS100 cash-session folder (replayed from a scratch copy): capital $100,000; reconstructed daily P&L = **$33,301.70** = saved OOS net = sum of trades. |
| 2 | A breached account could PASS profit checks with a positive closing balance | Walk-forward-profitable, double-commission and combined-stress checks FAIL when that result hit $0 (the detail gives the date). The study's "passed all key checks" also requires `survived`: no breach in full history, walk-forward or combined stress. Study rows now record `stress_all_capital_exhausted_on` and `stress_scenarios_breached`. | `test_breached_account_never_passes_a_profit_check`, `test_study_ranking_requires_the_account_to_survive`. Study: still 32 of 94. Every run with a breach already failed on P&L. |
| 3 | `make_folds(days, 1, 0)` hung; an empty date range crashed at `df.tday.iloc[0]` | `make_folds` refuses windows < 1 month and an empty day list. The CLI refuses `--is-months`/`--oos-months` < 1 before loading data. `make_job` stops with "no data for … between …". | `test_walkforward_rejects_nonpositive_windows` (4 cases), `test_walkforward_rejects_an_empty_day_list`, `test_cli_rejects_nonpositive_months`, `test_date_range_outside_the_data_gives_a_clear_error`. |
| 4 | Daily Monte Carlo with 3 days and a 5-day block gave 128 identical paths | A block that leaves fewer than 2 possible starts is refused with an explanation. Daily results record `block_days` and `distinct_block_starts`, and the report text shows them. | `test_daily_monte_carlo_rejects_a_block_with_too_few_starts`, `test_daily_monte_carlo_reports_its_distinct_block_starts` (40 days, block 5 → 36 starts, paths differ). The study uses bootstrap and shuffle only. |
| 5 | `finals` kept every batch's whole cumulative matrix alive | The final column is copied. The batch size is a module constant (`BATCH_CELLS`) so it can be tested. | `test_monte_carlo_does_not_keep_finished_batches_alive` (60 batches stay under 15 MB; fails with the old line), `test_monte_carlo_is_still_reproducible`. **Parity: all 136 saved study Monte Carlo summaries (68 runs × bootstrap/shuffle) re-simulated from their saved trades are identical.** |
| 6 | Profit-factor objective dropped no-loss settings and counted them as "not enough trades" | `sweep.report` counts `with_enough_trades` (by trade count), `scored`, and `excluded_undefined_score` with the reason ("no losing trades (profit factor is infinite)"). Ranking policy, documented in REVIEW_GUIDE: undefined scores are not ranked. | `test_profit_factor_sweep_reports_no_loss_settings_separately`. The study ranks by Sharpe and is unaffected. |

**Re-run and provenance.** The pre-run rows are kept in `results/PHOTO_STUDY/archive/study_rows_review7.csv`, and all earlier run folders are kept. The full re-run had 0 errors, and a resume found 0 runs to do. Compared with the archived rows, **every result column is identical** (only `seconds`, the run time, differs). The regenerated tables are identical apart from the breach table, which now includes stress breaches. That table shows something new: A12 also hits $0 in stress on NAS100 (spread ×2, ×3, combined worst case; first in 2016) and on spot gold (spread ×3, 2025-01-08). 355 scored walk-forward folds, 0 day-count mismatches.

**Independent re-checks** (raw data, no engine code): turn-of-month on NAS100, 114 of 114 trades identical (+ end-of-data trade = $80,070.79); A1 on MNQ, 41 trades, $23,224.00. Both are exactly the study rows.

**Not changed (reviewer's note on fingerprints):** resume fingerprints still include the shared engine files, so an engine edit re-runs every row. A full run takes about 10 minutes, so this conservative choice is kept. Provenance is preserved by the archive above and the timestamped run folders.

---

# Ninth review (findings.md, sections "Verification of the batched fixes" and "Consolidated end-to-end audit")

All 22 items (E1–E8, R1–R7, I1–I4, C1–C3) were reproduced as failing tests first (`tests/test_audit9.py`), then
fixed. One more problem turned up while running the new timeframe study, and it got the same treatment (last row of
the first table). **188/188 tests pass.**

## Execution, data and strategy behaviour

| ID | What changed | Test | Proof on real data / measured effect |
|---|---|---|---|
| E1 | The look-ahead gate checks the **whole** selected period (not the last 300,000 bars), every distinct parameter set up to 40 (sampled evenly beyond that), and also cuts the data after the first 1, 2, 3, 5, 9, 17, 33, 65 and 129 rows. If `prepare()` fails on a short prefix, that counts as a failure. The verdict says what was checked ("passed (DATES, N bars; X of Y parameter sets)"). `run.py` stops **before writing anything** when the check fails, unless `--force` is given (recorded in the summary). | `test_lookahead_check_finds_a_future_read_in_the_first_rows`, `test_lookahead_gate_checks_the_whole_selected_period`, `test_standalone_runner_refuses_to_publish_after_a_failed_check` | All 15 real strategies pass the stricter check: no false positives. It found one real problem in the new timeframe study: A13 on 1-hour bars (last row of this table). |
| E2 | ORB: the entry deadline is absolute. An order is cancelled on the bar **before** `last_entry`, so nothing can fill in a bar that starts at or after it. ORB orders are `intraday=True`, so after a missing afternoon the position closes at the first bar of the next session. | `test_orb_order_cannot_fill_at_the_entry_cutoff`, `test_orb_position_closes_at_the_first_bar_after_a_missing_close` | Control, default MNQ ORB on the full 1-minute history: the 4749c7a `orb.py` and today's give **1,430 / 1,430 identical trades**, $53,714.50 both. This matches the reviewer's "0 of 1,430 affected". |
| E3 | `indicators.money_flow_index(df, n)` weights money flow by the **raw** (as-traded) typical price when the frame has raw prices. A later roll re-bases the adjusted prices, but it can't change raw prices, so MFI no longer moves when history is appended. A07 uses it. | `test_futures_mfi_does_not_change_when_a_later_roll_rebases_history` | Reviewer's case (MNQ cash, through 2025-04-30, `mfi_len=5, mfi_entry=20`, later rebase 1,206.75 points). Old code: 19.9626 vs 20.0067 without the rebase. Now: **20.0067 both ways** (max difference over the window 0). A07 gives **55 trades, $14,856.00** both ways. In the full study no MNQ/NAS100 A07 trade changed. |
| E4 | GC roll spreads that have no same-time overlap are estimated **only from earlier measured rolls**: the median ratio of up to 4 earlier rolls. With no earlier roll, the spread is 0 and flagged "no_earlier_roll(uncertain)". The method is stored per roll. CACHE_VERSION 4. | `test_gc_fallback_roll_estimate_uses_past_rolls_only` | All 8 uncertain rolls changed (points): 2016-01-31 2.682→0.000; 2016-07-31 3.238→2.333; 2017-04-02 3.781→2.992; 2018-12-02 5.135→5.496; 2019-03-31 5.699→5.805; 2020-02-02 14.147→7.014; 2020-08-02 12.161→17.574; 2021-01-31 5.040→12.906. Effect: small changes on every MGC row (table below). |
| E5 | Breach is detected at the **open** as well as the close (`equity_open <= 0`), in both engines. In constrained mode, orders are cancelled and the forced liquidation happens at that open. The liquidation now runs **before** a session-gap exit, so it can't be masked. | `test_opening_gap_below_zero_is_a_breach_even_if_the_close_recovers`, `test_liquidation_is_not_masked_by_a_session_gap_exit`, `test_pair_opening_gap_breach_is_detected` | Study: no new breaches in the daily study (the breach list is unchanged). |
| E6 | Pair equity is also marked at each bar's pessimistic intrabar bound (`_mark_worst`: each leg at its adverse high/low). Drawdown uses min(open, worst, close). | `test_pair_drawdown_includes_an_adverse_move_between_marks` | B01 out-of-sample max drawdown **−$4,434.07 → −$4,566.20**. This is more conservative than the reviewer's common-minute replay (−$4,442.37), because both legs are assumed to hit their worst at the same moment. Full history −$6,123.69 → −$7,456.20. Trades and net unchanged (93 OOS, −$1,937.40). |
| E7 | Pair leg B direction follows the sign of beta (`side_b = −side × sign(beta)`). `max_leverage` caps the **gross** exposure of both legs against capital + realized P&L. | `test_pair_negative_beta_goes_long_the_second_leg`, `test_pair_leverage_cap_counts_both_legs` | B01 trades unchanged: beta is positive throughout, and both legs stay within the leverage cap. |
| E8 | A13 refuses input with any bar outside 09:30–16:00 ET (cash session only). A sample needs the previous bar to be exactly one bar earlier on the same day. | `test_order_flow_strategy_refuses_full_session_input`, `test_order_flow_sample_never_spans_a_missing_minute` | A13 MNQ cash-session study row unchanged (25,176 trades, −$64,700). The saved frame had no same-day missing minutes. |
| new | **Found by the E1 check during the timeframe study:** A13 guessed the bar size from the median step of the whole frame. 1-hour cash-session bars start with a 30-minute 09:30 bar, so a two-bar prefix guessed 30 minutes and the full frame guessed 60, and the 10:00 sample was in or out depending on later data. The bar size at row *i* is now the most common same-day step among rows 0…*i* (`bar_minutes_so_far`). | `test_order_flow_bar_size_is_inferred_from_past_bars_only` | On real MNQ 1-hour bars, every cut (1 … 8,352 rows) now gives identical columns. The 1-, 5- and 15-minute A13 rows are **identical** before and after. On 1-hour bars A13 makes **0 trades**: its rule needs 90% of the last 1,950 bars to be valid samples, and only 5 of 7 hourly bars per day can be. This is reported as a result, not changed. |

## Stress, robustness and report accuracy

| ID | What changed | Test | Proof / effect |
|---|---|---|---|
| R1 | The scenario is labelled "Still profitable under **combined execution stress**". A new check, "Still profitable in **every** tested execution scenario", names the worst scenario and its net, plus any scenario that hit $0. Study rows record `stress_worst_net`, `stress_worst_scenario` and `stress_scenarios_breached`. "Passed all key checks" now needs worst > 0 and at most one checklist item not passed. | `test_checklist_reports_the_worst_tested_scenario`, `test_study_ranking_requires_every_scenario_to_be_profitable` | A06 MNQ cash session: worst = "delay 2 bars", **−$6,549.50** (reviewer's figure), so it leaves the shortlist. Daily shortlist **32 → 27** (details below). |
| R2 | Named market periods (COVID etc.) use **daily marked-equity changes**, not exit-date P&L. "Worst rolling N months" uses complete calendar months only, shows the actual dates, and prints "n/a (incomplete months excluded)" when there are too few. | `test_market_period_pnl_comes_from_marked_equity`, `test_worst_stretch_marks_incomplete_windows` | Reviewer's fixture: the $600 gain inside the window is now reported in the window. |
| R3 | Walk-forward efficiency is **pooled**: total OOS P&L ÷ total OOS days, divided by total in-sample P&L ÷ total in-sample days. The report text says so. | `test_walk_forward_efficiency_uses_total_pnl_per_scored_day` | Old A03 XAUUSD cash folds recomputed: **0.295 → 0.755** (reviewer's figure, exactly). In the re-run it is 0.910, because of the longer indicator warm-up (next section). |
| R4 | The double-commission check uses the commission that was actually tested (`baseline_commission` in the stress result). | `test_double_commission_check_follows_the_tested_cost` (MNQ with 0, NAS100 with a positive override) | — |
| R5 | `spread_usd` uses the quote at the actual fill: the close quote for a close fill, the open quote for an open fill. | `test_spread_cost_uses_the_quote_of_the_actual_fill` | Reviewer's fixture: $250 reported (was $100), equal to the executed cost. |
| R6 | One-second verifier: if the tape ends before a definitive exit, the replay is **unresolved** (blank replay P&L, labelled "no 1-second data, no trigger, or the tape ends before an exit"). | `test_partial_one_second_tape_is_unresolved` | — |
| R7 | A zero-day span gives **no** annualised return or trades per year (None), instead of dividing by 1e-9. | `test_single_day_report_has_no_annualised_figures` | — |

## Input validation, saved results, performance

| ID | What changed | Test | Proof / effect |
|---|---|---|---|
| I1 | `make_job` refuses a market, date range and session with no eligible bars ("no bars in the {session} session …") before any look-ahead check or output. | `test_session_without_bars_is_rejected` | — |
| I2 | Monte Carlo refuses non-finite P&L, `n_sims < 1`, capital ≤ 0, skip/haircut outside [0, 100] and `ruin == 0`. CLI types `positive_int`/`percent` reject them before any data is loaded. | `test_monte_carlo_rejects_meaningless_inputs` (3 cases), `test_monte_carlo_accepts_percentage_endpoints` | — |
| I3 | Output folders are unique (suffix `_k`, `exist_ok=False`). Study rows are saved by `save_row`: file lock → re-read → replace this key → temp file → `os.replace`. | `test_concurrent_study_writers_keep_every_row`, `test_output_folders_are_unique_within_one_second` | The timeframe study (373 runs, 4 workers) and the A13 re-runs wrote every row. |
| I4 | Peak worker memory measured (cold start, GB): NQ 5m 0.96, GC 5m 1.47, NAS100 5m 0.80, XAUUSD 5m 1.11, NQ 1m cash 1.01, GC+XAUUSD pair 5m 2.01. `WORKER_PEAK_GB = 2.0` is the default budget, and `FRAME_CACHE = 2` (LRU) stops a worker accumulating frames. | `test_worker_count_respects_the_memory_budget` | The 373-run study completed with 4 workers and 0 errors. |
| C1 | Saved daily Monte Carlo keeps the trading dates and splits the history at skipped folds. Blocks are drawn only inside continuous segments. | `test_daily_blocks_stay_inside_continuous_segments`, `test_saved_replay_splits_daily_history_at_skipped_folds` | — |
| C2 | `profitable_pct` counts **every** setting with enough trades. The defined-score subset is only used for ranking. | `test_profitable_share_counts_every_setting_with_enough_trades` (66.7%) | Study sweeps use Sharpe, so it is unchanged. |
| C3 | Saved daily replay needs enough **days** for the block, not 2 trades. The 2-trade minimum stays for bootstrap/shuffle. | `test_saved_daily_replay_accepts_one_trade_with_enough_days` | — |

## Changes made for the timeframe study (not from findings.md)

- `PRICE_PCT` attribute: thresholds written as a % of price (A01 `vwap_disc_pct`, A02 `vwap_buffer_pct`, A11 `threshold_pct`) are scaled by √(bar minutes ÷ native bar minutes) on other bar sizes. A daily bar counts as one session (390 cash minutes or 1,380 full). Lengths stay in bars. Only declared names are scaled, so A12's `squeeze_pct` (a percentile) is left alone. Tests: `test_percent_thresholds_scale_with_the_square_root_of_bar_time`, `test_only_declared_price_percentages_are_scaled`.
- `SignalStrategy.warmup_bars()` = 3 × longest lookback + 2. An EMA needs about 3× its length to forget its starting value, so walk-forward windows now load enough history on any bar size. Test: `test_signal_strategies_ask_for_three_times_their_longest_lookback`. This is why some daily OOS figures moved even on markets with no data change (A03 MNQ cash 16,780.50 → 17,388.50; A03 XAUUSD cash 12,997.42 → 15,672.18).

## Re-run of the daily study and effect

The pre-run rows are archived as `results/PHOTO_STUDY/archive/study_rows_review8.csv`. Re-run: 94 runs, 0 errors.

- **Changed:** the MGC rows (GC rolls), B01 drawdown (E6), and OOS figures moved by the longer warm-up. Efficiency is now pooled for every row. Nothing else changed: MNQ, NAS100 and XAUUSD trades and net are identical except where the warm-up moved OOS.
- **Shortlist 32 → 27.** With the new data and the old rule it would be 34. The new rule removes 7, and 5 of them were on the old list:
  - A06 MNQ cash: worst scenario "delay 2 bars", −$6,549.50.
  - A06 MGC full, A07 MGC cash, A07 MGC full and A11 MGC full: each has two or more checklist items not passed. All four have a best setting that is a spike, not a plateau. The others are losing without the best 5% of trades (A06, A07 cash), fewer than half the folds profitable plus a 95%-worst Monte Carlo drawdown over $20,000 (A07 full: three items), or no efficiency (A11).
- **Independent re-checks** (raw data, no engine code):
  - Turn-of-month on NAS100: 114 of 115 trades identical. The 115th is the end-of-data close on 2021-09-30, which the independent script doesn't count. Total = $80,070.79, the study row.
  - A1 on MNQ cash session: 41 trades, $23,224.00, the study row.
  - A1 on MNQ 1-hour: 231 of 232 trades identical. The other differs by one $7.50 roll charge (the documented conservative overnight-roll rule).

## Open item for the reviewer (not changed)

Pooled efficiency has no lower limit on the in-sample rate. **A11 MGC cash session (daily)** scores 3,316 because only 2 of its 7 folds had enough trades, and their chosen in-sample P&L was +$3,446.80 and −$3,435.65 (pooled +$11.15). It therefore "passes" the efficiency ≥ 0.5 check, and that run is on the shortlist. Other large values in the timeframe study: A03 XAUUSD full 1-hour 16.96, A12 NAS100 full 4-hour 15.83, A04 MGC cash 1-hour 7.34, A04 MNQ cash 1-hour 6.15 (shortlisted), A01 MNQ cash 5-minute 5.30, A03 NAS100 cash 15-minute 5.26. Possible rules: require positive in-sample P&L in each scored fold, or a minimum share of folds scored. I left the rule as it is, because choosing a threshold is a policy decision.

Related, not changed: the example ORB (`strategies/orb.py`) also infers its bar size from the median of the first
5,000 steps. It passes the look-ahead check on the 1-minute data it is used with. On 1-hour cash-session bars (30-minute
first bar) it would have the same prefix problem as A13. If ORB is ever run on those bars, give it the same
past-rows-only inference.

---

# Tenth review (findings.md, section "Verification after the ninth revision")

All 10 open items were reproduced as failing tests first (`tests/test_audit10.py`, 17 tests, 18 cases), then fixed.
**206/206 tests pass.** Every earlier test still passes; two test stubs were widened to accept the gate's new optional
`coverage` argument.

## High priority

| ID | What changed | Test | Proof on saved data / measured effect |
|---|---|---|---|
| R1 | `survived()` also requires **zero breached single stress scenarios** (`stress_scenarios_breached`), so the shortlist does too. A scenario that hit $0 and then recovered to a profit is a breach. | `test_an_individual_stress_breach_means_the_run_did_not_survive` | Reproduced the reviewer's counts: timeframe "hit $0 somewhere" **52 → 64** (5-minute 35 → 41, 15-minute 15 → 20, 1-hour 2 → 3); daily 2 → 3 (A12 XAUUSD). Shortlists unchanged by this rule alone (47 and 27): every such run had already lost money in that scenario. |
| E1 | Besides the fixed and early cuts, the look-ahead check now cuts the data **right after the strategy's own decision bars** (on_bar placed an order, a close or a stop/target change: recorded by both brokers as `decision_bars`) and **right after True/False signal flips** in prepared columns: up to 16 extra prefixes per parameter set, half of each kind, evenly sampled. The docstring and the gate message say what is sampled ("features also re-checked at N cuts per set right after decision bars (M per set) and signal flips"); `on_bar` is still guarded on every bar. Same for pairs (which also gained the early cuts). | `test_lookahead_check_catches_a_sparse_future_read_at_a_decision_bar`, `test_boundary_only_recheck_finds_the_sparse_future_read` | The reviewer's 200-bar fixture (trigger at row 60 from row 61's close) is now caught. **Every saved configuration was re-checked: all 373 timeframe configurations (which include all 94 daily-study ones) pass, 0 failures.** |
| E5 | After any entry fill the account is marked at the opposite quote: opening commission paid, and closing at once gives back the slippage and the whole spread (`fill − opposite quote = slippage + 2 × half spread`). At or below $0 that is a breach (`capital_exhausted_at = "entry"`); a constrained account liquidates at the next open, like any breach. Both engines. The breach bar travels as a `breach` column through fold windows and stitching, so the walk-forward and the summary see it. | `test_entry_costs_that_exhaust_the_account_are_a_breach`, `test_pair_entry_costs_that_exhaust_the_account_are_a_breach` | Reviewer's fixture ($500 capital, $600 commission): breach at entry, liquidated at the next open. **Screen of saved paths:** a stage can only be affected if its equity came within the entry costs of $0, and its lowest equity is ≥ capital + max drawdown. No daily-study stage and 21 stages in 19 timeframe configurations (all losing 5-minute to 1-hour runs) came within $5,000 without a recorded breach. Those 19 were re-run with the current code: all 19 gave **identical** trades, full-history and out-of-sample P&L, and all 145 of their stress-scenario rows (net, drawdown, breach date). No entry breach occurred on real data. |

## Medium priority

| ID | What changed | Test | Proof / effect |
|---|---|---|---|
| E2 | `Order.last_fill_ts`: an absolute deadline the **engine** checks before any fill (an order can fill only in a bar starting at or before it), whatever bars are missing. ORB sets it so the last bar allowed to fill ENDS by `last_entry` (starts at `last_entry − bar size`). Bar size: ORB's `bar_minutes` parameter, else `df.attrs["bar_minutes"]`, which `data.resample` now sets on every frame; only hand-built frames fall back to the old step median. | `test_orb_order_cannot_fill_after_the_deadline_when_the_last_minute_is_missing`, `test_orb_order_cannot_fill_in_a_coarse_bar_that_ends_after_the_deadline`, `test_resampled_bars_declare_their_size_and_orb_uses_it` | Gap fixture (no bars 09:33–11:31): no fill. 30-minute bars with the 11:00 bar missing: no fill at 11:30. **Controls:** default MNQ ORB on the full 1-minute history: **1,430 / 1,430 trades identical** to the 22 Nov run, +$53,714.50, look-ahead passed. April 2024 stress: 22 trades in each of 7 scenarios, **+$2,437.50** baseline, **+$1,606.50** combined (the reviewer's figures). |
| C1 | `make_folds` records each fold's scheduled window (`period`), kept even when an earlier window had no bars. `daily_segments` starts a new segment when the schedule (or the fold number) is not consecutive. Older folders are rebuilt from the calendar using the saved `out_of_sample_months`. | `test_folds_keep_their_scheduled_period`, `test_daily_replay_does_not_bridge_an_absent_window` (with and without `period`) | Reviewer's case (February, no March, April): **[2, 2]** instead of one 4-day segment. Screen: **0 of 467** saved walk-forward folders have a scheduled window with no data, and the study Monte Carlo uses trade bootstrap/shuffle, so no saved result changes. |
| R2 | A "complete month" now has a row for **every exchange trading day** of that month (`calendar.trading_days`). Incomplete months are blanks on a continuous monthly index, so a rolling window never bridges a missing month; the "losing months" line says how many were excluded. | `test_a_month_ending_on_the_26th_is_not_complete`, `test_rolling_windows_do_not_bridge_an_absent_month` | The published reports do not use these tables (only each run's `stress_report.txt`). Saved per-run stress reports written before this fix keep the old rule. |
| R3 | `walkforward.efficiency_detail`: the ratio counts as a pass criterion only when **at least 50% of the scheduled folds were scored** and the **pooled in-sample profit is at least 1% of capital a year** (252 trading days). Otherwise it is "not available", and the checklist item fails with the reason. The raw ratio, both pooled rates and the coverage are published (`walk_forward_efficiency_raw`, `..._note`, `wf_is_pnl_per_day`, `wf_oos_pnl_per_day`, `wf_scored_folds`). Both limits are constants in `engine/walkforward.py`: a policy choice, flagged for the reviewer. | `test_efficiency_is_unavailable_with_low_coverage_or_a_tiny_in_sample_rate`, `test_checklist_explains_an_unavailable_efficiency` | Applied to every saved row from its saved folds (`tools/recheck_efficiency.py`). The saved ratio equals the recomputed raw ratio on all 467 rows. Daily: 2 rows lose the efficiency pass (A11 MGC cash 3,316.29: only 2 of 7 folds; A06 MGC full 4.09: in-sample $2.66/day); **shortlist 27 → 26** (A11 MGC cash). Timeframe: 21 rows lose it; **shortlist 47 → 45** (A11 MGC cash daily, and A04 MNQ cash 1-hour, raw 6.15 from $3.69/day in-sample, just under the $3.97 limit). |
| Costs | The engine exports `roll_slippage_usd` (the slippage part of roll charges, which is in BOTH `costs` and `slippage_usd`). `timeframe_costs.friction` = costs + (slippage − roll slippage) + spread; ledgers saved before the column existed get it rebuilt as rolls × 2 × slippage × qty. The table is labelled as a diagnostic on executed trades, not a zero-cost re-run. | `test_roll_slippage_is_added_back_once` (flat prices: 0 before costs, with and without the new column) | Reproduced the reviewer's figure on the archived ledgers: **$7,658** duplicate add-back ($1,225 on 5-minute bars), **0** sign changes in "profitable before costs". |
| Portfolio | `timeframe_portfolio` prints: positions carried in at the start; a **flat-start** view (trades entered in the window, whole P&L, drawdown on exit days); drawdown labelled "daily closes"; positions open at once from **bar timestamps** (and the per-day count); gross exposure from quantity × real (unadjusted) daily close × point value; each run's median and max entry notional. The text no longer says every trade is $100,000 of contract value, and says plainly that the book is separately sized accounts, not one constrained account. | `test_portfolio_counts_overlap_from_timestamps_and_reports_carry_in` | Reproduced the reviewer's figures on the old selection: +$220,933.43, 9 positions at once from bar timestamps (11 counted per day), 6 carried in, A12 XAUUSD max entry notional **$118,592** (now shown per run). With the 45-run shortlist, book 1 swaps A04 MNQ cash 1-hour for A04 MNQ full 4-hour: **608 trades, 32.1 a month**, marked net $218,785 (5 carried in), flat start $221,400, max drawdown −$27,165 on daily closes (−$18,147 flat start), at most **9** positions at once, gross exposure up to **$891,620** (median $393,370). Book 2 drops A11 MGC cash daily (no trades in its window): 731 trades, 22.2 a month, $259,737, 7 at once, gross exposure up to $803,033 |
| Perf | `robust.lookahead_reuse()`: inside one `robust all`, a parameter set that already passed on the same strategy, data span, session, settings and parameters is not checked again (the message says how many were reused). Standalone commands always check afresh. | `test_lookahead_gate_reuses_coverage_only_inside_one_run` | Real 3-month MNQ ORB `robust all` with 2 parameter sets (`rr=2,3`): look-ahead checks **7 → 3**, time in them **6.5 s → 2.8 s**, total 11.0 s → 9.7 s (machine busy with other jobs, so totals are rough). All 32 report table lines identical with and without reuse |

## Re-run scope and provenance

- Index archives before this round: `results/PHOTO_STUDY/archive/study_rows_review9.csv`, `results/TIMEFRAME_STUDY/archive/rows_review9.csv`. All earlier run folders are kept.
- Re-run with the current code: the 19 timeframe configurations from the E5 screen (`timeframe_study.py --keys …`, log `results/TIMEFRAME_STUDY/rerun_review10.log`). Every other row keeps its saved run; the R1, R3 and cost/portfolio changes were applied to their saved tables, as the reviewer suggested. Because the engine files changed, a plain resume would now schedule every row (the shared-code fingerprint); use `--keys` for targeted re-runs.
- Look-ahead re-check of every configuration: `results/TIMEFRAME_STUDY/lookahead_recheck/` (`tools/recheck_lookahead.py`). 152 configurations went through the complete new gate; to finish in reasonable time the other 221 ran only the new decision/signal-boundary cuts (`--mode boundary`, `core.check_boundary_cuts`) on exactly the gate's parameter sets: the rest of the gate (fixed and early cuts, guarded on_bar, prefix trades) had already passed in their saved runs with the same strategy code and data. Combined list: `all.csv`.

## Noticed, not changed

- `metrics.summarize` reports `of_which_slippage` = `slippage_usd`, but fill slippage is inside the fill prices, not inside `total_costs`, so "of which" is not accurate (roll slippage is in both). The cost report no longer relies on it; the summary label is left for the reviewer.
