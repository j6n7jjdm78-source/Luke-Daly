"""Scout (S/R levels + rejection setup) and a paper simulator for gold proxy data. Stdlib only.
Paper only. No lookahead: levels use only closed 1h bars; entry is the NEXT bar open after a closed signal bar.
Run: python3 -I bot/lab.py
"""
import csv, json, os, random, statistics
from datetime import datetime, timezone

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
SECS = {"5m": 300, "15m": 900, "1h": 3600}

# ---- starting values to TEST (not facts) ----
P = dict(lookback=120, pivot=3, cluster=1.50, min_touches=3, atr_mult=0.25, buffer=0.30,
         max_stop=3.50, min_stop=0.50, rr=1.5, h_from=7, h_to=16, max_trades_day=10,
         max_losses_day=2, daily_loss=7.0)

def load(tf):
    rows = []
    with open(os.path.join(D, f"paxgusd_{tf}.csv")) as f:
        for r in csv.DictReader(f):
            rows.append(dict(ts=int(r["ts"]), o=float(r["open"]), h=float(r["high"]), l=float(r["low"]), c=float(r["close"])))
    return rows

H1, M15 = load("1h"), load("15m")

def atr15(t, n=14):
    bars = [b for b in M15 if b["ts"] + 900 <= t][-(n + 1):]
    if len(bars) < n + 1: return 0.5
    trs = [max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"])) for p, b in zip(bars, bars[1:])]
    return sum(trs) / len(trs)

_cache = {}
def levels_at(t):
    """Valid S/R levels from closed 1h bars only. Pivot needs `pivot` closed bars on the right."""
    key = t // 3600
    if key in _cache: return _cache[key]
    h = [b for b in H1 if b["ts"] + 3600 <= t][-P["lookback"]:]
    k, pts = P["pivot"], []
    for i in range(k, len(h) - k):
        w = h[i - k:i + k + 1]
        if h[i]["h"] == max(x["h"] for x in w): pts.append(h[i]["h"])
        if h[i]["l"] == min(x["l"] for x in w): pts.append(h[i]["l"])
    pts.sort(); cl = []
    for p in pts:
        if cl and p - cl[-1][-1] <= P["cluster"]: cl[-1].append(p)
        else: cl.append([p])
    lv = [(sum(c) / len(c), len(c)) for c in cl if len(c) >= P["min_touches"]]
    z = P["atr_mult"] * atr15(t)
    _cache[key] = (lv, z)
    return _cache[key]

def signal(bars, i, tf):
    """Rejection bounce on closed bar i. Returns (side, stop_ref, level, next_levels) or None."""
    b = bars[i]; t = b["ts"] + SECS[tf]
    lv, z = levels_at(t)
    if not lv: return None
    near = sorted(lv, key=lambda x: abs(x[0] - b["c"]))[:3]
    for L, n in near:
        if b["l"] <= L + z and b["l"] >= L - 2 * z and b["c"] > L + z and b["c"] > b["o"]:
            return ("long", b["l"] - P["buffer"], L, [x[0] for x in lv if x[0] > b["c"]])
        if b["h"] >= L - z and b["h"] <= L + 2 * z and b["c"] < L - z and b["c"] < b["o"]:
            return ("short", b["h"] + P["buffer"], L, [x[0] for x in lv if x[0] < b["c"]])
    return None

def simulate(bars, tf, spread, slip, direction=None, rng=None, only=None):
    """Paper account, 0.01 lot = 1 oz so P&L in USD = price move. Returns trades, skipped counts."""
    trades, skipped = [], dict(wide=0, tiny=0, hours=0, day_limit=0, busy=0)
    busy_until, day, dn, dl, dpnl = -1, None, 0, 0, 0.0
    for i in range(len(bars) - 2):
        if i < busy_until: continue
        s = signal(bars, i, tf)
        if only is not None and i not in only: s = None if only is not None and s is None else s
        if not s: continue
        side, stop, L, nxt = s
        if direction == "random": side = rng.choice(["long", "short"])
        e = bars[i + 1]; hr = datetime.fromtimestamp(e["ts"], timezone.utc)
        d = hr.date()
        if d != day: day, dn, dl, dpnl = d, 0, 0, 0.0
        if not (P["h_from"] <= hr.hour < P["h_to"]): skipped["hours"] += 1; continue
        if dn >= P["max_trades_day"] or dl >= P["max_losses_day"] or dpnl <= -P["daily_loss"]:
            skipped["day_limit"] += 1; continue
        cost = spread / 2 + slip
        entry = e["o"] + cost if side == "long" else e["o"] - cost
        if direction == "random":
            dist = abs(s[1] - bars[i]["c"])  # same stop distance as real setup, random direction
            stop = entry - dist if side == "long" else entry + dist
        dist = abs(entry - stop)
        if dist > P["max_stop"]: skipped["wide"] += 1; continue
        if dist < P["min_stop"]: skipped["tiny"] += 1; continue
        tgt = entry + P["rr"] * dist if side == "long" else entry - P["rr"] * dist
        if direction != "random":
            if side == "long" and nxt:
                n1 = min(nxt) - cost
                if entry + 0.5 * dist < n1 < tgt: tgt = n1
            if side == "short" and nxt:
                n1 = max(nxt) + cost
                if tgt < n1 < entry - 0.5 * dist: tgt = n1
        exitp, why, j = None, None, i + 1
        while j < len(bars):
            b = bars[j]
            if datetime.fromtimestamp(b["ts"], timezone.utc).hour >= P["h_to"] and j > i + 1:
                exitp = b["o"] - cost if side == "long" else b["o"] + cost; why = "time"; break
            if side == "long":
                if b["l"] <= stop: exitp, why = min(stop, b["o"]) - cost, "stop"; break
                if b["h"] >= tgt: exitp, why = tgt - cost, "target"; break
            else:
                if b["h"] >= stop: exitp, why = max(stop, b["o"]) + cost, "stop"; break
                if b["l"] <= tgt: exitp, why = tgt + cost, "target"; break
            j += 1
        if exitp is None: break  # trade still open at end of data: not counted
        pnl = (exitp - entry) if side == "long" else (entry - exitp)
        trades.append(dict(time=hr.isoformat(), side=side, entry=round(entry, 2), stop=round(stop, 2),
                           exit=round(exitp, 2), why=why, pnl=round(pnl, 2), r=round(pnl / dist, 2)))
        dn += 1; dpnl += pnl; dl = dl + 1 if pnl < 0 else 0
        busy_until = j
    return trades, skipped

def stats(tr):
    if not tr: return None
    pn = [t["pnl"] for t in tr]; eq = peak = dd = 0.0
    for p in pn:
        eq += p; peak = max(peak, eq); dd = max(dd, peak - eq)
    return dict(n=len(tr), win=round(sum(p > 0 for p in pn) / len(pn), 2), pnl=round(sum(pn), 2),
                avg_r=round(statistics.mean(t["r"] for t in tr), 2), worst=round(min(pn), 2),
                best=round(max(pn), 2), max_dd=round(dd, 2))

if __name__ == "__main__":
    out = dict(params=P, runs={})
    # Scout snapshot: current levels
    t_now = H1[-1]["ts"] + 3600
    lv, z = levels_at(t_now)
    last = M15[-1]["c"]
    snap = dict(as_of=datetime.fromtimestamp(t_now, timezone.utc).isoformat(), last_price=last, zone_halfwidth=round(z, 2),
                levels=[dict(price=round(p, 2), touches=n, side="support" if p < last else "resistance") for p, n in sorted(lv)])
    json.dump(snap, open(os.path.join(D, "levels_latest.json"), "w"), indent=1)
    print("SCOUT levels now:", json.dumps(snap, indent=1))
    for tf in ("5m", "15m", "1h"):
        bars = load(tf)
        span_h = (bars[-1]["ts"] - bars[0]["ts"]) / 3600
        for name, sp, sl in (("spread0.15_slip0.10", 0.15, 0.10), ("spread0.36_slip0.10", 0.36, 0.10), ("stress_spread0.36_slip0.20", 0.36, 0.20)):
            tr, sk = simulate(bars, tf, sp, sl)
            res = dict(span_hours=round(span_h), stats=stats(tr), skipped=sk)
            if name == "spread0.36_slip0.10" and tr:
                rr = []
                for s in range(200):
                    rt, _ = simulate(bars, tf, sp, sl, "random", random.Random(s))
                    if rt: rr.append(statistics.mean(t["r"] for t in rt))
                res["random_baseline_avg_r_mean"] = round(statistics.mean(rr), 2) if rr else None
                json.dump(tr, open(os.path.join(D, f"trades_{tf}.json"), "w"), indent=1)
            out["runs"][f"{tf}|{name}"] = res
            print(tf, name, json.dumps(res))
    json.dump(out, open(os.path.join(D, "first_check_results.json"), "w"), indent=1)
