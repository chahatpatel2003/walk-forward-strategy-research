"""The backtest engine: a bar-by-bar simulator with conservative fills.

How a bar is processed (bar i), in the order things can really happen:
  1. Roll: if a futures contract rolled at bar i and a position is open, the cost of rolling
     (commission + slippage on both sides) is charged. Prices are back-adjusted, so P&L stays correct.
  2. At the OPEN:
       - a close() request (made at least 1 + delay_bars bars earlier) exits at the open;
       - a held position whose stop/target was gapped through exits at the open;
       - entry orders that are market orders, or stop/limit orders the open gapped through, fill at the open.
  3. INSIDE the bar (only 1-minute OHLC is known, so the path is uncertain; the engine assumes the worst):
       - a held position's stop-loss / take-profit; if the bar touches BOTH, the stop-loss wins;
       - if the held position exits inside the bar, no new entry may fill in that bar (the open came before);
       - if several entry orders could trigger, the one whose price is nearest the open is taken
         (counted in notes["ambiguous_entry_bars"]);
       - after an entry inside or at the open of the bar, its stop-loss is hit if the bar reaches it;
         a target counts only when the price path must have reached it AFTER the entry
         (market/stop entries: the high/low; limit entries: only the close).
  4. Equity is marked at the close (and at the bar's worst price, for intraday drawdown).
  5. strategy.on_bar(i) runs on the closed bar; anything it orders can fill from bar i+1 (+ delay_bars).

Bid/ask: longs buy at the ask and sell at the bid; shorts the reverse. XAUUSD uses the real Dukascopy
bid/ask. Other instruments use price +/- spread/2 (futures: spread 0, the traded price).
Stops never fill better than the quotes available in the bar; targets (limits) need the price to trade
through by `limit_through_ticks` (1 tick for futures).
"""
from array import array
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .instruments import Instrument

# Columns the engine fills against. A strategy's prepare() must not change them.
PROTECTED = ("ts", "o", "h", "l", "c", "bo", "bh", "bl", "bc", "ao", "ah", "al", "ac", "roll", "contract", "tday",
             # execution metadata: roll charges and the conversion of adjusted fills to real prices
             "roll_inside", "adj", "adj_open", "raw_o", "raw_h", "raw_l", "raw_c")


@dataclass
class Order:
    side: int                 # +1 buy, -1 sell
    kind: str                 # 'market' | 'stop' | 'limit'
    price: float | None
    qty: float | None         # fixed size, or None to size by risk / notional
    risk_usd: float | None
    risk_pct: float | None
    notional_usd: float | None
    sl: float | None          # absolute stop-loss price
    tp: float | None          # absolute take-profit price
    sl_dist: float | None     # stop distance in points from the fill price
    tp_dist: float | None
    tp_r: float | None        # take-profit as a multiple of the stop distance (2 = 2R)
    tag: str
    placed_i: int
    expires_i: int | None
    intraday: bool = False
    last_fill_ts: int | None = None   # absolute: the order may fill only in a bar that STARTS at or before this time


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
    roll_slippage_usd: float = 0.0   # the slippage part of roll charges (inside BOTH costs and slippage_usd)
    mae: float = 0.0          # worst adverse excursion, points
    mfe: float = 0.0          # best favourable excursion, points
    intraday: bool = False    # must not be held into another trading day


@dataclass
class Settings:
    capital: float = 50_000.0
    limit_through_ticks: float | None = None   # None = 1 tick for futures, 0 for bid/ask instruments
    oco: bool = True                            # when an entry fills, cancel the other pending entries
    charge_rolls: bool = True
    # stress-test knobs (defaults = normal behaviour)
    spread_mult: float = 1.0                    # widen the bid/ask spread (real or fixed) by this factor
    delay_bars: int = 0                         # entries and close() requests fill this many bars later
    # windows: orders placed before this bar timestamp are ignored (indicator warm-up only)
    trade_start_ts: int | None = None
    max_leverage: float | None = None           # cap position notional at equity x this (None = no cap)
    # Account model. Unconstrained (default, a research model): trading continues whatever the balance; the first
    # bar whose marked equity is <= 0 is reported. Constrained: at that bar's close pending orders are cancelled,
    # the position is closed at the very next open (reason 'capital_exhausted'; not subject to delay_bars) and no
    # new orders are accepted, permanently (also in later walk-forward folds).
    account_constrained: bool = False


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


class FutureReadError(IndexError):
    pass


class _Guarded:
    """A data column that raises when the strategy reads a bar after the current one (look-ahead check)."""
    __slots__ = ("_seq", "_b")

    def __init__(self, seq, broker):
        self._seq, self._b = seq, broker

    def __len__(self):
        return len(self._seq)

    def __getitem__(self, k):
        now = self._b.i
        if isinstance(k, slice):
            touched = range(*k.indices(len(self._seq)))     # every index the slice reads, any direction
            if len(touched) and max(touched) > now:
                raise FutureReadError(f"slice {k} at bar {now} reads bar {max(touched)}")
        elif k < 0 or k > now:                               # negative = counted from the END of the data
            raise FutureReadError(f"read bar {k} at bar {now}")
        return self._seq[k]

    def __iter__(self):
        raise FutureReadError("iterating over a whole column reads future bars")


class _GuardedColumns(dict):
    def __init__(self, cols, broker):
        super().__init__()
        self._cols, self._b = cols, broker

    def __missing__(self, key):
        g = _Guarded(self._cols[key], self._b)
        self[key] = g
        return g

    def __contains__(self, key):
        return key in self._cols


