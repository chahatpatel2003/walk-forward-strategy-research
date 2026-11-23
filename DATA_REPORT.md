# Data report: what's in `T9/DATA`

Audited 2026-11-22. Everything was read-only: nothing in `DATA/` was changed or added.
The scripts that produced these numbers are in `BACKTESTING/tools/`.
All times are UTC unless noted.

## Summary

| Market | Best file for backtesting | Period | 1-min bars | Quality |
|---|---|---|---|---|
| **GC** gold futures | `GC_Gold_futures/bars_1m_continuous_...parquet` | 2016-01-03 → 2025-12-31 | 3.49 M | Clean. Raw prices, so rollover gaps must be adjusted (the engine does this). |
| **NQ** Nasdaq futures | `NQ_Nasdaq100_futures/bars_1m_front_contract_...parquet` | 2021-01-04 → 2026-08-14 | 1.99 M | Clean. One missing day (2026-06-17). Raw prices, so rollover gaps must be adjusted. |
| **XAUUSD** spot gold | `XAUUSD_Gold_spot_Dukascopy/bars_1m_bid_ask_mid_...parquet` | 2021-06-29 → 2026-11-17 | 1.91 M | Clean, with **real bid and ask**, so the actual spread can be charged. |
| **NAS100** CFD | `NAS100_CFD_Dukascopy/bars_1m_mid_...parquet` | 2012-02-01 → 2021-09-30 | 2.53 M | Usable. Mid prices only. Trading hours change over the years (see below). |

Every main series passed these checks: **0 duplicate timestamps, 0 out-of-order bars, 0 missing prices, 0 zero or negative prices, 0 bars with high < low or open/close outside the high-low range**.

## Time zones: verified correct
- The busiest minutes in every series are 13:30 / 14:30 UTC, which is the 09:30 New York open in summer and winter. GC's busiest minutes also include 12:30 / 13:30 UTC, the 08:30 ET US data releases.
- **Sources line up to the minute.** I compared 1-minute price changes at offsets of −2 to +2 minutes. They only match at 0:
  - GC futures vs XAUUSD spot: correlation **0.974** at 0 min (≈0.01–0.03 at other offsets)
  - NQ futures vs NAS100 CFD (2021-01..09 overlap): **0.993** at 0 min
  - Dukascopy XAUUSD vs TradingView OANDA XAUUSD (Oct–Nov 2026): **0.998**, median price difference $0.05

## GC: COMEX gold futures (Databento)
- One stitched "front month by volume" series (`GC.v.0`), ~1,120 bars per day and ~310 trading days per year every year.
- **The `bars_1m_by_contract_2016_to_2025/` folder is the same continuous series**, not separate contracts. It has the same 3,486,356 rows, labelled `GC.v.0`. That means the price of the *other* contract at roll time isn't available.
- **50 contract switches.** Prices are **not** adjusted, so each switch shows an artificial jump of +$0 to **+$57.70** ($5,770 per GC contract). These have grown since 2023 because of higher interest rates. A backtest on the raw series would book these jumps as profit or loss, so the engine back-adjusts them.
- **How the roll spread is measured** (updated after the code audit). The jump at a switch = roll spread + the market's own move across the gap. The move is kept, not erased:
  - **22 rolls (2021–2025):** jump minus spot gold's move over the same minutes.
  - **20 rolls:** gap of under 4 hours, so the move is assumed 0. The error is gold's move during the pause.
  - **8 weekend rolls before 2021:** spread estimated from the 4 nearest measured rolls (spread/price ratio).

  Each roll's method is in `cache/GC_rolls.csv`.
- Gaps: normal daily 1-hour break, weekends, holidays. Real exchange events also show up: CME outage on 2025-11-28 (10.7 h), short sessions on Christmas Eve and Thanksgiving. One unexplained gap: **2020-06-30 14:10 → 2020-07-01 00:00 (9.8 h) is missing.**
- 3.2% of bars have high = low (quiet overnight minutes). That's normal.

