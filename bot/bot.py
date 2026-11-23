"""Meme coin call-out bot. Run every ~10 min via cron/launchd: python3 bot/bot.py
Env: X_CLIENT_ID, X_CLIENT_SECRET. Needs tokens.json from auth.py.
Create a file named STOP in repo root to halt all posting."""
import os, re, sys, threading, csv, json, time, base64, datetime as dt, statistics as st
import urllib.parse as u, urllib.request as r, urllib.error
import cliperz_keys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(f"{ROOT}/bot/config.json"))
TOK = cliperz_keys.TOK  # ~/.config/cliperz-bot/tokens.json, außerhalb des Bot-Ordners
FIELDS = "id,token,chain,contract,called_at_utc,mcap_at_call,tweet_id,status,current_mcap,multiple,notes,peak_mcap".split(",")
# Testlauf: config dry_run oder CLIPERZ_DRY=1 (start.mjs test). Probe-Calls landen in eigener Datei,
# damit ein späterer Live-Lauf nie Ergebnis-Posts zu Coins schreibt, die nie öffentlich gecallt wurden.
DRY = CFG["dry_run"] or os.environ.get("CLIPERZ_DRY") == "1"; now = dt.datetime.now(dt.timezone.utc)
CALLS = f"{ROOT}/calls-dry.csv" if DRY else f"{ROOT}/calls.csv"
STATE = f"{ROOT}/state-dry" if DRY else f"{ROOT}/state"

def http(url, data=None, headers=None, method=None):
    req = r.Request(url, data, {"User-Agent": "Mozilla/5.0 (compatible; cliperz-bot/1.0)", "Accept": "application/json", **(headers or {})}, method=method)
    for attempt in range(3):   # retry brief connection drops (HTTP errors such as 429 are handled by the callers)
        try: return json.load(r.urlopen(req, timeout=20))
        except urllib.error.HTTPError: raise
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            if attempt == 2: raise
            time.sleep(2 * (attempt + 1))

def http_text(url, headers=None):
    """GET returning text (for RSS feeds). Same retry behaviour as http()."""
    req = r.Request(url, None, {"User-Agent": "Mozilla/5.0 (compatible; cliperz-bot/1.0)", **(headers or {})})
    for attempt in range(3):
        try: return r.urlopen(req, timeout=20).read().decode("utf-8", "replace")
        except urllib.error.HTTPError: raise
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            if attempt == 2: raise
            time.sleep(2 * (attempt + 1))

def token():
    """Current X access token. The refresh time is stored INSIDE the login file ("obtained_at") so it survives being copied to another machine
    (file timestamps do not); the file timestamp is only a fallback for older files."""
    t = json.load(open(TOK))
    obtained = t.get("obtained_at") or os.path.getmtime(TOK)
    if time.time() - obtained > t.get("expires_in", 7200) - 300:  # refresh
        cid, sec = cliperz_keys.load()
        a = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        try:
            t = http("https://api.x.com/2/oauth2/token", u.urlencode(dict(grant_type="refresh_token",
                     refresh_token=t["refresh_token"], client_id=cid)).encode(),
                     {"Authorization": "Basic " + a, "Content-Type": "application/x-www-form-urlencoded"})
        except urllib.error.HTTPError as ex:   # tell the owner once an hour why the X login cannot refresh (no secrets in the message)
            try: body = ex.read().decode()[:200]
            except Exception: body = ""
            mark = f"{STATE}/refresh-alert"; os.makedirs(STATE, exist_ok=True)
            if not os.path.exists(mark) or time.time() - os.path.getmtime(mark) > 3600:
                open(mark, "w").close()
                owner_msg(f"⚠️ X login could not refresh (HTTP {ex.code}). X says: {body}\nClient id length {len(cid)}, secret length {len(sec)}. "
                          "401 usually means the X client id/secret saved in GitHub secrets is wrong. Nothing can post until it is fixed.")
            raise
        t["obtained_at"] = time.time()
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

def owner_msg(text):
    """Private Telegram message to the account owner (reports and alerts). Needs the owner to press Start on the bot once.
    Never raises, never posts anything public."""
    try:
        tok = cliperz_keys.optional("TELEGRAM_BOT_TOKEN")
        if not tok or DRY: return
        base = f"https://api.telegram.org/bot{tok}/"
        oid = cliperz_keys.optional("TELEGRAM_OWNER_CHAT_ID")
        if not oid:   # find the private chat of whoever pressed Start, and remember it
            for u in http(base + "getUpdates")["result"]:
                m = u.get("message") or {}
                if (m.get("chat") or {}).get("type") == "private": oid = str(m["chat"]["id"])
            if not oid: return
            open(cliperz_keys.KEYS, "a").write(f"\nTELEGRAM_OWNER_CHAT_ID={oid}\n")
        http(base + "sendMessage", json.dumps({"chat_id": oid, "text": text[:3900], "disable_web_page_preview": True}).encode(), {"Content-Type": "application/json"})
    except Exception:
        pass

def owner_alert(key, text, every=3600):
    """Private alert that repeats at most once per `every` seconds for the same key, so a problem that persists cannot flood the owner's chat."""
    try:
        os.makedirs(STATE, exist_ok=True); mark = f"{STATE}/alert-{re.sub('[^A-Za-z0-9]', '_', key)[:60]}"
        if os.path.exists(mark) and time.time() - os.path.getmtime(mark) < every: return
        open(mark, "w").close()
    except Exception: pass
    owner_msg(text)

def tg_send(text, image=None, tweet_id=None):
    """Mirrors a post to the Telegram channel. Never raises: a Telegram problem must not affect X posting."""
    try:
        tok, chat = cliperz_keys.optional("TELEGRAM_BOT_TOKEN"), cliperz_keys.optional("TELEGRAM_CHAT_ID")
        if not tok or not chat: return
        lk = CFG.get("community_link")
        if lk: text = "\n".join(l for l in text.split("\n") if lk not in l).rstrip()   # no "join us" line inside the community itself
        link = f"\n\nhttps://x.com/{CFG.get('handle', 'Cliperzcoins711')}/status/{tweet_id}" if str(tweet_id).isdigit() else ""
        caption = (text + link)[:1000]
        if DRY: print(f"[TG dry] {caption[:80]!r}"); return
        base = f"https://api.telegram.org/bot{tok}/"
        if image and os.path.exists(image):
            import uuid
            b = uuid.uuid4().hex
            def part(n, v, fn=None, ct=None):
                h = f'--{b}\r\nContent-Disposition: form-data; name="{n}"' + (f'; filename="{fn}"' if fn else "") + "\r\n" + (f"Content-Type: {ct}\r\n" if ct else "") + "\r\n"
                return h.encode() + (v if isinstance(v, bytes) else v.encode()) + b"\r\n"
            body = part("chat_id", chat) + part("caption", caption) + part("photo", open(image, "rb").read(), "card.png", "image/png") + f"--{b}--\r\n".encode()
            http(base + "sendPhoto", body, {"Content-Type": f"multipart/form-data; boundary={b}"})
        else:
            http(base + "sendMessage", json.dumps({"chat_id": chat, "text": caption, "disable_web_page_preview": True}).encode(), {"Content-Type": "application/json"})
        print("[TG] mirrored to Telegram")
    except Exception as e:
        print(f"[TG] could not mirror to Telegram ({type(e).__name__}); X post is unaffected")

def post(text, reply_to=None, media=None, image=None, mirror=True, quote_id=None):
    print(("[DRY RUN] " if DRY else "[POST] ") + text + (f"\n[+ image {media}]" if media else "") + "\n")
    if DRY:
        if mirror: tg_send(text, image, "dry")
        return "dry-" + str(int(time.time()))
    body = {"text": text}
    if media: body["media"] = {"media_ids": [media]}
    if reply_to and str(reply_to).isdigit(): body["reply"] = {"in_reply_to_tweet_id": reply_to}
    if quote_id and str(quote_id).isdigit(): body["quote_tweet_id"] = str(quote_id)
    tid = http("https://api.x.com/2/tweets", json.dumps(body).encode(),
               {"Authorization": "Bearer " + token(), "Content-Type": "application/json"})["data"]["id"]
    if mirror: tg_send(text, image, tid)
    return tid

def rows():
    if not os.path.exists(CALLS): return []
    return list(csv.DictReader(open(CALLS)))
def save(rs):
    w = csv.DictWriter(open(CALLS, "w", newline=""), FIELDS); w.writeheader(); w.writerows(rs)

def fmt(n): return f"${n/1000:.0f}k" if n < 1e6 else f"${n/1e6:.2f}m"
PAIRS = {}   # contract -> (fetched_at, best pair or None); filled 30 at a time so a scan makes a few requests instead of ~100

