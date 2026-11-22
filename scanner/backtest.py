"""Backtest the strategy on history.  python -m scanner.backtest [--days 90]

Rules: entry at the signal bar's close, one open trade per symbol, SL/TP checked on later bars
(if SL and TP are both inside one bar the SL is assumed to hit first - conservative),
trades time out after --max-bars bars and close at market. Results are in R (1R = distance to stop).
No spread/commission is modelled: subtract your broker's costs yourself.
"""
import argparse
from datetime import datetime, timedelta, timezone
import pandas as pd
import requests
from .config import SYMBOLS
from .data import PublicSource, COLS
from .strategy import evaluate


def coinbase_history(product, granularity, days):
    end = datetime.now(timezone.utc)
    start_all = end - timedelta(days=days)
    rows, step = [], timedelta(seconds=granularity * 300)
    cur_end = end
    while cur_end > start_all:
        cur_start = max(start_all, cur_end - step)
        r = requests.get(f"https://api.exchange.coinbase.com/products/{product}/candles",
                         params={"granularity": granularity, "start": cur_start.isoformat(), "end": cur_end.isoformat()},
                         headers={"User-Agent": "backtest"}, timeout=20)
        r.raise_for_status()
        rows += r.json()
        cur_end = cur_start
    df = pd.DataFrame(rows, columns=["time", "low", "high", "open", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df.drop_duplicates("time").set_index("time").sort_index()[COLS].astype(float)


def load(sym, days):
    if sym.name == "GOLD":
        p = PublicSource()
        return p._yahoo(sym.yahoo, "15m", 10**6), p._yahoo(sym.yahoo, "1h", 10**6)
    product = {"BTC": "BTC-USD", "ETH": "ETH-USD"}[sym.name]
    return coinbase_history(product, 900, days), coinbase_history(product, 3600, days + 10)


def simulate(name, df15, df1h, min_touches=3, min_rr=1.5, max_bars=96, warmup=150):
    trades, busy_until = [], -1
    for i in range(warmup, len(df15) - 1):
        if i <= busy_until:
            continue
        sig = evaluate(name, df15, df1h, min_touches, min_rr, i=i)
        if not sig:
            continue
        risk = abs(sig.price - sig.sl)
        out, exit_i, r = "timeout", min(i + max_bars, len(df15) - 1), None
        for j in range(i + 1, min(i + max_bars, len(df15) - 1) + 1):
            hi, lo = df15["high"].iloc[j], df15["low"].iloc[j]
            if sig.side == "BUY":
                hit_sl, hit_tp = lo <= sig.sl, hi >= sig.tp
            else:
                hit_sl, hit_tp = hi >= sig.sl, lo <= sig.tp
            if hit_sl:
                out, r, exit_i = "SL", -1.0, j; break
            if hit_tp:
                out, r, exit_i = "TP", abs(sig.tp - sig.price) / risk, j; break
        if r is None:
            last = df15["close"].iloc[exit_i]
            r = ((last - sig.price) if sig.side == "BUY" else (sig.price - last)) / risk
        busy_until = exit_i
        trades.append(dict(symbol=name, time=sig.time, side=sig.side, outcome=out, r=r))
    return trades


def summarize(trades):
    if not trades:
        return "no trades"
    t = pd.DataFrame(trades)
    wins = t[t.r > 0].r.sum()
    loss = -t[t.r < 0].r.sum()
    eq = t.r.cumsum()
    dd = (eq.cummax() - eq).max()
    return (f"trades {len(t)} | win rate {(t.r > 0).mean():.0%} | avg R {t.r.mean():+.2f} | total R {t.r.sum():+.1f} | "
            f"profit factor {wins / loss if loss else float('inf'):.2f} | max drawdown {dd:.1f}R")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-touches", type=int, default=3)
    a = ap.parse_args()
    allt = []
    for sym in SYMBOLS:
        try:
            d15, d1h = load(sym, a.days)
        except Exception as e:
            print(f"{sym.name}: data failed ({e})"); continue
        tr = simulate(sym.name, d15, d1h, a.min_touches)
        allt += tr
        print(f"{sym.name:5} {d15.index[0]:%Y-%m-%d} to {d15.index[-1]:%Y-%m-%d} | {summarize(tr)}", flush=True)
    print(f"ALL   | {summarize(allt)}")


if __name__ == "__main__":
    main()
