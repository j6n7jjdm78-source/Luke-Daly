import json, pytest
from tradebot.app import App, LAMPORTS
from tradebot.app_db import AppDB
from tradebot.keystore import Keystore, b58encode
from tradebot.signer import Signer
from tradebot.signer_db import SignerDB

T = [1_000_000.0]; BH = b58encode(bytes([7]) * 32); DEST = b58encode(bytes([9]) * 32); PIN = "483920"
UID = 42


class FakeRPC:
    def __init__(self): self.bal = 3 * LAMPORTS; self.sent = []
    def get_balance(self, pk): return self.bal
    def get_blockhash(self): return BH
    def send(self, tx): self.sent.append(tx); return "SIGOK"


@pytest.fixture
def env(tmp_path):
    T[0] = 1_000_000.0; rpc = FakeRPC(); sdb = SignerDB(":memory:")
    sg = Signer(Keystore(bytes(range(32))), sdb, rpc, str(tmp_path / "PAUSE"), clock=lambda: T[0])
    cfg = {"brand": "TradeBot", "network": "devnet", "admin_id": 999, "max_total_deposits_sol": 5, "fee_bps": 100}
    app = App(sg.handle, AppDB(":memory:"), cfg, rpc.get_balance, clock=lambda: T[0])
    app.rpc, app.sg, app.sdb, app.sent_log = rpc, sg, sdb, []
    return app


def msg(text, uid=UID, mid=1, chat_type="private"): return {"message": {"message_id": mid, "from": {"id": uid}, "chat": {"id": uid, "type": chat_type}, "text": text}}
def cb(data, uid=UID): return {"callback_query": {"id": "c1", "from": {"id": uid}, "data": data, "message": {"message_id": 5, "chat": {"id": uid, "type": "private"}}}}


def run(app, upd):
    acts = app.handle(upd); app.sent_log += acts; return acts
def texts(acts): return " ".join(a.get("text") or "" for a in acts if a["op"] == "send")


def test_start_creates_wallet_and_shows_home(env):
    a = run(env, msg("/start")); assert "custodial" in texts(a) or "holds the key" in texts(a)
    h = run(env, cb("home")); t = texts(h)
    pk = env.sg.handle({"op": "status", "tg_id": UID})["pubkey"]
    assert pk in t and "3.0000 SOL" in t and "1% per trade" in t and "devnet" in t
    assert not (set(["blob", "secret"]) & set(t.split()))


def test_pin_flow_deletes_message_and_never_echoes_pin(env):
    run(env, msg("/start")); run(env, cb("setpin"))
    acts = run(env, msg(PIN, mid=77))
    assert {"op": "delete", "chat_id": UID, "message_id": 77} in acts
    assert "PIN saved" in texts(acts)
    assert all(PIN not in json.dumps(a) for a in env.sent_log)                            # PIN never appears in any outgoing action
    assert env.sg.handle({"op": "status", "tg_id": UID})["has_pin"] is True


def test_weak_pin_rejected(env):
    run(env, msg("/start")); run(env, cb("setpin")); acts = run(env, msg("123456", mid=3))
    assert "❌" in texts(acts) and env.sg.handle({"op": "status", "tg_id": UID})["has_pin"] is False


def full_setup(env):
    run(env, msg("/start")); run(env, cb("setpin")); run(env, msg(PIN, mid=2))
    run(env, cb("addaddr")); run(env, msg(DEST, mid=3)); a = run(env, msg(PIN, mid=4)); assert "registered" in texts(a)


def test_withdraw_blocked_by_cooldown_then_works(env):
    full_setup(env)
    def attempt(amount="1"):
        run(env, cb("withdraw")); run(env, cb("wd:0")); run(env, msg(amount, mid=10)); return texts(run(env, msg(PIN, mid=11)))
    assert "cooldown" in attempt()
    T[0] += 2 * 86400; env.state.clear()
    assert "Sent" in attempt() and len(env.rpc.sent) == 1


