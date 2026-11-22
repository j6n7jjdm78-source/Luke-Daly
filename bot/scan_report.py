"""Compact scan report: how many candidate tokens there are, why they fail, and what passes. Posts nothing."""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
C = bot.CFG; seen = {x["contract"] for x in bot.rows()}
sol = [{"tokenAddress": a} for a in bot.candidate_addresses()]
fails = collections.Counter(); passed = []
for p in sol:
    ca = p["tokenAddress"]
    if ca in seen: fails["already called"] += 1; continue
    q = bot.pair(ca)
    if not q or not q.get("pairCreatedAt"): fails["no data"] += 1; continue
    age = (bot.now.timestamp() * 1000 - q["pairCreatedAt"]) / 3.6e6
    mc = q.get("marketCap") or 0; liq = (q.get("liquidity") or {}).get("usd", 0); vol = (q.get("volume") or {}).get("h24", 0)
    tx = (q.get("txns") or {}).get("h1", {}); b, s = tx.get("buys", 0), tx.get("sells", 0); pc = q.get("priceChange") or {}
    why = []
    if not C["min_mcap_usd"] <= mc <= C["max_mcap_usd"]: why.append("mcap out of $20-300k")
    if liq < C["min_liquidity_usd"]: why.append("liq<$15k")
    if vol < C["min_volume_24h_usd"]: why.append("vol<$50k")
    if not C["min_age_hours"] <= age <= C["max_age_hours"]: why.append("age out of range")
    if not C.get("min_h1_change_pct", -5) < pc.get("h1", 0) <= C.get("max_h1_change_pct", 40): why.append("1h move out of range")
    if pc.get("m5", 0) <= C.get("min_m5_change_pct", -5): why.append("dumping")
    if b < C.get("min_buy_ratio", 1.3) * max(s, 1): why.append("weak buy ratio")
    if b + s < 200: why.append("<200 trades")
    if mc and vol > mc * C.get("max_vol_mcap_ratio", 15): why.append("wash volume")
    if why: fails[why[0]] += 1
    else:
        ok, w, summ = bot.safety(ca); passed.append(f"${q['baseToken']['symbol']} ${mc/1000:.0f}k liq ${liq/1000:.0f}k safety {'PASS' if ok else 'BLOCKED: ' + w}")
print(f"{len(sol)} candidate tokens | " + ", ".join(f"{v} {k}" for k, v in fails.most_common(4)))
print("PASSED MARKET FILTERS: " + ("; ".join(passed) if passed else "none"))

try:   # new-pair tier funnel: how many pools are being watched and what happened to the candidates logged so far
    import json, time, csv
    w = json.load(open(os.path.join(bot.STATE, "watch.json"))); ages = [(time.time() - (v["t"] if isinstance(v, dict) else v)) / 60 for v in w.values()]
    cr = bot.cand_rows(); dec = collections.Counter(x["decision"] for x in cr)
    print(f"NEW PAIRS: {len(w)} watched, {sum(bot.E['min_age_min'] <= a <= bot.E['max_age_min'] for a in ages)} in the {bot.E['min_age_min']}-{bot.E['max_age_min']} min window | logged {len(cr)}: {dict(dec)}")
except Exception as e:
    print("NEW PAIRS: no data yet")
