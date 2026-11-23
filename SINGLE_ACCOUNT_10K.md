# The book on one $10,000 account, 2% risk per trade, compounding

*Generated November 23, 2026 by `tools/write_single_account_report.py`. Data: the walk-forward out-of-sample trades of the runs selected in TIMEFRAME_STUDY_RESULTS.md section 7.*

## How it was run

* **One account, $10,000.** All the strategies in a book share it and can hold positions at the same time.
* **Risk 2% of the balance on every trade, compounding:** the balance is $10,000 plus every trade closed before this one is entered. Quantity = 2% of the balance ÷ (stop distance × point value), rounded **down** to whole MNQ/MGC micro contracts or 0.01 lots of XAUUSD/NAS100. If even one contract would risk more than 2%, the trade is **skipped**.
* **Two ways to define the stop distance** (13 of the 15 strategies have no stop of their own):
  * **A. ATR-sized, no hard stop:** the saved trades exactly as they were, sized as if the stop were 2 × ATR(14) of the decision bar. The exits are the strategies' own, so a loss can be bigger than 2%.
  * **B. Real 2 × ATR stop:** every strategy re-run through the whole pipeline (grid, walk-forward, Monte Carlo, stress, checklist) with a hard stop 2 × ATR(14) from the fill. The walk-forward re-optimised the settings with the stop in place; those new out-of-sample trades are then sized the same way.
  * A12 already has its own stop and is the same in both.
* Costs (commission, slippage, spread, rolls) are per contract, so they scale with the new size. **Margin is not modelled**: the leverage row shows how much contract value was open per dollar of equity.

## Read this first

* **The profit comes mostly from spot gold.** In the MNQ + gold book, XAUUSD strategies made 88% (A) / 96% (B) of the net profit, in a period when gold rose strongly. The out-of-sample window is only about 19 months.
* **At $10,000, MNQ and MGC are often too big:** one micro contract with a 2 × ATR stop usually risks more than $200. On their own $10,000 account the MNQ strategies took almost no trades (table below); inside the book they start trading only after gold profits have grown the balance.
* **Leverage:** with 2% risk on several positions at once, open contract value reached about 10–12 × equity. Check your broker's margin before relying on this.
* **Selection bias:** these strategies were picked because they passed checks that include these same out-of-sample results, and compounding magnifies that optimism. Treat the returns as an upper bound and forward-test first.

## tradable now (MNQ + MGC + XAUUSD)

| | A. ATR-sized, no hard stop | B. Real 2×ATR stop |
|---|---|---|
| Period | 2024-06-03 → 2026-01-05 (19.1 months) | 2024-06-03 → 2026-01-05 (19.1 months) |
| Trades the strategies gave | 608 | 637 |
| Trades taken | 437 | 447 |
| Trades skipped (minimum size risks > 2%) | 171 | 190 |
| Trades per month (taken) | 22.9 | 23.4 |
| Final balance | $75,696 | $57,013 |
| Net profit | $65,696 | $47,013 |
| Return | 657% | 470% |
| Per year (compounded) | 257% | 199% |
| Max drawdown (daily closes) | −$12,124 (-18.8%) | −$8,636 (-18.0%) |
| Win rate | 60.4% | 58.2% |
| Profit factor | 2.04 | 1.75 |
| Average win / average loss (in R) | +0.96R / -0.76R | +0.97R / -0.79R |
| Worst trade | -2.93R | -3.17R |
| Losses bigger than the 2% risk | 35 | 53 |
| Profitable months | 16 of 20 | 17 of 20 |
| Worst month | 2024-12 -762 | 2024-06 -568 |
| Most positions open at once (day closes) | 7 | 7 |
| Leverage (contract value ÷ equity): max / median | 11.6× / 2.9× | 10.0× / 2.5× |
| Account hit $0 | no | no |

Per strategy inside the book:

