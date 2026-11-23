"""Pairs (two-leg) backtests: leg A = a futures contract (GC via MGC/GC), leg B = XAUUSD spot (real bid/ask).

Data: `load_pair("GC", "XAUUSD", tf, session)` aligns both legs on the same bar times. Leg A's columns are the
usual o/h/l/c (back-adjusted) + raw_*, roll, contract; leg B's are xo/xh/xl/xc (mid) and xbo..xbc / xao..xac
(bid / ask).

Execution (same principles as the single-market engine):
  - the strategy decides at a bar's close; both legs fill at the NEXT bar's open (+ delay_bars);
  - leg A pays commission and slippage; leg B buys at the ask and sells at the bid (spread stress widens it);
  - a held position pays the cost of rolling leg A at a contract switch;
  - P&L per trade is broken down: pnl = pnl_nominal (both legs at mid, no costs) - spread_cost (spot bid/ask)
    - slippage_cost (futures) - commission - roll_cost;
  - equity is marked at every bar's open and close. The bar's low for drawdown is a PESSIMISTIC BOUND: each leg
    marked at its own adverse extreme inside the bar (leg A's low/high, leg B's bid low / ask high). The two
    extremes need not happen at the same moment, so the true combined low is never worse than this bound;
  - only one pair position at a time; 'long spread' = long A, short beta x B (A - beta x B): with a negative
    beta the second leg is bought;
  - Settings.max_leverage caps the GROSS exposure of both legs at equity x max_leverage;
  - account model as in the single-market engine: a breach (marked equity <= 0 at a bar's open or close) is
    reported, and with Settings(account_constrained=True) both legs are closed at the next executable open (this
    open for a breach at the open) and no new pair is opened.
"""
from dataclasses import dataclass, replace
import math

import numpy as np
import pandas as pd

from . import data
from .core import Columns, Settings, _GuardedColumns, _check_untouched, FutureReadError
from .instruments import Instrument, get as get_instrument


def combine_legs(a: pd.DataFrame, b: pd.DataFrame, tf: int = 60, session: str = "full") -> pd.DataFrame:
    """Align two 1-minute tables on COMMON minutes first, then build bars: every bar's open/close of both legs
    comes from the same minute, and a minute where either leg has no quote is left out of both (no stale
    prices). Leg A's contract switches on dropped minutes are carried to the next kept minute.
    `ts_last_a` / `ts_last_b` = the source minute of each leg's close (identical by construction)."""
    bcols = {"o": "xo", "h": "xh", "l": "xl", "c": "xc", "bo": "xbo", "bh": "xbh", "bl": "xbl", "bc": "xbc",
             "ao": "xao", "ah": "xah", "al": "xal", "ac": "xac"}
    m = a.merge(b[["ts"] + [c for c in bcols if c in b]].rename(columns=bcols), on="ts", how="inner")
    seg = np.cumsum(a["roll"].to_numpy(dtype=bool))
    kept = seg[np.isin(a.ts.to_numpy(), m.ts.to_numpy())]
    m["roll"] = kept != np.r_[seg[0], kept[:-1]] if len(m) else np.array([], dtype=bool)
    m["ts_last"] = m.ts
    out = data.resample(m, tf, session) if tf > 1 or session != "full" else m
    out["ts_last_a"] = out["ts_last"]
    out["ts_last_b"] = out["ts_last"]
    return out.reset_index(drop=True)


def load_pair(key_a: str = "GC", key_b: str = "XAUUSD", tf: int = 60, session: str = "full",
              start: str | None = None, end: str | None = None) -> pd.DataFrame:
    return combine_legs(data.load(key_a, start, end), data.load(key_b, start, end), tf, session)


@dataclass
class PairPosition:
    side: int            # +1 long spread (long A, short B), -1 short spread
    qa: float
    qb: float
    pa: float            # leg A fill
    pb: float            # leg B fill
    entry_i: int
    beta: float
    costs: float
    tag: str
    mid_a: float = 0.0
    mid_b: float = 0.0
    side_b: int = 0      # direction of leg B: -side x sign(beta)
    rolls: int = 0
    roll_cost: float = 0.0


