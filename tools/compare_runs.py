"""Compare two trades.csv files exactly (regression check)."""
import sys, pandas as pd, numpy as np
a, b = pd.read_csv(sys.argv[1]), pd.read_csv(sys.argv[2])
cols = ["entry_time", "exit_time", "side", "qty", "entry_px", "exit_px", "pnl", "costs", "exit_reason"]
same = len(a) == len(b) and all((a[c].astype(str) == b[c].astype(str)).all() if not pd.api.types.is_numeric_dtype(a[c]) else np.allclose(a[c], b[c]) for c in cols)
print(f"{sys.argv[1].split('/')[-2]}: {len(a)} vs {len(b)} trades -> {'IDENTICAL' if same else 'DIFFERENT'}")