class Broker:
    """What the strategy talks to: place / cancel orders, read the position."""

    def __init__(self, inst: Instrument, d: dict, settings: Settings):
        self.inst, self.s = inst, settings
        self._d = d            # engine data (execution); strategies read `broker.d`, which may be guarded
        self._view = d
        self.pos: Position | None = None
        self.orders: list[Order] = []
        self.trades: list[dict] = []
        self.realized = 0.0
        self.skipped: dict = {}
        self.notes = {"ambiguous_entry_bars": 0, "ambiguous_exit_bars": 0, "orders_ignored_during_warmup": 0}
        self.i = 0
        self.exhausted_i: int | None = None               # first bar whose marked equity was <= 0
        self._liquidate = False                           # forced close at the next open (account constrained)
        self._close_req: tuple[str, int] | None = None   # (reason, bar it was FIRST requested on)
        self._new_sl = self._new_tp = None
        self.decisions: list[int] = []                    # bars on which on_bar placed an order / close / stop change

    # ---- strategy API ----
    @property
    def d(self):
        """The data as the strategy may see it (bar-bounded during the look-ahead check)."""
        return self._view

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

    def _order(self, side, kind="market", price=None, qty=None, risk_usd=None, risk_pct=None, notional_usd=None,
               sl=None, tp=None, sl_dist=None, tp_dist=None, tp_r=None, tag="", valid_bars=None, intraday=False,
               last_fill_ts=None):
        """intraday=True: the order expires if it hasn't filled by the end of the trading day it was placed on, and
        the resulting position is closed at the first bar of a new trading day if still open (exit reason
        'session_gap_exit': the data had no bar to close it in its own session).
        last_fill_ts (epoch seconds): an absolute deadline checked by the engine before any fill: the order can fill
        only in a bar whose start time is <= last_fill_ts, whatever bars are missing in between."""
        if kind not in ("market", "stop", "limit"):
            raise ValueError(kind)
        if kind != "market" and price is None:
            raise ValueError("stop/limit orders need a price")
        ts0 = self.s.trade_start_ts
        if ts0 is not None and self._d["ts"][self.i] < ts0:
            self.notes["orders_ignored_during_warmup"] += 1
            return None
        if self.s.account_constrained and self.exhausted_i is not None:
            self.notes["orders_refused_capital_exhausted"] = self.notes.get("orders_refused_capital_exhausted", 0) + 1
            return None
        if qty is None and risk_usd is None and risk_pct is None and notional_usd is None:
            qty = self.inst.qty_step
        o = Order(side, kind, price, qty, risk_usd, risk_pct, notional_usd, sl, tp, sl_dist, tp_dist, tp_r, tag,
                  self.i, None if valid_bars is None else self.i + valid_bars, intraday,
                  None if last_fill_ts is None else int(last_fill_ts))
        self.orders.append(o)
        self.decisions.append(self.i)
        return o

    def cancel_all(self):
        self.orders.clear()

    def close(self, reason="close"):
        """Exit the open position at the next bar's open (after delay_bars). Calling it again while a
        close is already pending does NOT restart the delay."""
        if self.pos is not None and self._close_req is None:
            self._close_req = (reason, self.i)
            self.decisions.append(self.i)

    def set_sl(self, price):  self._new_sl = price; self.decisions.append(self.i)
    def set_tp(self, price):  self._new_tp = price; self.decisions.append(self.i)

    def bars_in_trade(self) -> int:
        return 0 if self.pos is None else self.i - self.pos.entry_i


