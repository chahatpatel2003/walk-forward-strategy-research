"""What-if: close every position at the New York cash close (16:00 ET; 13:00 on early-close days and exchange
holidays, engine.calendar.session_close_minute) instead of holding it overnight.

For each saved trade:
  * the session-end bar of a trading day = its last 1-minute bar starting before the close minute;
  * the trade's new exit = the first session-end bar at or after its entry bar (a trade entered in the evening
    session is closed at the next day's close); if the trade's own exit came earlier, it is kept unchanged;
  * new exit price = that bar's closing BID for a long / ASK for a short (real quotes for XAUUSD, the fixed spread for
    NAS100, bid = ask for futures), minus / plus the instrument's slippage ticks; reason "session_end";
  * per-contract costs are rebuilt: entry + exit commission, plus a roll charge for every contract switch between
    entry and the new exit (none inside one day in practice). Entry price and its slippage are unchanged.
Prices are the same back-adjusted 1-minute series the engine trades, so they are consistent with entry_px.
No new entries are created: a strategy that would have stayed in the trade simply ends it at the close.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import data, get_instrument  # noqa: E402
from engine.calendar import session_close_minute  # noqa: E402

_ONE: dict = {}


def one_minute(market: str) -> pd.DataFrame:
    if market not in _ONE:
        _ONE[market] = data.load(get_instrument(market).data_key).reset_index(drop=True)
    return _ONE[market]


def session_end_bars(m1: pd.DataFrame) -> pd.DataFrame:
    """Index, ts and closing quotes of each trading day's last bar before the cash close."""
    close = session_close_minute(m1.tday.to_numpy())
    before = (m1.ny_min.to_numpy() < close) & (m1.ny_min.to_numpy() < 18 * 60)
    x = m1[before]
    last = x.groupby(x.tday.to_numpy().astype("datetime64[D]")).tail(1)
    return last


def to_session_end(t: pd.DataFrame, market: str, m1: pd.DataFrame | None = None) -> pd.DataFrame:
    inst = get_instrument(market)
    m1 = one_minute(market) if m1 is None else m1
    se = session_end_bars(m1)
    se_ts = se.ts.to_numpy()
    out = t.copy()
    out["exit_time"] = pd.to_datetime(out.exit_time, utc=True).astype("datetime64[s, UTC]")
    out["exit_tday"] = pd.to_datetime(out.exit_tday).astype("datetime64[s]")
    out["exit_reason"] = out.exit_reason.astype(object)
    ets = (pd.to_datetime(t.entry_time, utc=True) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    xts = (pd.to_datetime(t.exit_time, utc=True) - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    k = np.searchsorted(se_ts, ets.to_numpy(), side="left")          # first session-end bar at/after the entry bar
    slip = inst.slippage_ticks * inst.tick
    pv = inst.point_value
    hs = inst.spread / 2.0
    roll = m1.roll.to_numpy(dtype=bool)
    roll_cum = np.cumsum(roll)
    m1_ts = m1.ts.to_numpy()
    changed = np.zeros(len(t), dtype=bool)
    for r in range(len(t)):
        if k[r] >= len(se):
            continue
        end = se.iloc[k[r]]
        if xts.iloc[r] <= end.ts:                                     # its own exit came first (exit at that bar's open)
            continue
        side = 1 if t.side.iloc[r] == "long" else -1
        if "bc" in m1:
            px = (end.bc - slip) if side > 0 else (end.ac + slip)
        else:
            px = (end.c - hs - slip) if side > 0 else (end.c + hs + slip)
        q = t.qty.iloc[r]
        i0 = np.searchsorted(m1_ts, ets.iloc[r]); i1 = np.searchsorted(m1_ts, end.ts)
        n_roll = int(roll_cum[i1] - roll_cum[i0]) if i1 > i0 else 0
        unit_cost = 2 * inst.commission + n_roll * (2 * inst.commission + 2 * slip * pv)
        out.loc[out.index[r], ["exit_px", "pnl_gross", "costs", "exit_reason", "rolls"]] = \
            [px, (px - t.entry_px.iloc[r]) * side * q * pv, unit_cost * q, "session_end", n_roll]
        out.loc[out.index[r], "exit_time"] = pd.Timestamp(int(end.ts), unit="s", tz="UTC")
        out.loc[out.index[r], "exit_tday"] = pd.Timestamp(end.tday).normalize().tz_localize(None)
        changed[r] = True
    out["pnl"] = out.pnl_gross - out.costs
    out["cut_at_session_end"] = changed
    return out
