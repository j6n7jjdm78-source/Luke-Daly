"""Copies every future call-out: channel post -> checks -> buy -> exit rules. Same code for paper and live; only the executor differs."""
import json, os, time
from .rules import ExitRules, simulate
from .risk import Risk, Refused, killed, sell_all_requested
from .safety import check_sell_route, check_mint, Unsafe
from .executor import LAMPORTS
from . import notify

HERE = os.path.dirname(os.path.abspath(__file__))


class Trader:
    def __init__(self, cfg, executor, risk, seen, journal_path=None, pos_path=None, send=None, clock=time.time, live_gate=None):
        self.cfg, self.ex, self.risk, self.seen, self.clock = cfg, executor, risk, seen, clock
        self.journal_path = journal_path or os.path.join(HERE, "state", "trades.jsonl")
        self.pos_path = pos_path or os.path.join(HERE, "state", "positions.json")
        self.send = send or (lambda text: None)          # private owner notifications
        self.live_gate = live_gate                        # callable(sig) -> raises gate.GateError; used in live mode
        ex = cfg["exit"]
        self.rules = ExitRules(tp=[tuple(t) for t in ex["tp"]], stop=ex["stop"], trail_activate=ex["trail_activate"],
                               trail_pct=ex["trail_pct"], time_stop_s=ex["time_stop_s"])
        try:
            self.pos = json.load(open(self.pos_path))
        except Exception:
            self.pos = {}

    # ---- persistence
    def _journal(self, **kw):
        os.makedirs(os.path.dirname(self.journal_path), exist_ok=True)
        with open(self.journal_path, "a") as f:
            f.write(json.dumps({"ts": round(self.clock(), 3), "mode": "live" if self.ex.live else "paper", **kw}) + "\n")

    def _save_pos(self):
        tmp = self.pos_path + ".tmp"; json.dump(self.pos, open(tmp, "w")); os.replace(tmp, self.pos_path)

    def _skip(self, sig, reason):
        self._journal(event="skip", mint=sig["mint"], reason=reason, holds=sig["holds"])
        self.send(f"Skipped {sig['mint'][:6]}…: {reason}")
        if sig["holds"]:
            self.send(f"URGENT: a call-out says 'I hold this.' but the wallet did NOT buy {sig['mint']}: {reason}. Edit or delete that post.")

    # ---- entry
    def on_signal(self, sig):
        if not self.seen.is_new(sig):
            return "duplicate"
        self.seen.mark(sig)                               # mark first: a crash mid-buy must never lead to a second buy
        t0 = self.clock()
        if self.ex.live:
            if not sig["holds"]:
                open(os.path.join(os.path.dirname(HERE), "STOP"), "w").close()
                self._journal(event="halt", mint=sig["mint"], reason="call lacks 'I hold this.'")
                self.send(f"LIVE HALTED: call {sig['mint']} does not say 'I hold this.' No buy; STOP created.")
                return "halted"
            if self.live_gate:
                try: self.live_gate(sig)
                except Exception as e:
                    self._skip(sig, f"live gate: {e}"); return "skipped"
        size = self.cfg["sizing"]["max_per_trade_sol"]
        try:
            self.risk.check_buy(sig["message_id"], size, self.ex.wallet_sol())
            check_mint(self.ex.mint_info(sig["mint"]))
            bq = self.ex.quote_buy(sig["mint"], size)
            sq = self.ex.quote_sell(sig["mint"], int(bq["outAmount"]))
            rt = check_sell_route(bq, sq, int(size * LAMPORTS), self.cfg)
        except (Refused, Unsafe) as e:
            self._skip(sig, str(e)); return "skipped"
        except Exception as e:                            # network/shape errors: fail closed
            self._skip(sig, f"error {type(e).__name__}"); return "skipped"
        fill = self.ex.buy(sig["mint"], size, bq)
        self.risk.record_buy(sig["message_id"], size)
        self.pos[sig["mint"]] = {"entry_ts": self.clock(), "size_sol": size, "tokens": fill["tokens"], "hist": [],
                                 "done": 0, "message_id": sig["message_id"]}
        self._save_pos()
        lat = self.clock() - t0
        self._journal(event="buy", mint=sig["mint"], size_sol=size, tokens=fill["tokens"], roundtrip_loss_pct=round(rt, 2), latency_s=round(lat, 3))
        self.send(f"{'LIVE' if self.ex.live else 'PAPER'} bought {sig['mint'][:6]}… {size} SOL (round-trip loss {rt:.1f}%, {lat:.1f}s)")
        return "bought"

    # ---- exits
    def tick(self):
        """Mark every open position and apply the exit rules. Re-simulates the whole price history each tick, so partial exits are
        executed exactly once (only events beyond `done` are acted on)."""
        sell_all = sell_all_requested()
        for mint, p in list(self.pos.items()):
            val = self.ex.mark(mint, p["tokens"])
            now = self.clock() - p["entry_ts"]
            m = 0.0 if val is None else val / p["size_sol"]       # no sell route: treat as worthless (conservative)
            p["hist"].append((now, m, m, m, m))
            res = simulate(p["hist"], self.rules) if not sell_all else None
            if sell_all:
                self.ex.sell(mint, p["tokens"], 1.0)
                self._close(mint, p, (m - 1) * p["size_sol"], False, "sellall"); continue
            for ts, px, frac, why in res.exits[p["done"]:]:
                self.ex.sell(mint, p["tokens"], frac)
                self._journal(event="exit", mint=mint, reason=why, price_mult=px, fraction=frac)
                self.send(f"{'LIVE' if self.ex.live else 'PAPER'} {why} {mint[:6]}… {frac:.0%} at {px:.2f}x")
            p["done"] = len(res.exits)
            if res.held <= 1e-9:
                self._close(mint, p, (res.multiple - 1) * p["size_sol"], res.rugged, "closed")
        self._save_pos()

    def _close(self, mint, p, pnl, rugged, why):
        self.risk.record_close(pnl, rugged)
        self._journal(event="close", mint=mint, pnl_sol=round(pnl, 6), rugged=rugged, reason=why)
        self.send(f"{'LIVE' if self.ex.live else 'PAPER'} closed {mint[:6]}… P&L {pnl:+.4f} SOL")
        self.pos.pop(mint, None)
