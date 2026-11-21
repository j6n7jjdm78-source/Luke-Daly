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
