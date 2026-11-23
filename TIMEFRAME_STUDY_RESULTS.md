# Timeframe study: can the photo strategies trade 10–15 times a month?

*Generated November 23, 2026 by `tools/write_timeframe_report.py` from `results/TIMEFRAME_STUDY/rows.csv` (373
runs, 0 errors). Every number below comes from that file, from the run folders it points to, or from the helper
tables in the same folder (`tables.md`, `costs.md`, `portfolio.md`). Reproduce with the commands at the end.*

*Tenth revision (FIX_REPORT.md, "Tenth review"): a run that hit $0 in ANY single stress scenario no longer counts as
surviving; walk-forward efficiency is withheld when too few folds were scored or the in-sample profit is near zero;
roll slippage is counted once in the cost table; the combined book shows carried-in positions, a flat-start view and
gross exposure. 19 configurations whose saved paths could have changed under the new entry-fill breach rule were
re-run with the current code; the other rows are the saved runs with the report-side rules applied to their saved
tables.*

## Short answer

1. **No single strategy does it.** Of 373 runs, **45** passed all key checks, and
   **0** of those trade 10 or more times a month. The most frequent runs that passed everything are
   A07 on NAS100 4-hour bars, at 9.9 trades a month over the whole history
   (4.1 out-of-sample), and A07 on XAUUSD 4-hour bars, at 6.5
   (4.2 out-of-sample).
2. **Shorter bars give many more trades, but they lose money after costs.** On 5-minute bars the median run trades
   34 times a month. 51 of 69 runs have an edge *before* costs, yet only
   8 are profitable *after* costs. Each trade pays about the same costs whatever the bar size, while the
   average move per trade shrinks with the bar. Nothing on 5- or 15-minute bars passed all checks, and 61 of the
   64 runs that hit $0 somewhere are on those two bar sizes.
3. **1-hour and 4-hour bars are where extra trades still hold up.** 4 runs passed on 1-hour bars and
   15 on 4-hour bars, against 26 on daily. The passing 1-hour runs trade a median
   2.8 (range 1.7–5.9) times a month, the 4-hour runs 1.56 (range 0.25–9.89), and the passing daily runs
   0.6 (range 0.3–2.1).
4. **10–15 a month (and more) comes from running several of them together, on separate accounts.** One run per
   strategy and market among the runs that passed made **32.1 trades a month** on MNQ + gold from 2024-06-03 to
   2025-12-31 (18.9 months): net **$218,785**, max drawdown
   **−$27,165** on daily closes, profitable in 15 of 19 months. On the longer NAS100 + MGC
   history (2019-01-02 to 2021-09-30, COVID crash included) it made **22.2 a month**, net
   $259,737, max drawdown −$74,233. Three caveats (section 7): these are
   15 (and 10) separately sized accounts, with up to 9 positions open at the same moment and
   gross exposure up to $891,620; the runs were *selected* using checks that include their
   out-of-sample results; and per account the book earned less than holding gold over the same dates.

## 1. What was tested

* **Strategies:** the 13 photo strategies (A01–A13) and the gold futures-vs-spot pair (B01), with the same rules as the
  daily study.
* **Markets:**
  * MNQ (micro Nasdaq futures): 2021-01-05 → 2026-08-14, 5.6 years.
  * NAS100 (CFD): 2012-02-01 → 2021-09-30, 9.7 years.
  * MGC (micro gold futures): 2016-01-04 → 2025-12-31, 10.0 years.
  * XAUUSD (spot gold): 2021-06-29 → 2026-11-17, 5.4 years.

  Each market was tested on the New York cash session and on the full session.
* **Bar sizes:**
  * 5-minute, 15-minute, 1-hour, 4-hour and daily for A01–A07, A11, A12 and B01.
  * A08 (weekly RSI), A09 (turn of the month) and A10 (10-month average) decide on calendar dates, so shorter bars
    can't make them trade more. They ran on daily bars only.
  * A13 (order flow, needs NQ buy/sell volume) ran on 1-, 5-, 15- and 60-minute cash-session bars.
* **How rules were translated to other bar sizes:**
  * Lengths stay in bars: RSI(3) is 3 bars on any bar size.
  * Thresholds written as a percentage of price (A01 "1% below VWAP", A02's VWAP buffer, A11's momentum threshold)
    are scaled by √(bar length ÷ original bar length), because a typical move grows with the square root of time.
    A daily bar counts as one session (390 cash minutes or 1,380 full minutes). For example, A01's 1% becomes 0.11%
    on 5-minute cash bars. The grid tested around each scaled value is in the run folders.
  * Indicator warm-up is three times the longest lookback.
* **Same pipeline for every run as the daily study:**
  * Full history with the photo's settings.
  * Parameter grid with a look-ahead check over the whole period.
  * Walk-forward: optimise in-sample, trade the next window unseen. Windows are 18 + 6 months for bars up to 1 hour,
    36 + 12 months for 4-hour and daily, because those trade too rarely to optimise on 18 months.
  * Monte Carlo (5,000 paths).
  * 9 execution-stress scenarios: double costs, extra slippage, wider spreads, 1–2 bar delays, all combined.
  * The 13-item checklist.
* **Account and costs:** each run trades its own $100,000 account. Most strategies size a trade at about $100,000 of
  contract value; A12 sizes by risk ($500 a trade), so its positions vary (see the entry-notional columns in section 7).
  The account stops trading if it hits $0. Costs:
  * MNQ and MGC: $0.75 commission per side per contract, plus 1 tick of slippage.
  * XAUUSD: the real recorded bid/ask.
  * NAS100: a fixed 1.2-point spread.
* **"Passed all key checks"** means all of these:
  * profitable out-of-sample with out-of-sample PF ≥ 1.2;
  * Monte Carlo chance of a loss under 10%;
  * still profitable under the combined execution stress, **and** in every single stress scenario;
  * never hit $0: full history, walk-forward, the combined stress **or any single stress scenario**;
  * at most one of the 13 checklist items not passed. The walk-forward efficiency item counts as not passed when the
    ratio is not available: fewer than 50% of the scheduled folds were scored, or the pooled
    in-sample profit is below 1% of capital a year (a ratio over a near-zero denominator).

## 2. Results by bar size

| bars   |   runs |   median trades / month |   profitable full history |   walk-forward possible |   profitable out-of-sample |   passed all key checks |   hit $0 somewhere |   median win % |   median PF |
|:-------|-------:|------------------------:|--------------------------:|------------------------:|---------------------------:|------------------------:|-------------------:|---------------:|------------:|
| 1-min  |      1 |                   374.3 |                         0 |                       1 |                          0 |                       0 |                  0 |           45.4 |        0.82 |
| 5-min  |     70 |                    34   |                         5 |                      70 |                          8 |                       0 |                 41 |           55.3 |        0.78 |
| 15-min |     70 |                    20   |                        22 |                      70 |                         22 |                       0 |                 20 |           61.1 |        0.94 |
| 1-hour |     70 |                     5.7 |                        35 |                      67 |                         37 |                       4 |                  3 |           63.9 |        1    |
| 4-hour |     69 |                     2.1 |                        53 |                      68 |                         50 |                      15 |                  0 |           65.5 |        1.2  |
| daily  |     93 |                     0.5 |                        84 |                      62 |                         54 |                      26 |                  0 |           65.7 |        2.05 |

