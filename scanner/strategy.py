"""Trend + support/resistance strategy.

1. Trend: 15m AND 1h must agree (EMA20 vs EMA50, price vs EMA50, EMA50 slope).
2. Levels: confirmed swing highs/lows on 1h and 15m, clustered into zones (touch count = strength).
3. Signal on the last closed 15m bar:
   uptrend   -> price dips into a support zone and rejects it (closes back above, bullish bar)  => BUY
   downtrend -> price rallies into a resistance zone and rejects it (closes back below)         => SELL
   SL sits just beyond the zone, TP at the next opposing zone (or 2R if none), min RR enforced.
Only closed bars and confirmed pivots are used (no look-ahead).
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd


def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def trend(df):
    """+1 up, -1 down, 0 none (uses the last bar of df, which must be closed)."""
    if len(df) < 60:
        return 0
    c = df["close"]
    e20, e50 = ema(c, 20), ema(c, 50)
    if e20.iloc[-1] > e50.iloc[-1] and c.iloc[-1] > e50.iloc[-1] and e50.iloc[-1] > e50.iloc[-6]:
        return 1
    if e20.iloc[-1] < e50.iloc[-1] and c.iloc[-1] < e50.iloc[-1] and e50.iloc[-1] < e50.iloc[-6]:
        return -1
    return 0


def pivots(df, left=5, right=5):
    """Confirmed swing highs / lows as lists of prices."""
    h, l = df["high"].values, df["low"].values
    highs, lows = [], []
    for i in range(left, len(df) - right):
        if h[i] == h[i - left:i + right + 1].max(): highs.append(h[i])
        if l[i] == l[i - left:i + right + 1].min(): lows.append(l[i])
    return highs, lows


@dataclass
class Zone:
    lo: float
    hi: float
    touches: int

    @property
    def mid(self): return (self.lo + self.hi) / 2


def cluster(prices, tol):
    zones, cur = [], []
    for p in sorted(prices):
        if cur and p - cur[-1] > tol:
            zones.append(cur); cur = []
        cur.append(p)
    if cur: zones.append(cur)
    return [Zone(min(z), max(z), len(z)) for z in zones]


def find_zones(df15, df1h, tol_atr=0.6):
    """S/R zones from 1h and 15m pivots. 1h pivots count double (more significant)."""
    tol = tol_atr * atr(df1h).iloc[-1]
    h1, l1 = pivots(df1h.tail(300), 5, 5)
    h2, l2 = pivots(df15.tail(400), 5, 5)
    pts = h1 * 2 + l1 * 2 + h2 + l2
    zs = cluster(pts, tol)
    pad = 0.15 * tol
    return [Zone(z.lo - pad, z.hi + pad, z.touches) for z in zs]


@dataclass
class Signal:
    symbol: str
    side: str
    price: float
    sl: float
    tp: float
    score: int
    time: pd.Timestamp
    reasons: list
    tps: list = None
    zone_lo: float = None
    zone_hi: float = None
    ref: float = None       # zone midpoint: pips in updates are measured from here
    style: str = "btc"
    label: str = ""
    pip: float = 1.0
    decimals: int = 0
    n_tp: int = 4
    be_after: int = 1


def make_signal(name, side, zone_lo, zone_hi, price, time, touches, reasons, sym):
    """Build a signal with the symbol's level profile. None if price is already past TP1 or the stop."""
    from .levels import build
    lv = build(side, zone_lo, zone_hi, price, sym)
    if side == "BUY" and not (lv["sl"] < price < lv["tps"][0]): return None
    if side == "SELL" and not (lv["tps"][0] < price < lv["sl"]): return None
    return Signal(name, side, price, lv["sl"], lv["tps"][0], min(5, touches), time, reasons, tps=lv["tps"],
                  zone_lo=lv["lo"], zone_hi=lv["hi"], ref=lv["ref"], style=sym.style, label=sym.label or name,
                  pip=sym.pip, decimals=sym.decimals, n_tp=len(lv["tps"]), be_after=sym.be_after)


def evaluate(name, df15, df1h, min_touches=None, min_rr=None, i=-2, ltf_min=15, htf_min=60, sym=None):
    """Evaluate bar i of df15 (default: last closed bar; the forming bar is -1). min_rr is unused (levels are fixed)."""
    if sym is None:
        from .config import get_symbol
        sym = get_symbol(name) if name in ("GOLD", "BTC", "ETH") else get_symbol("BTC")
    min_touches = sym.touches if min_touches is None else min_touches
    n = len(df15) + i + 1 if i < 0 else i + 1
    d = df15.iloc[:n]
    if len(d) < 120 or len(df1h) < 80:
        return None
    if sym.session and not (sym.session[0] <= d.index[-1].hour < sym.session[1]):
        return None
    close_t = d.index[-1] + pd.Timedelta(minutes=ltf_min)
    h = df1h[df1h.index + pd.Timedelta(minutes=htf_min) <= close_t]
    if len(h) < 80:
        return None

    t15, t1h = trend(d), trend(h)
    if t15 == 0 or t15 != t1h:
        return None
    if sym.need_4h:
        h4 = h.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().iloc[:-1]
        if trend(h4) != t15:
            return None

    bar = d.iloc[-1]
    zones = find_zones(d, h)
    rng = max(bar.high - bar.low, 1e-12)
    why = [f"15m & 1h trend {'UP' if t15 > 0 else 'DOWN'}"]

    if t15 > 0:  # support bounce
        sup = [z for z in zones if z.mid < bar.close and z.touches >= min_touches]
        if not sup: return None
        z = max(sup, key=lambda z: z.mid)
        lower_wick = (min(bar.open, bar.close) - bar.low) / rng
        if bar.low <= z.hi and bar.close > z.hi and bar.close > bar.open and lower_wick >= sym.wick:
            why.append(f"bounce off support {z.lo:,.2f}-{z.hi:,.2f} ({z.touches} touches)")
            return make_signal(name, "BUY", z.lo, z.hi, bar.close, d.index[-1], z.touches, why, sym)
    else:  # resistance rejection
        res = [z for z in zones if z.mid > bar.close and z.touches >= min_touches]
        if not res: return None
        z = min(res, key=lambda z: z.mid)
        upper_wick = (bar.high - max(bar.open, bar.close)) / rng
        if bar.high >= z.lo and bar.close < z.lo and bar.close < bar.open and upper_wick >= sym.wick:
            why.append(f"rejection at resistance {z.lo:,.2f}-{z.hi:,.2f} ({z.touches} touches)")
            return make_signal(name, "SELL", z.lo, z.hi, bar.close, d.index[-1], z.touches, why, sym)
    return None
