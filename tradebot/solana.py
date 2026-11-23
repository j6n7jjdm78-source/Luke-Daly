"""Minimal Solana helpers: base58 decode and a legacy SOL transfer transaction built from structured fields.
The signer builds transfers itself so it never has to trust a transaction blob handed to it by the app."""
import struct
from .keystore import _B58

SYSTEM_PROGRAM = bytes(32)


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        i = _B58.find(ch)
        if i < 0:
            raise ValueError("invalid base58")
        n = n * 58 + i
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def pubkey_bytes(addr: str) -> bytes:
    b = b58decode(addr)
    if len(b) != 32:
        raise ValueError("not a 32-byte public key")
    return b


def _cu16(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        if n: out.append(b | 0x80)
        else: out.append(b); return bytes(out)


def transfer_message(frm: str, to: str, lamports: int, blockhash: str) -> bytes:
    if not isinstance(lamports, int) or isinstance(lamports, bool) or not (0 < lamports < 2 ** 63):
        raise ValueError("bad lamports")
    bh = b58decode(blockhash)
    if len(bh) != 32:
        raise ValueError("bad blockhash")
    data = struct.pack("<IQ", 2, lamports)                       # SystemProgram::Transfer
    return (bytes([1, 0, 1]) + _cu16(3) + pubkey_bytes(frm) + pubkey_bytes(to) + SYSTEM_PROGRAM + bh
            + _cu16(1) + bytes([2]) + _cu16(2) + bytes([0, 1]) + _cu16(len(data)) + data)


def transfer_tx(message: bytes, signature: bytes) -> bytes:
    if len(signature) != 64:
        raise ValueError("bad signature")
    return _cu16(1) + signature + message
