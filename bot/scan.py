"""Prints the best new Solana candidate not offered before, or NONE. Records it in state/offered.txt.
Usage: python3 bot/scan.py"""
import os, sys, json, datetime as dt, urllib.request as r
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bot")); import bot
os.makedirs(f"{ROOT}/state", exist_ok=True); OFF = f"{ROOT}/state/offered.txt"
offered = set(open(OFF).read().split()) if os.path.exists(OFF) else set()
offered |= {x["contract"] for x in bot.rows()}
H = {"User-Agent": "Mozilla/5.0 (compatible; cliperz-bot/1.0)", "Accept": "application/json"}
pools = {}
for ep in ("trending_pools", "new_pools"):
    for pg in (1, 2, 3):
        try: d = json.load(r.urlopen(r.Request(f"https://api.geckoterminal.com/api/v2/networks/solana/{ep}?page={pg}", headers=H), timeout=20))
        except Exception: continue
        for p in d["data"]:
            a = p["attributes"]
            try:
                m = float(a.get("market_cap_usd") or a.get("fdv_usd") or 0); liq = float(a["reserve_in_usd"]); v = float(a["volume_usd"]["h24"])
                age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
                t = a["transactions"]["h1"]; pc = a["price_change_percentage"]; ca = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
                pools[ca] = (ca, m, liq, v, age, t["buys"], t["sells"], float(pc["h1"]), float(pc["h24"]))
            except Exception: continue
ok = [x for x in pools.values() if x[0] not in offered and 20000 <= x[1] <= 500000 and x[2] >= 12000 and 30000 <= x[3] <= x[1] * 15
      and 1 <= x[4] <= 72 and x[5] > x[6] * 1.2 and x[7] > -8]
if not ok: print("NONE"); sys.exit()
ca, m, liq, v, age, b, s, h1, h24 = max(ok, key=lambda x: x[3])
q = bot.pair(ca) or {}; bt = q.get("baseToken", {})
open(OFF, "a").write(ca + "\n")
print(f"${bt.get('symbol','?')} ({bt.get('name','?')}) Solana\nMcap: ${m/1000:.0f}k | Liq: ${liq/1000:.0f}k | Age: {age:.0f}h\n"
      f"1h buys/sells: {b}/{s} | 1h {h1:+.1f}% | 24h {h24:+.1f}% | vol24 ${v/1000:.0f}k\nCA: {ca}\n{q.get('url','')}")
