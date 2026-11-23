"""PIN hashing (scrypt) and lockout. A PIN guards withdrawals and key export; it does not replace the other withdrawal rules."""
import hashlib, hmac, os

N, R, P = 2 ** 15, 8, 1
MAX_FAILS = 5
LOCK_SECONDS = [900, 3600, 21600, 86400]   # escalates per consecutive lockout


class PinError(Exception):
    pass


def validate_format(pin: str):
    if not (pin.isdigit() and 6 <= len(pin) <= 12):
        raise PinError("PIN must be 6 to 12 digits")
    if len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
        raise PinError("PIN too easy to guess")


def hash_pin(pin: str) -> str:
    validate_format(pin)
    salt = os.urandom(16)
    h = hashlib.scrypt(pin.encode(), salt=salt, n=N, r=R, p=P, maxmem=2 ** 26)
    return f"scrypt${N}${R}${P}${salt.hex()}${h.hex()}"


def _check(pin: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), maxmem=2 ** 26)
        return hmac.compare_digest(got.hex(), h)
    except Exception:
        return False


def verify(pin: str, stored: str, state: dict, now: float):
    """state: {'fails':int,'locked_until':float,'lockouts':int} (persist it). Returns (ok, new_state). Raises PinError if locked.
    Locked users are refused WITHOUT checking the PIN, so a lockout cannot be bypassed by guessing during it."""
    s = {"fails": 0, "locked_until": 0.0, "lockouts": 0, **state}
    if now < s["locked_until"]:
        raise PinError(f"locked for {int(s['locked_until'] - now)}s")
    if stored and _check(pin, stored):
        return True, {"fails": 0, "locked_until": 0.0, "lockouts": s["lockouts"]}
    s["fails"] += 1
    if s["fails"] >= MAX_FAILS:
        s["locked_until"] = now + LOCK_SECONDS[min(s["lockouts"], len(LOCK_SECONDS) - 1)]
        s["lockouts"] += 1; s["fails"] = 0
    return False, s
