"""Build the markdown tables of PHOTO_STUDY_RESULTS.md straight from results/PHOTO_STUDY/study_rows.csv
(no number is typed by hand). Usage: python tools/photo_report_tables.py > tables.md"""
import json

import pandas as pd

ROWS = "/Volumes/T9/BACKTESTING/results/PHOTO_STUDY/study_rows.csv"
NAMES = {"A01": "RSI+EMA+VWAP pullback", "A02": "Stochastic+KAMA+VWAP", "A03": "Williams %R+EMA+VWAP",
         "A04": "RSI+EMA50+VWAP", "A05": "Z-score mean reversion (long+short)", "A06": "Rubber Band",
         "A07": "MFI reversal", "A08": "Weekly RSI", "A09": "Turn of the month", "A10": "Faber 10-month MA",
         "A11": "Time-series momentum", "A12": "Volatility squeeze breakout (15m)", "A13": "Order-flow imbalance (1m, NQ)",
         "B01": "Gold futures vs spot pair (1h)"}


def comparison_counts(r: pd.DataFrame) -> dict:
    """Out-of-sample strategy vs buy-and-hold, counted only on rows that have both figures."""
    both = r.dropna(subset=["wf_oos_max_dd", "buy_hold_oos_max_dd", "wf_oos_net", "buy_hold_oos_net"])
    return {"both": int(len(both)),
            "smaller_dd": int((both.wf_oos_max_dd > both.buy_hold_oos_max_dd).sum()),     # drawdowns are negative
            "larger_dd": int((both.wf_oos_max_dd < both.buy_hold_oos_max_dd).sum()),
            "less_profit": int((both.wf_oos_net < both.buy_hold_oos_net).sum()),
            "more_profit": int((both.wf_oos_net > both.buy_hold_oos_net).sum())}


BREACH_COLUMNS = ["capital_exhausted_on", "wf_capital_exhausted_on", "stress_all_capital_exhausted_on"]


def survived(r: pd.DataFrame) -> pd.Series:
    """True where the account never hit $0: full history, walk-forward OOS, the combined stress scenario AND every
    individual stress scenario (a scenario that breached and later recovered to a profit still hit $0)."""
    ok = pd.Series(True, index=r.index)
    for c in BREACH_COLUMNS:
        if c in r:
            ok &= r[c].isna() | (r[c].astype(str).str.strip() == "")
    if "stress_scenarios_breached" in r:
        ok &= pd.to_numeric(r.stress_scenarios_breached, errors="coerce").fillna(0) == 0
    return ok


def robust_mask(r: pd.DataFrame) -> pd.Series:
    """'Passed all key checks': profitable out of sample (PF >= 1.2), Monte Carlo chance of a loss < 10%, still
    profitable under combined execution stress AND in every single tested execution scenario, the account never hit
    $0 (a positive balance after a forced liquidation is not a pass), and at most one checklist item not passed.
    (Rows saved before the per-scenario and checklist-count columns existed fall back to the earlier rule.)"""
    ok = (r.wf_oos_net > 0) & (r.wf_oos_pf >= 1.2) & (r.mc_prob_loss_pct < 10) & (r.stress_all_net > 0) & survived(r)
    if "stress_worst_net" in r:
        ok &= r.stress_worst_net > 0
    if "checks_total" in r and "stress_worst_net" in r:
        ok &= (r.checks_total - r.checks_passed) <= 1
    elif "checks_passed" in r:
        ok &= r.checks_passed >= 10
    return ok


def main():
    r = pd.read_csv(ROWS)
    r = r[r.error.isna()]
    r["code"] = r.strategy.str[:3].str.upper()
    r["robust"] = robust_mask(r)
    g = r.groupby("code").agg(runs=("market", "size"), profitable=("net", lambda x: int((x > 0).sum())),
                              wf=("wf_oos_net", lambda x: int(x.notna().sum())), oos=("wf_oos_net", lambda x: int((x > 0).sum())),
                              robust=("robust", "sum"), pf=("pf", "median"), oos_pf=("wf_oos_pf", "median"), trades=("trades", "median"))
    g.insert(0, "strategy", [NAMES[c] for c in g.index])
    g.columns = ["strategy", "runs", "profitable (full history)", "walk-forward possible", "profitable out-of-sample",
                 "passed all key checks", "median PF", "median OOS PF", "median trades"]
    print("<!--SUMMARY-->"); print(g.reset_index().round(2).to_markdown(index=False))
    cols = ["code", "market", "session", "trades", "net", "pf", "max_dd", "time_in_market_pct", "buy_hold_net", "buy_hold_max_dd",
            "wf_oos_net", "wf_oos_pf", "wf_oos_max_dd", "buy_hold_oos_net", "buy_hold_oos_max_dd", "mc_prob_loss_pct", "checks_passed"]
    rb = r[r.robust].sort_values("wf_oos_net", ascending=False)[cols].round(1)
    rb.columns = ["code", "market", "bars", "trades", "net $", "PF", "max DD $", "% time in market", "buy&hold net $",
                  "buy&hold max DD $", "OOS net $", "OOS PF", "OOS max DD $", "buy&hold OOS $", "buy&hold OOS max DD $", "MC loss %", "checks"]
    print("<!--ROBUST-->"); print(rb.to_markdown(index=False))
    full = r.sort_values(["code", "market", "session"])[["code", "market", "session", "trades", "net", "pf", "win_pct", "max_dd",
                                                         "buy_hold_net", "wf_oos_net", "wf_oos_pf", "buy_hold_oos_net",
                                                         "mc_prob_loss_pct", "stress_all_net", "checks_passed"]].round(2)
    print("<!--FULL-->"); print(full.to_markdown(index=False))
    c = comparison_counts(r)
    larger = r.dropna(subset=["wf_oos_max_dd", "buy_hold_oos_max_dd"])
    larger = larger[larger.wf_oos_max_dd < larger.buy_hold_oos_max_dd][["code", "market", "session", "wf_oos_max_dd", "buy_hold_oos_max_dd"]]
    larger.columns = ["code", "market", "bars", "strategy OOS max DD $", "buy&hold OOS max DD $"]
    print("<!--COMPARE-->", json.dumps(c))
    print("<!--LARGERDD-->"); print(larger.round(2).to_markdown(index=False))
    if "stress_scenarios_breached" not in r:
        r["stress_scenarios_breached"] = 0
    broke = r[~survived(r) | (r.stress_scenarios_breached.fillna(0) > 0)]
    cols = ["code", "market", "session", "capital_exhausted_on", "wf_capital_exhausted_on", "stress_scenarios_breached",
            "stress_all_capital_exhausted_on", "net", "wf_oos_net"]
    cols = [c for c in cols if c in broke]
    print("<!--BROKE-->"); print(broke[cols].fillna("").to_markdown(index=False) if len(broke) else "(none)")
    print("<!--COUNTS-->", len(r), int(r.robust.sum()))


if __name__ == "__main__":
    main()
