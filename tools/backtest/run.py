"""Backtest report: how would different rule sets have done on the coins we logged? Metric chosen by the owner: BIGGER PEAKS.
  hit2x = the coin's best 5-minute close within 6 hours after we evaluated it was at least 2x the price at evaluation.
Reads data/backtest/candidates_snapshot.csv + peaks.csv (from fetch_peaks.py) + calls_snapshot.csv and writes BACKTEST.md.
Usage: python3 tools/backtest/run.py        (no network; fully reproducible from the files in data/backtest/)

Honest limits (also printed in the report): small samples, only coins that reached our safety stage or narrowly missed a filter are logged (not every
coin on the chain), and rules are judged on the same coins they were designed with unless the walk-forward table says otherwise."""
import csv, math, os, random, statistics, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = os.path.join(ROOT, "data", "backtest")

def num(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def wilson(k, n, z=1.96):
    """95% Wilson confidence interval for a rate k/n. Returns (low, high); (0, 1) when n is 0."""
    if n == 0: return 0.0, 1.0
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)

def load():
    cands = list(csv.DictReader(open(os.path.join(D, "candidates_snapshot.csv"))))
    peaks = {r["ca"]: r for r in csv.DictReader(open(os.path.join(D, "peaks.csv")))} if os.path.exists(os.path.join(D, "peaks.csv")) else {}
    rows = []
    for r in cands:
        if r["m1h"] == "": continue                       # no outcome yet
        p = peaks.get(r["ca"], {})
        r = dict(r); r["tier"] = r["tier"] or "early"      # rows logged before the tier column existed all came from the early tier
        known = [x for x in (num(r["m1h"]), num(r["m3h"]), num(r["m6h"])) if x is not None]
        pk = num(p.get("peak_close_6h")) if p.get("status") == "ok" else None
        r["peak6"] = pk if pk is not None else (max(known) if known else 0.0)      # no candles: best known checkpoint is a lower bound
        r["peak_src"] = "candles" if pk is not None else "checkpoints"
        r["m1"] = num(r["m1h"]); r["flags"] = r.get("flags") or ""
        rows.append(r)
    return rows

def stats(rows):
    n = len(rows)
    if n == 0: return dict(n=0)
    h2 = sum(1 for r in rows if r["peak6"] >= 2); h15 = sum(1 for r in rows if r["peak6"] >= 1.5)
    lo, hi = wilson(h2, n)
    return dict(n=n, hit2=h2, rate2=h2 / n, ci=(lo, hi), rate15=h15 / n, med_peak=statistics.median(r["peak6"] for r in rows),
                med_1h=statistics.median(r["m1"] for r in rows), gone=sum(1 for r in rows if r["m1"] == 0) / n, up1h=sum(1 for r in rows if r["m1"] > 1) / n)

# ---- rule sets (pure functions of what we logged at evaluation time) ----
def f(r, k): return num(r.get(k))
def trades(r): return (f(r, "buys") or 0) + (f(r, "sells") or 0)
def ratio(r): return (f(r, "buys") or 0) / max(f(r, "sells") or 0, 1)
def no_lp_unlocked(r): return "LP Unlocked" not in r["flags"]

RULES = {
    "All logged coins (no filter)": lambda r: True,
    "Live: coins we actually called (normal + early)": lambda r: r["decision"] in ("pass", "posted"),
    "Live normal tier only": lambda r: r["tier"] == "normal" and r["decision"] in ("pass", "posted"),
    "No safety gate: normal-tier coins that passed market filters": lambda r: r["tier"] == "normal" and r["decision"] in ("pass", "posted", "blocked"),
    "Rug-checker style: holders>=50, risk score<=30, no 'LP unlocked'": lambda r: (f(r, "holders") or 0) >= 50 and (f(r, "score") if f(r, "score") is not None else 99) <= 30 and no_lp_unlocked(r),
    "Strict rug-checker: holders>=100, risk score<=20, no 'LP unlocked'": lambda r: (f(r, "holders") or 0) >= 100 and (f(r, "score") if f(r, "score") is not None else 99) <= 20 and no_lp_unlocked(r),
    "Momentum: 5m>0, 1h between +5% and +60%, buy ratio>=1.5": lambda r: (f(r, "m5") or -99) > 0 and 5 <= (f(r, "h1") or -99) <= 60 and ratio(r) >= 1.5,
    "Most active third (by trades)": None,       # filled in at run time (needs the whole set)
    "Near-misses (failed exactly one filter)": lambda r: r["decision"] == "nearmiss",
    "Early tier, all": lambda r: r["tier"] == "early",
    "Early tier, called only": lambda r: r["tier"] == "early" and r["decision"] in ("pass", "posted"),
}