class Engine:
    def __init__(self, df: pd.DataFrame, inst: Instrument, strategy, settings: Settings | None = None,
                 guard: bool = False):
        """guard=True: the strategy's data view raises FutureReadError on any read of a later bar
        (used by check_lookahead; a little slower)."""
        self.s = settings or Settings()
        self.inst = inst
        self.strategy = strategy
        base = df.reset_index(drop=True)
        prepared = strategy.prepare(base.copy()) if hasattr(strategy, "prepare") else base.copy()
        prepared = prepared.reset_index(drop=True)
        _check_untouched(base, prepared)
        self.df = prepared
        d = Columns(prepared)
        self._build_quotes(base, d)
        self.d = d
        self.b = Broker(inst, d, self.s)
        if guard:
            self.b._view = _GuardedColumns(d, self.b)
        strategy.d = self.b.d
        strategy.inst = inst
        strategy.broker = self.b
        tt = self.s.limit_through_ticks
        self.through = (0.0 if inst.uses_bid_ask or inst.spread > 0 else 1.0) * inst.tick if tt is None else tt * inst.tick
        self.ambiguous: list[tuple] = []   # bars whose outcome 1-minute OHLC cannot settle (see tools/verify_ambiguous_fills.py)

    def _build_quotes(self, base: pd.DataFrame, d: Columns):
        """Bid/ask arrays from the ORIGINAL data. Spread stress shifts each bar's whole bid side down and
        ask side up by the same amount, so every widened bar is still a valid OHLC bar."""
        m, inst = self.s.spread_mult, self.inst
        real = inst.uses_bid_ask and "bo" in base
        if real:
            if m == 1.0:
                for k in "ohlc":
                    d["b" + k] = _compact(base["b" + k]); d["a" + k] = _compact(base["a" + k])
                return
            # The open and close are widened by THEIR OWN half-spread (an opening fill never depends on a
            # later quote). Bid low / ask high move by the larger of the two, bid high / ask low by the
            # smaller, so every widened bar is still valid OHLC (and extremes are widened conservatively).
            e_o = (m - 1.0) * np.maximum((base.ao - base.bo).to_numpy(), 0.0) / 2.0
            e_c = (m - 1.0) * np.maximum((base.ac - base.bc).to_numpy(), 0.0) / 2.0
            e_hi, e_lo = np.maximum(e_o, e_c), np.minimum(e_o, e_c)
            shift_b = {"o": e_o, "c": e_c, "h": e_lo, "l": e_hi}
            shift_a = {"o": e_o, "c": e_c, "h": e_hi, "l": e_lo}
            for k in "ohlc":
                d["b" + k] = array("d", (base["b" + k].to_numpy() - shift_b[k]).astype(np.float64).tobytes())
                d["a" + k] = array("d", (base["a" + k].to_numpy() + shift_a[k]).astype(np.float64).tobytes())
            return
        hs = inst.spread / 2.0 * m
        for k in "ohlc":
            px = base[k].to_numpy()
            if hs == 0:
                col = _compact(base[k])
                d["b" + k] = d["a" + k] = col                # futures: bid = ask = traded price
            else:
                d["b" + k] = array("d", (px - hs).astype(np.float64).tobytes())
                d["a" + k] = array("d", (px + hs).astype(np.float64).tobytes())

    # ---------------------------------------------------------------- helpers
    def _slip(self) -> float:
        return self.inst.slippage_ticks * self.inst.tick

    def _skip(self, why: str):
        self.b.skipped[why] = self.b.skipped.get(why, 0) + 1

    def _half_spread(self, i: int, at: str = "o") -> float:
        """Half the bid/ask spread at bar i's open (at='o') or close (at='c'). Fills inside a bar (stops, limits,
        targets) have no contemporaneous quote in OHLC data: they are attributed the opening spread (an estimate;
        the fill price itself always comes from the bar's bid/ask path)."""
        return (self.d["a" + at][i] - self.d["b" + at][i]) / 2.0

    def _floor_qty(self, q: float) -> float:
        step = self.inst.qty_step
        return math.floor(q / step + 1e-9) * step

    def _real(self, i: int, px: float) -> float:
        """Real (unadjusted) price for contract value: back-adjusted price minus the adjustment of the contract the
        bar OPENED with (on a bar where the contract switches inside, a fill can't be placed before or after the
        switch from OHLC alone; the opening contract is the one the bar is labelled with)."""
        if "adj_open" in self.d:
            return px - self.d["adj_open"][i]
        return px - self.d["adj"][i] if "adj" in self.d else px

    def _size(self, o: Order, fill: float, sl: float | None) -> float:
        pv = self.inst.point_value
        real = abs(self._real(self.b.i, fill))
        if o.qty is not None:
            q = o.qty
        elif o.notional_usd is not None:
            q = o.notional_usd / (real * pv) if real else 0.0
        else:
            if sl is None:
                raise ValueError("risk-based sizing needs a stop-loss (sl or sl_dist)")
            risk_per_unit = abs(fill - sl) * pv
            if risk_per_unit <= 0:
                return 0.0
            budget = o.risk_usd if o.risk_usd is not None else self.b.equity * o.risk_pct / 100.0
            q = budget / risk_per_unit
        if self.s.max_leverage is not None and real:
            q = min(q, self.b.equity * self.s.max_leverage / (real * pv))
        return self._floor_qty(q)

    def _open(self, o: Order, i: int, fill: float, slip_pts: float) -> bool:
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
            self._skip("size_below_minimum")
            return False
        comm = self.inst.commission * qty
        self.b.pos = Position(o.side, qty, fill, i, sl, tp, sl, o.tag, costs=comm,
                              slippage_usd=slip_pts * self.inst.point_value * qty,
                              spread_usd=self._half_spread(i) * self.inst.point_value * qty, intraday=o.intraday)
        self.b.realized -= comm
        self.b._close_req = None
        return True

    def _exit(self, i: int, px: float, reason: str, slip_pts: float = 0.0, at: str = "o"):
        p = self.b.pos
        gross = (px - p.entry_px) * p.side * p.qty * self.inst.point_value
        comm = self.inst.commission * p.qty
        p.costs += comm
        p.slippage_usd += slip_pts * self.inst.point_value * p.qty
        p.spread_usd += self._half_spread(i, at) * self.inst.point_value * p.qty
        self.b.realized += gross - comm
        risk = abs(p.entry_px - p.sl_initial) * p.qty * self.inst.point_value if p.sl_initial is not None else np.nan
        d = self.d
        self.b.trades.append({
            "entry_time": d["ts"][p.entry_i], "exit_time": d["ts"][i], "side": "long" if p.side > 0 else "short",
            "qty": p.qty, "entry_px": p.entry_px, "exit_px": px, "sl": p.sl_initial, "tp": p.tp,
            "pnl_gross": gross, "costs": p.costs, "slippage_usd": p.slippage_usd, "spread_usd": p.spread_usd,
            "roll_slippage_usd": p.roll_slippage_usd,
            "pnl": gross - p.costs, "risk_usd": risk,
            "r": (gross - p.costs) / risk if risk and risk > 0 else np.nan,
            "bars": i - p.entry_i, "exit_reason": reason, "tag": p.tag, "rolls": p.rolls,
            "contract": d["contract"][p.entry_i], "mae_pts": p.mae, "mfe_pts": p.mfe,
            "entry_tday": d["tday"][p.entry_i], "exit_tday": d["tday"][i],
        })
        self.b.pos = None
        self.b._close_req = None

    # ------------------------------------------------------- exits of open position
    def _gap_exit(self, i: int) -> bool:
        """Stop or target gapped through at the open of bar i."""
        p, d, slip = self.b.pos, self.d, self._slip()
        if p.side > 0:
            o = d["bo"][i]
            if p.sl is not None and o <= p.sl:
                self._exit(i, o - slip, "sl_gap", slip); return True
            if p.tp is not None and o >= p.tp + self.through:
                self._exit(i, o, "tp_gap"); return True
        else:
            o = d["ao"][i]
            if p.sl is not None and o >= p.sl:
                self._exit(i, o + slip, "sl_gap", slip); return True
            if p.tp is not None and o <= p.tp - self.through:
                self._exit(i, o, "tp_gap"); return True
        return False

    def _intrabar_exit(self, i: int, entry_kind: str | None) -> bool:
        """Stop-loss / target inside bar i. entry_kind: None for a position held from before this bar,
        'open' (entered at this bar's open), 'stop' or 'limit' (entered inside this bar)."""
        p, d, slip = self.b.pos, self.d, self._slip()
        if p.side > 0:
            o, h, l, c = d["bo"][i], d["bh"][i], d["bl"][i], d["bc"][i]
            if p.sl is not None and l <= p.sl:
                if p.tp is not None and (c if entry_kind == "limit" else h) >= p.tp + self.through:
                    self._note_exit_ambiguity(i, p, entry_kind)
                px = o if (entry_kind == "open" and o <= p.sl) else min(p.sl, h)
                self._exit(i, px - slip, "sl", slip); return True
            if p.tp is not None:
                reach = c if entry_kind == "limit" else h
                if reach >= p.tp + self.through:
                    self._pre_exit_worst(l - p.entry_px, p)
                    self._exit(i, p.tp, "tp"); return True
        else:
            o, h, l, c = d["ao"][i], d["ah"][i], d["al"][i], d["ac"][i]
            if p.sl is not None and h >= p.sl:
                if p.tp is not None and (c if entry_kind == "limit" else l) <= p.tp - self.through:
                    self._note_exit_ambiguity(i, p, entry_kind)
                px = o if (entry_kind == "open" and o >= p.sl) else max(p.sl, l)
                self._exit(i, px + slip, "sl", slip); return True
            if p.tp is not None:
                reach = c if entry_kind == "limit" else l
                if reach <= p.tp - self.through:
                    self._pre_exit_worst(p.entry_px - h, p)
                    self._exit(i, p.tp, "tp"); return True
        return False

    def _charge_inside_roll(self, i: int, n_trades_before: int, ambiguous: bool):
        """The contract switched inside bar i while a position was held after the bar's open: charge one roll
        (both sides' commission + slippage). If the position entered or exited inside the bar, the order relative to
        the switch is unknown and the roll is charged anyway (pessimistic, counted in notes)."""
        slip, pv = self._slip(), self.inst.point_value
        b = self.b
        if ambiguous:
            b.notes["roll_inside_bar_ambiguous"] = b.notes.get("roll_inside_bar_ambiguous", 0) + 1
        if b.pos is not None:
            p = b.pos
            c = 2 * self.inst.commission * p.qty + 2 * slip * pv * p.qty
            p.costs += c; p.slippage_usd += 2 * slip * pv * p.qty; p.roll_slippage_usd += 2 * slip * pv * p.qty
            p.rolls += 1
            b.realized -= c
        elif len(b.trades) > n_trades_before:                    # exited inside this bar: charge the closed trade
            t = b.trades[-1]
            c = 2 * self.inst.commission * t["qty"] + 2 * slip * pv * t["qty"]
            t["costs"] += c; t["slippage_usd"] += 2 * slip * pv * t["qty"]; t["rolls"] += 1; t["pnl"] -= c
            t["roll_slippage_usd"] += 2 * slip * pv * t["qty"]
            rk = t.get("risk_usd")
            t["r"] = t["pnl"] / rk if rk and rk > 0 else np.nan          # R from the FINAL net P&L
            b.realized -= c

    def _pre_exit_worst(self, adverse_pts: float, p: Position):
        """A target was reached inside this bar. 1-minute OHLC can't tell whether the bar's adverse extreme came
        before or after the target, so for drawdown it is assumed to have come BEFORE (pessimistic)."""
        eq = self.s.capital + self.b.realized + adverse_pts * p.qty * self.inst.point_value
        self._bar_worst = min(self._bar_worst, eq)
        p.mae = max(p.mae, -adverse_pts)                 # same pessimistic path assumption in the trade export

    def _note_exit_ambiguity(self, i, p, entry_kind):
        self.b.notes["ambiguous_exit_bars"] = self.b.notes.get("ambiguous_exit_bars", 0) + 1
        self.ambiguous.append((self.d["ts"][i], "stop_and_target_same_bar",
                               {"side": p.side, "entry_px": p.entry_px, "entry_ts": self.d["ts"][p.entry_i],
                                "sl": p.sl, "tp": p.tp, "entered_this_bar": entry_kind}))

    # ------------------------------------------------------------- pending entries
    def _trigger(self, o: Order, i: int):
        """(fill price, slippage points, distance from open, entry kind) if order o triggers in bar i."""
        d, slip = self.d, self._slip()
        if o.side > 0:
            op, hi, lo = d["ao"][i], d["ah"][i], d["al"][i]
        else:
            op, hi, lo = d["bo"][i], d["bh"][i], d["bl"][i]
        if o.kind == "market":
            return op + o.side * slip, slip, 0.0, "open"
        if o.kind == "stop":
            if o.side > 0 and hi >= o.price:
                if op >= o.price:
                    return op + slip, slip, 0.0, "open"
                return o.price + slip, slip, o.price - op, "stop"
            if o.side < 0 and lo <= o.price:
                if op <= o.price:
                    return op - slip, slip, 0.0, "open"
                return o.price - slip, slip, op - o.price, "stop"
            return None
        # limit: needs the price to trade THROUGH the limit by `through` (1 tick on futures), also at the open
        th = self.through
        if o.side > 0:
            if op <= o.price - th:
                return op, 0.0, 0.0, "open"
            if lo <= o.price - th:
                return o.price, 0.0, max(op - o.price, 0.0), "limit"
        else:
            if op >= o.price + th:
                return op, 0.0, 0.0, "open"
            if hi >= o.price + th:
                return o.price, 0.0, max(o.price - op, 0.0), "limit"
        return None

    def _fill_entries(self, i: int) -> str | None:
        """Fill at most one entry in bar i. Returns the entry kind, or None."""
        b, delay = self.b, self.s.delay_bars
        live, cand = [], []
        for o in b.orders:
            if o.expires_i is not None and i > o.expires_i:
                continue
            if o.intraday and self.d["tday"][i] != self.d["tday"][o.placed_i]:
                b.notes["intraday_orders_expired"] = b.notes.get("intraday_orders_expired", 0) + 1
                continue
            if o.last_fill_ts is not None and self.d["ts"][i] > o.last_fill_ts:
                b.notes["orders_expired_at_deadline"] = b.notes.get("orders_expired_at_deadline", 0) + 1
                continue
            live.append(o)
            if o.placed_i + delay >= i:
                continue
            t = self._trigger(o, i)
            if t is not None:
                cand.append((t[2], len(cand), o, t))
        b.orders = live
        if not cand:
            return None
        cand.sort(key=lambda c: (c[0], c[1]))               # nearest the open first, then placement order
        if len(cand) > 1 and any(c[3][3] != "open" for c in cand):
            b.notes["ambiguous_entry_bars"] += 1
            self.ambiguous.append((self.d["ts"][i], "several_entries_triggered",
                                   {"chosen": (cand[0][2].side, cand[0][2].kind, cand[0][2].price),
                                    "others": [(c[2].side, c[2].kind, c[2].price) for c in cand[1:]]}))
        for _, _, o, (px, sp, _, kind) in cand:
            if self._open(o, i, px, sp):
                if self.s.oco:
                    b.orders = [x for x in b.orders if x.placed_i + delay >= i]   # cancel the other live entries
                else:
                    b.orders = [x for x in b.orders if x is not o]
                return kind
            b.orders = [x for x in b.orders if x is not o]
        return None

    def _breach(self, i: int, where: str):
        """First observed breach (marked equity <= 0 at an open or a close). Constrained: cancel pending orders and
        liquidate at the next executable open (an opening breach: this bar's open)."""
        b = self.b
        b.exhausted_i = i
        b.notes["capital_exhausted_ts"] = int(self.d["ts"][i])
        b.notes["capital_exhausted_at"] = where
        if self.s.account_constrained:
            b.orders = []
            b._close_req = None
            b._liquidate = b.pos is not None

    def _post_fill_check(self, i: int):
        """Equity right after an entry fill, marked at the opposite quote: the opening commission is paid and closing
        at once would give back the slippage and the whole spread (fill - opposite quote = slippage + 2 x half
        spread). Known at the fill, so at or below $0 it is a breach ('entry'); a constrained account then
        liquidates at the next open, like any other breach."""
        b, p = self.b, self.b.pos
        post = self.s.capital + b.realized - (p.slippage_usd + 2.0 * p.spread_usd)
        self._bar_worst = min(self._bar_worst, post)
        if post <= 0 and b.exhausted_i is None:
            self._breach(i, "entry")

    # ------------------------------------------------------------------- run
    def run(self) -> dict:
        d, b, st = self.d, self.b, self.strategy
        n = len(d["ts"])
        pv = self.inst.point_value
        roll = d["roll"] if "roll" in d else [0] * n
        roll_in = d["roll_inside"] if "roll_inside" in d else None
        delay = self.s.delay_bars
        equity = np.empty(n)
        equity_low = np.empty(n)
        equity_open = np.empty(n)
        slip = self._slip()
        on_bar = st.on_bar
        for i in range(n):
            b.i = i
            self._bar_worst = math.inf
            p = b.pos
            # 1. rolls
            if p is not None and roll[i] and self.s.charge_rolls:
                c = 2 * self.inst.commission * p.qty + 2 * slip * pv * p.qty
                p.costs += c; p.slippage_usd += 2 * slip * pv * p.qty; p.roll_slippage_usd += 2 * slip * pv * p.qty
                p.rolls += 1
                b.realized -= c
            # equity at the open (a held position marked at the opening quote): an observable peak
            if p is not None:
                mo = (d["bo"][i] - p.entry_px) if p.side > 0 else (p.entry_px - d["ao"][i])
                equity_open[i] = self.s.capital + b.realized + mo * p.qty * pv
            else:
                equity_open[i] = self.s.capital + b.realized
            # Account breach at the OPEN: marked equity at the opening quote is observable, so a gap through $0
            # is a breach even if the bar closes higher (constrained: liquidate at this open). Intrabar lows are
            # NOT used to detect a breach (their timing is unknown from OHLC).
            if equity_open[i] <= 0 and b.exhausted_i is None:
                self._breach(i, "open")
            # 2. at the open: forced liquidation first (account exhausted: the very next open, whatever
            #    delay_bars says, and never relabelled as another exit); then an intraday position still open in
            #    a new trading day (its own session ended without a bar to close it in), requested closes,
            #    modifications, gap exits
            if p is not None and b._liquidate:
                px = (d["bo"][i] - slip) if p.side > 0 else (d["ao"][i] + slip)
                self._exit(i, px, "capital_exhausted", slip)
                p = None
            b._liquidate = False
            if p is not None and p.intraday and d["tday"][i] != d["tday"][p.entry_i]:
                px = (d["bo"][i] - slip) if p.side > 0 else (d["ao"][i] + slip)
                self._exit(i, px, "session_gap_exit", slip)
                b.notes["session_gap_exits"] = b.notes.get("session_gap_exits", 0) + 1
                p = None
            if p is not None and b._close_req is not None and i > b._close_req[1] + delay:
                px = (d["bo"][i] - slip) if p.side > 0 else (d["ao"][i] + slip)
                self._exit(i, px, b._close_req[0], slip)
            elif p is None:
                b._close_req = None
            if b.pos is not None:
                if b._new_sl is not None: b.pos.sl = b._new_sl
                if b._new_tp is not None: b.pos.tp = b._new_tp
            b._new_sl = b._new_tp = None
            exited_inside = False
            if b.pos is not None:
                self._gap_exit(i)
            n_trades = len(b.trades)
            held_after_open = b.pos is not None
            if b.pos is not None:
                # 3. inside the bar: the held position's stop/target
                exited_inside = self._intrabar_exit(i, None)
            kind = None
            if b.orders:
                if b.pos is None and not exited_inside:
                    kind = self._fill_entries(i)
                    if kind is not None:
                        held_after_open = True
                        self._post_fill_check(i)
                        self._intrabar_exit(i, kind)
                else:
                    b.orders = [o for o in b.orders if (o.expires_i is None or i <= o.expires_i)
                                and not (o.intraday and d["tday"][i] != d["tday"][o.placed_i])
                                and not (o.last_fill_ts is not None and d["ts"][i] > o.last_fill_ts)]
            if roll_in is not None and roll_in[i] and held_after_open and self.s.charge_rolls:
                self._charge_inside_roll(i, n_trades, ambiguous=exited_inside or (kind not in (None, "open"))
                                         or len(b.trades) > n_trades)
            # 4. mark to market (close, and worst price inside the bar)
            p = b.pos
            base = self.s.capital + b.realized
            if p is not None:
                if p.side > 0:
                    p.mae = max(p.mae, p.entry_px - d["bl"][i]); p.mfe = max(p.mfe, d["bh"][i] - p.entry_px)
                    equity[i] = base + (d["bc"][i] - p.entry_px) * p.qty * pv
                    equity_low[i] = base + (d["bl"][i] - p.entry_px) * p.qty * pv
                else:
                    p.mae = max(p.mae, d["ah"][i] - p.entry_px); p.mfe = max(p.mfe, p.entry_px - d["al"][i])
                    equity[i] = base + (p.entry_px - d["ac"][i]) * p.qty * pv
                    equity_low[i] = base + (p.entry_px - d["ah"][i]) * p.qty * pv
            else:
                equity[i] = equity_low[i] = base
            if self._bar_worst < equity_low[i]:
                equity_low[i] = self._bar_worst
            # account breach at the CLOSE: first bar whose marked equity is <= 0
            if equity[i] <= 0 and b.exhausted_i is None:
                self._breach(i, "close")
            # 5. strategy decides on the closed bar
            on_bar(i)
        if b.pos is not None:
            p = b.pos
            px = (d["bc"][n - 1] - slip) if p.side > 0 else (d["ac"][n - 1] + slip)
            self._exit(n - 1, px, "end_of_data", slip, at="c")
            equity[n - 1] = self.s.capital + b.realized
            equity_low[n - 1] = min(equity_low[n - 1], equity[n - 1])
        trades = pd.DataFrame(b.trades)
        if len(trades):
            for c in ("entry_time", "exit_time"):
                trades[c] = pd.to_datetime(trades[c], unit="s", utc=True)
            for c in ("entry_tday", "exit_tday"):
                trades[c] = trades[c].to_numpy().astype("datetime64[D]")
        eq = pd.DataFrame({"ts": np.asarray(d["ts"]), "tday": np.asarray(d["tday"]).astype("datetime64[D]"),
                           "equity_open": equity_open, "equity": equity,
                           "equity_low": np.minimum(np.minimum(equity_low, equity), equity_open),
                           "breach": np.arange(n) == (b.exhausted_i if b.exhausted_i is not None else -1)})
        amb = pd.DataFrame(self.ambiguous, columns=["ts", "kind", "detail"])
        if len(amb):
            amb["time"] = pd.to_datetime(amb.ts, unit="s", utc=True)
        return {"trades": trades, "equity": eq, "skipped": b.skipped, "notes": dict(b.notes),
                "ambiguous": amb, "settings": self.s, "instrument": self.inst,
                "decision_bars": sorted(set(b.decisions))}


