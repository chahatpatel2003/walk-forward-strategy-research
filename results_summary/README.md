# Result tables

These are the machine-readable tables behind every number in the main README and the study reports, one row per
backtest. They hold results only, with no market price data. The complete raw output of every run (each trade, the
daily equity, the walk-forward folds, Monte Carlo, stress tests and charts) is attached to the
[full-results release](https://github.com/chahatpatel2003/walk-forward-strategy-research/releases/tag/full-results).

| Folder | What it is | Rows |
|---|---|---|
| [`daily_study/rows.csv`](daily_study/rows.csv) | Daily-bar study: 14 strategies × instruments × sessions | 94 |
| [`timeframe_study/rows.csv`](timeframe_study/rows.csv) | Same strategies on 5-min, 15-min, 1-hour, 4-hour and daily bars | 373 |
| [`intraday_study/rows.csv`](intraday_study/rows.csv) | Intraday versions (flat every day by 15:55 ET) on 1, 5, 15 and 60-minute bars | 144 |
| [`timeframe_study/`](timeframe_study) | Formatted tables, cost per trade by bar size, portfolio results, headline numbers | — |
| [`intraday_study/account.json`](intraday_study/account.json) | Intraday winners replayed on one $10,000 account | — |
| [`account_10k/`](account_10k) | $10,000 single-account replays: 2 × ATR sizing (`atr`), real 2 × ATR stops (`stops`, `stop_rows.csv`) and all strategies on one account, held or closed at 16:00 ET (`combined`) | — |
| [`dashboard_data/`](dashboard_data) | The data behind the results dashboard (shortlist, every passing configuration, equity curves, monthly account returns) | — |

## Main columns in the `rows.csv` files

| Column | Meaning |
|---|---|
| `strategy`, `market`, `session`, `bars` | Strategy file, instrument (NAS100, MNQ, MGC, XAUUSD, GC), `rth` = New York cash hours or `full` = all hours, bar size in minutes |
| `period` | First and last day of data used |
| `trades`, `net`, `pf`, `win_pct`, `max_dd`, `sharpe` | Full-history results with the best parameters: trade count, net profit ($), profit factor, win rate, maximum drawdown ($), Sharpe ratio |
| `avg_win`, `avg_loss`, `payoff_ratio`, `expectancy`, `trades_per_year` | Average winning and losing trade ($), their ratio, average $ per trade, trading frequency |
| `best_params`, `pct_param_sets_profitable` | Parameters chosen, and the share of all parameter sets tried that were profitable |
| `wf_oos_*` | Walk-forward out-of-sample results: parameters picked on earlier data only, then traded on the next window |
| `wf_folds_profitable_pct`, `wf_efficiency` | Share of out-of-sample windows that made money; out-of-sample vs. in-sample return per year |
| `mc_prob_loss_pct` | Monte Carlo: chance of ending with a loss when the out-of-sample results are resampled |
| `stress_all_net`, `stress_worst_net`, `stress_worst_scenario`, `stress_scenarios_breached` | Stress tests: net profit with doubled commission, wider spreads, extra slippage and fills delayed by 1–2 bars, all of them together, and the worst single scenario |
| `buy_hold_*` | Buy-and-hold of the same instrument over the same period, for comparison |
| `checks_passed`, `checks_total` | Robustness checks passed; a configuration is listed as robust only when it passes all of them |
| `account_model`, `capital_exhausted_on` | Account simulation used, and the date the account ran out of money if it did |

All dollar figures use $100,000 of contract value per trade with commission, slippage, spreads and roll costs
included, unless the file says otherwise (the `account_10k` files use 2% of the balance per trade).
