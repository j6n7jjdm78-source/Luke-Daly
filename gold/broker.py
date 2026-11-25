"""Broker adapters. MT5Broker = MetaTrader 5 DEMO account (Windows). FakeBroker = replays saved candles
to test the bot logic. PAPER ONLY: MT5Broker refuses to start on a non-demo account."""
import os, sys, time

SECS = {"5m": 300, "15m": 900, "1h": 3600}
MAGIC = 20260101
HERE = os.path.dirname(os.path.abspath(__file__))


class MT5Broker:
    TFN = {"5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15", "1h": "TIMEFRAME_H1"}
    mode = "MT5 DEMO"

    def __init__(self, cfg):
        import MetaTrader5 as m
        self.m, self.cfg, self.sym, self.last_error = m, cfg, cfg["symbol"], None
        if not m.initialize():
            raise SystemExit(f"MT5 initialize failed: {m.last_error()}. Open MT5, log in to the demo account, retry.")
        a = m.account_info()
        if a is None:
            raise SystemExit("No account info from MT5.")
        if a.trade_mode != m.ACCOUNT_TRADE_MODE_DEMO:
            raise SystemExit("NOT A DEMO ACCOUNT. Refusing to run (paper only).")
        if not m.symbol_select(self.sym, True):
            raise SystemExit(f"Symbol {self.sym} not available: {m.last_error()}")
        self.info = m.symbol_info(self.sym)
        self.digits, self.min_lot = self.info.digits, self.info.volume_min
        self.off = self._offset()

    def _offset(self):
        if self.cfg.get("utc_offset_hours") is not None:
            return int(self.cfg["utc_offset_hours"] * 3600)
        raw = self.m.symbol_info_tick(self.sym).time - time.time()
        off = round(raw / 1800) * 1800
        if abs(raw - off) > 300:
            raise SystemExit("Cannot auto-detect the broker's UTC offset (market closed?). "
                             "Set utc_offset_hours in gold/config.json (e.g. 2 or 3) and retry.")
        return int(off)

    def describe(self):
        a = self.m.account_info()
        return f"{self.mode} account {a.login} server {a.server} balance {a.balance} {a.currency}"

    def now(self):
        return int(time.time())

    def rates(self, tf, n):
        """Closed candles only (the forming one is dropped). Times converted to UTC."""
        r = self.m.copy_rates_from_pos(self.sym, getattr(self.m, self.TFN[tf]), 0, n + 1)
        if r is None or len(r) < 2:
            raise RuntimeError(f"no rates for {tf}: {self.m.last_error()}")
        return [dict(ts=int(x["time"]) - self.off, o=float(x["open"]), h=float(x["high"]), l=float(x["low"]),
                     c=float(x["close"]), v=float(x["tick_volume"]), sp=int(x["spread"])) for x in list(r)[:-1]]

    def tick(self):
        t = self.m.symbol_info_tick(self.sym)
        return float(t.bid), float(t.ask)

    def balance(self):
        return float(self.m.account_info().balance)

    def positions(self):
        m = self.m
        return [dict(ticket=int(p.ticket), side="long" if p.type == m.POSITION_TYPE_BUY else "short",
                     price=float(p.price_open), sl=float(p.sl), tp=float(p.tp), time=int(p.time) - self.off)
                for p in (m.positions_get(symbol=self.sym) or []) if p.magic == MAGIC]

    def risk(self, side, entry, stop, lot):
        """Loss in ACCOUNT currency if the stop is hit."""
        m = self.m
        act = m.ORDER_TYPE_BUY if side == "long" else m.ORDER_TYPE_SELL
        p = m.order_calc_profit(act, self.sym, lot, entry, stop)
        if p is None:
            raise RuntimeError(f"order_calc_profit failed: {m.last_error()}")
        return abs(float(p))

    def open(self, side, lot, sl, tp):
        m = self.m
        bid, ask = self.tick()
        for fill in (m.ORDER_FILLING_IOC, m.ORDER_FILLING_FOK):
            req = dict(action=m.TRADE_ACTION_DEAL, symbol=self.sym, volume=lot,
                       type=m.ORDER_TYPE_BUY if side == "long" else m.ORDER_TYPE_SELL,
                       price=ask if side == "long" else bid, sl=round(sl, self.digits), tp=round(tp, self.digits),
                       deviation=20, magic=MAGIC, comment="paperlab", type_time=m.ORDER_TIME_GTC, type_filling=fill)
            r = m.order_send(req)
            if r is not None and r.retcode == m.TRADE_RETCODE_DONE:
                return dict(ticket=int(r.order), price=float(r.price))
            self.last_error = f"retcode={getattr(r, 'retcode', None)} {getattr(r, 'comment', '')} {m.last_error()}"
        return None

    def close(self, ticket, why=""):
        m = self.m
        ps = [p for p in (m.positions_get(ticket=ticket) or [])]
        if not ps:
            return True
        p = ps[0]
        bid, ask = self.tick()
        buy = p.type == m.POSITION_TYPE_BUY
        for fill in (m.ORDER_FILLING_IOC, m.ORDER_FILLING_FOK):
            r = m.order_send(dict(action=m.TRADE_ACTION_DEAL, symbol=self.sym, volume=p.volume, position=ticket,
                                  type=m.ORDER_TYPE_SELL if buy else m.ORDER_TYPE_BUY, price=bid if buy else ask,
                                  deviation=20, magic=MAGIC, comment=("paperlab " + why)[:30], type_filling=fill))
            if r is not None and r.retcode == m.TRADE_RETCODE_DONE:
                return True
        self.last_error = f"close failed {m.last_error()}"
        return False

    def closed_info(self, ticket):
        m = self.m
        deals = m.history_deals_get(position=ticket) or []
        outs = [d for d in deals if d.entry == m.DEAL_ENTRY_OUT]
        if not outs:
            return None
        d = outs[-1]
        why = "stop" if d.reason == m.DEAL_REASON_SL else "target" if d.reason == m.DEAL_REASON_TP else "manual/time"
        return dict(price=float(d.price), pnl=float(sum(x.profit + x.commission + x.swap for x in deals)),
                    time=int(d.time) - self.off, why=why)

    def wait(self):
        time.sleep(5)
        return True


