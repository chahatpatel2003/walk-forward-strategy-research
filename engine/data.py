"""Load market data from T9/DATA (read-only) into one standard 1-minute table.

Standard columns (one row per bar, sorted by time, ts = bar START in Unix seconds UTC):
  ts, o, h, l, c, v      prices back-adjusted for futures rolls (latest prices = real prices)
  contract               contract traded at that bar (futures) or the symbol
  roll                   True on the first bar of a new contract
  raw_c                  unadjusted close (futures only)
  bo,bh,bl,bc, ao,ah,al,ac  bid / ask OHLC (XAUUSD only)
  ny_min                 minute of day in New York time (0..1439), DST-safe: 09:30 ET = 570
  ny_dow                 New York weekday, Monday=0
  tday                   trading day (datetime64[D]): a session that opens 18:00 ET belongs to the next day

Processed tables are cached in BACKTESTING/cache/. Nothing is ever written to DATA/.
"""
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path("/Volumes/T9/DATA")
CACHE = Path(__file__).resolve().parent.parent / "cache"
CACHE_VERSION = 1

SOURCES = {
    "GC": DATA / "GC_Gold_futures/bars_1m_continuous_2016-01_to_2025-12.parquet",
    "NQ": DATA / "NQ_Nasdaq100_futures/bars_1m_front_contract_2021-01_to_2026-08-14.parquet",
    "NQ_ALL": DATA / "NQ_Nasdaq100_futures/bars_1m_all_contracts_2021-01_to_2026-08-14.parquet",
    "XAUUSD": DATA / "XAUUSD_Gold_spot_Dukascopy/bars_1m_bid_ask_mid_2021-06-29_to_2026-11-17.parquet",
    "NAS100": DATA / "NAS100_CFD_Dukascopy/bars_1m_mid_2012-02_to_2021-09.parquet",
    "NAS100_RTH": DATA / "NAS100_CFD_Dukascopy/bars_1m_mid_0930-1600_complete_days_2012-02_to_2021-09.parquet",
}


def _assert_not_data_path(p: Path):
    if DATA in p.resolve().parents or p.resolve() == DATA:
        raise RuntimeError(f"refusing to write inside DATA/: {p}")


def _add_time_columns(df: pd.DataFrame) -> pd.DataFrame:
    ny = pd.to_datetime(df.ts.values, unit="s", utc=True).tz_convert("America/New_York")
    df["ny_min"] = (ny.hour * 60 + ny.minute).astype(np.int16)
    df["ny_dow"] = ny.day_of_week.astype(np.int8)
    # Sessions open at 18:00 ET; shifting by +6h puts the evening open on the next calendar day.
    df["tday"] = (ny.tz_localize(None) + pd.Timedelta(hours=6)).normalize().values.astype("datetime64[D]")
    return df


def _back_adjust(df: pd.DataFrame, spreads: np.ndarray, roll_idx: np.ndarray) -> pd.DataFrame:
    """Difference back-adjustment: add each roll spread (new - old) to every bar before that roll."""
    adj = np.zeros(len(df))
    for i, s in zip(roll_idx, spreads):
        adj[:i] += s
    df["raw_c"] = df["c"].values
    for col in ("o", "h", "l", "c"):
        df[col] = df[col].values + adj
    df["adj"] = adj
    return df


def _load_gc() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_parquet(SOURCES["GC"])[["ts", "o", "h", "l", "c", "v", "contract"]]
    df["contract"] = df.contract.astype(str)
    roll = (df.contract != df.contract.shift()).to_numpy(copy=True)
    roll[0] = False
    ri = np.flatnonzero(roll)
    # Only the stitched series exists, so the roll spread is estimated as (first open of new) - (last close of old).
    spreads = df.o.values[ri] - df.c.values[ri - 1]
    gap_min = (df.ts.values[ri] - df.ts.values[ri - 1]) // 60
    log = pd.DataFrame({"ts": df.ts.values[ri], "old": df.contract.values[ri - 1], "new": df.contract.values[ri],
                        "spread": spreads, "method": np.where(gap_min > 120, "gap_across_session_break(approx)", "gap_1min")})
    df["roll"] = roll
    return _back_adjust(df, spreads, ri), log


