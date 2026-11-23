"""The backtest engine: a bar-by-bar simulator with realistic fills.

How a bar is processed (bar i):
  1. If a futures contract rolled at bar i and a position is open, the cost of rolling
     (commission + slippage on both sides) is charged. Prices are back-adjusted, so P&L stays correct.
  2. Orders the strategy placed at the close of bar i-1 or earlier are filled against bar i:
       market -> at bar i's open (plus slippage)
       stop   -> when price trades to the stop; at the open if the bar gaps past it (plus slippage)
       limit  -> when price trades through the limit (by `limit_through_ticks`); at the open if it gaps past it
  3. Protective stop-loss / take-profit of the open position are checked against bar i.
     If the bar touches BOTH, the stop-loss is assumed to have come first (worst case).
     If the stop-loss falls inside the same bar the entry filled on, it counts as hit (worst case).
  4. Equity is marked at the close.
  5. strategy.on_bar(i) runs. It sees bar i fully closed, and anything it orders can fill from bar i+1 onward.
     So a strategy can never trade at a price it hasn't seen yet.

Bid/ask: longs buy at the ask and sell at the bid; shorts the reverse. XAUUSD uses the real Dukascopy
bid/ask. Other instruments use mid +/- spread/2 (futures: spread 0, the traded price).
"""
from array import array
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd

from .instruments import Instrument


@dataclass
class Order:
    side: int                 # +1 buy, -1 sell
    kind: str                 # 'market' | 'stop' | 'limit'
    price: float | None
    qty: float | None         # fixed size, or None to size by risk
    risk_usd: float | None
    risk_pct: float | None
    sl: float | None          # absolute stop-loss price
    tp: float | None          # absolute take-profit price
    sl_dist: float | None     # stop distance in points from the fill price
    tp_dist: float | None
    tp_r: float | None        # take-profit as a multiple of the stop distance (2 = 2R)
    tag: str
    placed_i: int
    expires_i: int | None


@dataclass
class Position:
    side: int
    qty: float
    entry_px: float
    entry_i: int
    sl: float | None
    tp: float | None
    sl_initial: float | None
    tag: str
    costs: float = 0.0
    slippage_usd: float = 0.0
    rolls: int = 0
    spread_usd: float = 0.0   # bid/ask spread paid (already inside the fill prices; shown for information)
    mae: float = 0.0          # worst adverse excursion, points
    mfe: float = 0.0          # best favourable excursion, points


@dataclass
class Settings:
    capital: float = 50_000.0
    limit_through_ticks: float | None = None   # None = 1 tick for futures, 0 for bid/ask instruments
    oco: bool = True                            # when an entry fills, cancel the other pending entries
    charge_rolls: bool = True
    # stress-test knobs (defaults = normal behaviour)
    spread_mult: float = 1.0                    # widen the bid/ask spread (real or fixed) by this factor
    delay_bars: int = 0                         # entries and close() requests fill this many bars later


def _compact(series: pd.Series):
    """Column -> compact sequence with fast scalar indexing (array.array uses 8 bytes per value,
    a Python list ~32). Datetime columns become integer day numbers (days since 1970-01-01)."""
    v = series.to_numpy()
    k = v.dtype.kind
    if k == "f":
        return array("d", v.astype(np.float64).tobytes())
    if k in "iu":
        return array("q", v.astype(np.int64).tobytes())
    if k == "b":
        return array("b", v.astype(np.int8).tobytes())
    if k == "M":
        return array("q", v.astype("datetime64[D]").astype(np.int64).tobytes())
    return series.tolist()


class Columns(dict):
    """Data columns for the strategy: d["c"][i]. Converted on first use, so unused columns cost nothing."""
    def __init__(self, df: pd.DataFrame):
        super().__init__()
        self._df = df

    def __missing__(self, key):
        if key not in self._df.columns:
            raise KeyError(f"no column {key!r}; available: {list(self._df.columns)}")
        col = _compact(self._df[key])
        self[key] = col
        return col

    def __contains__(self, key):
        return dict.__contains__(self, key) or key in self._df.columns