def prefetch(addrs):
    """Fetch many coins at once from DexScreener's batch endpoint (30 per request) into the cache that pair() reads."""
    todo = [a for a in dict.fromkeys(addrs) if a not in PAIRS or time.time() - PAIRS[a][0] > 60]
    for i in range(0, len(todo), 30):
        chunk = todo[i:i + 30]
        try: ps = http("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(chunk))
        except Exception: continue
        best = {}
        for q in ps:
            a = (q.get("baseToken") or {}).get("address")
            if a and (a not in best or (q.get("liquidity") or {}).get("usd", 0) > (best[a].get("liquidity") or {}).get("usd", 0)): best[a] = q
        for a in chunk: PAIRS[a] = (time.time(), best.get(a))

def pair(addr):
    hit = PAIRS.get(addr)
    if hit and time.time() - hit[0] <= 60: return hit[1]
    ps = http(f"https://api.dexscreener.com/latest/dex/tokens/{addr}").get("pairs") or []
    ps = [p for p in ps if p["chainId"] == CFG["chain"]]
    return max(ps, key=lambda p: (p.get("liquidity") or {}).get("usd", 0)) if ps else None

def name_ok(*names):
    """False if a coin's ticker or name contains a crude or offensive word. Short words must match as whole words (so 'assume' is fine)."""
    import re
    text = " ".join(n for n in names if n).lower()
    for w in CFG.get("blocked_name_words", []):
        if (len(w) <= 4 and re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text)) or (len(w) > 4 and w in text): return False
    return True

def gt_trending(ttl=300):
    """GeckoTerminal trending/top pools. These lists change slowly, so they are fetched at most every 5 minutes (5 requests) and reused between
    cycles; the fast-moving DexScreener lists are fetched every cycle. This is what cut most of our GeckoTerminal rate-limit trouble."""
    f = f"{STATE}/gt_addrs.json"; ch = CFG["chain"]
    try:
        c = json.load(open(f))
        if time.time() - c["t"] < ttl and c["a"]: return list(c["a"])
    except Exception: pass
    out = []
    for path in ("trending_pools?page=1", "trending_pools?page=2", "trending_pools?duration=1h&page=1", "trending_pools?duration=6h&page=1",
                 "pools?sort=h24_volume_usd_desc&page=1"):
        try:
            for p in gt_get(f"https://api.geckoterminal.com/api/v2/networks/{ch}/{path}")["data"]:
                out.append(p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1])
        except Exception: pass
    if out:
        try: os.makedirs(STATE, exist_ok=True); json.dump({"t": time.time(), "a": out}, open(f, "w"))
        except Exception: pass
    return out

_ADDR = [0.0, []]; _SRC = {}      # contract -> which source first listed it (logged with every candidate, so we can see which sources find winners)
def candidate_addresses():
    """Where we look for coins: DexScreener's newest profiles and boosted lists, and GeckoTerminal's trending pools (default, 1h, 6h)
    plus the top pools by 24h volume. Deduplicated. More sources = more coins to judge, every one still goes through the same filters."""
    if time.time() - _ADDR[0] < 90 and _ADDR[1]: return list(_ADDR[1])    # one shared scan per cycle
    try:   # a new process starts every cycle: reuse the list from the previous cycle if it is under 2 minutes old (halves the GeckoTerminal requests)
        c = json.load(open(f"{STATE}/addrs.json"))
        if time.time() - c["t"] < 120 and c["a"]: _ADDR[0], _ADDR[1] = c["t"], c["a"]; _SRC.update(c.get("s") or {}); return list(c["a"])
    except Exception: pass
    out = []
    ch = CFG["chain"]
    for label, url in (("dex_profile", "https://api.dexscreener.com/token-profiles/latest/v1"), ("dex_boost", "https://api.dexscreener.com/token-boosts/latest/v1"),
                       ("dex_top_boost", "https://api.dexscreener.com/token-boosts/top/v1")):
        try:
            got = [p["tokenAddress"] for p in http(url) if p.get("chainId") == ch]; out += got
            for a in got: _SRC.setdefault(a, label)
        except Exception: pass
    gt = gt_trending(); out += gt
    for a in gt: _SRC.setdefault(a, "gt_trending")
    out = list(dict.fromkeys(out)); _ADDR[0] = time.time(); _ADDR[1] = out
    try: os.makedirs(STATE, exist_ok=True); json.dump({"t": time.time(), "a": out, "s": {a: _SRC[a] for a in out if a in _SRC}}, open(f"{STATE}/addrs.json", "w"))
    except Exception: pass
    return list(out)

def quality_score(q, mc, liq, vol):
    """0-100 ranking of a coin that already passed the hard filters: buying pressure, liquidity depth, healthy liquidity/mcap,
    momentum in a sweet spot (rising, not exhausted), and sane volume. It orders candidates and sets a minimum bar (min_score)."""
    tx = (q.get("txns") or {}).get("h1", {}); b, sl = tx.get("buys", 0), tx.get("sells", 0); pc = q.get("priceChange") or {}
    h1, m5 = pc.get("h1", 0) or 0, pc.get("m5", 0) or 0
    sc = min(b / max(sl, 1), 2.5) / 2.5 * 30                      # buying pressure
    sc += min(liq / 60000, 1) * 20                                # liquidity depth
    sc += min((liq / mc) / 0.4, 1) * 10 if mc else 0              # liquidity relative to size
    sc += 20 if 5 <= h1 <= 40 else 10 if (0 <= h1 < 5 or 40 < h1 <= 60) else 0     # momentum sweet spot
    sc += 10 if m5 >= 0 else 0                                    # still moving up right now
    ratio = vol / mc if mc else 99
    sc += 10 if 2 <= ratio <= 12 else 5 if ratio < 2 else 0       # volume neither dead nor wash-like
    return round(sc)

def market_reasons(q, age):
    """Every normal-tier market filter a coin fails (empty list = passes). One place for the rules, used by the scan, the digest and the near-miss log."""
    C = CFG; mc = q.get("marketCap") or 0; liq = (q.get("liquidity") or {}).get("usd", 0); vol = (q.get("volume") or {}).get("h24", 0)
    tx = (q.get("txns") or {}).get("h1", {}); b, sl = tx.get("buys", 0), tx.get("sells", 0); pc = q.get("priceChange") or {}; why = []
    if not C["min_mcap_usd"] <= mc <= C["max_mcap_usd"]: why.append("mcap out of $20-300k")
    if liq < C["min_liquidity_usd"]: why.append(f"liq<${C['min_liquidity_usd']/1000:.0f}k")
    if vol < C["min_volume_24h_usd"]: why.append("vol<$50k")
    if not C["min_age_hours"] <= age <= C["max_age_hours"]: why.append("age out of range")
    if not C.get("min_h1_change_pct", -5) < (pc.get("h1", 0) or 0) <= C.get("max_h1_change_pct", 40): why.append("1h move out of range")
    if (pc.get("m5", 0) or 0) <= C.get("min_m5_change_pct", -5): why.append("dumping")
    if b <= sl: why.append("sells >= buys")
    if b < C.get("min_buy_ratio", 1.3) * max(sl, 1): why.append("weak buy ratio")
    if b + sl < 200: why.append("<200 trades")
    if mc and vol > mc * C.get("max_vol_mcap_ratio", 15): why.append("wash volume")
    if mc and liq / mc <= 0.05: why.append("thin liquidity vs mcap")
    return why

def log_near_miss(q, age, reason, per_day=40):
    """Paper-trade log of coins that failed exactly ONE filter (and are not junk): their outcome later tells us whether that filter is too strict."""
    mc = q.get("marketCap") or 0; liq = (q.get("liquidity") or {}).get("usd", 0)
    if mc < 10000 or liq < 5000: return
    today = str(now.date()); n = sum(1 for r in cand_rows() if r.get("decision") == "nearmiss" and (r.get("eval_utc") or "").startswith(today))
    if n < per_day: log_candidate(q["baseToken"]["address"], q, age * 60, None, "nearmiss", reason, tier="normal")

def candidates():
    seen = {x["contract"] for x in rows()}
    addrs = [a for a in candidate_addresses() if a not in seen]; prefetch(addrs)
    for addr in addrs:
        q = pair(addr)
        if not q or not q.get("pairCreatedAt"): continue
        if not name_ok(q["baseToken"].get("symbol"), q["baseToken"].get("name")): continue
        age = (now.timestamp() * 1000 - q["pairCreatedAt"]) / 3.6e6
        why = market_reasons(q, age)
        if why:
            if len(why) == 1: log_near_miss(q, age, why[0])
            continue
        mc, liq, vol = q.get("marketCap") or 0, (q.get("liquidity") or {}).get("usd", 0), (q.get("volume") or {}).get("h24", 0)
        sc = quality_score(q, mc, liq, vol)
        if sc < CFG.get("min_score", 0): continue
        yield sc, q, mc, liq, age

