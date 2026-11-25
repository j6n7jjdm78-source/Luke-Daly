# First check: Setup A on gold proxy (PAXG/USD, Kraken). CODE CHECK ONLY, NOT A STRATEGY RESULT.

Data: 5m = 60 hours, 15m = 180 hours, 1h = 719 hours, all ending 2026-11-23 13:00 UTC. Proxy, not MT5 XAUUSD.
Costs: spread 0.15 / 0.36, slippage 0.10 per side (stress 0.20). Commission 0 (unknown). 0.01 lot = 1 oz, so USD P&L = price move.
Attempts so far: 3 parameter settings (touches 3/cluster 1.5; touches 2/cluster 1.5; touches 2/cluster 3.0). Every extra attempt raises the bar.

| Setting | 5m trades | 15m trades | 1h trades |
|---|---|---|---|
| touches>=3, cluster 1.5 (spec) | 0 | 0 | 1 (+$1.32) |
| touches>=2, cluster 1.5 | 0 | 2 (-$3.71, both losers) | 1 (+$1.32) |
| touches>=2, cluster 3.0 | 0 | 2 (-$3.71) | 0 |

Skipped for stop wider than $3.50 (touches>=2): 12 on 15m, 3 on 1h. Many more were skipped by the 07:00-16:00 UTC filter.
Random-entry baseline (1h, 1 trade): avg -0.19 R. Meaningless at n=1.

Verdict: NO VERDICT. 0 to 2 trades is an anecdote. Need 50+ out-of-sample trades.
Finding: with the spec rules the strategy produces almost no signals on 30 days of data, nowhere near 5-10 trades a day.

Files: gold/lab.py (Scout + simulator), data/levels_latest.json, data/first_check_results.json, data/trades_*.json.
