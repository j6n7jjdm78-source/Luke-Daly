"""What predicts a 2x? Reads state/candidates.csv (every coin that reached the safety stage, with its outcome 1h/3h/6h later)
and prints, per feature bucket: how many coins, the share that was >=2x at a checkpoint, and the share that was rugged (0).
Usage: python3 bot/analyze.py"""
import csv, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
f = os.path.join(ROOT, "state", "candidates.csv")
rows = list(csv.DictReader(open(f))) if os.path.exists(f) else []
def num(v):
    try: return float(v)
    except Exception: return None
done = [r for r in rows if num(r["m3h"]) is not None]
print(f"{len(rows)} candidates logged, {len(done)} with a 3h outcome.")
if len(done) < 10: print("Too few finished outcomes to draw conclusions yet. Come back after ~30."); sys.exit()
def bucket(name, key, edges):
    print(f"\n{name}")
    for lo, hi in zip(edges, edges[1:]):
        g = [r for r in done if num(r[key]) is not None and lo <= num(r[key]) < hi]
        if not g: continue
        two = sum(num(r["m3h"]) >= 2 for r in g); rug = sum(num(r["m3h"]) == 0 for r in g); up = sum(num(r["m3h"]) >= 1 for r in g)
        print(f"  {lo:>6}-{hi:<6} n={len(g):<3} >=2x: {two/len(g):4.0%}  >=1x: {up/len(g):4.0%}  rugged: {rug/len(g):4.0%}")
bucket("Our quality score at evaluation (normal tier)", "qscore", [0, 55, 65, 75, 101])
bucket("Holders at evaluation", "holders", [0, 100, 300, 1000, 10**9])
bucket("RugCheck score (lower = safer)", "score", [0, 5, 20, 40, 101])
bucket("Age when evaluated (min)", "age_m", [0, 10, 20, 30, 60])
bucket("Liquidity ($)", "liq", [0, 15000, 25000, 50000, 10**9])
bucket("Already up since first sight (%)", "run_pct", [-100, 0, 25, 50, 101])
two = sum(num(r["m3h"]) >= 2 for r in done)
print(f"\nOverall: {two}/{len(done)} reached 2x at 3h; rugged: {sum(num(r['m3h']) == 0 for r in done)}/{len(done)}")