"Hit $0 somewhere" counts runs that ran the $100,000 account to zero in the full history, the walk-forward, or any
stress scenario. On the plain full history alone: 29 on 5-min, 10 on 15-min, 1 on 1-hour, 0 on 4-hour, 0 on daily bars.

## 3. Why the short bars fail: costs per trade

Every out-of-sample trade, before and after costs. Fill prices already include slippage and the bid/ask spread, so
"before costs" adds back commission, roll charges, fill slippage and the spread, each once. This describes the
trades that were executed; it is not a re-run with zero costs.

| bars   | market      |   runs |   OOS trades |   avg trade before costs $ |   avg costs per trade $ |   avg trade after costs $ |   runs profitable before costs |   runs profitable after costs |
|:-------|:------------|-------:|-------------:|---------------------------:|------------------------:|--------------------------:|-------------------------------:|------------------------------:|
| 1-min  | all markets |      1 |         6769 |                       0.34 |                    2.5  |                     -2.16 |                              1 |                             0 |
| 1-min  | MNQ         |      1 |         6769 |                       0.34 |                    2.5  |                     -2.16 |                              1 |                             0 |
| 5-min  | all markets |     69 |       190371 |                       4.14 |                   17.05 |                    -12.91 |                             51 |                             8 |
| 5-min  | MNQ         |     18 |        54563 |                       3.08 |                    6.4  |                     -3.33 |                             13 |                             3 |
| 5-min  | NAS100      |     17 |        50480 |                       8.1  |                   23.96 |                    -15.86 |                             15 |                             3 |
| 5-min  | MGC         |     17 |        49090 |                       1.2  |                   20.66 |                    -19.47 |                             11 |                             1 |
| 5-min  | XAUUSD      |     17 |        36238 |                       4.23 |                   18.58 |                    -14.35 |                             12 |                             1 |
| 15-min | all markets |     69 |       103533 |                       8.31 |                   15.7  |                     -7.39 |                             52 |                            22 |
| 15-min | MNQ         |     18 |        28885 |                       4.21 |                    5.71 |                     -1.5  |                             11 |                             6 |
| 15-min | NAS100      |     17 |        28340 |                      17.25 |                   21.53 |                     -4.28 |                             16 |                             6 |
| 15-min | MGC         |     17 |        29587 |                       3.58 |                   18.7  |                    -15.11 |                             12 |                             4 |
| 15-min | XAUUSD      |     17 |        16721 |                       8.6  |                   17.79 |                     -9.19 |                             13 |                             6 |
| 1-hour | all markets |     66 |        36721 |                      25.42 |                   15.74 |                      9.68 |                             52 |                            37 |
| 1-hour | MNQ         |     16 |         7562 |                      35.76 |                    5.77 |                     29.99 |                             13 |                            13 |
| 1-hour | NAS100      |     16 |        11702 |                      25.05 |                   19.52 |                      5.53 |                             14 |                             7 |
| 1-hour | MGC         |     17 |        11504 |                      15.62 |                   17.2  |                     -1.58 |                             13 |                             7 |
| 1-hour | XAUUSD      |     17 |         5953 |                      31.91 |                   18.13 |                     13.78 |                             12 |                            10 |
| 4-hour | all markets |     67 |         8788 |                      94.09 |                   15.78 |                     78.32 |                             54 |                            50 |
| 4-hour | MNQ         |     17 |         1246 |                     134.33 |                    4.47 |                    129.86 |                             15 |                            15 |
| 4-hour | NAS100      |     16 |         3046 |                     131.89 |                   16.83 |                    115.06 |                             16 |                            16 |
| 4-hour | MGC         |     17 |         3342 |                      41.4  |                   16.69 |                     24.71 |                             13 |                            10 |
| 4-hour | XAUUSD      |     17 |         1154 |                     103.49 |                   22.58 |                     80.91 |                             10 |                             9 |
| daily  | all markets |     62 |         2975 |                     424.51 |                   19.01 |                    405.5  |                             55 |                            54 |
| daily  | MNQ         |     16 |          523 |                     438.96 |                    4.77 |                    434.2  |                             14 |                            14 |
| daily  | NAS100      |     16 |         1048 |                     549.51 |                   18.36 |                    531.15 |                             16 |                            16 |
| daily  | MGC         |     16 |         1023 |                     306.05 |                   19.49 |                    286.56 |                             14 |                            14 |
| daily  | XAUUSD      |     14 |          381 |                     378.95 |                   39.07 |                    339.88 |                             11 |                            10 |

What the table shows:

* **The edge is real but small.** On 5-minute bars the average trade made **$4.14 before costs** and paid
  **$17.05** in costs.
* **The edge grows with the bar; costs don't.** The average trade before costs is $25 on 1-hour bars,
  $94 on 4-hour and $425 on daily, while costs stay at
  $16–19 a trade on 5-minute to daily bars.
* **MNQ is the cheapest market to trade often** ($5.77 a trade on 1-hour bars), and on 1-hour bars it
  makes $29.99 a trade after costs, against $13.78 on XAUUSD,
  $5.53 on NAS100 and −$1.58 on MGC.

## 4. Every strategy on every bar size

Cells show runs that passed all key checks / runs, then the median trades per month:

| strategy                                | 1-min          | 5-min          | 15-min        | 1-hour        | 4-hour       | daily        |
|:----------------------------------------|:---------------|:---------------|:--------------|:--------------|:-------------|:-------------|
| A01 RSI+EMA+VWAP pullback               | -              | 0/8 · 30.0/mo  | 0/8 · 19.1/mo | 0/8 · 5.9/mo  | 2/8 · 2.1/mo | 6/8 · 0.5/mo |
| A02 Stochastic+KAMA+VWAP                | -              | 0/8 · 20.7/mo  | 0/8 · 7.7/mo  | 0/8 · 1.9/mo  | 0/8 · 0.5/mo | 0/8 · 0.1/mo |
| A03 Williams %R+EMA+VWAP                | -              | 0/8 · 34.9/mo  | 0/8 · 19.7/mo | 1/8 · 5.8/mo  | 1/8 · 1.8/mo | 3/8 · 0.5/mo |
| A04 RSI+EMA50+VWAP                      | -              | 0/8 · 30.9/mo  | 0/8 · 17.4/mo | 1/8 · 5.0/mo  | 5/8 · 1.8/mo | 6/8 · 0.4/mo |
| A05 Z-score mean reversion (long+short) | -              | 0/8 · 37.0/mo  | 0/8 · 23.3/mo | 0/8 · 11.4/mo | 1/8 · 3.3/mo | 0/8 · 0.8/mo |
| A06 Rubber Band                         | -              | 0/8 · 44.0/mo  | 0/8 · 32.6/mo | 0/8 · 10.3/mo | 0/8 · 3.8/mo | 4/8 · 0.8/mo |
| A07 MFI reversal                        | -              | 0/8 · 60.8/mo  | 0/8 · 46.9/mo | 0/8 · 26.2/mo | 2/8 · 8.4/mo | 3/8 · 2.0/mo |
| A08 Weekly RSI                          | -              | -              | -             | -             | -            | 0/8 · 0.2/mo |
| A09 Turn of the month                   | -              | -              | -             | -             | -            | 3/8 · 1.0/mo |
| A10 Faber 10-month MA                   | -              | -              | -             | -             | -            | 0/8 · 0.1/mo |
| A11 Time-series momentum                | -              | 0/8 · 30.9/mo  | 0/8 · 11.3/mo | 1/8 · 3.1/mo  | 3/8 · 1.0/mo | 1/8 · 0.2/mo |
| A12 Volatility squeeze breakout (15m)   | -              | 0/4 · 11.9/mo  | 0/4 · 16.9/mo | 1/4 · 5.1/mo  | 1/4 · 1.1/mo | 0/4 · 0.2/mo |
| A13 Order-flow imbalance (1m, NQ)       | 0/1 · 374.3/mo | 0/1 · 167.7/mo | 0/1 · 78.5/mo | 0/1 · nan/mo  | -            | -            |
| B01 Gold futures vs spot pair (1h)      | -              | 0/1 · 27.8/mo  | 0/1 · 17.1/mo | 0/1 · 2.4/mo  | 0/1 · 0.1/mo | 0/1 · nan/mo |