| run                    |   trades given |   A taken |   A net $ |   A win % |   B given |   B taken |   B net $ |   B win % |
|:-----------------------|---------------:|----------:|----------:|----------:|----------:|----------:|----------:|----------:|
| A01 MNQ cash 4-hour    |             26 |         8 |      1784 |      87.5 |        28 |         5 |      -496 |      60   |
| A01 XAUUSD cash daily  |             16 |        16 |      4035 |      93.8 |        14 |        14 |      3219 |      92.9 |
| A03 MNQ cash 1-hour    |             68 |        48 |      3543 |      70.8 |        78 |        52 |      -411 |      61.5 |
| A04 MNQ full 4-hour    |             22 |        13 |      1366 |      84.6 |        23 |        12 |       210 |      75   |
| A04 XAUUSD cash 4-hour |             37 |        37 |      6873 |      73   |        39 |        39 |      4234 |      69.2 |
| A05 MNQ cash 4-hour    |             15 |         2 |      2051 |     100   |        19 |         2 |      1136 |      50   |
| A06 MGC cash daily     |             26 |         1 |      -806 |       0   |        40 |         0 |         0 |     nan   |
| A06 MNQ full daily     |             12 |         0 |         0 |     nan   |        17 |         0 |         0 |     nan   |
| A07 MNQ cash daily     |             36 |         1 |      -450 |       0   |        15 |         0 |         0 |     nan   |
| A07 XAUUSD cash 4-hour |             77 |        77 |     10161 |      75.3 |        87 |        87 |      8690 |      75.9 |
| A09 XAUUSD cash daily  |             19 |        19 |      5588 |      68.4 |        19 |        19 |      4166 |      63.2 |
| A11 MNQ full 4-hour    |             54 |        16 |       718 |      43.8 |        56 |        16 |      1270 |      43.8 |
| A11 XAUUSD full 4-hour |             45 |        45 |     19414 |      37.8 |        47 |        47 |     15870 |      36.2 |
| A12 MNQ full 4-hour    |              1 |         0 |         0 |     nan   |         1 |         0 |         0 |     nan   |
| A12 XAUUSD full 1-hour |            154 |       154 |     11417 |      47.4 |       154 |       154 |      9125 |      47.4 |

Each strategy **alone** on its own $10,000 (its whole out-of-sample period):

| run                    |   A trades taken |   A of offered |   A net $ |   A return % |   A max DD % |   B trades taken |   B of offered |   B net $ |   B return % |   B max DD % |
|:-----------------------|-----------------:|---------------:|----------:|-------------:|-------------:|-----------------:|---------------:|----------:|-------------:|-------------:|
| A01 MNQ cash 4-hour    |                0 |             40 |      0    |          0   |          0   |                0 |             40 |      0    |          0   |          0   |
| A03 MNQ cash 1-hour    |                1 |            227 |     41.5  |          0.4 |          0   |                1 |            265 |     41.5  |          0.4 |          0   |
| A04 MNQ full 4-hour    |                0 |             38 |      0    |          0   |          0   |                0 |             40 |      0    |          0   |          0   |
| A05 MNQ cash 4-hour    |                0 |             34 |      0    |          0   |          0   |                0 |             40 |      0    |          0   |          0   |
| A06 MNQ full daily     |                0 |             18 |      0    |          0   |          0   |                0 |             23 |      0    |          0   |          0   |
| A07 MNQ cash daily     |                0 |             62 |      0    |          0   |          0   |                0 |             35 |      0    |          0   |          0   |
| A11 MNQ full 4-hour    |                0 |             95 |      0    |          0   |          0   |                0 |             98 |      0    |          0   |          0   |
| A12 MNQ full 4-hour    |                0 |              6 |      0    |          0   |          0   |                0 |              6 |      0    |          0   |          0   |
| A01 XAUUSD cash daily  |               19 |             21 |   1189.46 |         11.9 |         -4.1 |               17 |             19 |    773.85 |          7.7 |         -4.3 |
| A04 XAUUSD cash 4-hour |               46 |             46 |   2297.35 |         23   |         -7.3 |               49 |             50 |   2273.71 |         22.7 |         -6.4 |
| A06 MGC cash daily     |                5 |            121 |   -165.5  |         -1.7 |         -5.6 |                6 |            161 |    -26    |         -0.3 |         -3.8 |
| A07 XAUUSD cash 4-hour |              124 |            124 |   3704.53 |         37   |        -10.2 |              143 |            144 |   3222.12 |         32.2 |         -9.5 |
| A09 XAUUSD cash daily  |               27 |             29 |   1883.55 |         18.8 |         -6.3 |               27 |             29 |   1583.94 |         15.8 |         -3.3 |
| A11 XAUUSD full 4-hour |               84 |             84 |   8681.59 |         86.8 |        -17.6 |               86 |             86 |   8115.34 |         81.2 |        -18.2 |
| A12 XAUUSD full 1-hour |              305 |            305 |  14180.1  |        141.8 |        -19.9 |              305 |            305 |  14180.1  |        141.8 |        -19.9 |

