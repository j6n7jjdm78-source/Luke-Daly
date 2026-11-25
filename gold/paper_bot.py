"""Paper bot: Scout -> Shield -> Pilot -> Journal. DEMO account only. Real money is never part of this.
Run on Windows:  py gold\\paper_bot.py            (MT5 open and logged in to the demo account)
Mechanics test:  python3 gold/paper_bot.py --replay --loose --hours 0 24   (NOT a strategy result)
Exit code 2 = halted for safety (run_bot.bat will not restart it)."""
import argparse, csv, json, os, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab
from broker import FakeBroker, MT5Broker

DATA = os.path.join(HERE, "..", "data")
JCOLS = ["trade_id", "mode", "market", "side", "entry_time", "entry_price", "size", "stop", "target",
         "exit_time", "exit_price", "pnl_account_ccy", "r_multiple", "reason_in", "reason_out"]
S = dict(path=None, incidents=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "incidents.md"))  # file paths set in main


def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc)


def log(msg, alert=False):
    line = f"{datetime.now(timezone.utc).isoformat()} MODE: PAPER {msg}"
    print(line, flush=True)
    for f in ([S["log"]] + ([S["alerts"]] if alert else [])):
        with open(f, "a") as h:
            h.write(line + "\n")


def load_state():
    base = dict(day=None, trades_today=0, loss_streak=0, day_start=0.0, peak=0.0, open={}, last_bar=None,
                halted=False, blocked={}, warned_news=False)
    if os.path.exists(S["state"]):
        base.update(json.load(open(S["state"])))
    return base


def save_state(st):
    json.dump(st, open(S["state"], "w"), indent=1)


def news_blocked(now):
    """Optional file gold/news_blackouts.txt: one 'startISO,endISO' (UTC) per line, e.g. CPI/FOMC windows."""
    p = os.path.join(HERE, "news_blackouts.txt")
    if not os.path.exists(p):
        return None
    for ln in open(p):
        if "," in ln and not ln.startswith("#"):
            a, b = [datetime.fromisoformat(x.strip()).replace(tzinfo=timezone.utc) for x in ln.split(",")[:2]]
            if a <= utc(now) <= b:
                return f"news blackout {a.isoformat()}..{b.isoformat()}"
    return None