def _check_untouched(base: pd.DataFrame, prepared: pd.DataFrame):
    if len(prepared) != len(base):
        raise ValueError("prepare() must not add or remove rows")
    for c in PROTECTED:
        if c not in base.columns:
            if c in prepared.columns:
                raise ValueError(f"prepare() created the engine column {c!r}; use another name")
            continue
        if c in base.columns:
            if c not in prepared.columns:
                raise ValueError(f"prepare() removed the column {c!r}")
            a, b = base[c].to_numpy(), prepared[c].to_numpy()
            same = (np.array_equal(a, b, equal_nan=True) if a.dtype.kind == "f" else np.array_equal(a, b))
            if not same:
                raise ValueError(f"prepare() changed the column {c!r}; add new columns instead "
                                 "(the engine fills against the original prices)")


class Strategy:
    """Base class. Override prepare() (vectorized indicators, past data only, NEW columns only)
    and on_bar(i) (may read d[...][i] and earlier, never later)."""
    params: dict = {}

    def __init__(self, **params):
        self.p = {**self.params, **params}

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def warmup_bars(self) -> int:
        """Bars of history the indicators need before the first valid signal (used to size window warm-up)."""
        return 0

    def on_bar(self, i: int):
        raise NotImplementedError


def _entries(t: pd.DataFrame, upto) -> list[tuple]:
    if not len(t):
        return []
    x = t[t.entry_time <= upto]
    return [tuple(r) for r in x[["entry_time", "side", "qty", "entry_px"]].itertuples(index=False)]


