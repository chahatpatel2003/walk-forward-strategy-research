# BACKTESTING: backtest engine for NQ / MNQ, GC / MGC, XAUUSD, NAS100

Reads market data from `T9/DATA` (**read-only, never written to**). Everything it produces stays in this folder.

```
BACKTESTING/
  DATA_REPORT.md      what's in DATA/, its quality, and the quirks to know about
  run.py              command line: run a strategy on one or more markets
  robust.py           parameter test, walk-forward, Monte Carlo, stress test
  photo_study.py      runs every photo strategy through all of the above
  timeframe_study.py  the same, on 5-min, 15-min, 1-hour, 4-hour and daily bars (TIMEFRAME_STUDY_RESULTS.md)
  STRATEGY_CATALOG.md the 53 strategy photos: what each says and whether it can be tested
  REVIEW_GUIDE.md     for code reviewers: invariants, tests, deliberate choices
  engine/             the engine (data loading, fills, costs, metrics, reports)
  strategies/         your strategies (orb.py and sma_cross.py are examples)
  tests/              hand-checked engine tests
  results/            one folder per run: summary.txt, trades.csv, daily_equity.csv, equity.png
  cache/              processed 1-minute data (safe to delete; it rebuilds in seconds)
  tools/              the data-audit scripts behind DATA_REPORT.md
```

## Running it

The Python environment lives at `~/.venvs/t9-backtesting` on the Mac's internal disk. The T9 drive is exFAT, which breaks Python package installs.

```bash
cd /Volumes/T9/BACKTESTING
~/.venvs/t9-backtesting/bin/python run.py strategies/orb.py --symbol MNQ
~/.venvs/t9-backtesting/bin/python run.py strategies/orb.py --symbol MNQ,MGC,XAUUSD --start 2022-01-01 --set rr=3 or_minutes=30
~/.venvs/t9-backtesting/bin/python run.py strategies/sma_cross.py --symbol GC --tf 60
~/.venvs/t9-backtesting/bin/python -m pytest tests -q -p no:cacheprovider
```

| Option | Meaning |
|---|---|
| `--symbol` | `NQ, MNQ, GC, MGC, XAUUSD, NAS100` (comma-separated for several) |
| `--tf` | bar size in minutes: 1, 5, 15, 60, 240, 1440. Built from 1-min bars and aligned to the 18:00 ET session open. |
| `--start / --end` | trading-day range, `YYYY-MM-DD` |
| `--set k=v ...` | override strategy parameters |
| `--commission / --slippage / --spread` | override default costs. Defaults are in `engine/instruments.py`; edit them to match your broker. |
| `--data NAS100_RTH` | NAS100 with complete 09:30–16:00 days only |
| `--force` | publish even if the look-ahead check fails (by default nothing is saved; with `--force` the failure is recorded in the report) |

## Robustness testing (`robust.py`)

```bash
PY=~/.venvs/t9-backtesting/bin/python
$PY robust.py sweep       strategies/orb.py --symbol MNQ --grid rr=1.5,2,2.5,3 or_minutes=10,15,20,30
$PY robust.py walkforward strategies/orb.py --symbol MNQ --grid rr=1.5,2,3 or_minutes=10,15,30 --is-months 24 --oos-months 6
$PY robust.py montecarlo  --from results/<a run or walk-forward folder> --ruin 3000
$PY robust.py stress      strategies/orb.py --symbol MNQ --set rr=2 or_minutes=30
$PY robust.py all         strategies/orb.py --symbol MNQ --grid rr=1.5,2,3 or_minutes=10,15,30 --ruin 3000
```

| Test | What it does | Main outputs |
|---|---|---|
| **sweep** (parameter test) | Runs every grid combination. Plateau score = how good a setting's *neighbourhood* is, so isolated lucky spikes stand out. Shows sensitivity per parameter. | `sweep_report.txt`, `sweep_heatmaps.png`, `sweep_results.csv` |
| **walkforward** | Cuts our own history into folds: optimise on `--is-months`, then trade the winner on the next `--oos-months` it never saw, and repeat. Stitches the out-of-sample periods into one honest equity curve. `--anchored` keeps the in-sample start fixed. | `walkforward_report.txt`, `walkforward_equity.png`, `walkforward_folds.csv`, `walkforward_oos_trades.csv` |
| **montecarlo** | 10,000 re-orderings (`shuffle`) or re-samplings (`bootstrap`, `daily` blocks) of the trades. Gives the distribution of drawdown, final P&L and losing streaks, the chance of hitting a `--ruin` loss limit, and a safe size multiplier. `--skip` / `--haircut` add missed trades or worse fills. | `montecarlo_report.txt`, `montecarlo.png` |
| **stress** | Re-runs with 2× commission, +1/+2 ticks slippage, wider spreads, 1–2 bar delays, and all of them combined. Also tests P&L without the best 1%/5% of trades, inside known turbulent periods, on volatile vs calm days, and over the worst month / 3 months / 12 months. | `stress_report.txt` + CSVs |
| **all** | Runs sweep, then walk-forward, then Monte Carlo on the walk-forward OOS trades, then stress. Writes `ROBUSTNESS_REPORT.md` with a pass/fail checklist (rules of thumb, not guarantees). | one folder with everything |

