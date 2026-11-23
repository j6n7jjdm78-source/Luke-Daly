"""Per-user wallet key storage with envelope encryption.
Each wallet secret is encrypted with its own random data key (AES-256-GCM); that data key is wrapped by a MASTER key which
lives only on the server (env/KMS), never in the DB or git. The pubkey is bound in as associated data, so a blob moved to
another wallet row fails to decrypt. Master key rotation = rewrap(), no user-visible change."""
import base64, json, os
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big"); out = ""
    while n:
        n, r = divmod(n, 58); out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


class KeystoreError(Exception):
    pass


def _pub_raw(priv: Ed25519PrivateKey) -> bytes:
    return priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _seal(key: bytes, plain: bytes, aad: bytes) -> str:
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plain, aad)).decode()


def _open(key: bytes, blob: str, aad: bytes) -> bytes:
    raw = base64.b64decode(blob)
    try:
        return AESGCM(key).decrypt(raw[:12], raw[12:], aad)
    except Exception:
        raise KeystoreError("decryption failed (wrong master key, or blob tampered/moved)")


class Keystore:
    def __init__(self, master_key: bytes):
        if len(master_key) != 32:
            raise KeystoreError("master key must be 32 bytes")
        self._mk = master_key

    @staticmethod
    def generate_master_key() -> str:
        """Run once ON THE SERVER; store the result in the server secrets and back it up OFFLINE. Losing it loses every wallet."""
        return base64.b64encode(os.urandom(32)).decode()

    @classmethod
    def from_env(cls, var="TRADEBOT_MASTER_KEY"):
        v = os.environ.get(var)
        if not v:
            raise KeystoreError(f"{var} not set")
        return cls(base64.b64decode(v))

    def new_wallet(self):
        """Returns (pubkey_base58, encrypted_blob). The plaintext secret never leaves this function."""
        priv = Ed25519PrivateKey.generate()
        seed = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        pub = _pub_raw(priv); pk = b58encode(pub); aad = pk.encode()
        dk = os.urandom(32)
        blob = json.dumps({"v": 1, "dk": _seal(self._mk, dk, aad), "ct": _seal(dk, seed + pub, aad)})
        return pk, blob

    def secret(self, pubkey: str, blob: str) -> bytes:
        """64-byte Solana secret key (seed+pub). Only the signer should call this; verifies it matches the pubkey."""
        b = json.loads(blob); aad = pubkey.encode()
        sk = _open(_open(self._mk, b["dk"], aad), b["ct"], aad)
        if b58encode(sk[32:]) != pubkey or b58encode(_pub_raw(Ed25519PrivateKey.from_private_bytes(sk[:32]))) != pubkey:
            raise KeystoreError("key does not match pubkey")
        return sk

    def sign(self, pubkey: str, blob: str, message: bytes) -> bytes:
        return Ed25519PrivateKey.from_private_bytes(self.secret(pubkey, blob)[:32]).sign(message)

    def export_json(self, pubkey: str, blob: str) -> str:
        """Solana-CLI style JSON array. Callers MUST gate this behind PIN + confirmation and auto-delete the message."""
        return json.dumps(list(self.secret(pubkey, blob)))

    def rewrap(self, pubkey: str, blob: str, new_master: bytes) -> str:
        b = json.loads(blob); aad = pubkey.encode()
        dk = _open(self._mk, b["dk"], aad)
        b["dk"] = _seal(new_master, dk, aad)
        return json.dumps(b)
