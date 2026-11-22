import numpy as np, pandas as pd
from scanner.strategy import evaluate, trend, find_zones, cluster


def synth(n, freq, seed, drift=0.0004, vol=0.003):
    rng = np.random.default_rng(seed)
    # oscillation around a drifting mean gives repeated swing highs/lows -> S/R zones
    t = np.arange(n)
    c = 100 * np.exp(drift * t + 0.03 * np.sin(t / 12) + np.cumsum(rng.normal(0, vol, n)) * 0.3)
    o = np.r_[c[0], c[:-1]]
    hi = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.0015, n)))
    lo = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.0015, n)))
    idx = pd.date_range("2025-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": o, "high": hi, "low": lo, "close": c, "volume": 1.0}, index=idx)


def test_cluster_groups_nearby_prices():
    z = cluster([100, 100.1, 105, 105.2, 105.1], tol=0.5)
    assert sorted(x.touches for x in z) == [2, 3]


def test_trend_detects_direction():
    up = synth(300, "1h", 1, drift=0.003, vol=0.0005)
    dn = synth(300, "1h", 1, drift=-0.003, vol=0.0005)
    assert trend(up) == 1 and trend(dn) == -1


def test_signals_valid_and_no_lookahead():
    found = 0
    for seed in range(6):
        m15, h1 = synth(1600, "15min", seed), synth(400, "1h", seed)
        for i in range(900, 1590, 3):
            s = evaluate("X", m15, h1, min_touches=2, i=i)
            if s:
                found += 1
                assert (s.sl < s.price < s.tp) if s.side == "BUY" else (s.tp < s.price < s.sl)
                # same result when future bars are removed => no look-ahead
                s2 = evaluate("X", m15.iloc[:i + 1], h1, min_touches=2, i=-1)
                assert s2 and s2.side == s.side and abs(s2.sl - s.sl) < 1e-9
    print("signals found:", found)


def test_backtest_simulation_runs_and_outcomes_valid():
    from scanner.backtest import simulate, summarize
    from scanner.config import get_symbol
    tr = []
    for seed in range(6):
        tr += simulate(get_symbol("BTC"), synth(1600, "15min", seed), synth(400, "1h", seed), min_touches=2)
    for t in tr:
        assert t["res"] in ("ALL", "SL", "BE", "timeout")
        assert t["res"] != "SL" or t["hit"] > 0 or t["pips"] < 0
    assert isinstance(summarize(tr), str)


def test_gold_levels_match_reference_layout():
    from scanner.levels import build
    from scanner.config import get_symbol
    lv = build("BUY", 3567, 3573, 3574, get_symbol("GOLD"))
    assert (lv["sl"], lv["tps"]) == (3562, [3578, 3583, 3588])
    lv = build("SELL", 3567, 3573, 3566, get_symbol("GOLD"))
    assert (lv["sl"], lv["tps"]) == (3578, [3562, 3557, 3552])


def test_btc_levels_wider_and_sell_mirrors_reference():
    from scanner.levels import build
    from scanner.config import get_symbol
    lv = build("SELL", 56140, 56641, 56100, get_symbol("BTC"))
    assert 56641 + 300 < lv["sl"] < 56641 + 450          # reference: SL 57010 (+369)
    assert 56140 - 520 < lv["tps"][0] < 56140 - 400      # reference: TP1 55674 (-466)
    steps = [lv["tps"][k] - lv["tps"][k + 1] for k in range(3)]
    assert all(190 < x < 260 for x in steps) and len(lv["tps"]) == 4


def _trade(side="BUY"):
    from scanner.config import get_symbol
    from scanner.strategy import make_signal
    from scanner import tracker
    sig = make_signal("GOLD", side, 3567, 3573, 3574 if side == "BUY" else 3566, pd.Timestamp("2026-01-01", tz="UTC"), 3,
                      [], get_symbol("GOLD"))
    return tracker.new_trade(sig, 1, 1)


def _candles(rows, start="2026-01-01 00:15"):
    idx = pd.date_range(start, periods=len(rows), freq="15min", tz="UTC")
    return pd.DataFrame([dict(open=0, close=0, high=h, low=l) for h, l in rows], index=idx)


