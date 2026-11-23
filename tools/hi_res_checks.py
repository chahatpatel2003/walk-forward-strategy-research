import numpy as np, pandas as pd, pyarrow.parquet as pq, pyarrow.compute as pc, glob, os, re
D = '/Volumes/T9/DATA/'
def stat_range(f, col):
    md = pq.ParquetFile(f).metadata; idx = md.schema.to_arrow_schema().get_field_index(col)
    mins = [md.row_group(i).column(idx).statistics.min for i in range(md.num_row_groups)]
    maxs = [md.row_group(i).column(idx).statistics.max for i in range(md.num_row_groups)]
    return min(mins), max(maxs), md.num_rows
for sub, col in [('NQ_Nasdaq100_futures/ticks_trades_2021-01_to_2026-08-14','ts_event'), ('NQ_Nasdaq100_futures/quotes_top_of_book_mbp1_2021-01_to_2025-06','ts_event'),
                 ('NAS100_CFD_Dukascopy/ticks_bid_ask_2012-02_to_2021-09_and_2026-05','timestamp')]:
    print(f"\n== {sub}")
    for f in sorted(glob.glob(D+sub+'/[!._]*.parquet')):
        try: a, b, n = stat_range(f, col); print(f"   {os.path.basename(f):55s} {str(a)[:19]} -> {str(b)[:19]}  rows={n:,}")
        except Exception as e: print("  ", os.path.basename(f), "stats unavailable", e)
# NQ 1s -> 1m consistency for one month (front contract)
s = pd.read_parquet(D+'NQ_Nasdaq100_futures/bars_1s_2021-01_to_2026-08-14/2024-05.parquet'); s = s[s.is_front]
s['m'] = s.ts.dt.floor('min')
agg = s.groupby('m').agg(o=('open_t','first'), h=('high_t','max'), l=('low_t','min'), c=('close_t','last'), v=('volume','sum'))
fr = pd.read_parquet(D+'NQ_Nasdaq100_futures/bars_1m_front_contract_2021-01_to_2026-08-14.parquet'); fr['m'] = pd.to_datetime(fr.ts, unit='s', utc=True)
j = fr.merge(agg, left_on='m', right_index=True, suffixes=('','_s'))
print(f"\n1s->1m rebuild 2024-05: matched {len(j):,} bars; OHLC exact: {((j.o*4==j.o_s)&(j.h*4==j.h_s)&(j.l*4==j.l_s)&(j.c*4==j.c_s)).mean():.4f}; volume exact: {(j.v==j.v_s).mean():.4f}")
# 2026-06-17 gap: is it in 1s?
s2 = pd.read_parquet(D+'NQ_Nasdaq100_futures/bars_1s_2021-01_to_2026-08-14/2026-06.parquet', columns=['ts'])
d = s2[(s2.ts >= '2026-06-17 03:00Z') & (s2.ts < '2026-06-17 22:00Z')]
print("1s bars present 2026-06-17 03:00-22:00 UTC:", len(d))
# XAU bi5 coverage
for sub in ['ticks_raw_bi5_2021-06-29_to_2026-06-28', 'ticks_raw_bi5_2026-06-29_to_2026-11-17']:
    fs = [f for f in glob.glob(D+'XAUUSD_Gold_spot_Dukascopy/'+sub+'/**/*.bi5', recursive=True) if not os.path.basename(f).startswith('._')]
    sizes = np.array([os.path.getsize(f) for f in fs])
    print(f"\n{sub}: {len(fs):,} hourly files, empty(0-byte)={int((sizes==0).sum())}, example: {os.path.relpath(fs[0], D)}")
tv = pd.read_csv(D+'NQ_Nasdaq100_futures/tradingview_CME_NQ1_1m_2026-11-01_to_2026-11-20.csv')
print("\nTV NQ1 csv:", pd.to_datetime(tv.ts.min(),unit='s'), '->', pd.to_datetime(tv.ts.max(),unit='s'), len(tv), "bars")
tv60 = pd.read_parquet(D+'XAUUSD_Gold_spot_Dukascopy/tradingview_OANDA_XAUUSD_60m_2026-01-16_to_2026-11-18.parquet'); print("TV XAU 60m:", len(tv60), "bars")
vp = pd.read_parquet(D+'NQ_Nasdaq100_futures/volume_profiles_by_session_2021-01_to_2026-08-14/2024-05.parquet'); print("\nvolume profile sample:\n", vp.head(3).to_string())
