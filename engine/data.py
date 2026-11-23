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
CACHE_VERSION = 4      # 4: GC fallback roll spreads from earlier rolls only (causal)

SOURCES = {
    "GC": DATA / "GC_Gold_futures/bars_1m_continuous_2016-01_to_2025-12.parquet",
    "NQ": DATA / "NQ_Nasdaq100_futures/bars_1m_front_contract_2021-01_to_2026-08-14.parquet",
    "NQ_ALL": DATA / "NQ_Nasdaq100_futures/bars_1m_all_contracts_2021-01_to_2026-08-14.parquet",
    "NQ_FLOW": DATA / "NQ_Nasdaq100_futures/order_flow_1m_buy_sell_volume_2021-01_to_2026-08-14.parquet",
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


def estimate_missing_spreads(spreads: np.ndarray, prices: np.ndarray, n: int = 4) -> tuple[np.ndarray, dict]:
    """Fill unmeasured roll spreads (NaN) from the median spread/price ratio of up to `n` EARLIER measured rolls.
    A roll with no earlier measurement keeps NaN for the caller to resolve and is flagged. Returns (spreads, {k: method})."""
    spreads = np.asarray(spreads, dtype=float).copy()
    measured = ~np.isnan(spreads)
    methods = {}
    for k in np.flatnonzero(~measured):
        past = np.flatnonzero(measured[:k])[-n:]
        if len(past):
            ratio = np.median(spreads[past] / prices[past])
            spreads[k], methods[k] = ratio * prices[k], f"estimated_from_{len(past)}_earlier_rolls(session_break,uncertain)"
        else:
            methods[k] = "no_earlier_roll(uncertain)"
    return spreads, methods


def _load_gc() -> tuple[pd.DataFrame, pd.DataFrame]:
    """GC is only available as one stitched series, so the other contract's price at the roll is unknown.
    The jump at a roll = roll spread + the market's own move across the gap. The market move is
    estimated and kept:
      - from spot gold (XAUUSD mid) over the same minutes, when that data exists (from 2021-06-29);
      - otherwise, for a gap of up to 4 hours, it is assumed 0 (error = gold's move during the pause,
        usually far smaller than any carry estimate's error);
      - otherwise (weekend gap before 2021) the roll spread is estimated as the median spread/price
        ratio of the up to 4 most recent EARLIER measured rolls x the price (causal: a later roll never changes an
        earlier estimate). The first roll has no earlier measurement: its price jump is kept as the spread (the
        market's move over the gap assumed 0) and it is flagged 'uncertain'. These 8 estimates are uncertain
        either way: the source has no overlapping quotes of both contracts.
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
    spreads, est = estimate_missing_spreads(spreads, df.c.values[ri - 1])
    for k, m in est.items():
        methods[k] = m
        if np.isnan(spreads[k]):                     # first roll, nothing earlier: keep its jump (move assumed 0)
            spreads[k] = jump[k]
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
    # aggressor volume per minute (buyer- / seller-initiated trades) of the same front contract
    flow = pd.read_parquet(SOURCES["NQ_FLOW"], columns=["ts", "symbol", "buy", "sell"])
    df = df.merge(flow.rename(columns={"symbol": "contract", "buy": "buy_vol", "sell": "sell_vol"}),
                  on=["ts", "contract"], how="left")
    df[["buy_vol", "sell_vol"]] = df[["buy_vol", "sell_vol"]].fillna(0).astype(np.int64)
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


SOURCES_FOR = {"GC": ["GC", "XAUUSD"], "NQ": ["NQ", "NQ_ALL", "NQ_FLOW"], "XAUUSD": ["XAUUSD"],
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


def session_filter(df: pd.DataFrame, session: str = "full") -> pd.DataFrame:
    """'full': every bar. 'rth': New York cash session only: exchange trading days (holidays dropped), 09:30 to
    the close (16:00, or 13:00 on half days), from the exchange calendar. Roll flags are kept on the first remaining bar of each
    new contract, so a roll outside the session is charged at the next session bar."""
    if session == "full":
        return df
    if session != "rth":
        raise ValueError(f"unknown session {session!r} (use 'full' or 'rth')")
    from .calendar import session_close_minute
    days = df.tday.to_numpy().astype("datetime64[D]")
    uniq, inv = np.unique(days, return_inverse=True)
    close = session_close_minute(uniq)[inv]
    from .calendar import holidays
    hol = holidays()
    open_day = np.array([d.astype(object) not in hol for d in uniq])[inv]     # exchange closed -> no cash session
    m = df.ny_min.to_numpy()
    keep = (m >= 9 * 60 + 30) & (m < close) & open_day
    seg = np.cumsum(df["roll"].to_numpy(dtype=bool))          # contract segment of every original bar
    kept = seg[keep]
    out = df[keep].copy()
    # a kept bar starts a new contract if any switch happened since the previous kept bar (or since the data began)
    out["roll"] = kept != np.r_[seg[0], kept[:-1]] if len(out) else np.array([], dtype=bool)
    return out.reset_index(drop=True)


def resample(df: pd.DataFrame, minutes: int, session: str = "full") -> pd.DataFrame:
    """Aggregate 1-minute bars into N-minute bars (N=5, 15, 60, 240, 1440 ...).
    Buckets are counted from the 18:00 ET session open and never cross a trading day,
    so 60-minute bars line up with clock hours. ts = start of the bucket's first bar.
    `contract` = the contract at the bar's open; a switch inside a bar is flagged in `roll_inside`."""
    df = session_filter(df, session)
    if minutes == 1:
        df.attrs["bar_minutes"] = 1          # declared bar size (strategies read it instead of guessing from steps)
        return df
    since_open = (df.ny_min.astype(np.int32) - 18 * 60) % 1440
    key = df.tday.astype("int64").values * 10000 + (since_open // minutes).values
    agg = {"ts": "first", "o": "first", "h": "max", "l": "min", "c": "last", "v": "sum",
           "contract": "first", "ny_min": "first", "ny_dow": "first", "tday": "first"}
    for col, f in [("raw_o", "first"), ("raw_h", "max"), ("raw_l", "min"), ("raw_c", "last"), ("adj", "last"), ("bo", "first"), ("bh", "max"), ("bl", "min"), ("bc", "last"),
                   ("ao", "first"), ("ah", "max"), ("al", "min"), ("ac", "last"),
                   ("buy_vol", "sum"), ("sell_vol", "sum"), ("ts_last", "last"),
                   ("xo", "first"), ("xh", "max"), ("xl", "min"), ("xc", "last"),
                   ("xbo", "first"), ("xbh", "max"), ("xbl", "min"), ("xbc", "last"),
                   ("xao", "first"), ("xah", "max"), ("xal", "min"), ("xac", "last")]:
        if col in df:
            agg[col] = f
    g = df.groupby(key, sort=True)
    out = g.agg(agg).reset_index(drop=True)
    # Futures rolls. Every bucket stays ONE bar (one observation per session for daily indicators).
    #   roll        : the contract switches at the bar's first minute -> charged before anything happens in the bar
    #   roll_inside : the switch happens inside the bar -> the engine charges it if a position is held after the
    #                 bar's open (exact when positions only change at bar opens; otherwise pessimistic, see core)
    if "adj" in df:                     # adjustment in force at the bar's OPEN (the opening contract's)
        out["adj_open"] = g["adj"].first().to_numpy()
    first = g["roll"].first().to_numpy(dtype=bool)
    n_rolls = pd.Series(df["roll"].to_numpy(dtype=bool)).groupby(key).sum().to_numpy()
    out["roll"] = first
    out["roll_inside"] = (n_rolls - first.astype(int)) > 0
    out.attrs["bar_minutes"] = int(minutes)
    return out