Medians across the market/session runs of each cell. "Avg win ÷ avg loss" is the reward-to-risk ratio actually
achieved (average winning trade ÷ average losing trade):

| strategy   | bars   |   runs |   trades/mo |   win % |   avg win ÷ avg loss |     PF |   median net $ |   profitable | profitable OOS   |   median OOS PF |   passed all |   median max DD $ |
|:-----------|:-------|-------:|------------:|--------:|---------------------:|-------:|---------------:|-------------:|:-----------------|----------------:|-------------:|------------------:|
| A01        | 5-min  |      8 |       29.98 |   60.84 |                 0.52 |   0.84 |      -34942.1  |            0 | 2/8              |            0.87 |            0 |         -51399.6  |
| A01        | 15-min |      8 |       19.1  |   63.37 |                 0.55 |   0.92 |      -17771.7  |            1 | 3/8              |            0.96 |            0 |         -31171.8  |
| A01        | 1-hour |      8 |        5.88 |   63.76 |                 0.5  |   0.92 |      -10337.5  |            1 | 4/8              |            0.98 |            0 |         -24514.7  |
| A01        | 4-hour |      8 |        2.1  |   67.5  |                 0.6  |   1.33 |       19684.7  |            5 | 6/8              |            1.24 |            2 |         -18300.2  |
| A01        | daily  |      8 |        0.54 |   77.46 |                 0.72 |   2.44 |       22885.8  |            8 | 8/8              |            2.24 |            6 |         -12290.9  |
| A02        | 5-min  |      8 |       20.72 |   55.26 |                 0.62 |   0.83 |      -26002.8  |            0 | 0/8              |            0.84 |            0 |         -32758.5  |
| A02        | 15-min |      8 |        7.65 |   58.32 |                 0.64 |   0.96 |       -3853.56 |            4 | 3/8              |            0.93 |            0 |         -17502.9  |
| A02        | 1-hour |      8 |        1.85 |   66.02 |                 0.6  |   1.11 |        4077.86 |            5 | 2/6              |            0.9  |            0 |         -10999.4  |
| A02        | 4-hour |      8 |        0.5  |   64.38 |                 0.66 |   1.19 |        5772.96 |            6 | 4/7              |            1.03 |            0 |         -10621.2  |
| A02        | daily  |      8 |        0.06 |   80.62 |                 1.8  |   7.42 |         256.69 |            5 | 0/0              |          nan    |            0 |          -6811.23 |
| A03        | 5-min  |      8 |       34.86 |   61.26 |                 0.54 |   0.88 |      -36964.7  |            1 | 0/8              |            0.9  |            0 |         -68971    |
| A03        | 15-min |      8 |       19.67 |   65.19 |                 0.54 |   0.98 |       -3667.74 |            3 | 2/8              |            0.92 |            0 |         -26862.7  |
| A03        | 1-hour |      8 |        5.78 |   69.42 |                 0.5  |   1.14 |       24859.5  |            6 | 5/8              |            1.06 |            1 |         -19869.3  |
| A03        | 4-hour |      8 |        1.83 |   71.81 |                 0.59 |   1.57 |       32708.1  |            8 | 5/8              |            1.16 |            1 |         -15695.7  |
| A03        | daily  |      8 |        0.5  |   73.87 |                 0.8  |   2.21 |       30052.8  |            8 | 8/8              |            1.95 |            3 |         -23581.6  |
| A04        | 5-min  |      8 |       30.88 |   58.36 |                 0.54 |   0.74 |      -41696.1  |            0 | 0/8              |            0.89 |            0 |         -52839.2  |
| A04        | 15-min |      8 |       17.4  |   64.34 |                 0.51 |   0.97 |       -3842.64 |            4 | 5/8              |            1.02 |            0 |         -17621    |
| A04        | 1-hour |      8 |        5.04 |   67.98 |                 0.49 |   1.02 |         575.62 |            4 | 6/8              |            1.23 |            1 |         -13760.8  |
| A04        | 4-hour |      8 |        1.75 |   71.95 |                 0.53 |   1.53 |       23034.5  |            7 | 7/8              |            1.62 |            5 |         -10185.2  |
| A04        | daily  |      8 |        0.4  |   74.6  |                 0.79 |   2.02 |       19429.8  |            8 | 8/8              |            2.23 |            6 |         -12884.3  |
| A05        | 5-min  |      8 |       36.97 |   59.42 |                 0.5  |   0.7  |     -100055    |            0 | 0/8              |            0.78 |            0 |        -101071    |
| A05        | 15-min |      8 |       23.33 |   59.76 |                 0.5  |   0.8  |      -95146.4  |            0 | 0/8              |            0.87 |            0 |         -99276.6  |
| A05        | 1-hour |      8 |       11.45 |   61.29 |                 0.56 |   0.86 |      -53178.5  |            1 | 2/8              |            0.99 |            0 |         -61337    |
| A05        | 4-hour |      8 |        3.35 |   61.24 |                 0.61 |   0.96 |       -7743.84 |            3 | 5/8              |            1.11 |            1 |         -32696.8  |
| A05        | daily  |      8 |        0.85 |   63.3  |                 0.69 |   1.14 |        7948.53 |            5 | 4/8              |            0.97 |            0 |         -31861.4  |
| A06        | 5-min  |      8 |       43.96 |   56.28 |                 0.58 |   0.74 |     -100028    |            0 | 0/8              |            0.86 |            0 |        -100157    |
| A06        | 15-min |      8 |       32.56 |   61.35 |                 0.56 |   0.89 |      -31213.6  |            0 | 0/8              |            0.94 |            0 |         -50185.1  |
| A06        | 1-hour |      8 |       10.29 |   63.5  |                 0.57 |   0.99 |       -3242.73 |            3 | 3/8              |            0.99 |            0 |         -22478.9  |
| A06        | 4-hour |      8 |        3.84 |   66.35 |                 0.58 |   1.15 |       15916.3  |            7 | 6/8              |            1.13 |            0 |         -17970.4  |
| A06        | daily  |      8 |        0.75 |   69.08 |                 0.74 |   2    |       30254.6  |            8 | 8/8              |            2.24 |            4 |         -17419.2  |
| A07        | 5-min  |      8 |       60.84 |   49.58 |                 0.54 |   0.57 |     -100019    |            0 | 0/8              |            0.83 |            0 |        -100673    |
| A07        | 15-min |      8 |       46.9  |   61.1  |                 0.5  |   0.79 |     -100022    |            1 | 0/8              |            0.96 |            0 |        -100553    |
| A07        | 1-hour |      8 |       26.19 |   67.29 |                 0.49 |   1.01 |        4403.66 |            4 | 4/8              |            0.99 |            0 |         -33074.9  |
| A07        | 4-hour |      8 |        8.35 |   66.2  |                 0.55 |   1.11 |       29051.9  |            6 | 7/8              |            1.23 |            2 |         -24478.2  |
| A07        | daily  |      8 |        1.99 |   64.86 |                 0.7  |   1.43 |       34456.8  |            7 | 6/8              |            1.7  |            3 |         -22800    |
| A08        | daily  |      8 |        0.24 |   73.87 |                 1.09 |   2.39 |       30594.6  |            8 | 0/0              |          nan    |            0 |         -18678.8  |
| A09        | daily  |      8 |        1    |   61.04 |                 1.04 |   1.48 |       33487.7  |            8 | 6/8              |            1.32 |            3 |         -18097.2  |
| A10        | daily  |      8 |        0.06 |   50    |                 8.12 |  11.05 |       97725.1  |            8 | 0/0              |          nan    |            0 |         -39200.6  |
| A11        | 5-min  |      8 |       30.87 |   35.04 |                 1.88 |   1    |        -617.6  |            4 | 6/8              |            1.03 |            0 |         -32331.5  |
| A11        | 15-min |      8 |       11.3  |   36.36 |                 1.91 |   1.1  |       26434.5  |            8 | 8/8              |            1.15 |            0 |         -22473.4  |
| A11        | 1-hour |      8 |        3.11 |   40.42 |                 2.14 |   1.36 |       48037.6  |            8 | 8/8              |            1.41 |            1 |         -15766.7  |
| A11        | 4-hour |      8 |        0.97 |   42.92 |                 2    |   1.38 |       20801    |            8 | 8/8              |            1.45 |            3 |         -21047.5  |
| A11        | daily  |      8 |        0.25 |   47.53 |                 3.06 |   2.63 |       49698.7  |            8 | 6/6              |            4.18 |            1 |         -18825.8  |
| A12        | 5-min  |      4 |       11.88 |   35.65 |                 1.23 |   0.65 |     -100094    |            0 | 0/4              |            0.61 |            0 |        -100674    |
| A12        | 15-min |      4 |       16.92 |   38.04 |                 1.45 |   0.89 |      -47126.8  |            1 | 1/4              |            0.9  |            0 |         -59577.7  |
| A12        | 1-hour |      4 |        5.14 |   43.88 |                 1.38 |   1.07 |        5376.49 |            3 | 3/4              |            1.04 |            1 |         -12557.6  |
| A12        | 4-hour |      4 |        1.14 |   44.22 |                 1.37 |   1.09 |        1595.5  |            2 | 2/4              |            1.04 |            1 |          -7224.69 |
| A12        | daily  |      4 |        0.18 |   48.15 |                 1.64 |   1.47 |         719    |            3 | 0/0              |          nan    |            0 |          -1798.53 |
| A13        | 1-min  |      1 |      374.35 |   45.42 |                 0.98 |   0.82 |      -64700    |            0 | 0/1              |            0.83 |            0 |         -65962.5  |
| A13        | 5-min  |      1 |      167.68 |   47.34 |                 0.99 |   0.89 |      -31345.5  |            0 | 0/1              |            0.9  |            0 |         -32307.5  |
| A13        | 15-min |      1 |       78.45 |   47.73 |                 1.05 |   0.96 |       -8528    |            0 | 0/1              |            0.92 |            0 |         -11647    |
| A13        | 1-hour |      1 |      nan    |  nan    |               nan    | nan    |         nan    |            0 | 0/0              |          nan    |            0 |            nan    |
| B01        | 5-min  |      1 |       27.85 |    6.18 |                 2.03 |   0.13 |      -44861.2  |            0 | 0/1              |            0.11 |            0 |         -45755    |
| B01        | 15-min |      1 |       17.12 |    3.78 |                 2.8  |   0.11 |      -32388.1  |            0 | 0/1              |            0.3  |            0 |         -33952.1  |
| B01        | 1-hour |      1 |        2.4  |    5.38 |                 6.86 |   0.39 |       -5338.81 |            0 | 0/1              |            0.71 |            0 |          -7456.2  |
| B01        | 4-hour |      1 |        0.06 |   66.67 |                 1.92 |   3.85 |        3347.22 |            1 | 0/1              |            0.25 |            0 |          -5594    |
| B01        | daily  |      1 |      nan    |  nan    |               nan    | nan    |         nan    |            0 | 0/0              |          nan    |            0 |            nan    |

