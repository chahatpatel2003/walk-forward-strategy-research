# All strategies on one $10,000 account, 2% risk per trade, compounding: holding vs. closing at 16:00 ET

*Generated November 23, 2026 by `tools/combined_account.py`. All 24 runs of both books in TIMEFRAME_STUDY_RESULTS.md section 7, every walk-forward out-of-sample trade.*

* **A** = saved trades sized by 2 × ATR(14), no hard stop. **B** = re-runs with a real 2 × ATR stop (SINGLE_ACCOUNT_10K.md). **hold** = the strategies' own exits. **16:00** = every position still open at the New York cash close (13:00 on half days) is closed there at the bid (long) / ask (short) with slippage and commission; nothing is re-entered.
* Risk sizing is the same in all four: 2% of the balance ÷ (stop distance × point value), rounded down to whole MNQ/MGC contracts or 0.01 lots; skipped if one contract risks more. With the 16:00 exit the stop distance is still 2 × ATR of the strategy's own bars, so intraday positions are sized conservatively.
* **The multi-million 'hold' results are compounding arithmetic, not a tradable outcome:** at those balances 2% risk means up to 1,264 MNQ contracts or 160 lots of gold in one trade (see 'Largest single position'), with contract value up to ~15× equity; fills, margin and liquidity would not be the same. Per-strategy dollar figures are dominated by WHEN a strategy traded (late trades are sized on a much bigger balance), so compare the strategies by sign, not size. Drawdown is measured at daily closes, so the intraday swings of the 16:00 versions are not in it.
* The markets don't overlap in time: NAS100 data ends 2021-09-30, while the MNQ and spot-gold out-of-sample trades start in 2022. The yearly table shows what traded when.

| | A hold | A 16:00 | B hold | B 16:00 |
|---|---|---|---|---|
| Period | 2013-08-01 → 2026-11-17 | 2013-08-01 → 2026-11-17 | 2013-08-01 → 2026-11-17 | 2013-08-01 → 2026-11-17 |
| Trades taken | 2,652 | 2,347 | 3,067 | 2,846 |
| Trades skipped (1 contract risks > 2%) | 0 | 305 | 0 | 221 |
| Trades per month | 16.6 | 14.7 | 19.2 | 17.8 |
| Trades cut at the 16:00 close | 0 | 2,082 | 0 | 2,176 |
| Positions held overnight | 2,081 | 2 | 2,175 | 2 |
| $10,000 → | **$23,648,824** | **$35,666** | **$7,899,125** | **$38,932** |
| Per year (compounded) | 79.4% | 10.0% | 65.2% | 10.8% |
| Max drawdown (daily closes) | −$7,210,885 (-53.2%) | −$7,412 (-31.0%) | −$4,176,995 (-40.2%) | −$9,241 (-28.2%) |
| Win rate | 64.7% | 58.7% | 62.1% | 57.4% |
| Profit factor | 1.44 | 1.14 | 1.28 | 1.12 |
| Average win / loss | +0.7R / -0.79R | +0.37R / -0.45R | +0.68R / -0.78R | +0.37R / -0.43R |
| Worst trade | -11.91R | -4.51R | -4.35R | -1.01R |
| Profitable months | 97 of 160 | 79 of 160 | 93 of 160 | 85 of 160 |
| Worst month | 2026-06 -4,451,362 | 2025-10 -3,200 | 2026-06 -2,574,623 | 2024-07 -4,828 |
| Most positions open at the same moment | 11 | 6 | 10 | 6 |
| Max contract value ÷ balance (any moment) | 16.7× | 10.5× | 14.9× | 10.5× |
| Largest single position (contracts / lots) | MGC 568, MNQ 1,264, NAS100 70.28, XAUUSD 160.61 | MGC 3, MNQ 3, NAS100 10.69, XAUUSD 1.03 | MGC 255, MNQ 576, NAS100 68.81, XAUUSD 66.05 | MGC 4, MNQ 4, NAS100 12.18, XAUUSD 1.17 |
| Account hit $0 | no | no | no | no |

### A hold: year by year

