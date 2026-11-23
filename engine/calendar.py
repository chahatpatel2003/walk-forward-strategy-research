"""US exchange calendar (NYSE rules; CME index/metals futures follow the same holidays and early closes
closely). Published in advance by the exchanges, so using it in a strategy is NOT look-ahead.

Holidays: New Year, MLK Day, Presidents Day, Good Friday, Memorial Day, Juneteenth (from 2022),
Independence Day, Labor Day, Thanksgiving, Christmas, plus one-off closures listed below.
Early closes (13:00 New York): the day after Thanksgiving; July 3 and Dec 24 when they fall Mon-Thu.
"""
from functools import lru_cache

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay, USMartinLutherKingJr,
                                    USMemorialDay, USPresidentsDay, USThanksgivingDay, nearest_workday)

SPECIAL_CLOSURES = ["2012-10-29", "2012-10-30",   # Hurricane Sandy
                    "2018-12-05",                 # President G.H.W. Bush funeral
                    "2025-01-09"]                 # President Carter funeral
EARLY_CLOSE_MIN = 13 * 60                         # 13:00 New York


def _no_saturday_new_year(dt):
    # NYSE does not close on Friday Dec 31 when Jan 1 is a Saturday
    return None if dt.weekday() == 5 else nearest_workday(dt)


class _NYSE(AbstractHolidayCalendar):
    rules = [Holiday("NewYear", month=1, day=1, observance=_no_saturday_new_year),
             USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
             Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
             Holiday("July4", month=7, day=4, observance=nearest_workday), USLaborDay, USThanksgivingDay,
             Holiday("Christmas", month=12, day=25, observance=nearest_workday)]


@lru_cache(maxsize=None)
def holidays(first_year: int = 2010, last_year: int = 2030) -> frozenset:
    h = _NYSE().holidays(f"{first_year}-01-01", f"{last_year}-12-31")
    days = {d.date() for d in h} | {pd.Timestamp(x).date() for x in SPECIAL_CLOSURES}
    return frozenset(days)


@lru_cache(maxsize=None)
def early_closes(first_year: int = 2010, last_year: int = 2030) -> frozenset:
    out = set()
    for y in range(first_year, last_year + 1):
        tg = USThanksgivingDay.dates(f"{y}-01-01", f"{y}-12-31")[0]
        out.add((tg + pd.Timedelta(days=1)).date())
        for m, d in ((7, 3), (12, 24)):
            day = pd.Timestamp(y, m, d)
            if day.weekday() <= 3:                    # Mon-Thu
                out.add(day.date())
    return frozenset(out - holidays(first_year, last_year))


def session_close_minute(days) -> np.ndarray:
    """Day-session close (minutes after midnight, New York) for each date: 960 (16:00), or 780 (13:00) on
    early-close days AND on exchange holidays (CME index and metals futures still trade on most US holidays,
    but halt at 13:00 New York)."""
    short = early_closes() | holidays()
    d = pd.to_datetime(np.asarray(days)).date
    return np.array([EARLY_CLOSE_MIN if x in short else 16 * 60 for x in d], dtype=np.int32)


def trading_days(start, end) -> pd.DatetimeIndex:
    """Weekdays that are not exchange holidays."""
    h = holidays()
    b = pd.bdate_range(start, end)
    return b[[x.date() not in h for x in b]]


@lru_cache(maxsize=None)
def _cal_days() -> np.ndarray:
    return trading_days("2010-01-01", "2030-12-31").values.astype("datetime64[D]")


def period_position(days, freq: str = "M") -> pd.DataFrame:
    """For each date (trading days and futures holiday sessions alike), its place in its calendar month
    ('M') or ISO week ('W') according to the exchange calendar (known in advance, so not look-ahead):
      n_in_period   trading days in the period up to and including this date
      left          trading days remaining in the period after this date (0 = last trading day)"""
    cal = _cal_days()
    d = np.asarray(days).astype("datetime64[D]")
    if freq == "M":
        key_cal = cal.astype("datetime64[M]")
        key_d = d.astype("datetime64[M]")
    else:
        # ISO week key: the Monday of the week
        key_cal = cal - ((cal.astype("datetime64[D]").view("int64") - 4) % 7).astype("timedelta64[D]")
        key_d = d - ((d.view("int64") - 4) % 7).astype("timedelta64[D]")
    upto = np.searchsorted(cal, d, "right")                       # calendar days <= date
    start = np.searchsorted(key_cal, key_d, "left")              # first calendar day of the period
    end = np.searchsorted(key_cal, key_d, "right")               # one past its last
    return pd.DataFrame({"n_in_period": upto - start, "left": end - upto})
