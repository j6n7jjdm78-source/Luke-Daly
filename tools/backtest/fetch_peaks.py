"""Fetch 5-minute candles for every logged candidate and compute the PEAK multiple reached within 1h / 3h / 6h / 24h after we evaluated it.

Why: the candidate log only stores the price multiple at 1h/3h/6h, but the goal is bigger PEAKS. Candles give the best price reached in between.
Two peak measures per window (both relative to the price when we evaluated the coin):
  peak_close = highest 5-minute CLOSE (conservative, robust to one-candle wick glitches)  <- the main metric
  peak_hi    = highest 5-minute HIGH (upper bound)
Coins whose pool no longer exists are marked status=no_pool (treated as gone). Resumable: rerun to fill in the rest.
Usage: python3 tools/backtest/fetch_peaks.py [--limit N]
Data in: data/backtest/candidates_snapshot.csv   Data out: data/backtest/peaks.csv   (network: DexScreener + GeckoTerminal, free, rate limited)"""
import csv, datetime as dt, os, sys, time, json
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["CLIPERZ_DRY"] = "1"
sys.path.insert(0, os.path.join(ROOT, "bot"))
import bot  # noqa: E402  (gt_get spaces GeckoTerminal requests and retries 429s)
bot.GT_SPACING = 4.0     # the free tier allows about 30 requests a minute; a bulk job must stay under it

SRC = os.path.join(ROOT, "data", "backtest", "candidates_snapshot.csv")
OUT = os.path.join(ROOT, "data", "backtest", "peaks.csv")
WINDOWS = (("1h", 1), ("3h", 3), ("6h", 6), ("24h", 24))
FIELDS = ["ca", "pool", "status", "n_candles"] + [f"peak_{k}_{w}" for k in ("close", "hi") for w, _ in WINDOWS] + ["fetched_at"]
SANE_MAX = 200.0   # a peak over 200x is treated as bad data and left empty

def pools_from_dexscreener(cas):
    out = {}
    for i in range(0, len(cas), 30):
        try: ps = bot.http("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(cas[i:i + 30]))
        except Exception: continue
        for q in ps:
            a = (q.get("baseToken") or {}).get("address")
            if a and (a not in out or (q.get("liquidity") or {}).get("usd", 0) > out[a][1]): out[a] = (q.get("pairAddress"), (q.get("liquidity") or {}).get("usd", 0))
    return {a: v[0] for a, v in out.items()}

def pool_from_gt(ca):
    try:
        d = bot.gt_get(f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{ca}/pools?page=1")["data"]
        return d[0]["attributes"]["address"] if d else None
    except Exception:
        return None

def candles(pool, eval_ts):
    """Candles from the evaluation time to 24 h later, oldest first: [(ts, open, high, low, close), ...]."""
    end = int(eval_ts + 24 * 3600 + 600)
    d = bot.gt_get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/minute?aggregate=5&limit=300&before_timestamp={end}&currency=usd")
    cs = [(c[0], c[1], c[2], c[3], c[4]) for c in d["data"]["attributes"]["ohlcv_list"] if c[0] >= eval_ts]
    return sorted(cs)

def peaks(cs, price0, eval_ts):
    out = {}
    for w, h in WINDOWS:
        sub = [c for c in cs if c[0] <= eval_ts + h * 3600]
        for k, idx in (("close", 4), ("hi", 2)):
            v = max((c[idx] for c in sub), default=None)
            m = None if v is None or price0 <= 0 else round(v / price0, 3)
            out[f"peak_{k}_{w}"] = "" if m is None or m > SANE_MAX else m
    return out

def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    rows = list(csv.DictReader(open(SRC)))
    done = {r["ca"]: r for r in csv.DictReader(open(OUT))} if os.path.exists(OUT) else {}
    todo = [r for r in rows if r["ca"] not in done or done[r["ca"]]["status"] == "error"]
    def dead(r): return all((r.get(k) or "") in ("0", "0.0") for k in ("m1h", "m3h", "m6h"))      # gone by the first checkpoint already
    todo.sort(key=dead)         # coins that lived past 1h first; instantly-dead ones last (their peak falls back to the checkpoints if never fetched)
    if limit: todo = todo[:limit]
    print(f"{len(rows)} candidates, {len(done)} already fetched, fetching {len(todo)}")
    pools = pools_from_dexscreener([r["ca"] for r in todo])
    res = dict(done)
    for n, r in enumerate(todo, 1):
        ca = r["ca"]; row = dict.fromkeys(FIELDS, ""); row.update(ca=ca, fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
        try:
            pool = pools.get(ca) or pool_from_gt(ca); row["pool"] = pool or ""
            if not pool: row["status"] = "no_pool"
            else:
                ets = dt.datetime.fromisoformat(r["eval_utc"]).timestamp(); cs = candles(pool, ets)
                row["n_candles"] = len(cs)
                if not cs: row["status"] = "no_candles"
                else: row["status"] = "ok"; row.update(peaks(cs, float(r["price0"] or 0), ets))
        except Exception as e:
            row["status"] = "error"; print("  error", ca[:8], type(e).__name__, str(e)[:60])
        res[ca] = row
        if n % 10 == 0 or n == len(todo):
            w = csv.DictWriter(open(OUT, "w", newline=""), FIELDS); w.writeheader(); w.writerows(res.values())
            print(f"  {n}/{len(todo)} done (GeckoTerminal requests {bot.GT_STATS[0]}, rate-limited {bot.GT_STATS[1]})", flush=True)

if __name__ == "__main__": main()
