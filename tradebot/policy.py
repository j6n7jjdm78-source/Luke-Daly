"""Withdrawal policy. Pure and fail-closed: every rule must pass. Hijacked Telegram account must not be able to empty a wallet."""
DAY = 86400


class Refused(Exception):
    pass


DEFAULTS = {"address_cooldown_s": DAY, "daily_limit_lamports": 5 * 10 ** 9, "reserve_lamports": 5_000_000}


def check_withdrawal(*, pin_ok, dest, amount, balance, whitelist, spent_24h, now, global_paused=False, user_frozen=False, cfg=None):
    """whitelist: {address: added_at_ts}. amount/balance/spent_24h in lamports."""
    c = {**DEFAULTS, **(cfg or {})}
    if global_paused:
        raise Refused("withdrawals are paused")
    if user_frozen:
        raise Refused("account frozen")
    if not pin_ok:
        raise Refused("PIN required")
    if not isinstance(amount, int) or amount <= 0:
        raise Refused("invalid amount")
    if dest not in whitelist:
        raise Refused("destination not in your registered addresses")
    if now - whitelist[dest] < c["address_cooldown_s"]:
        raise Refused("new address is still in its cooldown period")
    if amount > balance - c["reserve_lamports"]:
        raise Refused("amount exceeds balance after fee reserve")
    if spent_24h + amount > c["daily_limit_lamports"]:
        raise Refused("daily withdrawal limit")


def check_add_address(*, pin_ok, address, whitelist, global_paused=False, user_frozen=False, max_addresses=3):
    if global_paused or user_frozen:
        raise Refused("not available right now")
    if not pin_ok:
        raise Refused("PIN required")
    if not (32 <= len(address) <= 44) or not address.isalnum():
        raise Refused("not a valid Solana address")
    if address not in whitelist and len(whitelist) >= max_addresses:
        raise Refused("too many registered addresses")
