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
Scores 5 conditions per direction: price vs EMA200, EMA20/50 alignment, 4h trend, MACD momentum, RSI zone.
Signal fires on a closed bar when score >= 3 (`--min-score`) and a fresh MACD/EMA20 trigger occurs.
SL = 1.5x ATR, TP = 3x ATR (1:2 R:R). Cooldown prevents repeat alerts. All signals are logged to `signals.csv`.

## Important
This is a starting point, not a proven edge. Backtest and paper-trade before risking money. Not financial advice.