What stands out (counts from the table above):

* **A01, A03, A04 (RSI/Williams + EMA + VWAP pullbacks):** 15 of their 24 daily runs passed. On 4-hour bars:
  A01 2, A03 1, A04 5. On 1-hour bars: A01 none; A03 MNQ cash;
  A04 NAS100 cash. Below 1 hour none passes.
* **A05, A06, A07 (z-score, rubber band, MFI):** the most frequent traders and the most cost-sensitive. Passing runs:
  A05 1, A06 4, A07 5 (A07 on 4-hour: NAS100 full, XAUUSD cash).
* **A11 (time-series momentum):** profitable out-of-sample in 6 of 8 on 5-min; 8 of 8 on 15-min; 8 of 8 on 1-hour; 8 of 8 on 4-hour; 6 of 6 on daily
  runs with a walk-forward. It wins less than half its trades but the average win is about twice the average loss;
  what stops it is reliance on a few big trades, drawdown and (for several gold runs) a walk-forward efficiency that
  is not available because too few folds were scored or the in-sample profit is near zero.
* **A12 (squeeze breakout):** designed for 15-minute bars; passing runs: XAUUSD 1-hour, MNQ 4-hour.
* **A02, A13, B01:** pass on no bar size. A13 can't trade at all on 1-hour bars: it needs 90% of the last 1,950 bars
  to be valid one-bar samples, and only 5 of the 7 hourly cash bars per day qualify (the 09:30 bar is 30 minutes, and
  the first bar of each day has no earlier bar that day).

## 5. Every run that passed all key checks (45)

Sorted by bar size, then out-of-sample profit. "Trades/mo" is over the whole history; "OOS" is the walk-forward
(parameters chosen only on earlier data):

