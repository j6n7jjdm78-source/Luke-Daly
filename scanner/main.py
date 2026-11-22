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


def script(sig, steps, thr):
    """Fake candles that walk a signal through steps: run, tp1..tp4, back (retrace to entry), sl."""
    buy, p, ref = sig.side == "BUY", sig.price, sig.ref
    mid = (p + sig.tps[0]) / 2          # stays between entry and TP1 so it never touches the entry stop
    rows = []
    for st in steps:
        if st == "run":   hi, lo = (ref + thr * 1.02, ref) if buy else (ref, ref - thr * 1.02)
        elif st == "back": hi, lo = (p, p - 0.0001) if buy else (p + 0.0001, p)
        elif st == "sl":  hi, lo = (p, sig.sl - 0.0001) if buy else (sig.sl + 0.0001, p)
        else:
            tp = sig.tps[int(st[2:]) - 1]
            hi, lo = (tp, mid) if buy else (mid, tp)
        rows.append(dict(open=p, close=p, high=hi, low=lo))
    return rows


def run_test(s):
    """Post fake setups covering every path (all TPs, breakeven stop, SL hit) as threaded replies, for gold and BTC."""
    now = pd.Timestamp.now(tz="UTC").floor("15min")
    cases = [  # name, side, zone lo, zone hi, entry price, steps
        ("GOLD", "BUY", 3567.0, 3573.0, 3574.0, ["run", "tp1", "tp2", "tp3"]),
        ("GOLD", "SELL", 3590.0, 3596.0, 3589.0, ["run", "tp1", "tp2", "back"], 2),   # demo of a BE-after-TP2 stop
        ("GOLD", "BUY", 3567.0, 3573.0, 3574.0, ["run", "sl"]),
        ("BTC", "SELL", 56140.0, 56641.0, 56100.0, ["run", "tp1", "tp2", "tp3", "tp4"]),
        ("BTC", "BUY", 56140.0, 56641.0, 56700.0, ["run", "tp1", "back"], 1),         # demo of a BE-after-TP1 stop
    ]
    st = {"counter": {}}
    from dataclasses import replace
    for k, (name, side, lo, hi, price, steps, *be) in enumerate(cases):
        sym = get_symbol(name)
        if be:
            sym = replace(sym, be_after=be[0])
        sig = make_signal(name, side, lo, hi, price, now, 3, ["test"], sym)
        number = next_number(st, name) if sym.style == "gold" else None
        mid = notify.send(sig, s, number, test=True)
        t = tracker.new_trade(sig, mid, number)
        thr = sym.run * (price if sym.pct else 1)
        df = pd.DataFrame(script(sig, steps, thr), index=[now + pd.Timedelta(minutes=15 * (j + 1)) for j in range(len(steps))])
        for text in tracker.resolve(t, df, thr):
            time.sleep(1.2)
            notify.reply(text, mid, s)
        time.sleep(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="scan once and exit")
    ap.add_argument("--test", action="store_true", help="send sample signals and updates to Telegram")
    ap.add_argument("--chat-id", action="store_true", help="check the bot token and list chats it can see")
    ap.add_argument("--track", action="store_true", help="only follow open trades (no new signals)")
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
    if a.track:
        tracker.run(st, src, s)
        save_state(st)
        return print(f"tracking {len(st['open'])} open trade(s)")
    bar = TF_MINUTES[s.timeframe] * 60
    while True:
        tracker.run(st, src, s)
        save_state(st)
        for sym in s.symbols:
            try:
                df, htf = src.candles(sym, s.timeframe), src.candles(sym, s.htf)
                sig = evaluate(sym.name, df, htf, a.min_touches, ltf_min=TF_MINUTES[s.timeframe],
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
