"""Telegram UI. `App.handle(update) -> list of actions` is pure (no network) so it is fully testable; `run()` is a thin poller.
The app never sees keys, PIN hashes or the whitelist: everything sensitive goes through the signer socket."""
import html, json, os, time
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation

LAMPORTS = 10 ** 9
TTL = 300
NEXT = {"setpin", "addaddr", "withdraw", "export"}
SOON = {"trending", "alerts", "orders", "top", "refer", "sniper", "copy", "settings", "positions"}


def _kb(rows): return [[{"text": t, "callback_data": d} for t, d in r] for r in rows]


class App:
    def __init__(self, signer, db, cfg, rpc_balance, clock=time.time):
        self.signer, self.db, self.cfg, self.rpc_balance, self.clock = signer, db, cfg, rpc_balance, clock
        self.state, self.hits = {}, defaultdict(lambda: deque(maxlen=30))
        self.brand = html.escape(cfg.get("brand", "TradeBot"))
        self.admin = cfg.get("admin_id")

    # ---------- helpers
    def _send(self, chat, text, rows=None, delete_after=None):
        return {"op": "send", "chat_id": chat, "text": text, "keyboard": _kb(rows) if rows else None, "delete_after": delete_after}

    def _limited(self, uid):
        now = self.clock(); q = self.hits[uid]; q.append(now)
        return len(q) >= 20 and now - q[0] < 10

    def _balance(self, uid, pubkey):
        try:
            b = int(self.rpc_balance(pubkey)); self.db.set_balance(uid, b); return b
        except Exception:
            return None

    def _ensure(self, uid):
        r = self.signer({"op": "create_wallet", "tg_id": uid})
        if not r.get("ok"): return None
        self.db.ensure_user(uid, self.clock(), pubkey=r["pubkey"]); return r["pubkey"]

    def _fee(self): return self.cfg.get("fee_bps", 100) / 100

    # ---------- screens
    def home(self, uid, chat):
        pk = self._ensure(uid)
        if not pk: return [self._send(chat, "Wallet service unavailable. Try again shortly.")]
        bal = self._balance(uid, pk)
        b = "unavailable" if bal is None else f"{bal / LAMPORTS:.4f} SOL"
        net = "" if self.cfg.get("network") == "mainnet" else f"\nNetwork: <b>{html.escape(self.cfg.get('network', 'devnet'))}</b> (test funds only)"
        txt = (f"<b>{self.brand}</b> · Solana\n──────────\n{b}\n0 positions{net}\n\nYour wallet (tap to copy):\n<code>{pk}</code>\n"
               f"Send SOL to this address to start.\nTrading fee: {self._fee():g}% per trade.")
        rows = [[("Deposit SOL", "deposit")], [("Trending", "soon:trending"), ("Alerts", "soon:alerts"), ("Orders", "soon:orders")],
                [("Top", "soon:top"), ("Refer", "soon:refer")], [("Wallet", "wallet"), ("Help", "help"), ("Refresh", "home")]]
        return [self._send(chat, txt, rows)]

    def welcome(self, uid, chat):
        self._ensure(uid)
        txt = (f"<b>Welcome to {self.brand}</b>\nTrade Solana tokens from Telegram.\n\n"
               f"• Your wallet is created for you and <b>the bot holds the key</b> (custodial). You can export it any time in Wallet.\n"
               f"• Set a PIN to protect withdrawals. Withdrawals go only to addresses you register, after a waiting period.\n"
               f"• Fee: {self._fee():g}% per trade.\n• Trade only what you can afford to lose. Not financial advice.")
        return [self._send(chat, txt, [[("Start", "home")]])]

    def wallet(self, uid, chat):
        self._ensure(uid)
        st = self.signer({"op": "status", "tg_id": uid})
        if not st.get("ok"): return [self._send(chat, "Wallet unavailable.")]
        txt = (f"<b>Wallet</b>\n<code>{st['pubkey']}</code>\nPIN: {'set' if st['has_pin'] else 'NOT set'}  ·  Withdrawal addresses: {len(st['addresses'])}"
               + ("\n⚠️ Trading and withdrawals are paused." if st["paused"] else "") + ("\n⚠️ Account frozen." if st["frozen"] else ""))
        rows = [[("Set / change PIN", "setpin")], [("Add withdrawal address", "addaddr"), ("Withdraw", "withdraw")], [("Export key", "export")], [("Back", "home")]]
        return [self._send(chat, txt, rows)]

    def deposit(self, uid, chat):
        pk = self._ensure(uid)
        cap = self.cfg.get("max_total_deposits_sol")
        if self.cfg.get("network") == "mainnet" and (cap is None or self.db.total_balance() >= cap * LAMPORTS):
            return [self._send(chat, "Deposits are temporarily full during the private beta.", [[("Back", "home")]])]
        return [self._send(chat, f"Send SOL to your wallet:\n<code>{pk}</code>\nBalance updates when you tap Refresh.", [[("Refresh", "home"), ("Back", "home")]])]

    # ---------- flows
    def _start(self, uid, step, data=None): self.state[uid] = {"step": step, "data": data or {}, "exp": self.clock() + TTL}

    def _begin(self, uid, chat, what):
        self._ensure(uid)
        st = self.signer({"op": "status", "tg_id": uid})
        if not st.get("ok"): return [self._send(chat, "Wallet unavailable.")]
        if st["paused"] or st["frozen"]: return [self._send(chat, "Not available right now.", [[("Back", "wallet")]])]
        if what == "setpin":
            self._start(uid, "pin_old" if st["has_pin"] else "pin_new")
            return [self._send(chat, "Enter your CURRENT PIN:" if st["has_pin"] else "Choose a PIN (6 to 12 digits). Your message will be deleted.")]
        if what == "addaddr":
            if not st["has_pin"]: return [self._send(chat, "Set a PIN first.", [[("Set PIN", "setpin")]])]
            self._start(uid, "addr_addr"); return [self._send(chat, "Send the Solana address you want to withdraw to. New addresses wait 24h before they can be used.")]
        if what == "withdraw":
            if not st["has_pin"] or not st["addresses"]: return [self._send(chat, "Set a PIN and register a withdrawal address first.", [[("Wallet", "wallet")]])]
            self._start(uid, "wd_pick", {"addrs": st["addresses"]})
            return [self._send(chat, "Withdraw to which address?", [[(a[:6] + "…" + a[-4:], f"wd:{i}")] for i, a in enumerate(st["addresses"])] + [[("Cancel", "wallet")]])]
        if what == "export":
            if not st["has_pin"]: return [self._send(chat, "Set a PIN first.", [[("Set PIN", "setpin")]])]
            self._start(uid, "exp_pin"); return [self._send(chat, "Enter your PIN to export your private key. Anyone with the key controls the wallet.")]

    def _text_step(self, uid, chat, msg_id, text):
        s = self.state[uid]; step = s["step"]; out = []
        secret = step in ("pin_old", "pin_new", "addr_pin", "wd_pin", "exp_pin")
        if secret: out.append({"op": "delete", "chat_id": chat, "message_id": msg_id})   # remove the PIN from the chat immediately
        text = text.strip()
        if step == "pin_old":
            s["data"]["old"] = text; s["step"] = "pin_new"; s["exp"] = self.clock() + TTL
            return out + [self._send(chat, "Now choose the NEW PIN (6 to 12 digits).")]
        if step == "pin_new":
            r = self.signer({"op": "set_pin", "tg_id": uid, "pin": text, **({"old_pin": s["data"]["old"]} if "old" in s["data"] else {})})
            self.state.pop(uid, None)
            return out + [self._send(chat, "✅ PIN saved." if r.get("ok") else f"❌ {html.escape(r.get('error', 'failed'))}", [[("Wallet", "wallet")]])]
        if step == "addr_addr":
            s["data"]["addr"] = text[:64]; s["step"] = "addr_pin"; s["exp"] = self.clock() + TTL
            return out + [self._send(chat, "Enter your PIN to confirm.")]
        if step == "addr_pin":
            r = self.signer({"op": "add_address", "tg_id": uid, "pin": text, "address": s["data"]["addr"]}); self.state.pop(uid, None)
            return out + [self._send(chat, "✅ Address registered. It can be used after the 24h waiting period." if r.get("ok") else f"❌ {html.escape(r.get('error', 'failed'))}", [[("Wallet", "wallet")]])]
        if step == "wd_amt":
            try:
                if len(text) > 24: raise InvalidOperation
                d = Decimal(text)
                if not d.is_finite() or d <= 0 or d > 1_000_000 or d.as_tuple().exponent < -9: raise InvalidOperation
                s["data"]["lamports"] = int(d * LAMPORTS)
            except InvalidOperation:
                return out + [self._send(chat, "Enter an amount in SOL, e.g. 0.5")]
            s["step"] = "wd_pin"; s["exp"] = self.clock() + TTL
            return out + [self._send(chat, f"Withdraw {d.normalize():f} SOL. Enter your PIN to confirm.")]
        if step == "wd_pin":
            r = self.signer({"op": "withdraw", "tg_id": uid, "pin": text, "dest": s["data"]["dest"], "lamports": s["data"]["lamports"]}); self.state.pop(uid, None)
            return out + [self._send(chat, f"✅ Sent. Signature: <code>{html.escape(r['sig'])}</code>" if r.get("ok") else f"❌ {html.escape(r.get('error', 'failed'))}", [[("Wallet", "wallet")]])]
        if step == "exp_pin":
            r = self.signer({"op": "export_key", "tg_id": uid, "pin": text, "confirm": "EXPORT"}); self.state.pop(uid, None)
            if not r.get("ok"): return out + [self._send(chat, f"❌ {html.escape(r.get('error', 'failed'))}", [[("Wallet", "wallet")]])]
            return out + [self._send(chat, "⚠️ Your private key (deletes in 60s). Never share it:\n<code>" + html.escape(r["key"]) + "</code>", None, delete_after=60)]
        self.state.pop(uid, None); return out

    # ---------- entry point
    def handle(self, update):
        cb = update.get("callback_query"); m = update.get("message")
        src = cb["message"] if cb else m
        if not src or (src.get("chat") or {}).get("type") != "private": return []        # private chats only
        uid, chat = (cb or m).get("from", {}).get("id"), src["chat"]["id"]
        if not isinstance(uid, int) or uid != chat: return []
        if self._limited(uid): return []
        s = self.state.get(uid)
        if s and self.clock() > s["exp"]: self.state.pop(uid, None); s = None
        if cb: return self._callback(uid, chat, cb)
        text = m.get("text") or ""
        if text.startswith("/"):
            cmd = text.split()[0].split("@")[0].lower()
            if cmd in ("/start", "/home", "/menu"):
                self.state.pop(uid, None); return (self.welcome(uid, chat) if cmd == "/start" and not self.db.user(uid) else self.home(uid, chat))
            if cmd == "/cancel": self.state.pop(uid, None); return [self._send(chat, "Cancelled.")]
            if uid == self.admin and cmd in ("/pause", "/resume", "/freeze", "/unfreeze"): return self._admin(chat, text)
            return []
        return self._text_step(uid, chat, m.get("message_id"), text) if s else []

    def _callback(self, uid, chat, cb):
        d = cb.get("data") or ""; ack = {"op": "answer", "callback_id": cb.get("id"), "text": None}
        if d.startswith("soon:") and d[5:] in SOON: ack["text"] = "Coming soon"; return [ack]
        s = self.state.get(uid)
        if d.startswith("wd:") and s and s["step"] == "wd_pick":
            try: s["data"]["dest"] = s["data"]["addrs"][int(d[3:])]
            except (ValueError, IndexError): return [ack]
            s["step"] = "wd_amt"; s["exp"] = self.clock() + TTL
            return [ack, self._send(chat, "How much SOL to withdraw?")]
        if d in ("home", "wallet", "deposit", "help"): self.state.pop(uid, None)
        if d == "home": return [ack] + self.home(uid, chat)
        if d == "wallet": return [ack] + self.wallet(uid, chat)
        if d == "deposit": return [ack] + self.deposit(uid, chat)
        if d == "help": return [ack, self._send(chat, "Paste a token address to trade (coming in the next release). Wallet holds your SOL; set a PIN, register an address, then withdraw. /cancel stops any step.")]
        if d in NEXT: return [ack] + self._begin(uid, chat, d)
        return [ack]

    def _admin(self, chat, text):
        parts = text.split(); cmd = parts[0].split("@")[0].lower()
        if cmd == "/pause": r = self.signer({"op": "admin_pause"}); return [self._send(chat, "Paused." if r.get("ok") else "Failed.")]
        if cmd == "/freeze" and len(parts) == 2 and parts[1].isdigit():
            r = self.signer({"op": "admin_freeze", "tg_id": int(parts[1])}); return [self._send(chat, "Frozen." if r.get("ok") else "No such wallet.")]
        if cmd in ("/resume", "/unfreeze"): return [self._send(chat, "For safety this is done on the server only:\npython3 -m tradebot.signer " + ("resume" if cmd == "/resume" else "unfreeze <tg_id>"))]
        return [self._send(chat, "Usage: /pause, /freeze <tg_id>")]