|   year |          start $ |            end $ |   return % |   max DD % in year |   trades | markets traded   |
|-------:|-----------------:|-----------------:|-----------:|-------------------:|---------:|:-----------------|
|   2013 |  10000           |  11258           |       12.6 |               -7.6 |       10 | NAS100           |
|   2014 |  11258           |  10670           |       -5.2 |               -5.6 |        3 | NAS100           |
|   2015 |  10670           |  10022           |       -6.1 |              -43.4 |      131 | NAS100           |
|   2016 |  10022           |  11035           |       10.1 |              -39.5 |      177 | NAS100           |
|   2017 |  11035           |  37385           |      238.8 |              -14.1 |      149 | NAS100           |
|   2018 |  37385           |  27101           |      -27.5 |              -49.4 |      169 | NAS100           |
|   2019 |  27101           |  75198           |      177.5 |              -19   |      241 | MGC, NAS100      |
|   2020 |  75198           | 153685           |      104.4 |              -53.2 |      268 | MGC, NAS100      |
|   2021 | 153685           | 286341           |       86.3 |              -18.8 |      227 | MGC, NAS100      |
|   2022 | 286341           | 312106           |        9   |               -5.9 |       61 | MGC, MNQ, XAUUSD |
|   2023 | 312106           | 434481           |       39.2 |              -12.2 |      185 | MGC, MNQ, XAUUSD |
|   2024 | 434481           |      1.86278e+06 |      328.7 |              -27.6 |      381 | MGC, MNQ, XAUUSD |
|   2025 |      1.86278e+06 |      1.4842e+07  |      696.8 |              -35.3 |      412 | MGC, MNQ, XAUUSD |
|   2026 |      1.4842e+07  |      2.36488e+07 |       59.3 |              -25.1 |      238 | MNQ, XAUUSD      |

### A 16:00: year by year

|   year |   start $ |   end $ |   return % |   max DD % in year |   trades | markets traded   |
|-------:|----------:|--------:|-----------:|-------------------:|---------:|:-----------------|
|   2013 |     10000 |   10104 |        1   |               -2   |       10 | NAS100           |
|   2014 |     10104 |    9872 |       -2.3 |               -2.7 |        3 | NAS100           |
|   2015 |      9872 |    7708 |      -21.9 |              -30.9 |      131 | NAS100           |
|   2016 |      7708 |    9686 |       25.7 |              -11.6 |      177 | NAS100           |
|   2017 |      9686 |   11319 |       16.9 |              -11.1 |      149 | NAS100           |
|   2018 |     11319 |    8784 |      -22.4 |              -27.3 |      169 | NAS100           |
|   2019 |      8784 |   13486 |       53.5 |               -9.2 |      213 | MGC, NAS100      |
|   2020 |     13486 |   19740 |       46.4 |              -13.7 |      239 | MGC, NAS100      |
|   2021 |     19740 |   27016 |       36.9 |              -18.7 |      215 | MGC, NAS100      |
|   2022 |     27016 |   26701 |       -1.2 |               -3.1 |       58 | MGC, MNQ, XAUUSD |
|   2023 |     26701 |   28618 |        7.2 |              -12.3 |      182 | MGC, MNQ, XAUUSD |
|   2024 |     28618 |   30887 |        7.9 |              -16.3 |      295 | MGC, MNQ, XAUUSD |
|   2025 |     30887 |   34396 |       11.4 |              -16.6 |      324 | MGC, MNQ, XAUUSD |
|   2026 |     34396 |   35666 |        3.7 |              -17.2 |      182 | MNQ, XAUUSD      |

### B hold: year by year

|   year |          start $ |            end $ |   return % |   max DD % in year |   trades | markets traded   |
|-------:|-----------------:|-----------------:|-----------:|-------------------:|---------:|:-----------------|
|   2013 |  10000           |  10873           |        8.7 |               -9.7 |       11 | NAS100           |
|   2014 |  10873           |  12871           |       18.4 |               -4.9 |        9 | NAS100           |
|   2015 |  12871           |  10832           |      -15.8 |              -36.1 |      250 | NAS100           |
|   2016 |  10832           |  13065           |       20.6 |              -24.3 |      190 | NAS100           |
|   2017 |  13065           |  32152           |      146.1 |              -13.6 |      199 | NAS100           |
|   2018 |  32152           |  25725           |      -20   |              -40.2 |      219 | NAS100           |
|   2019 |  25725           |  50417           |       96   |              -17.9 |      267 | MGC, NAS100      |
|   2020 |  50417           | 180743           |      258.5 |              -21.5 |      297 | MGC, NAS100      |
|   2021 | 180743           | 285923           |       58.2 |              -18   |      257 | MGC, NAS100      |
|   2022 | 285923           | 284992           |       -0.3 |               -9.8 |       48 | MGC, MNQ, XAUUSD |
|   2023 | 284992           | 329699           |       15.7 |              -20.9 |      219 | MGC, MNQ, XAUUSD |
|   2024 | 329699           |      1.04761e+06 |      217.7 |              -29.7 |      377 | MGC, MNQ, XAUUSD |
|   2025 |      1.04761e+06 |      6.78638e+06 |      547.8 |              -26.6 |      444 | MGC, MNQ, XAUUSD |
|   2026 |      6.78638e+06 |      7.89912e+06 |       16.4 |              -34.6 |      280 | MNQ, XAUUSD      |

