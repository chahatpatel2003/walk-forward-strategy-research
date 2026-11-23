"""Tests for indicators, calendar periods, cash-session bars and the photo strategies."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine import Engine, Settings, check_lookahead, data  # noqa: E402
from engine import indicators as ind  # noqa: E402
from engine.calendar import period_position  # noqa: E402
from engine.instruments import Instrument  # noqa: E402
from engine.loader import load_strategy  # noqa: E402
from test_engine import FREE  # noqa: E402

PHOTOS = sorted((ROOT / "strategies/photos").glob("a*.py"))


# ---------------------------------------------------------------- indicators vs reference loops
def ref_rsi(c, n):
    d = np.diff(c)
    up, dn = np.maximum(d, 0), np.maximum(-d, 0)
    out = np.full(len(c), np.nan)
    au, ad = up[:n].mean(), dn[:n].mean()          # (pandas ewm seeds with the first value; compare after warm-up)
    return out, up, dn


def test_rsi_matches_wilder_definition():
    rng = np.random.default_rng(0)
    c = pd.Series(100 + np.cumsum(rng.normal(0, 1, 400)))
    r = ind.rsi(c, 3)
    d = c.diff()
    au = d.clip(lower=0).iloc[1:].to_numpy(); ad = (-d.clip(upper=0)).iloc[1:].to_numpy()
    a_u, a_d = au[0], ad[0]
    for k in range(1, len(au)):               # Wilder smoothing with alpha = 1/n, seeded with the first change
        a_u = a_u + (au[k] - a_u) / 3; a_d = a_d + (ad[k] - a_d) / 3
    assert r.iloc[-1] == pytest.approx(100 - 100 / (1 + a_u / a_d))
    assert ind.rsi(pd.Series(np.arange(50.0)), 3).iloc[-1] == 100      # only gains
    assert ind.rsi(pd.Series(np.arange(50.0)[::-1]), 3).iloc[-1] == pytest.approx(0)


def test_mfi_hand_example():
    h = pd.Series([11.0, 12, 13, 12]); l = pd.Series([9.0, 10, 11, 10]); c = pd.Series([10.0, 11, 12, 11])
    v = pd.Series([100.0, 200, 100, 300])
    m = ind.mfi(h, l, c, v, 2)
    # bar 2: typical 12 > 11 -> +1200; bar 1: 11 > 10 -> +2200  => all positive => 100
    assert m.iloc[2] == 100
    # bar 3: typical 11 < 12 -> -3300; bar 2: +1200  => 100 - 100/(1 + 1200/3300)
    assert m.iloc[3] == pytest.approx(100 - 100 / (1 + 1200 / 3300))
    assert np.isnan(m.iloc[1])


def test_stochastic_williams_vwap_examples():
    h = pd.Series([10.0, 12, 11, 13]); l = pd.Series([8.0, 9, 9, 10]); c = pd.Series([9.0, 11, 10, 12])
    k = ind.stochastic_k(h, l, c, 3)
    assert k.iloc[2] == pytest.approx((10 - 8) / (12 - 8) * 100)
    assert ind.williams_r(h, l, c, 3).iloc[2] == pytest.approx((12 - 10) / (12 - 8) * -100)
    v = pd.Series([1.0, 1, 2, 2])
    tp = (h + l + c) / 3
    assert ind.rolling_vwap(h, l, c, v, 2).iloc[3] == pytest.approx((tp[2] * 2 + tp[3] * 2) / 4)


def test_kama_follows_trend_and_is_past_only():
    c = pd.Series(np.r_[np.full(20, 100.0), np.linspace(100, 120, 30)])
    k = ind.kama(c, 10, 2, 30)
    assert k.iloc[-1] > 110 and k.iloc[-1] < 120
    k_cut = ind.kama(c.iloc[:35], 10, 2, 30)
    assert np.allclose(k.iloc[:35].to_numpy(), k_cut.to_numpy(), equal_nan=True)


def test_pct_of_price_uses_the_real_price():
    df = pd.DataFrame({"c": [1100.0, 1110.0], "raw_c": [1000.0, 1010.0]})   # adjusted = raw + 100
    assert ind.pct_of_price(df.c.diff(), df, lag=1).iloc[1] == pytest.approx(1.0)


# ---------------------------------------------------------------- calendar periods
def test_period_position_known_dates():
    d = np.array(["2024-05-24", "2024-05-31", "2024-06-03", "2024-07-04"], dtype="datetime64[D]")
    m = period_position(d, "M")
    assert list(m.n_in_period) == [18, 22, 1, 3] and list(m.left) == [4, 0, 18, 19]
    w = period_position(d, "W")
    assert list(w.left) == [0, 0, 4, 1]


# ---------------------------------------------------------------- cash session
def test_rth_filter_keeps_cash_hours_and_carries_rolls():
    t0 = int(pd.Timestamp("2024-03-11 21:58", tz="UTC").timestamp())   # 17:58 New York (DST)
    n = 24 * 60                                                          # to 17:58 the next day
    df = pd.DataFrame({"ts": t0 + 60 * np.arange(n), "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1})
    df["contract"] = np.where(df.ts >= int(pd.Timestamp("2024-03-11 22:00", tz="UTC").timestamp()), "B", "A")
    df["roll"] = (df.contract != df.contract.shift()).to_numpy(); df.loc[0, "roll"] = False
    df = data._add_time_columns(df)
    r = data.session_filter(df, "rth")
    assert len(r) == 390 and r.ny_min.min() >= 570 and r.ny_min.max() < 960
    assert r.roll.sum() == 1 and r.roll.iloc[0] and r.contract.iloc[0] == "B"     # roll at 18:00 -> first cash bar


# ---------------------------------------------------------------- photo strategies
def daily_bars(n=900, seed=3, drift=0.0004):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(drift, 0.012, n)))
    o = c * np.exp(rng.normal(0, 0.003, n))
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 0.006, n)))
    l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 0.006, n)))
    days = pd.bdate_range("2018-01-02", periods=n)
    ts = ((days + pd.Timedelta(hours=14, minutes=30)).tz_localize("UTC") - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)
    df = pd.DataFrame({"ts": ts, "o": o, "h": h, "l": l, "c": c, "v": rng.integers(1000, 5000, n).astype(float),
                       "contract": "X", "roll": False})
    return data._add_time_columns(df)


DAILY_INST = Instrument("D", point_value=1.0, tick=0.01, commission=0.0, slippage_ticks=0, qty_step=0.01)


@pytest.mark.parametrize("path", [p for p in PHOTOS if "a12" not in p.name and "a13" not in p.name], ids=lambda p: p.stem)
def test_daily_photo_strategies_have_no_lookahead_and_trade(path):
    cls = load_strategy(str(path))
    df = daily_bars()
    assert check_lookahead(lambda: cls(), df, DAILY_INST, Settings(capital=100_000)) == []
    t = Engine(df, DAILY_INST, cls(), Settings(capital=100_000)).run()["trades"]
    assert len(t) > 0
    assert set(cls.GRID) <= set(cls().p)                 # the parameter ranges refer to real parameters


def test_squeeze_breakout_has_no_lookahead():
    cls = load_strategy(str(ROOT / "strategies/photos/a12_volatility_squeeze_breakout.py"))
    df = daily_bars(1500, seed=5)
    assert check_lookahead(lambda: cls(lookback=100), df, DAILY_INST, Settings(capital=100_000)) == []


def test_order_flow_strategy_has_no_lookahead():
    cls = load_strategy(str(ROOT / "strategies/photos/a13_order_flow_imbalance.py"))
    df = daily_bars(1200, seed=6)
    rng = np.random.default_rng(7)
    df["buy_vol"] = rng.integers(0, 500, len(df)); df["sell_vol"] = rng.integers(0, 500, len(df))
    assert check_lookahead(lambda: cls(window=100, threshold_ticks=0.5), df, DAILY_INST, Settings(capital=100_000)) == []


def test_signal_strategy_trades_next_open_with_notional_size():
    from engine.strategy_kit import SignalStrategy

    class Once(SignalStrategy):
        def signals(self, df):
            e = pd.Series(False, index=df.index); x = pd.Series(False, index=df.index)
            e.iloc[2] = True; x.iloc[5] = True
            return {"long_entry": e, "long_exit": x}
    df = daily_bars(20)
    t = Engine(df, DAILY_INST, Once(notional=10_000), Settings(capital=100_000)).run()["trades"].iloc[0]
    assert t.entry_px == pytest.approx(df.o.iloc[3]) and t.exit_px == pytest.approx(df.o.iloc[6])
    assert t.qty == pytest.approx(np.floor(10_000 / df.o.iloc[3] / 0.01) * 0.01)