def _exits(t: pd.DataFrame, before) -> list[tuple]:
    if not len(t):
        return []
    x = t[t.exit_time < before]
    return [tuple(r) for r in x[["entry_time", "exit_time", "exit_px", "exit_reason"]].itertuples(index=False)]


EARLY_CUTS = (1, 2, 3, 5, 9, 17, 33, 65, 129)    # also cut the data in its first rows (a feature that peeks only there)
BOUNDARY_CUTS = 16      # extra cuts right after the strategy's own decision bars and its signals' flips (half each)


def signal_flips(full: pd.DataFrame, cols) -> list[int]:
    """Rows where a prepared True/False signal column changes value (where a sparse future read would matter)."""
    out = set()
    for c in cols:
        x = full[c]
        if x.dtype == bool or (x.dtype == object and x.dropna().isin([True, False]).all() and x.notna().any()):
            v = x.fillna(False).to_numpy(dtype=bool)
            out.update((np.flatnonzero(v[1:] != v[:-1]) + 1).tolist())
    return sorted(out)


def boundary_cuts(decisions, flips, n: int, done, limit: int = BOUNDARY_CUTS) -> list[int]:
    """Prefix lengths k = row + 1 right after decision rows and signal flips (the cut keeps that row and drops the
    next one): an even sample of up to limit/2 of each, then topped up from either list, skipping cuts already done."""
    def ks(rows):
        return [k for k in sorted({int(r) + 1 for r in rows}) if 2 <= k < n and k not in done]
    a, b = ks(decisions), ks(flips)
    pick = lambda xs, m: [xs[int(j)] for j in np.unique(np.linspace(0, len(xs) - 1, m).round())] if m and xs else []  # noqa: E731
    half = limit // 2
    got = sorted(set(pick(a, min(half, len(a))) + pick(b, min(half, len(b)))))
    rest = [k for k in a + b if k not in got]
    return sorted(set(got + pick(rest, min(limit - len(got), len(rest)))))


