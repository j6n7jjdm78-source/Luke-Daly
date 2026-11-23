"""Narrative radar: pure helpers (no network, no imports from bot.py) for spotting coins that ride a news story, e.g. 'Nvidia reinstates Jensen Huang'.

How it works (the wiring and all network calls live in bot.py -> narrative_radar()):
  1. A watchlist of names (people, companies) is checked against free news headlines (Google News RSS).
  2. A name is HOT when several different publishers ran fresh headlines about it (one outlet is noise).
  3. For hot names we search DexScreener for Solana coins carrying the name, group the clones, and pick the one with the most real liquidity.
  4. The owner gets a private DM with the headlines, the coin, clone count and red flags. Nothing is ever posted publicly from a news alert, and
     any wording must never imply that the named person endorses a coin."""
import re
import datetime as dt
import email.utils
import xml.etree.ElementTree as ET


def parse_rss(xml_text):
    """Google News RSS -> list of {title, source, ts (UTC datetime), link}. Bad items are skipped; never raises on malformed input."""
    out = []
    try: root = ET.fromstring(xml_text)
    except ET.ParseError: return out
    for it in root.iter("item"):
        try:
            title = (it.findtext("title") or "").strip(); pub = it.findtext("pubDate") or ""
            ts = email.utils.parsedate_to_datetime(pub)
            if ts.tzinfo is None: ts = ts.replace(tzinfo=dt.timezone.utc)
            src = (it.findtext("source") or "").strip() or (title.rsplit(" - ", 1)[1] if " - " in title else "")
            if title: out.append(dict(title=title, source=src, ts=ts.astimezone(dt.timezone.utc), link=(it.findtext("link") or "").strip()))
        except (TypeError, ValueError): continue
    return out


def heat(items, now, window_h=6):
    """How hot is a story? Returns (distinct publishers in the last window_h hours, minutes since the newest headline). Hot needs both fresh and broad."""
    recent = [x for x in items if 0 <= (now - x["ts"]).total_seconds() <= window_h * 3600]
    if not recent: return 0, None
    pubs = {x["source"].lower() for x in recent if x["source"]} or {x["title"] for x in recent}
    newest = min((now - x["ts"]).total_seconds() / 60 for x in recent)
    return len(pubs), newest


def is_hot(items, now, min_publishers=3, fresh_min=120):
    n, newest = heat(items, now)
    return n >= min_publishers and newest is not None and newest <= fresh_min


def norm_name(s):
    """Lowercase letters and digits only, so 'Jensen Is Back' and 'JENSEN-IS-BACK' are the same coin family."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


FAKE_WORDS = ("official", "real", "verified", "authentic", "original")


def coin_view(p, now_ms):
    """Flatten a DexScreener pair into the fields the radar needs."""
    b = p.get("baseToken") or {}; liq = (p.get("liquidity") or {}).get("usd") or 0; mc = p.get("marketCap") or p.get("fdv") or 0
    age_h = (now_ms - (p.get("pairCreatedAt") or now_ms)) / 3.6e6; pc = p.get("priceChange") or {}
    return dict(ca=b.get("address", ""), symbol=b.get("symbol", ""), name=b.get("name", ""), liq=liq, mc=mc, age_h=age_h, h24=pc.get("h24"), h1=pc.get("h1"),
                key=norm_name(b.get("name")) or norm_name(b.get("symbol")), pair=p)


NOT_THE_NAME = {"trumpet", "trumpets", "trumpeter", "musketeer", "musketeers", "muskrat", "muskox", "elongated", "elongate"}


def words(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


def matches(coin, aliases):
    """True when a whole WORD of the coin's name or symbol is the alias (or starts with it and is only a little longer, like 'elonmusk').
    Plain substring matching would call 'Melon' an Elon coin."""
    for w in words(coin["name"]) + words(coin["symbol"]):
        if w in NOT_THE_NAME: continue
        if any(w == a or (w.startswith(a) and len(w) <= len(a) + 6) for a in aliases): return True
    return False


def red_flags(c, family_size):
    """Plain-language warnings for one coin. Clones and fake market caps are the main danger with news coins."""
    f = []
    if family_size > 1: f.append(f"{family_size} coins with this same name (clones)")
    if c["liq"] < 5000: f.append(f"liquidity only ${c['liq']:,.0f}")
    if c["mc"] and c["liq"] and c["mc"] / c["liq"] > 40: f.append(f"market cap ${c['mc']:,.0f} is {c['mc'] / c['liq']:.0f}x its liquidity (can be faked)")
    if any(w in (c["name"] or "").lower() for w in FAKE_WORDS): f.append("name claims to be 'official'")
    if (c["h24"] or 0) > 500: f.append(f"already up {c['h24']:.0f}% in 24h (late)")
    if c["age_h"] > 72: f.append("older coin that only recently moved")
    return f


def best_coins(pairs, aliases, now_ms, max_age_h=168, min_liq=8000, top=2):
    """From DexScreener Solana pairs: keep those matching the story's aliases and recent enough, group clones by name, return the best coin per family
    (most liquidity), best first, as (coin, family_size)."""
    coins = [coin_view(p, now_ms) for p in pairs if p.get("chainId") == "solana"]
    coins = [c for c in coins if c["ca"] and matches(c, aliases) and c["age_h"] <= max_age_h]
    fam = {}
    for c in coins: fam.setdefault(c["key"], []).append(c)
    best = [(max(g, key=lambda c: c["liq"]), len(g)) for g in fam.values()]
    best = [(c, n) for c, n in best if c["liq"] >= min_liq]
    return sorted(best, key=lambda t: -t[0]["liq"])[:top]


def format_alert(entity, items, coins, now, verdicts=None):
    """The private DM. verdicts maps ca -> short safety text. Always ends with the no-endorsement reminder."""
    top = sorted(items, key=lambda x: x["ts"], reverse=True)[:3]
    lines = [f"📰 Narrative alert: {entity}", ""]
    for x in top: lines.append(f"• {x['title'][:110]} ({int((now - x['ts']).total_seconds() // 60)} min ago)")
    for c, fam in coins:
        fl = red_flags(c, fam); v = (verdicts or {}).get(c["ca"], "not checked")
        lines += ["", f"Best matching coin: ${c['symbol']} ({c['name'][:30]})", f"Market cap ${c['mc']:,.0f} | liquidity ${c['liq']:,.0f} | age {c['age_h']:.1f}h | 24h {'n/a' if c['h24'] is None else str(c['h24']) + '%'}",
                  f"CA: {c['ca']}", f"Safety: {v}", "Red flags: " + ("; ".join(fl) if fl else "none found")]
    lines += ["", "Private alert only, nothing was posted. Never imply the named person endorses a coin. NFA."]
    return "\n".join(lines)