## longest history (NAS100 + MGC)

| | A. ATR-sized, no hard stop | B. Real 2×ATR stop |
|---|---|---|
| Period | 2019-01-02 → 2021-10-01 (33.0 months) | 2019-01-02 → 2021-10-01 (33.0 months) |
| Trades the strategies gave | 731 | 816 |
| Trades taken | 697 | 776 |
| Trades skipped (minimum size risks > 2%) | 34 | 40 |
| Trades per month (taken) | 21.2 | 23.5 |
| Final balance | $97,133 | $95,073 |
| Net profit | $87,133 | $85,073 |
| Return | 871% | 851% |
| Per year (compounded) | 129% | 127% |
| Max drawdown (daily closes) | −$20,622 (-51.1%) | −$10,344 (-21.7%) |
| Win rate | 70.2% | 67.1% |
| Profit factor | 1.74 | 1.59 |
| Average win / average loss (in R) | +0.61R / -0.77R | +0.62R / -0.77R |
| Worst trade | -11.91R | -1.82R |
| Losses bigger than the 2% risk | 50 | 29 |
| Profitable months | 21 of 34 | 21 of 34 |
| Worst month | 2020-02 -10,802 | 2021-01 -3,883 |
| Most positions open at once (day closes) | 6 | 5 |
| Leverage (contract value ÷ equity): max / median | 10.9× / 2.2× | 10.3× / 1.8× |
| Account hit $0 | no | no |

Per strategy inside the book:

| run                    |   trades given |   A taken |   A net $ |   A win % |   B given |   B taken |   B net $ |   B win % |
|:-----------------------|---------------:|----------:|----------:|----------:|----------:|----------:|----------:|----------:|
| A01 MGC full daily     |             24 |         7 |       232 |      71.4 |        28 |         9 |     -1498 |      55.6 |
| A01 NAS100 full 4-hour |            154 |       154 |     17631 |      75.3 |       187 |       187 |     21043 |      71.7 |
| A03 NAS100 cash daily  |             31 |        31 |      3178 |      83.9 |        35 |        35 |      3668 |      77.1 |
| A04 MGC cash 4-hour    |             16 |        16 |      1155 |      87.5 |        16 |        16 |      1838 |      87.5 |
| A04 NAS100 full 4-hour |            134 |       134 |     22263 |      79.1 |       147 |       147 |     13643 |      74.2 |
| A06 MGC cash daily     |             60 |        43 |      -706 |      62.8 |        71 |        50 |      1583 |      68   |
| A06 NAS100 cash daily  |             42 |        42 |      5251 |      69   |        41 |        41 |      5479 |      70.7 |
| A07 NAS100 full 4-hour |            121 |       121 |     19460 |      78.5 |       140 |       140 |     16796 |      72.9 |
| A09 NAS100 cash daily  |             33 |        33 |       967 |      63.6 |        33 |        33 |      1875 |      54.6 |
| A11 NAS100 cash 1-hour |            116 |       116 |     17702 |      43.1 |       118 |       118 |     20646 |      41.5 |

Each strategy **alone** on its own $10,000 (its whole out-of-sample period):