def _column_problems(make, base: pd.DataFrame, full: pd.DataFrame, cols, ks, why=None) -> tuple[list[str], set]:
    """Re-run prepare() on each prefix of length k and compare every prepared column on the rows kept."""
    problems, bad = [], {}
    for k in ks:
        try:
            part = make().prepare(base.iloc[:k].copy()).reset_index(drop=True)
        except Exception as e:            # prepare() must work on any prefix: failing means it needs later rows
            problems.append(f"prepare() fails when only the first {k} rows exist ({type(e).__name__}: {e})"
                            + (f" [{why(k)}]" if why else ""))
            continue
        for c in cols:
            if c not in bad and (c not in part.columns or not _same(full[c].iloc[:k], part[c])):
                bad[c] = k
    return problems, bad


def check_lookahead(strategy, df: pd.DataFrame, inst: Instrument | None = None, settings: Settings | None = None,
                    cuts=(0.35, 0.6, 0.85), coverage: dict | None = None) -> list[str]:
    """Detect use of future data. Returns a list of problems (empty = passed).

    1. prepare() may not change the prices the engine fills against.
    2. Every column prepare() produces (new or changed) must be identical when future rows are removed. This is a
       SAMPLED check: prefixes cut at fixed fractions, in the first rows (EARLY_CUTS), right after rows where a
       True/False signal flips, and (with inst) right after the strategy's own decision bars (BOUNDARY_CUTS in
       all). A future read in a row that no cut separates from the row it reads is not seen.
    3. (needs inst) on_bar() runs with guarded data over EVERY bar: reading any later bar is reported.
    4. (needs inst) Prefix test: on data cut at row k, the entries up to the cut and the exits completed
       before it must be identical to the full run's.
    `coverage` (a dict) is filled with what was sampled. `strategy` may be an instance or a zero-argument factory
    (a new instance is needed per run)."""
    make = strategy if callable(strategy) and not isinstance(strategy, Strategy) else (lambda s=strategy: type(s)(**getattr(s, "p", {})))
    problems = []
    base = df.reset_index(drop=True)
    full = make().prepare(base.copy()).reset_index(drop=True)
    try:
        _check_untouched(base, full)
    except ValueError as e:
        problems.append(str(e))
    cols = [c for c in full.columns if c not in base.columns or not _same(base[c], full[c])]
    col_cuts = sorted({int(len(base) * f) for f in cuts} | {k for k in EARLY_CUTS if k < len(base)})
    flips = signal_flips(full, cols)
    cov = coverage if coverage is not None else {}
    cov.update({"fixed_cuts": len(col_cuts), "signal_flips": len(flips), "decision_rows": None, "boundary_cuts": 0})
    p1, bad = _column_problems(make, base, full, cols, col_cuts)
    problems += p1
    if inst is None:
        ks = boundary_cuts([], flips, len(base), set(col_cuts))
        cov["boundary_cuts"] = len(ks)
        p2, bad2 = _column_problems(make, base, full, cols, ks, why=lambda k: f"cut after signal row {k - 1}")
        problems += p2
        bad = {**bad2, **bad}
        return problems + [f"column {c!r} changes when future rows are removed (first seen with {k} rows)"
                           for c, k in sorted(bad.items())]
    if problems or bad:
        return problems + [f"column {c!r} changes when future rows are removed (first seen with {k} rows)"
                           for c, k in sorted(bad.items())]
    s = settings or Settings()
    # (a) guarded run: any read of a later bar in on_bar() raises immediately
    try:
        res = Engine(base, inst, make(), s, guard=True).run()
    except FutureReadError as e:
        problems.append(f"on_bar() reads data from a later bar ({e})")
        return problems
    ref = res["trades"]
    # (b) prepared features again, cut right after the strategy's own decisions and its signals' flips
    dec = res.get("decision_bars", [])
    ks = boundary_cuts(dec, flips, len(base), set(col_cuts))
    cov.update({"decision_rows": len(dec), "boundary_cuts": len(ks)})
    dset = set(dec)
    p2, bad = _column_problems(make, base, full, cols, ks,
                               why=lambda k: f"cut after {'decision' if k - 1 in dset else 'signal'} row {k - 1}")
    problems += p2 + [f"column {c!r} changes when future rows are removed (cut after "
                      f"{'decision' if k - 1 in dset else 'signal'} row {k - 1})" for c, k in sorted(bad.items())]
    if problems:
        return problems
    # (c) prefix test: entries up to each cut, and exits completed before it, must not change
    #     when later rows are removed
    for f in cuts:
        k = int(len(base) * f)
        if k < 3:
            continue
        last_ts = pd.Timestamp(int(base.ts.iloc[k - 1]), unit="s", tz="UTC")
        part = Engine(base.iloc[:k], inst, make(), s).run()["trades"]
        if _entries(ref, last_ts) != _entries(part, last_ts) or _exits(ref, last_ts) != _exits(part, last_ts):
            problems.append(f"trades up to row {k} change when later rows are removed (uses future data)")
            break
    return problems