def test_tracker_running_then_tp1_tp3_all():
    from scanner import tracker
    t = _trade()
    ev = tracker.resolve(t, _candles([(3577, 3570), (3578.5, 3572), (3589, 3578)]), run_thr=2.5)
    heads = [e.split("\n")[0] for e in ev]
    # entry 3574: running +30, TP1 3578 = +40, TP2 3583 = +90, TP3 3588 = +140 pips (pip = 0.10)
    assert heads == ["Trade active and running +30PIPS ✅", "HIT TP1 ✅ +40PIPS", "HIT TP2 ✅ +90PIPS",
                     "HIT TP3 ✅ +140PIPS", "HIT ALL TP ✅"]
    assert t["closed"] and t["hit"] == 3


def test_tracker_sl_first_on_same_candle():
    from scanner import tracker
    t = _trade()
    ev = tracker.resolve(t, _candles([(3580, 3560)]), run_thr=2.5)       # touches TP1 and SL in one candle
    assert ev[0].startswith("SL HIT ❌ -") and t["closed"]


def test_gold_stop_stays_until_tp2_then_moves_to_entry():
    from scanner import tracker
    t = _trade(); t["be_after"] = 2
    ev = tracker.resolve(t, _candles([(3579, 3572), (3575, 3573.5), (3575, 3570)]), run_thr=2.5)  # TP1 then pullback to 3570
    assert [e.split("\n")[0] for e in ev] == ["HIT TP1 ✅ +40PIPS"] and not t["closed"]            # still running, no BE
    ev = tracker.resolve(t, _candles([(3584, 3574.5), (3575, 3574)], start="2026-01-01 01:00"), run_thr=2.5)
    assert ev[0].startswith("HIT TP2") and ev[-1].startswith("STOPPED AT BE") and t["closed"]


def test_be_after_tp1_policy_and_no_be_policy():
    from scanner import tracker
    t = _trade(); t["be_after"] = 1
    ev = tracker.resolve(t, _candles([(3579, 3572), (3575, 3573.5), (3575, 3574)]), run_thr=2.5)
    assert ev[-1].startswith("STOPPED AT BE")
    t = _trade(); t["be_after"] = None
    ev = tracker.resolve(t, _candles([(3584, 3572), (3575, 3574), (3575, 3561)]), run_thr=2.5)
    assert ev[-1].startswith("SL HIT ❌")


def test_demo_suite_sequences_cover_every_path():
    from scanner import tracker
    from scanner.main import script
    from scanner.config import get_symbol
    from scanner.strategy import make_signal
    now = pd.Timestamp("2026-01-01", tz="UTC")

    from dataclasses import replace

    def run(name, side, lo, hi, price, steps, be=None):
        sym = get_symbol(name)
        if be:
            sym = replace(sym, be_after=be)
        sig = make_signal(name, side, lo, hi, price, now, 3, [], sym)
        t = tracker.new_trade(sig, 1, 1)
        thr = sym.run * (price if sym.pct else 1)
        df = pd.DataFrame(script(sig, steps, thr), index=[now + pd.Timedelta(minutes=15 * (j + 1)) for j in range(len(steps))])
        return [e.split("\n")[0].split(" +")[0] for e in tracker.resolve(t, df, thr)]

    assert run("GOLD", "BUY", 3567, 3573, 3574, ["run", "tp1", "tp2", "tp3"])[-1] == "HIT ALL TP ✅"
    assert run("GOLD", "SELL", 3590, 3596, 3589, ["run", "tp1", "back"])[-1] == "STOPPED AT BE ⚖️"
    assert run("GOLD", "BUY", 3567, 3573, 3574, ["run", "sl"])[-1].startswith("SL HIT")
    assert run("BTC", "SELL", 56140, 56641, 56100, ["run", "tp1", "tp2", "tp3", "tp4"])[-2:] == ["HIT TP4 ✅", "HIT ALL TP ✅"]
    assert run("BTC", "BUY", 56140, 56641, 56700, ["run", "tp1", "back"])[-1] == "STOPPED AT BE ⚖️"
    assert run("BTC", "SELL", 56140, 56641, 56100, ["run", "sl"])[-1].startswith("SL HIT")


