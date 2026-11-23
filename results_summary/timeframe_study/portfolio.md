Selection: runs that passed all key checks, one per strategy and underlying (most out-of-sample trades per month), measured only on the dates inside every selected run's walk-forward fold schedule (a fold with no valid parameter set trades nothing and counts as zero). Each run trades its own $100,000 account with its own sizing rule (most size a trade at about $100,000 of contract value; risk-sized ones vary, see the entry-notional columns), so the combined P&L below is the sum of separate accounts, NOT one capital-constrained account: see the gross-exposure and positions-open rows. 'Marked' includes positions already open on the first day; 'flat start' counts only trades entered in the window. Drawdowns are on daily closes. The runs were chosen among those whose checks include their out-of-sample results, so this is NOT a fresh hold-out test.

<!--BOOK tradable now (MNQ + MGC + XAUUSD)-->

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

<!--BOOK longest history (NAS100 + MGC)-->

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

