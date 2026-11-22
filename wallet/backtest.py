"""Backtest exit rules on past calls. Usage: python3 -m wallet.backtest [--offline-demo] [--out wallet/state/backtest_report.md]
Entry = first candle at/after call time + latency, entry price = that candle's OPEN (+ slippage via fee_pct).
Calls with no candle history (dead/rugged pools) are bounded from calls.csv and labeled."""
import argparse, itertools, os, statistics as st, sys, time
from .calls import load_calls, call_ts, ROOT
from .rules import ExitRules, simulate

HORIZON_S = 48 * 3600
LATENCIES = [0, 60, 180, 300]
GRID = {
    "hold (no rules)": dict(tp=[], stop=None, trail_activate=None, time_stop_s=None),
    "tp2x all": dict(tp=[(2.0, 1.0)], stop=None, trail_activate=None, time_stop_s=None),
    "tp1.5x all": dict(tp=[(1.5, 1.0)], stop=None, trail_activate=None, time_stop_s=None),
    "stop0.6 only": dict(tp=[], stop=0.6, trail_activate=None, time_stop_s=None),
    "stop0.7 + tp2x": dict(tp=[(2.0, 1.0)], stop=0.7, trail_activate=None, time_stop_s=None),
    "stop0.6 + tp2x half + trail": dict(tp=[(2.0, 0.5)], stop=0.6, trail_activate=2.0, trail_pct=0.35, time_stop_s=None),
    "stop0.5 + tp3x half + trail": dict(tp=[(3.0, 0.5)], stop=0.5, trail_activate=3.0, trail_pct=0.35, time_stop_s=None),
    "stop0.6 + tp2x + time 1h": dict(tp=[(2.0, 1.0)], stop=0.6, trail_activate=None, time_stop_s=3600),
    "stop0.6 + tp2x + time 4h": dict(tp=[(2.0, 1.0)], stop=0.6, trail_activate=None, time_stop_s=14400),
}


def to_mult(raw, entry_ts):
    """raw [(ts,o,h,l,c)] USD -> multiples of the entry candle's open, starting at entry. None if no entry candle."""
    ent = [x for x in raw if x[0] >= entry_ts]
    if not ent or ent[0][1] <= 0:
        return None
    p0 = ent[0][1]
    return [(t - ent[0][0], o / p0, h / p0, l / p0, c / p0) for t, o, h, l, c in ent]


def fetch_all(calls):
    from . import data
    hist = {}
    for r in calls:
        try:
            pool = data.best_pool(r["contract"])
            ts = call_ts(r)
            hist[r["id"]] = data.candles(pool["pairAddress"], ts, min(ts + HORIZON_S, time.time())) if pool else []
        except Exception as e:
            print(f"[warn] call {r['id']} {r['token']}: {type(e).__name__}: {e}", file=sys.stderr)
            hist[r["id"]] = []
    return hist


def bound_from_csv(r):
    """No candles: rugged -> total loss; else (current, peak) known only. Returns multiple range (lo, hi) before costs."""
    if r["status"] == "rugged":
        return 0.0, 0.0
    return float(r["multiple"] or 0), float(r["peak_mcap"] or 0) / float(r["mcap_at_call"])


def run(calls, hist):
    rows = []
    for name, kw in GRID.items():
        for lat in LATENCIES:
            res, nobars = [], 0
            for r in calls:
                m = to_mult(hist.get(r["id"], []), call_ts(r) + lat)
                if m is None:
                    nobars += 1
                    lo, _hi = bound_from_csv(r)
                    res.append((r, lo, True)); continue  # conservative: unknown path -> assume current/lost
                res.append((r, simulate(m, ExitRules(**kw)).multiple, False))
            xs = [x for _, x, _ in res]
            rows.append(dict(rule=name, latency=lat, n=len(xs), nobars=nobars, mean=st.mean(xs), median=st.median(xs),
                             total=sum(xs) - len(xs), win=sum(x > 1 for x in xs) / len(xs), worst=min(xs),
                             no_best=(sum(xs) - max(xs)) / (len(xs) - 1) if len(xs) > 1 else float("nan")))
    return rows


def report(rows, calls, hist):
    L = ["# Wallet bot backtest", "", f"{len(calls)} calls; {sum(1 for r in calls if hist.get(r['id']))} with candle history, rest bounded from calls.csv (conservative).",
         "Multiples are per 1.0 SOL staked equally per call, after 1% per-side cost. n is tiny: treat as sanity check, not an edge.", "",
         "| rule | latency s | mean x | median x | win% | worst x | mean excl. best call | no-candle calls |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['rule']} | {r['latency']} | {r['mean']:.2f} | {r['median']:.2f} | {r['win']*100:.0f} | {r['worst']:.2f} | {r['no_best']:.2f} | {r['nobars']} |")
    return "\n".join(L) + "\n"


def demo_hist(calls):
    """Synthetic candles so the pipeline can be exercised offline (NOT real results)."""
    import random
    rnd = random.Random(1); h = {}
    for r in calls:
        ts, p, out = int(call_ts(r)), 1.0, []
        for i in range(600):
            o = p; p *= 1 + rnd.gauss(0, 0.04); out.append((ts + 60 * i, o, max(o, p) * 1.01, min(o, p) * 0.99, p))
        h[r["id"]] = out
    return h


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--offline-demo", action="store_true"); ap.add_argument("--out", default=os.path.join(ROOT, "wallet/state/backtest_report.md"))
    a = ap.parse_args()
    calls = load_calls()
    hist = demo_hist(calls) if a.offline_demo else fetch_all(calls)
    txt = report(run(calls, hist), calls, hist)
    if a.offline_demo:
        txt = "**SYNTHETIC DATA: pipeline check only, not real results.**\n\n" + txt
    os.makedirs(os.path.dirname(a.out), exist_ok=True); open(a.out, "w").write(txt); print(txt)