| strategy                                | market   | session   | bars   |   trades/mo |   win % |   avg win ÷ avg loss |   PF |   OOS trades |   OOS trades/mo |   OOS net $ |   OOS PF |   WF efficiency |   OOS max DD $ |   MC loss % |   worst stress $ |
|:----------------------------------------|:---------|:----------|:-------|------------:|--------:|---------------------:|-----:|-------------:|----------------:|------------:|---------:|----------------:|---------------:|------------:|-----------------:|
| A11 Time-series momentum                | NAS100   | rth       | 1-hour |         1.7 |    44   |                 2.15 | 1.69 |          161 |             1.6 |       49998 |     1.7  |            1.28 |         -15030 |         1.3 |            82879 |
| A04 RSI+EMA50+VWAP                      | NAS100   | rth       | 1-hour |         2.9 |    67.5 |                 0.57 | 1.19 |          287 |             2.9 |       33773 |     1.53 |            1.81 |          -8472 |         0.7 |            14514 |
| A12 Volatility squeeze breakout (15m)   | XAUUSD   | full      | 1-hour |         5.9 |    45.8 |                 1.38 | 1.16 |          305 |             6.4 |       24697 |     1.38 |            1.34 |          -5701 |         0.9 |             5123 |
| A03 Williams %R+EMA+VWAP                | MNQ      | rth       | 1-hour |         2.7 |    67.4 |                 0.71 | 1.47 |          227 |             4.6 |       18655 |     1.42 |            0.65 |          -8511 |         2.6 |            21380 |
| A11 Time-series momentum                | NAS100   | rth       | 4-hour |         0.6 |    50.8 |                 1.74 | 1.79 |           77 |             1   |       59317 |     2.02 |            1.2  |         -16884 |         1   |            59047 |
| A04 RSI+EMA50+VWAP                      | NAS100   | full      | 4-hour |         2.1 |    75.4 |                 0.5  | 1.53 |          257 |             3.2 |       42092 |     1.61 |            1.45 |         -11263 |         0.9 |            40175 |
| A11 Time-series momentum                | XAUUSD   | full      | 4-hour |         1.2 |    47.4 |                 2.33 | 2.1  |           84 |             2.8 |       37022 |     1.89 |            0.95 |         -23905 |         5.2 |            52207 |
| A07 MFI reversal                        | NAS100   | full      | 4-hour |         9.9 |    69.3 |                 0.49 | 1.1  |          328 |             4.1 |       34135 |     1.37 |            1.69 |         -21584 |         5   |            19412 |
| A01 RSI+EMA+VWAP pullback               | NAS100   | full      | 4-hour |         2.7 |    70.1 |                 0.57 | 1.33 |          286 |             3.6 |       33281 |     1.3  |            0.99 |         -18038 |         9.3 |            38635 |
| A11 Time-series momentum                | MNQ      | full      | 4-hour |         2.1 |    37.4 |                 2.05 | 1.23 |           95 |             3   |       30371 |     1.88 |            2.24 |         -12617 |         9.4 |            23972 |
| A07 MFI reversal                        | XAUUSD   | rth       | 4-hour |         6.5 |    65.2 |                 0.59 | 1.1  |          124 |             4.2 |       22530 |     1.48 |            0.88 |         -12048 |         6.6 |              897 |
| A01 RSI+EMA+VWAP pullback               | MNQ      | rth       | 4-hour |         1.6 |    75.2 |                 1.06 | 3.22 |           40 |             1.3 |       19202 |     3.86 |            0.83 |          -5252 |         0   |            34810 |
| A04 RSI+EMA50+VWAP                      | MGC      | rth       | 4-hour |         1.1 |    68.7 |                 0.7  | 1.53 |           76 |             0.9 |       18014 |     1.67 |            1.65 |          -8662 |         4.9 |             8410 |
| A04 RSI+EMA50+VWAP                      | XAUUSD   | rth       | 4-hour |         1.1 |    72.6 |                 0.83 | 2.21 |           46 |             1.6 |       14933 |     1.62 |            1.01 |          -8530 |         9.6 |            21398 |
| A05 Z-score mean reversion (long+short) | MNQ      | rth       | 4-hour |         2.5 |    59.5 |                 0.77 | 1.14 |           34 |             1.1 |       13452 |     1.97 |            0.95 |         -12944 |         6.8 |            27492 |
| A03 Williams %R+EMA+VWAP                | MNQ      | rth       | 4-hour |         1.4 |    70.8 |                 0.68 | 1.65 |           44 |             1.4 |       11646 |     1.96 |            0.6  |          -8183 |         7.9 |            18902 |
| A04 RSI+EMA50+VWAP                      | MNQ      | rth       | 4-hour |         1.2 |    71.8 |                 1.09 | 2.78 |           19 |             0.6 |        6000 |     3.12 |            0.36 |          -4664 |         3.5 |            22106 |
| A04 RSI+EMA50+VWAP                      | MNQ      | full      | 4-hour |         2.2 |    72.1 |                 0.5  | 1.28 |           38 |             1.2 |        5118 |     1.95 |            0.53 |          -3598 |         7.1 |            10742 |
| A12 Volatility squeeze breakout (15m)   | MNQ      | full      | 4-hour |         0.2 |    70.6 |                 1.86 | 4.45 |            6 |             0.5 |        2314 |     5.88 |          nan    |           -966 |         2   |             1605 |
| A09 Turn of the month                   | NAS100   | full      | daily  |         1   |    66.4 |                 1    | 1.98 |           80 |             1   |       75592 |     2.03 |            1.39 |         -18841 |         1.7 |            76518 |
| A09 Turn of the month                   | NAS100   | rth       | daily  |         1   |    63.5 |                 1.08 | 1.88 |           80 |             1   |       60950 |     1.82 |            1.2  |         -25610 |         4.1 |            74993 |
| A03 Williams %R+EMA+VWAP                | NAS100   | rth       | daily  |         0.6 |    83.3 |                 0.56 | 2.8  |           55 |             0.7 |       58900 |     4.13 |            0.97 |         -12339 |         0   |            49287 |
| A07 MFI reversal                        | NAS100   | rth       | daily  |         2.1 |    72.8 |                 0.74 | 1.97 |          115 |             1.4 |       54614 |     1.79 |            1.64 |         -17675 |         0.8 |            62822 |
| A06 Rubber Band                         | NAS100   | rth       | daily  |         0.8 |    72.4 |                 0.69 | 1.81 |          103 |             1.3 |       49258 |     1.79 |            0.83 |         -19842 |         0.8 |            59903 |
| A01 RSI+EMA+VWAP pullback               | MGC      | rth       | daily  |         0.4 |    69.8 |                 1    | 2.3  |           44 |             0.5 |       38393 |     3.18 |            1.77 |         -10682 |         0.2 |            45913 |
| A06 Rubber Band                         | NAS100   | full      | daily  |         0.6 |    74.6 |                 0.8  | 2.35 |           50 |             0.6 |       34649 |     2.17 |            0.68 |         -17978 |         1.8 |            42702 |
| A01 RSI+EMA+VWAP pullback               | NAS100   | rth       | daily  |         0.7 |    80.8 |                 0.84 | 3.53 |           70 |             0.9 |       33302 |     1.9  |            0.67 |         -14261 |         1.7 |            66817 |
| A06 Rubber Band                         | MNQ      | full      | daily  |         0.7 |    77.3 |                 0.93 | 3.18 |           18 |             0.6 |       30648 |     6.27 |            2.62 |          -8534 |         0.4 |             2204 |
| A01 RSI+EMA+VWAP pullback               | MGC      | full      | daily  |         0.5 |    71.4 |                 0.7  | 1.75 |           56 |             0.7 |       29124 |     2.28 |            2.37 |         -13177 |         1.4 |            29507 |
| A04 RSI+EMA50+VWAP                      | MGC      | rth       | daily  |         0.3 |    66.7 |                 1.01 | 2.03 |           42 |             0.5 |       28999 |     2.45 |            1.31 |         -10981 |         1   |            49109 |
| A09 Turn of the month                   | XAUUSD   | rth       | daily  |         1   |    59.4 |                 1.19 | 1.74 |           29 |             1   |       28356 |     2.74 |            1.26 |         -17995 |         2.5 |            52249 |
| A06 Rubber Band                         | MGC      | rth       | daily  |         1.4 |    61.2 |                 0.76 | 1.21 |          121 |             1.4 |       27339 |     1.47 |            2.14 |         -12058 |         7.8 |            19584 |
| A07 MFI reversal                        | MNQ      | rth       | daily  |         2   |    65.9 |                 0.87 | 1.68 |           62 |             2   |       26122 |     2    |            1.38 |         -11378 |         4.9 |            39194 |
| A01 RSI+EMA+VWAP pullback               | XAUUSD   | full      | daily  |         0.5 |    77.4 |                 0.69 | 2.38 |           18 |             0.6 |       25275 |     3.68 |            1.79 |         -17388 |         2.1 |            12034 |
| A04 RSI+EMA50+VWAP                      | MGC      | full      | daily  |         0.3 |    72.5 |                 0.72 | 1.9  |           46 |             0.5 |       24973 |     2.17 |            2.33 |         -12401 |         2.4 |            42333 |
| A03 Williams %R+EMA+VWAP                | MNQ      | full      | daily  |         0.4 |    78.6 |                 0.84 | 3.09 |           40 |             1.3 |       24432 |     2.9  |            2.24 |          -9847 |         1.2 |            15369 |
| A11 Time-series momentum                | MNQ      | rth       | daily  |         0.3 |    55.6 |                 2.72 | 3.4  |           11 |             0.5 |       22712 |     5.12 |            2.2  |         -13641 |         9.7 |            32250 |
| A07 MFI reversal                        | MNQ      | full      | daily  |         2.1 |    69.8 |                 0.78 | 1.79 |           61 |             1.9 |       22436 |     1.82 |            0.78 |         -19229 |         6.8 |            52230 |
| A01 RSI+EMA+VWAP pullback               | XAUUSD   | rth       | daily  |         0.5 |    64.5 |                 1.01 | 1.83 |           21 |             0.7 |       18535 |     2.81 |            1.2  |         -12932 |         3.7 |            25881 |
| A03 Williams %R+EMA+VWAP                | MNQ      | rth       | daily  |         0.4 |    75   |                 0.62 | 1.85 |           53 |             1.7 |       17388 |     1.99 |            2.91 |         -10335 |         6   |             7390 |
| A04 RSI+EMA50+VWAP                      | MNQ      | full      | daily  |         0.4 |    82.8 |                 0.95 | 4.57 |           20 |             0.6 |       17034 |     7.5  |            1.1  |          -5202 |         0   |            21789 |
| A04 RSI+EMA50+VWAP                      | NAS100   | full      | daily  |         0.5 |    74.2 |                 0.62 | 1.77 |           56 |             0.7 |       17026 |     1.53 |            1.05 |         -13027 |         9.8 |            39377 |
| A01 RSI+EMA+VWAP pullback               | MNQ      | full      | daily  |         0.6 |    77.5 |                 0.74 | 2.54 |           32 |             1   |       16066 |     2.2  |            1.12 |         -10723 |         7.8 |            24428 |
| A04 RSI+EMA50+VWAP                      | NAS100   | rth       | daily  |         0.5 |    75   |                 0.85 | 2.56 |           47 |             0.6 |       15976 |     1.68 |            0.56 |         -12815 |         7.1 |            48264 |
| A04 RSI+EMA50+VWAP                      | XAUUSD   | rth       | daily  |         0.3 |    68.2 |                 0.94 | 2    |           15 |             0.5 |       15007 |     2.57 |            1.12 |         -12932 |         7.2 |            25341 |