Common options:
- `--objective sharpe|profit_factor|net_pnl|expectancy|return_dd`
- `--min-trades 30`: settings with fewer trades are ignored
- `--select plateau|best`
- `--workers N`: parallel processes; the default is sized to RAM
- `--warmup-days`

Every command runs the look-ahead check first and stops if it fails.

For reviewers: see **REVIEW_GUIDE.md** (invariants, where they're tested, deliberate choices).

## The photo strategies (`strategies/photos/`, `photo_study.py`)
The 13 testable strategies from the photos (A1–A13) and the gold futures-vs-spot pair (B1) are in `strategies/photos/`. Each file's header gives the photo it came from, the rules, and any assumption that had to be made. `STRATEGY_CATALOG.md` lists all 53 photos, including the ideas that can't be tested with this data.

```bash
~/.venvs/t9-backtesting/bin/python photo_study.py                  # every strategy x market x session (resumes if interrupted)
~/.venvs/t9-backtesting/bin/python photo_study.py --only a01 b01   # some strategies
```

For each run the study does three things:
1. A full-history backtest with the photo's own rules.
2. The full robustness pipeline, with each strategy's own parameter ranges (`GRID`).
3. A buy-and-hold comparison over the same periods.

Results go to `results/PHOTO_STUDY/`: `PHOTO_STUDY_REPORT.md`, `study_rows.csv`, and one folder per run.

### Other bar sizes (`timeframe_study.py`)
```bash
~/.venvs/t9-backtesting/bin/python timeframe_study.py                       # every strategy on 5m/15m/1h/4h/daily (resumes)
~/.venvs/t9-backtesting/bin/python timeframe_study.py --only a01 --tfs 60   # one strategy, 1-hour bars
~/.venvs/t9-backtesting/bin/python tools/timeframe_report.py > results/TIMEFRAME_STUDY/tables.md
~/.venvs/t9-backtesting/bin/python tools/timeframe_costs.py > results/TIMEFRAME_STUDY/costs.md          # avg trade before/after costs
~/.venvs/t9-backtesting/bin/python tools/timeframe_portfolio.py > results/TIMEFRAME_STUDY/portfolio.md  # robust runs traded together
~/.venvs/t9-backtesting/bin/python tools/write_timeframe_report.py       # TIMEFRAME_STUDY_RESULTS.md from the tables above
~/.venvs/t9-backtesting/bin/python timeframe_study.py --keys a05_zscore_mean_reversion:MGC:rth:15   # re-run exact configurations
~/.venvs/t9-backtesting/bin/python tools/recheck_lookahead.py --rows results/TIMEFRAME_STUDY/rows.csv --out <file.csv>  # gate only
~/.venvs/t9-backtesting/bin/python tools/recheck_efficiency.py results/TIMEFRAME_STUDY/rows.csv  # efficiency rule on saved folds
```
Lengths stay in bars (RSI(3) on 5-minute bars = three 5-minute bars). Thresholds a strategy declares as a % of price
(`PRICE_PCT`: A1, A2, A11) are scaled by the square root of the bar size (1% on daily cash-session bars = 0.11% on
5-minute bars). A8, A9 and A10 decide once per week or month on fixed dates and run on daily bars only. Results:
`results/TIMEFRAME_STUDY/rows.csv`, one folder per run under `results/TIMEFRAME_STUDY/<bars>/`.

Other options:
- **`--session rth`** (in `run.py`, `robust.py`): New York cash-session bars only: exchange trading days, 09:30 to the close (13:00 on half days). Daily strategies are run both ways, and never make decisions on holiday sessions.
- **Pairs:** a strategy with `ENGINE = "pairs"` trades two legs (`engine/pairs.py`): futures leg with commission and slippage, XAUUSD leg at bid/ask, both filled at the next open. Use it with `robust.py`.

## How fills work (and why results aren't flattering)
- A strategy decides at a bar's **close**. Its orders fill from the **next** bar. It can't trade on a price it hasn't seen.
- **Inside each bar, things happen in time order:**
  1. At the open: pending close requests, gaps through stops/targets, and market orders.
  2. Then the rest of the bar.

  If a position is stopped out inside a bar, no new trade can fill in that same bar.
- **Market** orders fill at the open plus slippage (default 1 tick per side on futures). **Stop** orders fill at the stop price, or at the open on a gap, plus slippage. A stop never fills better than the quotes in the bar.
- **Limit orders and targets** must trade *through* the price by 1 tick on futures, at the open too.
- **Same-bar ambiguity is resolved pessimistically:**
  - If a bar hits both stop-loss and target, the stop-loss wins.
  - If both sides of an OCO trigger in one bar, the side nearest the open is taken; these bars are counted in `notes`.
  - A target on the entry bar only counts if price must have reached it *after* the entry.
- **Bid/ask:**
  - XAUUSD uses the real Dukascopy bid/ask: buys at the ask, sells at the bid.
  - NAS100 charges a fixed 1.2-pt spread.
  - Futures trade at the traded price plus commission and slippage.
- **Futures rolls:** prices are back-adjusted with the roll spread measured at the moment of the switch, and a held position pays the cost of rolling. Details are in `cache/*_rolls.csv`. Unadjusted prices are in the `raw_o/h/l/c` columns.
- **Drawdown** walks every bar in time order (open, worst price, close) and measures each low from the peak before it. If a target is hit inside a bar, that bar's adverse move is assumed to have come first (pessimistic).
- **Resampled futures bars** stay one bar per period. A contract switch inside a bar is flagged, and its roll cost is charged if a position is held after that bar's open.
- **Look-ahead check:** every run checks that indicators and trade decisions don't change when future data is removed. It also replays the strategy with data that errors if a later bar is read. `robust.py` checks every parameter set it will test. A strategy's `prepare()` may only add columns; changing prices is refused.

## Writing a strategy
Copy `strategies/orb.py`. A strategy has two methods:

```python
from engine import Strategy

class MyStrategy(Strategy):
    params = dict(risk_usd=500, rr=2.0)          # defaults, changeable with --set

    def prepare(self, df):                       # vectorized indicators, using ONLY past data
        df["ma"] = df.c.rolling(50).mean()
        return df

    def on_bar(self, i):                         # called after bar i closes
        d, b = self.d, self.broker               # d["c"][i], d["ma"][i], d["ny_min"][i], d["tday"][i] ...
        if b.flat and d["c"][i] > d["ma"][i]:
            b.buy(sl_dist=20, tp_r=self.p["rr"], risk_usd=self.p["risk_usd"])

STRATEGY = MyStrategy
```

Data columns: `o h l c v` (back-adjusted), `ny_min` (New York minute of day, 09:30 = 570), `ny_dow` (Mon = 0), `tday` (trading day; the 18:00 ET open belongs to the next day), `contract`. XAUUSD also has `bo..bc` / `ao..ac` (bid/ask).

**Placing orders:**
- `b.buy(...)` / `b.sell(...)`
  - `kind`: `"market"` / `"stop"` / `"limit"`, with `price=` for stop and limit
  - stop-loss: `sl=` (price) or `sl_dist=` (points)
  - target: `tp=` (price), `tp_dist=` (points) or `tp_r=` (multiple of risk)
  - size: `qty=` or `risk_usd=` / `risk_pct=`
  - `valid_bars=` (order expires after N bars), `tag=`
- `b.close()` exits at the next open.
- `b.cancel_all()`, `b.set_sl(price)`, `b.set_tp(price)`.

**Reading state:** `b.flat`, `b.position`, `b.equity`, `b.bars_in_trade()`.

Entries only fill while flat. To reverse, call `close()` and place the new entry on the same bar. When one entry fills, the other pending entries are cancelled (one-cancels-other). Calling `close()` again while a close is pending changes nothing. Sizing options: `qty=`, `risk_usd=`, `risk_pct=` or `notional_usd=`; futures are rounded down to whole contracts.

Exchange calendar: `from engine.calendar import session_close_minute, holidays, trading_days` (holidays and 13:00 closes, published in advance).

## Known limits
- One position at a time per strategy (no pyramiding or scaling in yet).
- Ambiguous bars (both stop and target inside one bar) are resolved pessimistically. NQ has 1-second bars that could settle these exactly; that's not wired in yet.
- 8 of GC's 50 roll adjustments are estimates (weekend rolls before 2021; see DATA_REPORT.md).
- No news-calendar filter (no calendar in DATA).
