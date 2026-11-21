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

def publish_call(q, mc, liq, text, tier=""):
    """Makes the card, uploads it, posts, and logs the call. Never posts a call as text only."""
    import subprocess
    rs = rows(); sym = q["baseToken"]["symbol"]; ca = q["baseToken"]["address"]
    if CFG["paid_promo"]: text += "\nPaid promotion."
    elif CFG["i_hold_called_coins"]: text += "\nI hold this."
    n = len(rs) + 1; png = f"{ROOT}/drafts/call{n}.png"; tx = (q.get("txns") or {}).get("h1", {})
    try:
        subprocess.run([sys.executable, f"{ROOT}/bot/card.py", str(n), sym, q["baseToken"].get("name", sym), f"{mc/1000:.0f}", f"{liq/1000:.0f}",
                        str(tx.get("buys", 0)), str(tx.get("sells", 0)), png], check=True, timeout=90,
                       env={**os.environ, "CARD_TAG": "EARLY CALL" if tier == "EARLY" else "CALL"})
        media = "dry-media" if DRY else upload_image(png)
    except Exception as e:
        print(f"[SKIP] could not make/upload the card ({e!r}); not posting a text-only call"); return
    tid = post(text, media=media)
    rs.append(dict(id=n, token=sym, chain=CFG["chain"], contract=ca, called_at_utc=now.isoformat(), mcap_at_call=mc,
                   tweet_id=tid, status="open", current_mcap=mc, multiple=1.0, notes=tier))
    save(rs)

def call_out():
    rs = rows(); today = [x for x in rs if x["called_at_utc"][:10] == str(now.date()) and x["notes"] != "EARLY"]
    if len(today) >= CFG["max_calls_per_day"]: return
    best = None; safe = ""
    for c in sorted(candidates(), key=lambda c: -c[0])[:4]:
        ok, why, summ = safety(c[1]["baseToken"]["address"])
        if ok: best, safe = c, summ; break
        print(f"[SKIP] {c[1]['baseToken']['symbol']}: {why}")
    if not best: return
    _, q, mc, liq, age = best; sym = q["baseToken"]["symbol"]; ca = q["baseToken"]["address"]
    publish_call(q, mc, liq, (f"${sym} (Solana)\nMcap: {fmt(mc)} | Liq: {fmt(liq)} | Age: {age:.0f}h\n"
            f"Why: buys > sells last hour, 24h vol {fmt(q['volume']['h24'])}, liq/mcap {liq/mc:.0%}\n"
            f"Safety: {safe}. Still new, can rug.\nCA: {ca}"))

# ---------- EARLY tier: 15-60 min old tokens, clearly labelled high risk ----------
E = dict(min_age_min=15, max_age_min=60, min_mcap=10000, max_mcap=60000, min_liq=8000, buy_ratio=2.0, min_trades=150, max_per_day=2)

