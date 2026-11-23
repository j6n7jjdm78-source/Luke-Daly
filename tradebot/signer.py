"""The ONLY component that holds the master key or decrypts wallets. Runs as its own OS user, talks over a 0600 Unix socket.
It never trusts the app: PIN checks, withdrawal policy, pause/freeze are all evaluated here from its own DB. Every request is
validated strictly and anything malformed fails closed. It builds the withdrawal transaction itself from structured fields."""
import json, os, socketserver, sys, time
from . import pin as pinmod, policy
from .keystore import Keystore
from .signer_db import SignerDB
from . import solana

MAX_LINE = 4096
OPS = {"create_wallet", "status", "set_pin", "add_address", "withdraw", "export_key", "admin_freeze", "admin_pause"}


class BadRequest(Exception):
    pass


def _int(v, name, lo=1, hi=2 ** 63):
    if isinstance(v, bool) or not isinstance(v, int) or not (lo <= v < hi):
        raise BadRequest(f"bad {name}")
    return v


def _str(v, name, maxlen=64):
    if not isinstance(v, str) or not (0 < len(v) <= maxlen):
        raise BadRequest(f"bad {name}")
    return v


class Signer:
    def __init__(self, ks: Keystore, db: SignerDB, rpc, pause_file, cfg=None, clock=time.time):
        self.ks, self.db, self.rpc, self.pause_file, self.cfg, self.clock = ks, db, rpc, pause_file, cfg or {}, clock

    def paused(self):
        return os.path.exists(self.pause_file)

    def handle(self, req):
        """req: dict. Returns {'ok': True, ...} or {'ok': False, 'error': str}. Never raises."""
        try:
            if not isinstance(req, dict) or req.get("op") not in OPS:
                raise BadRequest("bad request")
            return {"ok": True, **getattr(self, "op_" + req["op"])(req)}
        except (BadRequest, policy.Refused, pinmod.PinError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:                       # fail closed; never leak internals
            self.db.audit(None, "internal_error", {"type": type(e).__name__}, self.clock())
            return {"ok": False, "error": "internal error"}

    # ---- helpers
    def _wallet(self, req):
        tg = _int(req.get("tg_id"), "tg_id", 1, 2 ** 53)
        w = self.db.wallet(tg)
        if not w:
            raise BadRequest("no wallet")
        return tg, w

    def _gate(self, w):
        if self.paused():
            raise policy.Refused("paused")
        if w["frozen"]:
            raise policy.Refused("account frozen")

    def _verify_pin(self, tg, w, pin):
        if not w["pin_hash"]:
            raise pinmod.PinError("set a PIN first")
        ok, st = pinmod.verify(_str(pin, "pin", 32), w["pin_hash"], json.loads(w["pin_state"] or "{}"), self.clock())
        self.db.save_pin_state(tg, st)
        return ok

    # ---- ops
    def op_create_wallet(self, req):
        tg = _int(req.get("tg_id"), "tg_id", 1, 2 ** 53)
        w = self.db.wallet(tg)
        if not w:
            pk, blob = self.ks.new_wallet(); self.db.add_wallet(tg, pk, blob); self.db.audit(tg, "wallet_created", {"pubkey": pk}, self.clock())
            return {"pubkey": pk, "created": True}
        return {"pubkey": w["pubkey"], "created": False}

    def op_status(self, req):
        tg, w = self._wallet(req)
        return {"pubkey": w["pubkey"], "has_pin": bool(w["pin_hash"]), "frozen": bool(w["frozen"]), "paused": self.paused(),
                "addresses": sorted(self.db.whitelist(tg))}

    def op_set_pin(self, req):
        tg, w = self._wallet(req); self._gate(w)
        if w["pin_hash"]:                                         # changing a PIN needs the old one
            if not self._verify_pin(tg, w, req.get("old_pin")):
                self.db.audit(tg, "pin_change_denied", {}, self.clock()); raise pinmod.PinError("wrong PIN")
        self.db.set_pin(tg, pinmod.hash_pin(_str(req.get("pin"), "pin", 32)))
        self.db.audit(tg, "pin_set", {}, self.clock())
        return {}

    def op_add_address(self, req):
        tg, w = self._wallet(req)
        ok = self._verify_pin(tg, w, req.get("pin"))
        addr = _str(req.get("address"), "address", 44)
        policy.check_add_address(pin_ok=ok, address=addr, whitelist=self.db.whitelist(tg), global_paused=self.paused(), user_frozen=bool(w["frozen"]))
        solana.pubkey_bytes(addr)                                 # must decode to 32 bytes
        self.db.add_address(tg, addr, self.clock()); self.db.audit(tg, "address_added", {"address": addr}, self.clock())
        return {"cooldown_s": policy.DEFAULTS["address_cooldown_s"]}

    def op_withdraw(self, req):
        tg, w = self._wallet(req)
        ok = self._verify_pin(tg, w, req.get("pin"))
        dest, lamports = _str(req.get("dest"), "dest", 44), _int(req.get("lamports"), "lamports")
        now = self.clock()
        pol = {**policy.DEFAULTS, **self.cfg.get("policy", {})}
        try:
            policy.check_withdrawal(pin_ok=ok, dest=dest, amount=lamports, balance=self.rpc.get_balance(w["pubkey"]),
                                    whitelist=self.db.whitelist(tg), spent_24h=self.db.withdrawn_since(tg, now - 86400), now=now,
                                    global_paused=self.paused(), user_frozen=bool(w["frozen"]), cfg=pol)
        except policy.Refused as e:
            self.db.audit(tg, "withdraw_refused", {"dest": dest, "lamports": lamports, "why": str(e)}, now); raise
        msg = solana.transfer_message(w["pubkey"], dest, lamports, self.rpc.get_blockhash())
        sig = self.rpc.send(solana.transfer_tx(msg, self.ks.sign(w["pubkey"], w["blob"], msg)))
        self.db.record_withdrawal(tg, dest, lamports, now, sig); self.db.audit(tg, "withdrawn", {"dest": dest, "lamports": lamports, "sig": sig}, now)
        return {"sig": sig}

    def op_export_key(self, req):
        tg, w = self._wallet(req); self._gate(w)
        if req.get("confirm") != "EXPORT":
            raise BadRequest("confirmation required")
        if not self._verify_pin(tg, w, req.get("pin")):
            self.db.audit(tg, "export_denied", {}, self.clock()); raise pinmod.PinError("wrong PIN")
        self.db.audit(tg, "key_exported", {}, self.clock())
        return {"key": self.ks.export_json(w["pubkey"], w["blob"])}

    def op_admin_freeze(self, req):                               # freezing is always allowed; unfreezing is server-CLI only
        tg, w = self._wallet(req); self.db.set_frozen(tg, True); self.db.audit(tg, "frozen", {}, self.clock()); return {}

    def op_admin_pause(self, req):                                # pausing is allowed; resuming is server-CLI only
        open(self.pause_file, "a").close(); self.db.audit(None, "paused", {}, self.clock()); return {}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        line = self.rfile.readline(MAX_LINE + 1)
        if not line or len(line) > MAX_LINE:
            resp = {"ok": False, "error": "bad request"}
        else:
            try: req = json.loads(line)
            except Exception: req = None
            resp = self.server.signer.handle(req)
        self.wfile.write((json.dumps(resp) + "\n").encode())


def serve(signer, sock_path):
    if os.path.exists(sock_path): os.unlink(sock_path)
    srv = socketserver.ThreadingUnixStreamServer(sock_path, _Handler); srv.signer = signer
    os.chmod(sock_path, int(os.environ.get("TRADEBOT_SOCKET_MODE", "600"), 8))   # 0660 in deployment: group 'tradebot' only
    srv.serve_forever()


class SignerClient:
    def __init__(self, sock_path): self.path = sock_path

    def __call__(self, req):
        import socket
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(30); s.connect(self.path); s.sendall((json.dumps(req) + "\n").encode())
            return json.loads(s.makefile().readline())


class SolanaRPC:
    """Real RPC used on the server. Injected so tests never touch the network."""
    def __init__(self, url):
        import requests; self.url, self.s = url, requests.Session()

    def _call(self, method, params):
        r = self.s.post(self.url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15); r.raise_for_status()
        j = r.json()
        if "error" in j: raise RuntimeError(j["error"])
        return j["result"]

    def get_balance(self, pubkey): return int(self._call("getBalance", [pubkey, {"commitment": "confirmed"}])["value"])
    def get_blockhash(self): return self._call("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"]

    def send(self, tx: bytes):
        import base64
        return self._call("sendTransaction", [base64.b64encode(tx).decode(), {"encoding": "base64", "preflightCommitment": "confirmed"}])


def main(argv):
    """Server CLI. serve | resume | unfreeze <tg_id>. Paths/secrets come from the signer user's own environment/files."""
    base = os.environ.get("TRADEBOT_STATE", "/var/lib/tradebot-signer")
    pause = os.path.join(base, "PAUSE"); db = SignerDB(os.path.join(base, "signer.db"))
    if argv[:1] == ["resume"]:
        if os.path.exists(pause): os.unlink(pause)
        print("resumed"); return
    if argv[:1] == ["unfreeze"] and len(argv) == 2:
        db.set_frozen(int(argv[1]), False); print("unfrozen", argv[1]); return
    if argv[:1] == ["serve"]:
        key = open(os.environ.get("TRADEBOT_MASTER_KEY_FILE", os.path.join(base, "master.key"))).read().strip()
        import base64
        serve(Signer(Keystore(base64.b64decode(key)), db, SolanaRPC(os.environ["TRADEBOT_RPC_URL"]), pause),
              os.environ.get("TRADEBOT_SOCKET", os.path.join(base, "signer.sock")))
        return
    print("usage: python3 -m tradebot.signer serve | resume | unfreeze <tg_id>")


if __name__ == "__main__":
    main(sys.argv[1:])
