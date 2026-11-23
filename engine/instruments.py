"""Contract specifications and default trading costs.

Edit the cost numbers to match YOUR broker. Everything is per 1 contract / 1 lot.
  point_value : $ made or lost when price moves 1.0 point, per 1 contract/lot
  tick        : minimum price increment
  commission  : $ per side (charged on entry AND on exit), per contract/lot
  slippage_ticks : ticks of adverse slippage on market and stop fills (not limits)
  qty_step    : smallest tradable size (1 contract for futures, 0.01 lot for CFDs)
  uses_bid_ask: True when the data has real bid/ask, so the real spread is paid instead of a fixed one
  spread      : fixed spread in points, used only when the data has no bid/ask
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Instrument:
    name: str
    point_value: float
    tick: float
    commission: float
    slippage_ticks: float
    qty_step: float
    uses_bid_ask: bool = False
    spread: float = 0.0
    data_key: str = ""          # which dataset to load (see data.py)

    def with_costs(self, **kw):
        return replace(self, **kw)


INSTRUMENTS = {
    # CME futures: NQ $20/pt (tick 0.25 = $5), MNQ $2/pt. COMEX GC $100/pt (tick 0.10 = $10), MGC $10/pt.
    "NQ":  Instrument("NQ",  20.0,  0.25, 2.25, 1, 1, data_key="NQ"),
    "MNQ": Instrument("MNQ",  2.0,  0.25, 0.75, 1, 1, data_key="NQ"),
    "GC":  Instrument("GC", 100.0,  0.10, 2.25, 1, 1, data_key="GC"),
    "MGC": Instrument("MGC", 10.0,  0.10, 0.75, 1, 1, data_key="GC"),
    # Spot gold CFD: 1 lot = 100 oz, so $100 per $1 move. Real Dukascopy bid/ask spread is charged.
    # Commission 0 by default (spread-only account); raw-spread accounts often charge ~$3.5/lot/side.
    "XAUUSD": Instrument("XAUUSD", 100.0, 0.01, 0.0, 0, 0.01, uses_bid_ask=True, data_key="XAUUSD"),
    # Nasdaq CFD: contract size varies by broker ($1/pt per lot is common). Mid-price data only,
    # so a fixed spread is charged: 1.2 pts is about the measured median in US cash hours (2015-2021).
    "NAS100": Instrument("NAS100", 1.0, 0.25, 0.0, 0, 0.01, spread=1.2, data_key="NAS100"),
}


def get(name: str) -> Instrument:
    try:
        return INSTRUMENTS[name.upper()]
    except KeyError:
        raise KeyError(f"unknown instrument {name!r}; choose from {list(INSTRUMENTS)}") from None