def early_safety(ca):
    """Needs mint+freeze revoked (required). Holder data is often not available yet at this age; if present it must look sane."""
    info = None
    for attempt in range(3):
        try: info = http(f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{ca}/info")["data"]["attributes"]; break
        except Exception: time.sleep(3 * (attempt + 1))
    if not info: return False, "no safety data", ""
    if info.get("mint_authority") != "no": return False, f"mint authority not confirmed revoked ({info.get('mint_authority')})", ""
    if info.get("freeze_authority") != "no": return False, f"freeze authority not confirmed revoked ({info.get('freeze_authority')})", ""
    if str(info.get("is_honeypot")).lower() == "yes": return False, "honeypot flag", ""
    h = info.get("holders") or {}
    try: cnt = int(h.get("count") or 0); top10 = float((h.get("distribution_percentage") or {}).get("top_10") or 0)
    except Exception: cnt, top10 = 0, 0
    if cnt:
        if cnt < 50: return False, f"only {cnt} holders", ""
        if top10 > 60: return False, f"top 10 holders own {top10:.0f}%", ""
        return True, "ok", f"mint+freeze revoked | {cnt} holders | top10 {top10:.0f}%"
    return True, "ok", "mint+freeze revoked | holder data not available yet"

def gt_get(url, tries=4):
    """GeckoTerminal GET that waits and retries when rate limited (HTTP 429)."""
    for i in range(tries):
        try: return http(url)
        except Exception as e:
            if getattr(e, "code", None) == 429 and i < tries - 1: time.sleep(8 * (i + 1)); continue
            raise

def early_candidates():
    """GeckoTerminal's new-pools list only reaches ~7 min back, so we keep a watchlist: note every new pool with real liquidity
    (state/watch.json), then re-check each one when it is 15-60 min old using DexScreener's batch endpoint."""
    seen = {x["contract"] for x in rows()}
    wf = f"{STATE}/watch.json"; os.makedirs(STATE, exist_ok=True)
    try: watch = json.load(open(wf))
    except Exception: watch = {}
    for pg in range(1, 7):
        try: d = gt_get(f"https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page={pg}")["data"]
        except Exception: break
        for p in d:
            a = p["attributes"]
            try:
                created = dt.datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00")).timestamp()
                ca = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
                if float(a["reserve_in_usd"]) >= 4000 and ca not in watch: watch[ca] = created
            except Exception: continue
        time.sleep(3)
    t_now = now.timestamp()
    watch = {ca: t for ca, t in watch.items() if (t_now - t) / 60 <= 90}          # forget anything older than 90 min
    json.dump(watch, open(wf, "w"))
    due = [ca for ca, t in watch.items() if E["min_age_min"] <= (t_now - t) / 60 <= E["max_age_min"] and ca not in seen]
    for i in range(0, len(due), 30):
        try: pairs = http("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(due[i:i + 30]))
        except Exception: continue
        best = {}
        for q in pairs:
            ca = q["baseToken"]["address"]
            if ca not in best or (q.get("liquidity") or {}).get("usd", 0) > (best[ca].get("liquidity") or {}).get("usd", 0): best[ca] = q
        for ca, q in best.items():
            age_m = (t_now - watch[ca]) / 60
            mc, liq = q.get("marketCap") or 0, (q.get("liquidity") or {}).get("usd", 0)
            tx = (q.get("txns") or {}).get("h1", {}); b, sl = tx.get("buys", 0), tx.get("sells", 0); pc = q.get("priceChange") or {}
            if (E["min_mcap"] <= mc <= E["max_mcap"] and liq >= E["min_liq"] and b >= E["buy_ratio"] * max(sl, 1)
                    and b + sl >= E["min_trades"] and pc.get("m5", 0) > 0 and liq / mc > 0.1):
                yield b / max(sl, 1), q, mc, liq, age_m

def early_call_out():
    rs = rows()
    if len([x for x in rs if x["called_at_utc"][:10] == str(now.date()) and x["notes"] == "EARLY"]) >= E["max_per_day"]: return
    for c in sorted(early_candidates(), key=lambda c: -c[0])[:3]:
        _, q, mc, liq, age_m = c; ca = q["baseToken"]["address"]; sym = q["baseToken"]["symbol"]
        ok, why, safe = early_safety(ca)
        if not ok: print(f"[SKIP early] {sym}: {why}"); continue
        tx = q["txns"]["h1"]
        publish_call(q, mc, liq, (f"EARLY / HIGH RISK\n${sym} (Solana)\nMcap: {fmt(mc)} | Liq: {fmt(liq)} | Age: {age_m:.0f}m\n"
            f"Why: {tx['buys']} buys vs {tx['sells']} sells, price {q['priceChange'].get('m5', 0):+.0f}% last 5m\n"
            f"Safety: {safe}. Very new, most of these fail.\nCA: {ca}"), tier="EARLY")
        return

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
    """Sunday leaderboard: top 10 calls of the last 7 days that finished above their call price. Footer says how many calls the week had."""
    if now.weekday() != 6 or now.hour < 17: return  # Sundays from 17:00 UTC, once per day
    mark = f"{STATE}/scoreboard-{now.date()}"; os.makedirs(STATE, exist_ok=True)
    if os.path.exists(mark): return
    open(mark, "w").close()
    week = now - dt.timedelta(days=7)
    wk = [x for x in rows() if x["multiple"] and dt.datetime.fromisoformat(x["called_at_utc"]) >= week]
    top = sorted([x for x in wk if float(x["multiple"]) > 1.0], key=lambda x: -float(x["multiple"]))[:10]
    if not top: return
    import subprocess
    rj = f"{STATE}/lb_rows.json"; png = f"{ROOT}/drafts/leaderboard-{now.date()}.png"
    json.dump([[x["token"], float(x["multiple"]), x["notes"] == "EARLY"] for x in top], open(rj, "w"))
    try:
        subprocess.run([sys.executable, f"{ROOT}/bot/leaderboard.py", rj, str(len(wk)), png], check=True, timeout=90)
        media = "dry-media" if DRY else upload_image(png)
    except Exception as e:
        print(f"[SKIP] leaderboard picture failed ({e!r}); not posting a text-only leaderboard"); os.remove(mark); return
    post(f"Top calls this week 🏆\nTop {len(top)} of {len(wk)} calls. Every call is logged.", media=media)

if __name__ == "__main__":
    if os.path.exists(f"{ROOT}/STOP"): sys.exit("STOP file present, not posting")
    track(); call_out(); early_call_out(); scoreboard()