class PairsBroker:
    def __init__(self, engine):
        self._e = engine
        self.i = 0
        self.pos: PairPosition | None = None
        self._pending: tuple | None = None          # ("open", side, beta, tag, placed_i) or ("close", reason, placed_i)
        self.trades: list[dict] = []
        self.realized = 0.0
        self.skipped: dict = {}
        self.notes = {"orders_ignored_during_warmup": 0}
        self._view = None
        self.exhausted_i: int | None = None
        self._liquidate = False
        self.decisions: list[int] = []

    @property
    def d(self):
        return self._view

    @property
    def flat(self):
        return self.pos is None

    @property
    def position(self):
        return 0 if self.pos is None else self.pos.side

    def bars_in_trade(self):
        return 0 if self.pos is None else self.i - self.pos.entry_i

    def open(self, side: int, beta: float, tag: str = ""):
        ts0 = self._e.s.trade_start_ts
        if ts0 is not None and self._e.d["ts"][self.i] < ts0:
            self.notes["orders_ignored_during_warmup"] += 1
            return
        if self._e.s.account_constrained and self.exhausted_i is not None:
            self.notes["orders_refused_capital_exhausted"] = self.notes.get("orders_refused_capital_exhausted", 0) + 1
            return
        if self.pos is None and self._pending is None:
            self._pending = ("open", side, beta, tag, self.i)
            self.decisions.append(self.i)

    def close(self, reason: str = "close"):
        if self.pos is not None and self._pending is None:
            self._pending = ("close", reason, self.i)
            self.decisions.append(self.i)