Runs on 1-hour and 4-hour bars that passed: **19** (4 + 15), covering
MGC, MNQ, NAS100, XAUUSD and strategies A01, A03, A04, A05, A07, A11, A12.

The efficiency rule removed 2 runs that passed before:
A04 MNQ cash 1-hour (raw ratio 6.15: not available: in-sample profit $3.69/day is below the $3.97/day minimum (1% of capital a year)); A11 MGC cash daily (raw ratio 3,316.29: not available: only 2 of 7 folds scored (needs at least 50%)).

## 6. Frequent but not robust: the closest misses (≥ 10 trades a month, profitable out-of-sample)

| strategy   | market   | session   | bars   |   trades/mo |   win % |   avg win ÷ avg loss |   OOS net $ |   OOS PF |   MC loss % |   worst stress $ | not passed                                                                                                                                                                                                                                                                                    |
|:-----------|:---------|:----------|:-------|------------:|--------:|---------------------:|------------:|---------:|------------:|-----------------:|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| A11        | NAS100   | full      | 15-min |        17.8 |    36   |                 1.89 |       51845 |     1.17 |         3.6 |            -4452 | Best setting is on a plateau, not a spike, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable in every tested execution scenario, Still profitable without the best 5% of trades                                                                                                |
| A07        | MNQ      | full      | 1-hour |        46.2 |    70   |                 0.47 |       33813 |     1.14 |         5   |           -13328 | Monte Carlo: 95%-worst drawdown within $20,000, Still profitable under combined execution stress, Still profitable in every tested execution scenario, Still profitable without the best 5% of trades                                                                                         |
| A11        | XAUUSD   | full      | 15-min |        19   |    35.1 |                 2.04 |       33642 |     1.26 |         3.3 |             8928 | Best setting is on a plateau, not a spike, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable without the best 5% of trades                                                                                                                                                     |
| A11        | MNQ      | full      | 5-min  |        67.8 |    33.1 |                 2.07 |       31288 |     1.14 |         6.5 |            14204 | Best setting is on a plateau, not a spike, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable without the best 5% of trades                                                                                                                                                     |
| A11        | NAS100   | rth       | 5-min  |        14.3 |    39.6 |                 1.69 |       24844 |     1.09 |        20.6 |            -5754 | Best setting is on a plateau, not a spike, Walk-forward OOS profit factor >= 1.1, Monte Carlo: chance of ending at a loss < 10%, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable in every tested execution scenario, Still profitable without the best 5% of trades          |
| A02        | NAS100   | full      | 15-min |        10.5 |    60.7 |                 0.67 |       23555 |     1.14 |         8.5 |           -74701 | Most parameter sets are profitable (>= 60%), Best setting is on a plateau, not a spike, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable under combined execution stress, Still profitable in every tested execution scenario, Still profitable without the best 5% of trades |
| A07        | MNQ      | rth       | 1-hour |        13.5 |    68.8 |                 0.5  |       21900 |     1.2  |         9.3 |            19430 | Best setting is on a plateau, not a spike, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable without the best 5% of trades                                                                                                                                                     |
| A11        | MGC      | full      | 15-min |        15.2 |    34.5 |                 1.9  |       20137 |     1.13 |        13.9 |             3520 | Best setting is on a plateau, not a spike, Monte Carlo: chance of ending at a loss < 10%, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable without the best 5% of trades                                                                                                      |
| A07        | XAUUSD   | rth       | 1-hour |        14.8 |    67.9 |                 0.56 |       18798 |     1.21 |        14.7 |            -5364 | Best setting is on a plateau, not a spike, Monte Carlo: chance of ending at a loss < 10%, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable in every tested execution scenario, Still profitable without the best 5% of trades                                                 |
| A11        | MNQ      | rth       | 5-min  |        19.8 |    37   |                 1.87 |       17185 |     1.11 |        19.1 |             3094 | Best setting is on a plateau, not a spike, Monte Carlo: chance of ending at a loss < 10%, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable without the best 5% of trades                                                                                                      |
| A12        | MNQ      | full      | 15-min |        17.9 |    40.3 |                 1.51 |       16054 |     1.08 |        16.9 |            11960 | Best setting is on a plateau, not a spike, Walk-forward OOS profit factor >= 1.1, Monte Carlo: chance of ending at a loss < 10%, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable without the best 5% of trades                                                               |
| A11        | MNQ      | full      | 15-min |        25.4 |    36   |                 1.95 |       15984 |     1.1  |        22   |            16084 | Walk-forward OOS profit factor >= 1.1, Monte Carlo: chance of ending at a loss < 10%, Monte Carlo: 95%-worst drawdown within $20,000, Still profitable without the best 5% of trades                                                                                                          |

