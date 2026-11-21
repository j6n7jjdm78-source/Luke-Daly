"""Trend-pullback/momentum scorer. Score 0-5 per direction; signal when >= min_score.

Long score points:  +1 close above EMA200 (trend)   +1 EMA20 > EMA50 (short trend)
                    +1 higher-TF trend agrees       +1 MACD histogram rising & > 0 / cross up
                    +1 RSI between 45-65 (momentum, not overbought)
Short is the mirror image.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd


def ema(s, n): return s.ewm(span=n, adjust=False).mean()


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def indicators(df):
    d = df.copy()
    d["ema20"], d["ema50"], d["ema200"] = ema(d.close, 20), ema(d.close, 50), ema(d.close, 200)
    d["rsi"] = rsi(d.close)
    macd = ema(d.close, 12) - ema(d.close, 26)
    d["macd_h"] = macd - ema(macd, 9)
    d["atr"] = atr(d)
    return d


def htf_bias(df_htf):
    d = indicators(df_htf).iloc[-2]  # last closed HTF bar
    if d.close > d.ema50 > d.ema200: return 1
    if d.close < d.ema50 < d.ema200: return -1
    return 0


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


def score_bar(d, i, bias):
    """Return (long_score, short_score, long_reasons, short_reasons) for bar index i (a closed bar)."""
    r, p = d.iloc[i], d.iloc[i - 1]
    L, S, lr, sr = 0, 0, [], []

    def add(cond_long, cond_short, text):
        nonlocal L, S
        if cond_long: L += 1; lr.append(text)
        if cond_short: S += 1; sr.append(text)

    add(r.close > r.ema200, r.close < r.ema200, "price vs EMA200")
    add(r.ema20 > r.ema50, r.ema20 < r.ema50, "EMA20/50 alignment")
    add(bias > 0, bias < 0, "higher-TF trend")
    add(r.macd_h > 0 and r.macd_h > p.macd_h, r.macd_h < 0 and r.macd_h < p.macd_h, "MACD momentum")
    add(45 <= r.rsi <= 65, 35 <= r.rsi <= 55, f"RSI {r.rsi:.0f}")
    return L, S, lr, sr


def evaluate(name, df, df_htf, min_score=3, sl_atr=1.5, tp_atr=3.0, i=-2):
    """Evaluate the last *closed* bar. Returns Signal or None."""
    d = indicators(df)
    if len(d) < 210:
        return None
    i = len(d) + i if i < 0 else i
    L, S, lr, sr = score_bar(d, i, htf_bias(df_htf))
    r = d.iloc[i]
    # require a fresh MACD/EMA20 trigger so we don't alert every bar of a trend
    fresh_long = d.macd_h.iloc[i] > 0 >= d.macd_h.iloc[i - 1] or d.close.iloc[i] > d.ema20.iloc[i] and d.close.iloc[i - 1] <= d.ema20.iloc[i - 1]
    fresh_short = d.macd_h.iloc[i] < 0 <= d.macd_h.iloc[i - 1] or d.close.iloc[i] < d.ema20.iloc[i] and d.close.iloc[i - 1] >= d.ema20.iloc[i - 1]
    if L >= min_score and L > S and fresh_long:
        return Signal(name, "BUY", r.close, r.close - sl_atr * r.atr, r.close + tp_atr * r.atr, L, d.index[i], lr)
    if S >= min_score and S > L and fresh_short:
        return Signal(name, "SELL", r.close, r.close + sl_atr * r.atr, r.close - tp_atr * r.atr, S, d.index[i], sr)
    return None