## NQ: CME E-mini Nasdaq-100 futures (Databento)
- 1-min front-contract bars, ~1,135 per day. **22 rolls**, about 4 days before each quarterly expiry (Mon 22:00/23:00 UTC).
- Rollover gaps grew from about −9 pts (2021) to **+307 pts** (2026), or $6,140 per contract. The engine back-adjusts with the spread between both contracts' **open of the roll minute** (from `bars_1m_all_contracts`), the moment the switch happens. All 22 rolls had both contracts trading that minute.
- The two `contract_roll_adjust_*` files hold cumulative adjustments in ticks from an earlier build. They differ slightly from the same-minute measurement, so the engine doesn't use them.
- **Missing data: 2026-06-17 03:03 → 22:00 UTC (~19 h, almost a whole session).** It's missing from the ticks and 1-second bars too. That's where the two tick files were stitched together.
- Short sessions are present and correct: Jan 9 2025 (national day of mourning), holidays.
- Cross-checks: rebuilding 1-min bars from the 1-second bars (May 2024) matches **100%** on OHLC and volume. The front file matches the `all_contracts` file on 100% of shared bars.
- Extra NQ data beyond what the engine needs at first:
  - Trade ticks with aggressor side, 563 M rows (2021-01 → 2026-08-14)
  - Top-of-book quotes, 7.9 B rows, 222 GB (2021-01 → 2025-06)
  - 1-second bars, 74 M rows
  - Per-session volume profiles
  - 1-min buy/sell volume
  - Opening-range POC tables
- `tradingview_CME_NQ1_1m_2026-11-01_to_2026-11-20.csv` covers Nov 2026 only and doesn't overlap the Databento data, which ends 2026-08-14. It's useful for a recent out-of-sample check.

## XAUUSD: spot gold (Dukascopy)
- Use the **bid/ask/mid file**. It's a superset: the older `bars_1m_...parquet` is exactly the **bid** prices (close = bid close on 100% of bars) and ends 2026-06-28.
- **Spread (ask − bid, $ per oz):**

| Year | Typical (median) | 99th percentile | Worst |
|---|---|---|---|
| 2021–2024 | $0.33–0.38 | $0.49–0.62 | $4–6 |
| 2025 | $0.58 | $1.20 | $14.74 |
| 2026 | $0.67 | $1.90 | $12.61 |

  The spread is widest around 21:00–23:00 UTC (daily rollover). On 1 lot (100 oz), a $0.67 spread costs $67 per round trip, so the engine charges the real spread bar by bar.
- Gold futures minus spot ("basis") grew from about $1 (2021) to about $15 (2025), which reflects interest rates. That's expected, not an error.
- Gaps: only holidays, short sessions and the daily break. 369 small gaps of 2–5 min in five years.
- Raw `.bi5` tick files: 31,904 hourly files. In the folder names, **months count from 00**, Dukascopy's convention (`2021/05/29` = 29 June). They aren't needed for 1-min backtests.

## NAS100: Nasdaq-100 CFD (Dukascopy)
- Mid prices only (no bid/ask in the bars). Spreads measured from the tick files:

| Session | Median spread (pts) |
|---|---|
| 2015–2021 US cash hours | ~1.0–1.4 |
| 2018–2021 overnight | ~3 |
| 2012 | 0 (Dukascopy quoted bid = ask, so costs must be assumed) |

- **Trading hours change over time.** The 1-minute bar file:
  - 2012–early 2013: cash session only (~385 bars/day)
  - 2015–2017: partial overnight (~830 bars/day)
  - 2018 onward: nearly 24 h (~1,100 bars/day)

  **This matters:** a strategy using overnight or Asian-session data will see different inputs in different years. For cash-session strategies, use `bars_1m_mid_0930-1600_complete_days`: 2,198 complete 390-bar days.
- Some multi-day holes in 2012–2013 (e.g. 2013-05-17 → 05-22).
- Tick files: 2012-02 → 2021-09, plus one isolated month, 2026-05.

## Things to keep in mind when backtesting
1. **NQ futures (2021–2026) and NAS100 CFD (2012–2021) overlap only Jan–Sep 2021.** Together they give about 14 years of Nasdaq history on different instruments with different costs.
2. **GC (2016–2025) and XAUUSD (2021–2026) overlap 2021-06 → 2025-12.** A gold strategy should hold up on both. If it only works on one, that's a red flag.
3. Rolls: never backtest on the raw futures series without adjusting. The engine does it automatically.
4. Not in the data: economic-news calendars. Any news filter would have to come from elsewhere.
