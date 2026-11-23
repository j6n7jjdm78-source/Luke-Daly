import json, os, pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from tradebot.keystore import Keystore, b58encode
from tradebot.signer import Signer, SignerClient, serve, MAX_LINE
from tradebot.signer_db import SignerDB
from tradebot import solana

MK = bytes(range(32)); T = [1_000_000.0]
DEST = b58encode(bytes([9]) * 32); BH = b58encode(bytes([7]) * 32)


class FakeRPC:
    def __init__(self): self.bal = 3 * 10 ** 9; self.sent = []
    def get_balance(self, pk): return self.bal
    def get_blockhash(self): return BH
    def send(self, tx): self.sent.append(tx); return "SIG" + str(len(self.sent))


@pytest.fixture
def env(tmp_path):
    T[0] = 1_000_000.0
    rpc = FakeRPC(); db = SignerDB(str(tmp_path / "s.db"))
    s = Signer(Keystore(MK), db, rpc, str(tmp_path / "PAUSE"), clock=lambda: T[0])
    s.rpc_, s.t = rpc, tmp_path
    return s


def ready(s, tg=1, pin="483920"):
    pk = s.handle({"op": "create_wallet", "tg_id": tg})["pubkey"]
    assert s.handle({"op": "set_pin", "tg_id": tg, "pin": pin})["ok"]
    assert s.handle({"op": "add_address", "tg_id": tg, "pin": pin, "address": DEST})["ok"]
    return pk


def wd(s, **kw): return s.handle({"op": "withdraw", "tg_id": 1, "pin": "483920", "dest": DEST, "lamports": 10 ** 9, **kw})


def test_transfer_signed_by_signer_and_valid(env):
    pk = ready(env); T[0] += 2 * 86400
    r = wd(env); assert r["ok"] and r["sig"] == "SIG1"
    tx = env.rpc_.sent[0]; assert tx[0] == 1 and len(tx) == 1 + 64 + len(tx) - 65
    sig, msg = tx[1:65], tx[65:]
    Ed25519PublicKey.from_public_bytes(solana.pubkey_bytes(pk)).verify(sig, msg)       # signature really verifies
    assert msg == solana.transfer_message(pk, DEST, 10 ** 9, BH)
    assert msg[3 + 1:3 + 1 + 32] == solana.pubkey_bytes(pk) and solana.pubkey_bytes(DEST) in msg


def test_withdraw_refusals(env):
    ready(env)
    assert "cooldown" in wd(env)["error"]                                  # new address
    T[0] += 2 * 86400
    assert "PIN" in wd(env, pin="000111")["error"] or "wrong" in wd(env, pin="000111")["error"]
    assert not wd(env, dest=b58encode(bytes([8]) * 32))["ok"]                # not whitelisted
    assert not wd(env, lamports=6 * 10 ** 9)["ok"] and not wd(env, lamports=0)["ok"] and not wd(env, lamports=-5)["ok"]
    assert not wd(env, lamports=True)["ok"] and not wd(env, lamports=1.5)["ok"] and not wd(env, lamports="9")["ok"]
    assert not wd(env, lamports=3 * 10 ** 9)["ok"]                          # no fee reserve left
    assert env.rpc_.sent == []                                              # nothing ever sent on refusals


def test_daily_limit_across_withdrawals(env):
    ready(env); T[0] += 2 * 86400; env.rpc_.bal = 20 * 10 ** 9
    assert wd(env, lamports=3 * 10 ** 9)["ok"] and wd(env, lamports=2 * 10 ** 9)["ok"]
    assert "daily" in wd(env, lamports=10 ** 9)["error"]
    T[0] += 86401; assert wd(env, lamports=10 ** 9)["ok"]


def test_pin_lockout_enforced_in_signer(env):
    ready(env); T[0] += 2 * 86400
    for _ in range(5): wd(env, pin="000111")
    r = wd(env); assert not r["ok"] and "locked" in r["error"] and env.rpc_.sent == []   # right PIN refused while locked
    T[0] += 901; assert wd(env)["ok"]


