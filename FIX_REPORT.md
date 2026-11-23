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
