import numpy as np, pandas as pd, pyarrow.parquet as pq, glob, os, re
D = '/Volumes/T9/DATA/'
# XAU bid file vs bid_ask (fixed unit)
b = pd.read_parquet(D+'XAUUSD_Gold_spot_Dukascopy/bars_1m_2021-06-29_to_2026-06-28.parquet'); b['ts'] = b.timestamp_utc.astype('int64')//10**6
x = pd.read_parquet(D+'XAUUSD_Gold_spot_Dukascopy/bars_1m_bid_ask_mid_2021-06-29_to_2026-11-17.parquet', columns=['ts','bid_c'])
m = b.merge(x, on='ts', how='outer', indicator=True)
print("XAU bid-only file vs bid_ask file:", m._merge.value_counts().to_dict(), "| close==bid_c in overlap:", round(float((abs(m.close-m.bid_c)<1e-6)[m._merge=='both'].mean()),4))
# front vs all contracts
fr = pd.read_parquet(D+'NQ_Nasdaq100_futures/bars_1m_front_contract_2021-01_to_2026-08-14.parquet')
al = pd.read_parquet(D+'NQ_Nasdaq100_futures/bars_1m_all_contracts_2021-01_to_2026-08-14.parquet')
al['ts_s'] = al.ts.astype('int64')//10**9
af = al[al.is_front]
mm = fr.merge(af, left_on=['ts','symbol'], right_on=['ts_s','symbol'], how='outer', indicator=True)
print("\nNQ front file vs all_contracts(is_front):", mm._merge.value_counts().to_dict(), "| close match:", round(float((mm.c*4 == mm.close_t)[mm._merge=='both'].mean()),5))
print("contracts in all_contracts:", al.symbol.nunique(), sorted(al.symbol.unique()))
# true roll spread: at roll minute, price diff between new and old contract at the same minute
rolls = fr.index[fr.symbol != fr.symbol.shift()][1:]
print("\nroll spread measured at the same minute (new - old contract, pts) vs adjust file:")
ra = pd.read_parquet(D+'NQ_Nasdaq100_futures/contract_roll_adjust_2021-01_to_2026-06.parquet')
ra2 = pd.read_parquet(D+'NQ_Nasdaq100_futures/contract_roll_adjust_2026-01_to_2026-08-14_second_build.parquet')
piv = al.pivot_table(index='ts_s', columns='symbol', values='close_t')
for i in rolls:
    old, new, t = fr.symbol.iloc[i-1], fr.symbol.iloc[i], fr.ts.iloc[i]
    row = piv.loc[t] if t in piv.index else None
    sp = (row[new]-row[old])/4 if row is not None and pd.notna(row.get(old)) and pd.notna(row.get(new)) else np.nan
    print(f"   {pd.to_datetime(t,unit='s'):%Y-%m-%d %H:%M} {old}->{new}  spread={sp:+.2f}")
print("\nadjust file 1 epochs/adj_t (unique):"); print(ra.groupby(['epoch','chain']).agg(first=('session','min'), last=('session','max'), adj_t=('adj_t','first'), sym=('symbol','first')).to_string())
print("\nadjust file 2:"); print(ra2.groupby(['epoch','chain']).agg(first=('session','min'), last=('session','max'), adj_t=('adj_t','first'), sym=('symbol','first')).to_string())