class Broker:
    """What the strategy talks to: place / cancel orders, read the position."""

    def __init__(self, inst: Instrument, d: dict, settings: Settings):
        self.inst, self.d, self.s = inst, d, settings
        self.pos: Position | None = None
        self.orders: list[Order] = []
        self.trades: list[dict] = []
        self.realized = 0.0
        self.skipped = {}
        self.i = 0
        self._close_req: tuple[str, int] | None = None   # (reason, bar it was requested on)
        self._new_sl = self._new_tp = None

    # ---- strategy API ----
    @property
    def position(self) -> float:
        return 0.0 if self.pos is None else self.pos.side * self.pos.qty

    @property
    def flat(self) -> bool:
        return self.pos is None

    @property
    def equity(self) -> float:
        return self.s.capital + self.realized

    def buy(self, **kw):  return self._order(+1, **kw)
    def sell(self, **kw): return self._order(-1, **kw)

    def _order(self, side, kind="market", price=None, qty=None, risk_usd=None, risk_pct=None,
               sl=None, tp=None, sl_dist=None, tp_dist=None, tp_r=None, tag="", valid_bars=None):
        if kind not in ("market", "stop", "limit"):
            raise ValueError(kind)
        if kind != "market" and price is None:
            raise ValueError("stop/limit orders need a price")
        if qty is None and risk_usd is None and risk_pct is None:
            qty = self.inst.qty_step
        o = Order(side, kind, price, qty, risk_usd, risk_pct, sl, tp, sl_dist, tp_dist, tp_r, tag, self.i,
                  None if valid_bars is None else self.i + valid_bars)
        self.orders.append(o)
        return o

    def cancel_all(self):
        self.orders.clear()

    def close(self, reason="close"):
        """Exit the open position at the next bar's open."""
        if self.pos is not None:
            self._close_req = (reason, self.i)

    def set_sl(self, price):  self._new_sl = price
    def set_tp(self, price):  self._new_tp = price

    def bars_in_trade(self) -> int:
        return 0 if self.pos is None else self.i - self.pos.entry_i


