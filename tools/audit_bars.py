"""Read-only quality audit of a 1-minute OHLCV series. Usage: audit_bars.py NAME"""
import sys, numpy as np, pandas as pd
D = '/Volumes/T9/DATA/'
def load(name):
    if name == 'GC':
        df = pd.read_parquet(D+'GC_Gold_futures/bars_1m_continuous_2016-01_to_2025-12.parquet'); df['sym'] = df.contract.astype(str)
    elif name == 'NQ':
        df = pd.read_parquet(D+'NQ_Nasdaq100_futures/bars_1m_front_contract_2021-01_to_2026-08-14.parquet'); df['sym'] = df.symbol
    elif name == 'NAS100':
        df = pd.read_parquet(D+'NAS100_CFD_Dukascopy/bars_1m_mid_2012-02_to_2021-09.parquet'); df['sym'] = 'NAS100'
    elif name == 'XAU':
        df = pd.read_parquet(D+'XAUUSD_Gold_spot_Dukascopy/bars_1m_bid_ask_mid_2021-06-29_to_2026-11-17.parquet')
        df = df.rename(columns={'mid_o':'o','mid_h':'h','mid_l':'l','mid_c':'c','volume':'v'}); df['sym'] = 'XAU'
    df['t'] = pd.to_datetime(df.ts, unit='s', utc=True)
    return df
name = sys.argv[1]; df = load(name)
print(f"===== {name}: {len(df):,} bars  {df.t.min()} -> {df.t.max()}")
print("dup ts:", df.ts.duplicated().sum(), "| non-increasing ts:", (np.diff(df.ts.values) <= 0).sum(),
      "| NaN o/h/l/c:", int(df[['o','h','l','c']].isna().sum().sum()), "| price<=0:", int((df[['o','h','l','c']] <= 0).sum().sum()))
bad = (df.h < df[['o','c']].max(axis=1) - 1e-9) | (df.l > df[['o','c']].min(axis=1) + 1e-9) | (df.h < df.l)
print("OHLC inconsistent bars:", int(bad.sum()), "| zero-range bars %:", round(100*(df.h == df.l).mean(), 2), "| v==0 bars:", int((df.v == 0).sum()))
yr = df.groupby(df.t.dt.year).agg(bars=('ts','size'), days=('t', lambda s: s.dt.date.nunique()))
yr['bars_per_day'] = (yr.bars / yr.days).round(0); print("\nper year:\n", yr.T.to_string())
# gaps
g = np.diff(df.ts.values) // 60
gap = pd.Series(g)
cats = pd.cut(gap, [0,1,5,30,59,61,180,60*24,60*24*2,60*24*4,1e9], labels=['1m(ok)','2-5m','6-30m','31-59m','60-61m(daily break)','62-180m','3h-1d','1-2d','2-4d(weekend/holiday)','>4d'])
print("\ngap size distribution:\n", cats.value_counts().sort_index().to_string())
big = gap[(gap > 61) & ~((gap >= 60*24*2 - 120) & (gap <= 60*24*3 + 120))]  # exclude normal weekend
bi = big.sort_values(ascending=False).head(12).index
print("\nlargest non-weekend gaps (>61 min):")
for i in bi: print(f"   {df.t.iloc[i]} -> {df.t.iloc[i+1]}  ({gap[i]/60:.1f} h)")
# timezone sanity: average volume by UTC hour (should peak at US cash open 13:30/14:30 UTC)
hv = df.groupby(df.t.dt.hour).v.mean(); print("\ntop-3 volume hours UTC:", list(hv.sort_values(ascending=False).index[:3]))
mins = df.t.dt.strftime('%H:%M'); topm = df.groupby(mins).v.mean().sort_values(ascending=False).head(4); print("top-4 volume minutes UTC:", list(topm.index))
# jumps between consecutive bars
r = np.log(df.c).diff().abs(); ch = df.sym != df.sym.shift()
print(f"\nbar-to-bar |return| p99.99={r.quantile(.9999)*100:.3f}%  max={r.max()*100:.2f}%")
oc = np.log(df.o / df.c.shift()).abs()
top = oc.sort_values(ascending=False).head(10).index
print("largest open-vs-prev-close jumps:")
for i in top: print(f"   {df.t.iloc[i]}  prev_c={df.c.iloc[i-1]} o={df.o.iloc[i]}  {oc[i]*100:.2f}%  contract_change={bool(ch.iloc[i])}  gap_min={(df.ts.iloc[i]-df.ts.iloc[i-1])//60}")
# rolls
rolls = df.index[ch][1:]
print(f"\ncontract switches: {len(rolls)}")
if 1 < len(rolls) < 200:
    for i in rolls: print(f"   {df.t.iloc[i]:%Y-%m-%d %H:%M}  {df.sym.iloc[i-1]}->{df.sym.iloc[i]}  prev_c={df.c.iloc[i-1]}  new_o={df.o.iloc[i]}  diff={df.o.iloc[i]-df.c.iloc[i-1]:+.2f}")
