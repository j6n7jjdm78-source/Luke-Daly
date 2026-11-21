"""Meme coin call-out bot. Run every ~10 min via cron/launchd: python3 bot/bot.py
Env: X_CLIENT_ID, X_CLIENT_SECRET. Needs tokens.json from auth.py.
Create a file named STOP in repo root to halt all posting."""
import os, sys, csv, json, time, base64, datetime as dt, statistics as st
import urllib.parse as u, urllib.request as r
import cliperz_keys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(f"{ROOT}/bot/config.json"))
TOK = cliperz_keys.TOK  # ~/.config/cliperz-bot/tokens.json, außerhalb des Bot-Ordners
FIELDS = "id,token,chain,contract,called_at_utc,mcap_at_call,tweet_id,status,current_mcap,multiple,notes".split(",")
# Testlauf: config dry_run oder CLIPERZ_DRY=1 (start.mjs test). Probe-Calls landen in eigener Datei,
# damit ein späterer Live-Lauf nie Ergebnis-Posts zu Coins schreibt, die nie öffentlich gecallt wurden.
DRY = CFG["dry_run"] or os.environ.get("CLIPERZ_DRY") == "1"; now = dt.datetime.now(dt.timezone.utc)
CALLS = f"{ROOT}/calls-dry.csv" if DRY else f"{ROOT}/calls.csv"
STATE = f"{ROOT}/state-dry" if DRY else f"{ROOT}/state"

def http(url, data=None, headers=None, method=None):
    req = r.Request(url, data, {"User-Agent": "Mozilla/5.0 (compatible; cliperz-bot/1.0)", "Accept": "application/json", **(headers or {})}, method=method)
    return json.load(r.urlopen(req, timeout=20))

def token():
    t = json.load(open(TOK))
    if time.time() - os.path.getmtime(TOK) > t.get("expires_in", 7200) - 300:  # refresh
        cid, sec = cliperz_keys.load()
        a = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        t = http("https://api.x.com/2/oauth2/token", u.urlencode(dict(grant_type="refresh_token",
                 refresh_token=t["refresh_token"], client_id=cid)).encode(),
                 {"Authorization": "Basic " + a, "Content-Type": "application/x-www-form-urlencoded"})
        json.dump(t, open(TOK, "w"))
    return t["access_token"]

def upload_image(path):
    """Uploads a PNG to X (needs the media.write scope). Returns the media id string."""
    import uuid
    b = uuid.uuid4().hex
    def part(n, v, fn=None, ct=None):
        h = f'--{b}\r\nContent-Disposition: form-data; name="{n}"' + (f'; filename="{fn}"' if fn else "") + "\r\n" + (f"Content-Type: {ct}\r\n" if ct else "") + "\r\n"
        return h.encode() + (v if isinstance(v, bytes) else v.encode()) + b"\r\n"
    body = (part("media", open(path, "rb").read(), "card.png", "image/png") + part("media_category", "tweet_image")
            + part("media_type", "image/png") + f"--{b}--\r\n".encode())
    d = http("https://api.x.com/2/media/upload", body, {"Authorization": "Bearer " + token(), "Content-Type": f"multipart/form-data; boundary={b}"})
    return str(d["data"]["id"])

def post(text, reply_to=None, media=None):
    print(("[DRY RUN] " if DRY else "[POST] ") + text + (f"\n[+ image {media}]" if media else "") + "\n")
    if DRY: return "dry-" + str(int(time.time()))
    body = {"text": text}
    if media: body["media"] = {"media_ids": [media]}
    if reply_to and str(reply_to).isdigit(): body["reply"] = {"in_reply_to_tweet_id": reply_to}
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
                and CFG["min_age_hours"] <= age <= CFG["max_age_hours"] and tx.get("buys", 0) > tx.get("sells", 0) and liq / mc > 0.05
                and -5 < (q.get("priceChange") or {}).get("h1", 0) <= 40      # not falling, not already pumped
                and (q.get("priceChange") or {}).get("m5", 0) > -5            # not dumping right now
                and vol <= mc * 15                                           # skip wash-trading volume
                and tx.get("buys", 0) >= 1.3 * max(tx.get("sells", 0), 1)    # clear buy pressure
                and tx.get("buys", 0) + tx.get("sells", 0) >= 200):          # real activity
            yield vol, q, mc, liq, age

