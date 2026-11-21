"""Symbols and settings. Edit SYMBOLS to match your broker's names in MT5."""
import os
from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str          # label used in alerts
    mt5: str           # symbol name in your MetaTrader terminal (brokers differ: XAUUSD, XAUUSDm, BTCUSD...)
    binance: str = ""  # fallback feed (BTC/ETH)
    yahoo: str = ""    # fallback feed (gold futures)


SYMBOLS = [
    Symbol("GOLD", mt5="XAUUSD", yahoo="GC=F"),
    Symbol("BTC", mt5="BTCUSD", binance="BTCUSDT"),
    Symbol("ETH", mt5="ETHUSD", binance="ETHUSDT"),
]


@dataclass
class Settings:
    timeframe: str = "1h"          # entry timeframe: 15m, 30m, 1h, 4h
    htf: str = "4h"                # higher timeframe trend filter
    poll_seconds: int = 60
    min_score: int = 3             # signal strength needed (max 5)
    sl_atr: float = 1.5            # stop distance in ATR
    tp_atr: float = 3.0            # target distance in ATR (RR = 2)
    cooldown_bars: int = 6         # don't repeat same-direction signal within N bars
    source: str = os.getenv("DATA_SOURCE", "auto")  # auto | mt5 | public
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat: str = os.getenv("TELEGRAM_CHAT_ID", "")
    log_file: str = "signals.csv"
    symbols: list = field(default_factory=lambda: SYMBOLS)
