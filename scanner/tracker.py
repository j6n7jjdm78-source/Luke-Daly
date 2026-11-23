"""Follows open signals and posts TP / SL updates as replies to the original message.

Rules: candles are processed in order; the stop is checked before targets inside a candle (conservative);
after TP1 the stop moves to the entry price (breakeven). Pips are measured from the called (entry) price.
"""
import pandas as pd
from . import notify

MAX_AGE = pd.Timedelta(days=5)


def new_trade(sig, message_id, number=None):
    return dict(name=sig.symbol, side=sig.side, bar_time=sig.time.isoformat(), entry=sig.price, ref=sig.ref,
                sl=sig.sl, tps=list(sig.tps), pip=sig.pip, run=None, hit=0, be=False, running_sent=False,
                closed=False, message_id=message_id, number=number, n_tp=sig.n_tp, be_after=sig.be_after,
                done_until=(sig.time + pd.Timedelta(minutes=15) - pd.Timedelta(seconds=1)).isoformat(), style=sig.style)


def _pips(t, price):
    """Pips gained from the called price to `price` (negative for a loss)."""
    sign = 1 if t["side"] == "BUY" else -1
    return int(round((price - t["entry"]) * sign / t["pip"]))


def resolve(t, df, run_thr, tf_min=15):
    """Advance trade `t` with closed candles `df`; returns a list of update texts. Mutates t."""
    out, buy = [], t["side"] == "BUY"
    df = df[df.index > pd.Timestamp(t["done_until"])]
    for ts, c in df.iterrows():
        stop = t["entry"] if t["be"] else t["sl"]
        if (c["low"] <= stop) if buy else (c["high"] >= stop):
            if t["be"]:
                out.append(f"STOPPED AT BE ⚖️\nTrade closed at breakeven after TP{t['hit']}.")
            else:
                out.append(f"SL HIT ❌ -{abs(_pips(t, t['sl']))}PIPS")
            t["closed"] = True
            t["done_until"] = ts.isoformat()
            break
        fav = c["high"] if buy else c["low"]
        while t["hit"] < len(t["tps"]) and ((fav >= t["tps"][t["hit"]]) if buy else (fav <= t["tps"][t["hit"]])):
            k = t["hit"]
            t["hit"] += 1
            msg = f"HIT TP{k + 1} ✅ +{_pips(t, t['tps'][k])}PIPS"
            if t.get("be_after") and t["hit"] >= t["be_after"] and not t["be"]:
                t["be"] = True
                msg += "\nStop moved to entry (BE) ⚖️"
            out.append(f"{msg}\n\n{notify.FOOTER}")
        if t["hit"] >= len(t["tps"]):
            out.append("HIT ALL TP ✅")
            t["closed"] = True
        elif t["hit"] == 0 and not t["running_sent"] and abs(fav - t["entry"]) >= run_thr and \
                ((fav > t["entry"]) if buy else (fav < t["entry"])):
            out.append(f"Trade active and running +{_pips(t, fav)}PIPS ✅\n\n{notify.FOOTER}")
            t["running_sent"] = True
        t["done_until"] = ts.isoformat()
        if t["closed"]:
            break
    return out


def run(state, src, settings):
    """Check every open trade; send updates; drop finished ones."""
    from .config import get_symbol, is_open
    now = pd.Timestamp.now(tz="UTC")
    for t in state.get("open", []):
        if now - pd.Timestamp(t["bar_time"]) > MAX_AGE:
            t["closed"] = True
            continue
        try:
            sym = get_symbol(t["name"])
            if not is_open(sym, now):
                continue                      # market shut (e.g. gold at the weekend): resume on reopen
            df = src.candles(sym, settings.track_tf).iloc[:-1]   # fine candles, drop the forming one
        except Exception as e:
            print(f"[warn] tracker {t['name']}: {e}")
            continue
        run_thr = sym.run * (t["entry"] if sym.pct else 1)
        for text in resolve(t, df, run_thr):
            notify.reply(text, t["message_id"], settings)
    state["open"] = [t for t in state.get("open", []) if not t["closed"]]
