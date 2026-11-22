import csv, os, time
import requests

FOOTER = "Take partials. Manage Trade Risk. If hold set BE. Hold risk with Breakeven(BE)"


def _p(x, d):
    return f"{x:,.{d}f}".replace(",", "") if d else f"{x:.0f}"


def format_signal(sig, number=None, test=False):
    banner = "🧪 TEST - NOT A LIVE SIGNAL\n\n" if test else ""
    return banner + _format(sig, number)


def pips_from_entry(sig, price):
    """Pips between the called price and `price`, using the symbol's pip size (always positive)."""
    return int(round(abs(price - sig.price) / sig.pip))


def _format(sig, number):
    d = sig.decimals
    zone = (f"{_p(sig.zone_hi, d)} - {_p(sig.zone_lo, d)}" if sig.side == "BUY"
            else f"{_p(sig.zone_lo, d)} - {_p(sig.zone_hi, d)}")
    tp_line = lambda k, tp, sep: f"TP{k + 1}{sep}{_p(tp, d)} (+{pips_from_entry(sig, tp)} pips)"
    sl_line = f"{_p(sig.sl, d)} (-{pips_from_entry(sig, sig.sl)} pips)"
    if sig.style == "gold":
        word = "Buy" if sig.side == "BUY" else "Sell"
        lines = [f"{number}. GOLD {sig.side} SETUP" if number else f"GOLD {sig.side} SETUP", "",
                 f"Gold {word} Zone {zone}", f"Called at : {_p(sig.price, d)}", "", f"SL : {sl_line}", ""]
        lines += [tp_line(k, tp, " : ") for k, tp in enumerate(sig.tps)]
        lines += ["TP4 : Hold", "",
                  "🔑 Use suitable lot sizes based on your capital. Money management is key to long term success"]
        return "\n".join(lines)
    lines = [f"🕯️{sig.label} SIGNAL🕯️", "", f"DIRECTION: {sig.side} {sig.label}", "", f"ENTRY PRICE: {zone}",
             f"CALLED AT: {_p(sig.price, d)}", ""]
    lines += ["✅ " + tp_line(k, tp, ": ") for k, tp in enumerate(sig.tps)]
    lines += [f"❌ Stop Loss: {sl_line}", "", "⏰ TIMEFRAME : 15 MIN", "", "⚠️ USE PROPER RISK MANAGEMENT"]
    return "\n".join(lines)


def _post(settings, text, reply_to=None):
    """Send to Telegram. Returns the message_id or None."""
    print("\n" + text + "\n")
    if not (settings.telegram_token and settings.telegram_chat):
        return None
    data = {"chat_id": settings.telegram_chat, "text": text}
    if reply_to:
        data["reply_to_message_id"] = reply_to
    for attempt in range(5):
        try:
            r = requests.post(f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage", data=data, timeout=15)
        except Exception as e:
            print(f"[warn] telegram failed: {e}")
            return None
        if r.status_code == 429:   # rate limited: wait as long as Telegram asks, then retry
            wait = 5
            try:
                wait = int(r.json().get("parameters", {}).get("retry_after", 5))
            except Exception:
                pass
            print(f"[info] telegram rate limit, waiting {wait + 1}s")
            time.sleep(wait + 1)
            continue
        if not r.ok:
            print(f"[warn] telegram rejected the message: {r.status_code} {r.text} (chat id used: {settings.telegram_chat!r})")
            return None
        return r.json()["result"]["message_id"]
    print("[warn] telegram: gave up after repeated rate limits")
    return None


def send(sig, settings, number=None, test=False):
    mid = _post(settings, format_signal(sig, number, test))
    new = not os.path.exists(settings.log_file)
    with open(settings.log_file, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["time", "symbol", "side", "price", "sl", "tp1", "score"])
        w.writerow([sig.time, sig.symbol, sig.side, sig.price, sig.sl, sig.tp, sig.score])
    return mid


def reply(text, message_id, settings):
    return _post(settings, text, reply_to=message_id)
