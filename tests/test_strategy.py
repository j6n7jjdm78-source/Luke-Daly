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
        assert t["res"] != "SL" or (t["hit"] == 0 and t["pips"] < 0)
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
    ev = tracker.resolve(t, _candles([(3573.5, 3570), (3578.5, 3572), (3589, 3578)]), run_thr=2.5)
    assert ev[0].startswith("Trade active and running")
    assert ev[1].startswith("HIT TP1 ✅ +80PIPS")
    assert [e.split()[1] for e in ev[2:5]] == ["TP2", "TP3", "ALL"][:3] or ev[-1] == "HIT ALL TP ✅"
    assert t["closed"] and t["hit"] == 3


def test_tracker_sl_first_on_same_candle_and_be_after_tp1():
    from scanner import tracker
    t = _trade()
    ev = tracker.resolve(t, _candles([(3580, 3560)]), run_thr=2.5)       # touches TP1 and SL in one candle
    assert ev[0].startswith("SL HIT ❌ -")
    t = _trade()
    ev = tracker.resolve(t, _candles([(3579, 3572), (3575, 3573.5), (3575, 3570)]), run_thr=2.5)
    assert any(e.startswith("HIT TP1") for e in ev) and ev[-1].startswith("STOPPED AT BE") and t["closed"]


def test_message_formats_match_references():
    from scanner import notify
    t = _trade()
    from scanner.config import get_symbol
    from scanner.strategy import make_signal
    now = pd.Timestamp("2026-01-01", tz="UTC")
    g = notify.format_signal(make_signal("GOLD", "BUY", 3567, 3573, 3574, now, 3, [], get_symbol("GOLD")), 5)
    assert g.startswith("5. GOLD BUY SETUP\n\nGold Buy Zone 3573 - 3567\n\nSL : 3562\n\nTP1 : 3578\nTP2 : 3583\nTP3 : 3588\nTP4 : Hold")
    b = notify.format_signal(make_signal("BTC", "SELL", 56140, 56641, 56100, now, 3, [], get_symbol("BTC")))
    assert "DIRECTION: SELL BTCUSD" in b and "ENTRY PRICE: 56140 - 56641" in b and "❌ Stop Loss:" in b and "TP4:" in b