def journal(row):
    new = not os.path.exists(S["journal"])
    with open(S["journal"], "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=JCOLS)
        if new:
            w.writeheader()
        w.writerow(row)


def close_done(b, st, key):
    info, ci = st["open"][key], b.closed_info(int(key))
    if ci is None:
        return
    st["open"].pop(key)
    pnl = ci["pnl"]
    st["loss_streak"] = st["loss_streak"] + 1 if pnl < 0 else 0
    journal(dict(trade_id=key, mode="PAPER", market=info["market"], side=info["side"], entry_time=info["time"],
                 entry_price=info["price"], size=info["lot"], stop=info["stop"], target=info["target"],
                 exit_time=utc(ci["time"]).isoformat(), exit_price=ci["price"], pnl_account_ccy=round(pnl, 2),
                 r_multiple=round(pnl / info["risk"], 2) if info["risk"] else "", reason_in=info["reason"],
                 reason_out=ci["why"]))
    log(f"CLOSED {key} {info['side']} pnl {pnl:.2f} ({ci['why']}) loss_streak={st['loss_streak']}")


def halt(b, st, why):
    st["halted"] = True
    for p in b.positions():
        b.close(p["ticket"], "halt")
    log(f"HALT: {why}", alert=True)
    with open(S["incidents"], "a") as f:
        f.write(f"- {datetime.now(timezone.utc).isoformat()} HALT: {why}\n")


def shield(b, cfg, st, bars5, side, entry, stop, bid, ask, bal):
    """Returns None if APPROVED, else the reason the order is BLOCKED."""
    now, hr = b.now(), utc(b.now()).hour
    if st["halted"]: return "halted"
    if now - (bars5[-1]["ts"] + 300) > cfg["max_feed_age_s"]: return "stale price feed"
    if not (cfg["hour_from"] <= hr < cfg["hour_to"]): return f"outside trading hours ({hr}h UTC)"
    if ask - bid > cfg["max_spread"]: return f"spread {ask - bid:.2f} too wide"
    if st["trades_today"] >= cfg["max_trades_day"]: return "max trades per day"
    if st["loss_streak"] >= cfg["loss_streak_stop"]: return "loss streak limit"
    if bal - st["day_start"] <= -cfg["daily_loss_pct"] * st["day_start"]: return "daily loss limit"
    if (side == "long" and stop >= entry) or (side == "short" and stop <= entry): return "stop on wrong side"
    dist = abs(entry - stop)
    if dist < lab.P["min_stop"]: return f"stop too tight ({dist:.2f})"
    if b.min_lot > cfg["lot"]: return "broker minimum lot above configured lot"
    risk, limit = b.risk(side, entry, stop, cfg["lot"]), cfg["risk_pct"] * bal
    if risk > limit: return f"risk {risk:.2f} > limit {limit:.2f}"
    return news_blocked(now)


def cycle(b, cfg, st):
    now, bal = b.now(), b.balance()
    today = utc(now).date().isoformat()
    if st["day"] != today:
        st.update(day=today, trades_today=0, loss_streak=0, day_start=bal)
    st["peak"] = max(st["peak"], bal)
    live = {str(p["ticket"]): p for p in b.positions()}
    for key in list(st["open"]):
        if key not in live:
            close_done(b, st, key)
    if bal <= st["peak"] * (1 - cfg["kill_switch_dd"]):
        return halt(b, st, f"kill switch: balance {bal:.2f} is {cfg['kill_switch_dd']:.0%} below peak {st['peak']:.2f}")
    for key, p in live.items():
        hr = utc(now).hour
        if not p["sl"]:
            log(f"MISSING STOP on {key}: closing", alert=True); b.close(p["ticket"], "no stop")
        elif not (cfg["hour_from"] <= hr < cfg["hour_to"]):
            log(f"time exit {key}"); b.close(p["ticket"], "time")
    if live or st["halted"]:
        return
    bars5 = b.rates("5m", 60)
    lab.set_data(b.rates("1h", 200), b.rates("15m", 200))
    sig = lab.signal(bars5, len(bars5) - 1, "5m")
    if not sig:
        return
    side, stop, L, nxt = sig
    bid, ask = b.tick()
    entry = ask if side == "long" else bid
    why = shield(b, cfg, st, bars5, side, entry, stop, bid, ask, bal)
    if why:
        k = why.split(" ")[0]
        st["blocked"][k] = st["blocked"].get(k, 0) + 1
        return log(f"SHIELD BLOCKED {side} at {entry:.2f} stop {stop:.2f}: {why}")
    dist = abs(entry - stop)
    tp = entry + lab.P["rr"] * dist if side == "long" else entry - lab.P["rr"] * dist
    if side == "long" and nxt and entry + 0.5 * dist < min(nxt) < tp: tp = min(nxt)
    if side == "short" and nxt and tp < max(nxt) < entry - 0.5 * dist: tp = max(nxt)
    res = b.open(side, cfg["lot"], stop, tp) or b.open(side, cfg["lot"], stop, tp)
    if not res:
        return log(f"ORDER FAILED {side}: {getattr(b, 'last_error', None)}", alert=True)
    st["trades_today"] += 1
    st["open"][str(res["ticket"])] = dict(market=cfg["symbol"], side=side, time=utc(now).isoformat(), price=res["price"],
                                          lot=cfg["lot"], stop=round(stop, 2), target=round(tp, 2),
                                          risk=b.risk(side, res["price"], stop, cfg["lot"]),
                                          reason=f"S/R rejection at level {L:.2f}")
    log(f"OPENED {res['ticket']} {side} {cfg['lot']} at {res['price']:.2f} stop {stop:.2f} target {tp:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", action="store_true", help="test mechanics on saved candles with a fake account")
    ap.add_argument("--loose", action="store_true", help="TEST ONLY: min_touches=2 so the replay produces signals")
    ap.add_argument("--hours", nargs=2, type=int, help="override trading hours (UTC)")
    a = ap.parse_args()
    cfg = json.load(open(os.path.join(HERE, "config.json")))
    if a.hours:
        cfg["hour_from"], cfg["hour_to"] = a.hours
    lab.P["h_from"], lab.P["h_to"] = cfg["hour_from"], cfg["hour_to"]
    pre = "replay_" if a.replay else ""
    S.update(log=os.path.join(HERE, pre + "bot.log"), alerts=os.path.join(HERE, pre + "alerts.log"),
             state=os.path.join(HERE, pre + "state.json"), journal=os.path.join(DATA, pre + "live_trades.csv"),
             heart=os.path.join(HERE, pre + "heartbeat.txt"))
    if a.replay:
        for f in (S["log"], S["alerts"], S["state"], S["journal"]):
            if os.path.exists(f): os.remove(f)
        if a.loose: lab.P["min_touches"] = 2
        b = FakeBroker(cfg)
    else:
        b = MT5Broker(cfg)
    log(f"START {b.describe()}")
    st, errs = load_state(), 0
    st["peak"] = max(st["peak"], b.balance())
    while True:
        try:
            last = b.rates("5m", 2)[-1]["ts"]
            if last != st["last_bar"]:
                st["last_bar"] = last
                cycle(b, cfg, st)
                save_state(st)
            errs = 0
        except Exception as e:
            errs += 1
            log(f"ERROR {e!r} (consecutive {errs})", alert=True)
            if errs >= 3:
                halt(b, st, f"3 consecutive errors, last: {e!r}"); save_state(st)
                return 2
        open(S["heart"], "w").write(datetime.now(timezone.utc).isoformat())
        if not b.wait():
            break
    log(f"END blocked={st['blocked']} open={len(st['open'])} balance={b.balance():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
