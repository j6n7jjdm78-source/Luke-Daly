"""Symbols and settings. Edit SYMBOLS to match your broker's names in MT5."""
import os
from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str          # label used in alerts
    mt5: str           # symbol name in your MetaTrader terminal (brokers differ: XAUUSD, XAUUSDm, BTCUSD...)
    binance: str = ""  # fallback feed (BTC/ETH)
    kraken: str = ""   # public feed (BTC/ETH), works from cloud servers
    yahoo: str = ""    # fallback feed (gold futures)


SYMBOLS = [
    Symbol("GOLD", mt5="XAUUSD", yahoo="GC=F"),
    Symbol("BTC", mt5="BTCUSD", binance="BTCUSDT", kraken="XBTUSD"),
    Symbol("ETH", mt5="ETHUSD", binance="ETHUSDT", kraken="ETHUSD"),
]


@dataclass
class Settings:
    timeframe: str = "15m"         # entry timeframe (trend checked on 15m + 1h)
    htf: str = "1h"                # higher timeframe: trend + main S/R levels
    poll_seconds: int = 60
    min_touches: int = 3           # pivot touches needed for a level to count as S/R
    min_rr: float = 1.5            # minimum reward:risk to alert
    cooldown_bars: int = 6         # don't repeat same-direction signal within N bars
    source: str = os.getenv("DATA_SOURCE", "auto")  # auto | mt5 | public
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat: str = os.getenv("TELEGRAM_CHAT_ID", "")
    log_file: str = "signals.csv"
    symbols: list = field(default_factory=lambda: SYMBOLS)