def safety_gt(ca):
    """Contract safety gate via GeckoTerminal token info. Returns (ok, reason, summary). Fails closed when data is missing."""
    info = None
    for attempt in range(3):
        try:
            info = http(f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{ca}/info")["data"]["attributes"]; break
        except Exception as e:
            time.sleep(3 * (attempt + 1))
    if not info: return False, "no safety data", ""
    for k, name in (("mint_authority", "mint"), ("freeze_authority", "freeze")):
        v = info.get(k)
        if v is None: return False, f"{name} authority UNKNOWN (no data yet)", ""
        if v != "no": return False, f"{name} authority NOT revoked", ""
    if str(info.get("is_honeypot")).lower() == "yes": return False, "honeypot flag", ""
    h = info.get("holders") or {}
    try: cnt = int(h.get("count") or 0); top10 = float((h.get("distribution_percentage") or {}).get("top_10") or 100)
    except Exception: return False, "no holder data", ""
    if not cnt: return False, "holder data UNKNOWN (no data yet)", ""
    if cnt < 100: return False, f"only {cnt} holders", ""
    if top10 > 55: return False, f"top 10 holders own {top10:.0f}%", ""
    return True, "ok", f"mint+freeze revoked | {cnt} holders | top10 {top10:.0f}%"

CTA = [
    "Why follow @{h}? Every call is logged with the market cap at the time, and results get posted: wins and losses. Join the community: {link}",
    "What you get here: calls with a card and the contract, a safety check before each post, and a public record of how they do. Community: {link}",
    "We track every call-out and post the results, good or bad. Follow for the next one, and join the group to talk through them: {link}",
    "No hype, just logged calls: market cap at the call, peak results, and the misses too. Follow @{h} and join the community: {link}",
]

def cta_reply(tid, n):
    """Self-reply under a top-level post explaining why to follow and join the community. Wording rotates; never mirrored to Telegram."""
    if not CFG.get("cta_enabled") or not CFG.get("community_link"): return
    try: post(CTA[n % len(CTA)].format(h=CFG.get("handle", "Cliperzcoins711"), link=CFG["community_link"]), reply_to=tid, mirror=False)
    except Exception as e: print(f"[WARN] community comment failed ({type(e).__name__}); main post is unaffected")

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
        print(f"[SKIP] could not make/upload the card ({e!r}); not posting a text-only call"); owner_alert(f"card-{sym}", f"⚠️ Could not make/upload the card for ${sym}; call NOT posted (retrying every cycle, this alert repeats at most hourly). Cause: {e!r}"); return
    tid = post(text, media=media, image=png)
    rs.append(dict(id=n, token=sym, chain=CFG["chain"], contract=ca, called_at_utc=now.isoformat(), mcap_at_call=mc,
                   tweet_id=tid, status="open", current_mcap=mc, multiple=1.0, notes=tier))
    save(rs)
    owner_msg(f"🚀 NEW CALL #{n} ${sym}{' (EARLY)' if tier else ''} at {fmt(mc)}\nhttps://x.com/{CFG.get('handle', 'Cliperzcoins711')}/status/{tid}")
    cta_reply(tid, n)

def xlen(t):
    """Length as X counts it: every URL is 23 characters."""
    import re
    return len(re.sub(r"https?://\S+", "x" * 23, t))

def call_text(sym, mc, liq, age, q, safe, ca):
    """Call-out text ending with the follow/join line. Tries the fuller wording first and tightens until it fits in 280."""
    cta = CFG["cta_text"].format(link=CFG["community_link"]) if CFG.get("cta_in_post") and CFG.get("community_link") else ""
    why = [f"Why: buys > sells last hour, 24h vol {fmt(q['volume']['h24'])}, liq/mcap {liq/mc:.0%}",
           f"Why: buys > sells (1h), vol {fmt(q['volume']['h24'])}, liq/mcap {liq/mc:.0%}", "Why: buys > sells (1h)"]
    safety = [f"Safety: {safe}. Still new, can rug.", f"Safety: {safe.replace(' | ', ', ')}. Can rug."]
    for w in why:
        for sf in safety:
            t = f"${sym} (Solana)\nMcap: {fmt(mc)} | Liq: {fmt(liq)} | Age: {age:.0f}h\n{w}\n{sf}\nCA: {ca}" + (f"\n{cta}" if cta else "")
            if xlen(t) <= 274: return t
    return f"${sym} (Solana)\nMcap: {fmt(mc)} | Liq: {fmt(liq)}\nCA: {ca}" + (f"\n{cta}" if cta else "")

def rugcheck(ca):
    """RugCheck full report for a Solana token, or None if it cannot be read. Retries when rate limited."""
    for i in range(3):
        try: return http(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report", headers={"Accept": "application/json"})
        except Exception as e:
            if getattr(e, "code", None) in (429, 500, 502, 503) and i < 2: time.sleep(4 * (i + 1)); continue
            return None

RC_LAST = {}   # contract -> last RugCheck report (used to log features for the candidates file)

def safety_rc(ca, min_holders=100, max_score=20):
    """RugCheck verdict: (ok, reason, summary), or None when RugCheck has no report for the token."""
    d = rugcheck(ca)
    if not d or "risks" not in d: return None
    RC_LAST[ca] = d
    if d.get("rugged"): return False, "RugCheck marks it rugged", ""
    if d.get("mintAuthority"): return False, "mint authority is ACTIVE (more supply can be created)", ""
    if d.get("freezeAuthority"): return False, "freeze authority is ACTIVE", ""
    for r in d.get("risks") or []:
        if r.get("level") == "danger": return False, f"RugCheck danger: {r.get('name')}", ""
    holders = int(d.get("totalHolders") or 0)
    if holders < min_holders: return False, f"only {holders} holders", ""
    score = d.get("score_normalised", d.get("score", 100))
    if score is not None and float(score) > max_score: return False, f"RugCheck risk score {score}", ""
    tf = d.get("transferFee") or {}
    if float(tf.get("pct", 0) or 0) > 5: return False, f"transfer fee {tf.get('pct')}%", ""
    return True, "ok", f"mint+freeze revoked | {holders} holders | RugCheck: no risks"

def safety(ca):
    """Contract safety gate: RugCheck first, GeckoTerminal data as a fallback. Fails closed whenever it cannot verify."""
    v = safety_rc(ca)
    return v if v is not None else safety_gt(ca)

def off_high(q):
    """Price now as a share of the highest 5-minute close in the last hour (None if the chart is unavailable). Low = already dumping from its high."""
    try:
        d = gt_get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{q['pairAddress']}/ohlcv/minute?aggregate=5&limit=12&currency=usd")
        cl = [c[4] for c in d["data"]["attributes"]["ohlcv_list"] if c[4]]
        return float(q["priceUsd"]) / max(cl) if cl else None
    except Exception:
        return None

def _vet(c, early=False):
    """Safety gate plus the dump filter for one candidate (run in parallel). Returns (ok, why, summary)."""
    ca = c[1]["baseToken"]["address"]
    ok, why, summ = early_safety(ca) if early else safety(ca)
    if ok:
        r = off_high(c[1]); lim = CFG.get("max_dump_from_high_pct", 25)
        if r is not None and r < 1 - lim / 100: return False, f"already {100 * (1 - r):.0f}% off its 1-hour high (dumping)", ""
    return ok, why, summ

def vet_all(cs, early=False):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex: return list(ex.map(lambda c: _vet(c, early), cs))

def confirmed(ca, mc):
    """A coin must still pass on a later cycle (at least confirm_seconds after first passing, market cap not falling) before a call posts."""
    f = f"{STATE}/confirm.json"; os.makedirs(STATE, exist_ok=True); t = time.time()
    try: d = json.load(open(f))
    except Exception: d = {}
    d = {k: v for k, v in d.items() if t - v["t"] < 1800}
    e = d.get(ca)
    if e is None or mc < 0.95 * e["mc"]: d[ca] = {"t": t, "mc": mc}; json.dump(d, open(f, "w")); return False
    json.dump(d, open(f, "w")); return t - e["t"] >= CFG.get("confirm_seconds", 100)

def call_out():
    rs = rows(); today = [x for x in rs if x["called_at_utc"][:10] == str(now.date()) and not x["notes"].startswith("EARLY")]
    if len(today) >= CFG["max_calls_per_day"]: return
    best = None; safe = ""
    top = sorted(candidates(), key=lambda c: -c[0])[:5]
    for c, (ok, why, summ) in zip(top, vet_all(top)):
        log_candidate(c[1]["baseToken"]["address"], c[1], c[4] * 60, None, "pass" if ok else "blocked", "" if ok else why, tier="normal", qscore=c[0])
        if ok: best, safe = c, summ; break
        print(f"[SKIP] {c[1]['baseToken']['symbol']}: {why}")
    if not best: return
    _, q, mc, liq, age = best; sym = q["baseToken"]["symbol"]; ca = q["baseToken"]["address"]
    if not confirmed(ca, mc): print(f"[WAIT] {sym}: passed, waiting for a second cycle to confirm"); return
    publish_call(q, mc, liq, call_text(sym, mc, liq, age, q, safe, ca))
    if any(x["contract"] == ca for x in rows()): mark_candidate(ca, "posted")

# ---------- EARLY tier: 15-60 min old tokens, clearly labelled high risk ----------
E = dict(min_age_min=CFG.get("early_min_age_min", 5), max_age_min=CFG.get("early_max_age_min", 45), min_mcap=CFG.get("early_min_mcap", 10000),
         max_mcap=CFG.get("early_max_mcap", 60000), min_liq=CFG.get("early_min_liq", 8000), buy_ratio=CFG.get("early_buy_ratio", 1.5),
         min_trades=CFG.get("early_min_trades", 100), max_per_day=CFG.get("early_max_per_day", 3), max_run_pct=CFG.get("early_max_run_pct", 100),
         pages=CFG.get("early_pages", 6), min_holders=CFG.get("early_min_holders", 50), max_score=CFG.get("early_max_score", 30))

def early_safety(ca):
    """New-pair tier: RugCheck must have a report. Thresholds are a little looser than normal calls (holders, risk score), but
    mint/freeze must be revoked and any RugCheck 'danger' flag still blocks. No weaker fallback for brand-new tokens."""
    v = safety_rc(ca, min_holders=E["min_holders"], max_score=E["max_score"])
    return v if v is not None else (False, "no RugCheck report yet", "")

_GT_LOCK = threading.Lock(); _GT_LAST = [0.0]; _GT_COOL = [0.0]; GT_STATS = [0, 0]; GT_SPACING = 1.2     # seconds between GeckoTerminal request starts (bulk jobs raise this)   # [requests, rate-limited (429) answers], printed in the [TIMING] line
def gt_get(url, tries=4):
    """GeckoTerminal GET: starts are spaced ~1.2 s apart across all threads (free limit ~30/min), and it waits and retries when rate limited (HTTP 429)."""
    for i in range(tries):
        with _GT_LOCK:
            wait = max(GT_SPACING - (time.time() - _GT_LAST[0]), _GT_COOL[0] - time.time())     # spacing, plus a shared pause after any 429
            if wait > 0: time.sleep(wait)
            _GT_LAST[0] = time.time(); GT_STATS[0] += 1
        try: return http(url)
        except Exception as e:
            if getattr(e, "code", None) == 429: GT_STATS[1] += 1
            if getattr(e, "code", None) == 429 and i < tries - 1: _GT_COOL[0] = time.time() + max(6, GT_SPACING * 4) * (i + 1); continue    # all threads pause, none sleeps alone
            raise

CAND_FIELDS = "ca,symbol,eval_utc,age_m,mcap,liq,holders,score,flags,buys,sells,m5,h1,run_pct,decision,reason,price0,m1h,m3h,m6h,tier,qscore,src,top1,top10,insiders,creator_prior,lp_locked,lp_providers,launchpad".split(",")

def cand_rows():
    f = f"{STATE}/candidates.csv"
    return list(csv.DictReader(open(f))) if os.path.exists(f) else []

def cand_save(rs):
    os.makedirs(STATE, exist_ok=True)
    w = csv.DictWriter(open(f"{STATE}/candidates.csv", "w", newline=""), CAND_FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(rs)

def rc_features(d):
    """Extra signals from a RugCheck report, logged with every candidate so later analysis can test them (holder concentration, insider networks,
    creator history, LP lock). Pool/AMM accounts are excluded from the holder shares. Never raises; missing data gives empty strings."""
    out = dict(top1="", top10="", insiders="", creator_prior="", lp_locked="", lp_providers="", launchpad="")
    try:
        known = d.get("knownAccounts") or {}
        hs = [h for h in (d.get("topHolders") or []) if h.get("address") not in known and h.get("owner") not in known]
        pcts = sorted((float(h.get("pct") or 0) for h in hs), reverse=True)
        if pcts: out["top1"] = round(pcts[0], 1); out["top10"] = round(sum(pcts[:10]), 1)
        out["insiders"] = int(d.get("graphInsidersDetected") or 0)
        ct = d.get("creatorTokens"); out["creator_prior"] = len(ct) if isinstance(ct, list) else ""
        mk = d.get("markets") or []
        lk = [float((m.get("lp") or {}).get("lpLockedPct")) for m in mk if (m.get("lp") or {}).get("lpLockedPct") is not None]
        if lk: out["lp_locked"] = round(max(lk), 1)
        if d.get("totalLPProviders") is not None: out["lp_providers"] = int(d.get("totalLPProviders") or 0)
        lp = d.get("launchpad"); out["launchpad"] = (lp.get("name") if isinstance(lp, dict) else lp) or d.get("deployPlatform") or ""
    except Exception:
        pass
    return out

def log_candidate(ca, q, age_m, run, decision, reason, tier="early", qscore="", src=""):
    """Record a coin the first time it reaches the safety stage, with the features we may want to learn from. Outcomes are filled in later."""
    rs = cand_rows()
    old = [x for x in rs if x["ca"] == ca]
    if old:      # already logged: keep the first record, but remember that a news alert also flagged this coin
        if tier == "narrative" and not str(old[0].get("src") or "").startswith("news:") and not old[0].get("reason", "").startswith("also narrative"):
            old[0]["reason"] = f"also narrative: {reason} | {old[0].get('reason') or ''}"[:200]; cand_save(rs)
        return
    d = RC_LAST.get(ca) or {}; tx = (q.get("txns") or {}).get("h1", {}); pc = q.get("priceChange") or {}
    rs.append(dict(ca=ca, symbol=q["baseToken"]["symbol"], eval_utc=now.isoformat(timespec="seconds"), age_m=round(age_m), mcap=round(q.get("marketCap") or 0),
                   liq=round((q.get("liquidity") or {}).get("usd", 0)), holders=d.get("totalHolders", ""), score=d.get("score_normalised", ""),
                   flags="|".join(str(x.get("name")) for x in (d.get("risks") or []) if x.get("level") in ("danger", "warn")),
                   buys=tx.get("buys", ""), sells=tx.get("sells", ""), m5=pc.get("m5", ""), h1=pc.get("h1", ""), run_pct=round(run * 100) if run is not None else "",
                   decision=decision, reason=reason, price0=q.get("priceUsd", ""), m1h="", m3h="", m6h="", tier=tier, qscore=qscore,
                   src=src or _SRC.get(ca) or ("gt_new_pools" if tier == "early" else ""), **rc_features(d)))
    cand_save(rs)

def mark_candidate(ca, decision):
    rs = cand_rows()
    for x in rs:
        if x["ca"] == ca: x["decision"] = decision
    cand_save(rs)

def track_candidates():
    """Fill in how each logged candidate did 1h / 3h / 6h later (price multiple vs its price when evaluated; 0 = liquidity gone)."""
    rs = cand_rows(); due = []
    for x in rs:
        el = (now - dt.datetime.fromisoformat(x["eval_utc"])).total_seconds() / 3600
        need = [k for k, h in (("m1h", 1), ("m3h", 3), ("m6h", 6)) if not x[k] and el >= h]
        if need and x["price0"]: due.append((x, need))
    if not due: return
    for i in range(0, len(due), 30):
        chunk = due[i:i + 30]
        try: pairs = http("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(x["ca"] for x, _ in chunk))
        except Exception: continue
        best = {}
        for q in pairs:
            ca = q["baseToken"]["address"]
            if ca not in best or (q.get("liquidity") or {}).get("usd", 0) > (best[ca].get("liquidity") or {}).get("usd", 0): best[ca] = q
        for x, need in chunk:
            q = best.get(x["ca"]); liq = (q.get("liquidity") or {}).get("usd", 0) if q else 0
            try: mult = 0.0 if (not q or liq < 1000) else round(float(q["priceUsd"]) / float(x["price0"]), 2)
            except Exception: continue
            for k in need: x[k] = mult
    cand_save(rs)

def early_candidates():
    """GeckoTerminal's new-pools list only reaches a few minutes back, so we keep a watchlist: note every new pool with real liquidity
    and its price at first sight (state/watch.json), then re-check each one while it is 5-45 min old using DexScreener's batch endpoint.
    A coin that has already run up more than early_max_run_pct since first sight is skipped (that is calling after the move)."""
    seen = {x["contract"] for x in rows()}
    wf = f"{STATE}/watch.json"; os.makedirs(STATE, exist_ok=True)
    try: raw = json.load(open(wf))
    except Exception: raw = {}
    watch = {ca: (v if isinstance(v, dict) else {"t": v, "p0": None}) for ca, v in raw.items()}   # older files stored just the timestamp
    for pg in range(1, E["pages"] + 1):
        try: d = gt_get(f"https://api.geckoterminal.com/api/v2/networks/solana/new_pools?page={pg}")["data"]
        except Exception: break
        for p in d:
            a = p["attributes"]
            try:
                created = dt.datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00")).timestamp()
                ca = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
                if float(a["reserve_in_usd"]) >= 4000 and ca not in watch:
                    watch[ca] = {"t": created, "p0": float(a.get("base_token_price_usd") or 0) or None}
            except Exception: continue
    t_now = now.timestamp()
    watch = {ca: w for ca, w in watch.items() if (t_now - w["t"]) / 60 <= 90}          # forget anything older than 90 min
    json.dump(watch, open(wf, "w"))
    due = [ca for ca, w in watch.items() if E["min_age_min"] <= (t_now - w["t"]) / 60 <= E["max_age_min"] and ca not in seen]
    for i in range(0, len(due), 30):
        try: pairs = http("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(due[i:i + 30]))
        except Exception: continue
        best = {}
        for q in pairs:
            ca = q["baseToken"]["address"]
            if ca not in best or (q.get("liquidity") or {}).get("usd", 0) > (best[ca].get("liquidity") or {}).get("usd", 0): best[ca] = q
        for ca, q in best.items():
            if not name_ok(q["baseToken"].get("symbol"), q["baseToken"].get("name")): continue
            w = watch[ca]; age_m = (t_now - w["t"]) / 60
            mc, liq = q.get("marketCap") or 0, (q.get("liquidity") or {}).get("usd", 0)
            tx = (q.get("txns") or {}).get("h1", {}); b, sl = tx.get("buys", 0), tx.get("sells", 0); pc = q.get("priceChange") or {}
            try: run = float(q["priceUsd"]) / w["p0"] - 1 if w.get("p0") else None
            except Exception: run = None
            if run is not None and run * 100 > E["max_run_pct"]: continue            # already ran: do not chase
            if (E["min_mcap"] <= mc <= E["max_mcap"] and liq >= E["min_liq"] and b >= E["buy_ratio"] * max(sl, 1)
                    and b + sl >= E["min_trades"] and pc.get("m5", 0) > 0 and liq / mc > 0.1):
                yield b / max(sl, 1), q, mc, liq, age_m, run

def early_call_out():
    if not CFG.get("early_enabled", True): return
    rs = rows()
    if len([x for x in rs if x["called_at_utc"][:10] == str(now.date()) and x["notes"].startswith("EARLY")]) >= E["max_per_day"]: return
    top = sorted(early_candidates(), key=lambda c: -c[0])[:5]
    for c, (ok, why, safe) in zip(top, vet_all(top, early=True)):
        _, q, mc, liq, age_m, run = c; ca = q["baseToken"]["address"]; sym = q["baseToken"]["symbol"]
        log_candidate(ca, q, age_m, run, "pass" if ok else "blocked", "" if ok else why)
        if not ok: print(f"[SKIP early] {sym}: {why}"); continue
        if not confirmed(ca, mc): print(f"[WAIT early] {sym}: passed, waiting for a second cycle to confirm"); return
        tx = q["txns"]["h1"]
        cta = CFG["cta_text"].format(link=CFG["community_link"]) if CFG.get("cta_in_post") and CFG.get("community_link") else ""
        m5 = q["priceChange"].get("m5", 0)
        for why in (f"{tx['buys']} buys vs {tx['sells']} sells, 5m {m5:+.0f}%", f"buys {tx['buys']}/{tx['sells']} sells"):
            for sf in (f"Safety: {safe}. Very new, most fail.", f"Safety: {safe.replace(' | ', ', ')}. Can rug."):
                text = f"EARLY / HIGH RISK\n${sym} (Solana)\nMcap: {fmt(mc)} | Liq: {fmt(liq)} | Age: {age_m:.0f}m\nWhy: {why}\n{sf}\nCA: {ca}" + (f"\n{cta}" if cta else "")
                if xlen(text) <= 274: break
            else: continue
            break
        publish_call(q, mc, liq, text, tier="EARLY")
        if any(x["contract"] == ca for x in rows()): mark_candidate(ca, "posted")
        return

def peak_since(q, called_iso):
    """Highest market cap since the call, from 5-min price candles (GeckoTerminal). Uses candle highs but never more than
    1.25x the best candle close, so a one-off bad wick cannot inflate a result. Returns None if history is unavailable."""
    try:
        pool, price, mc = q["pairAddress"], float(q["priceUsd"]), float(q["marketCap"])
        d = gt_get(f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/minute?aggregate=5&limit=1000&currency=usd")
        t0 = dt.datetime.fromisoformat(called_iso).timestamp() - 300
        cs = [c for c in d["data"]["attributes"]["ohlcv_list"] if c[0] >= t0]
        if not cs or price <= 0: return None
        hi, cl = max(c[2] for c in cs), max(c[4] for c in cs)
        return mc * min(hi, 1.25 * cl) / price
    except Exception:
        return None

def record_rug():
    """Circuit breaker: if N calls rug within 24h, pause all posting (STOP file) and tell the owner. The owner resumes by asking."""
    f = f"{STATE}/rug_events.json"
    try: ev = [t for t in json.load(open(f)) if now.timestamp() - t < 86400]
    except Exception: ev = []
    ev.append(now.timestamp()); json.dump(ev, open(f, "w"))
    if len(ev) >= CFG.get("circuit_breaker_rugs", 2) and not DRY:
        open(f"{ROOT}/STOP", "w").write("circuit breaker")
        owner_msg(f"⛔ CIRCUIT BREAKER: {len(ev)} calls rugged within 24h. All posting is PAUSED. Tell Claude 'resume' once you have looked at it.")

def _far_below(x, mc):
    """True when a call is so far under its peak (or its call price) that it cannot be setting a new peak this cycle, so the chart-history lookup is skipped."""
    old_pk = float(x.get("peak_mcap") or 0); c0 = float(x["mcap_at_call"])
    return (old_pk >= c0 and mc < 0.8 * old_pk) or mc < 0.6 * c0

def track():
    rs = rows()
    prefetch([x["contract"] for x in rs if x["status"] == "open" or x["status"].startswith("hit")])
    PEAKS = {}; todo = []     # chart-history lookups run in parallel, and only for coins that could still be setting a new peak
    for x in rs:
        if x["status"] != "open" and not x["status"].startswith("hit"): continue
        q = pair(x["contract"])
        if not q: continue
        mc = float(q.get("marketCap") or 0); liq = float((q.get("liquidity") or {}).get("usd") or 0)
        if liq < 5000 or mc <= 0 or _far_below(x, mc): continue
        todo.append((x["id"], q, x["called_at_utc"]))
    if todo:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(3) as ex:
            for (i, _, _), r_ in zip(todo, ex.map(lambda t: peak_since(t[1], t[2]), todo)): PEAKS[i] = r_
    for x in rs:
        if x["status"] not in ("open",) and not x["status"].startswith("hit"): continue
        q = pair(x["contract"]); mc = float((q or {}).get("marketCap") or 0)
        liq_now = float(((q or {}).get("liquidity") or {}).get("usd") or 0); m5 = float(((q or {}).get("priceChange") or {}).get("m5") or 0)
        try:   # liquidity-drain alert to the owner (private): a called coin lost >30% of its best liquidity and is now under $12k
            lf = f"{STATE}/liqmax.json"; lm = json.load(open(lf)) if os.path.exists(lf) else {}
            e = lm.setdefault(str(x["id"]), {"max": 0, "alerted": False}); e["max"] = max(e["max"], liq_now)
            if q and liq_now < 12000 and liq_now < 0.7 * e["max"] and not e["alerted"] and x["status"] != "rugged":
                e["alerted"] = True; owner_msg(f"⚠️ Liquidity draining on ${x['token']}: ${liq_now/1000:.1f}k (was ${e['max']/1000:.1f}k). Possible rug.")
            json.dump(lm, open(lf, "w"))
        except Exception: pass
        if not q or liq_now < 1000 or m5 <= -80:      # liquidity pulled / price collapsed: it is a rug, never a "result"
            if x["status"] != "rugged":
                owner_msg(f"⚠️ ${x['token']} RUGGED: liquidity pulled or price collapsed. Logged as a loss."); record_rug()
            x["status"] = "rugged"; x["current_mcap"] = 0; x["multiple"] = 0.0; continue
        x["current_mcap"] = mc; x["multiple"] = round(mc / float(x["mcap_at_call"]), 2)
        if liq_now < 5000 or x["multiple"] > 1000: continue   # untrustworthy numbers: no milestone posts
        # results show the PEAK multiple since the call (the most it could have gained), always labelled as a peak
        old_pk = float(x.get("peak_mcap") or 0)   # skip the slow chart-history lookup for coins far below their peak or call price (cannot be setting a new peak)
        far_below = _far_below(x, mc)
        ref = max(mc, float(x["mcap_at_call"]))
        if old_pk > 100 * ref: old_pk = ref                         # an absurd stored peak (bad chart data): heal it
        chart_pk = 0 if far_below else (PEAKS.get(x["id"]) or 0)
        if chart_pk > 20 * ref: chart_pk = 0                         # ignore an absurd chart peak instead of storing it
        pk = max(old_pk, mc, chart_pk)
        x["peak_mcap"] = round(pk); peak_mult = pk / float(x["mcap_at_call"])
        if peak_mult > 1000: continue
        hit = [m for m in CFG["result_milestones"] if peak_mult >= m]
        done = float(x["status"][3:].rstrip("x") or 0) if x["status"].startswith("hit") else 0
        if hit and hit[-1] > done:  # post once per new milestone
            text = (f"${x['token']}: called at {fmt(float(x['mcap_at_call']))}, peaked at {fmt(pk)} = {peak_mult:.1f}x\n"
                    f"Peak since the call. Tracked from the original post.")
            import subprocess
            png = f"{ROOT}/drafts/result-{x['id']}-{hit[-1]}x.png"; media = None
            try:   # milestone posts carry a result card; if the card or upload fails the result still goes out as text
                called = dt.datetime.fromisoformat(x["called_at_utc"]).strftime("%b %d, %H:%M UTC")
                subprocess.run([sys.executable, f"{ROOT}/bot/result_card.py", x["token"], f"{peak_mult:.1f}", f"{float(x['mcap_at_call'])/1000:.0f}",
                                f"{pk/1000:.0f}", called, png], check=True, timeout=90)
                media = "dry-media" if DRY else upload_image(png)
            except Exception as e:
                print(f"[WARN] result card failed ({e!r}); posting the result as text"); png = None
            post(text, reply_to=x["tweet_id"], media=media, image=png); x["status"] = f"hit{hit[-1]}x"
            owner_msg(f"🚀 MILESTONE {text}")
        elif mc < float(x["mcap_at_call"]) * 0.1 or not q: x["status"] = "dead"
        age = (now - dt.datetime.fromisoformat(x["called_at_utc"])).days
        if age >= 14 and (x["status"] == "open" or x["status"].startswith("hit")): x["status"] = "closed"
    save(rs)

def peak_mult(x):
    """Best multiple a call reached after it was posted: highest recorded market cap (never lowered) over the market cap at the call."""
    c0 = float(x["mcap_at_call"]); cur = float(x.get("current_mcap") or 0); r = max(float(x.get("peak_mcap") or 0), cur) / c0
    return r if r <= 100 else max(cur, c0) / c0          # a peak over 100x is treated as bad data, so no board can show a garbage multiple

def scoreboard():
    """Sunday leaderboard picture: the best PEAK multiples among the last 7 days of calls, i.e. what someone could have had by buying
    when we shared it. Labelled as peaks. Calls whose liquidity was pulled are not listed as wins, and nothing is posted about failures."""
    if now.weekday() != 6 or now.hour < 17: return  # Sundays from 17:00 UTC, once per day
    mark = f"{STATE}/scoreboard-{now.date()}"; os.makedirs(STATE, exist_ok=True)
    if os.path.exists(mark): return
    open(mark, "w").close()
    week = now - dt.timedelta(days=7)
    wk = [x for x in rows() if dt.datetime.fromisoformat(x["called_at_utc"]) >= week]
    top = sorted([x for x in wk if x["status"] != "rugged" and peak_mult(x) >= 1.25 and name_ok(x["token"])], key=lambda x: -peak_mult(x))[:10]
    if not top: os.remove(mark); return
    import subprocess
    rj = f"{STATE}/lb_rows.json"; png = f"{ROOT}/drafts/leaderboard-{now.date()}.png"
    json.dump([[x["token"], round(peak_mult(x), 2), x["notes"].startswith("EARLY")] for x in top], open(rj, "w"))
    foot = f"Top {len(top)} of {len(wk)} calls this week · peak after our call · NFA"
    try:
        subprocess.run([sys.executable, f"{ROOT}/bot/leaderboard.py", rj, str(len(wk)), png], check=True, timeout=90,
                       env={**os.environ, "LB_TITLE": "TOP CALLS", "LB_SUB": "PEAK MULTIPLES · THIS WEEK", "LB_FOOT": foot})
        media = "dry-media" if DRY else upload_image(png)
    except Exception as e:
        print(f"[SKIP] leaderboard picture failed ({e!r}); not posting a text-only leaderboard"); os.remove(mark); return
    lb = post(f"Top calls this week 🏆\nBest peak after each call: what you could have had buying when we shared it. Peaks, not current prices. NFA", media=media, image=png)
    cta_reply(lb, len(wk))

def _once_today(tag):
    """True the first time it is called on a given UTC day for this tag (state file marks it)."""
    os.makedirs(STATE, exist_ok=True); mark = f"{STATE}/{tag}-{now.date()}"
    if os.path.exists(mark): return False
    open(mark, "w").close(); return True

def daily_lesson(hour=14):
    """One short safety lesson per day from content/lessons.json, in order. Every third one also carries the community link."""
    if now.hour < hour or not _once_today("lesson"): return
    try:
        lessons = json.load(open(f"{ROOT}/content/lessons.json")); idxf = f"{STATE}/lesson_idx"
        i = int(open(idxf).read()) if os.path.exists(idxf) else 0
        text = lessons[i % len(lessons)]["text"]
        if i % 3 == 2 and CFG.get("community_link"):
            extra = f"\nCommunity: {CFG['community_link']}"
            if xlen(text + extra) <= 278: text += extra
        post(text); open(idxf, "w").write(str(i + 1))
    except Exception as e:
        print(f"[WARN] daily lesson failed ({e!r})")
        if getattr(e, "code", None) == 403:    # X refused it (duplicate text): skip to the next lesson and do not retry today
            open(idxf, "w").write(str(i + 1)); return
        os.remove(f"{STATE}/lesson-{now.date()}") if os.path.exists(f"{STATE}/lesson-{now.date()}") else None

def daily_recap(hour=21):
    """Daily picture: best PEAK multiples among the last 24h of calls, labelled as peaks, with how many calls and how many rugged."""
    if now.hour < hour: return
    day = now - dt.timedelta(hours=24)
    rs = [x for x in rows() if dt.datetime.fromisoformat(x["called_at_utc"]) >= day]
    if not rs or not _once_today("recap"): return
    peak = peak_mult
    top = sorted([x for x in rs if x["status"] != "rugged" and peak(x) > 1.0 and name_ok(x["token"])], key=lambda x: -peak(x))[:5]
    if not top: os.remove(f"{STATE}/recap-{now.date()}"); return
    import subprocess
    rj = f"{STATE}/recap_rows.json"; png = f"{ROOT}/drafts/recap-{now.date()}.png"
    json.dump([[x["token"], round(peak(x), 2), x["notes"].startswith("EARLY")] for x in top], open(rj, "w"))
    foot = f"Top {len(top)} of {len(rs)} calls in 24h · peak after our call · NFA"
    try:
        subprocess.run([sys.executable, f"{ROOT}/bot/leaderboard.py", rj, str(len(rs)), png], check=True, timeout=90,
                       env={**os.environ, "LB_TITLE": "DAILY RECAP", "LB_SUB": "PEAK MULTIPLES · LAST 24H", "LB_FOOT": foot})
        media = "dry-media" if DRY else upload_image(png)
    except Exception as e:
        print(f"[SKIP] recap picture failed ({e!r})"); os.remove(f"{STATE}/recap-{now.date()}"); return
    post(f"Daily recap 📊\n{len(rs)} calls in the last 24h. Best peaks shown, labeled as peaks (not current prices).\nCommunity: {CFG.get('community_link', '')}"[:280], media=media, image=png)

def scan_summary():
    """Short text: how many coins were looked at, why they fail, what passes the market filters and safety, and the closest near-misses.
    Uses the shared per-cycle scan (cached addresses and batch prices), so it costs almost no extra requests."""
    import collections
    C = CFG; seen = {x["contract"] for x in rows()}
    addrs = candidate_addresses(); prefetch([a for a in addrs if a not in seen])
    fails = collections.Counter(); passed = []; near = []
    for ca in addrs:
        if ca in seen: fails["already called"] += 1; continue
        q = pair(ca)
        if not q or not q.get("pairCreatedAt"): fails["no data"] += 1; continue
        age = (now.timestamp() * 1000 - q["pairCreatedAt"]) / 3.6e6
        mc = q.get("marketCap") or 0; liq = (q.get("liquidity") or {}).get("usd", 0); vol = (q.get("volume") or {}).get("h24", 0); why = market_reasons(q, age)
        if why:
            fails[why[0]] += 1
            if len(why) == 1 and mc >= 10000: near.append((vol, f"${q['baseToken']['symbol']} ({why[0]})"))
        else:
            ok, w, _ = safety(ca); passed.append(f"${q['baseToken']['symbol']} ${mc/1000:.0f}k liq ${liq/1000:.0f}k safety {'PASS' if ok else 'BLOCKED: ' + w}")
    out = f"{len(addrs)} candidate tokens | " + ", ".join(f"{v} {k}" for k, v in fails.most_common(4))
    out += "\nPASSED MARKET FILTERS: " + ("; ".join(passed) if passed else "none")
    if near: out += "\nNEAR-MISSES (fail one filter): " + ", ".join(n for _, n in sorted(near, reverse=True)[:3])
    try:
        tm = json.load(open(f"{STATE}/timings.json")); out += f"\nLast cycle {tm['total']:.0f}s: " + ", ".join(f"{k} {v:.0f}s" for k, v in tm["stages"].items() if v >= 1)
    except Exception: pass
    return out

def scan_digest(every=1200):
    """Private Telegram DM to the owner with a short scan summary, at most once every 20 minutes."""
    if DRY: return
    mark = f"{STATE}/scan-digest"; os.makedirs(STATE, exist_ok=True)
    if os.path.exists(mark) and time.time() - os.path.getmtime(mark) < every: return
    open(mark, "w").close()
    owner_msg("🔎 " + scan_summary())

def outcome_summary():
    """Paper-trade view of every coin that reached the safety stage or narrowly missed a filter. Groups: (tier, decision), then near-misses by the one
    filter they failed, then outcomes by data source. Per group: coins with a 1-hour outcome, median market-cap multiple after 1 hour (1.0 = unchanged,
    0 = gone), share above 1.0x, share gone. This is the evidence for tuning: if near-misses of one filter did as well as the coins we called, that
    filter is too strict; if blocked coins did far worse, the gate is doing its job; a source with better outcomes deserves more weight."""
    import collections, statistics
    groups = collections.defaultdict(list); near = collections.defaultdict(list); src = collections.defaultdict(list)
    for r in cand_rows():
        try: v = float(r.get("m1h"))
        except (TypeError, ValueError): continue
        dec = "called" if r.get("decision") in ("pass", "posted") else r.get("decision") or "?"
        groups[(r.get("tier") or "normal", dec)].append(v)
        if dec == "nearmiss": near[r.get("reason") or "?"].append(v)
        if r.get("src") and dec in ("called", "blocked", "nearmiss"): src[r["src"]].append(v)
    if not groups: return "No finished 1-hour outcomes yet."
    def line(name, v): return f"{name}: {len(v)} coins, median {statistics.median(v):.2f}x after 1h, {100 * sum(1 for x in v if x > 1) / len(v):.0f}% above 1.0x, {100 * sum(1 for x in v if x == 0) / len(v):.0f}% gone"
    out = [line(f"{t} / {d}", v) for (t, d), v in sorted(groups.items())]
    if near: out += ["", "Near-misses by the one filter they failed (high % above 1.0x = that filter may be too strict):"] + [line("  " + k, v) for k, v in sorted(near.items(), key=lambda kv: -len(kv[1]))]
    if src: out += ["", "By data source:"] + [line("  " + k, v) for k, v in sorted(src.items(), key=lambda kv: -len(kv[1]))]
    return "\n".join(out)

def weekly_analysis():
    """Sundays from 18:00 UTC: private DM with what the logged outcomes say about which features predict good calls (needs enough finished outcomes)."""
    if DRY or now.weekday() != 6 or now.hour < 18 or not _once_today("analysis"): return
    import subprocess
    out = subprocess.run([sys.executable, f"{ROOT}/bot/analyze.py"], capture_output=True, text=True, timeout=60).stdout.strip()
    owner_msg("📊 Weekly outcome analysis\n" + outcome_summary() + ("\n\n" + out if out else ""))

def daily_growth(hour=16):
    """Once a day, private DM only: follower/post counts plus up to 4 ready-to-paste reply drafts for coins people are talking about
    right now (they pass our scanner filters and the RugCheck gate). The owner pastes them by hand under other people's posts.
    Nothing is ever posted or replied automatically."""
    if now.hour < hour or DRY or not _once_today("growth"): return
    try:
        auth = {"Authorization": "Bearer " + token()}
        u = http("https://api.x.com/2/users/me?user.fields=public_metrics", headers=auth)["data"]; me = u["public_metrics"]
        head = f"📈 Growth check: {me.get('followers_count')} followers, {me.get('tweet_count')} posts."
        try:   # views and likes on the last 20 posts (best effort; the X plan may not return impressions)
            tw = http(f"https://api.x.com/2/users/{u['id']}/tweets?max_results=20&tweet.fields=public_metrics", headers=auth).get("data") or []
            views = sum(t["public_metrics"].get("impression_count", 0) for t in tw); likes = sum(t["public_metrics"].get("like_count", 0) for t in tw)
            head += f" Last {len(tw)} posts: {views:,} views, {likes} likes."
        except Exception: pass
    except Exception: head = "📈 Growth check (follower count unavailable)."
    drafts = []
    for sc, q, mc, liq, age in sorted(candidates(), key=lambda t: -t[0])[:12]:
        ca = q["baseToken"]["address"]; v = safety_rc(ca)
        if not v or not v[0]: continue
        sym = q["baseToken"].get("symbol")
        t = f"Contract check on ${sym}: {v[2]}. Mcap {fmt(mc)}, liq {fmt(liq)}. Worth checking before aping. NFA"
        if xlen(t) <= 280: drafts.append(t)
        if len(drafts) >= 4: break
    body = "\n\n".join(f"{i+1}) {d}" for i, d in enumerate(drafts)) or "No coin passed the safety check for a reply draft today."
    owner_msg(f"{head}\n\nReply drafts to paste by hand under other people's call-outs (add value, no link-dropping):\n\n{body}")

def tg_api(method, **params):
    """Telegram Bot API call (JSON). Raises on HTTP errors; callers wrap it."""
    tok = cliperz_keys.optional("TELEGRAM_BOT_TOKEN")
    return http(f"https://api.telegram.org/bot{tok}/{method}", json.dumps(params).encode(), {"Content-Type": "application/json"})

def mk_pending():
    try: return json.load(open(f"{STATE}/mk_pending.json"))
    except Exception: return {}

def mk_pending_save(d):
    os.makedirs(STATE, exist_ok=True)
    json.dump({k: v for k, v in d.items() if time.time() - v.get("t", 0) < 3 * 86400}, open(f"{STATE}/mk_pending.json", "w"))

MK_MAX_APPROVED_PER_DAY = 6

def mk_handle_tap(data, from_id, owner_id):
    """One tap on a draft button. Returns a short answer for the owner. ONLY the owner's own tap can post, once per draft, expired after 24 h,
    at most MK_MAX_APPROVED_PER_DAY a day. The text posted is exactly the draft that was shown (stored server-side, not taken from the tap)."""
    if str(from_id) != str(owner_id): return None                      # anyone else: ignored completely
    try: _, action, did = data.split(":", 2)
    except ValueError: return None
    pend = mk_pending(); d = pend.get(did)
    if not d or d.get("state") != "open": return "Already handled or expired."
    if time.time() - d["t"] > 86400: d["state"] = "expired"; mk_pending_save(pend); return "That draft expired (older than 24 hours)."
    if action == "skip": d["state"] = "skipped"; mk_pending_save(pend); return "Skipped."
    if action != "post": return None
    cap = f"{STATE}/mk_posted-{now.date()}"; n = len(open(cap).read().split()) if os.path.exists(cap) else 0
    if n >= MK_MAX_APPROVED_PER_DAY: return f"Daily limit of {MK_MAX_APPROVED_PER_DAY} approved posts reached. Try tomorrow."
    d["state"] = "posting"; mk_pending_save(pend)                      # mark first, so a retry can never post it twice
    try:
        tid = post(d["text"], reply_to=d.get("reply_to"), quote_id=d.get("quote_id"), mirror=False)
    except Exception as e:
        d["state"] = "open"; mk_pending_save(pend); return f"Could not post ({type(e).__name__}); you can tap again."
    d["state"] = "posted"; mk_pending_save(pend); open(cap, "a").write(f"{did}\n")
    return f"✅ Posted: https://x.com/{CFG.get('handle', 'Cliperzcoins711')}/status/{tid}"

def telegram_actions():
    """Each cycle: if drafts are waiting for approval, read the owner's button taps (Telegram getUpdates) and act on them."""
    if DRY or not CFG.get("marketing_buttons", True): return
    owner = cliperz_keys.optional("TELEGRAM_OWNER_CHAT_ID")
    if not owner or not any(v.get("state") == "open" for v in mk_pending().values()): return
    offf = f"{STATE}/mk_tgoffset"; off = int(open(offf).read()) if os.path.exists(offf) else 0
    res = tg_api("getUpdates", offset=off, timeout=0, allowed_updates=["callback_query"]).get("result", [])
    for u_ in res:
        off = u_["update_id"] + 1; cq = u_.get("callback_query")
        if not cq: continue
        ans = mk_handle_tap(cq.get("data", ""), (cq.get("from") or {}).get("id"), owner)
        try: tg_api("answerCallbackQuery", callback_query_id=cq["id"], text=(ans or "")[:150])
        except Exception: pass
        if ans:
            owner_msg(ans)
            try:
                m = cq.get("message") or {}; tg_api("editMessageReplyMarkup", chat_id=m["chat"]["id"], message_id=m["message_id"], reply_markup={"inline_keyboard": []})
            except Exception: pass
    os.makedirs(STATE, exist_ok=True); open(offf, "w").write(str(off))

# ---------- Marketing agent: DRAFTS ONLY. It finds relevant posts and prepares reply/quote drafts and sends them privately to the owner.
# It never posts, replies, quotes, follows or likes anything itself; the owner copies a draft and posts it by hand. ----------
MK_QUERIES = ('(solana OR pumpfun OR "pump.fun") (rug OR rugged OR scam OR "is this safe" OR "how to check") -is:retweet lang:en',
              '(solana memecoin OR "solana meme") (dyor OR "mint authority" OR liquidity OR holders) -is:retweet lang:en',
              'solana ("new coin" OR "just launched" OR gem OR "ca:") -is:retweet lang:en')
MK_BAD = re.compile(r"giveaway|airdrop|guarantee|100x|1000x|dm me|send me|whitelist|presale|financial advice|follow back|f4f", re.I)
CA_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
MK_TIPS = ("30-second check before buying any meme coin: is mint authority revoked? freeze authority revoked? what share do the top 10 holders own? rugcheck.xyz shows all three for free. Can't answer them? Skip it. NFA",
           "Most new coins that lose their liquidity do it in the first hours. Check that the LP is locked or burned before you size up. NFA",
           "Volume can be faked. If a coin trades 20x its market cap in a day, that is often wash trading, not demand. DYOR",
           "Rule of thumb: if the dev wallet and a few top holders own a big share of supply, the exit liquidity is you. Check the holders first.",
           "Active mint authority means more supply can be printed at any moment. Revoked mint plus revoked freeze is the bare minimum, not a green light. NFA",
           "A chart that only goes up in the first 30 minutes is a warning, not a signal: late buyers fund the early ones. NFA")

def mk_seen():
    try: return set(json.load(open(f"{STATE}/mk_seen.json")))
    except Exception: return set()

def mk_find_posts(n=3):
    """Recent X posts where a short, useful reply fits: about rugs/safety/holders, or containing a Solana contract we can check. Skips scammy wording."""
    q = MK_QUERIES[(now.hour // 6) % len(MK_QUERIES)]
    d = http("https://api.x.com/2/tweets/search/recent?" + u.urlencode({"query": q, "max_results": 50, "tweet.fields": "created_at,public_metrics,author_id",
             "expansions": "author_id", "user.fields": "username,public_metrics"}), headers={"Authorization": "Bearer " + token()})
    users = {x["id"]: x for x in (d.get("includes") or {}).get("users", [])}; seen = mk_seen(); out = []
    for t in d.get("data") or []:
        us = users.get(t.get("author_id"))
        if not us or us["username"].lower() == CFG.get("handle", "Cliperzcoins711").lower() or t["id"] in seen: continue
        age_h = (now - dt.datetime.fromisoformat(t["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
        fol = us["public_metrics"]["followers_count"]; pm = t["public_metrics"]
        if age_h > 6 or not 150 <= fol <= 200000 or MK_BAD.search(t["text"]) or not name_ok(t["text"]): continue
        out.append((pm["like_count"] + 2 * pm["reply_count"] + (3 if CA_RE.search(t["text"]) else 0), t, us))
    return sorted(out, key=lambda x: -x[0])[:n]

def mk_reply_text(t):
    """A contract check when the post contains a Solana contract RugCheck knows, otherwise a short safety tip. Never a price call, never a link to us."""
    m = CA_RE.search(t["text"])
    if m:
        ca = m.group(0); d = rugcheck(ca); q = pair(ca)
        if not d or "risks" not in d: return None
        sym = (q or {}).get("baseToken", {}).get("symbol") or (d.get("tokenMeta") or {}).get("symbol") or "this coin"
        flags = list(dict.fromkeys(r.get("name") for r in (d.get("risks") or []) if r.get("level") in ("danger", "warn")))
        txt = (f"Contract check on ${sym}: mint {'revoked' if not d.get('mintAuthority') else 'ACTIVE'}, freeze {'revoked' if not d.get('freezeAuthority') else 'ACTIVE'}, "
               f"{int(d.get('totalHolders') or 0):,} holders, RugCheck flags: {', '.join(flags)[:80] if flags else 'none'}. Do your own checks. Not an endorsement. NFA")
        return txt if xlen(txt) <= 280 else None
    if re.search(r"rug|scam|safe|check|holders|mint|liquidity|dyor", t["text"], re.I): return MK_TIPS[int(t["id"]) % len(MK_TIPS)]
    return None

def mk_quote_draft():
    """Quote-post draft of our best recent result (peak after our call, at least 1.5x) that has not been suggested yet."""
    seen = mk_seen(); best = None
    for x in rows():
        try: pk = peak_mult(x)
        except Exception: continue
        if x["status"] == "rugged" or not str(x["tweet_id"]).isdigit() or f"q{x['id']}" in seen or pk < 1.5 or not name_ok(x["token"]): continue
        if pk > 100: continue
        if best is None or pk > best[0]: best = (pk, x)
    if not best: return None
    pk, x = best; c0 = float(x["mcap_at_call"]); pkm = pk * c0
    return f"q{x['id']}", f"https://x.com/{CFG.get('handle', 'Cliperzcoins711')}/status/{x['tweet_id']}", \
        f"${x['token']}: called at {fmt(c0)}, peaked at {fmt(pkm)} = {pk:.1f}x after our post. Peak, not a promise. We check safety before every call. NFA"

def narrative_radar(every=600, per_entity_hours=2, per_coin_hours=6):
    """News-driven alerts, PRIVATE DM ONLY (nothing is posted publicly). Every ~10 minutes: for each watched name, read fresh Google News headlines;
    when several publishers ran the story in the last hours, look for Solana coins carrying the name, group clones, check safety and the 1-hour chart,
    and DM the owner with headlines, the best coin, clone count and red flags. Each alerted coin is also logged as a shadow candidate (tier
    'narrative') so its later peak is tracked and we can measure whether following news would have paid."""
    if DRY or not CFG.get("narrative_enabled", True): return
    mark = f"{STATE}/nr-run"; os.makedirs(STATE, exist_ok=True)
    if os.path.exists(mark) and time.time() - os.path.getmtime(mark) < every: return
    open(mark, "w").close()
    import narrative
    try: seen = json.load(open(f"{STATE}/nr_seen.json"))
    except Exception: seen = {}
    t_now = time.time(); seen = {k: v for k, v in seen.items() if t_now - v < 86400}
    for entity, aliases in (CFG.get("narrative_entities") or {}).items():
        try:
            items = narrative.parse_rss(http_text("https://news.google.com/rss/search?q=" + u.quote(f'"{entity}" when:1d') + "&hl=en-US&gl=US&ceid=US:en"))
            if not narrative.is_hot(items, now): continue
            if t_now - seen.get(f"e:{entity}", 0) < per_entity_hours * 3600: continue
            pairs = []
            for a in aliases[:2]:
                try: pairs += http("https://api.dexscreener.com/latest/dex/search?q=" + u.quote(a)).get("pairs") or []
                except Exception: pass
            coins = [(c, n) for c, n in narrative.best_coins(pairs, aliases, now.timestamp() * 1000) if t_now - seen.get(f"c:{c['ca']}", 0) > per_coin_hours * 3600]
            if not coins: continue
            verdicts = {}
            for c, _ in coins:
                v = safety_rc(c["ca"], min_holders=50, max_score=30)
                verdicts[c["ca"]] = "no RugCheck report yet" if v is None else (("passes the RugCheck gate: " + v[2]) if v[0] else "BLOCKED: " + v[1])
                oh = off_high(c["pair"])
                if oh is not None: verdicts[c["ca"]] += f"; price is {100 * oh:.0f}% of its 1-hour high"
                seen[f"c:{c['ca']}"] = t_now
                try: log_candidate(c["ca"], c["pair"], c["age_h"] * 60, None, "alert", f"narrative:{entity}", tier="narrative", src=f"news:{entity}")
                except Exception: pass
            seen[f"e:{entity}"] = t_now
            owner_msg(narrative.format_alert(entity, items, coins, now, verdicts))
        except Exception as e:
            print(f"[WARN] narrative radar failed for {entity} ({type(e).__name__}: {str(e)[:80]})")
    json.dump(seen, open(f"{STATE}/nr_seen.json", "w"))

def marketing_drafts(hours=(12, 18)):
    """Twice a day: up to 3 reply drafts and 1 quote draft, sent privately to the owner. With buttons on, each draft arrives as its own message
    with [Post this] / [Skip]; the post is only made when the owner taps. Without buttons it is one plain DM to copy from."""
    if DRY or now.hour not in hours or not _once_today(f"mk{now.hour}"): return
    seen = mk_seen(); items = []; used = set()
    try:
        for _, t, us in mk_find_posts(8):
            txt = mk_reply_text(t)
            m = CA_RE.search(t["text"])
            if not txt or (m and m.group(0) in used): continue       # one draft per coin
            if m: used.add(m.group(0))
            snippet = t["text"].replace("\n", " ")[:140]
            items.append(dict(text=txt, reply_to=t["id"], label=f"REPLY to @{us['username']} ({us['public_metrics']['followers_count']:,} followers, {t['public_metrics']['like_count']} likes)\n"
                              f"https://x.com/{us['username']}/status/{t['id']}\nTheir post: \"{snippet}\"\nDraft: {txt}"))
            seen.add(t["id"])
            if len(items) >= 3: break
    except Exception as e: print(f"[WARN] marketing search failed ({type(e).__name__}: {str(e)[:80]})")
    qd = mk_quote_draft()
    if qd:
        seen.add(qd[0]); items.append(dict(text=qd[2], quote_id=qd[1].rsplit("/", 1)[-1], label=f"QUOTE our own call-out\n{qd[1]}\nDraft: {qd[2]}"))
    if not items: return
    os.makedirs(STATE, exist_ok=True); json.dump(sorted(seen)[-400:], open(f"{STATE}/mk_seen.json", "w"))
    owner = cliperz_keys.optional("TELEGRAM_OWNER_CHAT_ID")
    if CFG.get("marketing_buttons", True) and owner:
        pend = mk_pending(); sent = 0
        try:
            tg_api("sendMessage", chat_id=owner, text="📣 Marketing drafts. Nothing is posted unless you tap [Post this] on a draft.", disable_web_page_preview=True)
            for it in items:
                import hashlib
                did = hashlib.sha1((it["text"] + str(time.time())).encode()).hexdigest()[:10]
                pend[did] = dict(text=it["text"], reply_to=it.get("reply_to"), quote_id=it.get("quote_id"), state="open", t=time.time())
                tg_api("sendMessage", chat_id=owner, text=it["label"][:3900], disable_web_page_preview=True,
                       reply_markup={"inline_keyboard": [[{"text": "✅ Post this", "callback_data": f"mk:post:{did}"}, {"text": "⏭ Skip", "callback_data": f"mk:skip:{did}"}]]})
                sent += 1
            mk_pending_save(pend)
            return
        except Exception as e:
            print(f"[WARN] marketing buttons failed ({type(e).__name__}); sending a plain DM instead")
            if sent: mk_pending_save(pend); return
    owner_msg("📣 Marketing drafts. NOTHING was posted: copy what you like and post it from your own phone.\n\n" + "\n\n".join(it["label"] for it in items))

if __name__ == "__main__":
    if os.path.exists(f"{ROOT}/STOP"): sys.exit("STOP file present, not posting")
    if os.environ.get("GITHUB_ACTIONS") != "true" and not DRY and os.environ.get("CLIPERZ_ALLOW_LOCAL") != "1":
        sys.exit("Only the GitHub Actions run may post (a second copy would fight it over the single-use X login). See RUNBOOK.md; set CLIPERZ_ALLOW_LOCAL=1 only when moving to a private server.")
    t_all = time.time(); times = {}
    for stage in (track, call_out, early_call_out, track_candidates, scoreboard, daily_recap, daily_lesson, daily_growth, telegram_actions, marketing_drafts, narrative_radar, weekly_analysis, scan_digest):   # one failing stage must not skip the rest
        t0 = time.time()
        try: stage()
        except Exception as e: print(f"[WARN] {stage.__name__} failed this cycle: {type(e).__name__}: {str(e)[:100]}")
        times[stage.__name__] = time.time() - t0
    try: os.makedirs(STATE, exist_ok=True); json.dump({"total": time.time() - t_all, "stages": times}, open(f"{STATE}/timings.json", "w"))
    except Exception: pass
    print("[TIMING] " + f"{time.time() - t_all:.0f}s total | " + ", ".join(f"{k} {v:.0f}s" for k, v in times.items() if v >= 1) + f" | GeckoTerminal requests {GT_STATS[0]}, rate-limited {GT_STATS[1]}")
