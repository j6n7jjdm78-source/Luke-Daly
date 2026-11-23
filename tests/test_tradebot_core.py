import base64, json, pytest
from tradebot.keystore import Keystore, KeystoreError, b58encode
from tradebot import pin, policy, fees
from tradebot.db import DB

MK = bytes(range(32)); NOW = 1_000_000.0


def test_keystore_roundtrip_and_sign():
    ks = Keystore(MK); pk, blob = ks.new_wallet()
    sk = ks.secret(pk, blob)
    assert len(sk) == 64 and b58encode(sk[32:]) == pk
    sig = ks.sign(pk, blob, b"hello")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    Ed25519PublicKey.from_public_bytes(sk[32:]).verify(sig, b"hello")
    assert json.loads(ks.export_json(pk, blob)) == list(sk)
    assert pk not in blob and sk[:32].hex() not in blob          # no plaintext in the stored blob


def test_keystore_rejects_wrong_master_tamper_and_moved_blob():
    ks = Keystore(MK); pk, blob = ks.new_wallet(); pk2, blob2 = ks.new_wallet()
    with pytest.raises(KeystoreError): Keystore(bytes(32)).secret(pk, blob)
    with pytest.raises(KeystoreError): ks.secret(pk, blob2)                 # blob moved to another wallet row
    b = json.loads(blob); raw = bytearray(base64.b64decode(b["ct"])); raw[-1] ^= 1; b["ct"] = base64.b64encode(raw).decode()
    with pytest.raises(KeystoreError): ks.secret(pk, json.dumps(b))        # tampered


def test_rewrap_rotates_master_key():
    ks = Keystore(MK); pk, blob = ks.new_wallet(); sk = ks.secret(pk, blob)
    new = bytes([7]) * 32; blob2 = ks.rewrap(pk, blob, new)
    assert Keystore(new).secret(pk, blob2) == sk
    with pytest.raises(KeystoreError): ks.secret(pk, blob2)


def test_master_key_from_env(monkeypatch):
    monkeypatch.setenv("TRADEBOT_MASTER_KEY", Keystore.generate_master_key())
    Keystore.from_env()
    monkeypatch.delenv("TRADEBOT_MASTER_KEY")
    with pytest.raises(KeystoreError): Keystore.from_env()


def test_pin_format_and_lockout():
    for bad in ("123", "111111", "123456", "abcdef"):
        with pytest.raises(pin.PinError): pin.hash_pin(bad)
    h = pin.hash_pin("483920"); st = {}
    ok, st = pin.verify("483920", h, st, NOW); assert ok
    for i in range(5): ok, st = pin.verify("000111", h, st, NOW)
    assert not ok and st["locked_until"] > NOW
    with pytest.raises(pin.PinError): pin.verify("483920", h, st, NOW + 10)  # right PIN still refused while locked
    ok, st = pin.verify("483920", h, st, NOW + 901); assert ok


WL = {"DestAddr1111111111111111111111111111111111": NOW - 2 * 86400}
BASE = dict(pin_ok=True, dest="DestAddr1111111111111111111111111111111111", amount=10**9, balance=2 * 10**9, whitelist=WL, spent_24h=0, now=NOW)


def test_withdrawal_policy():
    policy.check_withdrawal(**BASE)
    cases = {"pin_ok": False, "dest": "Other" + "1" * 39, "amount": 0, "global_paused": True, "user_frozen": True,
             "balance": 10**9, "spent_24h": 5 * 10**9, "whitelist": {BASE["dest"]: NOW - 100}}
    for k, v in cases.items():
        with pytest.raises(policy.Refused): policy.check_withdrawal(**{**BASE, k: v})
    with pytest.raises(policy.Refused): policy.check_withdrawal(**{**BASE, "amount": 1.5})   # non-int


def test_add_address_policy():
    a = "A" * 44
    policy.check_add_address(pin_ok=True, address=a, whitelist={})
    with pytest.raises(policy.Refused): policy.check_add_address(pin_ok=False, address=a, whitelist={})
    with pytest.raises(policy.Refused): policy.check_add_address(pin_ok=True, address="short", whitelist={})
    with pytest.raises(policy.Refused): policy.check_add_address(pin_ok=True, address=a, whitelist={"x" * 40: 1, "y" * 40: 1, "z" * 40: 1})


def test_fee_math_exact():
    assert fees.fee(1_000_000_000, 100) == 10_000_000 and fees.fee(99, 100) == 0
    f = fees.fee(123_456_789, 100); p, r = fees.split(f); assert p + r == f
    assert fees.split(f, has_referrer=False) == (f, 0)
    assert fees.net_trade(10**9)[0] + fees.net_trade(10**9)[1] == 10**9
    with pytest.raises(ValueError): fees.fee(10, 900)


def test_db_flow(tmp_path):
    db = DB(str(tmp_path / "t.db")); ks = Keystore(MK)
    u = db.create_user(111, NOW); assert db.create_user(111, NOW) == u            # idempotent
    pk, blob = ks.new_wallet(); db.add_wallet(u, pk, blob)
    w = db.wallet(u); assert ks.secret(w["pubkey"], w["blob"])
    db.add_address(u, "D" * 40, NOW); assert db.whitelist(u) == {"D" * 40: NOW}
    db.record_withdrawal(u, "D" * 40, 5, NOW); db.record_withdrawal(u, "D" * 40, 7, NOW - 200000)
    assert db.withdrawn_since(u, NOW - 86400) == 5
    db.freeze(u); assert db.user(u)["frozen"] == 1
    db.audit(u, "x'; DROP TABLE users;--", {"a": 1}, NOW)                         # injection-safe
    assert db.user(u) is not None
