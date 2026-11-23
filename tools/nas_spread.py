import pandas as pd, glob, os
D='/Volumes/T9/DATA/NAS100_CFD_Dukascopy/ticks_bid_ask_2012-02_to_2021-09_and_2026-05/'
out={}
for f in sorted(glob.glob(D+'[!._]*.parquet')):
    y=os.path.basename(f)[:4]
    s=pd.read_parquet(f, columns=['timestamp','spread'])
    ny=s.timestamp.dt.tz_convert('America/New_York'); rth=(ny.dt.hour*60+ny.dt.minute).between(570,959)
    out.setdefault(y,[]).append((s.spread[rth].median(), s.spread[~rth].median()))
for y,v in out.items(): print(y, "RTH median spread %.2f | overnight %.2f" % (sum(a for a,_ in v)/len(v), sum(b for _,b in v)/len(v)))