def test_pause_and_freeze_block_everything(env):
    ready(env); T[0] += 2 * 86400
    assert env.handle({"op": "admin_pause"})["ok"] and not wd(env)["ok"]
    assert not env.handle({"op": "export_key", "tg_id": 1, "pin": "483920", "confirm": "EXPORT"})["ok"]
    os.unlink(env.pause_file); assert wd(env)["ok"]
    env.handle({"op": "admin_freeze", "tg_id": 1}); assert "frozen" in wd(env)["error"]
    assert env.handle({"op": "status", "tg_id": 1})["frozen"] is True      # no op unfreezes: that is server CLI only


def test_pin_change_requires_old_pin(env):
    ready(env)
    assert not env.handle({"op": "set_pin", "tg_id": 1, "pin": "902817"})["ok"]
    assert not env.handle({"op": "set_pin", "tg_id": 1, "pin": "902817", "old_pin": "111222"})["ok"]
    assert env.handle({"op": "set_pin", "tg_id": 1, "pin": "902817", "old_pin": "483920"})["ok"]


def test_export_needs_pin_and_confirm_and_is_audited(env):
    pk = ready(env)
    base = {"op": "export_key", "tg_id": 1, "pin": "483920"}
    assert not env.handle(base)["ok"] and not env.handle({**base, "confirm": "yes"})["ok"]
    assert not env.handle({**base, "pin": "000111", "confirm": "EXPORT"})["ok"]
    k = json.loads(env.handle({**base, "confirm": "EXPORT"})["key"]); assert b58encode(bytes(k[32:])) == pk
    assert env.db.c.execute("SELECT COUNT(*) FROM audit WHERE event='key_exported'").fetchone()[0] == 1


def test_wallet_never_in_responses_and_idempotent(env):
    r1 = env.handle({"op": "create_wallet", "tg_id": 7}); r2 = env.handle({"op": "create_wallet", "tg_id": 7})
    assert r1["pubkey"] == r2["pubkey"] and r1["created"] and not r2["created"]
    assert set(r1) == {"ok", "pubkey", "created"}
    st = env.handle({"op": "status", "tg_id": 7}); assert "blob" not in json.dumps(st)


HOSTILE = [None, [], "x", 5, {}, {"op": "nope"}, {"op": "withdraw"}, {"op": "withdraw", "tg_id": "1"},
           {"op": "withdraw", "tg_id": 1, "pin": 5, "dest": 5, "lamports": 5}, {"op": "create_wallet", "tg_id": -1},
           {"op": "create_wallet", "tg_id": 10 ** 40}, {"op": "create_wallet", "tg_id": True},
           {"op": "add_address", "tg_id": 1, "pin": "x" * 1000, "address": "y"}, {"op": "set_pin", "tg_id": 1, "pin": None}]


def test_hostile_requests_fail_closed(env):
    ready(env)
    for h in HOSTILE:
        r = env.handle(h); assert r["ok"] is False and "error" in r
    assert env.rpc_.sent == []


def test_unknown_user_ops_fail(env):
    for op in ("status", "withdraw", "export_key", "set_pin", "add_address", "admin_freeze"):
        assert not env.handle({"op": op, "tg_id": 99, "pin": "483920", "dest": DEST, "lamports": 5, "address": DEST})["ok"]


def test_socket_roundtrip_and_oversize(env, tmp_path):
    import threading, socket, time
    sp = str(tmp_path / "s.sock"); threading.Thread(target=serve, args=(env, sp), daemon=True).start()
    for _ in range(50):
        if os.path.exists(sp): break
        time.sleep(0.05)
    assert oct(os.stat(sp).st_mode)[-3:] == "600"
    c = SignerClient(sp); r = c({"op": "create_wallet", "tg_id": 3}); assert r["ok"] and "pubkey" in r
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(sp); s.sendall(b"x" * (MAX_LINE + 10) + b"\n"); assert json.loads(s.makefile().readline())["ok"] is False
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(sp); s.sendall(b"not json\n"); assert json.loads(s.makefile().readline())["ok"] is False


def test_base58_and_tx_helpers():
    assert solana.b58decode(b58encode(bytes([0, 0, 5, 200]))) == bytes([0, 0, 5, 200])
    with pytest.raises(ValueError): solana.b58decode("0OIl")
    with pytest.raises(ValueError): solana.transfer_message(DEST, DEST, 0, BH)
    with pytest.raises(ValueError): solana.transfer_message(DEST, DEST, 5, b58encode(b"short"))
