"""The ONLY component that holds the master key or decrypts wallets. Runs as its own OS user, talks over a 0600 Unix socket.
It never trusts the app: PIN checks, withdrawal policy, pause/freeze are all evaluated here from its own DB. Every request is
validated strictly and anything malformed fails closed. It builds the withdrawal transaction itself from structured fields."""
import json, os, socketserver, sys, time
from . import pin as pinmod, policy
from .keystore import Keystore
from .signer_db import SignerDB
from . import solana, swap_guard, fees as feemod

MAX_LINE = 4096
OPS = {"create_wallet", "status", "set_pin", "add_address", "withdraw", "export_key", "admin_freeze", "admin_pause", "swap", "set_limits", "get_limits"}
DEFAULT_LIMITS = {"max_trade": 10 ** 9, "daily": 3 * 10 ** 9, "hourly": 20, "pin_free": 5 * 10 ** 8}
HARD_MAX = {"max_trade": 10 * 10 ** 9, "daily": 50 * 10 ** 9, "hourly": 120, "pin_free": 10 * 10 ** 9}
LIMIT_COOLDOWN = 86400
SLIPPAGE_CAP_BPS = 1500


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
        except (BadRequest, policy.Refused, pinmod.PinError, swap_guard.Refuse) as e:
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

    # ---------- trading ----------
    def _limits(self, tg, now):
        base = {**DEFAULT_LIMITS, **self.cfg.get("limits", {})}
        row = self.db.limits_row(tg)
        if not row:
            return dict(base)
        vals = {k: row[k] for k in DEFAULT_LIMITS}
        if row["pending"] and row["effective_at"] and now >= row["effective_at"]:
            vals.update(json.loads(row["pending"])); self.db.save_limits(tg, vals, None, None)
        return vals

    def op_get_limits(self, req):
        tg, w = self._wallet(req); return {"limits": self._limits(tg, self.clock())}

    def op_set_limits(self, req):
        tg, w = self._wallet(req); self._gate(w); now = self.clock()
        cur = self._limits(tg, now); want = req.get("limits")
        if not isinstance(want, dict) or not want or set(want) - set(DEFAULT_LIMITS):
            raise BadRequest("bad limits")
        applied, pending = dict(cur), {}
        for k, v in want.items():
            v = _int(v, k, 0, HARD_MAX[k] + 1)
            if v <= cur[k]: applied[k] = v
            else: pending[k] = v
        if pending:
            if not self._verify_pin(tg, w, req.get("pin")):
                raise pinmod.PinError("PIN required to raise limits")
        eff = now + LIMIT_COOLDOWN if pending else None
        self.db.save_limits(tg, applied, pending or None, eff)
        self.db.audit(tg, "limits_changed", {"applied": applied, "pending": pending}, now)
        return {"limits": applied, "pending": pending, "effective_at": eff}

    def _send_fee(self, tg, w, lamports):
        """SOL transfer of our fee to the configured fee wallet, built entirely here. Returns signature or None."""
        try:
            msg = solana.transfer_message(w["pubkey"], self.cfg["fee_wallet"], lamports, self.rpc.get_blockhash())
            return self.rpc.send(solana.transfer_tx(msg, self.ks.sign(w["pubkey"], w["blob"], msg)))
        except Exception:
            return None

    def _settle_owed(self, tg, w):
        for r in self.db.owed_fees(tg):
            sig = self._send_fee(tg, w, r["fee"])
            if sig: self.db.settle_fee(r["id"], sig)

    def op_swap(self, req):
        from solders.hash import Hash
        from solders.message import MessageV0, to_bytes_versioned
        from solders.signature import Signature
        from solders.system_program import transfer, TransferParams
        from solders.transaction import VersionedTransaction
        from solders.pubkey import Pubkey
        tg, w = self._wallet(req); self._gate(w); now = self.clock()
        if not self.cfg.get("trading_enabled"):
            raise policy.Refused("trading is disabled on this server")          # enforced here, the real security boundary, not just in the app
        if not self.cfg.get("fee_wallet"):
            raise BadRequest("trading not configured")
        side = req.get("side")
        if side not in ("buy", "sell"): raise BadRequest("bad side")
        mint = _str(req.get("mint"), "mint", 44)
        amount, min_out, quote_out = _int(req.get("amount"), "amount"), _int(req.get("min_out"), "min_out"), _int(req.get("quote_out"), "quote_out")
        slip = _int(req.get("slippage_bps"), "slippage_bps", 1, 10_001)
        cap = self.cfg.get("slippage_cap_bps", SLIPPAGE_CAP_BPS)
        if slip > cap or min_out < quote_out * (10_000 - cap) // 10_000:
            raise policy.Refused("slippage above the allowed maximum")
        lim = self._limits(tg, now)
        if self.db.swaps_since(tg, now - 3600) >= lim["hourly"]:
            raise policy.Refused("hourly trade limit reached")
        bps = self.cfg.get("fee_bps", 100)
        if side == "buy":
            if amount > lim["max_trade"]: raise policy.Refused("above your per-trade limit")
            if self.db.volume_since(tg, now - 86400) + amount > lim["daily"]: raise policy.Refused("daily trade limit reached")
            if amount > lim["pin_free"]:
                if req.get("pin") is None: raise pinmod.PinError("PIN required for this trade size")
                if not self._verify_pin(tg, w, req.get("pin")): raise pinmod.PinError("wrong PIN")
            fee = feemod.fee(amount, bps); net = amount - fee
        else:
            fee = 0; net = 0
        self._settle_owed(tg, w)
        try:
            ixs, priority = swap_guard.validate(w["pubkey"], side, mint, net, req.get("jup"), self.cfg.get("guard"))
        except swap_guard.Refuse as e:
            self.db.audit(tg, "swap_refused", {"why": str(e), "side": side, "mint": mint}, now); raise policy.Refused(str(e))
        keys = [w["pubkey"], str(swap_guard.ata(w["pubkey"], mint)), str(swap_guard.ata(w["pubkey"], swap_guard.WSOL))]
        pre = swap_guard.parse_snapshot(self.rpc.get_accounts(keys), w["pubkey"], mint)
        if side == "sell" and pre["tokens"][mint] < amount:
            raise policy.Refused("not enough tokens")
        if side == "buy" and pre["eff_sol"] < amount + 3 * swap_guard.ATA_RENT:
            raise policy.Refused("insufficient SOL")
        payer = Pubkey.from_string(w["pubkey"])
        full = ([transfer(TransferParams(from_pubkey=payer, to_pubkey=Pubkey.from_string(self.cfg["fee_wallet"]), lamports=fee))] if fee else []) + ixs
        alts = [self.rpc.get_alt(k) for k in (req["jup"].get("addressLookupTableAddresses") or [])[:8]]
        msg = MessageV0.try_compile(payer, full, alts, Hash.from_string(self.rpc.get_blockhash()))
        sim = self.rpc.simulate(bytes(VersionedTransaction.populate(msg, [Signature.default()])), keys)
        if sim.get("err"):
            raise policy.Refused("simulation failed")
        post = swap_guard.parse_snapshot(sim["accounts"], w["pubkey"], mint)
        try:
            gain = swap_guard.check_simulation(side, mint, pre, post, amount if side == "buy" else 0, net if side == "buy" else amount, min_out, priority)
        except swap_guard.Refuse as e:
            self.db.audit(tg, "swap_refused", {"why": str(e), "side": side, "mint": mint}, now); raise
        sig_bytes = self.ks.sign(w["pubkey"], w["blob"], to_bytes_versioned(msg))
        sig = self.rpc.send(bytes(VersionedTransaction.populate(msg, [Signature.from_bytes(sig_bytes)])))
        volume = amount if side == "buy" else gain
        self.db.record_swap(tg, now, side, mint, volume, sig)
        out = {"sig": sig, "confirmed": bool(self.rpc.confirm(sig)), "fee_lamports": fee,
               "est_tokens": post["tokens"][mint] - pre["tokens"][mint], "est_sol": gain}
        if side == "buy":
            self.db.add_fee(tg, now, side, mint, amount, fee, sig, 1 if out["confirmed"] else 2)   # 2 = in-tx, unconfirmed: reconcile on-chain, never re-send
        else:
            sfee = feemod.fee(gain, bps) if out["confirmed"] else 0
            if sfee >= 5_000:
                fsig = self._send_fee(tg, w, sfee)
                self.db.add_fee(tg, now, side, mint, gain, sfee, fsig, bool(fsig))
            out["fee_lamports"] = sfee
        self.db.audit(tg, "swap", {"side": side, "mint": mint, "amount": amount, "sig": sig}, now)
        return out

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

    def mint_info(self, mint):
        v = self._call("getAccountInfo", [mint, {"encoding": "jsonParsed"}])["value"]
        if not v: return None
        i = v["data"]["parsed"]["info"]
        return {"mint_authority": i.get("mintAuthority"), "freeze_authority": i.get("freezeAuthority")}

    def get_accounts(self, keys):
        return self._call("getMultipleAccounts", [keys, {"encoding": "jsonParsed", "commitment": "confirmed"}])["value"]

    def simulate(self, tx: bytes, keys):
        import base64
        r = self._call("simulateTransaction", [base64.b64encode(tx).decode(), {"encoding": "base64", "sigVerify": False, "replaceRecentBlockhash": True,
                       "commitment": "confirmed", "accounts": {"encoding": "jsonParsed", "addresses": keys}}])["value"]
        return {"err": r.get("err"), "accounts": r.get("accounts")}

    def get_alt(self, key):
        import base64
        from solders.address_lookup_table_account import AddressLookupTableAccount
        from solders.pubkey import Pubkey
        v = self._call("getAccountInfo", [key, {"encoding": "base64"}])["value"]
        raw = base64.b64decode(v["data"][0])[56:]
        return AddressLookupTableAccount(Pubkey.from_string(key), [Pubkey.from_bytes(raw[i:i + 32]) for i in range(0, len(raw) - len(raw) % 32, 32)])

    def confirm(self, sig, timeout=30):
        import time as _t
        end = _t.time() + timeout
        while _t.time() < end:
            st = self._call("getSignatureStatuses", [[sig]])["value"][0]
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"): return st.get("err") is None
            _t.sleep(1)
        return False

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
        cfg_path = os.path.join(base, "signer.json")                     # {"fee_wallet": "...", "fee_bps": 100, "limits": {...}} (signer user only)
        cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
        if cfg.get("fee_wallet"): solana.pubkey_bytes(cfg["fee_wallet"])  # refuse to start with an invalid fee wallet
        serve(Signer(Keystore(base64.b64decode(key)), db, SolanaRPC(os.environ["TRADEBOT_RPC_URL"]), pause, cfg=cfg),
              os.environ.get("TRADEBOT_SOCKET", os.path.join(base, "signer.sock")))
        return
    print("usage: python3 -m tradebot.signer serve | resume | unfreeze <tg_id>")


if __name__ == "__main__":
    main(sys.argv[1:])