def check_boundary_cuts(strategy, df: pd.DataFrame, inst: Instrument, settings: Settings | None = None,
                        cuts=(0.35, 0.6, 0.85), coverage: dict | None = None, engine=None, run_args=()) -> list[str]:
    """Only the decision-bar / signal-flip part of check_lookahead (step 2's boundary cuts), for re-checking saved runs
    that already passed the other steps with the same strategy code and data. `engine`/`run_args`: the pairs engine
    and its second instrument (default: the single-market Engine)."""
    make = strategy if callable(strategy) and not isinstance(strategy, Strategy) else (lambda s=strategy: type(s)(**getattr(s, "p", {})))
    base = df.reset_index(drop=True)
    full = make().prepare(base.copy()).reset_index(drop=True)
    cols = [c for c in full.columns if c not in base.columns or not _same(base[c], full[c])]
    done = set({int(len(base) * f) for f in cuts} | {k for k in EARLY_CUTS if k < len(base)})
    flips = signal_flips(full, cols)
    E = engine or Engine
    res = E(base, inst, *run_args, make(), settings or Settings()).run()
    dec = res.get("decision_bars", [])
    ks = boundary_cuts(dec, flips, len(base), done)
    if coverage is not None:
        coverage.update({"signal_flips": len(flips), "decision_rows": len(dec), "boundary_cuts": len(ks)})
    dset = set(dec)
    problems, bad = _column_problems(make, base, full, cols, ks)
    return problems + [f"column {c!r} changes when future rows are removed (cut after "
                       f"{'decision' if k - 1 in dset else 'signal'} row {k - 1})" for c, k in sorted(bad.items())]


def _same(a: pd.Series, b: pd.Series) -> bool:
    a, b = a.to_numpy(), b.to_numpy()
    if len(a) != len(b):
        return False
    if a.dtype.kind in "fc" and b.dtype.kind in "fc":
        return bool(np.all(np.isclose(a, b, equal_nan=True, rtol=1e-9, atol=1e-9)))
    return bool(np.all((a == b) | (pd.isna(a) & pd.isna(b))))
