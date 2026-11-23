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
~/.venvs/t9-backtesting/bin/python -m pytest tests -q -p no:cacheprovider          # 29 tests, ~2 s
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
| `engine/metrics.py` | Statistics; `result_from_trades` (trade list → equity); `score` (objective for optimisation) |
| `engine/report.py` | Writes a single run's results |
| `engine/parallel.py` | `Job` (one backtest on one date window) and `run_many` (process pool) |
| `engine/sweep.py` | Parameter test: grid, plateau score, heatmaps |
| `engine/walkforward.py` | Fold construction, IS optimisation → OOS trading, stitching |
| `engine/montecarlo.py` | Shuffle / bootstrap / daily-block simulations |
| `engine/stress.py` | Execution stress re-runs, outlier dependence, turbulent periods, volatility regimes |
| `run.py`, `robust.py` | Command-line entry points |
| `tests/test_engine.py` | Hand-computed fill / cost / roll / look-ahead scenarios |
| `tests/test_robust.py` | Fold boundaries, optimiser isolation, plateau maths, Monte Carlo properties, stress settings, real-data window integration test |

## Invariants: what must stay true

| # | Invariant | Where | Test |
|---|---|---|---|
| 1 | A strategy acts on bar *i*'s close; nothing it orders can fill before bar *i+1* | `core.py` `_fill_entries` (`placed_i + delay_bars >= i` → not yet) | `test_market_order_fills_next_open...`, `test_order_placed_on_last_bar...` |
| 2 | `prepare()` indicators must not use future rows. Every run re-computes them on truncated data and compares. | `core.check_lookahead`; `robust.py` aborts on failure | `test_lookahead_checker` |
| 3 | If stop-loss and target are both inside one bar, the stop-loss wins. A stop-loss inside the entry bar counts as hit. | `core._check_exits` | `test_both_stop_and_target...`, `test_stop_entry_and_stop_loss_in_same_bar...` |
| 4 | Gaps through stops fill at the open (worse), plus slippage | `_check_exits`, `_fill_entries` | `test_gap_through_stop...`, `test_stop_entry_gapping...` |
| 5 | Futures limit orders need price to trade 1 tick *through* the limit | `Engine.through` | `test_limit_must_trade_through...` |
| 6 | Longs buy the ask and sell the bid; long stops trigger on the bid, short stops on the ask | `_check_exits`, `_fill_entries` | `test_bid_ask_long_buys_ask...` |
| 7 | Futures are back-adjusted by difference, newest prices = real prices. Rolling a held position costs 2 sides of commission + slippage. Back-adjusted P&L = true P&L of rolling. | `data._back_adjust`, `Engine.run` step 1 | `test_roll_charges_cost...`; on real data the last adjusted close equals the raw close |
| 8 | Walk-forward: every in-sample window ends before its OOS window starts; OOS windows are back-to-back and never overlap; OOS uses the IS winner | `walkforward.make_folds`, `walkforward.run` | `test_folds_*`, `test_walkforward_optimiser_only_sees_in_sample` |
| 9 | A window counts only trades **entered** on/after its start; warm-up data never adds trades; contiguous windows reproduce a full run exactly | `parallel.run_job` | `test_windows_reproduce_full_run_exactly` (real data) |
| 10 | Shuffle Monte Carlo keeps final P&L identical in every simulation | `montecarlo.simulate` | `test_shuffle_keeps_final_pnl...` |

## Deliberate choices (not bugs)
- **One net position per strategy.** Entry orders only fill while flat. To reverse, call `close()` and place the new entry on the same bar: the exit happens at the next open, then the entry. No pyramiding yet.
- **OCO is on by default.** When an entry fills, the other pending entries are cancelled.
- **`delay_bars` (stress)** delays when entries and `close()` become active. It doesn't delay the stop-loss/target, which sit at the broker. A delayed stop entry can miss a quick spike, which is intended.
- **Equity in two forms.** `run.py` full runs use mark-to-market at each bar close. Windowed runs (sweep, walk-forward, stress) use realized P&L booked on the exit day (`metrics.result_from_trades`). Max drawdown can differ slightly between the two. Ranking uses the realized form consistently.
- **Plateau score** = 0.5 × neighbourhood mean + 0.5 × neighbourhood worst (±1 step on every axis, diagonals included). Grid-edge settings have fewer neighbours, so `plateau_choice_on_grid_edge` flags them.
- **Walk-forward efficiency** = mean over folds of (OOS P&L per day) / (IS P&L per day of the chosen params). It's only defined when IS P&L is positive.
- **`robust.py all` stress-tests the plateau choice from the full-period sweep.** That choice is in-sample by nature. Stress tests measure sensitivity to execution, not edge.
- **Monte Carlo drawdown table:** the row labelled "95th pct" is the drawdown that only 5% of simulations exceeded (it's `np.percentile(maxdd, 5)` because drawdowns are negative).
- **About 13 of GC's 50 roll spreads are approximate.** They're estimated across the Sunday open, so they include the weekend move (see DATA_REPORT.md). Only the other contract's price would fix this, and DATA doesn't have it.
- **Intraday ambiguity is resolved pessimistically on 1-min bars.** NQ 1-second bars exist and could settle it exactly; that's not implemented yet.

## Reporting a problem
Please give: the file and line, a concrete input where the output is wrong, and the expected output. Best of all, add a failing test to `tests/`. Many "bugs" in backtesters are really disagreements about fill assumptions, so say which invariant above you think is broken.

## Files starting with `._`
macOS creates `._name` companion files on exFAT drives. They hold Finder metadata, not code or data, and can be ignored or deleted.
