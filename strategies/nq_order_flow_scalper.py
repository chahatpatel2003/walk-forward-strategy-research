"""A13-inspired one-minute NQ/MNQ scalper using aggressor volume and price response.

Continuation follows a strong imbalance when the candle agrees. Absorption follows the candle when the
imbalance points the other way. Signals only use completed minutes and orders expire after the next minute.
Each trade uses one contract, an ATR stop, a fixed target multiple, and a short time exit. A positive
pullback_ticks parameter requests a passive limit at that distance from the signal close.
"""
import math

import numpy as np

from engine import Strategy
from engine.calendar import session_close_minute


class OneMinuteScalper(Strategy):
    """Shared single-contract execution for strictly intraday scalps."""
    TF, SESSIONS, MARKETS = 1, ("rth",), ("NQ", "MNQ")

    def cash_minutes(self, df):
        p = self.p
        if df.attrs.get("bar_minutes", 1) != 1:
            raise ValueError("scalper requires one-minute bars")
        for name in ("hold", "atr_period", "pullback_ticks"):
            value = p[name]
            if not isinstance(value, (int, np.integer)) or value < (0 if name == "pullback_ticks" else 1):
                raise ValueError(f"invalid whole-number {name} {value!r}")
        for name in ("stop_atr", "target_r", "risk_usd"):
            if not math.isfinite(p[name]) or p[name] <= 0:
                raise ValueError(f"{name} must be positive and finite")
        minutes = df.ny_min.to_numpy()
        if ((minutes < 570) | (minutes >= 960)).any():
            raise ValueError("scalper requires the New York cash session")
        return minutes

    def atr(self, df):
        previous = df.c.shift().where(df.ts.diff().eq(60) & df.tday.eq(df.tday.shift()), df.o)
        true_range = np.maximum(df.h - df.l, np.maximum((df.h - previous).abs(), (df.l - previous).abs()))
        n = self.p["atr_period"]
        return true_range.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()

    def annotate(self, df, minutes, side, atr):
        close = session_close_minute(df.tday.to_numpy())
        can_enter = (minutes >= 575) & (minutes + 1 < close - 30)
        df["scalp_side"] = np.where(can_enter & atr.notna(), side, 0).astype(np.int8)
        df["scalp_stop_distance"] = atr * self.p["stop_atr"]
        df["scalp_end"] = minutes >= close - 2
        return df

    def on_bar(self, i):
        d, b, p = self.d, self.broker, self.p
        if not b.flat:
            if d["scalp_end"][i]:
                b.close("session_end")
            elif b.bars_in_trade() + 1 >= p["hold"]:
                b.close("time_exit")
            return
        side = d["scalp_side"][i]
        if not side or b.orders:
            return

        inst = self.inst
        stop = math.ceil(d["scalp_stop_distance"][i] / inst.tick) * inst.tick
        if stop <= 0:
            return
        exit_slippage = inst.slippage_ticks * inst.tick
        planned_risk = (stop + exit_slippage) * inst.point_value + 2 * inst.commission
        if planned_risk > p["risk_usd"]:
            key = "one_contract_exceeds_budget"
            b.skipped[key] = b.skipped.get(key, 0) + 1
            return

        target = math.ceil(stop * p["target_r"] / inst.tick) * inst.tick
        order = b.buy if side > 0 else b.sell
        pullback = p["pullback_ticks"]
        entry = dict(kind="limit", price=d["c"][i] - side * pullback * inst.tick) if pullback else {}
        order(**entry, qty=1, sl_dist=stop, tp_dist=target, intraday=True, valid_bars=1,
              last_fill_ts=d["ts"][i] + 60, tag=p["mode"])


class NQOrderFlowScalper(OneMinuteScalper):
    params = dict(mode="continuation", flow_minutes=1, imbalance=0.13, hold=3, stop_atr=0.60,
                  target_r=1.25, atr_period=14, min_body_atr=0.25, risk_usd=200.0, pullback_ticks=0)

    def prepare(self, df):
        p = self.p
        minutes = self.cash_minutes(df)
        if not {"buy_vol", "sell_vol"}.issubset(df.columns):
            raise ValueError("NQ order-flow scalper requires one-minute aggressor volume")
        if p["mode"] not in {"continuation", "absorption"}:
            raise ValueError("mode must be continuation or absorption")
        n = p["flow_minutes"]
        if not isinstance(n, (int, np.integer)) or n < 1:
            raise ValueError("flow_minutes must be a positive integer")
        if not 0 < p["imbalance"] <= 1 or not math.isfinite(p["min_body_atr"]) or p["min_body_atr"] <= 0:
            raise ValueError("invalid imbalance or minimum body filter")

        atr = self.atr(df)
        signed = (df.buy_vol - df.sell_vol).rolling(n, min_periods=n).sum()
        volume = (df.buy_vol + df.sell_vol).rolling(n, min_periods=n).sum()
        same_sequence = df.ts.sub(df.ts.shift(n - 1)).eq((n - 1) * 60) & df.tday.eq(df.tday.shift(n - 1))
        imbalance = (signed / volume.where(volume > 0)).where(same_sequence)
        body = df.c - df.o
        response = body * imbalance
        agreement = response.gt(0) if p["mode"] == "continuation" else response.lt(0)
        trigger = agreement & imbalance.abs().ge(p["imbalance"]) & body.abs().ge(p["min_body_atr"] * atr)
        return self.annotate(df, minutes, np.where(trigger, np.sign(body), 0), atr)


STRATEGY = NQOrderFlowScalper
