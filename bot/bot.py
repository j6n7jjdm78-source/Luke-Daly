"""Meme coin call-out bot. Run every ~10 min via cron/launchd: python3 bot/bot.py
Env: X_CLIENT_ID, X_CLIENT_SECRET. Needs tokens.json from auth.py.
Create a file named STOP in repo root to halt all posting."""
import os, sys, csv, json, time, base64, datetime as dt, statistics as st
import urllib.parse as u, urllib.request as r
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(f"{ROOT}/bot/config.json")); CALLS = f"{ROOT}/calls.csv"; TOK = f"{ROOT}/tokens.json"
FIELDS = "id,token,chain,contract,called_at_utc,mcap_at_call,tweet_id,status,current_mcap,multiple,notes".split(",")
DRY = CFG["dry_run"]; now = dt.datetime.now(dt.timezone.utc)

def http(url, data=None, headers=None, method=None):
    h = {"User-Agent": "Mozilla/5.0 (compatible; cliperz-bot/1.0)", "Accept": "application/json"}
    h.update(headers or {})
    req = r.Request(url, data, h, method=method)
    return json.load(r.urlopen(req, timeout=20))

def token():
    t = json.load(open(TOK))
    if time.time() - os.path.getmtime(TOK) > t.get("expires_in", 7200) - 300:  # refresh
        a = base64.b64encode(f"{os.environ['X_CLIENT_ID']}:{os.environ['X_CLIENT_SECRET']}".encode()).decode()
        t = http("https://api.x.com/2/oauth2/token", u.urlencode(dict(grant_type="refresh_token",
                 refresh_token=t["refresh_token"], client_id=os.environ["X_CLIENT_ID"])).encode(),
                 {"Authorization": "Basic " + a, "Content-Type": "application/x-www-form-urlencoded"})
        json.dump(t, open(TOK, "w"))
    return t["access_token"]

def post(text, reply_to=None):
    print(("[DRY RUN] " if DRY else "[POST] ") + text + "\n")
    if DRY: return "dry-" + str(int(time.time()))
    body = {"text": text}
    if reply_to and not str(reply_to).startswith("dry-"): body["reply"] = {"in_reply_to_tweet_id": reply_to}
    return http("https://api.x.com/2/tweets", json.dumps(body).encode(),
                {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})["data"]["id"]

def rows():
    if not os.path.exists(CALLS): return []
    return list(csv.DictReader(open(CALLS)))
def save(rs):
    w = csv.DictWriter(open(CALLS, "w", newline=""), FIELDS); w.writeheader(); w.writerows(rs)

def fmt(n): return f"${n/1000:.0f}k" if n < 1e6 else f"${n/1e6:.2f}m"
def pair(addr):
    ps = http(f"https://api.dexscreener.com/latest/dex/tokens/{addr}").get("pairs") or []
    ps = [p for p in ps if p["chainId"] == CFG["chain"]]
    return max(ps, key=lambda p: (p.get("liquidity") or {}).get("usd", 0)) if ps else None

def candidates():
    seen = {x["contract"] for x in rows()}
    for p in http("https://api.dexscreener.com/token-profiles/latest/v1"):
        if p["chainId"] != CFG["chain"] or p["tokenAddress"] in seen: continue
        q = pair(p["tokenAddress"])
        if not q or not q.get("pairCreatedAt"): continue
        age = (now.timestamp() * 1000 - q["pairCreatedAt"]) / 3.6e6
        mc, liq, vol = q.get("marketCap") or 0, (q.get("liquidity") or {}).get("usd", 0), (q.get("volume") or {}).get("h24", 0)
        tx = (q.get("txns") or {}).get("h1", {})
        if (CFG["min_mcap_usd"] <= mc <= CFG["max_mcap_usd"] and liq >= CFG["min_liquidity_usd"] and vol >= CFG["min_volume_24h_usd"]
                and CFG["min_age_hours"] <= age <= CFG["max_age_hours"] and tx.get("buys", 0) > tx.get("sells", 0) and liq / mc > 0.05):
            yield vol, q, mc, liq, age

def call_out():
    rs = rows(); today = [x for x in rs if x["called_at_utc"][:10] == str(now.date())]
    if len(today) >= CFG["max_calls_per_day"]: return
    best = max(candidates(), default=None, key=lambda c: c[0])
    if not best: return
    _, q, mc, liq, age = best; sym = q["baseToken"]["symbol"]; ca = q["baseToken"]["address"]
    text = (f"${sym} (Solana)\nMcap: {fmt(mc)} | Liq: {fmt(liq)} | Age: {age:.0f}h\n"
            f"Why: buys > sells last hour, 24h vol {fmt(q['volume']['h24'])}, liq/mcap {liq/mc:.0%}\n"
            f"Risk: new token, can rug. Check mint/freeze authority yourself.\nCA: {ca}")
    if CFG["paid_promo"]: text += "\nPaid promotion."
    elif CFG["i_hold_called_coins"]: text += "\nI hold this."
    tid = post(text)
    rs.append(dict(id=len(rs) + 1, token=sym, chain=CFG["chain"], contract=ca, called_at_utc=now.isoformat(), mcap_at_call=mc,
                   tweet_id=tid, status="open", current_mcap=mc, multiple=1.0, notes=""))
    save(rs)

def track():
    rs = rows()
    for x in rs:
        if x["status"] not in ("open",) and not x["status"].startswith("hit"): continue
        q = pair(x["contract"]); mc = float((q or {}).get("marketCap") or 0)
        x["current_mcap"] = mc; x["multiple"] = round(mc / float(x["mcap_at_call"]), 2)
        hit = [m for m in CFG["result_milestones"] if x["multiple"] >= m]
        done = int(x["status"].split("x")[0][3:] or 0) if x["status"].startswith("hit") else 0
        if hit and hit[-1] > done:  # post once per new milestone
            post(f"${x['token']}: called at {fmt(float(x['mcap_at_call']))}, now {fmt(mc)} = {x['multiple']:.0f}x\n"
                 f"Call: tracked from the original post.", reply_to=x["tweet_id"]); x["status"] = f"hit{hit[-1]}x"
        elif mc < float(x["mcap_at_call"]) * 0.1 or not q: x["status"] = "dead"
        age = (now - dt.datetime.fromisoformat(x["called_at_utc"])).days
        if age >= 14 and x["status"] == "open": x["status"] = "closed"
    save(rs)

def scoreboard():
    if now.weekday() != 6 or now.hour < 17: return  # Sundays from 17:00 UTC, once per day
    mark = f"{ROOT}/state/scoreboard-{now.date()}"; os.makedirs(f"{ROOT}/state", exist_ok=True)
    if os.path.exists(mark): return
    open(mark, "w").close()
    m = [float(x["multiple"]) for x in rows() if x["multiple"]]
    if m: post(f"Weekly scoreboard\nCalls: {len(m)} | 2x+: {sum(v >= 2 for v in m)} | Down 50%+: {sum(v <= .5 for v in m)}\n"
               f"Median: {st.median(m):.2f}x | Best: {max(m):.1f}x | Worst: {min(m):.2f}x")

if __name__ == "__main__":
    if os.path.exists(f"{ROOT}/STOP"): sys.exit("STOP file present, not posting")
    track(); call_out(); scoreboard()
