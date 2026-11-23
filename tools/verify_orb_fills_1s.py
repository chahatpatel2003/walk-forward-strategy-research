"""Check the ORB strategy's 1-minute fill assumptions against NQ 1-SECOND bars (read-only from DATA).

On 1-minute bars the engine has to assume an order of events inside a minute:
  A. several entry orders trigger in the same minute     -> engine takes the trigger nearest the open
  B. a trade's stop and target are both inside a minute  -> engine assumes the stop came first
  C. a trade exits inside its entry minute               -> engine assumes the exit came after the entry
For every such minute this tool looks at the 1-second bars of the traded contract and replays it:
which trigger came first, whether the stop/target order matches, and the trade's P&L if the 1-second
sequence differs. Events that happen inside the SAME second are flagged as unresolvable.

Prices: the engine trades back-adjusted prices; every price is converted back to the raw contract price
(adjusted - adj) before comparing with the 1-second bars.

Usage:  python tools/verify_orb_fills_1s.py [--set rr=3 or_minutes=30] [--start 2021-01-01 --end 2026-08-14]
Writes results/<time>_verify_1s_orb_MNQ/{events.csv, summary.txt}.
"""
import argparse
import ast
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import Engine, Settings, data, get_instrument  # noqa: E402
from engine.calendar import session_close_minute  # noqa: E402
from engine.loader import load_strategy  # noqa: E402

SEC_DIR = data.DATA / "NQ_Nasdaq100_futures/bars_1s_2021-01_to_2026-08-14"
_month_cache: dict = {}


def seconds(t0: int, t1: int, contract: str) -> pd.DataFrame:
    """1-second bars of `contract` with t0 <= ts < t1 (Unix seconds). Prices in points."""
    out = []
    for m in pd.period_range(pd.Timestamp(t0, unit="s"), pd.Timestamp(t1 - 1, unit="s"), freq="M"):
        key = str(m)
        if key not in _month_cache:
            f = SEC_DIR / f"{key}.parquet"
            if not f.exists():
                _month_cache[key] = None
            else:
                x = pd.read_parquet(f, columns=["ts", "symbol", "open_t", "high_t", "low_t", "close_t"])
                x["ts"] = x.ts.astype("int64") // 10**9
                _month_cache[key] = x
        x = _month_cache[key]
        if x is not None:
            out.append(x[(x.ts >= t0) & (x.ts < t1) & (x.symbol == contract)])
    if not out:
        return pd.DataFrame(columns=["ts", "o", "h", "l", "c"])
    s = pd.concat(out).sort_values("ts")
    return pd.DataFrame({"ts": s.ts.values, "o": s.open_t.values / 4, "h": s.high_t.values / 4,
                         "l": s.low_t.values / 4, "c": s.close_t.values / 4})


def first_second(sec: pd.DataFrame, side: int, price: float, kind: str):
    """First second in which a stop (kind='stop') or touch-through limit/target triggers."""
    if not len(sec):
        return None
    hit = (sec.h.values >= price) if side > 0 else (sec.l.values <= price)
    k = np.flatnonzero(hit)
    return int(sec.ts.values[k[0]]) if len(k) else None


def replay_trade(side, trigger_ts, entry_px, sl, tp, qty, pv, costs, slip, tick, flat_ts, contract):
    """Follow one trade second by second from its entry second until stop, target or the flatten time.
    Returns (exit_reason, exit_ts, exit_px, pnl, same_second_flag)."""
    sec = seconds(trigger_ts, flat_ts + 60, contract)
    if not len(sec):
        return None
    for k, row in enumerate(sec.itertuples(index=False)):
        if row.ts >= flat_ts:
            px = row.o - side * slip
            return "eod", row.ts, px, (px - entry_px) * side * qty * pv - costs, False
        sl_hit = (row.l <= sl) if side > 0 else (row.h >= sl)
        tp_hit = (row.h >= tp + tick) if side > 0 else (row.l <= tp - tick)
        same = sl_hit and tp_hit
        if k == 0 and sl_hit:
            # inside the entry second we cannot tell whether the stop came before or after the entry
            same = True
        if sl_hit:
            px = (min(sl, row.o) if side > 0 else max(sl, row.o)) - side * slip
            return "sl", row.ts, px, (px - entry_px) * side * qty * pv - costs, same
        if tp_hit:
            return "tp", row.ts, tp, (tp - entry_px) * side * qty * pv - costs, same
    last = sec.iloc[-1]
    px = last.c - side * slip
    return "end", int(last.ts), px, (px - entry_px) * side * qty * pv - costs, False