class PairsEngine:
    def __init__(self, df: pd.DataFrame, inst_a: Instrument, inst_b: Instrument, strategy, settings: Settings | None = None,
                 guard: bool = False):
        self.s = settings or Settings()
        self.ia, self.ib = inst_a, inst_b
        base = df.reset_index(drop=True)
        prepared = strategy.prepare(base.copy()).reset_index(drop=True)
        _check_untouched(base, prepared)
        for c in ("xo", "xc", "xbo", "xbc", "xao", "xac"):
            if c in base and not np.array_equal(base[c].to_numpy(), prepared[c].to_numpy(), equal_nan=True):
                raise ValueError(f"prepare() changed the column {c!r}")
        d = Columns(prepared)
        m = self.s.spread_mult
        for k in "ohlc":
            if "xb" + k not in base:              # no bid/ask extremes: use the mid's
                base["xb" + k], base["xa" + k] = base["x" + k], base["x" + k]
            bid, ask = base["xb" + k].to_numpy(), base["xa" + k].to_numpy()
            extra = (m - 1.0) * np.maximum(ask - bid, 0) / 2.0
            d["qb" + k] = (bid - extra).tolist()
            d["qa" + k] = (ask + extra).tolist()
        self.d = d
        self.b = PairsBroker(self)
        self.b._view = _GuardedColumns(d, self.b) if guard else d
        strategy.d, strategy.broker, strategy.inst = self.b.d, self.b, inst_a
        strategy.inst_b = inst_b
        self.strategy = strategy

    def _slip(self):
        return self.ia.slippage_ticks * self.ia.tick

    def _fill_open(self, i, side, beta, tag):
        d, ia, ib = self.d, self.ia, self.ib
        pa = d["o"][i] + side * self._slip()
        real_a = d["raw_o"][i] if "raw_o" in d else d["o"][i]
        notional = self.strategy.p.get("notional", 100_000.0)
        side_b = -side * (1 if beta >= 0 else -1)             # A - beta x B: long spread sells B when beta > 0
        pb = d["qao"][i] if side_b > 0 else d["qbo"][i]          # buy at the ask, sell at the bid
        units = notional / (real_a * ia.point_value)
        if self.s.max_leverage is not None:                   # gross exposure of both legs <= equity x leverage
            per_a = ia.point_value * (real_a + abs(beta) * pb)
            units = min(units, max(self.s.capital + self.b.realized, 0.0) * self.s.max_leverage / per_a if per_a > 0 else 0.0)
        qa = math.floor(units / ia.qty_step + 1e-9) * ia.qty_step
        # hedge: beta units of B per unit of A, in ounces (A: point_value $/pt = oz per contract)
        qb = math.floor(abs(beta) * qa * ia.point_value / ib.point_value / ib.qty_step + 1e-9) * ib.qty_step
        if qa < ia.qty_step or qb < ib.qty_step:
            self.b.skipped["size_below_minimum"] = self.b.skipped.get("size_below_minimum", 0) + 1
            return
        costs = ia.commission * qa + ib.commission * qb
        self.b.realized -= costs
        self.b.pos = PairPosition(side, qa, qb, pa, pb, i, beta, costs, tag, mid_a=d["o"][i], mid_b=d["xo"][i],
                                  side_b=side_b)

    def _mark(self, i, k):
        p, d = self.b.pos, self.d
        pa = d["o"][i] if k == "o" else d["c"][i]
        pb = (d["qb" + k][i] if p.side_b > 0 else d["qa" + k][i])  # to close: sell long B at the bid, buy short B at the ask
        return ((pa - p.pa) * p.side * p.qa * self.ia.point_value
                + (pb - p.pb) * p.side_b * p.qb * self.ib.point_value)

    def _mark_worst(self, i):
        """Pessimistic bound for the bar: each leg at its own adverse extreme inside the bar."""
        p, d = self.b.pos, self.d
        pa = d["l"][i] if p.side > 0 else d["h"][i]
        pb = d["qbl"][i] if p.side_b > 0 else d["qah"][i]
        return ((pa - p.pa) * p.side * p.qa * self.ia.point_value
                + (pb - p.pb) * p.side_b * p.qb * self.ib.point_value)

    def _close(self, i, reason, at="o"):
        p, d = self.b.pos, self.d
        slip = self._slip()
        mid_a = d["o"][i] if at == "o" else d["c"][i]
        pa = mid_a - p.side * slip
        pb = d[("qb" if p.side_b > 0 else "qa") + at][i]
        mid_b = (d["xo"][i] if at == "o" else d["xc"][i])
        ga = (pa - p.pa) * p.side * p.qa * self.ia.point_value
        gb = (pb - p.pb) * p.side_b * p.qb * self.ib.point_value
        comm = self.ia.commission * p.qa + self.ib.commission * p.qb
        p.costs += comm
        self.b.realized += ga + gb - comm
        # P&L components: nominal = both legs at mid prices with no costs; then what each cost took away
        pva, pvb = self.ia.point_value, self.ib.point_value
        nominal = ((mid_a - p.mid_a) * p.side * p.qa * pva + (mid_b - p.mid_b) * p.side_b * p.qb * pvb)
        spread_cost = ((mid_b - pb) + (p.pb - p.mid_b)) * p.side_b * p.qb * pvb
        slippage_cost = 2 * slip * pva * p.qa
        commission = 2 * (self.ia.commission * p.qa + self.ib.commission * p.qb)
        self.b.trades.append({
            "entry_time": d["ts"][p.entry_i], "exit_time": d["ts"][i], "side": "long" if p.side > 0 else "short",
            "qty": p.qa, "qty_b": p.qb, "beta": p.beta, "entry_px": p.pa, "exit_px": pa, "entry_px_b": p.pb, "exit_px_b": pb,
            "pnl_gross": ga + gb, "pnl_a": ga, "pnl_b": gb, "costs": p.costs,
            "pnl_nominal": nominal, "spread_cost": spread_cost, "slippage_cost": slippage_cost,
            "commission": commission, "roll_cost": p.roll_cost,
            "slippage_usd": 2 * slip * self.ia.point_value * p.qa * (1 + p.rolls), "spread_usd": spread_cost,
            "pnl": ga + gb - p.costs, "r": np.nan, "bars": i - p.entry_i, "exit_reason": reason, "tag": p.tag,
            "rolls": p.rolls, "contract": d["contract"][p.entry_i], "mae_pts": np.nan, "mfe_pts": np.nan,
            "entry_tday": d["tday"][p.entry_i], "exit_tday": d["tday"][i]})
        self.b.pos = None

    def run(self) -> dict:
        d, b, st = self.d, self.b, self.strategy
        n = len(d["ts"])
        cap, delay, slip, pva = self.s.capital, self.s.delay_bars, self._slip(), self.ia.point_value
        roll = d["roll"]
        roll_in = d["roll_inside"] if "roll_inside" in d else None
        eq_o, eq_c, eq_w = np.empty(n), np.empty(n), np.empty(n)

        def breach(i, where):
            b.exhausted_i = i
            b.notes["capital_exhausted_ts"] = int(d["ts"][i])
            b.notes["capital_exhausted_at"] = where
            if self.s.account_constrained:
                b._pending = None
                b._liquidate = b.pos is not None

        def charge(p):
            c = 2 * self.ia.commission * p.qa + 2 * slip * pva * p.qa
            p.costs += c; p.rolls += 1; p.roll_cost += c; b.realized -= c
        for i in range(n):
            b.i = i
            post_fill = np.inf
            p = b.pos
            if p is not None and roll[i] and self.s.charge_rolls:
                charge(p)
            eq_o[i] = cap + b.realized + (self._mark(i, "o") if b.pos is not None else 0.0)
            if eq_o[i] <= 0 and b.exhausted_i is None:          # a gap through $0 at the open is a breach
                breach(i, "open")
            if b._liquidate and b.pos is not None:            # account exhausted: both legs out at this open
                self._close(i, "capital_exhausted")
            b._liquidate = False
            pend = b._pending
            if pend is not None and i > pend[-1] + delay:
                b._pending = None
                if pend[0] == "close" and b.pos is not None:
                    self._close(i, pend[1])
                elif pend[0] == "open" and b.pos is None:
                    self._fill_open(i, pend[1], pend[2], pend[3])
                    if b.pos is not None:     # marked right after the fill: commissions, slippage, both spreads
                        post_fill = cap + b.realized + self._mark(i, "o")
                        if post_fill <= 0 and b.exhausted_i is None:
                            breach(i, "entry")
            if roll_in is not None and roll_in[i] and b.pos is not None and self.s.charge_rolls:
                charge(b.pos)                     # held after the open through a switch inside the bar
            eq_c[i] = cap + b.realized + (self._mark(i, "c") if b.pos is not None else 0.0)
            eq_w[i] = min(cap + b.realized + (self._mark_worst(i) if b.pos is not None else 0.0), post_fill)
            if eq_c[i] <= 0 and b.exhausted_i is None:
                breach(i, "close")
            st.on_bar(i)
        if b.pos is not None:
            self._close(n - 1, "end_of_data", at="c")
            eq_c[n - 1] = cap + b.realized
        trades = pd.DataFrame(b.trades)
        if len(trades):
            for c in ("entry_time", "exit_time"):
                trades[c] = pd.to_datetime(trades[c], unit="s", utc=True)
            for c in ("entry_tday", "exit_tday"):
                trades[c] = trades[c].to_numpy().astype("datetime64[D]")
        eq = pd.DataFrame({"ts": np.asarray(d["ts"]), "tday": np.asarray(d["tday"]).astype("datetime64[D]"),
                           "equity_open": eq_o, "equity_low": np.minimum(np.minimum(eq_o, eq_c), eq_w), "equity": eq_c,
                           "breach": np.arange(n) == (b.exhausted_i if b.exhausted_i is not None else -1)})
        return {"trades": trades, "equity": eq, "skipped": b.skipped, "notes": dict(b.notes),
                "ambiguous": pd.DataFrame(columns=["ts", "kind", "detail"]), "settings": self.s, "instrument": self.ia,
                "decision_bars": sorted(set(b.decisions))}