class FakeBroker:
    """Replays data/paxgusd_*.csv candle by candle. Mechanics test only, NOT a strategy result."""
    mode = "REPLAY TEST"

    def __init__(self, cfg, spread=0.15, start=60, balance=116.0):
        sys.path.insert(0, HERE)
        import lab
        lab.init("paxgusd")
        self.b = {tf: lab.load(tf) for tf in SECS}
        self.idx, self.spread, self.bal, self.pos, self.done, self.n = start, spread, balance, [], {}, 1000
        self.min_lot, self.cfg = 0.01, cfg

    def describe(self):
        return f"{self.mode} fake account balance {self.bal:.2f} USD (candles {len(self.b['5m'])})"

    def now(self):
        return self.b["5m"][self.idx]["ts"] + 300

    def rates(self, tf, n):
        return [x for x in self.b[tf] if x["ts"] + SECS[tf] <= self.now()][-n:]

    def tick(self):
        c = self.b["5m"][self.idx]["c"]
        return c - self.spread / 2, c + self.spread / 2

    def balance(self):
        return self.bal

    def positions(self):
        return [dict(p) for p in self.pos]

    def risk(self, side, entry, stop, lot):
        return abs(entry - stop) * lot * 100

    def open(self, side, lot, sl, tp):
        bid, ask = self.tick()
        self.n += 1
        p = dict(ticket=self.n, side=side, price=ask if side == "long" else bid, sl=sl, tp=tp, lot=lot, time=self.now())
        self.pos.append(p)
        return dict(ticket=self.n, price=p["price"])

    def _finish(self, p, price, why, ts):
        pnl = ((price - p["price"]) if p["side"] == "long" else (p["price"] - price)) * p["lot"] * 100
        self.bal += pnl
        self.done[p["ticket"]] = dict(price=price, pnl=pnl, time=ts, why=why)
        self.pos.remove(p)

    def close(self, ticket, why=""):
        for p in list(self.pos):
            if p["ticket"] == ticket:
                bid, ask = self.tick()
                self._finish(p, bid if p["side"] == "long" else ask, "manual/time", self.now())
        return True

    def closed_info(self, ticket):
        return self.done.get(ticket)

    def wait(self):
        self.idx += 1
        if self.idx >= len(self.b["5m"]):
            return False
        bar = self.b["5m"][self.idx]
        for p in list(self.pos):  # stop checked before target (conservative)
            if p["side"] == "long":
                if bar["l"] <= p["sl"]: self._finish(p, p["sl"], "stop", bar["ts"] + 300)
                elif bar["h"] >= p["tp"]: self._finish(p, p["tp"], "target", bar["ts"] + 300)
            else:
                if bar["h"] >= p["sl"]: self._finish(p, p["sl"], "stop", bar["ts"] + 300)
                elif bar["l"] <= p["tp"]: self._finish(p, p["tp"], "target", bar["ts"] + 300)
        return True
