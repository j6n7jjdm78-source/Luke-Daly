"""Backtest the strategy and its TP ladder on history.  python -m scanner.backtest [--days 90] [--sweep]

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


def scan_signals(sym, df15, df1h, min_touches=None, warmup=150):
    """Evaluate every bar once. Returns {bar_index: Signal}. The slow part, reused for every breakeven rule."""
    out = {}
    for i in range(warmup, len(df15) - 1):
        sig = evaluate(sym.name, df15, df1h, min_touches, i=i, sym=sym)
        if sig:
            out[i] = sig
    return out


def walk(sym, df15, sigs, be_after=1, max_bars=96):
    """Follow each signal: stop checked before targets in a candle, stop moves to entry once `be_after` TPs are hit
    (None = never), equal-size partial exits at each TP, one open trade per symbol, 96-bar timeout."""
    trades, busy_until = [], -1
    for i in sorted(sigs):
        if i <= busy_until:
            continue
        sig = sigs[i]
        buy, tps = sig.side == "BUY", sig.tps
        n, sgn = len(tps), (1 if sig.side == "BUY" else -1)
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
                if be_after and hit >= be_after:
                    be = True
            exit_i = j
            if hit == n:
                res = "ALL"
                break
        last = df15["close"].iloc[end]
        res = res or "timeout"
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


def simulate(sym, df15, df1h, min_touches=None, max_bars=96, warmup=150, be_after=None):
    return walk(sym, df15, scan_signals(sym, df15, df1h, min_touches, warmup),
                sym.be_after if be_after is None else be_after, max_bars)


def rate(t, k):
    sub = [q for q in t if q["n"] >= k]
    return sum(1 for q in sub if q["hit"] >= k) / len(sub) if sub else 0.0


def summarize(trades):
    if not trades:
        return "no trades"
    rates = " ".join(f"TP{k}:{rate(trades, k):.0%}" for k in range(1, 5) if any(q["n"] >= k for q in trades))
    n = len(trades)
    sl = sum(1 for q in trades if q["res"] == "SL") / n
    be = sum(1 for q in trades if q["res"] == "BE") / n
    avg = sum(q["pips"] for q in trades) / n
    return f"trades {n} | {rates} | stopped at SL {sl:.0%} | at BE {be:.0%} | avg {avg:+.0f} pips/trade"


def halves(trades):
    if len(trades) < 4:
        return ""
    t = sorted(trades, key=lambda x: x["time"])
    h = len(t) // 2
    f = lambda x: f"TP2 {rate(x, 2):.0%} avg {sum(q['pips'] for q in x) / len(x):+.0f}p"
    return f"  [1st half {f(t[:h])} | 2nd half {f(t[h:])}]"


BE_RULES = {"BE after TP1": 1, "BE after TP2": 2, "no BE": None}


def gold_sweep(sym, d15, d1h):
    import itertools
    from dataclasses import replace
    rows = []
    for mt, h4, wick, sess in itertools.product([3, 4, 5], [False, True], [0.25, 0.45], [None, (7, 20)]):
        s2 = replace(sym, touches=mt, need_4h=h4, wick=wick, session=sess)
        sigs = scan_signals(s2, d15, d1h)
        for name, be in BE_RULES.items():
            tr = walk(s2, d15, sigs, be)
            if not tr:
                continue
            t = sorted(tr, key=lambda x: x["time"]); h = len(t) // 2
            avg = lambda x: sum(q["pips"] for q in x) / len(x) if x else 0
            rows.append(dict(cfg=f"touches {mt} 4h {'Y' if h4 else 'N'} wick {wick} session {'LDN/NY' if sess else 'any'} | {name}",
                             n=len(tr), tp1=rate(tr, 1), tp2=rate(tr, 2), tp3=rate(tr, 3), avg=avg(tr),
                             h1=avg(t[:h]), h2=avg(t[h:])))
        print(f"  done: touches {mt} 4h {h4} wick {wick} session {sess}", flush=True)
    print("=== GOLD SWEEP (all rows with >= 8 trades, best TP2 first) ===")
    for r in sorted((r for r in rows if r["n"] >= 8), key=lambda r: (-r["tp2"], -r["tp3"]))[:25]:
        print(f"{r['cfg']} | n {r['n']} TP1 {r['tp1']:.0%} TP2 {r['tp2']:.0%} TP3 {r['tp3']:.0%} | avg {r['avg']:+.0f}p "
              f"(1st {r['h1']:+.0f} 2nd {r['h2']:+.0f})", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--sweep", action="store_true", help="also sweep the gold filters")
    a = ap.parse_args()
    for sym in SYMBOLS:
        try:
            d15, d1h = load(sym, a.days)
        except Exception as e:
            print(f"{sym.name}: data failed ({e})"); continue
        print(f"=== {sym.name} {d15.index[0]:%Y-%m-%d} to {d15.index[-1]:%Y-%m-%d}: breakeven rules (default filters) ===", flush=True)
        sigs = scan_signals(sym, d15, d1h)
        for name, be in BE_RULES.items():
            tr = walk(sym, d15, sigs, be)
            print(f"{name:13} {summarize(tr)}{halves(tr)}", flush=True)
        if a.sweep and sym.name == "GOLD":
            gold_sweep(sym, d15, d1h)


if __name__ == "__main__":
    main()
