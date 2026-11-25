"""Safety tests (no MT5 needed). Run: python3 gold/test_bot.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paper_bot as pb, lab
from broker import FakeBroker

cfg = json.load(open(os.path.join(pb.HERE, "config.json")))
t = tempfile.mkdtemp()
pb.S.update(incidents=t + "/inc.md", log=t + "/l", alerts=t + "/a", state=t + "/s", journal=t + "/j.csv", heart=t + "/h")
pb.DATA = t

def broker():
    b = FakeBroker(cfg); b.idx = 400; return b

def st(**k):
    s = pb.load_state(); s.update(day=pb.utc(400).date().isoformat(), day_start=116.0, peak=116.0); s.update(k); return s

def sh(b, s, side="long", entry=3600.0, stop=3598.0, bal=116.0, hour_ok=True):
    bars = b.rates("5m", 5); bid, ask = b.tick()
    c = dict(cfg); 
    if hour_ok: c["hour_from"], c["hour_to"] = 0, 24
    return pb.shield(b, c, s, bars, side, entry, stop, bid, ask, bal)

b = broker()
assert sh(b, st()) is None, "valid order should be approved"
assert "risk" in sh(b, st(), stop=3590.0), "wide stop must be blocked (risk > 3%)"
assert "wrong side" in sh(b, st(), stop=3601.0)
assert "tight" in sh(b, st(), stop=3599.8)
assert "loss streak" in sh(b, st(loss_streak=2))
assert "max trades" in sh(b, st(trades_today=10))
assert "daily loss" in sh(b, st(), bal=108.0)
assert "halted" in sh(b, st(halted=True))
hr = pb.utc(b.now()).hour; c = dict(cfg)
c["hour_from"], c["hour_to"] = (hr + 1, hr + 2) if hr < 12 else (hr - 2, hr - 1)
bid, ask = b.tick()
assert "outside" in pb.shield(b, c, st(), b.rates("5m", 5), "long", 3600.0, 3598.0, bid, ask, 116.0)
b.spread = 0.5; assert "spread" in sh(b, st()); b.spread = 0.15
b.idx = 400; fresh = b.rates("5m", 5); b.idx += 0
class Stale(FakeBroker):
    def now(self): return super().now() + 1000
    def rates(self, tf, n): return [x for x in self.b[tf] if x["ts"] + {"5m": 300, "15m": 900, "1h": 3600}[tf] <= FakeBroker.now(self)][-n:]
s2 = Stale(cfg); s2.idx = 400
assert "stale" in sh(s2, st()), "stale feed must block"
print("shield tests ok")

# kill switch: balance 15% below peak halts and closes everything
b = broker(); p = b.open("long", 0.01, 3500.0, 3700.0)
s = st(peak=200.0, open={})
pb.cycle(b, cfg, s)
assert s["halted"] and not b.positions(), "kill switch must halt and flatten"
print("kill switch ok")

# missing stop is closed immediately
b = broker(); b.open("long", 0.01, 0.0, 3700.0)
s = st(); s["open"] = {str(b.n): dict(market="XAUUSD", side="long", time="x", price=1, lot=.01, stop=0, target=1, risk=1, reason="t")}
pb.cycle(b, cfg, s)
assert not b.positions(), "position without stop must be closed"
print("missing stop ok")

# repeated errors halt with exit code 2
class Boom(FakeBroker):
    def rates(self, tf, n): raise RuntimeError("feed down")
sys.argv = ["x", "--replay"]
orig = pb.FakeBroker; pb.FakeBroker = Boom
assert pb.main() == 2, "3 errors must halt with exit code 2"
pb.FakeBroker = orig
print("error halt ok")
print("ALL TESTS PASSED")