### B 16:00: year by year

|   year |   start $ |   end $ |   return % |   max DD % in year |   trades | markets traded   |
|-------:|----------:|--------:|-----------:|-------------------:|---------:|:-----------------|
|   2013 |     10000 |   10061 |        0.6 |               -2.5 |       11 | NAS100           |
|   2014 |     10061 |   10226 |        1.6 |               -2   |        9 | NAS100           |
|   2015 |     10226 |    9380 |       -8.3 |              -28.2 |      250 | NAS100           |
|   2016 |      9380 |   11193 |       19.3 |              -12.7 |      190 | NAS100           |
|   2017 |     11193 |   11952 |        6.8 |              -20.3 |      199 | NAS100           |
|   2018 |     11952 |   10557 |      -11.7 |              -21.2 |      219 | NAS100           |
|   2019 |     10557 |   15166 |       43.7 |              -12.5 |      248 | MGC, NAS100      |
|   2020 |     15166 |   25598 |       68.8 |               -7.8 |      262 | MGC, NAS100      |
|   2021 |     25598 |   32341 |       26.3 |              -18.2 |      252 | MGC, NAS100      |
|   2022 |     32341 |   30786 |       -4.8 |               -6.2 |       47 | MGC, MNQ, XAUUSD |
|   2023 |     30786 |   32228 |        4.7 |              -15.9 |      219 | MGC, MNQ, XAUUSD |
|   2024 |     32228 |   37158 |       15.3 |              -18   |      339 | MGC, MNQ, XAUUSD |
|   2025 |     37158 |   41255 |       11   |              -12.8 |      372 | MGC, MNQ, XAUUSD |
|   2026 |     41255 |   38932 |       -5.6 |              -19.2 |      229 | MNQ, XAUUSD      |

### Net profit by strategy inside the combined account

| run                    |   trades (A hold) |     A hold net $ |   A 16:00 net $ |      B hold net $ |   B 16:00 net $ |
|:-----------------------|------------------:|-----------------:|----------------:|------------------:|----------------:|
| A01 MGC full daily     |                56 | 212141           |             -16 |  133199           |             162 |
| A01 MNQ cash 4-hour    |                40 | 782326           |             450 |  265259           |           -1311 |
| A01 NAS100 full 4-hour |               286 |  51310           |            4372 |   59801           |            7384 |
| A01 XAUUSD cash daily  |                21 | -80425           |             -25 | -115914           |            -868 |
| A03 MNQ cash 1-hour    |               227 |      1.92956e+06 |           -7910 |      -1.56129e+06 |           -9277 |
| A03 NAS100 cash daily  |                55 |  14968           |             510 |   13783           |            1849 |
| A04 MGC cash 4-hour    |                76 | 862675           |            -176 |  248527           |            -389 |
| A04 MNQ full 4-hour    |                38 |      1.68037e+06 |           -1800 |  355299           |           -1253 |
| A04 NAS100 full 4-hour |               257 |  67885           |            2605 |   40321           |            4664 |
| A04 XAUUSD cash 4-hour |                46 |      1.6865e+06  |            -193 |  491281           |            -576 |
| A05 MNQ cash 4-hour    |                34 |      1.22995e+06 |              -2 |  401793           |            -288 |
| A06 MGC cash daily     |               121 | 109200           |            -572 |  280762           |           -2378 |
| A06 MNQ full daily     |                18 |      1.53806e+06 |               0 |  739180           |               0 |
| A06 NAS100 cash daily  |               103 |  17784           |            2157 |   17187           |            2549 |
| A07 MNQ cash daily     |                62 | 843402           |               0 |  380177           |               0 |
| A07 NAS100 full 4-hour |               328 |  62110           |            4340 |   57321           |            3607 |
| A07 XAUUSD cash 4-hour |               124 | 514986           |            -126 |  496238           |             -47 |
| A09 NAS100 cash daily  |                80 |   7797           |             945 |    6264           |           -1782 |
| A09 XAUUSD cash daily  |                29 |      1.74802e+06 |            1647 |  555159           |            1879 |
| A11 MNQ full 4-hour    |                95 |      3.02223e+06 |            2376 |       1.37154e+06 |            1401 |
| A11 NAS100 cash 1-hour |               161 |  60994           |            2313 |   74284           |            4972 |
| A11 XAUUSD full 4-hour |                84 |      2.52602e+06 |            2235 |       1.44215e+06 |            3118 |
| A12 MNQ full 4-hour    |                 6 |  67235           |             299 |   42388           |             299 |
| A12 XAUUSD full 1-hour |               305 |      4.68372e+06 |           12236 |       2.09441e+06 |           15217 |
