"""Pure exit engine shared by backtest, paper and live. No network, no clock.

Prices are multiples of the entry price (entry = 1.0). A candle is (ts, open, high, low, close).
Conservative intra-candle ordering: if the stop and a target both fall inside one candle, the stop fills first.
"""
from dataclasses import dataclass, field


@dataclass
class ExitRules:
    tp: list = field(default_factory=lambda: [(2.0, 0.5)])  # (multiple, fraction of ORIGINAL size)
    stop: float | None = 0.6          # hard stop at 0.6x entry (-40%); None = off
    trail_activate: float | None = 2.0  # trailing starts once high >= this multiple
    trail_pct: float = 0.35           # exit when price falls this fraction from the peak
    time_stop_s: int | None = 14400   # exit remainder at the close of the first candle at/after this age
    fee_pct: float = 0.01             # per-side cost: fees + slippage
    stop_slip_pct: float = 0.05       # extra loss on stop fills (thin books)
    rug_floor: float = 0.10           # a stop triggered in a candle that dips below this multiple fills at that low


@dataclass
class Result:
    multiple: float                   # total proceeds / cost, after costs
    exits: list                       # [(ts, price_mult, fraction, reason)]
    held: float                       # fraction still open at the end of data (marked at last close)
    rugged: bool = False


def simulate(candles, rules: ExitRules, entry_ts=None) -> Result:
    """candles: iterable of (ts, o, h, l, c) as multiples of entry, starting at the entry candle."""
    candles = list(candles)
    if not candles:
        raise ValueError("no candles")
    t0 = entry_ts if entry_ts is not None else candles[0][0]
    left = 1.0
    proceeds = 0.0
    peak = 1.0
    exits = []
    pending = sorted(rules.tp)
    rugged = False

    def sell(ts, px, frac, why):
        nonlocal left, proceeds
        frac = min(frac, left)
        proceeds += frac * px * (1 - rules.fee_pct)
        left -= frac
        exits.append((ts, round(px, 4), round(frac, 4), why))

    for ts, o, h, l, c in candles:
        if left <= 1e-9:
            break
        # 1) stop (checked first, conservative)
        if rules.stop is not None and l <= rules.stop:
            px = min(rules.stop, o)
            if l < rules.rug_floor:
                px, rugged = l, True
            else:
                px *= (1 - rules.stop_slip_pct)
            sell(ts, px, left, "stop")
            break
        # 2) trailing stop from the running peak (peak updated from PRIOR candles)
        if rules.trail_activate is not None and peak >= rules.trail_activate:
            tl = peak * (1 - rules.trail_pct)
            if l <= tl:
                px = min(tl, o)
                if l < rules.rug_floor:
                    px, rugged = l, True
                sell(ts, px, left, "trail")
                break
        # 3) take-profit ladder
        while pending and h >= pending[0][0]:
            m, fr = pending.pop(0)
            sell(ts, max(m, o) if o >= m else m, fr, f"tp{m:g}x")
        peak = max(peak, h)
        # 4) time stop
        if rules.time_stop_s is not None and ts - t0 >= rules.time_stop_s and left > 1e-9:
            sell(ts, c, left, "time")
            break
    held = left
    if held > 1e-9:
        mark = candles[-1][4]
        proceeds += held * mark * (1 - rules.fee_pct)
    return Result(multiple=proceeds, exits=exits, held=held, rugged=rugged)
