# Data sources
| File | Source | What | Fetched (UTC) | Notes |
|---|---|---|---|---|
| data/paxgusd_5m.csv, _15m.csv, _1h.csv | Kraken public API OHLC, pair PAXGUSD (api.kraken.com) | PAXG/USD candles, a gold-backed token (1 token = 1 oz) used as a PROXY for XAUUSD | see bot/fetch_gold.py output; run again to append | Last forming candle dropped. Kraken returns only the latest 720 candles per timeframe (5m about 2.5 days, 1h about 30 days). History grows only by running the script regularly. |

Known differences from MT5 XAUUSD: trades 24/7 including weekends (CFD closes), own spread (about $0.36 at one sampling vs about $0.15 on the demo), small price gap to spot gold. Treat backtests on this proxy as low confidence.