def apply_rules(rows):
    rules = dict(RULES)
    cut = sorted((trades(r) for r in rows), reverse=True)[max(len(rows) // 3 - 1, 0)] if rows else 0
    rules["Most active third (by trades)"] = lambda r: trades(r) >= cut
    return {k: [r for r in rows if fn(r)] for k, fn in rules.items()}

def random_baseline(rows, size, draws=2000, seed=7):
    """Average hit rate of random picks of the same size as the live selection (the 'monkey with a dartboard' baseline)."""
    if not rows or size <= 0: return None
    rnd = random.Random(seed); rates = []
    for _ in range(draws):
        s = rnd.sample(rows, min(size, len(rows))); rates.append(sum(1 for r in s if r["peak6"] >= 2) / len(s))
    rates.sort(); return statistics.mean(rates), rates[int(0.05 * draws)], rates[int(0.95 * draws)]

def pct(x): return f"{100 * x:.0f}%"
def row_md(name, s):
    if s["n"] == 0: return f"| {name} | 0 | - | - | - | - | - | - |"
    return f"| {name} | {s['n']} | {s['hit2']} ({pct(s['rate2'])}, CI {pct(s['ci'][0])}-{pct(s['ci'][1])}) | {pct(s['rate15'])} | {s['med_peak']:.2f}x | {s['med_1h']:.2f}x | {pct(s['up1h'])} | {pct(s['gone'])} |"

HEAD = "| Rule set | Coins | Peak >= 2x within 6h (95% CI) | Peak >= 1.5x | Median peak | Median after 1h | Above 1.0x after 1h | Gone after 1h |\n|---|---|---|---|---|---|---|---|"

def calls_section():
    p = os.path.join(D, "calls_snapshot.csv")
    if not os.path.exists(p): return []
    rs = list(csv.DictReader(open(p))); out = []
    for r in rs:
        c0 = num(r["mcap_at_call"]) or 1; pk = max(num(r.get("peak_mcap")) or 0, num(r.get("current_mcap")) or 0)
        out.append(dict(tok=r["token"], status=r["status"], m=(pk / c0 if pk / c0 <= 100 else 1.0)))
    n = len(out); h15 = sum(1 for x in out if x["m"] >= 1.5); h2 = sum(1 for x in out if x["m"] >= 2); h4 = sum(1 for x in out if x["m"] >= 4)
    rug = sum(1 for x in out if x["status"] == "rugged"); lo, hi = wilson(h2, n)
    return [f"- {n} public calls so far: **{h15} reached 1.5x+ ({pct(h15 / n)})**, **{h2} reached 2x+ ({pct(h2 / n)}, 95% CI {pct(lo)}-{pct(hi)})**, {h4} reached 4x+, {rug} rugged. Median peak {statistics.median(x['m'] for x in out):.2f}x."]

def feature_tables(rows):
    """Hit rate of peak >= 2x by feature bucket, to show which logged features carry signal (only buckets with n >= 8)."""
    specs = [("Holders", "holders", [0, 100, 300, 1000, 10**9]), ("RugCheck risk score (low = safer)", "score", [0, 5, 20, 40, 101]), ("Age when evaluated (min)", "age_m", [0, 15, 30, 60, 10**5]),
             ("Liquidity ($)", "liq", [0, 15000, 25000, 50000, 10**9]), ("Market cap ($)", "mcap", [0, 30000, 60000, 150000, 10**9]), ("1h price change at evaluation (%)", "h1", [-100, 0, 20, 60, 10**6]),
             ("5m price change at evaluation (%)", "m5", [-100, 0, 10, 40, 10**6])]
    out = []
    for title, key, edges in specs:
        lines = []
        for lo_, hi_ in zip(edges, edges[1:]):
            g = [r for r in rows if f(r, key) is not None and lo_ <= f(r, key) < hi_]
            if len(g) < 8: continue
            k = sum(1 for r in g if r["peak6"] >= 2); lo, hi = wilson(k, len(g))
            lines.append(f"| {lo_} to {hi_ if hi_ < 10**5 else '+'} | {len(g)} | {k} ({pct(k / len(g))}, CI {pct(lo)}-{pct(hi)}) |")
        if lines: out += [f"**{title}**", "", "| Bucket | Coins | Peak >= 2x |", "|---|---|---|"] + lines + [""]
    return out

def split_by_time(rows):
    s = sorted(rows, key=lambda r: r["eval_utc"]); h = len(s) // 2
    return s[:h], s[h:]

def build():
    rows = load(); sets = apply_rules(rows); md = []
    if not rows: return "# Backtest\n\nNo logged coins with a finished 1-hour outcome yet, so there is nothing to test.\n"
    base = stats(rows)
    md += ["# Backtest: which rules find the coins that reach bigger peaks?", "",
           "Metric (chosen by the owner): **peak >= 2x** = the coin's best 5-minute close within 6 hours of our evaluation was at least twice the price at evaluation. "
           "Peaks come from 5-minute candles (`data/backtest/peaks.csv`); where a pool no longer exists the best known 1h/3h/6h checkpoint is used as a lower bound. "
           "Regenerate with `python3 tools/backtest/run.py`.", "",
           f"Data: {len(rows)} logged coins ({min(r['eval_utc'] for r in rows)[:16]} to {max(r['eval_utc'] for r in rows)[:16]} UTC); {sum(1 for r in rows if r['peak_src'] == 'candles')} have candle peaks.", "",
           "## Our public calls", ""] + calls_section() + ["", "## Rule sets on the logged coins", "", HEAD]
    for name, g in sets.items(): md.append(row_md(name, stats(g)))
    live = sets["Live: coins we actually called (normal + early)"]
    rb = random_baseline(rows, len(live))
    if rb: md += ["", f"Random picks of the same size as the live selection ({len(live)} coins) reach 2x+ about **{pct(rb[0])}** of the time (90% range {pct(rb[1])}-{pct(rb[2])}); the base rate over all logged coins is **{pct(base['rate2'])}**."]
    a, b = split_by_time(rows)
    md += ["", "## Stability: first half vs second half of the period", "", "A rule that only works in one half is probably luck.", "", HEAD]
    for name in ("All logged coins (no filter)", "Live: coins we actually called (normal + early)", "Rug-checker style: holders>=50, risk score<=30, no 'LP unlocked'", "Momentum: 5m>0, 1h between +5% and +60%, buy ratio>=1.5"):
        fn = (lambda r, nm=name: r in sets[nm]); md.append(row_md(name + " (first half)", stats([r for r in a if fn(r)]))); md.append(row_md(name + " (second half)", stats([r for r in b if fn(r)])))
    md += ["", "## Which logged features carry signal?", ""] + feature_tables(rows)
    md += ["## Read this before trusting any number", "",
           "- **Small samples.** Confidence intervals above are wide; differences between rule sets are only real if their intervals do not overlap, and even then only for this period.",
           "- **Selection bias.** Only coins that reached our safety stage (or narrowly missed one filter) are logged, not every coin on Solana, so these are not general market statistics.",
           "- **Tuned on the same coins.** Rules built from this data are not proven by it; new strategies run in shadow mode and are judged on forward data before they go live.",
           "- **Other bots.** Public rule sets (rug checkers, holder scanners) were re-implemented from their published criteria, not run; their own marketing claims are unverified.",
           "- **Public base rates** (arXiv 2026 study of 832,941 Pump.fun launches; CoinGecko launch-day data) show that only about 0.2-1.4% of new coins last, so a good scanner is judged by enrichment over the base rate, not by winning most calls."]
    return "\n".join(md) + "\n"

if __name__ == "__main__":
    out = build(); open(os.path.join(ROOT, "BACKTEST.md"), "w").write(out); print(out)
