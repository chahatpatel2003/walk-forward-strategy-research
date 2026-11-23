"""tools/single_account.py: one account, fixed % risk of the balance, compounding."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import single_account as sa  # noqa: E402


def trades(rows):
    t = pd.DataFrame(rows, columns=["entry_time", "exit_time", "side", "qty", "entry_px", "pnl_gross", "costs", "stop_dist"])
    t["entry_tday"] = pd.to_datetime(t.entry_time).dt.normalize()
    t["exit_tday"] = pd.to_datetime(t.exit_time).dt.normalize()
    return t


def test_size_is_two_percent_of_the_balance_and_compounds(monkeypatch):
    days = pd.bdate_range("2024-01-01", "2024-01-31")
    monkeypatch.setattr(sa, "daily_close", lambda m: pd.Series(100.0, index=days))
    monkeypatch.setattr(sa, "daily_raw", lambda m: pd.Series(100.0, index=days))
    # MGC: $10/point. Stop 2 points = $20 per contract. Original trades were 1 contract: +$100 and +$50 per contract.
    t = trades([("2024-01-02 15:00", "2024-01-03 15:00", "long", 1, 100.0, 101.5, 1.5, 2.0),
                ("2024-01-04 15:00", "2024-01-05 15:00", "long", 1, 100.0, 51.5, 1.5, 2.0)])
    out = sa.simulate([{"name": "x", "market": "MGC", "trades": t}], 10_000.0, 2.0)
    q = out["trades"].new_qty.tolist()
    assert q[0] == 10                       # $200 / $20 = 10 contracts
    assert q[1] == 11                       # balance 10,000 + 10 x 100 = 11,000 -> $220 / $20 = 11
    assert out["summary"]["final_equity"] == pytest.approx(10_000 + 10 * 100 + 11 * 50)


def test_a_trade_too_small_for_one_contract_is_skipped(monkeypatch):
    days = pd.bdate_range("2024-01-01", "2024-01-31")
    monkeypatch.setattr(sa, "daily_close", lambda m: pd.Series(100.0, index=days))
    monkeypatch.setattr(sa, "daily_raw", lambda m: pd.Series(100.0, index=days))
    t = trades([("2024-01-02 15:00", "2024-01-03 15:00", "long", 1, 100.0, 100.0, 1.5, 50.0)])   # $500 per contract
    out = sa.simulate([{"name": "x", "market": "MGC", "trades": t}], 10_000.0, 2.0)
    assert out["summary"]["trades_taken"] == 0 and sum(out["summary"]["skipped"].values()) == 1


def test_a_trade_opened_and_closed_in_one_bar_reaches_the_balance(monkeypatch):
    days = pd.bdate_range("2024-01-01", "2024-01-31")
    monkeypatch.setattr(sa, "daily_close", lambda m: pd.Series(100.0, index=days))
    monkeypatch.setattr(sa, "daily_raw", lambda m: pd.Series(100.0, index=days))
    t = trades([("2024-01-02 15:00", "2024-01-02 15:00", "long", 1, 100.0, 101.5, 1.5, 2.0),     # same bar
                ("2024-01-04 15:00", "2024-01-05 15:00", "long", 1, 100.0, 51.5, 1.5, 2.0)])
    out = sa.simulate([{"name": "x", "market": "MGC", "trades": t}], 10_000.0, 2.0)
    assert out["trades"].new_qty.tolist() == [10, 11]


def test_position_value_can_be_capped_at_a_multiple_of_the_balance(monkeypatch):
    days = pd.bdate_range("2024-01-01", "2024-01-31")
    monkeypatch.setattr(sa, "daily_close", lambda m: pd.Series(100.0, index=days))
    monkeypatch.setattr(sa, "daily_raw", lambda m: pd.Series(100.0, index=days))
    # MGC $10/pt at 100 -> $1,000 per contract. Stop 0.5 pt = $5/contract: 2% of 10,000 -> 40 contracts ($40,000).
    t = trades([("2024-01-02 15:00", "2024-01-03 15:00", "long", 1, 100.0, 0.0, 1.5, 0.5)])
    assert sa.simulate([{"name": "x", "market": "MGC", "trades": t}], 10_000.0, 2.0)["trades"].new_qty[0] == 40
    capped = sa.simulate([{"name": "x", "market": "MGC", "trades": t}], 10_000.0, 2.0, max_lev=2.0)["trades"]
    assert capped.new_qty[0] == 20                         # $20,000 = 2 x the balance
