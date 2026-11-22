import csv, os
import requests


def fmt(sig):
    arrow = "🟢" if sig.side == "BUY" else "🔴"
    return (f"{arrow} {sig.symbol} {sig.side}  (level strength {sig.score})\n"
            f"Entry ≈ {sig.price:,.2f}\nSL: {sig.sl:,.2f}\nTP: {sig.tp:,.2f}\n"
            f"Why: {', '.join(sig.reasons)}\nBar: {sig.time:%Y-%m-%d %H:%M} UTC\n"
            f"Not financial advice - manage your risk.")


def send(sig, settings):
    text = fmt(sig)
    print("\n" + text + "\n")
    if settings.telegram_token and settings.telegram_chat:
        try:
            r = requests.post(f"https://api.telegram.org/bot{settings.telegram_token}/sendMessage",
                              data={"chat_id": settings.telegram_chat, "text": text}, timeout=15)
            if not r.ok:
                print(f"[warn] telegram rejected the message: {r.status_code} {r.text} (chat id used: {settings.telegram_chat!r})")
        except Exception as e:
            print(f"[warn] telegram failed: {e}")
    new = not os.path.exists(settings.log_file)
    with open(settings.log_file, "a", newline="") as f:
        w = csv.writer(f)
        if new: w.writerow(["time", "symbol", "side", "price", "sl", "tp", "score"])
        w.writerow([sig.time, sig.symbol, sig.side, sig.price, sig.sl, sig.tp, sig.score])