def test_gold_filters_session_and_4h():
    from dataclasses import replace
    from scanner.config import get_symbol
    g = get_symbol("GOLD")
    m15, h1 = synth(1600, "15min", 3), synth(400, "1h", 3)
    base = [i for i in range(900, 1590, 2) if evaluate("GOLD", m15, h1, min_touches=2, i=i, sym=g)]
    night = [i for i in range(900, 1590, 2) if evaluate("GOLD", m15, h1, min_touches=2, i=i, sym=replace(g, session=(7, 8)))]
    assert set(night) <= set(base) and all(m15.index[i].hour == 7 for i in night)
    strict = [i for i in range(900, 1590, 2) if evaluate("GOLD", m15, h1, min_touches=2, i=i, sym=replace(g, need_4h=True, wick=0.45))]
    assert set(strict) <= set(base)


def test_message_formats_match_references():
    from scanner import notify
    t = _trade()
    from scanner.config import get_symbol
    from scanner.strategy import make_signal
    now = pd.Timestamp("2026-01-01", tz="UTC")
    g = notify.format_signal(make_signal("GOLD", "BUY", 3567, 3573, 3574, now, 3, [], get_symbol("GOLD")), 5)
    assert g.startswith("5. GOLD BUY SETUP\n\nGold Buy Zone 3573 - 3567\nCalled at : 3574\n\nSL : 3562 (-120 pips)\n\n"
                        "TP1 : 3578 (+40 pips)\nTP2 : 3583 (+90 pips)\nTP3 : 3588 (+140 pips)\nTP4 : Hold")
    b = notify.format_signal(make_signal("BTC", "SELL", 56140, 56641, 56100, now, 3, [], get_symbol("BTC")))
    assert "DIRECTION: SELL BTCUSD" in b and "ENTRY PRICE: 56140 - 56641" in b and "❌ Stop Loss:" in b and "TP4:" in b


def test_live_config_gold_btc_eth_move_stop_to_entry_after_tp1():
    from scanner.config import get_symbol
    assert all(get_symbol(n).be_after == 1 for n in ("GOLD", "BTC", "ETH")) and get_symbol("GOLD").need_4h


def test_tp1_message_announces_breakeven_only_when_it_applies():
    from scanner import tracker
    t = _trade(); t["be_after"] = 1
    ev = tracker.resolve(t, _candles([(3578.5, 3572)]), run_thr=2.5)
    assert any("Stop moved to entry (BE)" in e for e in ev if e.startswith("HIT TP1"))
    t = _trade(); t["be_after"] = None
    ev = tracker.resolve(t, _candles([(3578.5, 3572)]), run_thr=2.5)
    assert not any("Stop moved to entry" in e for e in ev)


def test_every_pip_number_is_calculated_from_the_called_price():
    """Signal lines and update messages must equal |price - entry| / pip, never hard-coded."""
    import re
    from scanner import notify, tracker
    from scanner.config import get_symbol
    from scanner.strategy import make_signal
    now = pd.Timestamp("2026-01-01", tz="UTC")
    cases = [("GOLD", "BUY", 3567, 3573, 3574), ("GOLD", "SELL", 3590, 3596, 3589),
             ("BTC", "SELL", 56140, 56641, 56100), ("BTC", "BUY", 56140, 56641, 56700),
             ("ETH", "BUY", 2900, 2915, 2920)]
    for name, side, lo, hi, price in cases:
        sym = get_symbol(name)
        sig = make_signal(name, side, lo, hi, price, now, 3, [], sym)
        text = notify.format_signal(sig)
        shown = [int(x) for x in re.findall(r"\(([+-]\d+) pips\)", text)]
        want = [round(abs(tp - price) / sym.pip) for tp in sig.tps] + [-round(abs(sig.sl - price) / sym.pip)]
        assert sorted(shown) == sorted([w for w in want if w > 0] + [w for w in want if w < 0]), (name, text)
        # every target is on the profit side, the stop on the loss side
        for tp in sig.tps:
            assert (tp > price) if side == "BUY" else (tp < price)
        assert (sig.sl < price) if side == "BUY" else (sig.sl > price)
        # update messages use the same numbers
        t = tracker.new_trade(sig, 1, 1)
        df = _candles([(max(sig.tps) if side == "BUY" else price, price if side == "BUY" else min(sig.tps))])
        ev = tracker.resolve(t, df, run_thr=1e18)
        tp_msgs = [e for e in ev if e.startswith("HIT TP")]
        for k, msg in enumerate(tp_msgs):
            assert f"+{round(abs(sig.tps[k] - price) / sym.pip)}PIPS" in msg.split("\n")[0], (name, msg)
