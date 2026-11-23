import sys, pandas as pd, pyarrow.parquet as pq
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
D='/Volumes/T9/DATA/'
for f in sys.argv[1:]:
    p = D+f
    if f.endswith('.csv'):
        df = pd.read_csv(p, nrows=5); print(f"\n### {f}\n", df); continue
    t = pq.ParquetFile(p)
    df = t.read_row_group(0).to_pandas().head(4)
    print(f"\n### {f}  rows={t.metadata.num_rows:,}\n", df)