def run():
    """Thin poller. ~/.config/tradebot/keys.env: TRADEBOT_TG_TOKEN, TRADEBOT_ADMIN_ID, TRADEBOT_RPC_URL, TRADEBOT_SOCKET (default /run/tradebot/signer.sock)."""
    import requests, threading
    from .app_db import AppDB
    from .signer import SignerClient, SolanaRPC
    env = {}
    for line in open(os.path.expanduser("~/.config/tradebot/keys.env")):
        if "=" in line and not line.lstrip().startswith("#"): k, v = line.strip().split("=", 1); env[k] = v.strip().strip("\"'")
    cfg = json.load(open(os.path.join(os.path.dirname(__file__), "config.json")))
    if cfg.get("network") == "mainnet" and not cfg.get("mainnet_enabled"): raise SystemExit("mainnet is disabled in tradebot/config.json (mainnet_enabled=false)")
    cfg["admin_id"] = int(env["TRADEBOT_ADMIN_ID"]) if env.get("TRADEBOT_ADMIN_ID", "").isdigit() else None
    tok, rpc = env["TRADEBOT_TG_TOKEN"], SolanaRPC(env["TRADEBOT_RPC_URL"])
    app = App(SignerClient(env.get("TRADEBOT_SOCKET", "/run/tradebot/signer.sock")), AppDB(os.path.expanduser("~/.local/share/tradebot/app.db") if os.path.isdir(os.path.expanduser("~/.local/share/tradebot")) else ":memory:"), cfg, rpc.get_balance)
    api = f"https://api.telegram.org/bot{tok}/"

    def do(a):
        try:
            if a["op"] == "send":
                p = {"chat_id": a["chat_id"], "text": a["text"], "parse_mode": "HTML", "disable_web_page_preview": True}
                if a.get("keyboard"): p["reply_markup"] = json.dumps({"inline_keyboard": a["keyboard"]})
                r = requests.post(api + "sendMessage", json=p, timeout=15).json()
                if a.get("delete_after") and r.get("ok"):
                    mid = r["result"]["message_id"]; threading.Timer(a["delete_after"], lambda: requests.post(api + "deleteMessage", json={"chat_id": a["chat_id"], "message_id": mid}, timeout=15)).start()
            elif a["op"] == "delete": requests.post(api + "deleteMessage", json={"chat_id": a["chat_id"], "message_id": a["message_id"]}, timeout=15)
            elif a["op"] == "answer": requests.post(api + "answerCallbackQuery", json={"callback_query_id": a["callback_id"], "text": a.get("text") or ""}, timeout=15)
        except Exception as e: print("[send]", type(e).__name__)

    offset = 0; print("tradebot app running on", cfg.get("network"))
    while True:
        try:
            r = requests.get(api + "getUpdates", params={"offset": offset, "timeout": 30, "allowed_updates": json.dumps(["message", "callback_query"])}, timeout=40).json()
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                try:
                    for a in app.handle(u): do(a)
                except Exception as e: print("[handle]", type(e).__name__)
        except Exception as e: print("[poll]", type(e).__name__); time.sleep(3)


if __name__ == "__main__":
    run()