def test_withdraw_amount_parsing(env):
    full_setup(env); T[0] += 2 * 86400
    for bad in ["abc", "-1", "0", "nan", "inf", "1e400", "0.0000000001"]:
        run(env, cb("withdraw")); run(env, cb("wd:0")); acts = run(env, msg(bad, mid=20))
        assert "amount in SOL" in texts(acts), bad
    assert env.rpc.sent == []


def test_export_flow_warns_and_auto_deletes(env):
    full_setup(env); run(env, cb("export"))
    a = run(env, msg("000111", mid=30)); assert "❌" in texts(a)                             # wrong PIN
    run(env, cb("export")); a = run(env, msg(PIN, mid=31))
    sends = [x for x in a if x["op"] == "send"]
    assert sends[0]["delete_after"] == 60 and "Never share" in sends[0]["text"] and {"op": "delete", "chat_id": UID, "message_id": 31} in a


def test_only_private_chats_and_matching_user(env):
    assert env.handle(msg("/start", chat_type="supergroup")) == []
    u = msg("/start"); u["message"]["chat"]["id"] = 1; assert env.handle(u) == []          # chat id != user id
    assert env.handle({}) == [] and env.handle({"message": {}}) == [] and env.handle({"callback_query": {}}) == []


def test_state_expires_and_cancel(env):
    run(env, msg("/start")); run(env, cb("setpin")); T[0] += 400
    assert run(env, msg(PIN, mid=9)) == []                                                  # expired: ignored, not treated as a PIN
    run(env, cb("setpin")); run(env, msg("/cancel")); assert run(env, msg(PIN, mid=9)) == []


def test_rate_limit(env):
    run(env, msg("/start"))
    outs = [env.handle(cb("home")) for _ in range(40)]
    assert any(o == [] for o in outs[-5:])


def test_callback_fuzz_is_harmless(env):
    run(env, msg("/start"))
    for d in ["", None, "wd:abc", "wd:99", "soon:../../x", "x" * 500, "withdraw;DROP", "deposit\n"]:
        acts = env.handle(cb(d))
        assert all(a["op"] in ("answer", "send") for a in acts)
    assert env.rpc.sent == []


def test_soon_buttons(env):
    run(env, msg("/start")); assert run(env, cb("soon:sniper"))[0]["text"] == "Coming soon"


def test_deposit_cap_on_mainnet(env):
    env.cfg["network"] = "mainnet"; run(env, msg("/start")); env.db.set_balance(UID, 6 * LAMPORTS)
    assert "full" in texts(run(env, cb("deposit")))
    env.db.set_balance(UID, 1 * LAMPORTS); assert "Send SOL" in texts(run(env, cb("deposit")))
    env.cfg["max_total_deposits_sol"] = None; assert "full" in texts(run(env, cb("deposit")))   # no cap configured -> closed


def test_admin_only_commands(env):
    run(env, msg("/start"))
    assert env.handle(msg("/pause", uid=7)) == [] and not env.sg.paused()                    # non-admin ignored
    assert "Paused" in texts(env.handle(msg("/pause", uid=999))) and env.sg.paused()
    assert "server only" in texts(env.handle(msg("/resume", uid=999))) and env.sg.paused()   # app cannot resume
    assert "Frozen" in texts(env.handle(msg("/freeze 42", uid=999)))
    assert "server only" in texts(env.handle(msg("/unfreeze 42", uid=999)))
    assert "unavailable" not in texts(run(env, cb("wallet"))) and "frozen" in texts(run(env, cb("wallet"))).lower()


def test_paused_blocks_flows(env):
    run(env, msg("/start")); env.sg.handle({"op": "admin_pause"})
    assert "Not available" in texts(run(env, cb("setpin")))


def test_app_db_has_no_secrets(env):
    run(env, msg("/start")); full_setup(env)
    dump = json.dumps([dict(r) for r in env.db.c.execute("SELECT * FROM users")]) + json.dumps([dict(r) for r in env.db.c.execute("SELECT * FROM audit")])
    assert PIN not in dump and "blob" not in dump and DEST not in dump
