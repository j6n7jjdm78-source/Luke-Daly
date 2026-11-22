"""Entry zone, stop and take-profit ladder for a signal (reference-channel style).

BUY : zone shown high - low, SL = zone low - sl, TPn = zone high + tp1 + (n-1)*step
SELL: zone shown low - high, SL = zone high + sl, TPn = zone low - tp1 - (n-1)*step
Gold has 3 priced TPs (TP4 = "Hold"); BTC/ETH have 4.
"""


def build(side, zone_lo, zone_hi, price, sym):
    f = (lambda v: v * price) if sym.pct else (lambda v: v)
    sl_d, tp1_d, step, cap = f(sym.sl), f(sym.tp1), f(sym.step), f(sym.zone_cap)
    lo, hi = zone_lo, zone_hi
    if hi - lo > cap:                      # keep the edge nearest to the trade direction
        if side == "BUY":
            lo = hi - cap
        else:
            hi = lo + cap
    d = sym.decimals
    lo, hi = round(lo, d), round(hi, d)
    n = 3 if sym.style == "gold" else 4
    if side == "BUY":
        sl, tps = lo - sl_d, [hi + tp1_d + k * step for k in range(n)]
    else:
        sl, tps = hi + sl_d, [lo - tp1_d - k * step for k in range(n)]
    return dict(lo=lo, hi=hi, sl=round(sl, d), tps=[round(x, d) for x in tps], ref=(lo + hi) / 2)
