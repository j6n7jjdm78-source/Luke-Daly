import numpy as np, pandas as pd
from scanner.strategy import evaluate, indicators


def synth(n=400, drift=0.002, seed=1, freq="1h"):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(drift * 0.3 + rng.normal(0, 0.004, n)))
    idx = pd.date_range("2025-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": c, "high": c * 1.002, "low": c * 0.998, "close": c, "volume": 1.0}, index=idx)


def test_indicators_have_no_nan_tail():
    assert not indicators(synth()).iloc[-1].isna().any()


def test_signals_are_directionally_valid():
    found = 0
    for seed in range(8):
        df, htf = synth(seed=seed), synth(seed=seed, freq="4h")
        for i in range(250, 399):
            s = evaluate("X", df, htf, min_score=3, i=i)
            if s:
                found += 1
                assert (s.sl < s.price < s.tp) if s.side == "BUY" else (s.tp < s.price < s.sl)
    assert found > 0