def safety(ca):
    """Contract safety gate via GeckoTerminal token info. Returns (ok, reason, summary). Fails closed when data is missing."""
    info = None
    for attempt in range(3):
        try:
            info = http(f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{ca}/info")["data"]["attributes"]; break
        except Exception as e:
            time.sleep(3 * (attempt + 1))
    if not info: return False, "no safety data", ""
    if info.get("mint_authority") != "no": return False, f"mint authority not revoked ({info.get('mint_authority')})", ""
    if info.get("freeze_authority") != "no": return False, f"freeze authority not revoked ({info.get('freeze_authority')})", ""
    if str(info.get("is_honeypot")).lower() == "yes": return False, "honeypot flag", ""
    h = info.get("holders") or {}
    try: cnt = int(h.get("count") or 0); top10 = float((h.get("distribution_percentage") or {}).get("top_10") or 100)
    except Exception: return False, "no holder data", ""
    if cnt < 100: return False, f"only {cnt} holders", ""
    if top10 > 55: return False, f"top 10 holders own {top10:.0f}%", ""
    return True, "ok", f"mint+freeze revoked | {cnt} holders | top10 {top10:.0f}%"

def call_out():
    rs = rows(); today = [x for x in rs if x["called_at_utc"][:10] == str(now.date())]
    if len(today) >= CFG["max_calls_per_day"]: return
    best = None; safe = ""
    for c in sorted(candidates(), key=lambda c: -c[0])[:4]:
        ok, why, summ = safety(c[1]["baseToken"]["address"])
        if ok: best, safe = c, summ; break
        print(f"[SKIP] {c[1]['baseToken']['symbol']}: {why}")
    if not best: return
    _, q, mc, liq, age = best; sym = q["baseToken"]["symbol"]; ca = q["baseToken"]["address"]
    text = (f"${sym} (Solana)\nMcap: {fmt(mc)} | Liq: {fmt(liq)} | Age: {age:.0f}h\n"
            f"Why: buys > sells last hour, 24h vol {fmt(q['volume']['h24'])}, liq/mcap {liq/mc:.0%}\n"
            f"Safety: {safe}. Still new, can rug.\nCA: {ca}")
    if CFG["paid_promo"]: text += "\nPaid promotion."
    elif CFG["i_hold_called_coins"]: text += "\nI hold this."
    # call card picture: always attach one, never post a call as text only
    import subprocess
    n = len(rs) + 1; png = f"{ROOT}/drafts/call{n}.png"; tx = (q.get("txns") or {}).get("h1", {})
    try:
        subprocess.run([sys.executable, f"{ROOT}/bot/card.py", str(n), sym, q["baseToken"].get("name", sym), f"{mc/1000:.0f}", f"{liq/1000:.0f}",
                        str(tx.get("buys", 0)), str(tx.get("sells", 0)), png], check=True, timeout=90)
        media = "dry-media" if DRY else upload_image(png)
    except Exception as e:
        print(f"[SKIP] could not make/upload the card ({e!r}); not posting a text-only call"); return
    tid = post(text, media=media)
    rs.append(dict(id=n, token=sym, chain=CFG["chain"], contract=ca, called_at_utc=now.isoformat(), mcap_at_call=mc,
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
        if age >= 14 and (x["status"] == "open" or x["status"].startswith("hit")): x["status"] = "closed"
    save(rs)

def scoreboard():
    if now.weekday() != 6 or now.hour < 17: return  # Sundays from 17:00 UTC, once per day
    mark = f"{STATE}/scoreboard-{now.date()}"; os.makedirs(STATE, exist_ok=True)
    if os.path.exists(mark): return
    open(mark, "w").close()
    week = now - dt.timedelta(days=7)  # nur Calls der letzten 7 Tage
    m = [float(x["multiple"]) for x in rows() if x["multiple"] and dt.datetime.fromisoformat(x["called_at_utc"]) >= week]
    if m: post(f"Weekly scoreboard\nCalls: {len(m)} | 2x+: {sum(v >= 2 for v in m)} | Down 50%+: {sum(v <= .5 for v in m)}\n"
               f"Median: {st.median(m):.2f}x | Best: {max(m):.1f}x | Worst: {min(m):.2f}x")

if __name__ == "__main__":
    if os.path.exists(f"{ROOT}/STOP"): sys.exit("STOP file present, not posting")
    track(); call_out(); scoreboard()