| run                    |   A trades taken |   A of offered |   A net $ |   A return % |   A max DD % |   B trades taken |   B of offered |   B net $ |   B return % |   B max DD % |
|:-----------------------|-----------------:|---------------:|----------:|-------------:|-------------:|-----------------:|---------------:|----------:|-------------:|-------------:|
| A01 NAS100 full 4-hour |              286 |            286 |   5212.96 |         52.1 |        -31.3 |              306 |            306 |   6444.65 |         64.4 |        -18.2 |
| A03 NAS100 cash daily  |               55 |             55 |   4733.18 |         47.3 |         -5.9 |               73 |             73 |   2657.16 |         26.6 |        -10   |
| A04 NAS100 full 4-hour |              257 |            257 |  11277.8  |        112.8 |        -22.2 |              264 |            264 |   6708.62 |         67.1 |        -10.8 |
| A06 NAS100 cash daily  |              103 |            103 |   3888.9  |         38.9 |         -9.3 |              121 |            121 |   2329.6  |         23.3 |        -10.7 |
| A07 NAS100 full 4-hour |              328 |            328 |   6855.85 |         68.6 |        -22.9 |              544 |            544 |   5672.04 |         56.7 |        -26.3 |
| A09 NAS100 cash daily  |               80 |             80 |   2347.85 |         23.5 |        -19.9 |               80 |             80 |    396.73 |          4   |        -15.4 |
| A11 NAS100 cash 1-hour |              161 |            161 |  19550.8  |        195.5 |        -17.3 |              191 |            191 |  33148.5  |        331.5 |        -21.4 |
| A01 MGC full daily     |                0 |             56 |      0    |          0   |          0   |                0 |             66 |      0    |          0   |          0   |
| A04 MGC cash 4-hour    |               14 |             76 |    158    |          1.6 |         -6.4 |               15 |             81 |    247.5  |          2.5 |         -4.5 |
| A06 MGC cash daily     |                5 |            121 |   -165.5  |         -1.7 |         -5.6 |                6 |            161 |    -26    |         -0.3 |         -3.8 |

## Do the strategies still pass every check with a real 2×ATR stop?

6 of 22 re-runs pass every key check (same rule as the timeframe study; all 22 passed without the stop). Full-history and out-of-sample figures at $100,000 of contract value:

