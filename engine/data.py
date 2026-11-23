"""Load market data from T9/DATA (read-only) into one standard 1-minute table.

Standard columns (one row per bar, sorted by time, ts = bar START in Unix seconds UTC):
  ts, o, h, l, c, v      prices back-adjusted for futures rolls (latest prices = real prices)
  raw_o, raw_h, raw_l, raw_c  unadjusted prices (futures only)
  contract               contract traded at that bar (futures) or the symbol
  roll                   True on the first bar of a new contract
  bo,bh,bl,bc, ao,ah,al,ac  bid / ask OHLC (XAUUSD only)
  ny_min                 minute of day in New York time (0..1439), DST-safe: 09:30 ET = 570
  ny_dow                 New York weekday, Monday=0
  tday                   trading day (datetime64[D]): a session that opens 18:00 ET belongs to the next day

Processed tables are cached in BACKTESTING/cache/. Nothing is ever written to DATA/.
"""
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path("/Volumes/T9/DATA")
CACHE = Path(__file__).resolve().parent.parent / "cache"
CACHE_VERSION = 2

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
    """Difference back-adjustment: add each roll spread (new - old contract, measured at the same moment)
    to every bar before that roll. The newest prices stay real; raw_* keep the unadjusted prices.
    Note: older adjusted levels include later roll spreads, so for %-based or absolute-level signals use
    raw_* or price differences; P&L is computed on adjusted prices, which is correct for differences."""
    adj = np.zeros(len(df))
    for i, s in zip(roll_idx, spreads):
        adj[:i] += s
    for col in ("o", "h", "l", "c"):
        df["raw_" + col] = df[col].values
        df[col] = df[col].values + adj
    df["adj"] = adj
    return df


def _xau_mid() -> pd.DataFrame:
    x = pd.read_parquet(SOURCES["XAUUSD"], columns=["ts", "mid_o", "mid_c"])
    return x.set_index("ts").sort_index()


def _load_gc() -> tuple[pd.DataFrame, pd.DataFrame]:
    """GC is only available as one stitched series, so the other contract's price at the roll is unknown.
    The jump at a roll = roll spread + the market's own move across the gap. The market move is
    estimated and kept:
      - from spot gold (XAUUSD mid) over the same minutes, when that data exists (from 2021-06-29);
      - otherwise, for a gap of up to 4 hours, it is assumed 0 (error = gold's move during the pause,
        usually far smaller than any carry estimate's error);
      - otherwise (weekend gap before 2021) the roll spread is estimated as the median spread/price
        ratio of the 4 nearest measured rolls x the price.
    Every roll's method is written to cache/GC_rolls.csv."""
    df = pd.read_parquet(SOURCES["GC"])[["ts", "o", "h", "l", "c", "v", "contract"]]
    df["contract"] = df.contract.astype(str)
    roll = (df.contract != df.contract.shift()).to_numpy(copy=True)
    roll[0] = False
    ri = np.flatnonzero(roll)
    t_old, t_new = df.ts.values[ri - 1], df.ts.values[ri]
    jump = df.o.values[ri] - df.c.values[ri - 1]
    gap_min = (t_new - t_old) // 60
    xau = _xau_mid()
    spreads, methods = np.full(len(ri), np.nan), [""] * len(ri)
    xi, xc, xo = xau.index.to_numpy(), xau.mid_c.to_numpy(), xau.mid_o.to_numpy()
    for k in range(len(ri)):
        ia = np.searchsorted(xi, t_old[k], "right") - 1          # last spot bar at/before GC's last old bar
        ib = np.searchsorted(xi, t_new[k], "left")               # first spot bar at/after GC's first new bar
        ok = 0 <= ia and ib < len(xi) and t_old[k] - xi[ia] <= 300 and xi[ib] - t_new[k] <= 300
        a, b = (xc[ia], xo[ib]) if ok else (np.nan, np.nan)
        if ok:
            spreads[k], methods[k] = jump[k] - (b - a), "jump_minus_spot_gold_move"
        elif gap_min[k] <= 240:
            spreads[k], methods[k] = jump[k], f"jump_over_{int(gap_min[k])}min_gap(move assumed 0)"
    measured = np.flatnonzero(~np.isnan(spreads))
    for k in np.flatnonzero(np.isnan(spreads)):
        near = measured[np.argsort(np.abs(measured - k))[:4]]
        ratio = np.median(spreads[near] / df.c.values[ri[near] - 1])
        spreads[k], methods[k] = ratio * df.c.values[ri[k] - 1], "estimated_from_nearest_rolls(session_break)"
    log = pd.DataFrame({"ts": t_new, "old": df.contract.values[ri - 1], "new": df.contract.values[ri],
                        "price_jump": jump, "spread": spreads, "market_move_kept": jump - spreads,
                        "gap_minutes": gap_min, "method": methods})
    df["roll"] = roll
    return _back_adjust(df, spreads, ri), log