class Engine:
    def __init__(self, df: pd.DataFrame, inst: Instrument, strategy, settings: Settings | None = None):
        self.s = settings or Settings()
        self.inst = inst
        self.strategy = strategy
        df = strategy.prepare(df.copy()) if hasattr(strategy, "prepare") else df
        self.df = df.reset_index(drop=True)
        d = Columns(self.df)
        # Unified bid/ask arrays. Real ones for XAUUSD; otherwise price -/+ half the fixed spread.
        # spread_mult widens the spread around the mid (stress test).
        m = self.s.spread_mult
        real = inst.uses_bid_ask and "bo" in self.df
        for k in "ohlc":
            if real:
                b_, a_ = self.df["b" + k].to_numpy(), self.df["a" + k].to_numpy()
                mid, hs = (a_ + b_) / 2.0, (a_ - b_) / 2.0 * m
            else:
                mid, hs = self.df[k].to_numpy(), inst.spread / 2.0 * m
            if real and m == 1.0:
                d["b" + k], d["a" + k] = d["b" + k], d["a" + k]   # untouched real quotes (exact)
            elif not real and hs == 0:
                d["b" + k] = d["a" + k] = d[k]            # futures: bid = ask = traded price, share memory
            else:
                d["b" + k] = array("d", (mid - hs).astype(np.float64).tobytes())
                d["a" + k] = array("d", (mid + hs).astype(np.float64).tobytes())
        self.d = d
        strategy.d = d
        strategy.inst = inst
        self.b = Broker(inst, d, self.s)
        strategy.broker = self.b
        tt = self.s.limit_through_ticks
        self.through = (0.0 if inst.uses_bid_ask or inst.spread > 0 else 1.0) * inst.tick if tt is None else tt * inst.tick

    # ---------------------------------------------------------------- helpers
    def _slip(self) -> float:
        return self.inst.slippage_ticks * self.inst.tick

    def _skip(self, why: str):
        self.b.skipped[why] = self.b.skipped.get(why, 0) + 1

    def _half_spread(self, i: int) -> float:
        return (self.d["ao"][i] - self.d["bo"][i]) / 2.0

    def _size(self, o: Order, fill: float, sl: float | None) -> float:
        if o.qty is not None:
            return o.qty
        if sl is None:
            raise ValueError("risk-based sizing needs a stop-loss (sl or sl_dist)")
        risk_per_unit = abs(fill - sl) * self.inst.point_value
        if risk_per_unit <= 0:
            return 0.0
        budget = o.risk_usd if o.risk_usd is not None else self.b.equity * o.risk_pct / 100.0
        step = self.inst.qty_step
        return math.floor(budget / risk_per_unit / step + 1e-9) * step

    def _open(self, o: Order, i: int, fill: float, slip_pts: float):
        sl = o.sl if o.sl is not None else (fill - o.side * o.sl_dist if o.sl_dist is not None else None)
        if o.tp is not None:
            tp = o.tp
        elif o.tp_dist is not None:
            tp = fill + o.side * o.tp_dist
        elif o.tp_r is not None and sl is not None:
            tp = fill + o.side * o.tp_r * abs(fill - sl)
        else:
            tp = None
        if sl is not None and (sl - fill) * o.side >= 0:   # stop on the wrong side of the fill: skip
            self._skip("stop_on_wrong_side_of_fill")
            return False
        qty = self._size(o, fill, sl)
        if qty < self.inst.qty_step - 1e-12:
            self._skip("risk_too_small_for_1_contract")
            return False
        comm = self.inst.commission * qty
        self.b.pos = Position(o.side, qty, fill, i, sl, tp, sl, o.tag, costs=comm,
                              slippage_usd=slip_pts * self.inst.point_value * qty,
                              spread_usd=self._half_spread(i) * self.inst.point_value * qty)
        self.b.realized -= comm
        return True

    def _exit(self, i: int, px: float, reason: str, slip_pts: float = 0.0):
        p = self.b.pos
        gross = (px - p.entry_px) * p.side * p.qty * self.inst.point_value
        comm = self.inst.commission * p.qty
        p.costs += comm
        p.slippage_usd += slip_pts * self.inst.point_value * p.qty
        p.spread_usd += self._half_spread(i) * self.inst.point_value * p.qty
        self.b.realized += gross - comm
        risk = abs(p.entry_px - p.sl_initial) * p.qty * self.inst.point_value if p.sl_initial is not None else np.nan
        d = self.d
        self.b.trades.append({
            "entry_time": d["ts"][p.entry_i], "exit_time": d["ts"][i], "side": "long" if p.side > 0 else "short",
            "qty": p.qty, "entry_px": p.entry_px, "exit_px": px, "sl": p.sl_initial, "tp": p.tp,
            "pnl_gross": gross, "costs": p.costs, "slippage_usd": p.slippage_usd, "spread_usd": p.spread_usd,
            "pnl": gross - p.costs,
            "r": (gross - p.costs) / risk if risk and risk > 0 else np.nan,
            "bars": i - p.entry_i, "exit_reason": reason, "tag": p.tag, "rolls": p.rolls,
            "contract": d["contract"][p.entry_i], "mae_pts": p.mae, "mfe_pts": p.mfe,
            "entry_tday": d["tday"][p.entry_i], "exit_tday": d["tday"][i],
        })
        self.b.pos = None

    # ------------------------------------------------------- exits of open position
    def _check_exits(self, i: int, entered_now: bool) -> bool:
        p, d = self.b.pos, self.d
        slip = self._slip()
        if p.side > 0:   # long exits sell at the bid
            o, h, l = d["bo"][i], d["bh"][i], d["bl"][i]
            sl_hit = p.sl is not None and l <= p.sl
            tp_hit = p.tp is not None and h >= p.tp + self.through
            if not entered_now and p.sl is not None and o <= p.sl:
                self._exit(i, o - slip, "sl_gap", slip); return True
            if not entered_now and p.tp is not None and o >= p.tp:
                self._exit(i, o, "tp_gap"); return True
            if sl_hit:
                self._exit(i, p.sl - slip, "sl", slip); return True
            if tp_hit:
                self._exit(i, p.tp, "tp"); return True
        else:            # short exits buy at the ask
            o, h, l = d["ao"][i], d["ah"][i], d["al"][i]
            sl_hit = p.sl is not None and h >= p.sl
            tp_hit = p.tp is not None and l <= p.tp - self.through
            if not entered_now and p.sl is not None and o >= p.sl:
                self._exit(i, o + slip, "sl_gap", slip); return True
            if not entered_now and p.tp is not None and o <= p.tp:
                self._exit(i, o, "tp_gap"); return True
            if sl_hit:
                self._exit(i, p.sl + slip, "sl", slip); return True
            if tp_hit:
                self._exit(i, p.tp, "tp"); return True
        return False

    # ------------------------------------------------------------- pending entries
    def _fill_entries(self, i: int) -> bool:
        d, b, slip = self.d, self.b, self._slip()
        keep, filled = [], False
        for o in b.orders:
            if filled or o.placed_i + self.s.delay_bars >= i:
                keep.append(o); continue
            if o.expires_i is not None and i > o.expires_i:
                continue
            if b.pos is not None:            # entries only fill when flat
                keep.append(o); continue
            if o.side > 0:
                op, hi, lo = d["ao"][i], d["ah"][i], d["al"][i]
            else:
                op, hi, lo = d["bo"][i], d["bh"][i], d["bl"][i]
            px = None; sp = 0.0
            if o.kind == "market":
                px, sp = op + o.side * slip, slip
            elif o.kind == "stop":
                if o.side > 0 and hi >= o.price:
                    px, sp = max(op, o.price) + slip, slip
                elif o.side < 0 and lo <= o.price:
                    px, sp = min(op, o.price) - slip, slip
            else:  # limit
                if o.side > 0 and (op <= o.price or lo <= o.price - self.through):
                    px = min(op, o.price)
                elif o.side < 0 and (op >= o.price or hi >= o.price + self.through):
                    px = max(op, o.price)
            if px is None:
                keep.append(o); continue
            if self._open(o, i, px, sp):
                filled = True
        if filled and self.s.oco:
            keep = [o for o in keep if o.placed_i + self.s.delay_bars >= i]   # cancel the other live entries
        b.orders = keep
        return filled

    # ------------------------------------------------------------------- run
    def run(self) -> dict:
        d, b, st = self.d, self.b, self.strategy
        n = len(d["ts"])
        pv = self.inst.point_value
        roll = d["roll"] if "roll" in d else [0] * n
        delay = self.s.delay_bars
        equity = np.empty(n)
        slip = self._slip()
        on_bar = st.on_bar
        for i in range(n):
            b.i = i
            p = b.pos
            # 1. rolls
            if p is not None and roll[i] and self.s.charge_rolls:
                c = 2 * self.inst.commission * p.qty + 2 * slip * pv * p.qty
                p.costs += c; p.slippage_usd += 2 * slip * pv * p.qty; p.rolls += 1
                b.realized -= c
            # 2a. requested close at this bar's open
            if p is not None and b._close_req and i > b._close_req[1] + delay:
                px = (d["bo"][i] - slip) if p.side > 0 else (d["ao"][i] + slip)
                self._exit(i, px, b._close_req[0], slip)
                b._close_req = None
            elif p is None:
                b._close_req = None
            # 2b. stop/target modifications requested last bar
            if b.pos is not None:
                if b._new_sl is not None: b.pos.sl = b._new_sl
                if b._new_tp is not None: b.pos.tp = b._new_tp
            b._new_sl = b._new_tp = None
            # 3. exits of a position held from before this bar, then new entries, then same-bar exit check
            if b.pos is not None:
                self._check_exits(i, entered_now=False)
            if b.orders and b.pos is None:
                if self._fill_entries(i):
                    self._check_exits(i, entered_now=True)
            elif b.orders:
                b.orders = [o for o in b.orders if o.expires_i is None or i <= o.expires_i]
            # 4. mark to market
            p = b.pos
            if p is not None:
                if p.side > 0:
                    p.mae = max(p.mae, p.entry_px - d["bl"][i]); p.mfe = max(p.mfe, d["bh"][i] - p.entry_px)
                    mark = (d["bc"][i] - p.entry_px) * p.qty * pv
                else:
                    p.mae = max(p.mae, d["ah"][i] - p.entry_px); p.mfe = max(p.mfe, p.entry_px - d["al"][i])
                    mark = (p.entry_px - d["ac"][i]) * p.qty * pv
                equity[i] = self.s.capital + b.realized + mark
            else:
                equity[i] = self.s.capital + b.realized
            # 5. strategy decides on the closed bar
            on_bar(i)
        if b.pos is not None:
            p = b.pos
            px = d["bc"][n - 1] if p.side > 0 else d["ac"][n - 1]
            self._exit(n - 1, px, "end_of_data")
            equity[n - 1] = self.s.capital + b.realized
        trades = pd.DataFrame(b.trades)
        if len(trades):
            for c in ("entry_time", "exit_time"):
                trades[c] = pd.to_datetime(trades[c], unit="s", utc=True)
            for c in ("entry_tday", "exit_tday"):
                trades[c] = trades[c].to_numpy().astype("datetime64[D]")
        eq = pd.DataFrame({"ts": np.asarray(d["ts"]), "tday": np.asarray(d["tday"]).astype("datetime64[D]"), "equity": equity})
        return {"trades": trades, "equity": eq, "skipped": b.skipped, "settings": self.s, "instrument": self.inst}


class Strategy:
    """Base class. Override prepare() (vectorized indicators, past data only) and on_bar(i)."""
    params: dict = {}

    def __init__(self, **params):
        self.p = {**self.params, **params}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def on_bar(self, i: int):
        raise NotImplementedError


def check_lookahead(strategy, df: pd.DataFrame, cuts=(0.35, 0.6, 0.85)) -> list[str]:
    """Run prepare() on the full data and on truncated copies. Any indicator value that changes
    when future bars are removed is using the future. Returns the offending column names."""
    full = strategy.prepare(df.copy())
    new_cols = [c for c in full.columns if c not in df.columns]
    bad = set()
    for f in cuts:
        k = int(len(df) * f)
        part = strategy.prepare(df.iloc[:k].copy())
        for c in new_cols:
            a, b = full[c].iloc[:k].to_numpy(), part[c].to_numpy()
            if a.dtype.kind in "fc":
                same = np.isclose(a, b, equal_nan=True, rtol=1e-9, atol=1e-9)
            else:
                same = (a == b) | (pd.isna(a) & pd.isna(b))
            if not np.all(same):
                bad.add(c)
    return sorted(bad)
