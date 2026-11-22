"""Run: python -m scanner.main [--once] [--tf 15m] [--source public|mt5] [--test] [--chat-id]"""
import argparse, json, os, time
import pandas as pd
from .config import Settings, get_symbol
from .data import make_source, TF_MINUTES
from .strategy import evaluate, make_signal
from . import notify, tracker

STATE_FILE = "state.json"


def load_env():
    if os.path.exists(".env"):
        for line in open(".env"):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v)
    return os.environ


def load_state():
    try:
        st = json.load(open(STATE_FILE))
    except Exception:
        st = {}
    if "last" not in st and "open" not in st and "counter" not in st:   # old format: {symbol: [time, side]}
        st = {"last": st}
    st.setdefault("last", {}); st.setdefault("open", []); st.setdefault("counter", {})
    return st


def save_state(st):
    json.dump(st, open(STATE_FILE, "w"))


def next_number(st, name):
    today = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d")
    c = st["counter"]
    if c.get("date") != today:
        c.clear(); c["date"] = today; c["n"] = {}
    c["n"][name] = c["n"].get(name, 0) + 1
    return c["n"][name]


def check_chat(env):
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
    print("Chats seen:", chats or "none yet - add the bot to the group, send a message there, run again")


def run_test(s):
    """Post one fake gold BUY and one fake BTC SELL, then fake running / TP / BE updates as threaded replies."""
    now = pd.Timestamp.now(tz="UTC").floor("15min")
    demos = [("GOLD", "BUY", 3567.0, 3573.0, 3574.0), ("BTC", "SELL", 56140.0, 56641.0, 56100.0)]
    for name, side, lo, hi, price in demos:
        sym = get_symbol(name)
        sig = make_signal(name, side, lo, hi, price, now, 3, ["test"], sym)
        mid = notify.send(sig, s, 1 if sym.style == "gold" else None)
        t = tracker.new_trade(sig, mid, 1)
        buy = side == "BUY"
        thr = sym.run * (price if sym.pct else 1)
        # synthetic candles: reach the "running" level, then TP1, then (gold) TP3 / (btc) fall back to entry
        c1 = dict(high=sig.ref + thr if buy else sig.ref, low=sig.ref if buy else sig.ref - thr, open=price, close=price)
        c2 = dict(high=sig.tps[0] if buy else price, low=price if buy else sig.tps[0], open=price, close=price)
        c3 = dict(high=sig.tps[-1], low=price + 0.5, open=price, close=price)
        if not buy:   # BTC demo ends with a breakeven stop instead of all TPs
            c3 = dict(high=price + 1, low=sig.tps[0] + 1, open=price, close=price)
        df = pd.DataFrame([c1, c2, c3], index=[now + pd.Timedelta(minutes=15 * (k + 1)) for k in range(3)])
        for text in tracker.resolve(t, df, thr):
            time.sleep(1)
            notify.reply(text, mid, s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="scan once and exit")
    ap.add_argument("--test", action="store_true", help="send sample signals and updates to Telegram")
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
    s.telegram_token, s.telegram_chat = env.get("TELEGRAM_BOT_TOKEN", "").strip(), env.get("TELEGRAM_CHAT_ID", "").strip()
    if a.chat_id:
        return check_chat(env)
    if a.test:
        return run_test(s)
    src = make_source(s, env)
    print(f"Scanning {[x.name for x in s.symbols]} on {s.timeframe} via {src.name}")
    st = load_state()
    bar = TF_MINUTES[s.timeframe] * 60
    while True:
        tracker.run(st, src, s)
        save_state(st)
        for sym in s.symbols:
            try:
                df, htf = src.candles(sym, s.timeframe), src.candles(sym, s.htf)
                sig = evaluate(sym.name, df, htf, s.min_touches, ltf_min=TF_MINUTES[s.timeframe],
                               htf_min=TF_MINUTES[s.htf], sym=sym)
            except Exception as e:
                print(f"[warn] {sym.name}: {e}")
                continue
            if not sig:
                print(f"{sym.name}: no signal")
                continue
            if a.once and (pd.Timestamp.now(tz="UTC") - sig.time).total_seconds() > (TF_MINUTES[s.timeframe] + 45) * 60:
                print(f"{sym.name}: signal is stale, skipping")
                continue
            prev = st["last"].get(sym.name)
            if prev and prev[1] == sig.side and (sig.time - pd.Timestamp(prev[0])).total_seconds() < bar * s.cooldown_bars:
                continue
            st["last"][sym.name] = [str(sig.time), sig.side]
            number = next_number(st, sym.name) if sym.style == "gold" else None
            mid = notify.send(sig, s, number)
            st["open"].append(tracker.new_trade(sig, mid, number))
            save_state(st)
        if a.once:
            break
        time.sleep(s.poll_seconds)


if __name__ == "__main__":
    main()
