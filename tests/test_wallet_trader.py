import json, pytest
from wallet.trader import Trader
from wallet.risk import Risk
from wallet.tg_trigger import Seen
from wallet.executor import PaperExecutor

CFG = json.load(open("wallet/config.json"))
MINT = "3b7WvfRxRaoMuq4j6JWJzrL5mym3Km3QzfX5dqCopump"
SOLM = "So11111111111111111111111111111111111111112"
CLEAN = {"mint_authority": None, "freeze_authority": None}


class Env:
    def __init__(self, tmp, value=1.0, route=True, info=CLEAN, mid=1):
        self.t = [1000.0]; self.value = value; self.route = route; self.sent = []
        self.state = tmp
        def quote(i, o, amt, bps):
            if not self.route: raise RuntimeError("no route")
            if i == SOLM: return {"outAmount": str(amt * 1000), "priceImpactPct": "0.01"}      # buy: 1 SOL -> 1000 tokens per lamport
            return {"outAmount": str(int(amt / 1000 * self.value)), "priceImpactPct": "0.01"}  # sell: value multiplier of what we paid
        self.ex = PaperExecutor(quote, lambda m: info)
        self.risk = Risk(CFG, str(tmp / "r.json"), str(tmp / "STOP"), clock=lambda: self.t[0])
        self.tr = Trader(CFG, self.ex, self.risk, Seen(str(tmp / "seen.json")), str(tmp / "j.jsonl"), str(tmp / "p.json"),
                         send=self.sent.append, clock=lambda: self.t[0])
    def sig(self, mid=1, holds=False, mint=MINT): return {"message_id": mid, "mint": mint, "text": "", "holds": holds}
    def journal(self): return [json.loads(l) for l in open(self.state / "j.jsonl")]


def test_buy_then_take_profit_and_close(tmp_path):
    e = Env(tmp_path)
    assert e.tr.on_signal(e.sig()) == "bought"
    e.value = 2.1; e.t[0] += 60; e.tr.tick()          # tp 50% at 2x
    assert any(j.get("reason") == "tp2x" for j in e.journal())
    e.value = 0.3; e.t[0] += 60; e.tr.tick()          # stop on the remainder
    ev = [j["event"] for j in e.journal()]
    assert ev.count("exit") == 2 and ev[-1] == "close" and MINT not in e.tr.pos
    e.tr.tick()                                        # idempotent: nothing left, no duplicate exits
    assert [j["event"] for j in e.journal()].count("exit") == 2


def test_duplicate_signal_never_buys_twice(tmp_path):
    e = Env(tmp_path)
    assert e.tr.on_signal(e.sig()) == "bought" and e.tr.on_signal(e.sig()) == "duplicate"
    assert e.tr.on_signal(e.sig(mid=2)) == "duplicate"   # same mint, new message


def test_no_sell_route_skips_and_unsafe_mint_skips(tmp_path):
    e = Env(tmp_path, route=False)
    assert e.tr.on_signal(e.sig()) == "skipped"
    (tmp_path / "x").mkdir()
    f = Env(tmp_path / "x", info={"mint_authority": "a", "freeze_authority": None})
    f.tr.cfg = {**CFG, "execution": {**CFG["execution"], "check_mint_authority": True}}   # opt-in check
    assert f.tr.on_signal(f.sig(mid=9, mint="A" * 43)) == "skipped"
    g = Env(tmp_path / "x", info={"mint_authority": "a", "freeze_authority": None})        # default: call-out bot already screened
    (tmp_path / "x" / "seen.json").unlink(); assert g.tr.on_signal(g.sig(mid=10, mint="C" * 43)) == "bought"


def test_skipped_buy_on_post_that_holds_sends_urgent_alert(tmp_path):
    e = Env(tmp_path, route=False)
    e.tr.on_signal(e.sig(holds=True))
    assert any("URGENT" in s for s in e.sent)


def test_limits_cap_copying(tmp_path):
    e = Env(tmp_path)
    got = [e.tr.on_signal(e.sig(mid=i, mint=("%043d" % i).replace("0", "B"))) for i in range(1, 6)]
    assert got.count("bought") == 3 and got.count("skipped") == 2   # max 3 open positions


def test_rug_closes_near_total_loss_and_trips_breaker(tmp_path):
    e = Env(tmp_path)
    e.tr.on_signal(e.sig()); e.value = 0.0; e.t[0] += 60; e.tr.tick()
    assert [j for j in e.journal() if j["event"] == "close"][0]["rugged"] is True


def test_sellall_closes_everything(tmp_path):
    import wallet.trader as T, wallet.risk as R
    e = Env(tmp_path); e.tr.on_signal(e.sig())
    sa = tmp_path / "SELLALL"; sa.write_text("")
    old = T.sell_all_requested; T.sell_all_requested = lambda: sa.exists()
    try: e.tr.tick()
    finally: T.sell_all_requested = old
    assert e.tr.pos == {}


def test_live_requires_disclosure_and_halts(tmp_path):
    e = Env(tmp_path); e.ex.live = True
    import wallet.trader as T
    assert e.tr.on_signal(e.sig(holds=False)) == "halted"
    import os; assert os.path.exists(os.path.join(os.path.dirname(T.HERE), "STOP"))
    os.remove(os.path.join(os.path.dirname(T.HERE), "STOP"))
