"""tools/session_exit.py: close every saved trade at the New York cash close."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools")); sys.path.insert(0, str(Path(__file__).resolve().parent))
import session_exit as se  # noqa: E402
from test_audit9 import frame_at  # noqa: E402


def minutes(day, start, n, px):
    return [str(pd.Timestamp(f"{day} {start}") + pd.Timedelta(minutes=k)) for k in range(n)], [px] * n


def ledger(entry, exit_, side="long", px=100.0):
    et = pd.Timestamp(entry, tz="America/New_York").tz_convert("UTC"); xt = pd.Timestamp(exit_, tz="America/New_York").tz_convert("UTC")
    return pd.DataFrame({"entry_time": [et], "exit_time": [xt], "side": [side], "qty": [2.0], "entry_px": [px], "exit_px": [px],
                         "pnl_gross": [0.0], "costs": [0.0], "rolls": [0], "exit_reason": ["signal"],
                         "entry_tday": [et.tz_convert(None).normalize()], "exit_tday": [xt.tz_convert(None).normalize()]})


@pytest.fixture
def two_days():
    a, pa = minutes("2024-01-08", "15:50", 15, 100.0)       # 15:50 .. 16:04
    b, pb = minutes("2024-01-09", "15:50", 15, 110.0)
    pa[9] = (100.0, 105.0, 100.0, 104.0)                    # the 15:59 bar closes at 104
    return frame_at(a + b, pa + pb)


def test_an_overnight_trade_is_closed_at_the_close_of_its_entry_day(two_days):
    out = se.to_session_end(ledger("2024-01-08 15:51", "2024-01-09 15:55"), "MGC", two_days).iloc[0]
    assert out.exit_reason == "session_end" and out.exit_px == pytest.approx(104.0 - 0.1)       # MGC 1 tick slippage
    assert pd.Timestamp(out.exit_time).tz_convert("America/New_York").strftime("%H:%M") == "15:59"
    assert out.costs == pytest.approx(2 * 0.75 * 2.0)                                           # entry + exit commission


def test_a_trade_that_already_exits_before_the_close_is_unchanged(two_days):
    out = se.to_session_end(ledger("2024-01-08 15:51", "2024-01-08 15:55"), "MGC", two_days).iloc[0]
    assert out.exit_reason == "signal" and not out.cut_at_session_end


def test_a_short_exits_on_the_ask_side(two_days):
    out = se.to_session_end(ledger("2024-01-08 15:51", "2024-01-09 15:55", side="short"), "MGC", two_days).iloc[0]
    assert out.exit_px == pytest.approx(104.0 + 0.1)
