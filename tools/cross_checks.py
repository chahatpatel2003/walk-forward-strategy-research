import numpy as np, pandas as pd, pyarrow.parquet as pq, os, glob
D = '/Volumes/T9/DATA/'
pd.set_option('display.width', 220)
xau = pd.read_parquet(D+'XAUUSD_Gold_spot_Dukascopy/bars_1m_bid_ask_mid_2021-06-29_to_2026-11-17.parquet')
xau['t'] = pd.to_datetime(xau.ts, unit='s', utc=True)
xau['spr'] = xau.ask_c - xau.bid_c
print("=== XAU spread (ask_c - bid_c, $/oz)")
print(xau.groupby(xau.t.dt.year).spr.describe(percentiles=[.5,.9,.99])[['mean','50%','90%','99%','max']].round(3).to_string())
h = xau.groupby(xau.t.dt.hour).spr.median().round(3); print("median spread by UTC hour:", dict(h))
print("bars with negative spread:", int((xau.spr < 0).sum()), "| n_ticks per bar median:", xau.n_ticks.median())
# bid-only bars file vs bid_ask file
b = pd.read_parquet(D+'XAUUSD_Gold_spot_Dukascopy/bars_1m_2021-06-29_to_2026-06-28.parquet')
b['ts'] = b.timestamp_utc.astype('int64')//10**9
m = b.merge(xau[['ts','bid_o','bid_c','mid_c','ask_c']], on='ts', how='outer', indicator=True)
print("\n=== XAU bars_1m vs bid_ask file: ", m._merge.value_counts().to_dict(), "| close==bid_c:", round(float((abs(m.close - m.bid_c) < 1e-6).mean()),4))
# TradingView OANDA vs Dukascopy
tv = pd.read_parquet(D+'XAUUSD_Gold_spot_Dukascopy/tradingview_OANDA_XAUUSD_1m_2026-10-22_to_2026-11-18.parquet')
j = tv.rename(columns={'time':'ts'}).merge(xau[['ts','mid_c']], on='ts')
for lag in [-1,0,1]:
    jj = tv.rename(columns={'time':'ts'}).assign(ts=lambda d: d.ts + 60*lag).merge(xau[['ts','mid_c']], on='ts')
    print(f"TV OANDA vs Duka mid, lag {lag:+d}m: n={len(jj)} median|diff|=${(jj.close-jj.mid_c).abs().median():.3f}  ret corr={np.corrcoef(jj.close.diff()[1:], jj.mid_c.diff()[1:])[0,1]:.3f}")
# GC vs XAU
gc = pd.read_parquet(D+'GC_Gold_futures/bars_1m_continuous_2016-01_to_2025-12.parquet')
print("\n=== GC (futures) vs XAU (spot) overlap")
for lag in [-2,-1,0,1,2]:
    jj = gc[['ts','c','contract']].assign(ts=lambda d: d.ts + 60*lag).merge(xau[['ts','mid_c']], on='ts')
    same = jj.contract == jj.contract.shift()
    r1, r2 = jj.c.diff()[same], jj.mid_c.diff()[same]
    print(f"   lag {lag:+d}m: n={len(jj):,} 1m-change corr={np.corrcoef(r1[1:], r2[1:])[0,1]:.3f}")
jj = gc[['ts','c']].merge(xau[['ts','mid_c']], on='ts'); jj['t']=pd.to_datetime(jj.ts,unit='s'); jj['basis']=jj.c-jj.mid_c
print("   GC - XAU basis ($) by year:", jj.groupby(jj.t.dt.year).basis.median().round(1).to_dict())
# NQ vs NAS100
nq = pd.read_parquet(D+'NQ_Nasdaq100_futures/bars_1m_front_contract_2021-01_to_2026-08-14.parquet')
na = pd.read_parquet(D+'NAS100_CFD_Dukascopy/bars_1m_mid_2012-02_to_2021-09.parquet')
print("\n=== NQ (futures) vs NAS100 (CFD) overlap 2021-01..2021-09")
for lag in [-1,0,1]:
    jj = nq[['ts','c','symbol']].assign(ts=lambda d: d.ts + 60*lag).merge(na[['ts','c']], on='ts', suffixes=('_nq','_na'))
    same = jj.symbol == jj.symbol.shift()
    print(f"   lag {lag:+d}m: n={len(jj):,} 1m-change corr={np.corrcoef(jj.c_nq.diff()[same][1:], jj.c_na.diff()[same][1:])[0,1]:.3f}")
jj = nq[['ts','c']].merge(na[['ts','c']], on='ts', suffixes=('_nq','_na')); print("   NQ - NAS100 median basis (pts):", round((jj.c_nq-jj.c_na).median(),1))
# NAS100 complete-days file
nc = pd.read_parquet(D+'NAS100_CFD_Dukascopy/bars_1m_mid_0930-1600_complete_days_2012-02_to_2021-09.parquet')
print(f"   NAS100 complete cash-session days: {nc.session.nunique()}  bars={len(nc):,}  bars/day={len(nc)/nc.session.nunique():.0f} (390 expected)")
print("   per year:", pd.Series(pd.to_datetime(nc.session.unique()).year).value_counts().sort_index().to_dict())