Checklist items these 12 runs did not pass, most common first:
* Monte Carlo: 95%-worst drawdown within $20,000: 12 of 12
* Still profitable without the best 5% of trades: 12 of 12
* Best setting is on a plateau, not a spike: 10 of 12
* Monte Carlo: chance of ending at a loss < 10%: 6 of 12
* Still profitable in every tested execution scenario: 5 of 12
* Walk-forward OOS profit factor >= 1.1: 3 of 12
* Still profitable under combined execution stress: 2 of 12
* Most parameter sets are profitable (>= 60%): 1 of 12

Profitable out-of-sample is not enough here: these miss on the reliance on a few big trades, an isolated best
setting, Monte Carlo risk or execution stress. They are candidates for a forward test, not for trading.

## 7. Getting to 10–15 trades a month: run several robust strategies together

The runs that passed all key checks are combined, using only their saved out-of-sample results.

**Selection rule:** one run per strategy and underlying market, the one with the **most** out-of-sample trades a
month. The rule picks by frequency, not profit. MNQ and NAS100 are both the Nasdaq-100, and MGC and XAUUSD are both
gold. The cash and full session and the different bar sizes of one strategy on one market take mostly the same
trades, so they count once.

**Measured on:** only the dates inside every selected run's walk-forward schedule. A fold in which the optimiser found
no valid setting trades nothing and counts as zero. Two views: *marked* (daily equity changes, including positions
already open on the first day) and *flat start* (only trades entered in the window, whole P&L).

### Book 1: tradable now (MNQ + MGC + XAUUSD)

|                                                       | tradable now (MNQ + MGC + XAUUSD)   |
|:------------------------------------------------------|:------------------------------------|
| start                                                 | 2024-06-03                          |
| end                                                   | 2025-12-31                          |
| months                                                | 18.9                                |
| runs                                                  | 15                                  |
| trades entered in window                              | 608                                 |
| trades_per_month                                      | 32.1                                |
| positions carried in at start                         | 5                                   |
| net (marked, includes carried-in positions)           | 218785.43                           |
| max drawdown (daily closes)                           | -27164.54                           |
| net (flat start: trades entered in window, whole P&L) | 221400.33                           |
| max drawdown (flat start, realised on exit days)      | -18146.76                           |
| profitable_months                                     | 15 of 19                            |
| worst_month                                           | 2025-02: -3,813                     |
| best_month                                            | 2025-04: 37,186                     |
| max positions open at once (bar timestamps)           | 9                                   |
| max positions open on one day                         | 12                                  |
| median positions open per day                         | 5.0                                 |
| max gross exposure $ (one day)                        | 891620.0                            |
| median gross exposure $                               | 393370.0                            |

| run                    |   trades |   trades / month |    net $ |   win % |   median entry notional $ |   max entry notional $ |
|:-----------------------|---------:|-----------------:|---------:|--------:|--------------------------:|-----------------------:|
| A01 MNQ rth 4-hour     |       26 |             1.37 | 12835    |    76.9 |                     82162 |                  98721 |
| A03 MNQ rth 1-hour     |       68 |             3.59 |  8759    |    69.1 |                     85394 |                  99896 |
| A04 MNQ full 4-hour    |       22 |             1.16 |  5231.5  |    81.8 |                     82440 |                  99896 |
| A05 MNQ rth 4-hour     |       15 |             0.79 |  8261.5  |    66.7 |                     81765 |                  96815 |
| A06 MNQ full daily     |       12 |             0.63 | 20094    |    83.3 |                     80192 |                  98169 |
| A07 MNQ rth daily      |       36 |             1.9  | 15032.5  |    69.4 |                     83468 |                  99992 |
| A11 MNQ full 4-hour    |       54 |             2.85 | 14289.5  |    37   |                     81304 |                  99933 |
| A12 MNQ full 4-hour    |        1 |             0.05 |   644.25 |   100   |                     38310 |                  38310 |
| A01 XAUUSD rth daily   |       16 |             0.85 | 23585.3  |    93.8 |                     99133 |                  99857 |
| A04 XAUUSD rth 4-hour  |       37 |             1.96 |  9955.89 |    73   |                     98252 |                  99995 |
| A06 MGC rth daily      |       26 |             1.37 | 13201.5  |    65.4 |                     82054 |                  99840 |
| A07 XAUUSD rth 4-hour  |       77 |             4.07 | 23308.9  |    75.3 |                     98515 |                  99961 |
| A09 XAUUSD rth daily   |       19 |             1    | 19225.4  |    68.4 |                     98767 |                  99918 |
| A11 XAUUSD full 4-hour |       45 |             2.38 | 35404.1  |    37.8 |                     98376 |                  99995 |
| A12 XAUUSD full 1-hour |      154 |             8.14 |  8957.09 |    47.4 |                     54974 |                 118592 |

Buy-and-hold over the same dates ($100,000 of contract value, same costs):

| market   | from       | to         |   net $ |   max DD $ |
|:---------|:-----------|:-----------|--------:|-----------:|
| MNQ      | 2024-06-03 | 2025-12-31 | 20468   |   -24659   |
| MGC      | 2024-06-03 | 2025-12-31 | 69712.3 |   -18920   |
| XAUUSD   | 2024-06-03 | 2025-12-31 | 83601.2 |   -19718.4 |

### Book 2: longest history (NAS100 + MGC)

|                                                       | longest history (NAS100 + MGC)   |
|:------------------------------------------------------|:---------------------------------|
| start                                                 | 2019-01-02                       |
| end                                                   | 2021-09-30                       |
| months                                                | 32.9                             |
| runs                                                  | 10                               |
| trades entered in window                              | 731                              |
| trades_per_month                                      | 22.2                             |
| positions carried in at start                         | 1                                |
| net (marked, includes carried-in positions)           | 259736.73                        |
| max drawdown (daily closes)                           | -74232.85                        |
| net (flat start: trades entered in window, whole P&L) | 258309.75                        |
| max drawdown (flat start, realised on exit days)      | -67406.94                        |
| profitable_months                                     | 23 of 33                         |
| worst_month                                           | 2020-02: -28,086                 |
| best_month                                            | 2020-04: 42,284                  |
| max positions open at once (bar timestamps)           | 7                                |
| max positions open on one day                         | 8                                |
| median positions open per day                         | 3.0                              |
| max gross exposure $ (one day)                        | 803033.0                         |
| median gross exposure $                               | 305191.0                         |