def outcome(agree: bool, unresolved: bool) -> str:
    """'unresolved' when the 1-second data can't establish the order (same second, or no data); otherwise
    'agree' / 'disagree'. An unresolved case is never counted as agreement and gets no replay P&L."""
    if unresolved:
        return "unresolved"
    return "agree" if agree else "disagree"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="MNQ")
    ap.add_argument("--set", nargs="*")
    ap.add_argument("--start"); ap.add_argument("--end")
    a = ap.parse_args()
    params = {k: ast.literal_eval(v) for k, v in (x.split("=", 1) for x in a.set or [])}
    ORB = load_strategy(str(ROOT / "strategies/orb.py"))
    strat = ORB(**params)
    inst = get_instrument(a.symbol)
    df = data.load("NQ", a.start, a.end)
    # The engine trades back-adjusted prices; the 1-second bars are raw contract prices.
    # raw = adjusted - adj (the adjustment in force at that minute). P&L differences are unaffected.
    adj_at = dict(zip(df.ts.to_numpy(), df.adj.to_numpy()))
    res = Engine(df, inst, strat, Settings()).run()
    t, amb = res["trades"], res["ambiguous"]
    out = ROOT / "results" / f"{datetime.now():%Y%m%d_%H%M%S}_verify_1s_orb_{a.symbol}"
    out.mkdir(parents=True, exist_ok=True)
    cols = ["minute", "check", "adjustment", "engine", "one_second", "outcome", "engine_pnl", "one_second_pnl", "note"]
    if len(t) == 0:
        pd.DataFrame(columns=cols).to_csv(out / "events.csv", index=False)
        text = f"1-second verification of ORB {strat.p} on {a.symbol}: 0 trades\n\nno ambiguous minutes (no trades)\n"
        (out / "summary.txt").write_text(text)
        print(text + f"saved -> {out}")
        return
    pv, slip, tick = inst.point_value, inst.slippage_ticks * inst.tick, inst.tick
    p = strat.p
    epoch = pd.Timestamp(0, tz="UTC")
    t = t.assign(entry_s=((t.entry_time - epoch) // pd.Timedelta(seconds=1)).astype("int64"),
                 exit_s=((t.exit_time - epoch) // pd.Timedelta(seconds=1)).astype("int64"))
    flat_min = dict(zip(pd.to_datetime(t.entry_tday).dt.date,
                        np.minimum(p["flat_at"], session_close_minute(t.entry_tday.to_numpy()) - 5)))

    def flat_ts(day, ref_ts):
        ny = pd.Timestamp(ref_ts, unit="s", tz="UTC").tz_convert("America/New_York").normalize()
        return int((ny + pd.Timedelta(minutes=int(flat_min[day]) + 1)).tz_convert("UTC").timestamp())

    rows = []
    # ---- A. competing entries
    for ev in (amb[amb.kind == "several_entries_triggered"].itertuples(index=False) if len(amb) else []):
        m0 = int(ev.ts)
        tr = t[t.entry_s == m0]
        contract = tr.contract.iloc[0] if len(tr) else df.contract[df.ts == m0].iloc[0]
        sec = seconds(m0, m0 + 60, contract)
        off = adj_at[m0]
        cands = [(s_, k_, px - off) for s_, k_, px in [ev.detail["chosen"]] + ev.detail["others"]]
        firsts = [first_second(sec, s_, px, k_) for s_, k_, px in cands]
        valid = sorted([(f, c) for f, c in zip(firsts, cands) if f is not None], key=lambda x: x[0])
        tie = len(valid) > 1 and valid[0][0] == valid[1][0]
        first_1s = valid[0][1] if valid else None
        unresolved = tie or first_1s is None
        agree = first_1s == cands[0]
        row = {"minute": pd.Timestamp(m0, unit="s", tz="UTC"), "check": "A: which entry first", "adjustment": off,
               "engine": f"{'long' if cands[0][0] > 0 else 'short'} @ {cands[0][2]} (raw)",
               "one_second": ("no 1-second data / no trigger" if first_1s is None else
                              f"{'long' if first_1s[0] > 0 else 'short'} @ {first_1s[2]}" + (" (same second as another trigger)" if tie else "")),
               "outcome": outcome(agree, unresolved), "engine_pnl": round(tr.pnl.iloc[0], 2) if len(tr) else None,
               "one_second_pnl": None, "note": ""}
        if len(tr) and not unresolved:
            if agree:
                row["one_second_pnl"] = row["engine_pnl"]
                row["note"] = "same entry; its exit is checked separately if ambiguous"
            else:
                side, _, price = first_1s
                other = [c for c in cands if c != first_1s][0][2]
                entry = price + side * slip
                risk = abs(entry - other)
                qty = math.floor(p["risk_usd"] / (risk * pv) + 1e-9)
                if qty >= 1:
                    rr = replay_trade(side, valid[0][0], entry, other, entry + side * p["rr"] * risk, qty, pv,
                                      2 * inst.commission * qty, slip, tick,
                                      flat_ts(pd.Timestamp(tr.entry_tday.iloc[0]).date(), m0), contract)
                    if rr and not rr[4]:
                        row["one_second_pnl"] = round(rr[3], 2)
                        row["note"] = f"1-second replay of the other side: {rr[0]}"
                    else:
                        row["outcome"], row["note"] = "unresolved", "replay of the other side not resolvable"
        rows.append(row)
    # ---- B and C. stop/target order, and exits inside the entry minute
    exit_amb = set(int(x) for x in amb.ts[amb.kind == "stop_and_target_same_bar"]) if len(amb) else set()
    check = t[(t.exit_s.isin(exit_amb)) | ((t.bars == 0) & t.exit_reason.isin(["sl", "tp"]))]
    for e in check.itertuples(index=False):
        side = 1 if e.side == "long" else -1
        off = adj_at[int(e.entry_s)]
        entry, sl_, tp_ = e.entry_px - off, e.sl - off, e.tp - off
        sec = seconds(int(e.entry_s), int(e.entry_s) + 60, e.contract)
        trig = first_second(sec, side, entry - side * slip, "stop")
        rr = None if trig is None else replay_trade(side, trig, entry, sl_, tp_, e.qty, pv, e.costs, slip, tick,
                                                     flat_ts(pd.Timestamp(e.entry_tday).date(), int(e.entry_s)), e.contract)
        unresolved = rr is None or rr[4]
        rows.append({"minute": e.exit_time,
                     "check": "C: exit in entry minute" if e.bars == 0 else "B: stop and target in one minute",
                     "adjustment": off, "engine": f"{e.exit_reason} @ {e.exit_px - off} (raw)",
                     "one_second": "no 1-second data / no trigger" if rr is None else
                                   f"{rr[0]} @ {rr[2]}" + (" (same second)" if rr[4] else ""),
                     "outcome": outcome(rr is not None and rr[0] == e.exit_reason, unresolved),
                     "engine_pnl": round(e.pnl, 2), "one_second_pnl": None if unresolved else round(rr[3], 2), "note": ""})
    ev = pd.DataFrame(rows, columns=cols)
    ev.to_csv(out / "events.csv", index=False)
    lines = [f"1-second verification of ORB {strat.p} on {a.symbol}: {len(t)} trades", ""]
    if len(ev):
        for c, g in ev.groupby("check"):
            n = g.outcome.value_counts()
            lines.append(f"{c}: {len(g)} cases | agree {n.get('agree', 0)} | disagree {n.get('disagree', 0)} | "
                         f"unresolved (same second or no data) {n.get('unresolved', 0)}")
            res_ = g[g.outcome != "unresolved"].dropna(subset=["engine_pnl", "one_second_pnl"])
            if len(res_):
                lines.append(f"    resolved cases only: engine P&L {res_.engine_pnl.sum():,.2f} | 1-second replay "
                             f"{res_.one_second_pnl.sum():,.2f} | difference {res_.one_second_pnl.sum() - res_.engine_pnl.sum():+,.2f}")
        lines += ["", ev.to_string(index=False)]
    else:
        lines.append("no ambiguous minutes")
    (out / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[:12]))
    print(f"saved -> {out}")

if __name__ == "__main__":
    main()