def _load_nq() -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_parquet(SOURCES["NQ"])[["ts", "o", "h", "l", "c", "v", "symbol"]].rename(columns={"symbol": "contract"})
    allc = pd.read_parquet(SOURCES["NQ_ALL"], columns=["symbol", "ts", "close_t"])
    allc["ts"] = allc.ts.astype("int64") // 10**9
    roll = (df.contract != df.contract.shift()).to_numpy(copy=True)
    roll[0] = False
    ri = np.flatnonzero(roll)
    spreads, methods = [], []
    for i in ri:
        t, old, new = df.ts.values[i], df.contract.values[i - 1], df.contract.values[i]
        a = allc[(allc.symbol == old) & (allc.ts <= t) & (allc.ts > t - 86400)].set_index("ts").close_t
        b = allc[(allc.symbol == new) & (allc.ts <= t) & (allc.ts > t - 86400)].set_index("ts").close_t
        common = a.index.intersection(b.index)
        if len(common):
            k = common.max()   # latest minute where both contracts traded, at or before the roll
            spreads.append((b[k] - a[k]) / 4.0)
            methods.append("same_minute_both_contracts")
        else:
            spreads.append(df.o.values[i] - df.c.values[i - 1])
            methods.append("gap_fallback")
    spreads = np.array(spreads)
    log = pd.DataFrame({"ts": df.ts.values[ri], "old": df.contract.values[ri - 1], "new": df.contract.values[ri],
                        "spread": spreads, "method": methods})
    df["roll"] = roll
    return _back_adjust(df, spreads, ri), log


def _load_xau() -> tuple[pd.DataFrame, None]:
    x = pd.read_parquet(SOURCES["XAUUSD"])
    df = pd.DataFrame({
        "ts": x.ts.values, "o": x.mid_o.values, "h": x.mid_h.values, "l": x.mid_l.values, "c": x.mid_c.values,
        "v": x.volume.values,
        "bo": x.bid_o.values, "bh": x.bid_h.values, "bl": x.bid_l.values, "bc": x.bid_c.values,
        "ao": x.ask_o.values, "ah": x.ask_h.values, "al": x.ask_l.values, "ac": x.ask_c.values,
    })
    df["contract"] = "XAUUSD"
    df["roll"] = False
    return df, None


def _load_nas(key: str) -> tuple[pd.DataFrame, None]:
    df = pd.read_parquet(SOURCES[key])[["ts", "o", "h", "l", "c", "v"]]
    df["contract"] = "NAS100"
    df["roll"] = False
    return df, None


LOADERS = {"GC": _load_gc, "NQ": _load_nq, "XAUUSD": _load_xau,
           "NAS100": lambda: _load_nas("NAS100"), "NAS100_RTH": lambda: _load_nas("NAS100_RTH")}


def load(key: str, start: str | None = None, end: str | None = None, rebuild: bool = False) -> pd.DataFrame:
    """Return the standard 1-minute table for GC / NQ / XAUUSD / NAS100 / NAS100_RTH.
    start/end: 'YYYY-MM-DD' trading-day filter (inclusive)."""
    key = key.upper()
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{key}_1m_v{CACHE_VERSION}.parquet"
    _assert_not_data_path(path)
    if path.exists() and not rebuild:
        df = pd.read_parquet(path)
    else:
        df, rolls = LOADERS[key]()
        df = df.sort_values("ts").reset_index(drop=True)
        df = _add_time_columns(df)
        df.to_parquet(path, index=False)
        if rolls is not None:
            rolls.assign(time=pd.to_datetime(rolls.ts, unit="s", utc=True)).to_csv(CACHE / f"{key}_rolls.csv", index=False)
    if start:
        df = df[df.tday >= np.datetime64(start)]
    if end:
        df = df[df.tday <= np.datetime64(end)]
    return df.reset_index(drop=True)


def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate 1-minute bars into N-minute bars (N=5, 15, 60, 240, 1440 ...).
    Buckets are counted from the 18:00 ET session open and never cross a trading day,
    so 60-minute bars line up with clock hours. ts = start of the bucket's first bar."""
    if minutes == 1:
        return df
    since_open = (df.ny_min.astype(np.int32) - 18 * 60) % 1440
    key = df.tday.astype("int64").values * 10000 + (since_open // minutes).values
    agg = {"ts": "first", "o": "first", "h": "max", "l": "min", "c": "last", "v": "sum",
           "contract": "last", "roll": "any", "ny_min": "first", "ny_dow": "first", "tday": "first"}
    for col, f in [("raw_c", "last"), ("adj", "last"), ("bo", "first"), ("bh", "max"), ("bl", "min"), ("bc", "last"),
                   ("ao", "first"), ("ah", "max"), ("al", "min"), ("ac", "last")]:
        if col in df:
            agg[col] = f
    out = df.groupby(key, sort=True).agg(agg).reset_index(drop=True)
    return out
