"""Read-only: print schema + row count of every parquet in DATA (metadata only, no data load)."""
import sys, os, pyarrow.parquet as pq
root = sys.argv[1]
for d, _, fs in sorted(os.walk(root)):
    if '_Samsung' in d: continue
    ps = sorted(f for f in fs if f.endswith('.parquet') and not f.startswith('._'))
    if not ps: continue
    rows = 0; size = 0
    for f in ps:
        m = pq.ParquetFile(os.path.join(d, f)).metadata; rows += m.num_rows; size += os.path.getsize(os.path.join(d, f))
    s = pq.ParquetFile(os.path.join(d, ps[0])).schema_arrow
    print(f"\n== {os.path.relpath(d, root)}  files={len(ps)} rows={rows:,} size={size/1e9:.2f}GB")
    if len(ps) > 1: print("   first file:", ps[0], " last:", ps[-1])
    print("   cols:", ", ".join(f"{n}:{t}" for n, t in zip(s.names, s.types)))