| run                    |   trades |   trades / month |   net $ |   win % |   median entry notional $ |   max entry notional $ |
|:-----------------------|---------:|-----------------:|--------:|--------:|--------------------------:|-----------------------:|
| A01 NAS100 full 4-hour |      154 |             4.68 | 36501.3 |    75.3 |                     99951 |                  99999 |
| A03 NAS100 rth daily   |       31 |             0.94 | 28988.3 |    83.9 |                     99967 |                  99998 |
| A04 NAS100 full 4-hour |      134 |             4.07 | 36657.9 |    79.1 |                     99953 |                  99999 |
| A06 NAS100 rth daily   |       42 |             1.28 | 33912.6 |    69   |                     99954 |                  99996 |
| A07 NAS100 full 4-hour |      121 |             3.68 | 19343.2 |    78.5 |                     99944 |                  99999 |
| A09 NAS100 rth daily   |       33 |             1    | 42147.9 |    63.6 |                     99956 |                  99998 |
| A11 NAS100 rth 1-hour  |      116 |             3.52 | 22891.5 |    43.1 |                     99954 |                 100000 |
| A01 MGC full daily     |       24 |             0.73 | 16304.6 |    70.8 |                     90373 |                  97860 |
| A04 MGC rth 4-hour     |       16 |             0.49 |  4454.5 |    87.5 |                     92026 |                  99911 |
| A06 MGC rth daily      |       60 |             1.82 | 18534.9 |    66.7 |                     91561 |                  99911 |

Buy-and-hold over the same dates ($100,000 of contract value, same costs):

| market   | from       | to         |    net $ |   max DD $ |
|:---------|:-----------|:-----------|---------:|-----------:|
| NAS100   | 2019-01-02 | 2021-09-30 | 132206   |   -48874.6 |
| MGC      | 2019-01-02 | 2021-09-30 |  23853.8 |   -30158.7 |

How to read this:

* **The trade count is the answer to "10–15 a month":** book 1 averaged **32.1** trades a month from 15 runs
  and book 2 **22.2** from 10 runs. Book 1 had 5 positions already open on its first day
  (book 2: 1); they are in the marked P&L, not in the trade count. The flat-start view, which leaves
  them out, gives $221,400 for book 1 and $258,310 for book 2.
* **This is NOT one account.** Each run sized its trades on its own $100,000 account, so the dollar figures add
  15 (or 10) separately sized accounts. At most 9 book-1 positions were open at the same moment
  (12 on one day counting every position open at any time that day), and gross exposure reached
  $891,620 (median $393,370). Book 2: 7 at once, gross exposure up to
  $803,033. One $100,000 account cannot carry that: positions would have to be cut to a
  fraction, and micro contracts can't be cut that finely (one MNQ contract was $34,464–$52,442 of contract
  value in this period at daily closes, and positions are rounded *down* to whole contracts). A single account can run only a few
  of these at full size. A capital-constrained portfolio test on untouched data is the step before trusting these
  dollar figures.
* **Compare with buy-and-hold over the same dates** ($100,000 of contract value, same costs):
  * Book 1 period: MNQ $20,468 (max DD −$24,659), MGC $69,712 (max DD −$18,920), XAUUSD $83,601 (max DD −$19,718).
  * Book 2 period: NAS100 $132,206 (max DD −$48,875), MGC $23,854 (max DD −$30,159).

  Most of these strategies only buy, and Nasdaq and gold both rose strongly in both periods. Per $100,000 account the
  book earned less than holding gold in book 1 ($83,601). What it offers is smaller drawdowns per account and
  many more, smaller bets, not a higher return than the market.
* **Selection bias:** the runs were chosen because they passed checks that include their out-of-sample results. This
  combined record is therefore optimistic. It is not a fresh test; the next step is a forward test on data none of
  this has seen.

## 8. What needs to change to go from ~10 trades a year to 10–15 a month

Tested here:

1. **Move from daily to 1-hour or 4-hour bars, not to 5- or 15-minute.** Some pullback, MFI, momentum and squeeze
   runs keep an edge there (section 5), at a median 2.8 (1-hour) and 1.6 (4-hour) trades a
   month per run instead of 0.6 on daily. Below 1 hour, costs take more than the edge.
2. **Scale price-percentage thresholds to the bar size** (done in this study). A "1% below VWAP" rule almost never
   triggers on a 5-minute bar. The scaled 0.11% does, but it produces the small, cost-eaten trades of section 3.
3. **Trade several uncorrelated strategies and markets at once.** This is what reaches the target: 32.1 a month in
   book 1 and 22.2 in book 2, but with the exposure described in section 7.
4. **Trade the cheaper instruments when trading often.** MNQ costs about $6 a trade on 1-hour bars against
   $17 for MGC and $20 for NAS100. On 1-hour bars that difference decides profit or loss.

Not tested here (suggestions only):

* Cut the cost per trade (limit entries instead of market fills, fewer lots per trade).
* Design rules for intraday from the start, with targets several times the cost, instead of shrinking daily rules.

## 9. Limits of this study

* **Selection bias** in sections 5–7: picking the best of 373 runs flatters the winners. Forward-test before trusting
  any of them.
* **Data coverage:**
  * MNQ has 5.6 years and XAUUSD 5.4 years. The 4-hour and daily walk-forwards on them have only 2.6 and 2.5 years
    of out-of-sample data, and few trades (see the "OOS trades" column).
  * NAS100 data ends 2021-09-30.
* **The √-time scaling of percentage thresholds is an assumption.** The parameter grid tests lower and higher values
  around each scaled one (A01 0.5×–1.5×, A11 0.6×–1.6×, A02 0 to 2× of its 0.5% default), but a different rule
  could give different trade counts.
* **The efficiency limits are a policy choice** (50% of folds scored, in-sample profit ≥
  1% of capital a year). They are set in `engine/walkforward.py`; changing them changes which runs pass.
* **Mixed code versions:** 19 rows were re-run with the current code; the others keep their saved runs (code
  versions in the index: 22). The engine changes since those runs could only alter a saved path where an
  account came within its entry costs of $0; the 19 configurations that came within $5,000 were re-run and gave
  identical trades, P&L and stress tables. No saved fold schedule has an absent window, and every configuration's
  look-ahead gate was re-checked with the new decision-bar cuts. The report-side rules were applied to the saved
  tables.
* **Fixed costs**, without commission tiers or exchange fees by date. The stress scenarios (double costs, triple
  spread, 2-bar delay) show how much margin each run has.

## Reproduce

```
cd /Volumes/T9/BACKTESTING
~/.venvs/t9-backtesting/bin/python timeframe_study.py --workers 4        # resumes; reruns only changed code or data
~/.venvs/t9-backtesting/bin/python tools/recheck_efficiency.py results/TIMEFRAME_STUDY/rows.csv
~/.venvs/t9-backtesting/bin/python tools/timeframe_report.py    > results/TIMEFRAME_STUDY/tables.md
~/.venvs/t9-backtesting/bin/python tools/timeframe_costs.py     > results/TIMEFRAME_STUDY/costs.md
~/.venvs/t9-backtesting/bin/python tools/timeframe_portfolio.py > results/TIMEFRAME_STUDY/portfolio.md
~/.venvs/t9-backtesting/bin/python tools/write_timeframe_report.py
```
Each row of `rows.csv` points to its run folder (`report` column). The folder holds the full robustness report,
the walk-forward folds and trades, Monte Carlo and stress tables. `tables.md` also has the complete table of all
373 runs.