def check_lookahead_pairs(make, df: pd.DataFrame, inst_a, inst_b, settings=None, cuts=(0.35, 0.6, 0.85),
                          coverage: dict | None = None) -> list[str]:
    """Same checks as core.check_lookahead, for pair strategies (fixed, early, signal-flip and decision cuts)."""
    from .core import EARLY_CUTS, _column_problems, _entries, _exits, _same, boundary_cuts, signal_flips
    base = df.reset_index(drop=True)
    full = make().prepare(base.copy()).reset_index(drop=True)
    cols = [c for c in full.columns if c not in base.columns or not _same(base[c], full[c])]
    col_cuts = sorted({int(len(base) * f) for f in cuts} | {k for k in EARLY_CUTS if k < len(base)})
    flips = signal_flips(full, cols)
    problems, bad = _column_problems(make, base, full, cols, col_cuts)
    cov = coverage if coverage is not None else {}
    cov.update({"fixed_cuts": len(col_cuts), "signal_flips": len(flips), "decision_rows": None, "boundary_cuts": 0})
    if problems or bad:
        return sorted(set(problems + [f"column {c!r} changes when future rows are removed" for c in bad]))
    s = settings or Settings()
    try:
        res = PairsEngine(base, inst_a, inst_b, make(), s, guard=True).run()
    except FutureReadError as e:
        return [f"on_bar() reads data from a later bar ({e})"]
    ref = res["trades"]
    dec = res.get("decision_bars", [])
    ks = boundary_cuts(dec, flips, len(base), set(col_cuts))
    cov.update({"decision_rows": len(dec), "boundary_cuts": len(ks)})
    problems, bad = _column_problems(make, base, full, cols, ks)
    if problems or bad:
        return sorted(set(problems + [f"column {c!r} changes when future rows are removed (cut after row {k - 1})"
                                      for c, k in bad.items()]))
    for f in cuts:
        k = int(len(base) * f)
        last_ts = pd.Timestamp(int(base.ts.iloc[k - 1]), unit="s", tz="UTC")
        part = PairsEngine(base.iloc[:k], inst_a, inst_b, make(), s).run()["trades"]
        if _entries(ref, last_ts) != _entries(part, last_ts) or _exits(ref, last_ts) != _exits(part, last_ts):
            return [f"trades up to row {k} change when later rows are removed (uses future data)"]
    return []


def is_pairs(cls) -> bool:
    return getattr(cls, "ENGINE", "") == "pairs"


def pair_key(cls) -> str:
    return "+".join(cls.LEGS)
