"""Compare two trades.csv files EXACTLY (regression check). Exit code 0 = identical, 1 = different."""
import sys

import pandas as pd

COLS = ["entry_time", "exit_time", "side", "qty", "entry_px", "exit_px", "pnl", "costs", "exit_reason"]


def main(a_path, b_path) -> int:
    a, b = pd.read_csv(a_path, dtype=str), pd.read_csv(b_path, dtype=str)   # compare the text: no tolerance
    if len(a) != len(b):
        print(f"DIFFERENT: {len(a)} vs {len(b)} trades")
        return 1
    for c in COLS:
        diff = (a[c].fillna("") != b[c].fillna(""))
        if diff.any():
            k = int(diff.idxmax())
            print(f"DIFFERENT: column {c!r}, first at row {k}: {a[c].iloc[k]!r} vs {b[c].iloc[k]!r} ({int(diff.sum())} rows)")
            return 1
    print(f"IDENTICAL: {len(a)} trades")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
