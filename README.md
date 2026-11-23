# BACKTESTING: backtest engine for NQ / MNQ, GC / MGC, XAUUSD, NAS100

Reads market data from `T9/DATA` (**read-only, never written to**). Everything it produces stays in this folder.

```
BACKTESTING/
  DATA_REPORT.md      what's in DATA/, its quality, and the quirks to know about
  run.py              command line: run a strategy on one or more markets
  robust.py           parameter test, walk-forward, Monte Carlo, stress test
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

## How fills work (and why results aren't flattering)
- A strategy decides at a bar's **close**. Its orders fill from the **next** bar. It can't trade on a price it hasn't seen.
- **Market** orders fill at the next open plus slippage (default 1 tick per side on futures).
- **Stop** orders fill at the stop price, or at the open if price gaps past it, plus slippage.
- **Limit** orders must trade *through* the price by 1 tick on futures (a touch isn't a fill).
- If a bar hits **both stop-loss and target**, the stop-loss is assumed to have come first. Same if the stop-loss is inside the bar the entry filled on.
- **XAUUSD** uses the real Dukascopy bid/ask: buys at the ask, sells at the bid, stops trigger on the right side of the quote.
  - **NAS100** has mid prices only, so it charges a fixed spread (1.2 pts by default).
  - Futures trade at the traded price plus commission and slippage.
- **Futures rolls**: prices are back-adjusted, so roll jumps don't appear as fake profit. A position held across a roll is charged the cost of rolling. Roll details are in `cache/NQ_rolls.csv` and `cache/GC_rolls.csv`.
- **Look-ahead check**: every run re-computes your indicators on cut-off copies of the data. If any value changes when future bars are removed, the run is flagged `lookahead_check FAILED`.

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

Entries only fill while flat. To reverse, call `close()` and place the new entry on the same bar. When one entry fills, the other pending entries are cancelled (one-cancels-other).

## Known limits
- One position at a time per strategy (no pyramiding or scaling in yet).
- Ambiguous bars (both stop and target inside one bar) are resolved pessimistically. NQ has 1-second bars that could settle these exactly; that's not wired in yet.
- About 13 of GC's 50 roll adjustments are approximate (the roll happened at the Sunday open; see DATA_REPORT.md).
- No news-calendar filter (no calendar in DATA).
