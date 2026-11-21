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
