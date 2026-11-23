"""Run the wallet bot (paper by default). Usage: python3 -m wallet.run
Env file ~/.config/cliperz-wallet/keys.env: WALLET_TG_TOKEN, WALLET_OWNER_ID (your Telegram user id; also your private chat id),
optional WALLET_RPC_URL. Live mode is refused here until the live executor exists (phase 3) and the gate passes."""
import json, os, sys, threading, time
from . import notify, data
from .tg_trigger import parse_post, Seen, CHANNEL_ID
from .control import handle
from .executor import PaperExecutor
from .risk import Risk
from .trader import Trader
from .calls import ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.expanduser("~/.config/cliperz-wallet/keys.env")


def load_env(path=ENV):
    out = {}
    try:
        for line in open(path):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.strip().split("=", 1); out[k.strip()] = v.strip().strip("\"'")
    except FileNotFoundError:
        pass
    return {**out, **{k: v for k, v in os.environ.items() if k.startswith("WALLET_")}}


def main():
    cfg = json.load(open(os.path.join(HERE, "config.json")))
    env = load_env()
    if cfg["mode"] != "paper":
        sys.exit("Live mode is not available yet: the live executor is built only after the paper review (phase 3).")
    tok, owner = env.get("WALLET_TG_TOKEN"), env.get("WALLET_OWNER_ID")
    if not tok or not owner or not owner.lstrip("-").isdigit():
        sys.exit("Set WALLET_TG_TOKEN and WALLET_OWNER_ID in " + ENV)
    owner = int(owner)
    rpc = env.get("WALLET_RPC_URL", "https://api.mainnet-beta.solana.com")
    ex = PaperExecutor(data.jupiter_quote, lambda m: data.mint_info(m, rpc), cfg["execution"]["max_slippage_bps"])
    tr = Trader(cfg, ex, Risk(cfg), Seen(os.path.join(HERE, "state", "seen.json")), send=lambda t: notify.send(tok, owner, t))
    lock = threading.Lock()

    def ticker():
        while True:
            time.sleep(cfg["telegram"]["tick_seconds"])
            try:
                with lock: tr.tick()
            except Exception as e:
                print("[tick]", type(e).__name__, e)
    threading.Thread(target=ticker, daemon=True).start()

    import requests
    offset = 0
    print("wallet bot running (PAPER). Waiting for call-outs...")
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=40, params={
                "offset": offset, "timeout": 30, "allowed_updates": json.dumps(["channel_post", "message"])})
            r.raise_for_status()
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                sig = parse_post(u, CHANNEL_ID)
                if sig:
                    with lock: print(sig["mint"], tr.on_signal(sig))
                    continue
                with lock:
                    reply = handle(u, owner, os.path.join(HERE, "state"), ROOT, address=None,
                                   status_text=lambda: f"PAPER mode. Open positions: {len(tr.pos)}")
                if reply: notify.send(tok, owner, reply)
        except Exception as e:
            print("[poll]", type(e).__name__, e); time.sleep(3)


if __name__ == "__main__":
    main()
