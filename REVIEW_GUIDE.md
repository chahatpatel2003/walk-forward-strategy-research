# Code review guide

Written for whoever reviews this code (the owner uses ChatGPT as a coding supervisor).
It explains what the code must guarantee, where each guarantee lives and is tested, and which
behaviours are **deliberate choices**, so they aren't mistaken for bugs.

## Hard rules
1. **`/Volumes/T9/DATA` is read-only.** Nothing may be written, added, renamed or deleted there, by the code or by a reviewer. `engine/data.py::_assert_not_data_path` refuses writes inside it. All outputs go to `BACKTESTING/cache/` and `BACKTESTING/results/`.
2. **Don't change engine behaviour without a test** that shows the old behaviour was wrong. Fill rules are deliberately conservative (see below).
3. After any engine change, run the tests and the regression check (below). Trades on real data must not change unless the change was meant to change them.

## Running things
The Python environment is `~/.venvs/t9-backtesting`. It's on the internal disk, because the T9 drive is exFAT and breaks pip installs.

```bash
cd /Volumes/T9/BACKTESTING
~/.venvs/t9-backtesting/bin/python -m pytest tests -q -p no:cacheprovider          # 70 tests, ~4 s
~/.venvs/t9-backtesting/bin/python run.py strategies/orb.py --symbol MNQ            # one backtest
~/.venvs/t9-backtesting/bin/python robust.py all strategies/orb.py --symbol MNQ --grid rr=1.5,2,3 or_minutes=10,15,30
# regression: compare two runs' trades exactly
~/.venvs/t9-backtesting/bin/python tools/compare_runs.py results/<old>/trades.csv results/<new>/trades.csv
```

## Map of the code
| File | Responsibility |
|---|---|
| `engine/data.py` | Loads DATA into one standard 1-min table; futures back-adjustment; New York time columns; resampling |
| `engine/instruments.py` | Contract specs (point value, tick) and default costs |
| `engine/core.py` | The bar-by-bar simulator (`Engine`), the order API (`Broker`), `Strategy` base class, `check_lookahead` |
| `engine/calendar.py` | Exchange holidays and 13:00 closes (published in advance, so not look-ahead) |
| `engine/metrics.py` | Statistics; `result_from_trades` (trade list → equity); `score` (objective for optimisation) |
| `engine/report.py` | Writes a single run's results |
| `engine/parallel.py` | `Job` (one backtest on one date window) and `run_many` (process pool) |
| `engine/sweep.py` | Parameter test: grid, plateau score, heatmaps |
| `engine/walkforward.py` | Fold construction, IS optimisation → OOS trading, stitching |
| `engine/montecarlo.py` | Shuffle / bootstrap / daily-block simulations |
| `engine/stress.py` | Execution stress re-runs, outlier dependence, turbulent periods, volatility regimes |
| `run.py`, `robust.py` | Command-line entry points |
| `tests/test_engine.py` | Hand-computed fill / cost / roll / look-ahead scenarios |
| `tests/test_findings.py` | One regression test per problem in `findings.md` |
| `tests/test_robust.py` | Fold boundaries, optimiser isolation, plateau maths, Monte Carlo properties, stress settings, real-data window integration test |

## Invariants: what must stay true
Tests are in `tests/`. `test_findings.py` holds one regression test per problem reported in `findings.md`.

