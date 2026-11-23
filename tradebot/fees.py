"""Per-trade fee math in integer lamports (never floats for money). Rounds DOWN so we never charge more than the stated rate."""


def fee(amount: int, bps: int = 100) -> int:
    if amount < 0 or not (0 <= bps <= 500):
        raise ValueError("bad fee input")
    return amount * bps // 10_000


def split(fee_total: int, referrer_bps: int = 2500, has_referrer: bool = True):
    """(platform, referrer). Referrer share is of the fee; the two always sum to fee_total exactly."""
    ref = fee_total * referrer_bps // 10_000 if has_referrer else 0
    return fee_total - ref, ref


def net_trade(amount: int, bps: int = 100):
    """(fee, amount_traded). User is charged fee on top of nothing hidden: traded = amount - fee."""
    f = fee(amount, bps)
    return f, amount - f
