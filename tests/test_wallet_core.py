import json, pytest
from wallet.rules import ExitRules, simulate
from wallet.risk import Risk, Refused
from wallet.gate import check_live, check_call, GateError

CFG = json.load(open("wallet/config.json"))


def c(ts, o, h, l, cl): return (ts, o, h, l, cl)
NOFEE = dict(fee_pct=0.0, stop_slip_pct=0.0)


def test_tp_then_trail():
    r = ExitRules(tp=[(2.0, 0.5)], stop=0.6, trail_activate=2.0, trail_pct=0.35, time_stop_s=None, **NOFEE)
    cs = [c(0, 1, 1.1, 0.9, 1), c(60, 1, 2.1, 1, 2.0), c(120, 2, 3.0, 2, 3.0), c(180, 3, 3, 1.5, 1.6)]
    res = simulate(cs, r)
    assert [e[3] for e in res.exits] == ["tp2x", "trail"]
    assert res.multiple == pytest.approx(0.5 * 2.0 + 0.5 * 3.0 * 0.65)


def test_stop_beats_tp_in_same_candle():
    r = ExitRules(tp=[(2.0, 1.0)], stop=0.6, trail_activate=None, time_stop_s=None, **NOFEE)
    res = simulate([c(0, 1, 2.5, 0.5, 1)], r)
    assert res.exits[0][3] == "stop"


def test_gap_down_fills_at_open_not_stop():
    r = ExitRules(stop=0.6, trail_activate=None, time_stop_s=None, **NOFEE)
    res = simulate([c(0, 1, 1, 1, 1), c(60, 0.4, 0.45, 0.35, 0.4)], r)
    assert res.multiple == pytest.approx(0.4)


def test_rug_is_near_total_loss():
    r = ExitRules(stop=0.6, trail_activate=None, time_stop_s=None, **NOFEE)
    res = simulate([c(0, 1, 1, 1, 1), c(60, 0.9, 0.9, 0.0, 0.0)], r)
    assert res.rugged and res.multiple < 0.01


def test_time_stop_and_costs():
    r = ExitRules(tp=[], stop=None, trail_activate=None, time_stop_s=120, fee_pct=0.01)
    res = simulate([c(0, 1, 1, 1, 1), c(60, 1, 1.2, 1, 1.1), c(120, 1.1, 1.2, 1, 1.15)], r)
    assert res.exits[0][3] == "time" and res.multiple == pytest.approx(1.15 * 0.99)


def test_open_position_marked_to_last_close():
    r = ExitRules(tp=[], stop=None, trail_activate=None, time_stop_s=None, fee_pct=0)
    res = simulate([c(0, 1, 1, 1, 1), c(60, 1, 1.3, 1, 1.3)], r)
    assert res.held == 1.0 and res.multiple == pytest.approx(1.3)


@pytest.fixture
def risk(tmp_path):
    t = [1_000_000.0]
    r = Risk(CFG, str(tmp_path / "r.json"), str(tmp_path / "STOP"), clock=lambda: t[0])
    r.t = t
    return r


def test_limits_trip(risk, tmp_path):
    risk.check_buy(1, 0.05, 0.3)
    with pytest.raises(Refused): risk.check_buy(1, 0.06, 0.3)        # per-trade
    with pytest.raises(Refused): risk.check_buy(1, 0.05, None)       # unknown balance
    with pytest.raises(Refused): risk.check_buy(1, 0.05, 5.0)        # wallet too large
    for i in range(3):
        risk.record_buy(i, 0.05)
    with pytest.raises(Refused): risk.check_buy(9, 0.05, 0.3)        # open positions / daily spend
    with pytest.raises(Refused): risk.check_buy(0, 0.01, 0.3)        # same call twice


def test_kill_switch(risk, tmp_path):
    (tmp_path / "STOP").write_text("")
    with pytest.raises(Refused, match="kill"): risk.check_buy(1, 0.01, 0.3)


def test_restart_does_not_reset_counters(tmp_path):
    p, s = str(tmp_path / "r.json"), str(tmp_path / "STOP")
    a = Risk(CFG, p, s, clock=lambda: 1_000_000.0); a.record_buy(1, 0.05); a.record_buy(2, 0.05); a.record_buy(3, 0.05)
    b = Risk(CFG, p, s, clock=lambda: 1_000_100.0)
    with pytest.raises(Refused): b.check_buy(4, 0.05, 0.3)


def test_daily_loss_and_breaker(risk):
    risk.record_buy(1, 0.05); risk.record_close(-0.11)
    with pytest.raises(Refused, match="loss"): risk.check_buy(2, 0.05, 0.3)
    risk.t[0] += 86400 * 2  # next day clears loss; breaker is separate
    risk.record_close(0, rugged=True); risk.record_close(0, rugged=True)
    with pytest.raises(Refused, match="breaker"): risk.check_buy(3, 0.05, 0.3)


# ---- gate
def good_review(tmp_path, name="paper_review.json", **kw):
    p = tmp_path / name
    p.write_text(json.dumps({"approved_by_owner": True, "trades": 25, "days": 8, **kw}))
    return str(p)

LIVE = {**CFG, "mode": "live", "live_from_id": 14}
ENV = {"WALLET_LIVE_CONFIRM": "1"}
CALLS = [{"id": "13", "tweet_id": "t13", "token": "OLD"}, {"id": "14", "tweet_id": "t14", "token": "NEW"}]


def tw(m): return lambda tid: m[tid]


def test_gate_passes_only_when_all_in_scope_disclosed(tmp_path):
    scope = check_live(LIVE, CALLS, tw({"t14": "NEW call\nI hold this."}), good_review(tmp_path), ENV)
    assert [x["id"] for x in scope] == ["14"]   # historical call 13 never checked / traded


def test_gate_refusals(tmp_path):
    ok = tw({"t14": "I hold this."})
    rv = good_review(tmp_path)
    with pytest.raises(GateError): check_live({**LIVE, "mode": "paper"}, CALLS, ok, rv, ENV)
    with pytest.raises(GateError): check_live(LIVE, CALLS, ok, rv, {})
    with pytest.raises(GateError): check_live({**LIVE, "live_from_id": None}, CALLS, ok, rv, ENV)
    with pytest.raises(GateError): check_live(LIVE, CALLS, ok, str(tmp_path / "nope.json"), ENV)
    with pytest.raises(GateError): check_live(LIVE, CALLS, ok, good_review(tmp_path, "low.json", trades=3), ENV)
    with pytest.raises(GateError, match="does not say"): check_live(LIVE, CALLS, tw({"t14": "no line"}), rv, ENV)

    def boom(_): raise TimeoutError()
    with pytest.raises(GateError, match="unreachable"): check_live(LIVE, CALLS, boom, rv, ENV)
    with pytest.raises(GateError, match="tweet_id"): check_call({"id": "1"}, ok)
