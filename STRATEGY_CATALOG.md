# Strategy catalog: from the 53 photos in `T9/Strategy photos`

Read 2026-11-22. `IMG_2695 copy.jpeg` is an exact duplicate of `IMG_2695.jpg`.
For each idea: what the photo says, what is **missing or assumed** (marked ⚠), and whether our data can test it.
Nothing here has been coded or backtested yet. **Rules marked ⚠ need your confirmation.**

The performance numbers in the photos (e.g. "PF 3.94, 78.6% win rate") are the creators' claims,
mostly on QQQ/SPY daily since 1999 with **no costs**. We'll measure our own.

---

## Group A: testable on our data (NQ/MNQ, NAS100, GC/MGC, XAUUSD)

### A1. RSI + EMA + VWAP pullback (IMG_2695, QQQ daily)
- **Entry (all must be true at the close):** RSI(3) < 22, EMA(100) today > EMA(100) five days ago, close at least 1% below the 10-day rolling VWAP.
- **Execution:** buy the next open.
- **Exit:** next open after RSI(3) > 55.
- Long only. Photo: fixed $100k position, no costs.
- Complete rules.

### A2. Stochastic + KAMA + VWAP (IMG_2696, SPY daily)
- **Entry:**
  - Stochastic(21,3) below 55
  - KAMA(10, fast 3, slow 75) as trend filter
  - 200-day rolling VWAP with 1.005 / 0.995 buffers as price filter
- **Execution:** buy the next open when all align.
- **Exit:** "signal recovery", or after 25 trading days at most.
- ⚠ Assumptions:
  - %K (not %D) < 55
  - trend filter = close > KAMA
  - price filter = close < VWAP × 0.995
  - recovery = %K > 55

### A3. Williams %R + EMA + VWAP (IMG_2697, QQQ daily)
- **Entry:** %R pullback, long-term EMA bullish, close below rolling VWAP.
- **Execution:** buy the next open.
- **Exit:** "momentum recovery". One position at a time.
- ⚠ No numbers given. Starting point, to be explored with the parameter test:
  - %R(10) < −80
  - close > EMA(200)
  - close < 10-day VWAP
  - exit when %R > −20

### A4. RSI + EMA(50) + VWAP on ES (IMG_2698, ES futures daily)
- **Entry:** RSI pullback, EMA(50) confirms trend, close below 10-day rolling VWAP.
- **Execution:** buy the next open.
- **Exit:** RSI recovery. Photo assumes $30 round-trip cost.
- ⚠ Assumptions:
  - RSI(3) < 22, same as A1
  - close > EMA(50)
  - exit RSI(3) > 55
- We have no ES; test it on NQ/NAS100.

### A5. Z-score mean reversion (IMG_2701–2702, 2713, 2736, 2742–2744)
- z = (close − rolling mean) / rolling std, window 20–60 days.
- **Entry:** short when z > +2, long when z < −2.
- **Exit:** |z| < 0.5.
- **Stop:** |z| > 4 (from the pairs toolkit).
- Applied to a single instrument's price. The photos apply it to a pair spread; see B1.

### A6. "Rubber Band" (IMG_2714 #2, SPY daily)
- Buy on a close below a volatility band; exit on the breakout.
- ⚠ The band isn't defined in the photo. My recollection of QuantifiedStrategies' published version, unverified:
  - band = 5-day high − 2.5 × ATR(10)
  - buy at the close when the close is below the band
  - sell when the close > yesterday's high

### A7. MFI reversal (IMG_2714 #3, QQQ daily)
- Buy when the 2-day Money Flow Index < 10.
- ⚠ Exit not given. Assumed: sell when the close > yesterday's high.

### A8. Weekly RSI (IMG_2714 #5, XLP)
- Buy when the 2-week RSI < 15.
- ⚠ Exit not given. Assumed: weekly RSI(2) > 70.
- Few trades expected on our data.

### A9. Turn of the month (IMG_2714 #6)
- Buy 5 trading days before month-end; sell on the 3rd trading day of the next month.
- Complete rules.

### A10. Faber 10-month moving average (IMG_2730)
- At each month-end: hold if close > 10-month SMA, otherwise flat.
- Complete rules. Very few trades.

### A11. Time-series momentum / trend (IMG_2713, 2720, 2727 chart)
- **Entry:** buy when the 20-day return > 5% (or close > 50-day MA).
- **Exit:** "on trend break". ⚠ Assumed: close < 50-day MA.

