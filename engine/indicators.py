"""Technical indicators, vectorised, using ONLY past and current bars (no look-ahead).

Futures prices are back-adjusted by difference: differences (RSI, momentum in points, MA slopes,
stochastic, Williams %R) are exact, but percentages and price levels are not. For any percentage,
divide an adjusted-price DIFFERENCE by the real price: see `pct_of_price`.
"""
import numpy as np
import pandas as pd


def real_price(df: pd.DataFrame) -> pd.Series:
    """Unadjusted close (futures) or the close (other instruments)."""
    return df["raw_c"] if "raw_c" in df else df["c"]


def pct_of_price(diff: pd.Series, df: pd.DataFrame, lag: int = 0) -> pd.Series:
    """A price difference expressed in % of the real price (lag bars ago)."""
    return diff / real_price(df).shift(lag) * 100.0


def sma(x: pd.Series, n: int) -> pd.Series:
    return x.rolling(n, min_periods=n).mean()


def ema(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi(close: pd.Series, n: int) -> pd.Series:
    """Wilder's RSI."""
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = up / dn
    out = 100.0 - 100.0 / (1.0 + rs)
    out[(dn == 0) & (up > 0)] = 100.0
    out[(dn == 0) & (up == 0)] = 50.0
    return out


def true_range(h, l, c):
    pc = c.shift()
    return pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)


def atr(h, l, c, n: int) -> pd.Series:
    """Wilder's average true range."""
    return true_range(h, l, c).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def avg_range(h, l, n: int) -> pd.Series:
    """Simple average of (high - low) over n bars."""
    return (h - l).rolling(n, min_periods=n).mean()


def stochastic_k(h, l, c, n: int, smooth: int = 1) -> pd.Series:
    """%K = (close - lowest low) / (highest high - lowest low) x 100 over n bars, optionally SMA-smoothed."""
    hh, ll = h.rolling(n, min_periods=n).max(), l.rolling(n, min_periods=n).min()
    k = (c - ll) / (hh - ll) * 100.0
    k = k.where(hh > ll, 50.0).where(hh.notna())
    return k if smooth <= 1 else k.rolling(smooth, min_periods=smooth).mean()


def williams_r(h, l, c, n: int) -> pd.Series:
    """Williams %R in [-100, 0]."""
    hh, ll = h.rolling(n, min_periods=n).max(), l.rolling(n, min_periods=n).min()
    r = (hh - c) / (hh - ll) * -100.0
    return r.where(hh > ll, -50.0).where(hh.notna())


def mfi(h, l, c, v, n: int, weight_tp=None) -> pd.Series:
    """Money Flow Index: volume-weighted RSI of the typical price.
    Direction (up/down) comes from the typical price of h/l/c. Money flow = `weight_tp` x volume when given,
    else typical price x volume. On back-adjusted futures pass the REAL typical price as `weight_tp` (see
    money_flow_index): adjusted prices shift whenever a later roll is appended, which would change the weights
    and therefore past values."""
    tp = (h + l + c) / 3.0
    flow = (tp if weight_tp is None else weight_tp) * v
    up = flow.where(tp > tp.shift(), 0.0)
    dn = flow.where(tp < tp.shift(), 0.0)
    pos, neg = up.rolling(n, min_periods=n).sum(), dn.rolling(n, min_periods=n).sum()
    out = 100.0 - 100.0 / (1.0 + pos / neg)
    out[(neg == 0) & (pos > 0)] = 100.0
    out[(neg == 0) & (pos == 0)] = 50.0
    out[tp.shift(n).isna()] = np.nan                 # needs n price changes
    return out


def rolling_vwap(h, l, c, v, n: int) -> pd.Series:
    """Volume-weighted average of the typical price over the last n bars."""
    tp = (h + l + c) / 3.0
    num, den = (tp * v).rolling(n, min_periods=n).sum(), v.rolling(n, min_periods=n).sum()
    return (num / den).where(den > 0)


def kama(close: pd.Series, n: int = 10, fast: int = 2, slow: int = 30) -> pd.Series:
    """Kaufman's adaptive moving average."""
    x = close.to_numpy(dtype=float)
    out = np.full(len(x), np.nan)
    fsc, ssc = 2.0 / (fast + 1), 2.0 / (slow + 1)
    change = np.abs(x - np.r_[np.full(n, np.nan), x[:-n]]) if len(x) > n else np.full(len(x), np.nan)
    vol = pd.Series(np.abs(np.diff(x, prepend=np.nan))).rolling(n, min_periods=n).sum().to_numpy()
    prev = np.nan
    for i in range(len(x)):
        if np.isnan(change[i]) or np.isnan(vol[i]):
            continue
        er = change[i] / vol[i] if vol[i] > 0 else 0.0
        sc = (er * (fsc - ssc) + ssc) ** 2
        prev = x[i] if np.isnan(prev) else prev + sc * (x[i] - prev)
        out[i] = prev
    return pd.Series(out, index=close.index)


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    return mid, mid + k * sd, mid - k * sd


def zscore(close: pd.Series, n: int) -> pd.Series:
    m, sd = sma(close, n), close.rolling(n, min_periods=n).std(ddof=0)
    return ((close - m) / sd).where(sd > 0)


def money_flow_index(df: pd.DataFrame, n: int) -> pd.Series:
    """MFI of a bar frame that is unchanged by later futures rolls: up/down from the (adjusted) price path, whose
    differences a rebase leaves alone, weights from the contemporaneous real typical price (raw_* columns, or the
    prices themselves for instruments that are never adjusted)."""
    if all(f"raw_{k}" in df for k in "hlc"):
        real_tp = (df.raw_h + df.raw_l + df.raw_c) / 3.0
    else:
        real_tp = None
    return mfi(df.h, df.l, df.c, df.v, n, weight_tp=real_tp)
