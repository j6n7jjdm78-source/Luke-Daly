"""One-line status per tracked call. Updates calls.csv."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bot")); import bot
rs = bot.rows()
for x in rs:
    q = bot.pair(x["contract"])
    if not q: print(f"${x['token']}: no pair found (possibly dead)"); continue
    mc = float(q.get("marketCap") or 0); x["current_mcap"] = mc; x["multiple"] = round(mc / float(x["mcap_at_call"]), 2)
    print(f"${x['token']}: ${mc/1000:.1f}k = {x['multiple']}x (call ${float(x['mcap_at_call'])/1000:.0f}k) liq ${q['liquidity']['usd']/1000:.1f}k 5m {q['priceChange'].get('m5')}% 1h {q['priceChange'].get('h1')}%")
bot.save(rs)
