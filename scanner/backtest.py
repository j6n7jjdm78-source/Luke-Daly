"""Backtest the strategy and its TP1-TP4 ladder on history.  python -m scanner.backtest [--days 90] [--min-touches 2 3 4]

Rules: entry at the signal bar's close, one open trade per symbol, stop checked before targets inside a candle
(conservative), stop moves to entry after TP1, equal-size partial exits at each TP, trades time out after 96 bars.
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


def simulate(sym, df15, df1h, min_touches=3, max_bars=96, warmup=150):
    """Walk each signal forward: SL before TP1, BE stop after TP1, equal-size partial exits at each TP."""
    trades, busy_until = [], -1
    for i in range(warmup, len(df15) - 1):
        if i <= busy_until:
            continue
        sig = evaluate(sym.name, df15, df1h, min_touches, i=i, sym=sym)
        if not sig:
            continue
        buy, n, tps = sig.side == "BUY", len(sig.tps), sig.tps
        sgn = 1 if buy else -1
        end = min(i + max_bars, len(df15) - 1)
        hit, be, res, exit_i = 0, False, None, end
        for j in range(i + 1, end + 1):
            hi, lo = df15["high"].iloc[j], df15["low"].iloc[j]
            stop = sig.price if be else sig.sl
            if (lo <= stop) if buy else (hi >= stop):
                res, exit_i = ("BE" if be else "SL"), j
                break
            fav = hi if buy else lo
            while hit < n and ((fav >= tps[hit]) if buy else (fav <= tps[hit])):
                hit += 1
                be = True
            exit_i = j
            if hit == n:
                res = "ALL"
                break
        last = df15["close"].iloc[end]
        if res is None:
            res = "timeout"
        pnl = 0.0
        for k in range(n):
            if k < hit:
                pnl += (tps[k] - sig.price) * sgn / sym.pip
            elif res == "SL":
                pnl += (sig.sl - sig.price) * sgn / sym.pip
            elif res == "timeout":
                pnl += (last - sig.price) * sgn / sym.pip
        busy_until = exit_i
        trades.append(dict(symbol=sym.name, time=sig.time, side=sig.side, hit=hit, n=n, res=res, pips=pnl / n))
    return trades


def summarize(trades):
    if not trades:
        return "no trades"
    t = pd.DataFrame(trades)
    rates = " ".join(f"TP{k}:{(t.hit >= k)[t.n >= k].mean():.0%}" for k in range(1, 5) if (t.n >= k).any())
    return (f"trades {len(t)} | TP1 hit {(t.hit >= 1).mean():.0%} | {rates} | SL before TP1 {(t.res == 'SL').mean():.0%} "
            f"| BE stops {(t.res == 'BE').mean():.0%} | avg {t.pips.mean():+.0f} pips/trade")


def halves(trades):
    if len(trades) < 4:
        return ""
    t = sorted(trades, key=lambda x: x["time"])
    h = len(t) // 2
    f = lambda x: f"TP1 {sum(1 for q in x if q['hit'] >= 1) / len(x):.0%} avg {sum(q['pips'] for q in x) / len(x):+.0f}p"
    return f"  [1st half {f(t[:h])} | 2nd half {f(t[h:])}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-touches", type=int, nargs="*", default=[2, 3, 4])
    a = ap.parse_args()
    for mt in a.min_touches:
        allt = []
        print(f"=== min touches {mt} ===", flush=True)
        for sym in SYMBOLS:
            try:
                d15, d1h = load(sym, a.days)
            except Exception as e:
                print(f"{sym.name}: data failed ({e})"); continue
            tr = simulate(sym, d15, d1h, mt)
            allt += tr
            print(f"{sym.name:5} {summarize(tr)}{halves(tr)}", flush=True)
        print(f"ALL   {summarize(allt)}{halves(allt)}", flush=True)


if __name__ == "__main__":
    main()