| strategy                  | market   | session   | bars   |   trades |   win_pct |   payoff_ratio |   pf |      net |   wf_oos_trades |   wf_oos_net |   wf_oos_pf |   mc_prob_loss_pct |   stress_worst_net |   checks_passed |   checks_total | robust   |
|:--------------------------|:---------|:----------|:-------|---------:|----------:|---------------:|-----:|---------:|----------------:|-------------:|------------:|-------------------:|-------------------:|----------------:|---------------:|:---------|
| a01_rsi_ema_vwap          | MNQ      | rth       | 4-hour |      116 |     71.55 |           0.86 | 2.15 | 40151.4  |              40 |     18048.3  |        2.72 |               0.2  |           19503.2  |              13 |             13 | True     |
| a03_williams_ema_vwap     | MNQ      | rth       | 1-hour |      243 |     53.91 |           0.86 | 1    |   140.29 |             265 |     -5606.61 |        0.92 |              69.26 |            8292.5  |               6 |             13 | False    |
| a04_rsi_ema50_vwap        | MNQ      | full      | 4-hour |      153 |     69.28 |           0.5  | 1.14 |  4978.84 |              40 |      5301.05 |        1.96 |               3.66 |            6641.21 |              12 |             13 | True     |
| a05_zscore_mean_reversion | MNQ      | rth       | 4-hour |      230 |     54.78 |           0.88 | 1.06 | 10185.1  |              40 |     11636    |        1.4  |              21.02 |           15432.9  |              11 |             13 | False    |
| a06_rubber_band           | MNQ      | full      | daily  |       50 |     72    |           0.93 | 2.39 | 39828.3  |              23 |     31571.5  |        4.12 |               0.28 |           -9423.06 |              11 |             13 | False    |
| a07_mfi_reversal          | MNQ      | rth       | daily  |      160 |     65.62 |           0.7  | 1.34 | 38005.3  |              35 |     16321.8  |        1.87 |               7.66 |           22529.8  |              13 |             13 | True     |
| a11_time_series_momentum  | MNQ      | full      | 4-hour |      147 |     35.37 |           2.3  | 1.26 | 22794.5  |              98 |     29333.5  |        1.82 |              10.24 |           34514.4  |              11 |             13 | False    |
| a01_rsi_ema_vwap          | XAUUSD   | rth       | daily  |       35 |     65.71 |           0.68 | 1.3  | 10286.9  |              19 |     15918.8  |        1.89 |              13.42 |           23594.9  |              10 |             12 | False    |
| a04_rsi_ema50_vwap        | XAUUSD   | rth       | 4-hour |       76 |     69.74 |           0.59 | 1.36 | 11983    |              50 |      4343.04 |        1.12 |              35.38 |           14441.2  |               8 |             12 | False    |
| a06_rubber_band           | MGC      | rth       | daily  |      210 |     61.9  |           0.72 | 1.17 | 18616    |             161 |     42204.6  |        1.56 |               1.88 |           28413    |              11 |             13 | False    |
| a07_mfi_reversal          | XAUUSD   | rth       | 4-hour |      508 |     63.78 |           0.6  | 1.06 |  9906.3  |             144 |     22148.5  |        1.34 |               9.24 |           -5434.37 |               8 |             12 | False    |
| a09_turn_of_month         | XAUUSD   | rth       | daily  |       64 |     56.25 |           1.21 | 1.56 | 26845.7  |              29 |     23601.5  |        2.27 |               4.04 |           42393.8  |              12 |             12 | True     |
| a11_time_series_momentum  | XAUUSD   | full      | 4-hour |       88 |     40.91 |           2.62 | 1.81 | 43108.9  |              86 |     34281.4  |        1.79 |               7.16 |           47335.8  |               9 |             12 | False    |
| a01_rsi_ema_vwap          | NAS100   | full      | 4-hour |      373 |     66.22 |           0.59 | 1.16 | 20828.5  |             306 |     29680.5  |        1.25 |               5.38 |           14011.9  |              10 |             12 | False    |
| a03_williams_ema_vwap     | NAS100   | rth       | daily  |       91 |     61.54 |           0.88 | 1.4  | 43726.5  |              73 |     37056.1  |        1.82 |               2.38 |           55043.7  |              11 |             12 | True     |
| a04_rsi_ema50_vwap        | NAS100   | full      | 4-hour |      257 |     70.43 |           0.52 | 1.23 | 15890.6  |             264 |     24638.9  |        1.33 |               4.78 |           -7444.78 |               9 |             12 | False    |
| a06_rubber_band           | NAS100   | rth       | daily  |      119 |     70.59 |           0.53 | 1.26 | 28703.9  |             121 |     34897.5  |        1.31 |              11.12 |           47774.7  |              10 |             12 | False    |
| a07_mfi_reversal          | NAS100   | full      | 4-hour |     1468 |     67.03 |           0.54 | 1.1  | 46311    |             544 |     32708.7  |        1.2  |               6.42 |          -15842.3  |               9 |             12 | False    |
| a09_turn_of_month         | NAS100   | rth       | daily  |      115 |     59.13 |           1.07 | 1.55 | 55396.3  |              80 |     26937.1  |        1.33 |              14.02 |           34450.3  |               9 |             12 | False    |
| a11_time_series_momentum  | NAS100   | rth       | 1-hour |      209 |     41.15 |           2.52 | 1.76 | 82267    |             191 |     71177.1  |        1.84 |               0.14 |           83853.3  |              11 |             12 | True     |
| a01_rsi_ema_vwap          | MGC      | full      | daily  |       62 |     69.35 |           0.58 | 1.32 | 13304.7  |              66 |     28619.9  |        1.69 |               4.22 |           33086.8  |              10 |             13 | False    |
| a04_rsi_ema50_vwap        | MGC      | rth       | 4-hour |      139 |     65.47 |           0.76 | 1.43 | 19158.1  |              81 |     12352.1  |        1.38 |              12.14 |            2303.2  |              10 |             13 | False    |
