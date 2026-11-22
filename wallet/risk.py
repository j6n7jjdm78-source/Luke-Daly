"""Hard limits + kill switch + circuit breaker. Fail closed: any doubt -> refuse.
State is persisted to disk so a restart cannot reset the daily counters."""
import json, os, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "state", "risk.json")
STOP_FILE = os.path.join(os.path.dirname(HERE), "STOP")
SELLALL_FILE = os.path.join(os.path.dirname(HERE), "SELLALL")


class Refused(Exception):
    pass


def killed(stop_file=STOP_FILE) -> bool:
    return os.path.exists(stop_file)


def sell_all_requested(f=SELLALL_FILE) -> bool:
    return os.path.exists(f)


def _day(now=None):
    return datetime.fromtimestamp(now or time.time(), timezone.utc).strftime("%Y-%m-%d")


class Risk:
    def __init__(self, cfg, state_path=STATE, stop_file=STOP_FILE, clock=time.time):
        self.cfg, self.path, self.stop_file, self.clock = cfg, state_path, stop_file, clock
        self.s = self._load()

    def _load(self):
        try:
            return json.load(open(self.path))
        except Exception:
            return {"day": None, "spent": 0.0, "realized": 0.0, "bought_ids": [], "open": 0, "rugs": []}

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        json.dump(self.s, open(tmp, "w"))
        os.replace(tmp, self.path)

    def _roll(self):
        d = _day(self.clock())
        if self.s["day"] != d:
            self.s.update(day=d, spent=0.0, realized=0.0)

    def check_buy(self, call_id, size_sol, wallet_sol):
        """Raises Refused with the reason; returns None if the buy is allowed. Call right before signing."""
        z = self.cfg["sizing"]
        self._roll()
        if killed(self.stop_file):
            raise Refused("kill switch (STOP file) present")
        if str(call_id) in self.s["bought_ids"]:
            raise Refused(f"call {call_id} already bought")
        if not (0 < size_sol <= z["max_per_trade_sol"]):
            raise Refused(f"size {size_sol} outside per-trade limit {z['max_per_trade_sol']}")
        if self.s["spent"] + size_sol > z["max_daily_spend_sol"]:
            raise Refused("daily spend limit")
        if self.s["open"] >= z["max_open_positions"]:
            raise Refused("max open positions")
        if -self.s["realized"] >= z["max_daily_loss_sol"]:
            raise Refused("daily loss limit hit")
        if wallet_sol is None or wallet_sol > z["max_wallet_sol"]:
            raise Refused(f"wallet balance unknown or above cap {z['max_wallet_sol']} (burner must stay small)")
        cutoff = self.clock() - 86400
        if len([r for r in self.s["rugs"] if r > cutoff]) >= self.cfg["breaker"]["max_rugs_24h"]:
            raise Refused("circuit breaker: too many rugs in 24h")

    def record_buy(self, call_id, size_sol):
        self._roll()
        self.s["bought_ids"].append(str(call_id))
        self.s["spent"] += size_sol
        self.s["open"] += 1
        self._save()

    def record_close(self, pnl_sol, rugged=False):
        self._roll()
        self.s["realized"] += pnl_sol
        self.s["open"] = max(0, self.s["open"] - 1)
        if rugged:
            self.s["rugs"].append(self.clock())
        self._save()
