# Market Signal Scanner (Gold / BTC / ETH)

Scans XAUUSD, BTCUSD and ETHUSD and sends BUY/SELL signals with entry, stop-loss and take-profit.
**Signals only - it never places trades.**

## Setup
```
pip install -r requirements.txt
cp .env.example .env      # add Telegram bot token + chat id (optional)
python -m scanner.main            # runs continuously
python -m scanner.main --once     # single scan
```

## Data sources
- **MetaTrader 5** (Windows only - the `MetaTrader5` package doesn't run on Linux/Mac): open and log in to your MT5 terminal, then run the scanner. Edit symbol names in `scanner/config.py` to match your broker (e.g. `XAUUSDm`).
- **Public feeds** (any OS): Binance for BTC/ETH, Yahoo gold futures (GC=F) for gold. Used automatically when MT5 isn't available (`--source public`).

## Strategy (scanner/strategy.py)
1. **Trend (15m + 1h):** both timeframes must agree - EMA20 vs EMA50, price vs EMA50, and EMA50 slope.
2. **Support/resistance:** confirmed swing highs/lows from 1h (weighted double) and 15m are clustered into zones; the touch count is the zone's strength (`--min-touches`, default 3).
3. **Signal on the last closed 15m bar:**
   - Uptrend: price dips into a support zone and rejects it (bullish bar, closes back above, lower wick) -> **BUY**
   - Downtrend: price rallies into a resistance zone and rejects it -> **SELL**
4. **Risk:** SL just beyond the zone (+0.3 ATR), TP at the next opposing zone (or 2R if none); alerts only if RR >= 1.5. 

Only closed bars and confirmed pivots are used, so there's no look-ahead. All signals are logged to `signals.csv`.

## Important
This is a starting point, not a proven edge. Backtest and paper-trade before risking money. Not financial advice.