### A12. Volatility compression breakout (IMG_2700, daytrading.co)
- Tight range → enter on a breakout with momentum.
- ⚠ No rules given. Proposed:
  - squeeze = Bollinger(20,2) width in its lowest 10% of the last 100 bars
  - then buy/sell stop at the squeeze range high/low
  - stop at the other side, target 2R
  - intraday (5–15 min)

### A13. Order-flow imbalance, slow version (IMG_2711)
- OFI = buy volume − sell volume. Next move ≈ λ × OFI, with λ from rolling 5-day regressions on 1-second bars.
- Holds from 50 ms to 3 minutes. A session loss limit stops it.
- We have NQ 1-second bars with buy/sell volume, so a 1-second-to-1-minute version is testable.
- The real "sub-500 µs" HFT version is **not** testable (needs exchange-colocated execution).

## Group B: needs a two-instrument (pairs) extension of the engine

### B1. Pairs / statistical arbitrage
Photos: IMG_2705–2706, 2713, 2719 (basis trade), 2729, 2732, 2736–2747.

**Method:**
- Engle-Granger cointegration test
- hedge ratio β from 60-day rolling OLS (or a Kalman filter)
- spread z-score: enter at ±2, exit at ±0.5, stop at |z| > 4
- OU half-life to check holding time
- inverse-volatility sizing

**Pairs our data supports:**
- **GC futures vs XAUUSD spot.** Same metal, 2021-06 → 2025-12. This is really a futures-vs-spot "basis" trade.
- NQ vs NAS100. Only 9 months of overlap, so too short.

The engine currently trades one instrument. This needs a pairs mode.

## Group C: can't be tested with this data

| Idea | Photos | Why not |
|---|---|---|
| Cross-sectional momentum, factor investing, value + momentum everywhere, Jegadeesh-Titman, PCA factors | 2703–04, 2709–10, 2727–28, 2734 | Need hundreds of stocks |
| Market making (Avellaneda-Stoikov) | 2707–08, 2723 | Needs order-queue simulation; 1-min bars can't tell if a passive quote would have filled |
| True HFT | 2711–12 | Microsecond execution |
| Options / volatility trading (Black-Scholes, term structure, dispersion, gamma scalping, skew) | 2718, 2719, 2724 | No options data |
| Merger / convertible / capital-structure / yield-curve arbitrage, TLT, stocks/gold/bonds rotation, Russell rebalancing | 2714, 2719 | No such instruments |
| Roll yield | 2719 | Needs every GC contract; DATA has only the stitched series |
| Event-driven | 2725 | No news/economic calendar in DATA |
| "Volatility bands", "Treasury long/short" | 2714 #7, #8 | Rules not disclosed |
| Execution algorithms (TWAP/VWAP/POV) | 2726 | Not a trading strategy |

## Group D: tools and lessons, useful for the engine (not strategies)
- **Regime filter.** Gaussian mixture on 21-day return and volatility splits calm vs crisis (IMG_2733). It can gate any strategy.
- **GARCH volatility forecast** (IMG_2731). Usable for position sizing or as a filter.
- **Missing metrics** (IMG_2717, 2748): Sortino, Calmar, CAGR, VaR/CVaR, information ratio vs buy-and-hold, time in market. These are easy to add.
- **Sizing:** inverse-volatility / volatility targeting (IMG_2743, 2748) and Kelly (IMG_2716).
- **Lessons the photos themselves make:**
  - ML at 53% accuracy wasn't significant (2735).
  - A cointegrated pair broke out of sample (2732).
  - Walk-forward is the standard check (2740, 2746).

  Our robustness tools already cover these.

## Important caveats for Group A
- Most Group A strategies are **long-only daily dip-buying on stock indices**. They benefit from the long uptrend, so they must be compared with buy-and-hold on the same data.
- On daily bars our data is thin:
  - NQ: 2021–2026, about 5.6 years
  - NAS100: 2012–2021, about 9.7 years
  - GC: 2016–2025
  - XAUUSD: 2021–2026

  A strategy that made 215 trades in 27 years would make only about 45–75 here. That's too few to prove much on its own. We'll test each on several markets and pool the evidence.
- The equity versions use the stock-market close (16:00 New York). Futures trade nearly 24h, so "daily close" must be chosen: cash session (09:30–16:00 ET) or full futures session.