def _load_nq() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The roll spread is measured at the roll minute's OPEN on both contracts (the moment the switch
    happens); if one contract has no bar that minute, at the latest earlier minute both traded."""
    df = pd.read_parquet(SOURCES["NQ"])[["ts", "o", "h", "l", "c", "v", "symbol"]].rename(columns={"symbol": "contract"})
    allc = pd.read_parquet(SOURCES["NQ_ALL"], columns=["symbol", "ts", "open_t", "close_t"])
    allc["ts"] = allc.ts.astype("int64") // 10**9
    roll = (df.contract != df.contract.shift()).to_numpy(copy=True)
    roll[0] = False
    ri = np.flatnonzero(roll)
    spreads, methods = [], []
    for i in ri:
        t, old, new = df.ts.values[i], df.contract.values[i - 1], df.contract.values[i]
        a = allc[(allc.symbol == old) & (allc.ts <= t) & (allc.ts > t - 86400)].set_index("ts")
        b = allc[(allc.symbol == new) & (allc.ts <= t) & (allc.ts > t - 86400)].set_index("ts")
        if t in a.index and t in b.index:
            spreads.append((b.open_t[t] - a.open_t[t]) / 4.0)
            methods.append("open_of_roll_minute_both_contracts")
            continue
        common = a.index.intersection(b.index)
        common = common[common < t]
        if len(common):
            k = common.max()
            spreads.append((b.close_t[k] - a.close_t[k]) / 4.0)
            methods.append("last_minute_both_traded_before_roll")
        else:
            spreads.append(df.o.values[i] - df.c.values[i - 1])
            methods.append("jump_fallback(move assumed 0)")
    spreads = np.array(spreads)
    log = pd.DataFrame({"ts": df.ts.values[ri], "old": df.contract.values[ri - 1], "new": df.contract.values[ri],
                        "price_jump": df.o.values[ri] - df.c.values[ri - 1], "spread": spreads, "method": methods})
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


SOURCES_FOR = {"GC": ["GC", "XAUUSD"], "NQ": ["NQ", "NQ_ALL"], "XAUUSD": ["XAUUSD"],
               "NAS100": ["NAS100"], "NAS100_RTH": ["NAS100_RTH"]}


def _fingerprint(key: str) -> dict:
    return {"version": CACHE_VERSION,
            "sources": {k: [os.path.getsize(SOURCES[k]), int(os.path.getmtime(SOURCES[k]))] for k in SOURCES_FOR[key]}}


def _atomic_write(path: Path, writer):
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    _assert_not_data_path(tmp)
    writer(tmp)
    os.replace(tmp, path)          # readers see the old file or the complete new one, never a partial one


def load(key: str, start: str | None = None, end: str | None = None, rebuild: bool = False) -> pd.DataFrame:
    """Return the standard 1-minute table for GC / NQ / XAUUSD / NAS100 / NAS100_RTH.
    start/end: 'YYYY-MM-DD' trading-day filter (inclusive).
    The cache is rebuilt automatically when the source files change (size or modification time) or the
    cache format version changes."""
    key = key.upper()
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{key}_1m_v{CACHE_VERSION}.parquet"
    meta = CACHE / f"{key}_1m_v{CACHE_VERSION}.json"
    _assert_not_data_path(path)
    fp = _fingerprint(key)
    fresh = path.exists() and meta.exists() and json.loads(meta.read_text()) == fp
    if fresh and not rebuild:
        df = pd.read_parquet(path)
    else:
        df, rolls = LOADERS[key]()
        df = df.sort_values("ts").reset_index(drop=True)
        df = _add_time_columns(df)
        _atomic_write(path, lambda p: df.to_parquet(p, index=False))
        if rolls is not None:
            r = rolls.assign(time=pd.to_datetime(rolls.ts, unit="s", utc=True))
            _atomic_write(CACHE / f"{key}_rolls.csv", lambda p: r.to_csv(p, index=False))
        _atomic_write(meta, lambda p: p.write_text(json.dumps(fp)))
    if start:
        df = df[df.tday >= np.datetime64(start)]
    if end:
        df = df[df.tday <= np.datetime64(end)]
    return df.reset_index(drop=True)


def resample(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate 1-minute bars into N-minute bars (N=5, 15, 60, 240, 1440 ...).
    Buckets are counted from the 18:00 ET session open and never cross a trading day,
    so 60-minute bars line up with clock hours. ts = start of the bucket's first bar.
    Futures: a bar containing a contract switch is split at the switch (see below)."""
    if minutes == 1:
        return df
    since_open = (df.ny_min.astype(np.int32) - 18 * 60) % 1440
    key = df.tday.astype("int64").values * 10000 + (since_open // minutes).values
    # Futures rolls: a bar never contains two contracts. A bucket in which the contract switches is split at
    # the switch minute, so the roll is charged exactly when it happens (also on a final bar). On those days
    # there is one extra, shorter bar.
    seg = np.cumsum(df["roll"].to_numpy(dtype=bool))
    key = key * 1000 + (seg % 1000)
    agg = {"ts": "first", "o": "first", "h": "max", "l": "min", "c": "last", "v": "sum",
           "contract": "first", "ny_min": "first", "ny_dow": "first", "tday": "first"}
    for col, f in [("raw_o", "first"), ("raw_h", "max"), ("raw_l", "min"), ("raw_c", "last"), ("adj", "last"), ("bo", "first"), ("bh", "max"), ("bl", "min"), ("bc", "last"),
                   ("ao", "first"), ("ah", "max"), ("al", "min"), ("ac", "last")]:
        if col in df:
            agg[col] = f
    g = df.groupby(key, sort=True)
    out = g.agg(agg).reset_index(drop=True)
    out["roll"] = g["roll"].first().to_numpy(dtype=bool)      # after splitting, a switch is always a bar's first minute
    return out
