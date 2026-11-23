# Wallet bot backtest

13 calls; 10 with candle history, rest bounded from calls.csv (conservative).
Multiples are per 1.0 SOL staked equally per call, after 1% per-side cost. n is tiny: treat as sanity check, not an edge.

| rule | latency s | mean x | median x | win% | worst x | mean excl. best call | no-candle calls |
|---|---|---|---|---|---|---|---|
| hold (no rules) | 0 | 0.34 | 0.32 | 8 | 0.00 | 0.28 | 3 |
| hold (no rules) | 60 | 0.35 | 0.33 | 8 | 0.00 | 0.28 | 3 |
| hold (no rules) | 180 | 0.34 | 0.30 | 8 | 0.00 | 0.27 | 3 |
| hold (no rules) | 300 | 0.34 | 0.32 | 8 | 0.00 | 0.28 | 3 |
| tp2x all | 0 | 0.55 | 0.32 | 23 | 0.00 | 0.43 | 3 |
| tp2x all | 60 | 0.56 | 0.33 | 23 | 0.00 | 0.44 | 3 |
| tp2x all | 180 | 0.55 | 0.31 | 23 | 0.00 | 0.44 | 3 |
| tp2x all | 300 | 0.56 | 0.32 | 23 | 0.00 | 0.44 | 3 |
| tp1.5x all | 0 | 0.58 | 0.34 | 31 | 0.00 | 0.51 | 3 |
| tp1.5x all | 60 | 0.61 | 0.35 | 31 | 0.00 | 0.54 | 3 |
| tp1.5x all | 180 | 0.61 | 0.36 | 31 | 0.00 | 0.54 | 3 |
| tp1.5x all | 300 | 0.62 | 0.36 | 31 | 0.00 | 0.54 | 3 |
| stop0.6 only | 0 | 0.48 | 0.56 | 8 | 0.00 | 0.42 | 3 |
| stop0.6 only | 60 | 0.48 | 0.56 | 8 | 0.00 | 0.42 | 3 |
| stop0.6 only | 180 | 0.48 | 0.56 | 8 | 0.00 | 0.42 | 3 |
| stop0.6 only | 300 | 0.48 | 0.56 | 8 | 0.00 | 0.42 | 3 |
| stop0.7 + tp2x | 0 | 0.64 | 0.66 | 15 | 0.00 | 0.53 | 3 |
| stop0.7 + tp2x | 60 | 0.65 | 0.66 | 15 | 0.00 | 0.54 | 3 |
| stop0.7 + tp2x | 180 | 0.54 | 0.66 | 8 | 0.00 | 0.49 | 3 |
| stop0.7 + tp2x | 300 | 0.54 | 0.66 | 8 | 0.00 | 0.49 | 3 |
| stop0.6 + tp2x half + trail | 0 | 0.56 | 0.56 | 15 | 0.00 | 0.47 | 3 |
| stop0.6 + tp2x half + trail | 60 | 0.60 | 0.56 | 15 | 0.00 | 0.47 | 3 |
| stop0.6 + tp2x half + trail | 180 | 0.48 | 0.56 | 8 | 0.00 | 0.42 | 3 |
| stop0.6 + tp2x half + trail | 300 | 0.60 | 0.56 | 15 | 0.00 | 0.47 | 3 |
| stop0.5 + tp3x half + trail | 0 | 0.59 | 0.47 | 15 | 0.00 | 0.41 | 3 |
| stop0.5 + tp3x half + trail | 60 | 0.58 | 0.47 | 15 | 0.00 | 0.41 | 3 |
| stop0.5 + tp3x half + trail | 180 | 0.41 | 0.47 | 8 | 0.00 | 0.35 | 3 |
| stop0.5 + tp3x half + trail | 300 | 0.58 | 0.47 | 15 | 0.00 | 0.41 | 3 |
| stop0.6 + tp2x + time 1h | 0 | 0.78 | 0.90 | 31 | 0.00 | 0.72 | 3 |
| stop0.6 + tp2x + time 1h | 60 | 0.76 | 0.88 | 31 | 0.00 | 0.71 | 3 |
| stop0.6 + tp2x + time 1h | 180 | 0.70 | 0.85 | 23 | 0.00 | 0.65 | 3 |
| stop0.6 + tp2x + time 1h | 300 | 0.79 | 0.92 | 38 | 0.00 | 0.71 | 3 |
| stop0.6 + tp2x + time 4h | 0 | 0.75 | 0.56 | 31 | 0.00 | 0.64 | 3 |
| stop0.6 + tp2x + time 4h | 60 | 0.75 | 0.56 | 31 | 0.00 | 0.65 | 3 |
| stop0.6 + tp2x + time 4h | 180 | 0.64 | 0.56 | 23 | 0.00 | 0.57 | 3 |
| stop0.6 + tp2x + time 4h | 300 | 0.75 | 0.56 | 31 | 0.00 | 0.64 | 3 |

## Data coverage per call
| id | token | status | candles | first | last |
|---|---|---|---|---|---|
| 1 | JINGYU | open | 1977 | 1795266480 | 1795409160 |
| 2 | Bigfoot | hit4x | 2000 | 1795272720 | 1795409220 |
| 3 | NEX Ai | rugged | 0 | - | - |
| 4 | ANT | rugged | 0 | - | - |
| 5 | Dandelion | rugged | 0 | - | - |
| 6 | PATRICK | open | 1489 | 1795291740 | 1795409100 |
| 7 | HUSS | open | 1034 | 1795322400 | 1795409220 |
| 8 | SIDOOR | open | 1214 | 1795333620 | 1795409280 |
| 9 | CATEMAS | open | 1168 | 1795334340 | 1795409160 |
| 10 | CORONA | open | 863 | 1795334640 | 1795408680 |
| 11 | FIREBALL | open | 493 | 1795343760 | 1795409100 |
| 12 | HIPPO | hit1.5x | 786 | 1795346100 | 1795409040 |
| 13 | testicles | open | 332 | 1795351740 | 1795407240 |
