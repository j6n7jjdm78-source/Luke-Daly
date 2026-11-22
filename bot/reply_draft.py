"""Turns a coin's contract address into a ready-to-paste, useful reply for someone else's call-out post. It posts nothing.
Usage: python3 bot/reply_draft.py <CONTRACT_ADDRESS>"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
if len(sys.argv) < 2: sys.exit("usage: python3 bot/reply_draft.py <contract address>")
ca = sys.argv[1].strip()
d = bot.rugcheck(ca); q = bot.pair(ca)
if not d or "risks" not in d: sys.exit("RugCheck has no report for that address (yet). Nothing to reply with.")
sym = (q or {}).get("baseToken", {}).get("symbol") or (d.get("tokenMeta") or {}).get("symbol") or "this coin"
mint = "revoked ✅" if not d.get("mintAuthority") else "ACTIVE ⚠️"
freeze = "revoked ✅" if not d.get("freezeAuthority") else "ACTIVE ⚠️"
flags = [r.get("name") for r in (d.get("risks") or []) if r.get("level") in ("danger", "warn")]
holders = int(d.get("totalHolders") or 0)
liq = float(((q or {}).get("liquidity") or {}).get("usd") or 0); mc = float((q or {}).get("marketCap") or 0)
flag_txt = "none flagged" if not flags else ", ".join(dict.fromkeys(flags))[:90]
text = f"Contract check on ${sym}: mint {mint}, freeze {freeze}, {holders:,} holders, RugCheck flags: {flag_txt}."
if mc and liq: text += f" Mcap ${mc/1000:.0f}k, liq ${liq/1000:.0f}k."
text += " Worth checking before aping. NFA"
print(text); print(f"\n({bot.xlen(text)}/280 characters)")