| # | Invariant | Where | Test |
|---|---|---|---|
| 1 | A strategy acts on bar *i*'s close; nothing it orders can fill before bar *i+1* (+ `delay_bars`) | `core._fill_entries` | `test_market_order_fills_next_open...`, `test_order_placed_on_last_bar...`, `test_delay_bars_shifts...` |
| 2 | **Fill chronology inside a bar:** open (close request, gap exits, market/gapped entries), then inside the bar. After a held position exits *inside* a bar, no entry may fill in that bar | `core.Engine.run` | `test_no_entry_at_the_open_after_an_intrabar_exit` |
| 3 | If several entries could trigger in one bar, the trigger nearest the open is taken; counted in `notes.ambiguous_entry_bars` | `core._fill_entries` | `test_oco_takes_the_trigger_nearest_the_open...` |
| 4 | Stop-loss beats target in the same bar. On the entry bar the stop counts if reached; a target counts only if the price path must have reached it after the entry (limit entries: only the close counts) | `core._intrabar_exit` | `test_both_stop_and_target...`, `test_limit_entry_bar_cannot_award...` |
| 5 | Stops never fill better than the bar's quotes (gaps fill at the open); limit entries and targets need a 1-tick trade-through on futures, **also at the open**; the final forced exit pays slippage; futures sizes are whole contracts | `core._gap_exit`, `_intrabar_exit`, `_floor_qty` | `test_gap_through_stop...`, `test_stop_never_fills_above_the_best_bid`, `test_target_needs_trade_through...`, `test_futures_limit_entry_needs_trade_through_at_the_open`, `test_forced_final_exit...`, `test_futures_quantity...` |
| 6 | Longs buy the ask and sell the bid. Spread stress widens the open and close by **their own** quote's spread (an opening fill never uses a later quote); bid low/ask high move by the larger, bid high/ask low by the smaller, so bars stay valid OHLC | `core._build_quotes` | `test_bid_ask_long...`, `test_widened_real_spread_keeps_valid_ohlc`, `test_spread_stress_prices_the_open...` |
| 7 | **Look-ahead:** `prepare()` may not change price columns (engine refuses); every produced column must be unchanged when future rows are removed; `on_bar()` runs once with guarded data where reading a later bar raises, through `self.d` **and** `self.broker.d` (every index a slice can touch is checked, in any direction; negative indexes count from the end and are refused; the engine's own execution data stays separate in `Broker._d`); entries/exits up to a cut must not change when later rows are removed. `robust.py` checks every parameter set (up to 40) | `core.check_lookahead`, `core._Guarded`, `core._check_untouched`, `robust.lookahead_gate` | `test_lookahead_*`, `test_prepare_may_not_change...`, `test_reverse_slices...`, `test_guard_blocks_every_slice...`, `test_broker_data_is_guarded_too` |
| 8 | `close()` called repeatedly keeps the first request (the delay is not restarted) | `core.Broker.close` | `test_repeated_close_calls...` |
| 9 | Futures back-adjusted by difference; newest prices = real; roll spread measured at the moment of the switch (NQ: both contracts' open of the roll minute; GC: jump minus spot gold's move, see DATA_REPORT); `raw_*` columns keep unadjusted prices | `data._load_nq`, `data._load_gc`, `data._back_adjust` | `test_roll_charges_cost...`; method per roll in `cache/*_rolls.csv` |
| 10 | Walk-forward: folds are whole calendar months, OOS windows back-to-back with no gap or overlap, IS ends before OOS; OOS uses the IS winner; OOS folds run in order and carry the account balance forward | `walkforward.make_folds`, `walkforward.run` | `test_folds_*`, `test_walkforward_optimiser_only_sees_in_sample`, `test_walkforward_with_no_valid_parameters...` |
| 11 | Windows: orders before the window start are ignored (warm-up only computes indicators); contiguous windows reproduce a full run exactly | `parallel.run_job`, `Settings.trade_start_ts` | `test_warmup_positions_never_block...`, `test_windows_reproduce_full_run_exactly` (real data) |
| 12 | **Drawdown** is an exact walk over every bar in its known order: open → worst price → close. A bar's worst price is never a peak, and each low is measured from the highest open/close **before** it, so the % uses the preceding peak. When a target is hit inside a bar, that bar's adverse extreme is assumed to come before the target (pessimistic; 1-minute OHLC can't tell). Equals an independent plain loop on real data | `core.Engine.run` (`equity_open`, `equity_low`, `_pre_exit_worst`), `metrics.drawdown_walk` | `test_intraday_drawdown...`, `test_drawdown_from_an_intraday_peak...`, `test_drawdown_from_an_opening_peak...`, `test_drawdown_inside_the_exit_bar...`, `test_drawdown_percent_uses_the_peak_before...` |
| 13 | Shuffle Monte Carlo keeps final P&L identical; daily Monte Carlo uses every trading day (needs the daily equity file) and refuses `--skip` | `montecarlo.simulate`, `robust._mc_from_trades` | `test_shuffle_keeps_final_pnl...`, `test_daily_monte_carlo_rejects_skip` |
| 15 | Resampled bars never contain two contracts: a bucket with a switch is **split at the switch minute**, so the roll is charged exactly when it happens (also on a final bar) and never for positions closed before it or opened after it. Gives one shorter extra bar on those days (37 of GC's 50 rolls at 4 h / daily) | `data.resample` | `test_resampled_bars_split_at_the_roll`, `test_resampled_roll_costs_match_one_minute` (4 cases vs the 1-minute engine) |
| 14 | A dataset can only be used with its own instrument; the regression comparator is exact and exits 1 when different | `robust.check_dataset`, `tools/compare_runs.py` | `test_dataset_must_match...`, `test_compare_runs_exits_nonzero...` |

## Deliberate choices (not bugs)
- **One net position per strategy.** Entry orders only fill while flat. To reverse, call `close()` and place the new entry on the same bar: the exit happens at the next open, then the entry. No pyramiding yet.
- **OCO is on by default.** When an entry fills, the other pending entries are cancelled.
- **Ambiguous bars are resolved by rule in the engine** (nearest the open for competing entries; stop before target), counted in `notes` and listed in `result["ambiguous"]`. For NQ they can be checked against the 1-second bars with `tools/verify_orb_fills_1s.py` (prices converted from back-adjusted to raw). Each case is `agree`, `disagree` or `unresolved` (same second, or no 1-second data); unresolved cases get no replay P&L and are left out of the P&L comparison. ORB on MNQ: 1 ambiguous minute in 1,430 trades; the 1-second data confirmed both the entry and the stop-out (P&L difference $0).
- **`delay_bars` (stress)** delays when entries and `close()` become active. It doesn't delay the stop-loss/target, which sit at the broker.
- **No margin or volume model.** `Settings.max_leverage` can cap position notional at equity × N; there is no per-contract margin schedule and no check against traded volume.
- **Plateau score** = 0.5 × neighbourhood mean + 0.5 × neighbourhood worst (±1 step on every axis, diagonals included). Grid-edge choices are flagged (`plateau_choice_on_grid_edge`).
- **Walk-forward efficiency** = mean over folds of (OOS P&L per day) / (IS P&L per day of the chosen params). It's only meaningful when IS P&L is positive.
- **`robust.py all` stress-tests the plateau choice from the full-period sweep.** That choice is in-sample by nature. Stress tests measure sensitivity to execution, not edge.
- **Monte Carlo drawdown table:** the row labelled "95th pct" is the drawdown only 5% of simulations exceeded.
- **8 of GC's 50 roll spreads are estimates** (weekend rolls before 2021, no spot data). See `cache/GC_rolls.csv`.
- **Session handling is the strategy's job.** `engine/calendar.py` provides exchange holidays and 13:00 closes (half days and holiday futures sessions). ORB uses it to flatten 5 minutes before the close.
- **Guard scope.** The look-ahead guard stops accidental future reads through the documented data views. Deliberate access to private attributes (names starting with `_`) is not prevented; the prefix test is the backstop.
- **Each worker process loads its own copy of the data** (about 1–1.5 GB each). The pool is reused between stages; parameter-search jobs return summaries only.

## Reporting a problem
Please give: the file and line, a concrete input where the output is wrong, and the expected output. Best of all, add a failing test to `tests/`. Many "bugs" in backtesters are really disagreements about fill assumptions, so say which invariant above you think is broken.

## Files starting with `._`
macOS creates `._name` companion files on exFAT drives. They hold Finder metadata, not code or data, and can be ignored or deleted.

## Version history (git)
This folder is a git repository, so every change is recorded and can be undone.
- Before changing code: `git status` should be clean. Check `git log --oneline` to see recent changes.
- Make one change at a time, run the tests, then save it with a clear message:
  `git add -A && git commit -m "fix: <what and why>"`
- Never commit with failing tests. `cache/` and `results/` are not tracked (they're regenerated).
- To see what changed: `git diff` (not yet saved) or `git show <id>` (a saved change).
- To undo a saved change: `git revert <id>`. This adds a new change that reverses it; history is kept.
