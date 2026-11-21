"""Run: python -m scanner.main [--once] [--tf 1h] [--source public|mt5]"""
import argparse, os, time
from .config import Settings
from .data import make_source, TF_MINUTES
from .strategy import evaluate
from . import notify


def load_env():
    if os.path.exists(".env"):
        for line in open(".env"):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)
    return os.environ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="scan once and exit")
    ap.add_argument("--test", action="store_true", help="send a sample signal to check Telegram")
    ap.add_argument("--chat-id", action="store_true", help="check the bot token and list chats it can see")
    ap.add_argument("--tf", default=None)
    ap.add_argument("--source", default=None)
    ap.add_argument("--min-touches", type=int, default=None)
    a = ap.parse_args()
    env = load_env()
    s = Settings()
    if a.tf: s.timeframe = a.tf
    if a.source: s.source = a.source
    if a.min_touches: s.min_touches = a.min_touches
    s.telegram_token, s.telegram_chat = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
    if a.chat_id:
        import requests
        tok = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not tok:
            return print("TELEGRAM_BOT_TOKEN is empty in .env")
        me = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=15).json()
        if not me.get("ok"):
            return print("Token rejected by Telegram (wrong, revoked, or has extra characters):", me)
        print("Token OK. Bot:", me["result"]["username"])
        ups = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=15).json()
        chats = {}
        for u in ups.get("result", []):
            c = (u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}).get("chat", {})
            if c.get("id"):
                chats[c["id"]] = c.get("title")
        chats.pop(None, None)
        print("Chats seen:", chats or "none yet - add the bot to the group, send a message there, run again")
        return
    if a.test:
        import pandas as pd
        from .strategy import Signal
        notify.send(Signal("TEST-BTC", "BUY", 100000.0, 99000.0, 102000.0, 3,
                           pd.Timestamp.now(tz="UTC"), ["this is a test message"]), s)
        return
    src = make_source(s, env)
    print(f"Scanning {[x.name for x in s.symbols]} on {s.timeframe} via {src.name}")
    last = {}  # (symbol) -> (bar time, side)
    while True:
        for sym in s.symbols:
            try:
                df, htf = src.candles(sym, s.timeframe), src.candles(sym, s.htf)
                sig = evaluate(sym.name, df, htf, s.min_touches, s.min_rr, ltf_min=TF_MINUTES[s.timeframe], htf_min=TF_MINUTES[s.htf])
            except Exception as e:
                print(f"[warn] {sym.name}: {e}")
                continue
            if not sig:
                print(f"{sym.name}: no signal")
                continue
            prev = last.get(sym.name)
            bar = TF_MINUTES[s.timeframe] * 60
            if prev and prev[1] == sig.side and (sig.time - prev[0]).total_seconds() < bar * s.cooldown_bars:
                continue
            last[sym.name] = (sig.time, sig.side)
            notify.send(sig, s)
        if a.once:
            break
        time.sleep(s.poll_seconds)


if __name__ == "__main__":
    main()
