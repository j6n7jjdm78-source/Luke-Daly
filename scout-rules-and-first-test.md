# Scout rules and first Lab test (XAUUSD, paper only)

All numbers below are STARTING VALUES to test, not facts. Lab changes one at a time and logs each test.

## Facts used (from MT5 demo specs)
- Contract size 100 oz, min lot 0.01 (= 1 oz), so $1 move = $1 P&L. 1 point = $0.01.
- Risk 3% of EUR 100 = EUR 3, about $3.5 (use the live EUR/USD rate). Max stop distance = risk in USD / 1 oz = about $3.50.
- Spread about $0.15 (floating). Swap makes overnight holding costly: close by session end.

## Scout: how levels are drawn (no eyeballing)
1. Timeframe for levels: 1h chart, lookback 120 bars (5 trading days).
2. Pivot high/low: a bar whose high (low) is the highest (lowest) of 3 bars before and 3 bars after.
3. Cluster pivots within $1.50 of each other into one level (level = average of the cluster).
4. A level is valid with 3 or more pivot touches in the lookback.
5. Zone = level plus/minus 0.25 x ATR(14) on the 15m chart.
6. Recompute the list at 00:00 UTC and on each new 1h close. Freeze levels while a trade is open.
7. Keep only the 3 valid levels nearest to current price.

## Setup A: rejection bounce (the first rule to test)
- Trigger: on a closed 5m bar, the wick enters a zone and the bar closes back outside it on the same side (support: close above the zone; resistance: close below).
- Entry: next bar open (simulated at the ask for buys, bid for sells).
- Stop: beyond the wick extreme plus $0.30 buffer.
- Max stop: $3.50 including spread. If the stop is wider, SKIP the trade (Shield blocks; lot cannot go below 0.01).
- Target: 1.5R or the next valid level, whichever is nearer.
- Exit: stop, target, or forced close at 16:00 UTC. No overnight holds.
- Filters: trade only 07:00 to 16:00 UTC; spread at entry at most $0.30; no entries 30 minutes either side of high-impact USD news; max 10 trades a day; stop after 2 straight losses or 6% daily loss.
- Direction: both. Long and short are logged separately (short swap is cheaper).

## Setup B (later): break and retest
Only after A has been tested. Not built yet.

## Lab: first test plan
1. Data: M5 and M1 XAUUSD history exported from desktop MT5 (Tools > History Center, or the Python MetaTrader5 package on Windows). Log source and download time in data/sources.md. I cannot download it from this container; add the CSV to a data/ folder in this repo. Need at least 12 months; demo history may be shorter, and then results are labeled low confidence.
2. Costs in: use the recorded spread per bar if present, else $0.15 with a stress test at $0.30; slippage $0.10 per side, doubled in stress; commission 0 on demo (flag as unknown for any live account).
3. Out of sample: tune on 6 months, test on the next 2 months, roll forward. Report only the combined test windows.
4. Baselines: random entries with the same stops, targets and hours; and doing nothing. Setup A must beat the random baseline after costs.
5. Robustness: zone width, min touches (2, 3, 4), lookback (60, 120, 240), buffer, target (1, 1.5, 2R). Nearby values must also be profitable.
6. Skipped trades: count how many setups were skipped for a stop wider than $3.50 and report the share. If most setups are skipped, drop the 5m timeframe or raise the account size.
7. Review 20 trades by hand on a chart.
8. Pass bar: 50 or more out-of-sample trades, profitable after costs, beats random baseline, max drawdown within 6% daily and 15% total limits. Anything else is a fail, written to the graveyard.

## Strategy card
```
S/R REJECTION BOUNCE (XAUUSD 5m, levels from 1h): fade a failed touch of a validated level
- Edge: stops cluster beyond levels; a failed break leaves trapped traders to unwind (hypothesis, untested)
- Rules: entry next bar after wick-in/close-out, stop beyond wick +$0.30, size 0.01, target 1.5R or next level
- Results: [return], [max drawdown], [trades]  (not run yet)
- Walk-forward: [not run yet]
WHY THIS COULD FAIL: the $0.15 spread plus slippage eats the edge on tight stops; levels drawn from pivots may not hold; stops under $3.50 get hit by normal gold noise; demo fills are better than live.
```
